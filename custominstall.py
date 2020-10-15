# This file is a part of custom-install.py.
#
# custom-install is copyright (c) 2019-2020 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE.md in the root of this project.

from argparse import ArgumentParser
from os import makedirs, scandir
from os.path import dirname, join, isdir, isfile
from random import randint
from hashlib import sha256
from locale import getpreferredencoding
from pprint import pformat
from shutil import copyfile
import sys
from sys import platform, executable
from tempfile import TemporaryDirectory
from traceback import format_exception
from typing import BinaryIO, TYPE_CHECKING
import subprocess

if TYPE_CHECKING:
    from os import PathLike
    from typing import List, Union

from events import Events

from pyctr.crypto import CryptoEngine, Keyslot, load_seeddb, get_seed
from pyctr.type.cdn import CDNReader
from pyctr.type.cia import CIAReader, CIAError
from pyctr.type.ncch import NCCHSection
from pyctr.util import roundup

is_windows = platform == 'win32'

if platform == 'msys':
    platform = 'win32'

# used to run the save3ds_fuse binary next to the script
frozen = getattr(sys, 'frozen', False)
script_dir: str
if frozen:
    script_dir = dirname(executable)
else:
    script_dir = dirname(__file__)

# missing contents are replaced with 0xFFFFFFFF in the cmd file
CMD_MISSING = b'\xff\xff\xff\xff'

# the size of each file and directory in a title's contents are rounded up to this
TITLE_ALIGN_SIZE = 0x8000

# size to read at a time when copying files
READ_SIZE = 0x200000

# version for cifinish.bin
CIFINISH_VERSION = 3


# Placeholder for SDPathErrors
class SDPathError(Exception):
    pass


class InvalidCIFinishError(Exception):
    pass


def load_cifinish(path: 'Union[PathLike, bytes, str]'):
    try:
        with open(path, 'rb') as f:
            header = f.read(0x10)
            if header[0:8] != b'CIFINISH':
                raise InvalidCIFinishError('CIFINISH magic not found')
            version = int.from_bytes(header[0x8:0xC], 'little')
            count = int.from_bytes(header[0xC:0x10], 'little')
            data = {}
            for _ in range(count):
                if version == 1:
                    # ignoring the titlekey and common key index, since it's not useful in this scenario
                    raw_entry = f.read(0x30)
                    if len(raw_entry) != 0x30:
                        raise InvalidCIFinishError(f'title entry is not 0x30 (version {version})')

                    title_magic = raw_entry[0xA:0x10]
                    title_id = int.from_bytes(raw_entry[0:8], 'little')
                    has_seed = raw_entry[0x9]
                    seed = raw_entry[0x20:0x30]

                elif version == 2:
                    # this is assuming the "wrong" version created by an earlier version of this script
                    # there wasn't a version of custom-install-finalize that really accepted this version
                    raw_entry = f.read(0x20)
                    if len(raw_entry) != 0x20:
                        raise InvalidCIFinishError(f'title entry is not 0x20 (version {version})')

                    title_magic = raw_entry[0:6]
                    title_id = int.from_bytes(raw_entry[0x6:0xE], 'little')
                    has_seed = raw_entry[0xE]
                    seed = raw_entry[0x10:0x20]

                elif version == 3:
                    raw_entry = f.read(0x20)
                    if len(raw_entry) != 0x20:
                        raise InvalidCIFinishError(f'title entry is not 0x20 (version {version})')

                    title_magic = raw_entry[0:6]
                    title_id = int.from_bytes(raw_entry[0x8:0x10], 'little')
                    has_seed = raw_entry[0x6]
                    seed = raw_entry[0x10:0x20]

                else:
                    raise InvalidCIFinishError(f'unknown version {version}')

                if title_magic == b'TITLE\0':
                    data[title_id] = {'seed': seed if has_seed else None}

        return data
    except FileNotFoundError:
        # allow the caller to easily create a new database in the same place where an existing one would be updated
        return {}


def save_cifinish(path: 'Union[PathLike, bytes, str]', data: dict):
    with open(path, 'wb') as out:
        entries = sorted(data.items())

        out.write(b'CIFINISH')
        out.write(CIFINISH_VERSION.to_bytes(4, 'little'))
        out.write(len(entries).to_bytes(4, 'little'))

        for tid, data in entries:
            finalize_entry_data = [
                # magic
                b'TITLE\0',
                # has seed
                bool(data['seed']).to_bytes(1, 'little'),
                # padding
                b'\0',
                # title id
                tid.to_bytes(8, 'little'),
                # seed, if needed
                (data['seed'] if data['seed'] else (b'\0' * 0x10))
            ]

            out.write(b''.join(finalize_entry_data))


class CustomInstall:
    def __init__(self, boot9, seeddb, movable, sd, cifinish_out=None,
                 overwrite_saves=False, skip_contents=False):
        self.event = Events()
        self.log_lines = []  # Stores all info messages for user to view

        self.crypto = CryptoEngine(boot9=boot9)
        self.crypto.setup_sd_key_from_file(movable)
        self.seeddb = seeddb
        self.readers: 'List[Union[CDNReader, CIAReader]]' = []
        self.sd = sd
        self.skip_contents = skip_contents
        self.overwrite_saves = overwrite_saves
        self.cifinish_out = cifinish_out
        self.movable = movable

    def copy_with_progress(self, src: BinaryIO, dst: BinaryIO, size: int, path: str, fire_event: bool = True):
        left = size
        cipher = self.crypto.create_ctr_cipher(Keyslot.SD, self.crypto.sd_path_to_iv(path))
        while left > 0:
            to_read = min(READ_SIZE, left)
            data = cipher.encrypt(src.read(READ_SIZE))
            dst.write(data)
            left -= to_read
            total_read = size - left
            if fire_event:
                self.event.update_percentage((total_read / size) * 100, total_read / 1048576, size / 1048576)

    def prepare_titles(self, paths: 'List[PathLike]'):
        readers = []
        for path in paths:
            self.log(f'Reading {path}')
            if isdir(path):
                # try the default tmd file
                reader = CDNReader(join(path, 'tmd'))
            else:
                try:
                    reader = CIAReader(path)
                except CIAError:
                    # if there was an error with parsing the CIA header,
                    # the file would be tried in CDNReader next (assuming it's a tmd)
                    # any other error should be propagated to the caller
                    reader = CDNReader(path)
            readers.append(reader)
        self.readers = readers

    def start(self):
        if frozen:
            save3ds_fuse_path = join(script_dir, 'bin', 'save3ds_fuse')
        else:
            save3ds_fuse_path = join(script_dir, 'bin', platform, 'save3ds_fuse')
        if is_windows:
            save3ds_fuse_path += '.exe'
        if not isfile(save3ds_fuse_path):
            self.log("Couldn't find " + save3ds_fuse_path, 2)
            return None, False

        crypto = self.crypto
        # TODO: Move a lot of these into their own methods
        self.log("Finding path to install to...")
        [sd_path, id1s] = self.get_sd_path()
        if len(id1s) > 1:
            raise SDPathError(f'There are multiple id1 directories for id0 {crypto.id0.hex()}, '
                              f'please remove extra directories')
        elif len(id1s) == 0:
            raise SDPathError(f'Could not find a suitable id1 directory for id0 {crypto.id0.hex()}')

        if self.cifinish_out:
            cifinish_path = self.cifinish_out
        else:
            cifinish_path = join(self.sd, 'cifinish.bin')
        sd_path = join(sd_path, id1s[0])
        title_info_entries = {}
        cifinish_data = load_cifinish(cifinish_path)

        load_seeddb(self.seeddb)

        # Now loop through all provided cia files
        
        for idx, cia in enumerate(self.readers):

            self.event.on_cia_start(idx)

            tid_parts = (cia.tmd.title_id[0:8], cia.tmd.title_id[8:16])

            try:
                self.log(f'Installing {cia.contents[0].exefs.icon.get_app_title().short_desc}...')
            except:
                self.log('Installing...')
            
            sizes = [1] * 5

            if cia.tmd.save_size:
                # one for the data directory, one for the 00000001.sav file
                sizes.extend((1, cia.tmd.save_size))
            
            for record in cia.content_info:
                sizes.append(record.size)
            
            # this calculates the size to put in the Title Info Entry
            title_size = sum(roundup(x, TITLE_ALIGN_SIZE) for x in sizes)

            # checks if this is dlc, which has some differences
            is_dlc = tid_parts[0] == '0004008c'

            # this checks if it has a manual (index 1) and is not DLC
            has_manual = (not is_dlc) and (1 in cia.contents)

            # this gets the extdata id from the extheader, stored in the storage info area
            try:
                with cia.contents[0].open_raw_section(NCCHSection.ExtendedHeader) as e:
                    e.seek(0x200 + 0x30)
                    extdata_id = e.read(8)
            except KeyError:
                # not an executable title
                extdata_id = b'\0' * 8

            # cmd content id, starts with 1 for non-dlc contents
            cmd_id = len(cia.content_info) if is_dlc else 1
            cmd_filename = f'{cmd_id:08x}.cmd'

            # get the title root where all the contents will be
            title_root = join(sd_path, 'title', *tid_parts)
            content_root = join(title_root, 'content')
            # generate the path used for the IV
            title_root_cmd = f'/title/{"/".join(tid_parts)}'
            content_root_cmd = title_root_cmd + '/content'

            if not self.skip_contents:
                makedirs(join(content_root, 'cmd'), exist_ok=True)
                if cia.tmd.save_size:
                    makedirs(join(title_root, 'data'), exist_ok=True)
                if is_dlc:
                    # create the separate directories for every 256 contents
                    for x in range(((len(cia.content_info) - 1) // 256) + 1):
                        makedirs(join(content_root, f'{x:08x}'), exist_ok=True)

                # maybe this will be changed in the future
                tmd_id = 0

                tmd_filename = f'{tmd_id:08x}.tmd'

                # write the tmd
                enc_path = content_root_cmd + '/' + tmd_filename
                self.log(f'Writing {enc_path}...')
                with open(join(content_root, tmd_filename), 'wb') as o:
                    with self.crypto.create_ctr_io(Keyslot.SD, o, self.crypto.sd_path_to_iv(enc_path)) as e:
                        e.write(bytes(cia.tmd))

                # write each content
                for co in cia.content_info:
                    content_filename = co.id + '.app'
                    if is_dlc:
                        dir_index = format((co.cindex // 256), '08x')
                        enc_path = content_root_cmd + f'/{dir_index}/{content_filename}'
                        out_path = join(content_root, dir_index, content_filename)
                    else:
                        enc_path = content_root_cmd + '/' + content_filename
                        out_path = join(content_root, content_filename)
                    self.log(f'Writing {enc_path}...')
                    with cia.open_raw_section(co.cindex) as s, open(out_path, 'wb') as o:
                        self.copy_with_progress(s, o, co.size, enc_path)

                # generate a blank save
                if cia.tmd.save_size:
                    enc_path = title_root_cmd + '/data/00000001.sav'
                    out_path = join(title_root, 'data', '00000001.sav')
                    if self.overwrite_saves or not isfile(out_path):
                        cipher = crypto.create_ctr_cipher(Keyslot.SD, crypto.sd_path_to_iv(enc_path))
                        # in a new save, the first 0x20 are all 00s. the rest can be random
                        data = cipher.encrypt(b'\0' * 0x20)
                        self.log(f'Generating blank save at {enc_path}...')
                        with open(out_path, 'wb') as o:
                            o.write(data)
                            o.write(b'\0' * (cia.tmd.save_size - 0x20))
                    else:
                        self.log(f'Not overwriting existing save at {enc_path}')

                # generate and write cmd
                enc_path = content_root_cmd + '/cmd/' + cmd_filename
                out_path = join(content_root, 'cmd', cmd_filename)
                self.log(f'Generating {enc_path}')
                highest_index = 0
                content_ids = {}

                for record in cia.content_info:
                    highest_index = record.cindex
                    with cia.open_raw_section(record.cindex) as s:
                        s.seek(0x100)
                        cmac_data = s.read(0x100)

                    id_bytes = bytes.fromhex(record.id)[::-1]
                    cmac_data += record.cindex.to_bytes(4, 'little') + id_bytes

                    cmac_ncch = crypto.create_cmac_object(Keyslot.CMACSDNAND)
                    cmac_ncch.update(sha256(cmac_data).digest())
                    content_ids[record.cindex] = (id_bytes, cmac_ncch.digest())

                # add content IDs up to the last one
                ids_by_index = [CMD_MISSING] * (highest_index + 1)
                installed_ids = []
                cmacs = []
                for x in range(len(ids_by_index)):
                    try:
                        info = content_ids[x]
                    except KeyError:
                        # "MISSING CONTENT!"
                        # The 3DS does generate a cmac for missing contents, but I don't know how it works.
                        # It doesn't matter anyway, the title seems to be fully functional.
                        cmacs.append(bytes.fromhex('4D495353494E4720434F4E54454E5421'))
                    else:
                        ids_by_index[x] = info[0]
                        cmacs.append(info[1])
                        installed_ids.append(info[0])
                installed_ids.sort(key=lambda x: int.from_bytes(x, 'little'))

                final = (cmd_id.to_bytes(4, 'little')
                         + len(ids_by_index).to_bytes(4, 'little')
                         + len(installed_ids).to_bytes(4, 'little')
                         + (1).to_bytes(4, 'little'))
                cmac_cmd_header = crypto.create_cmac_object(Keyslot.CMACSDNAND)
                cmac_cmd_header.update(final)
                final += cmac_cmd_header.digest()

                final += b''.join(ids_by_index)
                final += b''.join(installed_ids)
                final += b''.join(cmacs)

                cipher = crypto.create_ctr_cipher(Keyslot.SD, crypto.sd_path_to_iv(enc_path))
                self.log(f'Writing {enc_path}')
                with open(out_path, 'wb') as o:
                    o.write(cipher.encrypt(final))

            # this starts building the title info entry
            title_info_entry_data = [
                # title size
                title_size.to_bytes(8, 'little'),
                # title type, seems to usually be 0x40
                0x40.to_bytes(4, 'little'),
                # title version
                int(cia.tmd.title_version).to_bytes(2, 'little'),
                # ncch version
                cia.contents[0].version.to_bytes(2, 'little'),
                # flags_0, only checking if there is a manual
                (1 if has_manual else 0).to_bytes(4, 'little'),
                # tmd content id, always starting with 0
                (0).to_bytes(4, 'little'),
                # cmd content id
                cmd_id.to_bytes(4, 'little'),
                # flags_1, only checking save data
                (1 if cia.tmd.save_size else 0).to_bytes(4, 'little'),
                # extdataid low
                extdata_id[0:4],
                # reserved
                b'\0' * 4,
                # flags_2, only using a common value
                0x100000000.to_bytes(8, 'little'),
                # product code
                cia.contents[0].product_code.encode('ascii').ljust(0x10, b'\0'),
                # reserved
                b'\0' * 0x10,
                # unknown
                randint(0, 0xFFFFFFFF).to_bytes(4, 'little'),
                # reserved
                b'\0' * 0x2c
            ]

            title_info_entries[cia.tmd.title_id] = b''.join(title_info_entry_data)

            cifinish_data[int(cia.tmd.title_id, 16)] = {'seed': (get_seed(cia.contents[0].program_id) if cia.contents[0].flags.uses_seed else None)}

        # This is saved regardless if any titles were installed, so the file can be upgraded just in case.
        save_cifinish(cifinish_path, cifinish_data)

        if title_info_entries:
            with TemporaryDirectory(suffix='-custom-install') as tempdir:
                # set up the common arguments for the two times we call save3ds_fuse
                save3ds_fuse_common_args = [
                    save3ds_fuse_path,
                    '-b', crypto.b9_path,
                    '-m', self.movable,
                    '--sd', self.sd,
                    '--db', 'sdtitle',
                    tempdir
                ]

                extra_kwargs = {}
                if is_windows:
                    # hide console window
                    extra_kwargs['creationflags'] = 0x08000000  # CREATE_NO_WINDOW

                # extract the title database to add our own entry to
                self.log('Extracting Title Database...')
                out = subprocess.run(save3ds_fuse_common_args + ['-x'],
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT,
                                     encoding=getpreferredencoding(),
                                     **extra_kwargs)
                if out.returncode:
                    for l in out.stdout.split('\n'):
                        self.log(l)
                    self.log('Command line:')
                    for l in pformat(out.args).split('\n'):
                        self.log(l)
                    return False, False

                for title_id, entry in title_info_entries.items():
                    # write the title info entry to the temp directory
                    with open(join(tempdir, title_id), 'wb') as o:
                        o.write(entry)

                # import the directory, now including our title
                self.log('Importing into Title Database...')
                out = subprocess.run(save3ds_fuse_common_args + ['-i'],
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT,
                                     encoding=getpreferredencoding(),
                                     **extra_kwargs)
                if out.returncode:
                    for l in out.stdout.split('\n'):
                        self.log(l)
                    self.log('Command line:')
                    for l in pformat(out.args).split('\n'):
                        self.log(l)
                    return False, False

            finalize_3dsx_orig_path = join(script_dir, 'custom-install-finalize.3dsx')
            hb_dir = join(self.sd, '3ds')
            finalize_3dsx_path = join(hb_dir, 'custom-install-finalize.3dsx')
            copied = False
            if isfile(finalize_3dsx_orig_path):
                self.log('Copying finalize program to ' + finalize_3dsx_path)
                makedirs(hb_dir, exist_ok=True)
                copyfile(finalize_3dsx_orig_path, finalize_3dsx_path)
                copied = True

            self.log('FINAL STEP:')
            self.log('Run custom-install-finalize through homebrew launcher.')
            self.log('This will install a ticket and seed if required.')
            if copied:
                self.log('custom-install-finalize has been copied to the SD card.')
            return True, copied

        else:
            self.log('Did not install any titles.', 2)
            return None, False

    def get_sd_path(self):
        sd_path = join(self.sd, 'Nintendo 3DS', self.crypto.id0.hex())
        id1s = []
        for d in scandir(sd_path):
            if d.is_dir() and len(d.name) == 32:
                try:
                    # check if the name can be converted to hex
                    # I'm not sure what the 3DS does if there is a folder that is not a 32-char hex string.
                    bytes.fromhex(d.name)
                except ValueError:
                    continue
                else:
                    id1s.append(d.name)
        return [sd_path, id1s]

    def log(self, message, mtype=0, errorname=None, end='\n'):
        """Logs an Message with a type. Format is similar to python errors

        There are 3 types of errors, indexed accordingly
        type 0 = Message
        type 1 = Warning
        type 2 = Error

        optionally, errorname can be a custom name as a string to identify errors easily
        """
        if errorname:
            errorname += ": "
        else:
            # No errorname provided
            errorname = ""
        types = [
            "",  # Type 0
            "Warning: ",  # Type 1
            "Error: "  # Type 2
        ]
        # Example: "Warning: UninformativeError: An error occured, try again.""
        msg_with_type = types[mtype] + errorname + str(message)
        self.log_lines.append(msg_with_type)
        self.event.on_log_msg(msg_with_type, end=end)
        return msg_with_type


if __name__ == "__main__":
    parser = ArgumentParser(description='Manually install a CIA to the SD card for a Nintendo 3DS system.')
    parser.add_argument('cia', help='CIA files', nargs='+')
    parser.add_argument('-m', '--movable', help='movable.sed file', required=True)
    parser.add_argument('-b', '--boot9', help='boot9 file')
    parser.add_argument('-s', '--seeddb', help='seeddb file')
    parser.add_argument('--sd', help='path to SD root', required=True)
    parser.add_argument('--skip-contents', help="don't add contents, only add title info entry", action='store_true')
    parser.add_argument('--overwrite-saves', help='overwrite existing save files', action='store_true')
    parser.add_argument('--cifinish-out', help='path for cifinish.bin file, defaults to (SD root)/cifinish.bin')

    args = parser.parse_args()

    installer = CustomInstall(boot9=args.boot9,
                              seeddb=args.seeddb,
                              movable=args.movable,
                              sd=args.sd,
                              overwrite_saves=args.overwrite_saves,
                              cifinish_out=args.cifinish_out,
                              skip_contents=(args.skip_contents or False))

    def log_handle(msg, end='\n'):
        print(msg, end=end)
    
    def percent_handle(total_percent, total_read, size):
        installer.log(f' {total_percent:>5.1f}%  {total_read:>.1f} MiB / {size:.1f} MiB\r', end='')

    def error(exc):
        for line in format_exception(*exc):
            for line2 in line.split('\n')[:-1]:
                installer.log(line2)

    installer.event.on_log_msg += log_handle
    installer.event.update_percentage += percent_handle
    installer.event.on_error += error

    installer.prepare_titles(args.cia)

    result, copied_3dsx = installer.start()
    if result is False:
        # save3ds_fuse failed
        installer.log('NOTE: Once save3ds_fuse is fixed, run the same command again with --skip-contents')

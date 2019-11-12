# This file is a part of ninfs.
#
# Copyright (c) 2017-2019 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE.md in the root of this project.

from io import TextIOWrapper
from threading import Lock
from typing import overload, TYPE_CHECKING, NamedTuple

from ..common import PyCTRError, _ReaderOpenFileBase
from ..fileio import SubsectionIO
from ..util import readle, roundup

if TYPE_CHECKING:
    from typing import BinaryIO, Optional, Tuple, Union

__all__ = ['IVFC_HEADER_SIZE', 'IVFC_ROMFS_MAGIC_NUM', 'ROMFS_LV3_HEADER_SIZE', 'RomFSError', 'InvalidIVFCError',
           'InvalidRomFSHeaderError', 'RomFSEntryError', 'RomFSFileNotFoundError', 'RomFSReader']

IVFC_HEADER_SIZE = 0x5C
IVFC_ROMFS_MAGIC_NUM = 0x10000
ROMFS_LV3_HEADER_SIZE = 0x28


class RomFSError(PyCTRError):
    """Generic exception for RomFS operations."""


class InvalidIVFCError(RomFSError):
    """Invalid IVFC header exception."""


class InvalidRomFSHeaderError(RomFSError):
    """Invalid RomFS Level 3 header."""


class RomFSEntryError(RomFSError):
    """Error with RomFS Directory or File entry."""


class RomFSFileNotFoundError(RomFSEntryError):
    """Invalid file path in RomFS Level 3."""


class RomFSIsADirectoryError(RomFSEntryError):
    """Attempted to open a directory as a file."""


class RomFSRegion(NamedTuple):
    offset: int
    size: int


class RomFSDirectoryEntry(NamedTuple):
    name: str
    type: str
    contents: 'Tuple[str, ...]'


class RomFSFileEntry(NamedTuple):
    name: str
    type: str
    offset: int
    size: int


class RomFSReader:
    """
    Class for 3DS RomFS Level 3 partition.

    https://www.3dbrew.org/wiki/RomFS
    """

    closed = False
    lv3_offset = 0
    data_offset = 0

    def __init__(self, fp: 'Union[str, BinaryIO]', case_insensitive: bool = False):
        if isinstance(fp, str):
            fp = open(fp, 'rb')

        self._start = fp.tell()
        self._fp = fp
        self.case_insensitive = case_insensitive
        self._lock = Lock()

        lv3_offset = fp.tell()
        magic = fp.read(4)

        # detect ivfc and get the lv3 offset
        if magic == b'IVFC':
            ivfc = magic + fp.read(0x54)  # IVFC_HEADER_SIZE - 4
            ivfc_magic_num = readle(ivfc[0x4:0x8])
            if ivfc_magic_num != IVFC_ROMFS_MAGIC_NUM:
                raise InvalidIVFCError(f'IVFC magic number is invalid '
                                       f'({ivfc_magic_num:#X} instead of {IVFC_ROMFS_MAGIC_NUM:#X})')
            master_hash_size = readle(ivfc[0x8:0xC])
            lv3_block_size = readle(ivfc[0x4C:0x50])
            lv3_hash_block_size = 1 << lv3_block_size
            lv3_offset += roundup(0x60 + master_hash_size, lv3_hash_block_size)
            fp.seek(self._start + lv3_offset)
            magic = fp.read(4)
        self.lv3_offset = lv3_offset

        lv3_header = magic + fp.read(0x24)  # ROMFS_LV3_HEADER_SIZE - 4

        # get offsets and sizes from lv3 header
        lv3_header_size = readle(magic)
        lv3_dirhash = RomFSRegion(offset=readle(lv3_header[0x4:0x8]), size=readle(lv3_header[0x8:0xC]))
        lv3_dirmeta = RomFSRegion(offset=readle(lv3_header[0xC:0x10]), size=readle(lv3_header[0x10:0x14]))
        lv3_filehash = RomFSRegion(offset=readle(lv3_header[0x14:0x18]), size=readle(lv3_header[0x18:0x1C]))
        lv3_filemeta = RomFSRegion(offset=readle(lv3_header[0x1C:0x20]), size=readle(lv3_header[0x20:0x24]))
        lv3_filedata_offset = readle(lv3_header[0x24:0x28])
        self.data_offset = lv3_offset + lv3_filedata_offset

        # verify lv3 header
        if lv3_header_size != ROMFS_LV3_HEADER_SIZE:
            raise InvalidRomFSHeaderError('Length in RomFS Lv3 header is not 0x28')
        if lv3_dirhash.offset < lv3_header_size:
            raise InvalidRomFSHeaderError('Directory Hash offset is before the end of the Lv3 header')
        if lv3_dirmeta.offset < lv3_dirhash.offset + lv3_dirhash.size:
            raise InvalidRomFSHeaderError('Directory Metadata offset is before the end of the Directory Hash region')
        if lv3_filehash.offset < lv3_dirmeta.offset + lv3_dirmeta.size:
            raise InvalidRomFSHeaderError('File Hash offset is before the end of the Directory Metadata region')
        if lv3_filemeta.offset < lv3_filehash.offset + lv3_filehash.size:
            raise InvalidRomFSHeaderError('File Metadata offset is before the end of the File Hash region')
        if lv3_filedata_offset < lv3_filemeta.offset + lv3_filemeta.size:
            raise InvalidRomFSHeaderError('File Data offset is before the end of the File Metadata region')

        # get entries from dirmeta and filemeta
        def iterate_dir(out: dict, raw: bytes, current_path: str):
            first_child_dir = readle(raw[0x8:0xC])
            first_file = readle(raw[0xC:0x10])

            out['type'] = 'dir'
            out['contents'] = {}

            # iterate through all child directories
            if first_child_dir != 0xFFFFFFFF:
                fp.seek(self._start + lv3_offset + lv3_dirmeta.offset + first_child_dir)
                while True:
                    child_dir_meta = fp.read(0x18)
                    next_sibling_dir = readle(child_dir_meta[0x4:0x8])
                    child_dir_name = fp.read(readle(child_dir_meta[0x14:0x18])).decode('utf-16le')
                    child_dir_name_meta = child_dir_name.lower() if case_insensitive else child_dir_name
                    if child_dir_name_meta in out['contents']:
                        print(f'WARNING: Dirname collision! {current_path}{child_dir_name}')
                    out['contents'][child_dir_name_meta] = {'name': child_dir_name}

                    iterate_dir(out['contents'][child_dir_name_meta], child_dir_meta,
                                f'{current_path}{child_dir_name}/')
                    if next_sibling_dir == 0xFFFFFFFF:
                        break
                    fp.seek(self._start + lv3_offset + lv3_dirmeta.offset + next_sibling_dir)

            if first_file != 0xFFFFFFFF:
                fp.seek(self._start + lv3_offset + lv3_filemeta.offset + first_file)
                while True:
                    child_file_meta = fp.read(0x20)
                    next_sibling_file = readle(child_file_meta[0x4:0x8])
                    child_file_offset = readle(child_file_meta[0x8:0x10])
                    child_file_size = readle(child_file_meta[0x10:0x18])
                    child_file_name = fp.read(readle(child_file_meta[0x1C:0x20])).decode('utf-16le')
                    child_file_name_meta = child_file_name.lower() if self.case_insensitive else child_file_name
                    if child_file_name_meta in out['contents']:
                        print(f'WARNING: Filename collision! {current_path}{child_file_name}')
                    out['contents'][child_file_name_meta] = {'name': child_file_name, 'type': 'file',
                                                             'offset': child_file_offset, 'size': child_file_size}

                    self.total_size += child_file_size
                    if next_sibling_file == 0xFFFFFFFF:
                        break
                    fp.seek(self._start + lv3_offset + lv3_filemeta.offset + next_sibling_file)

        self._tree_root = {'name': 'ROOT'}
        self.total_size = 0
        fp.seek(self._start + lv3_offset + lv3_dirmeta.offset)
        iterate_dir(self._tree_root, fp.read(0x18), '/')

    def close(self):
        self.closed = True
        try:
            self._fp.close()
        except AttributeError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    @overload
    def open(self, path: str, encoding: str, errors: 'Optional[str]' = None,
             newline: 'Optional[str]' = None) -> TextIOWrapper: ...

    @overload
    def open(self, path: str, encoding: None = None, errors: 'Optional[str]' = None,
             newline: 'Optional[str]' = None) -> SubsectionIO: ...

    def open(self, path, encoding=None, errors=None, newline=None):
        """Open a file in the RomFS for reading."""
        file_info = self.get_info_from_path(path)
        if not isinstance(file_info, RomFSFileEntry):
            raise RomFSIsADirectoryError(path)
        f = SubsectionIO(self._fp, self._start + self.data_offset + file_info.offset, file_info.size)
        if encoding is not None:
            f = TextIOWrapper(f, encoding, errors, newline)
        return f

    __del__ = close

    def get_info_from_path(self, path: str) -> 'Union[RomFSDirectoryEntry, RomFSFileEntry]':
        """Get a directory or file entry"""
        curr = self._tree_root
        if self.case_insensitive:
            path = path.lower()
        if path[0] == '/':
            path = path[1:]
        for part in path.split('/'):
            if part == '':
                break
            try:
                # noinspection PyTypeChecker
                curr = curr['contents'][part]
            except KeyError:
                raise RomFSFileNotFoundError(path)
        if curr['type'] == 'dir':
            contents = (k['name'] for k in curr['contents'].values())
            return RomFSDirectoryEntry(name=curr['name'], type='dir', contents=(*contents,))
        elif curr['type'] == 'file':
            return RomFSFileEntry(name=curr['name'], type='file', offset=curr['offset'], size=curr['size'])

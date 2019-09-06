# This file is a part of ninfs.
#
# Copyright (c) 2017-2019 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE.md in the root of this project.

from enum import IntEnum
from io import BytesIO
from threading import Lock
from typing import TYPE_CHECKING, NamedTuple

from ..common import PyCTRError, _ReaderOpenFileBase
from ..crypto import CryptoEngine, Keyslot
from ..types.ncch import NCCHReader
from ..types.tmd import TitleMetadataReader
from ..util import readle, roundup

if TYPE_CHECKING:
    from typing import BinaryIO, Dict, Optional, Union

ALIGN_SIZE = 64


class CIAError(PyCTRError):
    """Generic error for CIA operations."""


class InvalidCIAError(CIAError):
    """Invalid CIA header exception."""


class CIASection(IntEnum):
    # these values as negative, as positive ones are used for contents
    ArchiveHeader = -4
    CertificateChain = -3
    Ticket = -2
    TitleMetadata = -1
    Meta = -5


class CIARegion(NamedTuple):
    section: 'Union[int, CIASection]'
    offset: int
    size: int
    iv: bytes  # only used for encrypted sections


class _CIASectionFile(_ReaderOpenFileBase):
    """Provides a raw CIA section as a file-like object."""

    def __init__(self, reader: 'CIAReader', path: 'CIASection'):
        super().__init__(reader, path)
        self._info = reader.sections[path]


class CIAReader:
    """Class for the 3DS CIA container."""

    closed = False

    def __init__(self, fp: 'Union[str, BinaryIO]', *, case_insensitive: bool = True, crypto: CryptoEngine = None,
                 dev: bool = False, seeddb: str = None, load_contents: bool = True):
        if isinstance(fp, str):
            fp = open(fp, 'rb')

        if crypto:
            self._crypto = crypto
        else:
            self._crypto = CryptoEngine(dev=dev)

        # store the starting offset so the CIA can be read from any point in the base file
        self._start = fp.tell()
        self._fp = fp
        # store case-insensitivity for RomFSReader
        self._case_insensitive = case_insensitive
        # threading lock
        self._lock = Lock()

        header = fp.read(0x20)

        archive_header_size = readle(header[0x0:0x4])
        if archive_header_size != 0x2020:
            raise InvalidCIAError('Archive Header Size is not 0x2020')
        # in practice, the certificate chain is the same for all retail titles
        cert_chain_size = readle(header[0x8:0xC])
        # the ticket size usually never changes from 0x350
        # there is one ticket (without an associated title) that is smaller though
        ticket_size = readle(header[0xC:0x10])
        # tmd contains info about the contents of the title
        tmd_size = readle(header[0x10:0x14])
        # meta contains info such as the SMDH and Title ID dependency list
        meta_size = readle(header[0x14:0x18])
        # content size is the total size of the contents
        # I'm not sure what happens yet if one of the contents is not aligned to 0x40 bytes.
        content_size = readle(header[0x18:0x20])
        # the content index determines what contents are in the CIA
        # this is not stored as int, so it's faster to parse(?)
        content_index = fp.read(archive_header_size - 0x20)

        active_contents = set()
        for idx, b in enumerate(content_index):
            offset = idx * 8
            curr = b
            for x in range(7, -1, -1):
                if curr & 1:
                    active_contents.add(x + offset)
                curr >>= 1

        # the header only stores sizes; offsets need to be calculated.
        # the sections are aligned to 64(0x40) bytes. for example, if something is 0x78,
        #   it will take up 0x80, with the remaining 0x8 being padding.
        cert_chain_offset = roundup(archive_header_size, ALIGN_SIZE)
        ticket_offset = cert_chain_offset + roundup(cert_chain_size, ALIGN_SIZE)
        tmd_offset = ticket_offset + roundup(ticket_size, ALIGN_SIZE)
        content_offset = tmd_offset + roundup(tmd_size, ALIGN_SIZE)
        meta_offset = content_offset + roundup(content_size, ALIGN_SIZE)

        # lazy method to get the total size
        self.total_size = meta_offset + meta_size

        # this contains the location of each section, as well as the IV of encrypted ones
        self.sections: Dict[Union[int, CIASection], CIARegion] = {}

        def add_region(section: 'Union[int, CIASection]', offset: int, size: int, iv: 'Optional[bytes]'):
            region = CIARegion(section=section, offset=offset, size=size, iv=iv)
            self.sections[section] = region

        # add each part of the header
        add_region(CIASection.ArchiveHeader, 0, archive_header_size, None)
        add_region(CIASection.CertificateChain, cert_chain_offset, cert_chain_size, None)
        add_region(CIASection.Ticket, ticket_offset, ticket_size, None)
        add_region(CIASection.TitleMetadata, tmd_offset, tmd_size, None)
        if meta_size:
            add_region(CIASection.Meta, meta_offset, meta_size, None)

        # this will load the titlekey to decrypt the contents
        self._fp.seek(self._start + ticket_offset)
        ticket = self._fp.read(ticket_size)
        self._crypto.load_from_ticket(ticket)

        # the tmd describes the contents: ID, index, size, and hash
        self._fp.seek(self._start + tmd_offset)
        tmd_data = self._fp.read(tmd_size)
        self.tmd = TitleMetadataReader.load(BytesIO(tmd_data))

        active_contents_tmd = set()
        self.content_info = []

        # this does a first check to make sure there are no missing contents that are marked active in content_index
        for record in self.tmd.chunk_records:
            if record.cindex in active_contents:
                active_contents_tmd.add(record.cindex)
                self.content_info.append(record)

        # if the result of this is not an empty set, it means there are contents enabled in content_index
        #   that are not in the tmd, which is bad
        if active_contents ^ active_contents_tmd:
            raise InvalidCIAError('Missing active contents in the TMD')

        self.contents = {}

        # this goes through the contents and figures out their regions, then creates an NCCHReader
        curr_offset = content_offset
        for record in self.content_info:
            iv = None
            if record.type.encrypted:
                iv = record.cindex.to_bytes(2, 'big') + (b'\0' * 14)
            add_region(record.cindex, curr_offset, record.size, iv)
            if load_contents:
                # check if the content is a Nintendo DS ROM (SRL) first
                is_srl = record.cindex == 0 and self.tmd.title_id[3:5] == '48'
                if not is_srl:
                    content_fp = self.open_raw_section(record.cindex)
                    self.contents[record.cindex] = NCCHReader(content_fp, case_insensitive=case_insensitive,
                                                              dev=dev, seeddb=seeddb)

            curr_offset += record.size

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

    __del__ = close

    def __repr__(self):
        info = [('title_id', self.tmd.title_id)]
        try:
            info.append(('title_name', repr(self.contents[0].exefs.icon.get_app_title().short_desc)))
        except KeyError:
            info.append(('title_name', 'unknown'))
        info.append(('content_count', len(self.contents)))
        info_final = " ".join(x + ": " + str(y) for x, y in info)
        return f'<{type(self).__name__} {info_final}>'

    def open_raw_section(self, section: 'CIASection'):
        """Open a raw CIA section for reading."""
        return _CIASectionFile(self, section)

    def get_data(self, region: 'CIARegion', offset: int, size: int) -> bytes:
        if offset + size > region.size:
            # prevent reading past the region
            size = region.size - offset

        with self._lock:
            if region.iv:
                real_size = size
                # if encrypted, the block needs to be decrypted first
                # CBC requires a full block (0x10 in this case). and the previous
                #   block is used as the IV. so that's quite a bit to read if the
                #   application requires just a few bytes.
                # thanks Stary2001 for help with random-access crypto
                before = offset % 16
                if size % 16 != 0:
                    size = size + 16 - size % 16
                if offset - before == 0:
                    iv = region.iv
                else:
                    self._fp.seek(self._start + region.offset + offset - before - 0x10)
                    iv = self._fp.read(0x10)
                # read to block size
                self._fp.seek(self._start + region.offset + offset - before)
                # adding x10 to the size fixes some kind of decryption bug I think. this needs more testing.
                return self._crypto.create_cbc_cipher(Keyslot.DecryptedTitlekey,
                                                      iv).decrypt(self._fp.read(size + 0x10))[before:real_size + before]
            else:
                # no encryption
                self._fp.seek(self._start + region.offset + offset)
                return self._fp.read(size)

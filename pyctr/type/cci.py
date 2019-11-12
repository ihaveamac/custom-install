# This file is a part of ninfs.
#
# Copyright (c) 2017-2019 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE.md in the root of this project.

from enum import IntEnum
from threading import Lock
from typing import TYPE_CHECKING, NamedTuple

from ..common import PyCTRError
from ..fileio import SubsectionIO
from ..type.ncch import NCCHReader
from ..util import readle

if TYPE_CHECKING:
    from typing import BinaryIO, Dict, Union

CCI_MEDIA_UNIT = 0x200


class CCIError(PyCTRError):
    """Generic error for CCI operations."""


class InvalidCCIError(CCIError):
    """Invalid CCI header exception."""


class CCISection(IntEnum):
    Header = -3
    CardInfo = -2
    DevInfo = -1

    Application = 0
    Manual = 1
    DownloadPlayChild = 2
    Unk3 = 3
    Unk4 = 4
    Unk5 = 5
    UpdateOld3DS = 6
    UpdateNew3DS = 7


class CCIRegion(NamedTuple):
    section: 'Union[int, CCISection]'
    offset: int
    size: int


class CCIReader:
    """Class for the 3DS CCI container."""

    closed = False

    def __init__(self, fp: 'Union[str, BinaryIO]', *, case_insensitive: bool = True, dev: bool = False,
                 load_contents: bool = True, assume_decrypted: bool = False):
        if isinstance(fp, str):
            fp = open(fp, 'rb')

        # store the starting offset so the CCI can be read from any point in the base file
        self._start = fp.tell()
        self._fp = fp
        # store case-insensitivity for RomFSReader
        self._case_insensitive = case_insensitive
        # threading lock
        self._lock = Lock()

        # ignore the signature, we don't need it
        self._fp.seek(0x100, 1)
        header = fp.read(0x100)
        if header[0:4] != b'NCSD':
            raise InvalidCCIError('NCSD magic not found')

        # make sure the Media ID is not 00, which is used for the NAND header
        self.media_id = header[0x8:0x10][::-1].hex()
        if self.media_id == '00' * 8:
            raise InvalidCCIError('Media ID is ' + self.media_id)

        self.image_size = readle(header[4:8]) * CCI_MEDIA_UNIT

        # this contains the location of each section
        self.sections: Dict[CCISection, CCIRegion] = {}

        # this contains loaded sections
        self.contents: Dict[CCISection, NCCHReader] = {}

        def add_region(section: 'CCISection', offset: int, size: int):
            region = CCIRegion(section=section, offset=offset, size=size)
            self.sections[section] = region

        # add each part of the header
        add_region(CCISection.Header, 0, 0x200)
        add_region(CCISection.CardInfo, 0x200, 0x1000)
        add_region(CCISection.DevInfo, 0x1200, 0x300)

        # use a CCISection value for section keys
        partition_sections = [x for x in CCISection if x >= 0]

        part_raw = header[0x20:0x60]

        # the first content always starts at 0x4000 but this code makes no assumptions about it
        for idx, info_offset in enumerate(range(0, 0x40, 0x8)):
            part_info = part_raw[info_offset:info_offset + 8]
            part_offset = int.from_bytes(part_info[0:4], 'little') * CCI_MEDIA_UNIT
            part_size = int.from_bytes(part_info[4:8], 'little') * CCI_MEDIA_UNIT
            if part_offset:
                section_id = partition_sections[idx]
                add_region(section_id, part_offset, part_size)

                if load_contents:
                    content_fp = self.open_raw_section(section_id)
                    self.contents[section_id] = NCCHReader(content_fp, case_insensitive=case_insensitive, dev=dev,
                                                           assume_decrypted=assume_decrypted)

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
        info = [('media_id', self.media_id)]
        try:
            info.append(('title_name',
                         repr(self.contents[CCISection.Application].exefs.icon.get_app_title().short_desc)))
        except KeyError:
            info.append(('title_name', 'unknown'))
        info.append(('partition_count', len(self.contents)))
        info_final = " ".join(x + ": " + str(y) for x, y in info)
        return f'<{type(self).__name__} {info_final}>'

    def open_raw_section(self, section: 'CCISection'):
        """Open a raw CCI section for reading."""
        region = self.sections[section]
        return SubsectionIO(self._fp, self._start + region.offset, region.size)

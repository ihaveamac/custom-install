# This file is a part of ninfs.
#
# Copyright (c) 2017-2019 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE.md in the root of this project.

from hashlib import sha256
from struct import pack
from typing import TYPE_CHECKING, NamedTuple

from ..common import PyCTRError
from ..util import readbe, readle

if TYPE_CHECKING:
    from typing import BinaryIO, Iterable

__all__ = ['CHUNK_RECORD_SIZE', 'TitleMetadataError', 'InvalidSignatureTypeError', 'InvalidHashError',
           'ContentInfoRecord', 'ContentChunkRecord', 'ContentTypeFlags', 'TitleVersion', 'TitleMetadataReader']

CHUNK_RECORD_SIZE = 0x30

# sig-type: (sig-size, padding)
signature_types = {
    # RSA_4096 SHA1 (unused on 3DS)
    0x00010000: (0x200, 0x3C),
    # RSA_2048 SHA1 (unused on 3DS)
    0x00010001: (0x100, 0x3C),
    # Elliptic Curve with SHA1 (unused on 3DS)
    0x00010002: (0x3C, 0x40),
    # RSA_4096 SHA256
    0x00010003: (0x200, 0x3C),
    # RSA_2048 SHA256
    0x00010004: (0x100, 0x3C),
    # ECDSA with SHA256
    0x00010005: (0x3C, 0x40),
}

BLANK_SIG_PAIR = (0x00010004, b'\xFF' * signature_types[0x00010004][0])


class TitleMetadataError(PyCTRError):
    """Generic exception for TitleMetadata operations."""


class InvalidTMDError(TitleMetadataError):
    """Title Metadata is invalid."""


class InvalidSignatureTypeError(InvalidTMDError):
    """Invalid signature type was used."""

    def __init__(self, sig_type):
        super().__init__(sig_type)

    def __str__(self):
        return f'{self.args[0]:#010x}'


class InvalidHashError(InvalidTMDError):
    """Hash mismatch in the Title Metadata."""


class InvalidInfoRecordError(InvalidHashError):
    """Hash mismatch in the Content Info Records."""

    def __init__(self, info_record):
        super().__init__(info_record)

    def __str__(self):
        return f'Invalid info record: {self.args[0]}'


class UnusualInfoRecordError(InvalidTMDError):
    """Encountered Content Info Record that attempts to hash a Content Chunk Record that has already been hashed."""

    def __init__(self, info_record, chunk_record):
        super().__init__(info_record, chunk_record)

    def __str__(self):
        return f'Attempted to hash twice: {self.args[0]}, {self.args[1]}'


class ContentTypeFlags(NamedTuple):
    encrypted: bool
    disc: bool
    cfm: bool
    optional: bool
    shared: bool

    def __index__(self) -> int:
        return self.encrypted | (self.disc << 1) | (self.cfm << 2) | (self.optional << 14) | (self.shared << 15)

    __int__ = __index__

    def __format__(self, format_spec: str) -> str:
        return self.__int__().__format__(format_spec)

    @classmethod
    def from_int(cls, flags: int) -> 'ContentTypeFlags':
        # noinspection PyArgumentList
        return cls(bool(flags & 1), bool(flags & 2), bool(flags & 4), bool(flags & 0x4000), bool(flags & 0x8000))


class ContentInfoRecord(NamedTuple):
    index_offset: int
    command_count: int
    hash: bytes

    def __bytes__(self) -> bytes:
        return b''.join((self.index_offset.to_bytes(2, 'big'), self.command_count.to_bytes(2, 'big'), self.hash))


class ContentChunkRecord(NamedTuple):
    id: str
    cindex: int
    type: ContentTypeFlags
    size: int
    hash: bytes

    def __bytes__(self) -> bytes:
        return b''.join((bytes.fromhex(self.id), self.cindex.to_bytes(2, 'big'), int(self.type).to_bytes(2, 'big'),
                         self.size.to_bytes(8, 'big'), self.hash))


class TitleVersion(NamedTuple):
    major: int
    minor: int
    micro: int

    def __str__(self) -> str:
        return f'{self.major}.{self.minor}.{self.micro}'

    def __index__(self) -> int:
        return (self.major << 10) | (self.minor << 4) | self.micro

    __int__ = __index__

    def __format__(self, format_spec: str) -> str:
        return self.__int__().__format__(format_spec)

    @classmethod
    def from_int(cls, ver: int) -> 'TitleVersion':
        # noinspection PyArgumentList
        return cls((ver >> 10) & 0x3F, (ver >> 4) & 0x3F, ver & 0xF)


class TitleMetadataReader:
    """
    Class for 3DS Title Metadata.

    https://www.3dbrew.org/wiki/Title_metadata
    """

    __slots__ = ('title_id', 'save_size', 'srl_save_size', 'title_version', 'info_records',
                 'chunk_records', 'content_count', 'signature', '_u_issuer', '_u_version', '_u_ca_crl_version',
                 '_u_signer_crl_version', '_u_reserved1', '_u_system_version', '_u_title_type', '_u_group_id',
                 '_u_reserved2', '_u_srl_flag', '_u_reserved3', '_u_access_rights', '_u_boot_count', '_u_padding')

    # arguments prefixed with _u_ are values unused by the 3DS and/or are only kept around to generate the final tmd
    def __init__(self, *, title_id: str, save_size: int, srl_save_size: int, title_version: TitleVersion,
                 info_records: 'Iterable[ContentInfoRecord]', chunk_records: 'Iterable[ContentChunkRecord]',
                 signature=BLANK_SIG_PAIR, _u_issuer='Root-CA00000003-CP0000000b', _u_version=1, _u_ca_crl_version=0,
                 _u_signer_crl_version=0, _u_reserved1=0, _u_system_version=b'\0' * 8, _u_title_type=b'\0\0\0@',
                 _u_group_id=b'\0\0', _u_reserved2=b'\0\0\0\0', _u_srl_flag=0, _u_reserved3=b'\0' * 0x31,
                 _u_access_rights=b'\0' * 4, _u_boot_count=b'\0\0', _u_padding=b'\0\0'):
        # TODO: add checks
        self.title_id = title_id.lower()
        self.save_size = save_size
        self.srl_save_size = srl_save_size
        self.title_version = title_version
        self.info_records = tuple(info_records)
        self.chunk_records = tuple(chunk_records)
        self.content_count = len(self.chunk_records)
        self.signature = signature  # TODO: store this differently

        # unused values
        self._u_issuer = _u_issuer
        self._u_version = _u_version
        self._u_ca_crl_version = _u_ca_crl_version
        self._u_signer_crl_version = _u_signer_crl_version
        self._u_reserved1 = _u_reserved1
        self._u_system_version = _u_system_version
        self._u_title_type = _u_title_type
        self._u_group_id = _u_group_id
        self._u_reserved2 = _u_reserved2
        self._u_srl_flag = _u_srl_flag
        self._u_reserved3 = _u_reserved3
        self._u_access_rights = _u_access_rights
        self._u_boot_count = _u_boot_count
        self._u_padding = _u_padding

    def __hash__(self) -> int:
        return hash((self.title_id, self.save_size, self.srl_save_size, self.title_version,
                     self.info_records, self.chunk_records))

    def __repr__(self) -> str:
        return (f'<TitleMetadataReader title_id={self.title_id!r} title_version={self.title_version!r} '
                f'content_count={self.content_count!r}>')

    def __bytes__(self) -> bytes:
        sig_data = pack(f'>I {signature_types[self.signature[0]][0]}s {signature_types[self.signature[0]][1]}x',
                        self.signature[0], self.signature[1])

        info_records = b''.join(bytes(x) for x in self.info_records).ljust(0x900, b'\0')

        header = pack('>64s b b b b 8s 8s 4s 2s I I 4s b 49s 4s H H 2s 2s 32s', self._u_issuer.encode('ascii'),
                      self._u_version, self._u_ca_crl_version, self._u_signer_crl_version, self._u_reserved1,
                      self._u_system_version, bytes.fromhex(self.title_id), self._u_title_type, self._u_group_id,
                      self.save_size, self.srl_save_size, self._u_reserved2, self._u_srl_flag, self._u_reserved3,
                      self._u_access_rights, self.title_version, self.content_count, self._u_boot_count,
                      self._u_padding, sha256(info_records).digest())

        chunk_records = b''.join(bytes(x) for x in self.chunk_records)

        return sig_data + header + info_records + chunk_records

    @classmethod
    def load(cls, fp: 'BinaryIO', verify_hashes: bool = True) -> 'TitleMetadataReader':
        """Load a tmd from a file-like object."""
        sig_type = readbe(fp.read(4))
        try:
            sig_size, sig_padding = signature_types[sig_type]
        except KeyError:
            raise InvalidSignatureTypeError(sig_type)

        signature = fp.read(sig_size)
        try:
            fp.seek(sig_padding, 1)
        except Exception:
            # most streams are probably seekable, but for some that aren't...
            fp.read(sig_padding)

        header = fp.read(0xC4)
        if len(header) != 0xC4:
            raise InvalidTMDError('Header length is not 0xC4')

        # only values that actually have a use are loaded here. (currently)
        # several fields in were left in from the Wii tmd and have no function on 3DS.
        title_id = header[0x4C:0x54].hex()
        save_size = readle(header[0x5A:0x5E])
        srl_save_size = readle(header[0x5E:0x62])
        title_version = TitleVersion.from_int(readbe(header[0x9C:0x9E]))
        content_count = readbe(header[0x9E:0xA0])

        content_info_records_hash = header[0xA4:0xC4]

        content_info_records_raw = fp.read(0x900)
        if len(content_info_records_raw) != 0x900:
            raise InvalidTMDError('Content info records length is not 0x900')

        if verify_hashes:
            real_hash = sha256(content_info_records_raw)
            if content_info_records_hash != real_hash.digest():
                raise InvalidHashError('Content Info Records hash is invalid')

        content_chunk_records_raw = fp.read(content_count * CHUNK_RECORD_SIZE)

        chunk_records = []
        for cr_raw in (content_chunk_records_raw[i:i + CHUNK_RECORD_SIZE] for i in
                       range(0, content_count * CHUNK_RECORD_SIZE, CHUNK_RECORD_SIZE)):
            chunk_records.append(ContentChunkRecord(id=cr_raw[0:4].hex(),
                                                    cindex=readbe(cr_raw[4:6]),
                                                    type=ContentTypeFlags.from_int(readbe(cr_raw[6:8])),
                                                    size=readbe(cr_raw[8:16]),
                                                    hash=cr_raw[16:48]))

        info_records = []
        for ir_raw in (content_info_records_raw[i:i + 0x24] for i in range(0, 0x900, 0x24)):
            if ir_raw != b'\0' * 0x24:
                info_records.append(ContentInfoRecord(index_offset=readbe(ir_raw[0:2]),
                                                      command_count=readbe(ir_raw[2:4]),
                                                      hash=ir_raw[4:36]))

        if verify_hashes:
            chunk_records_hashed = set()
            for ir in info_records:
                to_hash = []
                for cr in chunk_records[ir.index_offset:ir.index_offset + ir.command_count]:
                    if cr in chunk_records_hashed:
                        raise InvalidTMDError('attempting to hash chunk record twice')

                    chunk_records_hashed.add(cr)
                    to_hash.append(cr)

                hashed = sha256(b''.join(bytes(x) for x in to_hash))
                if hashed.digest() != ir.hash:
                    raise InvalidInfoRecordError(ir)

        # unused vales are loaded only for use when re-building the binary tmd
        u_issuer = header[0:0x40].decode('ascii').rstrip('\0')
        u_version = header[0x40]
        u_ca_crl_version = header[0x41]
        u_signer_crl_version = header[0x42]
        u_reserved1 = header[0x43]
        u_system_version = header[0x44:0x4C]
        u_title_type = header[0x54:0x58]
        u_group_id = header[0x58:0x5A]
        u_reserved2 = header[0x62:0x66]
        u_srl_flag = header[0x66]  # is this one used for anything?
        u_reserved3 = header[0x67:0x98]
        u_access_rights = header[0x98:0x9C]
        u_boot_count = header[0xA0:0xA2]
        u_padding = header[0xA2:0xA4]

        return cls(title_id=title_id, save_size=save_size, srl_save_size=srl_save_size, title_version=title_version,
                   info_records=info_records, chunk_records=chunk_records, signature=(sig_type, signature),
                   _u_issuer=u_issuer, _u_version=u_version, _u_ca_crl_version=u_ca_crl_version,
                   _u_signer_crl_version=u_signer_crl_version, _u_reserved1=u_reserved1,
                   _u_system_version=u_system_version, _u_title_type=u_title_type, _u_group_id=u_group_id,
                   _u_reserved2=u_reserved2, _u_srl_flag=u_srl_flag, _u_reserved3=u_reserved3,
                   _u_access_rights=u_access_rights, _u_boot_count=u_boot_count, _u_padding=u_padding)

    @classmethod
    def from_file(cls, fn: str, *, verify_hashes: bool = True) -> 'TitleMetadataReader':
        with open(fn, 'rb') as f:
            return cls.load(f, verify_hashes=verify_hashes)

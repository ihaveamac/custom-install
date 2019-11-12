# This file is a part of ninfs.
#
# Copyright (c) 2017-2019 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE.md in the root of this project.

from enum import IntEnum
from functools import wraps
from hashlib import sha256
from io import BufferedIOBase
from os import environ
from os.path import getsize, join as pjoin
from struct import pack, unpack
from typing import TYPE_CHECKING

from Cryptodome.Cipher import AES
from Cryptodome.Hash import CMAC
from Cryptodome.Util import Counter

from .common import PyCTRError, _raise_if_closed
from .util import config_dirs, readbe, readle

if TYPE_CHECKING:
    # noinspection PyProtectedMember
    from Cryptodome.Cipher._mode_cbc import CbcMode
    # noinspection PyProtectedMember
    from Cryptodome.Cipher._mode_ctr import CtrMode
    # noinspection PyProtectedMember
    from Cryptodome.Cipher._mode_ecb import EcbMode
    from Cryptodome.Hash.CMAC import CMAC as CMACObject
    from typing import BinaryIO, Dict, List, Optional, Union

__all__ = ['CryptoError', 'OTPLengthError', 'CorruptBootromError', 'KeyslotMissingError', 'TicketLengthError',
           'BootromNotFoundError', 'CorruptOTPError', 'Keyslot', 'CryptoEngine']


class CryptoError(PyCTRError):
    """Generic exception for cryptography operations."""


class OTPLengthError(CryptoError):
    """OTP is the wrong length."""


class CorruptOTPError(CryptoError):
    """OTP hash does not match."""


class KeyslotMissingError(CryptoError):
    """Normal key is not set up for the keyslot."""


class BadMovableSedError(CryptoError):
    """movable.sed provided is invalid."""


class TicketLengthError(CryptoError):
    """Ticket is too small."""
    def __init__(self, length):
        super().__init__(length)

    def __str__(self):
        return f'0x350 expected, {self.args[0]:#x} given'


# wonder if I'm doing this right...
class BootromNotFoundError(CryptoError):
    """ARM9 bootROM was not found. Main argument is a tuple of checked paths."""


class CorruptBootromError(CryptoError):
    """ARM9 bootROM hash does not match."""


class Keyslot(IntEnum):
    TWLNAND = 0x03
    CTRNANDOld = 0x04
    CTRNANDNew = 0x05
    FIRM = 0x06
    AGB = 0x07

    CMACNANDDB = 0x0B

    NCCH93 = 0x18
    CMACCardSaveNew = 0x19
    CardSaveNew = 0x1A
    NCCH96 = 0x1B

    CMACAGB = 0x24
    NCCH70 = 0x25

    NCCH = 0x2C
    UDSLocalWAN = 0x2D
    StreetPass = 0x2E
    Save60 = 0x2F
    CMACSDNAND = 0x30

    CMACCardSave = 0x33
    SD = 0x34

    CardSave = 0x37
    BOSS = 0x38
    DownloadPlay = 0x39

    DSiWareExport = 0x3A

    CommonKey = 0x3D

    # anything after 0x3F is custom to PyCTR
    DecryptedTitlekey = 0x40


BOOT9_PROT_HASH = '7331f7edece3dd33f2ab4bd0b3a5d607229fd19212c10b734cedcaf78c1a7b98'

DEV_COMMON_KEY_0 = bytes.fromhex('55A3F872BDC80C555A654381139E153B')

common_key_y = (
    # eShop
    0xD07B337F9CA4385932A2E25723232EB9,
    # System
    0x0C767230F0998F1C46828202FAACBE4C,
    # Unknown
    0xC475CB3AB8C788BB575E12A10907B8A4,
    # Unknown
    0xE486EEE3D0C09C902F6686D4C06F649F,
    # Unknown
    0xED31BA9C04B067506C4497A35B7804FC,
    # Unknown
    0x5E66998AB4E8931606850FD7A16DD755
)

base_key_x = {
    # New3DS 9.3 NCCH
    0x18: (0x82E9C9BEBFB8BDB875ECC0A07D474374, 0x304BF1468372EE64115EBD4093D84276),
    # New3DS 9.6 NCCH
    0x1B: (0x45AD04953992C7C893724A9A7BCE6182, 0x6C8B2944A0726035F941DFC018524FB6),
    # 7x NCCH
    0x25: (0xCEE7D8AB30C00DAE850EF5E382AC5AF3, 0x81907A4B6F1B47323A677974CE4AD71B),
}

# global values to be copied to new CryptoEngine instances after the first one
_b9_key_x: 'Dict[int, int]' = {}
_b9_key_y: 'Dict[int, int]' = {}
_b9_key_normal: 'Dict[int, bytes]' = {}
_b9_extdata_otp: bytes = None
_b9_extdata_keygen: bytes = None
_b9_path: str = None
_otp_key: bytes = None
_otp_iv: bytes = None

b9_paths: 'List[str]' = []
for p in config_dirs:
    b9_paths.append(pjoin(p, 'boot9.bin'))
    b9_paths.append(pjoin(p, 'boot9_prot.bin'))
try:
    b9_paths.insert(0, environ['BOOT9_PATH'])
except KeyError:
    pass


def _requires_bootrom(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        if not self.b9_keys_set:
            raise KeyslotMissingError('bootrom is required to set up keys, see setup_keys_from_boot9')
        return method(self, *args, **kwargs)
    return wrapper


# used from http://www.falatic.com/index.php/108/python-and-bitwise-rotation
# converted to def because pycodestyle complained to me
def rol(val: int, r_bits: int, max_bits: int) -> int:
    return (val << r_bits % max_bits) & (2 ** max_bits - 1) |\
           ((val & (2 ** max_bits - 1)) >> (max_bits - (r_bits % max_bits)))


class _TWLCryptoWrapper:
    def __init__(self, cipher: 'CbcMode'):
        self._cipher = cipher

    def encrypt(self, data: bytes) -> bytes:
        data_len = len(data)
        data_rev = bytearray(data_len)
        for i in range(0, data_len, 0x10):
            data_rev[i:i + 0x10] = data[i:i + 0x10][::-1]

        data_out = bytearray(self._cipher.encrypt(bytes(data_rev)))

        for i in range(0, data_len, 0x10):
            data_out[i:i + 0x10] = data_out[i:i + 0x10][::-1]
        return bytes(data_out[0:data_len])

    decrypt = encrypt


class CryptoEngine:
    """Class for 3DS crypto operations, including encryption and key generation."""

    b9_keys_set: bool = False
    b9_path: str = None

    _b9_extdata_otp: bytes = None
    _b9_extdata_keygen: bytes = None

    _otp_device_id: int = None
    _otp_key: bytes = None
    _otp_iv: bytes = None

    _id0: bytes = None

    def __init__(self, boot9: str = None, dev: int = 0, setup_b9_keys: bool = True):
        self.key_x: Dict[int, int] = {}
        self.key_y: Dict[int, int] = {0x03: 0xE1A00005202DDD1DBD4DC4D30AB9DC76,
                                      0x05: 0x4D804F4E9990194613A204AC584460BE}
        self.key_normal: Dict[int, bytes] = {}

        self.dev = dev

        for keyslot, keys in base_key_x.items():
            self.key_x[keyslot] = keys[dev]

        if setup_b9_keys:
            self.setup_keys_from_boot9_file(boot9)

    @property
    @_requires_bootrom
    def b9_extdata_otp(self) -> bytes:
        return self._b9_extdata_otp

    @property
    @_requires_bootrom
    def b9_extdata_keygen(self) -> bytes:
        return self._b9_extdata_keygen

    @property
    @_requires_bootrom
    def otp_device_id(self) -> int:
        return self._otp_device_id

    @property
    @_requires_bootrom
    def otp_key(self) -> bytes:
        return self._otp_key

    @property
    @_requires_bootrom
    def otp_iv(self) -> bytes:
        return self._otp_iv

    @property
    def id0(self) -> bytes:
        if not self._id0:
            raise KeyslotMissingError('load a movable.sed with setup_sd_key')
        return self._id0

    def create_cbc_cipher(self, keyslot: Keyslot, iv: bytes) -> 'CbcMode':
        """Create AES-CBC cipher with the given keyslot."""
        try:
            key = self.key_normal[keyslot]
        except KeyError:
            raise KeyslotMissingError(f'normal key for keyslot 0x{keyslot:02x} is not set up')

        return AES.new(key, AES.MODE_CBC, iv)

    def create_ctr_cipher(self, keyslot: Keyslot, ctr: int) -> 'Union[CtrMode, _TWLCryptoWrapper]':
        """
        Create an AES-CTR cipher with the given keyslot.

        Normal and DSi crypto will be automatically chosen depending on keyslot.
        """
        try:
            key = self.key_normal[keyslot]
        except KeyError:
            raise KeyslotMissingError(f'normal key for keyslot 0x{keyslot:02x} is not set up')

        cipher = AES.new(key, AES.MODE_CTR, counter=Counter.new(128, initial_value=ctr))

        if keyslot < 0x04:
            return _TWLCryptoWrapper(cipher)
        else:
            return cipher

    def create_ecb_cipher(self, keyslot: Keyslot) -> 'EcbMode':
        """Create an AES-ECB cipher with the given keyslot."""
        try:
            key = self.key_normal[keyslot]
        except KeyError:
            raise KeyslotMissingError(f'normal key for keyslot 0x{keyslot:02x} is not set up')

        return AES.new(key, AES.MODE_ECB)

    def create_cmac_object(self, keyslot: Keyslot) -> 'CMACObject':
        """Create a CMAC object with the given keyslot."""
        try:
            key = self.key_normal[keyslot]
        except KeyError:
            raise KeyslotMissingError(f'normal key for keyslot 0x{keyslot:02x} is not set up')

        return CMAC.new(key, ciphermod=AES)

    def create_ctr_io(self, keyslot: Keyslot, fh: 'BinaryIO', ctr: int):
        """Create an AES-CTR read-write file object with the given keyslot."""
        return CTRFileIO(fh, self, keyslot, ctr)

    def create_cbc_io(self, keyslot: Keyslot, fh: 'BinaryIO', iv: bytes):
        """Create an AES-CBC read-only file object with the given keyslot."""
        return CBCFileIO(fh, self, keyslot, iv)

    @staticmethod
    def sd_path_to_iv(path: str) -> int:
        # ensure the path is lowercase
        path = path.lower()

        # SD Save Data Backup does a copy of the raw, encrypted file from the game's data directory
        # so we need to handle this and fake the path
        if path.startswith('/backup') and len(path) > 28:
            tid_upper = path[12:20]
            tid_lower = path[20:28]
            path = f'/title/{tid_upper}/{tid_lower}/data' + path[28:]

        path_hash = sha256(path.encode('utf-16le') + b'\0\0').digest()
        hash_p1 = readbe(path_hash[0:16])
        hash_p2 = readbe(path_hash[16:32])
        return hash_p1 ^ hash_p2

    def load_from_ticket(self, ticket: bytes):
        """Load a titlekey from a ticket and set keyslot 0x40 to the decrypted titlekey."""
        ticket_len = len(ticket)
        # TODO: probably support other sig types which would be different lengths
        # unlikely to happen in practice, but I would still like to
        if ticket_len < 0x2AC:
            raise TicketLengthError(ticket_len)

        titlekey_enc = ticket[0x1BF:0x1CF]
        title_id = ticket[0x1DC:0x1E4]
        common_key_index = ticket[0x1F1]

        if self.dev and common_key_index == 0:
            self.set_normal_key(0x3D, DEV_COMMON_KEY_0)
        else:
            self.set_keyslot('y', 0x3D, common_key_y[common_key_index])

        cipher = self.create_cbc_cipher(0x3D, title_id + (b'\0' * 8))
        self.set_normal_key(0x40, cipher.decrypt(titlekey_enc))

    def set_keyslot(self, xy: str, keyslot: int, key: 'Union[int, bytes]'):
        """Sets a keyslot to the specified key."""
        to_use = None
        if xy == 'x':
            to_use = self.key_x
        elif xy == 'y':
            to_use = self.key_y
        if isinstance(key, bytes):
            key = int.from_bytes(key, 'big' if keyslot > 0x03 else 'little')
        to_use[keyslot] = key
        try:
            self.key_normal[keyslot] = self.keygen(keyslot)
        except KeyError:
            pass

    def set_normal_key(self, keyslot: int, key: bytes):
        self.key_normal[keyslot] = key

    def keygen(self, keyslot: int) -> bytes:
        """Generate a normal key based on the keyslot."""
        if keyslot < 0x04:
            # DSi
            return self.keygen_twl_manual(self.key_x[keyslot], self.key_y[keyslot])
        else:
            # 3DS
            return self.keygen_manual(self.key_x[keyslot], self.key_y[keyslot])

    @staticmethod
    def keygen_manual(key_x: int, key_y: int) -> bytes:
        """Generate a normal key using the 3DS AES keyscrambler."""
        return rol((rol(key_x, 2, 128) ^ key_y) + 0x1FF9E9AAC5FE0408024591DC5D52768A, 87, 128).to_bytes(0x10, 'big')

    @staticmethod
    def keygen_twl_manual(key_x: int, key_y: int) -> bytes:
        """Generate a normal key using the DSi AES keyscrambler."""
        # usually would convert to LE bytes in the end then flip with [::-1], but those just cancel out
        return rol((key_x ^ key_y) + 0xFFFEFB4E295902582A680F5F1A4F3E79, 42, 128).to_bytes(0x10, 'big')

    def _copy_global_keys(self):
        self.key_x.update(_b9_key_x)
        self.key_y.update(_b9_key_y)
        self.key_normal.update(_b9_key_normal)
        self._otp_key = _otp_key
        self._otp_iv = _otp_iv
        self._b9_extdata_otp = _b9_extdata_otp
        self._b9_extdata_keygen = _b9_extdata_keygen

        self.b9_keys_set = True

    def setup_keys_from_boot9(self, b9: bytes):
        """Set up certain keys from an ARM9 bootROM dump."""
        global _otp_key, _otp_iv, _b9_extdata_otp, _b9_extdata_keygen
        if self.b9_keys_set:
            return

        if _b9_key_x:
            self._copy_global_keys()
            return

        b9_len = len(b9)
        if b9_len != 0x8000:
            raise CorruptBootromError(f'wrong length: {b9_len}')

        b9_hash_digest: str = sha256(b9).hexdigest()
        if b9_hash_digest != BOOT9_PROT_HASH:
            raise CorruptBootromError(f'expected: {BOOT9_PROT_HASH}; returned: {b9_hash_digest}')

        keyblob_offset = 0x5860
        otp_key_offset = 0x56E0
        if self.dev:
            keyblob_offset += 0x400
            otp_key_offset += 0x20

        _otp_key = b9[otp_key_offset:otp_key_offset + 0x10]
        _otp_iv = b9[otp_key_offset + 0x10:otp_key_offset + 0x20]

        keyblob: bytes = b9[keyblob_offset:keyblob_offset + 0x400]

        _b9_extdata_keygen = keyblob[0:0x200]
        _b9_extdata_otp = keyblob[0:0x24]

        # Original NCCH key, UDS local-WLAN CCMP key, StreetPass key, 6.0 save key
        _b9_key_x[0x2C] = _b9_key_x[0x2D] = _b9_key_x[0x2E] = _b9_key_x[0x2F] = readbe(keyblob[0x170:0x180])

        # SD/NAND AES-CMAC key, APT wrap key, Unknown, Gamecard savedata AES-CMAC
        _b9_key_x[0x30] = _b9_key_x[0x31] = _b9_key_x[0x32] = _b9_key_x[0x33] = readbe(keyblob[0x180:0x190])

        # SD key (loaded from movable.sed), movable.sed key, Unknown (used by friends module),
        #   Gamecard savedata actual key
        _b9_key_x[0x34] = _b9_key_x[0x35] = _b9_key_x[0x36] = _b9_key_x[0x37] = readbe(keyblob[0x190:0x1A0])

        # BOSS key, Download Play key + actual NFC key for generating retail amiibo keys, CTR-CARD hardware-crypto seed
        #   decryption key
        _b9_key_x[0x38] = _b9_key_x[0x39] = _b9_key_x[0x3A] = _b9_key_x[0x3B] = readbe(keyblob[0x1A0:0x1B0])

        # Unused
        _b9_key_x[0x3C] = readbe(keyblob[0x1B0:0x1C0])

        # Common key (titlekey crypto)
        _b9_key_x[0x3D] = readbe(keyblob[0x1C0:0x1D0])

        # Unused
        _b9_key_x[0x3E] = readbe(keyblob[0x1D0:0x1E0])

        # NAND partition keys
        _b9_key_y[0x04] = readbe(keyblob[0x1F0:0x200])
        # correct 0x05 KeyY not set by boot9.
        _b9_key_y[0x06] = readbe(keyblob[0x210:0x220])
        _b9_key_y[0x07] = readbe(keyblob[0x220:0x230])

        # Unused, Unused, DSiWare export key, NAND dbs/movable.sed AES-CMAC key
        _b9_key_y[0x08] = readbe(keyblob[0x230:0x240])
        _b9_key_y[0x09] = readbe(keyblob[0x240:0x250])
        _b9_key_y[0x0A] = readbe(keyblob[0x250:0x260])
        _b9_key_y[0x0B] = readbe(keyblob[0x260:0x270])

        _b9_key_normal[0x0D] = keyblob[0x270:0x280]

        self._copy_global_keys()

    def setup_keys_from_boot9_file(self, path: str = None):
        """Set up certain keys from an ARM9 bootROM file."""
        global _b9_path
        if self.b9_keys_set:
            return

        if _b9_key_x:
            self.b9_path = _b9_path
            self._copy_global_keys()
            return

        paths = (path,) if path else b9_paths

        for p in paths:
            try:
                b9_size = getsize(p)
                if b9_size in {0x8000, 0x10000}:
                    with open(p, 'rb') as f:
                        if b9_size == 0x10000:
                            f.seek(0x8000)
                        self.setup_keys_from_boot9(f.read(0x8000))
                        _b9_path = p
                        self.b9_path = p
                        return
            except FileNotFoundError:
                continue

        # if keys are not set...
        raise BootromNotFoundError(paths)

    @_requires_bootrom
    def setup_keys_from_otp(self, otp: bytes):
        """Set up console-unique keys from an OTP dump. Encrypted and decrypted are supported."""
        otp_len = len(otp)
        if otp_len != 0x100:
            raise OTPLengthError(otp_len)

        cipher_otp = AES.new(self.otp_key, AES.MODE_CBC, self.otp_iv)
        if otp[0:4] == b'\x0f\xb0\xad\xde':
            # decrypted otp
            otp_enc: bytes = cipher_otp.encrypt(otp)
            otp_dec = otp
        else:
            # encrypted otp
            otp_enc = otp
            otp_dec: bytes = cipher_otp.decrypt(otp)

        self._otp_device_id = int.from_bytes(otp_dec[4:8], 'little')

        otp_hash: bytes = otp_dec[0xE0:0x100]
        otp_hash_digest: bytes = sha256(otp_dec[0:0xE0]).digest()
        if otp_hash_digest != otp_hash:
            raise CorruptOTPError(f'expected: {otp_hash.hex()}; result: {otp_hash_digest.hex()}')

        otp_keysect_hash: bytes = sha256(otp_enc[0:0x90]).digest()

        self.set_keyslot('x', 0x11, otp_keysect_hash[0:0x10])
        self.set_keyslot('y', 0x11, otp_keysect_hash[0:0x10])

        # most otp code from https://github.com/Stary2001/3ds_tools/blob/master/three_ds/aesengine.py

        twl_cid_lo, twl_cid_hi = readle(otp_dec[0x08:0xC]), readle(otp_dec[0xC:0x10])
        twl_cid_lo ^= 0xB358A6AF
        twl_cid_lo |= 0x80000000
        twl_cid_hi ^= 0x08C267B7
        twl_cid_lo = twl_cid_lo.to_bytes(4, 'little')
        twl_cid_hi = twl_cid_hi.to_bytes(4, 'little')
        self.set_keyslot('x', 0x03, twl_cid_lo + b'NINTENDO' + twl_cid_hi)

        console_key_xy: bytes = sha256(otp_dec[0x90:0xAC] + self.b9_extdata_otp).digest()
        self.set_keyslot('x', 0x3F, console_key_xy[0:0x10])
        self.set_keyslot('y', 0x3F, console_key_xy[0x10:0x20])

        extdata_off = 0

        def gen(n: int) -> bytes:
            nonlocal extdata_off
            extdata_off += 36
            iv = self.b9_extdata_keygen[extdata_off:extdata_off+16]
            extdata_off += 16

            data = self.create_cbc_cipher(0x3F, iv).encrypt(self.b9_extdata_keygen[extdata_off:extdata_off + 64])

            extdata_off += n
            return data

        a = gen(64)
        for i in range(0x4, 0x8):
            self.set_keyslot('x', i, a[0:16])

        for i in range(0x8, 0xc):
            self.set_keyslot('x', i, a[16:32])

        for i in range(0xc, 0x10):
            self.set_keyslot('x', i, a[32:48])

        self.set_keyslot('x', 0x10, a[48:64])

        b = gen(16)
        off = 0
        for i in range(0x14, 0x18):
            self.set_keyslot('x', i, b[off:off + 16])
            off += 16

        c = gen(64)
        for i in range(0x18, 0x1c):
            self.set_keyslot('x', i, c[0:16])

        for i in range(0x1c, 0x20):
            self.set_keyslot('x', i, c[16:32])

        for i in range(0x20, 0x24):
            self.set_keyslot('x', i, c[32:48])

        self.set_keyslot('x', 0x24, c[48:64])

        d = gen(16)
        off = 0

        for i in range(0x28, 0x2c):
            self.set_keyslot('x', i, d[off:off + 16])
            off += 16

    @_requires_bootrom
    def setup_keys_from_otp_file(self, path: str):
        """Set up console-unique keys from an OTP file. Encrypted and decrypted are supported."""
        with open(path, 'rb') as f:
            self.setup_keys_from_otp(f.read(0x100))

    def setup_sd_key(self, data: bytes):
        """Set up the SD key from movable.sed. Must be 0x10 (only key), 0x120 (no cmac), or 0x140 (with cmac)."""
        if len(data) == 0x10:
            key = data
        elif len(data) in {0x120, 0x140}:
            key = data[0x110:0x120]
        else:
            raise BadMovableSedError(f'invalid length ({len(data):#x}')

        self.set_keyslot('y', Keyslot.SD, key)
        self.set_keyslot('y', Keyslot.CMACSDNAND, key)
        self.set_keyslot('y', Keyslot.DSiWareExport, key)

        key_hash = sha256(key).digest()[0:16]
        hash_parts = unpack('<IIII', key_hash)
        self._id0 = pack('>IIII', *hash_parts)

    def setup_sd_key_from_file(self, path: str):
        """Set up the SD key from a movable.sed file."""
        with open(path, 'rb') as f:
            self.setup_sd_key(f.read(0x140))


class _CryptoFileBase(BufferedIOBase):
    """Base class for CTR and CBC IO classes."""

    closed = False
    _reader: 'BinaryIO'

    def close(self):
        self.closed = True

    __del__ = close

    @_raise_if_closed
    def flush(self):
        self._reader.flush()

    @_raise_if_closed
    def tell(self) -> int:
        return self._reader.tell()

    @_raise_if_closed
    def readable(self) -> bool:
        return self._reader.readable()

    @_raise_if_closed
    def writable(self) -> bool:
        return self._reader.writable()

    @_raise_if_closed
    def seekable(self) -> bool:
        return self._reader.seekable()


class CTRFileIO(_CryptoFileBase):
    """Provides transparent read-write AES-CTR encryption as a file-like object."""

    def __init__(self, file: 'BinaryIO', crypto: 'CryptoEngine', keyslot: Keyslot, counter: int):
        self._reader = file
        self._crypto = crypto
        self._keyslot = keyslot
        self._counter = counter

    def __repr__(self):
        return f'{type(self).__name__}(file={self._reader!r}, keyslot={self._keyslot:#04x}, counter={self._counter!r})'

    @_raise_if_closed
    def read(self, size: int = -1) -> bytes:
        cur_offset = self.tell()
        data = self._reader.read(size)
        counter = self._counter + (cur_offset >> 4)
        cipher = self._crypto.create_ctr_cipher(self._keyslot, counter)
        # beginning padding
        cipher.decrypt(b'\0' * (cur_offset % 0x10))
        return cipher.decrypt(data)

    read1 = read  # probably make this act like read1 should, but this for now enables some other things to work

    @_raise_if_closed
    def write(self, data: bytes) -> int:
        cur_offset = self.tell()
        counter = self._counter + (cur_offset >> 4)
        cipher = self._crypto.create_ctr_cipher(self._keyslot, counter)
        # beginning padding
        cipher.encrypt(b'\0' * (cur_offset % 0x10))
        return self._reader.write(cipher.encrypt(data))

    @_raise_if_closed
    def seek(self, seek: int, whence: int = 0) -> int:
        # TODO: if the seek goes past the file, the data between the former EOF and seek point should also be encrypted.
        return self._reader.seek(seek, whence)

    def truncate(self, size: 'Optional[int]' = None) -> int:
        return self._reader.truncate(size)


class CBCFileIO(_CryptoFileBase):
    """Provides transparent read-only AES-CBC encryption as a file-like object."""

    def __init__(self, file: 'BinaryIO', crypto: 'CryptoEngine', keyslot: Keyslot, iv: bytes):
        self._reader = file
        self._crypto = crypto
        self._keyslot = keyslot
        self._iv = iv

    def __repr__(self):
        return f'{type(self).__name__}(file={self._reader!r}, keyslot={self._keyslot:#04x}, iv={self._iv!r})'

    @_raise_if_closed
    def read(self, size: int = -1):
        offset = self._reader.tell()

        # if encrypted, the block needs to be decrypted first
        # CBC requires a full block (0x10 in this case). and the previous
        #   block is used as the IV. so that's quite a bit to read if the
        #   application requires just a few bytes.
        # thanks Stary2001 for help with random-access crypto

        before = offset % 16
        if offset - before == 0:
            iv = self._iv
        else:
            # seek back one block to read it as iv
            self._reader.seek(-0x10 - before, 1)
            iv = self._reader.read(0x10)
        # this is done since we may not know the original size of the file
        # and the caller may have requested -1 to read all the remaining data
        data_before = self._reader.read(before)
        data_requested = self._reader.read(size)
        data_requested_len = len(data_requested)
        data_total_len = len(data_before) + data_requested_len
        if data_total_len % 16:
            data_after = self._reader.read(16 - (data_total_len % 16))
            self._reader.seek(-len(data_after), 1)
        else:
            data_after = b''
        cipher = self._crypto.create_cbc_cipher(self._keyslot, iv)
        # decrypt data, and cut off extra bytes
        return cipher.decrypt(
            b''.join((data_before, data_requested, data_after))
        )[before:data_requested_len + before]

    read1 = read  # probably make this act like read1 should, but this for now enables some other things to work

    @_raise_if_closed
    def seek(self, seek: int, whence: int = 0):
        # even though read re-seeks to read required data, this allows the underlying object to handle seek how it wants
        return self._reader.seek(seek, whence)

    @_raise_if_closed
    def writable(self) -> bool:
        return False

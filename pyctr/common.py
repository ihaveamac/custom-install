# This file is a part of ninfs.
#
# Copyright (c) 2017-2019 Ian Burgwin
# This file is licensed under The MIT License (MIT).
# You can find the full license text in LICENSE.md in the root of this project.

from functools import wraps
from io import BufferedIOBase
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # this is a lazy way to make type checkers stop complaining
    from typing import BinaryIO
    BufferedIOBase = BinaryIO


class PyCTRError(Exception):
    """Common base class for all PyCTR errors."""


def _raise_if_closed(method):
    @wraps(method)
    def decorator(self: '_ReaderOpenFileBase', *args, **kwargs):
        if self._reader.closed:
            self.closed = True
        if self.closed:
            raise ValueError('I/O operation on closed file')
        return method(self, *args, **kwargs)
    return decorator


class _ReaderOpenFileBase(BufferedIOBase):
    """Base class for all open files for Reader classes."""

    _seek = 0
    _info = None
    closed = False

    def __init__(self, reader, path):
        self._reader = reader
        self._path = path

    def __repr__(self):
        return f'<{type(self).__name__} path={self._path!r} info={self._info!r} reader={self._reader!r}>'

    @_raise_if_closed
    def read(self, size: int = -1) -> bytes:
        if size == -1:
            size = self._info.size - self._seek
        data = self._reader.get_data(self._info, self._seek, size)
        self._seek += len(data)
        return data

    read1 = read  # probably make this act like read1 should, but this for now enables some other things to work

    @_raise_if_closed
    def seek(self, seek: int, whence: int = 0) -> int:
        if whence == 0:
            if seek < 0:
                raise ValueError(f'negative seek value {seek}')
            self._seek = min(seek, self._info.size)
        elif whence == 1:
            self._seek = max(self._seek + seek, 0)
        elif whence == 2:
            self._seek = max(self._info.size + seek, 0)
        return self._seek

    @_raise_if_closed
    def tell(self) -> int:
        return self._seek

    @_raise_if_closed
    def readable(self) -> bool:
        return True

    @_raise_if_closed
    def writable(self) -> bool:
        return False

    @_raise_if_closed
    def seekable(self) -> bool:
        return True

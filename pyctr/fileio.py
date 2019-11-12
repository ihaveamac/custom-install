from io import BufferedIOBase
from threading import Lock
from weakref import WeakValueDictionary
from typing import TYPE_CHECKING

from .common import _raise_if_closed

if TYPE_CHECKING:
    from typing import BinaryIO

# this prevents two SubsectionIO instances on the same file object from interfering with eachother
_lock_objects = WeakValueDictionary()


class SubsectionIO(BufferedIOBase):
    """Provides read-write access to a subsection of a file."""

    closed = False
    _seek = 0

    def __init__(self, file: 'BinaryIO', offset: int, size: int):
        # get existing Lock object for file, or create a new one
        file_id = id(file)
        try:
            self._lock = _lock_objects[file_id]
        except KeyError:
            self._lock = Lock()
            _lock_objects[file_id] = self._lock

        self._reader = file
        self._offset = offset
        self._size = size
        # subsection end is stored for convenience
        self._end = offset + size

    def __repr__(self):
        return f'{type(self).__name__}(file={self._reader!r}, offset={self._offset!r}, size={self._size!r})'

    def close(self):
        self.closed = True
        # remove Lock reference, so it can be automatically removed from the WeakValueDictionary once all SubsectionIO
        #   instances for the base file are closed
        self._lock = None

    __del__ = close

    @_raise_if_closed
    def read(self, size: int = -1) -> bytes:
        if size == -1:
            size = self._size - self._seek
        if self._offset + self._seek > self._end:
            # if attempting to read after the section, return nothing
            return b''
        if self._seek + size > self._size:
            size = self._size - self._seek
           
        with self._lock:
            self._reader.seek(self._seek + self._offset)
            data = self._reader.read(size)

        self._seek += len(data)
        return data

    @_raise_if_closed
    def seek(self, seek: int, whence: int = 0) -> int:
        if whence == 0:
            if seek < 0:
                raise ValueError(f'negative seek value {seek}')
            self._seek = min(seek, self._size)
        elif whence == 1:
            self._seek = max(self._seek + seek, 0)
        elif whence == 2:
            self._seek = max(self._size + seek, 0)
        else:
            if not isinstance(whence, int):
                raise TypeError(f'an integer is required (got type {type(whence).__name__}')
            raise ValueError(f'invalid whence ({seek}, should be 0, 1 or 2)')
        return self._seek

    @_raise_if_closed
    def write(self, data: bytes) -> int:
        if self._seek > self._size:
            # attempting to write past subsection
            return 0
        data_len = len(data)
        data_end = data_len + self._seek
        if data_end > self._size:
            data = data[:-(data_end - self._size)]

        with self._lock:
            self._reader.seek(self._seek + self._offset)
            data_written = self._reader.write(data)

        self._seek += data_written
        return data_written

    @_raise_if_closed
    def readable(self) -> bool:
        return self._reader.readable()

    @_raise_if_closed
    def writable(self) -> bool:
        return self._reader.writable()

    @_raise_if_closed
    def seekable(self) -> bool:
        return self._reader.seekable()

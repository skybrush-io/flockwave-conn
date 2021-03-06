"""File-based connection object."""

from os import PathLike
from trio import open_file
from typing import Union

from .base import FDConnectionBase, ConnectionState
from .factory import create_connection

__all__ = ("FileConnection",)


@create_connection.register("file")
class FileConnection(FDConnectionBase):
    """Connection object that reads its incoming data from a file or
    file-like object.
    """

    def __init__(
        self,
        path: Union[bytes, str, PathLike],
        mode: str = "rb",
        autoflush: bool = False,
    ):
        """Constructor.

        Parameters:
            path: path to the file to read the incoming data from
            mode: the mode to open the file with
            autoflush: whether to flush the file automatically after each write
        """
        super(FileConnection, self).__init__()

        self.autoflush = bool(autoflush)
        self._path = path
        self._mode = mode

    async def close(self) -> None:
        """Closes the file connection."""
        if self.state == ConnectionState.DISCONNECTED:
            return

        self._set_state(ConnectionState.DISCONNECTING)
        await self._file_object.close()
        self._detach()
        self._set_state(ConnectionState.DISCONNECTED)

    async def open(self) -> None:
        """Opens the file connection."""
        if self.state in (ConnectionState.CONNECTED, ConnectionState.CONNECTING):
            return

        self._set_state(ConnectionState.CONNECTING)
        self._attach(await open_file(self._path, self._mode))
        self._set_state(ConnectionState.CONNECTED)

    async def read(self, size: int = -1) -> bytes:
        """Reads the given number of bytes from the connection.

        Parameters:
            size: the number of bytes to read; -1 means to read all available
                data

        Returns:
            the data that was read, or an empty bytes object if the end of file
            was reached
        """
        return await self._file_object.read(size)

    async def write(self, data: bytes) -> None:
        """Writes the given data to the connection.

        Parameters:
            data: the data to write
        """
        await self._file_object.write(data)
        if self.autoflush:
            await self.flush()

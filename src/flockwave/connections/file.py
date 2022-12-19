"""File-based connection object."""

import sys

from os import fdopen, PathLike
from trio import open_file
from typing import Any, Optional, Union

from .base import FDConnectionBase
from .factory import create_connection

__all__ = ("FileConnection",)


@create_connection.register("file")
class FileConnection(FDConnectionBase):
    """Connection object that reads its incoming data from a file or
    file-like object, or writes its data to a file or file-like object.
    """

    def __init__(
        self,
        path: Union[bytes, str, PathLike],
        mode: str = "rb",
        autoflush: bool = False,
    ):
        """Constructor.

        Parameters:
            path: path to the file to read from or to write to
            mode: the mode to open the file with
            autoflush: whether to flush the file automatically after each write
        """
        super().__init__(autoflush=autoflush)

        self._path = path
        self._mode = mode

    async def _get_file_object_during_open(self) -> Any:
        return await open_file(self._path, self._mode)


@create_connection.register("fd")
class FDConnection(FDConnectionBase):
    """Connection object that reads its incoming data from a numeric file
    descriptor, or writes its data to a numeric file descrptior.
    """

    def __init__(
        self,
        path: Union[bytes, str, int],
        mode: Optional[str] = None,
        autoflush: bool = False,
    ):
        """Constructor.

        Parameters:
            path: integer file descriptor to read from or to write to
            mode: the mode to open the file with
            autoflush: whether to flush the file automatically after each write
        """
        super().__init__(autoflush=autoflush)

        self._fd = int(path)
        self._mode = mode

    async def _get_file_object_during_open(self) -> Any:
        if self._mode is None:
            if self._fd == 0:
                mode = "r"
            elif self._fd == 1 or self._fd == 2:
                mode = "w"
            else:
                raise RuntimeError("mode must be specified")
        else:
            mode = self._mode
        if self._fd == 0:
            return sys.stdin
        elif self._fd == 1:
            return sys.stdout
        elif self._fd == 2:
            return sys.stderr
        else:
            return fdopen(self._fd, mode)

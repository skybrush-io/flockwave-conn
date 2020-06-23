"""Class that implements a Trio-style channel object that takes data from a
ReadableConnection_ and yields parsed message objects.
"""

from collections import deque
from inspect import iscoroutinefunction
from trio import EndOfChannel
from trio.abc import ReceiveChannel

from .types import MessageType, Parser, RawType, Reader

__all__ = ("ParserChannel",)


class ParserChannel(ReceiveChannel[MessageType]):
    """Trio-style ReceiveChannel_ that takes data from a ReadableConnection_
    and yields parsed message objects.
    """

    def __init__(self, reader: Reader[RawType], parser: Parser[RawType, MessageType]):
        if iscoroutinefunction(getattr(reader, "read", None)):
            # Reader is a Connection
            self._reader = reader.read
            self._closer = getattr(reader, "close", None)
        elif iscoroutinefunction(reader):
            self._reader = reader
            self._closer = None
        else:
            raise TypeError(
                f"ReadableConnection or async function expected, got {type(reader)}"
            )

        if callable(getattr(parser, "feed", None)):
            self._parser = parser.feed
        elif callable(parser):
            self._parser = parser
        else:
            raise TypeError(f"Parser or callable expected, got {type(parser)}")

        self._pending = deque()

    async def aclose(self) -> None:
        if self._closer:
            await self._closer()

    async def receive(self) -> MessageType:
        while not self._pending:
            await self._read()
        return self._pending.popleft()

    async def _read(self) -> None:
        """Reads the pending bytes using the associated reader function and
        feeds the parsed messages into the pending list.

        Raises:
            EndOfChannel: if there is no more data to read from the connection
        """
        data = await self._reader()
        if not data:
            raise EndOfChannel()
        self._pending.extend(self._parser(data))

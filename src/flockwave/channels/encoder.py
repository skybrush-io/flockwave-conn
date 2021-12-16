"""Class that implements a Trio-style channel object that encodes messages
and writes them to a WritableConnection_.
"""

from inspect import iscoroutinefunction
from typing import Awaitable, Callable

from trio.abc import SendChannel

from .types import Encoder, MessageType, RawType, Writer


class EncoderChannel(SendChannel[MessageType]):
    """Trio-style SendChannel_ that encodes objects and writes them to a
    WritableConnection_.
    """

    _writer: Callable[..., Awaitable[None]]

    def __init__(self, writer: Writer[RawType], encoder: Encoder[MessageType, RawType]):
        if iscoroutinefunction(getattr(writer, "write", None)):
            # Writer is a Connection
            self._writer = writer.writer  # type: ignore
            self._closer = getattr(writer, "close", None)
        elif iscoroutinefunction(writer):
            self._writer = writer  # type: ignore
            self._closer = None
        else:
            raise TypeError(
                f"WritableConnection or async function expected, got {type(writer)}"
            )

        self._encoder = encoder

    async def aclose(self) -> None:
        if self._closer:
            await self._closer()

    async def send(self, value: MessageType) -> None:
        await self._writer(self._encoder(value))

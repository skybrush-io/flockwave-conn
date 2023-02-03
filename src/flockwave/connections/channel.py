"""Dummy connection that does nothing."""

from trio import sleep
from trio.abc import ReceiveChannel, SendChannel
from typing import TypeVar

from .base import ConnectionBase, RWConnection

__all__ = ("ChannelConnection",)

TIn = TypeVar("TIn")
TOut = TypeVar("TOut")


class ChannelConnection(ConnectionBase, RWConnection[TIn, TOut]):
    """Connection that uses a pair of Trio channels, one for reading and one
    for writing.

    This is used to implement a loopback connection pair with two in-memory
    queues.
    """

    _tx: SendChannel[TOut]
    _rx: ReceiveChannel[TIn]

    def __init__(self, tx: SendChannel[TOut], rx: ReceiveChannel[TIn]):
        super().__init__()
        self._tx = tx
        self._rx = rx

    async def _open(self) -> None:
        # Force a Trio checkpoint
        await sleep(0)

    async def _close(self) -> None:
        await self._tx.aclose()
        await self._rx.aclose()

    async def read(self) -> TIn:
        return await self._rx.receive()

    async def write(self, data: TOut) -> None:
        await self._tx.send(data)

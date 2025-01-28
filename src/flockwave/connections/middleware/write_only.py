from trio import sleep_forever
from typing import Generic, TypeVar

from flockwave.connections.base import RWConnection

from .base import ConnectionMiddleware

__all__ = ("WriteOnlyMiddleware",)

RT = TypeVar("RT")
WT = TypeVar("WT")


class WriteOnlyMiddleware(ConnectionMiddleware[RWConnection[RT, WT]], Generic[RT, WT]):
    """Middleware that replaces the read operation of a connection with a
    null reader that never returns anything.

    This middleware can be used to simulate one-way outbound links on top of an
    otherwise bidirectional connection.
    """

    async def read(self) -> RT:
        await sleep_forever()

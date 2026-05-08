from typing import Generic, TypeVar, cast

from trio import sleep_forever

from flockwave.connections.base import RWConnection

from .base import ConnectionMiddleware

__all__ = ("WriteOnlyMiddleware",)

RT = TypeVar("RT")
WT = TypeVar("WT")

C = TypeVar("C", bound="RWConnection")


class WriteOnlyMiddleware(ConnectionMiddleware[RWConnection[RT, WT]], Generic[RT, WT]):
    """Middleware that replaces the read operation of a connection with a
    null reader that never returns anything.

    This middleware can be used to simulate one-way outbound links on top of an
    otherwise bidirectional connection.
    """

    @classmethod
    def wrap(cls, connection: C) -> C:
        return cast(C, cls(connection))

    async def read(self) -> RT:
        await sleep_forever()

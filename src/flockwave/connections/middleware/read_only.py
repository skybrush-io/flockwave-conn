from typing import Generic, TypeVar, cast

from flockwave.connections.base import RWConnection

from .base import ConnectionMiddleware

__all__ = ("ReadOnlyMiddleware",)

RT = TypeVar("RT")
WT = TypeVar("WT")

C = TypeVar("C", bound="RWConnection")


class ReadOnlyMiddleware(ConnectionMiddleware[RWConnection[RT, WT]], Generic[RT, WT]):
    """Middleware that replaces the write operation of a connection with a
    null writer that always returns immediately.

    This middleware can be used to simulate one-way outbound links on top of an
    otherwise bidirectional connection.
    """

    @classmethod
    def wrap(cls, connection: C) -> C:
        return cast(C, cls(connection))

    async def write(self, data: WT) -> None:
        pass

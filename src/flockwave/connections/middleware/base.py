"""Base middleware classes."""

from typing import Generic, TypeVar
from wrapt import ObjectProxy

from flockwave.connections.base import Connection

__all__ = ("ConnectionMiddleware",)


T = TypeVar("T", bound="Connection")


class ConnectionMiddleware(ObjectProxy, Generic[T]):
    """Base class for middleware that wrap connectin objects to provide
    additional functionality.
    """

    __wrapped__: T

    async def __aenter__(self):
        result = await self.__wrapped__.__aenter__()
        return self if result is self.__wrapped__ else result

    async def __aexit__(self, exc_type, exc_value, traceback):
        return await self.__wrapped__.__aexit__(exc_type, exc_value, traceback)

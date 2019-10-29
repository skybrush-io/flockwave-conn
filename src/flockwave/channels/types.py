from ..connections import ReadableConnection, WritableConnection

from typing import Awaitable, Callable, List, TypeVar, Union

__all__ = ("Encoder", "MessageType", "Parser", "RawType", "Reader", "Writer")

RawType = TypeVar("RawType")
MessageType = TypeVar("MessageType")

Reader = Union[Callable[[], Awaitable[RawType]], ReadableConnection[RawType]]
Writer = Union[Callable[[RawType], None], WritableConnection[RawType]]

Parser = Callable[[RawType], List[MessageType]]
Encoder = Callable[[MessageType], RawType]

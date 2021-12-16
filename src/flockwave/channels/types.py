from __future__ import annotations

from typing import Awaitable, Callable, Iterable, TypeVar, Union, TYPE_CHECKING

from ..connections import ReadableConnection, WritableConnection

if TYPE_CHECKING:
    from tinyrpc.protocols import RPCRequest, RPCResponse

__all__ = ("Encoder", "MessageType", "Parser", "RawType", "Reader", "Writer")

RawType = TypeVar("RawType")
MessageType = TypeVar("MessageType")

Reader = Union[Callable[[], Awaitable[RawType]], ReadableConnection[RawType]]
Writer = Union[Callable[[RawType], None], WritableConnection[RawType]]

Parser = Callable[[RawType], Iterable[MessageType]]
Encoder = Callable[[MessageType], RawType]

RPCRequestHandler = Callable[
    ["RPCRequest"], Union["RPCResponse", Awaitable["RPCResponse"]]
]

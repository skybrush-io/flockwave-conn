from __future__ import annotations

from typing import Awaitable, Callable, Iterable, TypeVar, Union, TYPE_CHECKING

from ..connections import ReadableConnection, WritableConnection

if TYPE_CHECKING:
    from tinyrpc.protocols import RPCRequest, RPCResponse

__all__ = (
    "Encoder",
    "MessageType",
    "Parser",
    "RawType",
    "Reader",
    "Writer",
)

RawType = TypeVar("RawType")
"""Type variable that is used to indicate the raw (encoded) type of a message
on a MessageChannel.
"""

MessageType = TypeVar("MessageType")
"""Type variable that is used to indicate the decoded, object-like type of a
message on a MessageChannel.
"""

Reader = Union[Callable[[], Awaitable[RawType]], ReadableConnection[RawType]]
Writer = Union[Callable[[RawType], None], WritableConnection[RawType]]

Parser = Callable[[RawType], Iterable[MessageType]]
Encoder = Callable[[MessageType], RawType]

RPCRequestHandler = Callable[
    ["RPCRequest"], Union["RPCResponse", Awaitable["RPCResponse"]]
]

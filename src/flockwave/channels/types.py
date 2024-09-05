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
message on a MessageChannel. For channels that involve addressing, this is
usually a tuple of a "real" message type and an address. For channels that do
not involve addressing, this is the "real" message type only.
"""

BroadcastMessageType = TypeVar("BroadcastMessageType")
"""Type variable that is used to indicate the decoded, object-like type of a
message on a MessageChannel when the message is used for broadcasting purposes.
Since broadcasting does not need a target address, this is different from
MessageType in the sense that it is always the "real" message type only, without
an address component, even for channels that use addressing.
"""

Reader = Union[Callable[[], Awaitable[RawType]], ReadableConnection[RawType]]
Writer = Union[Callable[[RawType], None], WritableConnection[RawType]]

Parser = Callable[[RawType], Iterable[MessageType]]
Encoder = Callable[[MessageType], RawType]

RPCRequestHandler = Callable[
    ["RPCRequest"], Union["RPCResponse", Awaitable["RPCResponse"]]
]

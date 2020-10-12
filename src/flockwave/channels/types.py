from ..connections import ReadableConnection, WritableConnection

try:
    from tinyrpc.protocols import RPCRequest, RPCResponse
except ImportError:
    RPCResponse, RPCResponse = None, None
    RPCRequest = "RPCRequest"
    RPCResponse = "RPCResponse"

from typing import Awaitable, Callable, List, TypeVar, Union

__all__ = ("Encoder", "MessageType", "Parser", "RawType", "Reader", "Writer")

RawType = TypeVar("RawType")
MessageType = TypeVar("MessageType")

Reader = Union[Callable[[], Awaitable[RawType]], ReadableConnection[RawType]]
Writer = Union[Callable[[RawType], None], WritableConnection[RawType]]

Parser = Callable[[RawType], List[MessageType]]
Encoder = Callable[[MessageType], RawType]

if RPCRequest:
    RPCRequestHandler = Callable[
        [RPCRequest], Union[RPCResponse, Awaitable[RPCResponse]]
    ]
else:
    RPCRequestHandler = Callable[
        ["RPCRequest"], Union["RPCResponse", Awaitable["RPCResponse"]]
    ]

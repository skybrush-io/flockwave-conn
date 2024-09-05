"""Class that implements a Trio-style channel object that takes data from a
ReadableConnection_ and yields parsed message objects, or takes messages,
encodes them and writes them to a WritableConnection_.
"""

from __future__ import annotations

from collections import deque
from contextlib import asynccontextmanager
from logging import Logger
from trio import EndOfChannel
from trio.abc import Channel
from typing import Generic, Optional, Union, TYPE_CHECKING, cast

from flockwave.connections.base import BroadcastConnection, RWConnection
from flockwave.connections.capabilities import get_connection_capabilities
from flockwave.connections.errors import NoBroadcastAddressError

from .types import (
    BroadcastMessageType,
    Encoder,
    MessageType,
    Parser,
    RawType,
    RPCRequestHandler,
)

__all__ = ("BroadcastMessageChannel", "MessageChannel")

if TYPE_CHECKING:
    from tinyrpc.dispatch import RPCDispatcher
    from tinyrpc.protocols import RPCProtocol


class MessageChannel(Generic[MessageType, RawType], Channel[MessageType]):
    """Trio-style Channel_ that wraps a readable-writable connection and
    uses a parser to decode the messages read from the connection and an
    encoder to encode the messages to the wire format of the connection.
    """

    _connection: RWConnection[RawType, RawType]
    _encoder: Encoder[MessageType, RawType]
    _parser: Parser[RawType, MessageType]

    @classmethod
    def for_rpc_protocol(
        cls, protocol: RPCProtocol, connection: RWConnection[RawType, RawType]
    ):
        """Helper method to construct a message channel that will send and
        receive messages using the given RPC protocol.

        Parameters:
            protocol: the protocol to use on the message channel
        """
        from flockwave.encoders.rpc import create_rpc_encoder
        from flockwave.parsers.rpc import create_rpc_parser

        # Create a parser-encoder pair that will be used to parse incoming messages
        # and serialize outgoing messages
        parser = create_rpc_parser(protocol=protocol)
        encoder = create_rpc_encoder(protocol=protocol)

        # Wrap the parser and the encoder in a MessageChannel
        result = cls(connection, parser=parser, encoder=encoder)  # type: ignore
        result._protocol = protocol
        return result

    def __init__(
        self,
        connection: RWConnection[RawType, RawType],
        parser: Parser[RawType, MessageType],
        encoder: Encoder[MessageType, RawType],
    ):
        self._connection = connection
        self._encoder = encoder
        self._pending = deque()
        self._protocol = None

        if callable(getattr(parser, "feed", None)):
            self._parser = parser.feed
        elif callable(parser):
            self._parser = parser
        else:
            raise TypeError(f"Parser or callable expected, got {type(parser)}")

    async def aclose(self) -> None:
        await self._connection.close()

    async def receive(self) -> MessageType:
        while not self._pending:
            await self._read()
        return self._pending.popleft()

    async def send(self, value: MessageType) -> None:
        await self._connection.write(self._encoder(value))

    @asynccontextmanager
    async def serve_rpc_requests(
        self,
        handler: Union[RPCRequestHandler, "RPCDispatcher"],
        log: Optional[Logger] = None,
        timeout: float = 5,
    ):
        """Sets up a context that uses this message channel to serve remote
        procedure call (RPC) requests.

        Parameters:
            handler: handler function or method dispatcher that we will invoke
                when we receive a request from our peer
            log: optional logger to use for logging error messages and warnings
            timeout: default timeout for requests, in seconds

        Yields:
            a function that can be used to send RPC requests to our peer. The
            function must be called with the name of the RPC method to call
            as well as positional and keyword arguments to the call. The
            `timeout` and `one_way` keyword arguments are handled differently:
            `timeout` specifies the maximum number of seconds to wait for the
            response of the request (and it overrides the default timeout given
            at the time when `serve_rpc_requests()`  was called), while
            `one_way` specifies whether the request needs a response (`False`,
            which is the default) or not (`True`).
        """
        from .rpc import serve_rpc_requests

        if self._protocol is None:
            raise ValueError(
                f"{self.__class__.__name__} was not created with .for_rpc_protocol()"
            )

        async with serve_rpc_requests(
            self,
            create_request=self._protocol.create_request,
            handler=handler,
            log=log,
            timeout=timeout,
        ) as sender:
            yield sender

    async def _read(self) -> None:
        """Reads the pending bytes using the associated reader function and
        feeds the parsed messages into the pending list.

        Raises:
            EndOfChannel: if there is no more data to read from the connection
        """
        data = await self._connection.read()
        if not data:
            raise EndOfChannel()
        self._pending.extend(self._parser(data))


class BroadcastMessageChannel(
    Generic[MessageType, RawType, BroadcastMessageType],
    MessageChannel[MessageType, RawType],
):
    """MessageChannel_ subclass that provides a dedicated method for sending a
    message with broadcast semantics.
    """

    _broadcast_encoder: Encoder[BroadcastMessageType, RawType]

    _can_broadcast: bool = False
    """Cached property that holds whether the underlying connection can
    broadcast.
    """

    def __init__(
        self,
        connection: RWConnection[RawType, RawType],
        parser: Parser[RawType, MessageType],
        encoder: Encoder[MessageType, RawType],
        broadcast_encoder: Encoder[BroadcastMessageType, RawType],
    ):
        super().__init__(connection, parser, encoder)

        self._broadcast_encoder = broadcast_encoder

        cap = get_connection_capabilities(self._connection)
        self._can_broadcast = cap["can_broadcast"]

    async def broadcast(self, value: BroadcastMessageType) -> None:
        """Broadcasts the given message on the channel. No-op if the underlying
        connection has no broadcast address at the moment but _could_ broadcast
        in theory. Falls back to sending the message if the underlying
        connection has no broadcast capabilities.
        """
        encoded = self._broadcast_encoder(value)
        if self._can_broadcast:
            conn = cast(BroadcastConnection[RawType], self._connection)
            try:
                await conn.broadcast(encoded)
            except NoBroadcastAddressError:
                pass
        else:
            await self._connection.write(encoded)

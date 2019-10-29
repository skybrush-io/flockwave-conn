"""Class that implements a Trio-style channel object that takes data from a
ReadableConnection_ and yields parsed message objects, or takes messages,
encodes them and writes them to a WritableConnection_.
"""

from collections import deque
from contextlib import asynccontextmanager
from inspect import iscoroutinefunction
from logging import Logger
from tinyrpc.dispatch import RPCDispatcher
from tinyrpc.protocols import RPCProtocol, RPCRequest, RPCResponse
from trio import EndOfChannel, fail_after, open_memory_channel, open_nursery
from trio.abc import Channel
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

from flockwave.encoders.rpc import create_rpc_encoder
from flockwave.parsers.rpc import create_rpc_parser

from ..connections import Connection

from .types import Encoder, MessageType, Parser, RawType
from .utils import Future

__all__ = ("MessageChannel",)


RPCRequestHandler = Callable[[RPCRequest], Union[RPCResponse, Awaitable[RPCResponse]]]


class MessageChannel(Channel[MessageType]):
    """Trio-style Channel_ that wraps a readable-writable connection and
    uses a parser to decode the messages read from the connection and an
    encoder to encode the messages to the wire format of the connection.
    """

    @classmethod
    def for_rpc_protocol(cls, protocol: RPCProtocol, connection: Connection):
        """Helper method to construct a message channel that will send and
        receive messages using the given RPC protocol.

        Parameters:
            protocol: the protocol to use on the message channel
        """
        # Create a parser-encoder pair that will be used to parse incoming messages
        # and serialize outgoing messages
        parser = create_rpc_parser(protocol=protocol)
        encoder = create_rpc_encoder(protocol=protocol)

        # Wrap the parser and the encoder in a MessageChannel
        result = cls(connection, parser=parser, encoder=encoder)
        result._protocol = protocol
        return result

    def __init__(
        self,
        connection: Connection,
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
        handler: Union[RPCRequestHandler, RPCDispatcher],
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


@asynccontextmanager
async def serve_rpc_requests(
    channel: MessageChannel,
    *,
    create_request: Callable[[str, List[Any], Dict[str, Any]], RPCRequest],
    handler: Union[RPCRequestHandler, RPCDispatcher],
    log: Optional[Logger] = None,
    timeout: float = 5,
):
    """Sets up a context that allows us to use the given connection for
    remote procedure calls (RPC) with the given protocol.

    Parameters:
        channel: the channel to use
        create_request: function that can be called with an RPC method name,
            the list of positional arguments and the dictionary holding
            the keyword arguments, and that will return an RPC request
            object that can be sent over the channel
        handler: handler function or method dispatcher that we will invoke
            when we receive a request from our peer
        log: optional logger to use for logging error messages and warnings
        timeout: default timeout for requests, in seconds
    """
    handler_is_async = iscoroutinefunction(handler)

    # If we received an RPCDispatcher as a handler, use its dispatch method
    if isinstance(handler, RPCDispatcher):
        handler = handler.dispatch

    # Create a queue in which one can post outbound messages
    out_queue_tx, out_queue_rx = open_memory_channel(0)

    # Create a map that maps pending requests that we have sent to the
    # corresponding events that we need to set when the response arrives
    pending_requests = {}

    # Store the default timeout
    default_timeout = timeout

    async def handle_single_inbound_message(message) -> None:
        """Task that handles a single inbound message."""

        if isinstance(message, RPCRequest):
            # TODO(ntamas): send this to a worker?
            if handler_is_async:
                response = await handler(message)
            else:
                response = handler(message)
            if response and not message.one_way:
                await out_queue_tx.send(response)
        elif isinstance(message, RPCResponse):
            request_id = message.unique_id
            future = pending_requests.get(request_id)
            if future:
                if not future.done():
                    if hasattr(message, "error"):
                        future.set_exception(message.error)
                    else:
                        future.set_result(message.result)
                else:
                    if log:
                        log.warn(
                            "Duplicate response received for request {!r}".format(
                                request_id
                            )
                        )
            else:
                if log:
                    log.warn(
                        "Stale response received for request {!r}".format(request_id)
                    )
        else:
            if log:
                log.warn("Received unknown message type: {!r}".format(type(message)))

    async def handle_inbound_messages() -> None:
        """Task that handles incoming messages and forwards RPC requests to
        the dispatcher function.
        """
        async with out_queue_tx:
            async for message in channel:
                await handle_single_inbound_message(message)

    async def handle_outbound_messages() -> None:
        """Task that handles the sending of outbound messages on the
        connection.
        """
        async with out_queue_rx:
            async for message in out_queue_rx:
                await channel.send(message)

    async def send_request(
        method: str, *args, one_way=False, timeout=None, **kwds
    ) -> RPCResponse:
        """Sends an RPC request with the given method. Additional positional
        and keyword arguments are forwarded intact to the remote side.

        Parameters:
            method: the method to send
            one_way: whether the request is one-way (i.e. we are not interested
                in a response)
            timeout: number of seconds to wait for the response; `None` means to
                use the default timeout

        Returns:
            the response that we have received

        Raises:
            TooSlowError: if the server did not respond in time
        """
        timeout = timeout if timeout is not None else default_timeout
        request = create_request(method, args, kwds)
        needs_response = not one_way and request.unique_id is not None
        request_id = request.unique_id

        if needs_response:
            pending_requests[request_id] = future = Future()

        await out_queue_tx.send(request)

        if not needs_response:
            return None

        try:
            with fail_after(timeout):
                return await future.wait()
        finally:
            pending_requests.pop(request_id, None)

    # Start the tasks and yield the sending half of the outbound queue so the
    # caller can send messages
    async with open_nursery() as nursery:
        nursery.start_soon(handle_inbound_messages)
        nursery.start_soon(handle_outbound_messages)
        yield send_request

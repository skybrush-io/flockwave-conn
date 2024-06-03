from contextlib import asynccontextmanager

from flockwave.concurrency import FutureMap
from inspect import iscoroutinefunction
from logging import Logger
from tinyrpc.dispatch import RPCDispatcher
from tinyrpc.protocols import RPCRequest, RPCResponse, RPCErrorResponse
from trio import CancelScope, fail_after, open_memory_channel, open_nursery
from typing import cast, Any, Callable, Optional, Union

from .types import RPCRequestHandler

__all__ = ("serve_rpc_requests",)


class RPCError(RuntimeError):
    """Base class for RPC errors that arose on the server side without ever
    reaching a request handler.
    """

    def __init__(self, code: int = 0, message: str = ""):
        super().__init__(message or f"RPC error {code}")
        self.code = code
        self.message = message


class RPCRemoteProxy:
    """Proxy object that allows us to call methods on the remote side of an
    RPC connection or send notifications, using the familiar Python function
    call syntax.

    The proxy responds to the retrieval of one of its attributes by returning
    a function that can be called with arbitrary positional and keyword
    arguments. The name of the attribute, the positional and the keyword
    arguments are then converted into a single RPC request or notification
    object that is then dispatched to the remote side.

    At construction time, the proxy requires a function that takes the name
    of a method and a set of positional and keyword arguments, and that
    returns an awaitable that resolves to the response of the server (or to
    `None` if the request is a notification). The function must treat the
    `one_way` keyword argument in a special way; it must be used to determine
    whether the request needs a response (`False`) or not (`True`).
    """

    class _Method:
        def __init__(self, name: str, sender, one_way: bool):
            self._name = name
            self._sender = sender
            self._one_way = one_way

        def __call__(self, *args, **kwds):
            return self._sender(self._name, *args, one_way=self._one_way, **kwds)

    def __init__(self, sender, one_way: bool = False):
        """Constructor.

        Parameters:
            sender: the request sender function to use.
            one_way: specifies whether the proxy sends requests (`False`) or
                notifications (`True`)
        """
        self._methods = {}
        self._sender = sender
        self._one_way = bool(one_way)

    def __getattr__(self, name: str):
        func = self._methods.get(name)
        if func is None:
            self._methods[name] = func = self._Method(
                name, one_way=self._one_way, sender=self._sender
            )
        return func


class RPCRemotePeer:
    """Object representing the remote peer of an RPC connection.

    This object can be used to send requests and notifications to the remote
    peer using the familiar Python method call syntax.
    """

    def __init__(self, sender):
        """Constructor.

        Parameters:
            sender: a request sender function; see RPCRemoteProxy_ for more
                details
        """
        self.notify = RPCRemoteProxy(sender, one_way=True)
        self.request = RPCRemoteProxy(sender, one_way=False)


@asynccontextmanager
async def serve_rpc_requests(
    channel,
    *,
    create_request: Callable[[str, list[Any], dict[str, Any]], RPCRequest],
    handler: Union[RPCRequestHandler, RPCDispatcher],
    log: Optional[Logger] = None,
    timeout: float = 5,
):
    """Sets up a context that allows us to use the given connection for
    remote procedure calls (RPC) with the given protocol.

    Parameters:
        channel: the message channel to use
        create_request: function that can be called with an RPC method name,
            the list of positional arguments and the dictionary holding
            the keyword arguments, and that will return an RPC request
            object that can be sent over the channel
        handler: handler function or method dispatcher that we will invoke
            when we receive a request from our peer
        log: optional logger to use for logging error messages and warnings
        timeout: default timeout for requests, in seconds

    Yields:
        an RPCRemotePeer_ object with two properties: `notify` and `request`.
        Both of these properties map to an RPCRemoteProxy_ object that can be
        used to send requests and notifications to the remote peer using the
        familiar Python method call syntax.
    """
    handler_is_async = iscoroutinefunction(handler)

    # If we received an RPCDispatcher as a handler, use its dispatch method
    if isinstance(handler, RPCDispatcher):
        handler = handler.dispatch  # type: ignore

    handler = cast(RPCRequestHandler, handler)

    # Create a queue in which one can post outbound messages
    out_queue_tx, out_queue_rx = open_memory_channel(0)

    # Create a map that maps pending requests that we have sent to the
    # corresponding futures that we need to resolve when the response arrives
    pending_requests = FutureMap()

    # Store the default timeout
    default_timeout = timeout

    # Create a cancellation scope so we can cancel the tasks spawned by the
    # user if the channel closes
    cancel_scope = CancelScope()

    async def handle_single_inbound_message(message) -> None:
        """Task that handles a single inbound message."""

        if isinstance(message, RPCRequest):
            # TODO(ntamas): send this to a worker?
            if handler_is_async:
                response = await handler(message)  # type: ignore
            else:
                response = handler(message)
            if response and not message.one_way:
                await out_queue_tx.send(response)

        elif isinstance(message, RPCErrorResponse):
            request_id = cast(str, message.unique_id)
            future = pending_requests.get(request_id)
            if future:
                if not future.done():
                    error = message.error
                    if isinstance(error, dict):
                        future.set_exception(
                            RPCError(error.get("code", 0), error.get("message", ""))
                        )
                    else:
                        future.set_exception(RPCError(0, str(error)))
                else:
                    if log:
                        log.warn(
                            "Duplicate error response received for request {!r}".format(
                                request_id
                            )
                        )
            else:
                if log:
                    log.warn(
                        "Stale error response received for request {!r}".format(
                            request_id
                        )
                    )

        elif isinstance(message, RPCResponse):
            request_id = cast(str, message.unique_id)
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
        cancel_scope.cancel()

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
        request = create_request(method, args, kwds, one_way=one_way)
        needs_response = not one_way and request.unique_id is not None
        request_id = request.unique_id

        if needs_response:
            future_context = pending_requests.new(request_id)

        await out_queue_tx.send(request)

        if not needs_response:
            return None

        async with future_context as future:
            with fail_after(timeout):
                return await future.wait()

    # Start the tasks and yield the sending half of the outbound queue so the
    # caller can send messages
    async with open_nursery() as nursery:
        nursery.start_soon(handle_inbound_messages)
        nursery.start_soon(handle_outbound_messages)
        with cancel_scope:
            yield RPCRemotePeer(send_request)

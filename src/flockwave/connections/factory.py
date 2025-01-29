"""Factory object that allows connections to be constructed from a simple
string or dict representation.

See :meth:`FactoryBase.create()`_ for more information about the two
specification formats.
"""

from __future__ import annotations

from contextlib import contextmanager
from functools import partial
from typing import (
    Any,
    Callable,
    Generic,
    Iterator,
    Optional,
    TypeVar,
    Union,
    TYPE_CHECKING,
)
from urllib.parse import parse_qs, urlparse

from .base import Connection
from .errors import UnknownConnectionTypeError, UnknownMiddlewareTypeError

if TYPE_CHECKING:
    from .channel import ChannelConnection


__all__ = (
    "create_connection",
    "create_connection_factory",
    "create_loopback_connection_pair",
    "register_builtin_middleware",
)

T = TypeVar("T")


class Factory(Generic[T]):
    """Base class for connection or listener factory objects that create
    connections or listeners from a URL-like string representation or a simple
    dict representation.
    """

    _registry: dict[str, Callable[..., T]]
    """Dictionary mapping connection names to factory functions that create a
    connection.
    """

    _middleware_registry: dict[str, Callable[[T], T]]
    """Dictionary mapping middleware names to functions that wrap an existing
    instance returned from a factory function to provide additional functionality
    on top of it.
    """

    def __init__(self):
        """Constructor."""
        self._registry = {}
        self._middleware_registry = {}

    @staticmethod
    def _url_specification_to_dict(specification: str) -> dict[str, Any]:
        """Converts a URL-styled specification to a dict-styled
        specification.

        Parameters:
            specification: the URL-styled specification to convert

        Returns:
            dict: the dict-styled specification
        """
        # Break up the URL into parts
        parts = urlparse(specification, allow_fragments=False)
        if not parts.scheme:
            # No ":" in specification; let's assume that the entire string is
            # a URL scheme and that we have no parameters
            base_type, *middleware = specification.split("+")
            return {"type": base_type, "middleware": middleware}

        # Split the netloc into authentication info and the rest if needed
        auth, _, host_and_port = parts.netloc.rpartition("@")

        # Split the host-and-port into hostname and port if needed
        host, _, port = host_and_port.partition(":")
        port = int(port) if port else None

        # Parse the parameters into a dict, turning values into integers
        # where applicable
        raw_parameters = parse_qs(parts.query) if parts.query else {}
        parameters: dict[str, Union[int, str]] = {}
        for k, v in raw_parameters.items():
            if len(v) > 1:
                raise ValueError("repeated parameters are not supported")
            v = v[0]
            try:
                v = int(v)
            except ValueError:
                pass
            parameters[k] = v

        # Split the scheme into base and middleware
        base_type, *middleware = parts.scheme.split("+")

        # Return the result in dict-styled format
        result = {"type": base_type, "middleware": middleware, "parameters": parameters}
        if host:
            result["host"] = host
        if port is not None:
            result["port"] = port
        if parts.path:
            result["path"] = parts.path
        if auth:
            username, sep, password = auth.partition(":")
            result["username"] = username
            if sep:
                result["password"] = password

        return result

    def create(self, specification: Union[str, dict[str, Any]]) -> T:
        """Creates a connection or listener object from its specification. The
        specification may be written in one of two forms: a single URL-style
        string or a dictionary with prescribed keys and values.

        When the specification is a string, it must follow the following
        URL-like format::

            scheme:[//host:port]/path?param1=value1&param2=value2&...

        where ``scheme`` defines the registered name of the connection class
        (e.g., ``serial`` for serial ports, ``file`` for files and so on),
        ``path`` defines the target of the connection or listener (e.g., the
        serial port itself or the name of the file), ``host`` and ``port`` define
        the hostname and the port where the path is found (if it makes sense
        for the given type of connection or listener) and the remaining parameters
        and values define additional connection or listener arguments. The ``scheme``
        will be used to look up the class (or callable) registered
        in this factory, then it will be called with ``host``, ``port``,
        ``path`` and the additional parameters as keyword arguments. For
        instance, assuming that the ``serial`` scheme resolves to the
        SerialPortConnection_ class, the following URL::

            serial:/dev/ttyUSB0?baud=115200

        is resolved to the following call::

            SerialPortConnection(path="/dev/ttyUSB0", baud=115200)

        When the scheme contains one or more ``+`` signs, the part before the
        first ``+`` is considered the name that resolves to a connection class,
        and the remaining parts are considered _middleware_ names, i.e. wrappers
        that take an existing object instance and return another instance by
        adding some functionality on top of the original instance.

        Parameter value that contain digits and positive/negative signs
        only will be cast to an integer before passing them to the
        connection or listener class. Note that fractional numbers will *not* be cast
        to floats (to avoid any precision loss or rounding errors) - it is
        up to the connection class to handle floats appropriately.

        The other possible specification is in the format of a dictionary
        like the one below::

            {
                "type": "serial",
                "middleware": [],
                "path": "/dev/ttyUSB0",
                "parameters": {
                    "param1": "value1",
                    "param2": "value2"
                }
            }

        When this specification is used, the ``type`` member of the
        dictionary will be used to look up the connection or listener class (or
        callable) in the factory, the ``host``, ``port`` and ``path``
        members will be merged with the ``parameters`` dictionary (if any)
        and the merged dictionary will be passed as keyword arguments.

        The ``middleware`` array will be used to look of the middleware that
        should wrap the originally created instance. Each entry in the
        ``middleware`` array is a string identifying the middleware to look up.

        ``host``, ``middleware``, ``port``, ``path`` and ``parameters`` are all
        optional. No automatic type conversion is performed on the members of the
        ``parameters`` dict.

        Parameters:
            specification: the specification of the connection or listener
                to create, in one of the two possible formats outlined above

        Returns:
            the connection or listener that was created by the factory

        Raises:
            UnknownConnectionTypeError: if the type of the connection or listener
                is not known to the factory
            UnknownMiddlewareTypeError: if the type of one of the middleware
                is not known to the factory
        """
        if isinstance(specification, str):
            specification = self._url_specification_to_dict(specification)

        connection_type = specification["type"]
        func = self._registry.get(connection_type)
        if func is None:
            raise UnknownConnectionTypeError(connection_type)

        middleware_types = specification.get("middleware", ())
        middleware = []
        for middleware_type in middleware_types:
            mw = self._middleware_registry.get(middleware_type)
            if mw is None:
                raise UnknownMiddlewareTypeError(middleware_type)
            middleware.append(mw)

        parameters = {}
        for name in ("host", "port", "path", "username", "password"):
            if name in specification:
                parameters[name] = specification[name]
        parameters.update(specification.get("parameters", {}))

        result = func(**parameters)
        for mw in middleware:
            result = mw(result)

        return result

    def register(self, name: str, klass=None):
        """Registers the given class for this factory with the given name, or
        returns a decorator that will register an arbitrary class with the given
        name (if no class is specified).

        Parameters:
            name: the name that will be used in the factory to refer
                to the given connection class. See the `create()`_ method
                for more information about how this name is used.
            klass: a connection class or a callable that
                returns a new connection instance when called with some
                keyword arguments (that are provided by the factory in
                the `create()`_ method).

        Returns:
            when ``klass`` is not ``None``, returns the class itself. When
            ``klass`` is ``None``, returns a decorator that can be applied
            on a class to register it with the given name in this factory.
        """
        if klass is None:
            return partial(self.register, name)
        else:
            self._registry[name] = klass
            return klass

    def register_middleware(
        self, name: str, middleware: Optional[Callable[[T], T]] = None
    ):
        """Registers the given middleware for this factory with the given name, or
        returns a decorator that will register an arbitrary middleware with the given
        name (if no class is specified).

        Overwrites existing middleware with the same name when already
        registered.

        Parameters:
            name: the name that will be used in the factory to refer
                to the given middleware. See the `create()`_ method
                for more information about how this name is used.
            middleware: a middleware that wraps an existing connection or listener
                instance when called with an existing connection or listener.

        Returns:
            when ``middleware`` is not ``None``, returns the middleware itself.
            When ``middleware`` is ``None``, returns a decorator that can be
            applied on a middleware to register it with the given name in this
            factory.
        """
        if middleware is None:
            return partial(self.register_middleware, name)
        else:
            self._middleware_registry[name] = middleware
            return middleware

    def unregister(self, name: str) -> None:
        """Unregisters the class identified with the given name from this
        factory.
        """
        del self._registry[name]

    def unregister_middleware(self, name: str) -> None:
        """Unregisters the middleware identified with the given name from this
        factory.
        """
        del self._middleware_registry[name]

    @contextmanager
    def use(self, klass: Callable[..., T], name: str) -> Iterator[None]:
        """Context manager temporarily registers the given class for this factory
        with the given name and unregisters it when the context is exited.

        This function allows the user to safely override a class associated to a
        given name with another one. If the name is already taken by another
        class, the old class will be restored upon exiting the context.
        """
        old_klass = self._registry.get(name)
        try:
            self.register(name, klass)
            yield
        finally:
            self.unregister(name)
            if old_klass is not None:
                self.register(name, old_klass)

    @contextmanager
    def use_middleware(self, klass: Callable[[T], T], name: str) -> Iterator[None]:
        """Context manager temporarily registers the given middleware for this
        factory with the given name and unregisters it when the context is exited.

        This function allows the user to safely override a middleware associated
        to a given name with another one. If the name is already taken by another
        middleware, the old middleware will be restored upon exiting the context.
        """
        old_middleware = self._middleware_registry.get(name)
        try:
            self.register_middleware(name, klass)
            yield
        finally:
            self.unregister_middleware(name)
            if old_middleware is not None:
                self.register_middleware(name, old_middleware)

    def __call__(self, *args, **kwds):
        """Forwards the invocation to the `create()`_ method."""
        return self.create(*args, **kwds)


def register_builtin_middleware(factory: Factory[Connection]) -> None:
    """Registers the default middleware that comes with the `connections` module
    in the given factory.

    Currently registered middleware are:

    - `log`: logs incoming and outgoing messages to the standard output
    - `rd`: disables writing to the connection, making it read-only.
    - `wr`: disables reading from the connection, making it write-only.
    """
    from .middleware import (
        ReadOnlyMiddleware,
        WriteOnlyMiddleware,
        LoggingMiddleware,
    )

    factory.register_middleware("log", LoggingMiddleware.create())
    factory.register_middleware("rd", ReadOnlyMiddleware)
    factory.register_middleware("wr", WriteOnlyMiddleware)


create_connection = Factory[Connection]()
"""Singleton connection factory"""

register_builtin_middleware(create_connection)


def create_connection_factory(*args, **kwds):
    """Creates a connection factory function that creates a connection
    configured in a specific way when invoked with no arguments.

    This is essentially a deferred call to `create_connection()`
    """
    return partial(create_connection, *args, **kwds)


def create_loopback_connection_pair(
    data_type: Callable[[], T],
    buffer_size: int = 0,
) -> tuple["ChannelConnection[T, T]", "ChannelConnection[T, T]"]:
    """Creates a pair of connections such that writing to one of them will
    send the written data to the read endpoint of the other connection and vice versa.

    Args:
        data_type: specifies the type of data that can be sent on the
            channel; used only for type safety
        buffer_size: number of items that can stay in the buffers between the
            connections without blocking
    """
    from trio import open_memory_channel
    from .channel import ChannelConnection

    tx1, rx1 = open_memory_channel(buffer_size)
    tx2, rx2 = open_memory_channel(buffer_size)

    conn1 = ChannelConnection(tx1, rx2)
    conn2 = ChannelConnection(tx2, rx1)

    return conn1, conn2

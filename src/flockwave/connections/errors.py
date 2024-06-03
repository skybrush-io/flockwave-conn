__all__ = (
    "ConnectionError",
    "UnknownConnectionTypeError",
    "UnknownMiddlewareTypeError",
)


class ConnectionError(RuntimeError):
    """Base class for connection-related errors."""

    pass


class UnknownConnectionTypeError(RuntimeError):
    """Exception thrown when trying to construct a connection with an
    unknown type.
    """

    def __init__(self, connection_type: str):
        """Constructor.

        Parameters:
            connection_type: the connection type that the user tried
                to construct.
        """
        super().__init__(f"Unknown connection type: {connection_type!r}")


class UnknownMiddlewareTypeError(RuntimeError):
    """Exception thrown when trying to construct a middleware with an
    unknown type.
    """

    def __init__(self, middleware_type: str):
        """Constructor.

        Parameters:
            middleware_type: the middleware type that the user tried
                to construct.
        """
        super().__init__(f"Unknown middleware type: {middleware_type!r}")

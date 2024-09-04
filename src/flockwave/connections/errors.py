__all__ = (
    "AddressError",
    "ConnectionError",
    "UnknownConnectionTypeError",
    "UnknownMiddlewareTypeError",
)


class AddressError(RuntimeError):
    """Base class for addressing-related errors."""

    pass


class ConnectionError(RuntimeError):
    """Base class for connection-related errors."""

    pass


class NoBroadcastAddressError(AddressError):
    """Error thrown when there is no broadcast address associated to a connection
    and it would be needed for a broadcast operation.
    """

    def __init__(self, message: str = ""):
        super().__init__(message or "No broadcast address")


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

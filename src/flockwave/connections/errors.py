__all__ = ("ConnectionError", "UnknownConnectionTypeError")


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
            connection_type (str): the connection type that the user tried
                to construct.
        """
        message = f"Unknown connection type: {connection_type!r}"
        super(UnknownConnectionTypeError, self).__init__(message)

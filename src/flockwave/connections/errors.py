__all__ = ("ConnectionError", "UnknownConnectionTypeError")


class ConnectionError(RuntimeError):
    """Exception thrown during a connection attempt.

    Not thrown by Connection_ subclasses but you may throw one yourself.
    """

    def __init__(self, connection, message=None):
        """Constructor.

        Parameters:
            connection (Connection): the connection that failed to connect
        """
        super(ConnectionError, self).__init__(message or "Connection failed")
        self.connection = connection


class UnknownConnectionTypeError(RuntimeError):
    """Exception thrown when trying to construct a connection with an
    unknown type.
    """

    def __init__(self, connection_type):
        """Constructor.

        Parameters:
            connection_type (str): the connection type that the user tried
                to construct.
        """
        message = "Unknown connection type: {0!r}".format(connection_type)
        super(UnknownConnectionTypeError, self).__init__(message)

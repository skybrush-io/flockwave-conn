from trio import Event
from typing import Generic, TypeVar


T = TypeVar("T")


class Future(Generic[T]):
    """Future-like object for Trio that can be used as a handle for a computation
    that is not finished yet.
    """

    def __init__(self):
        """Constructor."""
        self._error = None
        self._result = None
        self._event = Event()

    def done(self) -> bool:
        """Returns whether the computation has completed."""
        return self._event.is_set()

    def set_exception(self, exc: Exception) -> None:
        """Sets an exception as the result of the execution associated with the
        future.
        """
        self._error = exc
        self._result = None
        self._event.set()

    def set_result(self, value: T) -> None:
        """Sets the result of the execution associated with the future."""
        self._result = value
        self._error = None
        self._event.set()

    async def wait(self) -> T:
        """Wait for the result of the computation and returns the result, or
        throws an error if the computation ended with an error.
        """
        await self._event.wait()
        if self._error:
            raise self._error
        else:
            return self._result

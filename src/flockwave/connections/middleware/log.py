from functools import partial, singledispatch, wraps
from typing import (
    cast,
    Any,
    Callable,
    Generic,
    Iterable,
    TypeVar,
    Union,
)

from flockwave.connections.base import Connection, RWConnection
from flockwave.connections.utils.hexdump import hexdump

from .base import ConnectionMiddleware

__all__ = (
    "format_object_for_logging",
    "prefix_formatter",
    "LoggingMiddleware",
)

RT = TypeVar("RT")
WT = TypeVar("WT")

Formatter = Callable[[Any], Iterable[str]]


@singledispatch
def format_object_for_logging(obj) -> Iterable[str]:
    """Formats an object into one or more lines to be printed into a log."""
    yield repr(obj)


@format_object_for_logging.register
def format_string_for_logging(obj: str) -> Iterable[str]:
    return obj


@format_object_for_logging.register(bytes)
@format_object_for_logging.register(bytearray)
@format_object_for_logging.register(memoryview)
def format_bytes_for_logging(
    obj: Union[bytes, bytearray, memoryview],
) -> Iterable[str]:
    for line in cast(Iterable[str], hexdump(obj, "generator")):
        yield line[line.index(":") + 1 :]


def prefix_formatter(formatter: Formatter, prefix: str) -> Formatter:
    """Wraps a formatter and returns another formatter that prepends the given
    prefix to each line.
    """

    @wraps(formatter)
    def prefixed_formatter(obj: Any) -> Iterable[str]:
        for line in formatter(obj):
            yield f"{prefix}{line}"

    return prefixed_formatter


_default_formatters = (
    prefix_formatter(format_bytes_for_logging, "<-- "),
    prefix_formatter(format_bytes_for_logging, "--> "),
)


class LoggingMiddleware(ConnectionMiddleware[RWConnection[RT, WT]], Generic[RT, WT]):
    """Logging middleware that logs each read and write over the connection."""

    @classmethod
    def create(
        cls,
        writer: Union[
            Callable[[str], None], tuple[Callable[[str], None], Callable[[str], None]]
        ] = print,
        formatter: Union[
            Callable[[Union[RT, WT]], Iterable[str]],
            tuple[
                Callable[[RT], Iterable[str]],
                Callable[[WT], Iterable[str]],
            ],
        ] = _default_formatters,
    ) -> Callable[[Connection], Connection]:
        """Constructor.

        Arguments:
            writer: a function that can be called with a string to write a log
                line to a logger, or two such functions, one for logging read
                attempts and one for logging write attempts
            formatter: a function that can be called with an object read from
                or written to a connection and that yield a list of strings to
                write to the log, or two such functions, one for formatting
                read objects and one for formatting written objects
        """
        writers: tuple[Callable[[str], None], Callable[[str], None]] = (
            (writer, writer) if callable(writer) else writer
        )
        formatters: tuple[
            Callable[[RT], Iterable[str]],
            Callable[[WT], Iterable[str]],
        ] = (formatter, formatter) if callable(formatter) else formatter
        return partial(cls, writers=writers, formatters=formatters)

    def __init__(
        self,
        wrapped,
        *,
        writers: tuple[Callable[[str], None], Callable[[str], None]],
        formatters: tuple[
            Callable[[RT], Iterable[str]],
            Callable[[WT], Iterable[str]],
        ],
    ):
        """Constructor, for internal use.

        Arguments:
            wrapped: the connection instance to wrap
            writers: functions that can be called with a string to write a log
                line to a logger, one for logging read attempts and one for
                logging write attempts
            formatter: functions that can be called with an object read from
                or written to a connection and that yield a list of strings to
                write to the log
        """
        super().__init__(wrapped)
        self._self_print = writers
        self._self_format = formatters

    async def read(self) -> RT:
        result = await self.__wrapped__.read()
        for line in self._self_format[0](result):
            self._self_print[0](line)
        return result

    async def write(self, data: WT) -> None:
        for line in self._self_format[1](data):
            self._self_print[1](line)
        return await self.__wrapped__.write(data)

from functools import singledispatch, wraps
from hexdump import hexdump
from typing import (
    cast,
    Any,
    Callable,
    Generic,
    Iterable,
    TypeVar,
    Union,
)

from flockwave.connections.base import RWConnection

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
    def __init__(
        self,
        wrapped,
        *,
        writer: Callable[[str], None] = print,
        formatter: Union[
            Callable[[Union[RT, WT]], Iterable[str]],
            tuple[
                Callable[[Union[RT, WT]], Iterable[str]],
                Callable[[Union[RT, WT]], Iterable[str]],
            ],
        ] = _default_formatters,
    ):
        super().__init__(wrapped)
        self._self_print = writer
        self._self_format: tuple[
            Callable[[Union[RT, WT]], Iterable[str]],
            Callable[[Union[RT, WT]], Iterable[str]],
        ] = (formatter, formatter) if callable(formatter) else formatter

    async def read(self) -> RT:
        result = await self.__wrapped__.read()
        for line in self._self_format[0](result):
            self._self_print(line)
        return result

    async def write(self, data: WT) -> None:
        for line in self._self_format[1](data):
            self._self_print(line)
        return await self.__wrapped__.write(data)

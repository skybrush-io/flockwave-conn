"""Connection object that reads from the standard output or error stream of
a forked process and writes to its stdin.
"""

from dataclasses import dataclass
from functools import partial
from subprocess import PIPE, STDOUT
from trio import Nursery, Process, move_on_after, run_process
from trio.abc import ReceiveStream, SendStream
from typing import Callable, Optional, Sequence, Union

from .base import ConnectionBase, RWConnection

__all__ = ("ProcessConnection", "ProcessDescriptor")


@dataclass
class ProcessDescriptor:
    """Dataclass that describes how a process should be started by a
    ProcessConnection_ when the connection is opened.
    """

    command: Union[str, Sequence[str]]
    """The command that should be used to start the process. May be a single
    string or a list of arguments.
    """

    cwd: Optional[str] = None
    """Working directory to change to before starting the process."""

    env: Optional[dict[str, str]] = None
    """The environment of the process; ``None`` to inherit the environment of
    the parent process.
    """

    async def start_in_nursery(self, nursery: Nursery) -> Process:
        """Starts the process described by the descriptor in the given nursery."""
        process = await nursery.start(
            partial(
                run_process,
                self.command,
                cwd=self.cwd,
                env=self.env,
                check=False,
                stdout=PIPE,
                stderr=STDOUT,
                stdin=PIPE,  # type: ignore
            )
        )
        return process  # type: ignore


class ProcessConnection(ConnectionBase, RWConnection[bytes, bytes]):
    """Connection object that reads from the standard output or error stream of
    a forked process and writes to its stdin.
    """

    _nursery: Nursery
    """The Trio nursery that will supervise processes spawned by the connection."""

    _process: Optional[Process] = None
    """The running process if the connection is open; ``None`` if the connection
    is closed.
    """

    _process_descriptor_factory: Callable[[], ProcessDescriptor]
    """Callable that can be called with no arguments and that returns a process
    descriptor that specifies how to start the process for the connection.
    """

    _stdin: Optional[SendStream]
    """The stream where the standard input of the process can be written to;
    ``None`` if the process is not running or if we have started closing the
    process.
    """

    _stdout: Optional[ReceiveStream]
    """The stream where the standard output of the process can be read from;
    ``None`` if the process is not running or if we have started closing the
    process.
    """

    exit_code: Optional[int] = None
    """The exit code of the process if it was terminated; ``None`` if the process
    is still running.
    """

    @classmethod
    def create_in_nursery(
        cls,
        nursery: Nursery,
        args: Union[str, Sequence[str]],
        cwd: Optional[str] = None,
        env: Optional[dict[str, str]] = None,
    ):
        return cls(ProcessDescriptor(args, cwd=cwd, env=env), nursery)

    def __init__(
        self,
        process: Union[ProcessDescriptor, Callable[[], ProcessDescriptor]],
        nursery: Nursery,
    ):
        """Constructor.

        Parameters:
            process: descriptor that specifies how to start the process, or a
                callable that can be called with no arguments and returns such a
                descriptor
            nursery: the Trio nursery that will supervise processes spawned by
                the connection
        """
        super().__init__()
        self._nursery = nursery
        self._process_descriptor_factory = (
            process if callable(process) else lambda: process
        )

    async def _open(self) -> None:
        descriptor = self._process_descriptor_factory()
        self.exit_code = None
        self._process = await descriptor.start_in_nursery(self._nursery)

        stdout, stdin = self._process.stdout, self._process.stdin
        assert stdout is not None
        assert stdin is not None

        self._stdout, self._stdin = stdout, stdin

    async def _close(self) -> None:
        if self._process is None:
            # already closed or waiting to be closed
            return

        process, self._process = self._process, None
        self._stdout, self._stdin = None, None

        try:
            process.terminate()
            with move_on_after(5):
                await process.wait()

            if process.returncode is None:
                process.kill()
                await process.wait()
        finally:
            self.exit_code = process.returncode

    async def read(self) -> bytes:
        assert self._stdout is not None
        data: bytes = await self._stdout.receive_some()  # type: ignore
        return data

    async def write(self, data: bytes) -> None:
        assert self._stdin is not None
        await self._stdin.send_all(data)

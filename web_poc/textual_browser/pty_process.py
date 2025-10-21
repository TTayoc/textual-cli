"""Utilities for spawning subprocesses inside a pseudo-terminal."""

from __future__ import annotations

import asyncio
import os
import pty
import signal
import struct
from typing import Callable, Mapping, Sequence

import fcntl
import termios

__all__ = ["PTYProcess"]


def _set_winsize(fd: int | None, rows: int, cols: int) -> None:
    """Apply terminal window size to the PTY."""
    if fd is None:
        return
    if rows <= 0 or cols <= 0:
        return
    packed = struct.pack("HHHH", rows, cols, 0, 0)
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, packed)
    except OSError:
        pass


class PTYProcess:
    """Manage a subprocess running inside a PTY."""

    def __init__(
        self,
        argv: Sequence[str],
        *,
        cols: int,
        rows: int,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.argv = list(argv)
        self.cols = cols
        self.rows = rows
        self.env = dict(env or {})
        self.pid: int | None = None
        self.fd: int | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._read_callback: Callable[[bytes], None] | None = None
        self._exit_callback: Callable[[int | None], None] | None = None

    async def spawn(
        self,
        read_callback: Callable[[bytes], None],
        exit_callback: Callable[[int | None], None],
    ) -> None:
        """Fork the subprocess and begin reading from the PTY."""
        self._loop = asyncio.get_running_loop()
        self._read_callback = read_callback
        self._exit_callback = exit_callback
        pid, fd = await asyncio.to_thread(self._fork)
        self.pid = pid
        self.fd = fd
        _set_winsize(fd, self.rows, self.cols)
        os.set_blocking(fd, False)
        if self._loop:
            self._loop.add_reader(fd, self._on_data)

    async def terminate(self) -> None:
        """Send SIGTERM to the subprocess and wait for it to exit."""
        await asyncio.to_thread(self._terminate_blocking)

    def write(self, data: bytes) -> None:
        """Write raw data to the PTY master fd."""
        if not data or self.fd is None:
            return
        try:
            os.write(self.fd, data)
        except OSError:
            pass

    def resize(self, rows: int, cols: int) -> None:
        """Update the PTY window size."""
        self.rows = rows
        self.cols = cols
        if self.fd is not None:
            _set_winsize(self.fd, rows, cols)

    async def wait(self) -> int | None:
        """Wait for the subprocess to exit."""
        if self.pid is None:
            return None
        return await asyncio.to_thread(self._wait_blocking)

    def _fork(self) -> tuple[int, int]:
        pid, fd = pty.fork()
        if pid == 0:  # child
            os.environ.setdefault("TERM", "xterm-256color")
            os.environ.setdefault("COLORTERM", "truecolor")
            os.environ.update(self.env)
            os.execvp(self.argv[0], self.argv)
        return pid, fd

    def _on_data(self) -> None:
        if self.fd is None or self._read_callback is None:
            return
        try:
            data = os.read(self.fd, 4096)
        except OSError:
            data = b""
        if data:
            self._read_callback(data)
        else:
            self._cleanup_reader()
            if self._exit_callback:
                exit_code = self._poll_exit_status()
                self._exit_callback(exit_code)

    def _poll_exit_status(self) -> int | None:
        if self.pid is None:
            return None
        try:
            pid, status = os.waitpid(self.pid, os.WNOHANG)
        except ChildProcessError:
            pid = 0
            status = 0
        if pid == 0:
            return None
        if os.WIFEXITED(status):
            return os.WEXITSTATUS(status)
        if os.WIFSIGNALED(status):
            return -os.WTERMSIG(status)
        return None

    def _cleanup_reader(self) -> None:
        if self._loop and self.fd is not None:
            try:
                self._loop.remove_reader(self.fd)
            except RuntimeError:
                pass
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None

    def _terminate_blocking(self) -> None:
        if self.pid is None:
            return
        try:
            os.kill(self.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            os.waitpid(self.pid, 0)
        except ChildProcessError:
            pass
        self.pid = None

    def _wait_blocking(self) -> int | None:
        if self.pid is None:
            return None
        try:
            _, status = os.waitpid(self.pid, 0)
        except ChildProcessError:
            return None
        if os.WIFEXITED(status):
            return os.WEXITSTATUS(status)
        if os.WIFSIGNALED(status):
            return -os.WTERMSIG(status)
        return None

"""
File-level exclusive locking for safe concurrent file modifications.
Prevents multiple processes from modifying the same file simultaneously.
"""

import os
import sys
from collections.abc import Generator
from contextlib import contextmanager, suppress

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


class FileLockError(Exception):
    """Raised when file lock cannot be acquired."""

    pass


@contextmanager
def exclusive_file_lock(file_path: str, timeout_seconds: int = 30) -> Generator[None]:
    """
    Acquire exclusive lock on a file.

    Usage:
        with exclusive_file_lock("/path/to/file.py"):
            # Safely modify file
            with open("/path/to/file.py", "w") as f:
                f.write(new_content)

    Args:
        file_path: Path to file to lock
        timeout_seconds: How long to wait for lock (ignored on Unix)

    Raises:
        FileLockError: If lock cannot be acquired
    """
    lock_file = f"{file_path}.lock"

    try:
        # Create lock file
        lock_fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)

        try:
            if sys.platform == "win32":
                # Windows: lock with timeout
                import time

                start = time.time()
                while True:
                    try:
                        msvcrt.locking(lock_fd, msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        if time.time() - start > timeout_seconds:
                            raise FileLockError(f"Cannot acquire lock on {file_path} after {timeout_seconds}s")  # noqa: B904
                        time.sleep(0.1)
            else:
                # Unix: use fcntl
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    raise FileLockError(f"Cannot acquire exclusive lock on {file_path}")  # noqa: B904

            yield

        finally:
            if sys.platform == "win32":
                with suppress(Exception):
                    msvcrt.locking(lock_fd, msvcrt.LK_UNLCK, 1)
            else:
                with suppress(Exception):
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)

    except FileExistsError:
        raise FileLockError(f"File is locked (another process is using {file_path})")  # noqa: B904

    finally:
        with suppress(Exception):
            os.unlink(lock_file)


@contextmanager
def shared_file_lock(file_path: str) -> Generator[None]:
    """
    Acquire shared (read) lock on a file.
    Multiple processes can hold shared locks simultaneously.

    Usage:
        with shared_file_lock("/path/to/file.py"):
            with open("/path/to/file.py", "r") as f:
                content = f.read()
    """
    if sys.platform == "win32":
        # Windows doesn't support shared locks easily, just yield
        yield
        return

    lock_file = f"{file_path}.lock"

    try:
        lock_fd = os.open(lock_file, os.O_CREAT | os.O_WRONLY, 0o644)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_SH)
            yield
        finally:
            with suppress(Exception):
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
    except Exception:
        # Lock not critical for reads, fail gracefully
        yield

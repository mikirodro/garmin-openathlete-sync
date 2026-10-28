"""Local data protection and a process-lifetime lock (Linux/Docker)."""
import os
import stat
from contextlib import contextmanager


@contextmanager
def single_instance(data_dir):
    # Restrict access to existing data as well as files created with umask 077.
    data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    data_dir.chmod(0o700)
    import fcntl

    descriptor = os.open(data_dir / ".sync.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise RuntimeError("Sync lock must be a regular file")
        os.fchmod(descriptor, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another sync process is using DATA_DIR; stop it before a manual run") from None
        yield
    finally:
        # Keep the inode: unlinking the lock can let two processes hold different locks.
        os.close(descriptor)

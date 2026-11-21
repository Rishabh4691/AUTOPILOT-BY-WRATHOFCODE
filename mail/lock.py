import fcntl
import time
from pathlib import Path

from .config import settings


class AlreadyRunning(RuntimeError):
    pass


def single_instance(path: Path | None = None):
    path = path or settings.db_path.with_name("bot.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.close()
        raise AlreadyRunning(f"another bot holds {path}, stop it first")
    fh.write(str(time.time()))
    fh.flush()
    return fh

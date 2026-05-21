"""Run scraper in a separate OS process (survives Django runserver reload)."""
import logging
import os
import signal
import subprocess
import sys
from pathlib import Path

from django.conf import settings

logger = logging.getLogger("scraper_process")

STOP_FILE = None
WORKER_LOG = None


def _paths():
    global STOP_FILE, WORKER_LOG
    if STOP_FILE is None:
        STOP_FILE = settings.LOGS_DIR / "scraper.stop"
        WORKER_LOG = settings.LOGS_DIR / "worker.log"
    return STOP_FILE, WORKER_LOG


def clear_stop_flag():
    path, _ = _paths()
    if path.exists():
        path.unlink()


def request_stop():
    path, _ = _paths()
    path.touch()


def is_stop_requested():
    path, _ = _paths()
    return path.exists()


def pid_is_alive(pid):
    if not pid or pid <= 0:
        return False
    if sys.platform == "win32":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        return str(pid) in (out.stdout or "")
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def terminate_pid(pid):
    if not pid or pid <= 0:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass


def spawn_worker(resume=False):
    manage = Path(settings.BASE_DIR) / "manage.py"
    args = [sys.executable, str(manage), "run_scraper"]
    if resume:
        args.append("--resume")
    _, log_path = _paths()
    log_path.parent.mkdir(exist_ok=True)
    log_handle = open(log_path, "a", encoding="utf-8")
    kwargs = {
        "cwd": str(settings.BASE_DIR),
        "stdout": log_handle,
        "stderr": subprocess.STDOUT,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen(args, **kwargs)
    logger.info("Started scraper worker pid=%s resume=%s", proc.pid, resume)
    return proc.pid

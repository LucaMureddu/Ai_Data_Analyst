"""
dw_logger.py
------------
Logging persistente su file con rotazione automatica.
Invisibile all'utente — solo per debug e supporto post-vendita.

Percorso log:
  macOS   → ~/Library/Logs/Data-Whisperer/data-whisperer.log
  Windows → %APPDATA%/Data-Whisperer/Logs/data-whisperer.log
  Linux   → ~/.local/share/Data-Whisperer/logs/data-whisperer.log
"""

import logging
import logging.handlers
import os
import platform
import sys


def _log_dir() -> str:
    system = platform.system()
    if system == "Darwin":
        return os.path.expanduser("~/Library/Logs/Data-Whisperer")
    if system == "Windows":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
        return os.path.join(base, "Data-Whisperer", "Logs")
    return os.path.expanduser("~/.local/share/Data-Whisperer/logs")


def _setup() -> tuple[logging.Logger, str]:
    log_dir = _log_dir()
    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError:
        log_dir = os.path.expanduser("~")

    log_path = os.path.join(log_dir, "data-whisperer.log")

    logger = logging.getLogger("dw")
    if logger.handlers:
        return logger, log_path

    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    try:
        handler: logging.Handler = logging.handlers.RotatingFileHandler(
            log_path, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8",
        )
    except OSError:
        handler = logging.NullHandler()

    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(handler)

    logger.info("=== Data-Whisperer avviato — Python %s — %s ===",
                sys.version.split()[0], platform.platform())
    return logger, log_path


dw_logger, LOG_PATH = _setup()

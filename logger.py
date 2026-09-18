"""
Central logging setup — rotating file handler under ~/.snapcap/logs/, with
INFO/WARNING/ERROR levels, per the project's stability standard. Previously
the only diagnostic trail was crash.log (written once, on an unhandled
exception) — this adds an ongoing operational log so a user's bug report can
be diagnosed from context leading up to a failure, not just its traceback.
"""
import logging
import logging.handlers
from pathlib import Path

import config as cfg

LOG_DIR = cfg.CONFIG_DIR / "logs"
LOG_FILE = LOG_DIR / "snapcap.log"

_configured = False


def setup_logging(level=logging.INFO) -> logging.Logger:
    """Idempotent — safe to call multiple times (e.g. once per module import
    during tests) without duplicating handlers."""
    global _configured
    root = logging.getLogger("snapcap")
    if _configured:
        return root

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=1_000_000, backupCount=5, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        root.addHandler(handler)
    except Exception:
        # If the log directory truly can't be created/written, degrade to a
        # no-op logger rather than crash the app over logging infrastructure.
        root.addHandler(logging.NullHandler())

    root.setLevel(level)
    _configured = True
    return root


def get_logger(name: str) -> logging.Logger:
    """Child logger, e.g. get_logger('capture'), get_logger('ai_engine')."""
    setup_logging()
    return logging.getLogger(f"snapcap.{name}")

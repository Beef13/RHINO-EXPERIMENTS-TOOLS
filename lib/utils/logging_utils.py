"""Lightweight logging utilities for Rhino scripts.

Rhino's Python environment doesn't support the standard logging module well,
so these helpers provide simple print-based logging with timestamps.
"""
import time


_start_time = time.time()
_log_enabled = True


def enable_logging(enabled=True):
    """Enable or disable log output."""
    global _log_enabled
    _log_enabled = enabled


def log(message):
    """Print a timestamped log message."""
    if not _log_enabled:
        return
    elapsed = time.time() - _start_time
    print("[{:>8.2f}s] {}".format(elapsed, message))


def log_separator(label=""):
    """Print a visual separator line."""
    if not _log_enabled:
        return
    if label:
        print("--- {} ---".format(label))
    else:
        print("-" * 40)


def log_dict(data, title=None):
    """Print a dictionary as formatted key-value pairs."""
    if not _log_enabled:
        return
    if title:
        log(title)
    for key, value in data.items():
        print("  {}: {}".format(key, value))


class Timer(object):
    """Context manager for timing code blocks.

    Usage:
        with Timer("mesh generation"):
            build_mesh(...)
    """

    def __init__(self, label="operation"):
        self.label = label
        self.start = None
        self.elapsed = None

    def __enter__(self):
        self.start = time.time()
        return self

    def __exit__(self, *args):
        self.elapsed = time.time() - self.start
        log("{} completed in {:.3f}s".format(self.label, self.elapsed))

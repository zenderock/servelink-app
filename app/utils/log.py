import re
from datetime import datetime, timezone


def _get_level(log_line: str) -> str:
    """Get log level from log line."""
    level_aliases = {
        "debug": "DEBUG",
        "info": "INFO",
        "success": "SUCCESS",
        "warn": "WARNING",
        "warning": "WARNING",
        "error": "ERROR",
        "fatal": "CRITICAL",
        "critical": "CRITICAL",
    }

    # Pattern to find levels in:
    # - [INFO]
    # - INFO:
    # - INFO -
    # - level=INFO
    pattern = re.compile(
        r"""(?ix)                          # case-insensitive, verbose
        (?:^|\s|[^\w])                     # start or non-word boundary
        (?:level[=:\s]*)?                  # optional 'level=' or 'level:'
        \[?                                # optional opening bracket
        (?P<level>debug|info|success|warn|warning|error|fatal|critical)
        \]?                                # optional closing bracket
        (?=\s|:|\-|$|[^a-z])               # followed by separator or end
        """
    )

    match = pattern.search(log_line)
    if match:
        return level_aliases[match.group("level").lower()]

    return "INFO"


def parse_log(log: str):
    """Parse log line into timestamp, timestamp_iso, message, and level."""
    timestamp, separator, message = log.partition(" ")
    level = _get_level(message)

    return {
        "timestamp": timestamp if separator else None,
        "timestamp_iso": iso_nano_to_iso(timestamp) if separator else None,
        "message": message if separator else timestamp,
        "level": level,
    }


def iso_nano_to_iso(ts: str) -> str:
    """Convert RFC3339-nano string (with offset) to ISO-8601 UTC string (millis)."""
    if not ts:
        return ""
    dt_aware = datetime.fromisoformat(ts)
    dt_utc = dt_aware.astimezone(timezone.utc)
    return dt_utc.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def epoch_nano_to_iso(ns: str | int) -> str:
    """Convert epoch nanoseconds to ISO-8601 UTC string (millis)."""
    dt = datetime.fromtimestamp(int(ns) / 1e9, tz=timezone.utc)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")

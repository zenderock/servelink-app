import re
from datetime import datetime


def _get_level(log_line: str) -> str:
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


def _format_timestamp(ts: str) -> str:
    """Convert Docker nanosecond timestamp to millisecond ISO format."""
    dt = datetime.fromisoformat(ts[:-1])  # remove 'Z'
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"  # keep 3 digits


def parse_log(log: str):
    timestamp, separator, message = log.partition(" ")
    level = _get_level(message)
    formatted_timestamp = _format_timestamp(timestamp) if separator else None

    return {
        "timestamp": formatted_timestamp if separator else None,
        "message": message if separator else timestamp,
        "level": level,
    }

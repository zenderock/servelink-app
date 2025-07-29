import httpx
from typing import List, Dict, Any
from datetime import datetime, timezone, timedelta
import logging

logger = logging.getLogger(__name__)


class LokiService:
    def __init__(self, loki_url: str = "http://loki:3100"):
        self.loki_url = loki_url

    async def get_project_logs(
        self,
        project_id: str,
        limit: int = 50,
        end_ns: str = None,
    ) -> List[Dict[str, Any]]:
        """Get logs from Loki using a nanosecond timestamp cursor."""

        if not end_ns:
            end_ns = str(int(datetime.now(timezone.utc).timestamp() * 1e9))

        # Use a fixed start window. 30 days should be sufficient.
        start_ns = str(
            int((datetime.now(timezone.utc) - timedelta(days=30)).timestamp() * 1e9)
        )

        params = {
            "query": f'{{project_id="{project_id}"}}',
            "start": start_ns,
            "end": end_ns,
            "limit": limit,
            "direction": "backward",
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.loki_url}/loki/api/v1/query_range", params=params
            )
            response.raise_for_status()
            data = response.json()
            logs = []

            if "data" in data and "result" in data["data"]:
                for stream in data["data"]["result"]:
                    for value in stream["values"]:
                        timestamp_ns, log_line = value
                        logs.append(
                            {
                                "timestamp": timestamp_ns,
                                "message": log_line,
                                "level": self._extract_log_level(log_line),
                                "labels": {
                                    "project_id": stream["stream"]["project_id"],
                                    "deployment_id": stream["stream"]["deployment_id"],
                                    "environment_id": stream["stream"][
                                        "environment_id"
                                    ],
                                    "branch": stream["stream"]["branch"],
                                },
                            }
                        )
            return logs

    def _extract_log_level(self, log_line: str) -> str:
        """Extract log level from log message."""
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

        import re

        pattern = re.compile(
            r"""(?ix)
            (?:^|\s|[^\w])
            (?:level[=:\s]*)?
            \[?
            (?P<level>debug|info|success|warn|warning|error|fatal|critical)
            \]?
            (?=\s|:|\-|$|[^a-z])
            """
        )

        match = pattern.search(log_line)
        if match:
            return level_aliases[match.group("level").lower()]

        return "INFO"

import httpx
import re
from typing import List, Dict, Any
import logging

from utils.log import epoch_nano_to_iso

logger = logging.getLogger(__name__)


class LokiService:
    def __init__(self, loki_url: str = "http://loki:3100"):
        self.loki_url = loki_url
        self.client = httpx.AsyncClient()

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

    def _format_loki_log(
        self, stream: dict, ts: str, line: str, **extra_labels
    ) -> dict:
        """Format a Loki log entry consistently."""
        timestamp_iso = epoch_nano_to_iso(ts)
        return {
            "timestamp_iso": timestamp_iso,
            "timestamp": ts,
            "message": line,
            "level": self._extract_log_level(line),
            "labels": {"stream": stream.get("stream", "stdout"), **extra_labels},
        }

    async def get_logs(
        self,
        project_id: str,
        limit: int = 100,
        start_timestamp: str | None = None,
        end_timestamp: str | None = None,
        deployment_id: str | None = None,
        environment_id: str | None = None,
        branch: str | None = None,
        keyword: str | None = None,
        timeout: float = 10.0,
    ) -> List[Dict[str, Any]]:
        """Get logs from Loki."""

        query_parts = [f'project_id="{project_id}"']

        if deployment_id:
            query_parts.append(f'deployment_id="{deployment_id}"')
        if environment_id:
            query_parts.append(f'environment_id="{environment_id}"')
        if branch:
            query_parts.append(f'branch="{branch}"')

        query = "{" + ", ".join(query_parts) + "}"

        if keyword:
            query += f' |~ "(?i){re.escape(keyword)}"'

        params = {
            "query": query,
            "start": start_timestamp,
            "end": end_timestamp,
            "limit": limit,
        }

        response = await self.client.get(
            f"{self.loki_url}/loki/api/v1/query_range", params=params, timeout=timeout
        )
        response.raise_for_status()
        data = response.json()

        logs = []

        if "data" in data and "result" in data["data"]:
            for stream in data["data"]["result"]:
                for timestamp_ns, log_line in stream["values"]:
                    timestamp_iso = epoch_nano_to_iso(timestamp_ns)
                    logs.append(
                        {
                            "timestamp_iso": timestamp_iso,
                            "timestamp": timestamp_ns,
                            "message": log_line,
                            "level": self._extract_log_level(log_line),
                            "labels": {
                                "project_id": stream["stream"]["project_id"],
                                "deployment_id": stream["stream"]["deployment_id"],
                                "environment_id": stream["stream"]["environment_id"],
                                "branch": stream["stream"]["branch"],
                            },
                        }
                    )

        logs.sort(key=lambda x: int(x["timestamp"]))
        return logs

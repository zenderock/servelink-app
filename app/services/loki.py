import httpx
import re
from typing import List, Dict, Any
from datetime import datetime, timezone, timedelta
import logging

from utils.log import epoch_nano_to_iso

logger = logging.getLogger(__name__)


class LokiService:
    def __init__(self, loki_url: str = "http://loki:3100"):
        self.loki_url = loki_url

    async def get_project_logs(
        self,
        project_id: str,
        limit: int = 50,
        start_timestamp: str | None = None,
        end_timestamp: str | None = None,
        deployment_id: str | None = None,
        environment_id: str | None = None,
        branch: str | None = None,
        keyword: str | None = None,
        timeout: float = 10.0,
    ) -> List[Dict[str, Any]]:
        """Get logs from Loki."""

        if not start_timestamp:
            start_timestamp = str(
                int((datetime.now(timezone.utc) - timedelta(days=30)).timestamp() * 1e9)
            )
        if not end_timestamp:
            end_timestamp = str(int(datetime.now(timezone.utc).timestamp() * 1e9))

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
            "direction": "backward",
        }

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                f"{self.loki_url}/loki/api/v1/query_range", params=params
            )
            response.raise_for_status()
            data = response.json()
            logs = []

            if "data" in data and "result" in data["data"]:
                for stream in data["data"]["result"]:
                    for value in stream["values"]:
                        timestamp, log_line = value
                        timestamp_iso = epoch_nano_to_iso(timestamp)
                        logs.append(
                            {
                                "timestamp_iso": timestamp_iso,
                                "timestamp": timestamp,
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

                logs.sort(key=lambda x: int(x["timestamp"]), reverse=True)
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

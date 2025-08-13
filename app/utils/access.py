import json
import re
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

import httpx

_cache: dict[str, dict[str, Any]] = {}


def _load_rules(rules_path: str | Path) -> dict[str, Any]:
    path = Path(rules_path).resolve()
    if not path.is_file():
        raise FileNotFoundError

    key = str(path)
    entry = _cache.get(key) or {
        "mtime": 0,
        "emails": [],
        "domains": [],
        "globs": [],
        "regex": [],
        "regex_compiled": [],
    }
    try:
        file_mtime = path.stat().st_mtime
        if file_mtime != entry["mtime"]:
            try:
                json_data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                json_data = {}
            regex_raw = json_data.get("regex", []) or []
            entry["emails"] = json_data.get("emails", []) or []
            entry["domains"] = json_data.get("domains", []) or []
            entry["globs"] = json_data.get("globs", []) or []
            entry["regex"] = regex_raw
            entry["regex_compiled"] = [
                re.compile(pattern, re.IGNORECASE) for pattern in regex_raw
            ]
            entry["mtime"] = file_mtime
            _cache[key] = entry
    except FileNotFoundError:
        entry["mtime"] = 0
        entry["emails"] = []
        entry["domains"] = []
        entry["globs"] = []
        entry["regex"] = []
        entry["regex_compiled"] = []
        _cache[key] = entry
    return entry


def is_email_allowed(email: str, rules_path: str | Path) -> bool:
    if not rules_path:
        return True
    cache = _load_rules(rules_path)
    if not (cache["emails"] or cache["domains"] or cache["globs"] or cache["regex"]):
        return True
    if cache["mtime"] == 0:
        return True
    email_lower = (email or "").strip().lower()
    if not email_lower or "@" not in email_lower:
        return False
    domain = email_lower.split("@")[-1]

    allowed_emails = {item.strip().lower() for item in cache["emails"] if item}
    if email_lower in allowed_emails:
        return True

    allowed_domains = {item.strip().lower() for item in cache["domains"] if item}
    if domain in allowed_domains:
        return True

    glob_patterns = [item.strip() for item in cache["globs"] if item]
    if any(
        fnmatch(email_lower, pattern) or fnmatch(domain, pattern)
        for pattern in glob_patterns
    ):
        return True

    if any(regex.search(email_lower) for regex in cache["regex_compiled"]):
        return True

    return False


async def notify_denied(email: str, provider: str, request, webhook_url: str):
    if not webhook_url:
        return
    try:
        payload = {
            "email": email,
            "provider": provider,
            "ip": getattr(getattr(request, "client", None), "host", None),
            "user_agent": request.headers.get("user-agent")
            if getattr(request, "headers", None)
            else None,
        }
        async with httpx.AsyncClient(timeout=3) as client:
            await client.post(webhook_url, json=payload)
    except Exception:
        pass

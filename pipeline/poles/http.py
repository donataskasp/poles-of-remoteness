"""HTTP helpers over urllib. Redirects are followed: Geofabrik serves downloads through mirrors."""
from __future__ import annotations

import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

USER_AGENT = "poles-pipeline/0.1"
TIMEOUT_S = 60


def _request(url: str, method: str = "GET", headers: dict | None = None):
    req = urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT, **(headers or {})})
    return urllib.request.urlopen(req, timeout=TIMEOUT_S)


def head(url: str) -> dict:
    """size (int or None), last_modified (aware datetime or None), accept_ranges (bool), final_url."""
    with _request(url, "HEAD") as r:
        h = r.headers
        lm = h.get("Last-Modified")
        return {
            "size": int(h["Content-Length"]) if h.get("Content-Length") else None,
            "last_modified": parsedate_to_datetime(lm) if lm else None,
            "accept_ranges": h.get("Accept-Ranges", "").lower() == "bytes",
            "final_url": r.geturl(),
        }


def snapshot_id(last_modified: datetime) -> str:
    """Snapshot identity: the primary file's Last-Modified date in GMT."""
    return last_modified.astimezone(timezone.utc).strftime("%Y-%m-%d")

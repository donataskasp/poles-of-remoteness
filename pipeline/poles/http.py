"""HTTP helpers over urllib. Redirects are followed: Geofabrik serves downloads through mirrors."""
from __future__ import annotations

import hashlib
import logging
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

USER_AGENT = "poles-pipeline/0.1"
TIMEOUT_S = 60
CHUNK = 1 << 20
_HEX32 = re.compile(r"\b[0-9a-fA-F]{32}\b")


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


def fetch_text(url: str) -> str:
    with _request(url) as r:
        return r.read().decode("utf-8", "replace")


def parse_checksum_line(text: str) -> str:
    """First 32-hex token of a `<md5>  <filename>` line. Raises ValueError on anything else (an HTML error page)."""
    m = _HEX32.search(text.strip().splitlines()[0] if text.strip() else "")
    if not m:
        raise ValueError(f"no md5 hash in checksum text: {text[:80]!r}")
    return m.group(0).lower()


def hash_file(path: Path) -> dict[str, str]:
    """md5 and sha256 in one pass."""
    md5, sha = hashlib.md5(), hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            md5.update(chunk)
            sha.update(chunk)
    return {"md5": md5.hexdigest(), "sha256": sha.hexdigest()}


def download(url: str, dest: Path, log: logging.Logger, *, expected_size: int | None = None, retries: int = 10) -> int:
    """Download url to dest, resuming a partial file with a Range request. Returns the final size."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    attempt = 0
    while True:
        have = dest.stat().st_size if dest.exists() else 0
        if expected_size is not None and have == expected_size:
            return have
        if expected_size is not None and have > expected_size:
            log.warning("%s is larger than expected (%d > %d bytes); restarting", dest.name, have, expected_size)
            dest.unlink()
            have = 0
        try:
            with _request(url, headers={"Range": f"bytes={have}-"} if have else None) as r:
                if have and r.status != 206:
                    log.warning("server ignored Range for %s; restarting from zero", dest.name)
                    have = 0
                with open(dest, "ab" if have else "wb") as f:
                    done, last_log, t0 = have, time.monotonic(), time.monotonic()
                    while chunk := r.read(CHUNK):
                        f.write(chunk)
                        done += len(chunk)
                        if time.monotonic() - last_log >= 60:
                            rate = (done - have) / max(1e-6, time.monotonic() - t0) / 1e6
                            log.info("%s: %.2f GB%s at %.0f MB/s", dest.name, done / 1e9, f" of {expected_size / 1e9:.2f}" if expected_size else "", rate)
                            last_log = time.monotonic()
            size = dest.stat().st_size
            if expected_size is not None and size != expected_size:
                raise OSError(f"short download: {size} of {expected_size} bytes")
            return size
        except urllib.error.HTTPError as e:
            if e.code == 416 and dest.exists():
                return dest.stat().st_size
            attempt += 1
            if attempt > retries:
                raise
            log.warning("download of %s failed (%s); retry %d/%d", dest.name, e, attempt, retries)
            time.sleep(min(60, 5 * attempt))
        except (urllib.error.URLError, OSError) as e:
            attempt += 1
            if attempt > retries:
                raise
            log.warning("download of %s failed (%s); retry %d/%d", dest.name, e, attempt, retries)
            time.sleep(min(60, 5 * attempt))

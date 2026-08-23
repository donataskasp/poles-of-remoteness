"""R2: bucket setup through Cloudflare's REST API (admin token), uploads through the S3 API (access key pair),
verification through the public URL. Configuration comes from the environment, secrets from files it names;
nothing here is region-specific and nothing is ever written into the repository."""
from __future__ import annotations

import http.client
import json
import logging
import mimetypes
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

import boto3
from boto3.exceptions import S3UploadFailedError
from boto3.s3.transfer import TransferConfig
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from ..errors import PolesError

API_BASE = "https://api.cloudflare.com/client/v4"
CACHE_CONTROL = "public, max-age=31536000, immutable"
ENV_NAMES = {"account_id": "POLES_R2_ACCOUNT_ID", "bucket": "POLES_R2_BUCKET", "token_file": "POLES_R2_TOKEN_FILE",
             "key_id_file": "POLES_R2_ACCESS_KEY_ID_FILE", "secret_file": "POLES_R2_SECRET_FILE"}
ENV_BASE = "POLES_R2_BASE"
CONTENT_TYPES = {".pmtiles": "application/octet-stream", ".png": "image/png", ".json": "application/json",
                 ".html": "text/html; charset=utf-8"}
RANGE_BYTES = 16384
MISSING_KEY_CODES = ("404", "NoSuchKey", "NotFound")
BUCKET_EXISTS_CODE = 10004
RETRY_STATUSES = (429, 500, 502, 503, 504)
RETRY_PAUSES = (1.0, 2.0, 4.0)     # seconds before each retry of a rate-limited or failing verification request
# The r2.dev edge answers 403 to urllib's default `Python-urllib/3.x` agent (Cloudflare's script-agent rule, seen
# 2026-08-23, issue #49) and 200 to a request that says who it is, so every verification request names the tool.
USER_AGENT = "poles-publish/1 (+https://github.com/donataskasp/atokiausia-lietuva)"
# The managed domain is verified from many threads and the upload runs on a machine the grid stage already fills,
# so cap the parts in flight per file instead of taking boto3's default of ten.
TRANSFER = TransferConfig(max_concurrency=2)


class PublishError(PolesError):
    pass


@dataclass(frozen=True)
class R2Config:
    account_id: str
    bucket: str
    base: str | None
    token_file: Path
    key_id_file: Path
    secret_file: Path

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "R2Config":
        missing = [name for name in ENV_NAMES.values() if not env.get(name)]
        if missing:
            raise PublishError("R2 is not configured; set " + ", ".join(missing)
                               + " (the *_FILE variables name files holding the secrets; see pipeline/README.md)")
        base = env.get(ENV_BASE) or None
        return cls(env[ENV_NAMES["account_id"]], env[ENV_NAMES["bucket"]], base.rstrip("/") if base else None,
                   Path(env[ENV_NAMES["token_file"]]), Path(env[ENV_NAMES["key_id_file"]]), Path(env[ENV_NAMES["secret_file"]]))


def read_secret(path: Path) -> str:
    """The one line in a secret file, stripped. The value itself is never logged or put into an error message."""
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise PublishError(f"secret file {path} is unreadable ({exc.strerror})") from exc
    if not value:
        raise PublishError(f"secret file {path} is empty")
    return value


def _error_payload(exc: urllib.error.HTTPError) -> dict:
    """The API's JSON error body, or an empty dict when it did not send one that parses."""
    try:
        raw = exc.read()
    except OSError:
        return {}
    if not exc.headers.get("Content-Type", "").startswith("application/json"):
        return {}
    try:
        payload = json.loads(raw or b"{}")
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _decode(raw: bytes, method: str, url: str) -> dict:
    """The API's JSON body. An edge maintenance page or a proxy answering 200 with HTML must stop the stage
    with the body in the message, not with a JSONDecodeError."""
    try:
        payload = json.loads(raw or b"{}")
    except ValueError as exc:
        raise PublishError(f"{method} {url}: expected JSON, got {raw[:200].decode('utf-8', 'replace')}") from exc
    if not isinstance(payload, dict):
        raise PublishError(f"{method} {url}: expected a JSON object, got {raw[:200].decode('utf-8', 'replace')}")
    return payload


def _api(method: str, url: str, token: str, body: dict | None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        payload = _error_payload(exc)
        codes = [e.get("code") for e in payload.get("errors", [])]
        if method == "POST" and url.endswith("/r2/buckets") and BUCKET_EXISTS_CODE in codes:
            return payload                         # bucket already exists
        raise PublishError(f"{method} {url}: HTTP {exc.code} {payload.get('errors') or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise PublishError(f"{method} {url}: unreachable ({exc.reason})") from exc
    except (OSError, http.client.HTTPException) as exc:   # a read that dies mid-body, a timeout waiting for it
        raise PublishError(f"{method} {url}: the response could not be read ({exc})") from exc
    payload = _decode(raw, method, url)
    if not payload.get("success", True):
        raise PublishError(f"{method} {url}: {payload.get('errors')}")
    return payload


def ensure_bucket(cfg: R2Config, log: logging.Logger, api_base: str = API_BASE) -> str:
    """Create the bucket if it is new, publish it on its managed r2.dev domain, allow ranged cross-origin reads.
    Returns the public base URL the site will fetch from."""
    token = read_secret(cfg.token_file)
    buckets = f"{api_base}/accounts/{cfg.account_id}/r2/buckets"
    _api("POST", buckets, token, {"name": cfg.bucket})
    domain = _api("PUT", f"{buckets}/{cfg.bucket}/domains/managed", token, {"enabled": True})
    managed = (domain.get("result") or {}).get("domain")
    if not managed:
        raise PublishError(f"managed domain response without a domain: {domain}")
    _api("PUT", f"{buckets}/{cfg.bucket}/cors", token, {"rules": [{
        "allowed": {"origins": ["*"], "methods": ["GET", "HEAD"], "headers": ["*"]},
        "exposeHeaders": ["Content-Length", "Content-Range", "ETag", "Accept-Ranges"], "maxAgeSeconds": 86400}]})
    base = f"https://{managed}"
    if cfg.base and cfg.base != base:
        raise PublishError(f"{ENV_BASE} is {cfg.base} but the bucket's managed domain is {base}")
    log.info("publish: bucket %s ready at %s", cfg.bucket, base)
    return base


def s3_client(cfg: R2Config, endpoint_url: str | None = None):
    return boto3.client("s3", endpoint_url=endpoint_url or f"https://{cfg.account_id}.r2.cloudflarestorage.com",
                        aws_access_key_id=read_secret(cfg.key_id_file), aws_secret_access_key=read_secret(cfg.secret_file),
                        region_name="auto", config=Config(signature_version="s3v4", retries={"max_attempts": 5, "mode": "standard"}))


def content_type(path: Path) -> str:
    return CONTENT_TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _upload_one(client, bucket: str, path: Path, key: str, forced: bool = False) -> tuple[bool, int]:
    """(uploaded, bytes sent). An object that is already there at the same size is left alone, unless the run is
    forced: keys are immutable per snapshot, so a rebuilt archive of the same size would otherwise keep the old
    bytes in the bucket for good, and --force is exactly the run that rebuilds it."""
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise PublishError(f"upload of {key} failed: {path} is unreadable ({exc.strerror})") from exc
    try:
        if not forced and client.head_object(Bucket=bucket, Key=key)["ContentLength"] == size:
            return False, 0
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in MISSING_KEY_CODES:
            raise PublishError(f"looking up {key} before its upload failed: {exc}") from exc
    try:
        client.upload_file(str(path), bucket, key, Config=TRANSFER,
                           ExtraArgs={"ContentType": content_type(path), "CacheControl": CACHE_CONTROL})
    except (ClientError, S3UploadFailedError, BotoCoreError, OSError) as exc:
        raise PublishError(f"upload of {key} failed: {exc}") from exc
    return True, size


def upload_tree(client, bucket: str, items: list[tuple[Path, str]], log: logging.Logger, workers: int = 8,
                forced: bool = False) -> dict:
    stats = {"uploaded": 0, "skipped": 0, "bytes": 0}
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(items)))) as pool:
        for done, size in pool.map(lambda it: _upload_one(client, bucket, it[0], it[1], forced), items):
            stats["uploaded" if done else "skipped"] += 1
            stats["bytes"] += size
    log.info("publish: upload to %s: %s", bucket, stats)
    return stats


def _retrying(probe: Callable[[str], tuple[int, str]], url: str) -> tuple[int, str]:
    """Reads off the managed domain are rate limited, so give a 429 or a 5xx up to three backed-off retries.
    Whatever the last attempt says is what the caller lists."""
    status, detail = probe(url)
    for pause in RETRY_PAUSES:
        if status not in RETRY_STATUSES:
            break
        time.sleep(pause)
        status, detail = probe(url)
    return status, detail


def _head_once(url: str) -> tuple[int, str]:
    """(status, detail); status 0 when the request never reached a server or the object came back without a size."""
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            if resp.status == 200 and resp.headers.get("Content-Length") is None:
                return 0, "200 without Content-Length"
            return resp.status, str(resp.status)
    except urllib.error.HTTPError as exc:
        exc.close()
        return exc.code, f"{exc.code} {exc.reason}"
    except urllib.error.URLError as exc:
        return 0, f"unreachable ({exc.reason})"
    except (OSError, http.client.HTTPException) as exc:
        return 0, f"unreachable ({exc})"


def _head(url: str) -> tuple[int, str]:
    return _retrying(_head_once, url)


def _total_size(content_range: str | None) -> int:
    """The object's full size out of a Content-Range header ("bytes 0-16383/40000"), or 0 when it does not say."""
    if content_range and "/" in content_range:
        total = content_range.rsplit("/", 1)[1].strip()
        if total.isdigit():
            return int(total)
    return 0


def _range_once(url: str) -> tuple[int, str]:
    """(status, detail) for a 16 KiB range request; status 0 when the body came back the wrong length."""
    req = urllib.request.Request(url, headers={"Range": f"bytes=0-{RANGE_BYTES - 1}", "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            got = len(resp.read())
            if resp.status != 206:
                return resp.status, f"{resp.status}, the range was ignored"
            total = _total_size(resp.headers.get("Content-Range"))
            want = min(RANGE_BYTES, total) if total else RANGE_BYTES
            return (206, "206") if got == want else (0, f"206 with {got} bytes, expected {want}")
    except urllib.error.HTTPError as exc:
        exc.close()
        return exc.code, f"{exc.code} {exc.reason}"
    except urllib.error.URLError as exc:
        return 0, f"unreachable ({exc.reason})"
    except (OSError, http.client.HTTPException) as exc:   # the body died between the headers and the last byte
        return 0, f"unreachable ({exc})"


def _range(url: str) -> tuple[int, str]:
    return _retrying(_range_once, url)


def verify_head(base: str, keys: list[str], range_keys: list[str], log: logging.Logger, workers: int = 8) -> dict:
    """Spec check 7: every published key answers HEAD 200; the archives answer a 16 KiB range with 206."""
    failures = []
    range_ok = 0
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(keys) + len(range_keys)))) as pool:
        for key, (status, detail) in zip(keys, pool.map(lambda k: _head(f"{base}/{k}"), keys)):
            if status != 200:
                failures.append(f"HEAD {key}: {detail}")
        for key, (status, detail) in zip(range_keys, pool.map(lambda k: _range(f"{base}/{k}"), range_keys)):
            if status == 206:
                range_ok += 1
            else:
                failures.append(f"RANGE {key}: {detail}")
    if failures:
        raise PublishError(f"{len(failures)} of {len(keys) + len(range_keys)} checks failed: " + "; ".join(failures[:10]))
    out = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "keys": len(keys), "range_ok": range_ok}
    log.info("publish: verified %d keys and %d ranges at %s", len(keys), range_ok, base)
    return out

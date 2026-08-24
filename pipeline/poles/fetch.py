"""Stage fetch: download sources and supplements, verify Geofabrik md5s, record the snapshot identity."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from . import http
from .config import RegionConfig, poly_url
from .workspace import Workspace

STAGE = "fetch"


class FetchError(RuntimeError):
    pass


def source_filename(url: str) -> str:
    return url.rsplit("/", 1)[-1]


def fetch_one(url: str, role: str, out_dir: Path, log: logging.Logger) -> dict:
    name = source_filename(url)
    dest = out_dir / name
    md5_path = out_dir / f"{name}.md5"
    info = http.head(url)
    expected_md5 = http.parse_checksum_line(http.fetch_text(url + ".md5"))
    if dest.exists() and md5_path.exists() and http.parse_checksum_line(md5_path.read_text()) != expected_md5:
        log.warning("remote %s changed since the partial download started; restarting it", name)
        dest.unlink()
    md5_path.write_text(f"{expected_md5}  {name}\n", encoding="utf-8")
    size = http.download(url, dest, log, expected_size=info["size"])
    hashes = http.hash_file(dest)
    if hashes["md5"] != expected_md5:
        dest.unlink()
        md5_path.unlink()
        raise FetchError(f"checksum mismatch for {name}: expected {expected_md5}, got {hashes['md5']}; file deleted, rerun to download it again")
    poly = out_dir / source_filename(poly_url(url))
    http.download(poly_url(url), poly, log)
    lm = info["last_modified"]
    return {
        "url": url, "role": role, "file": name, "size": size, "md5": hashes["md5"], "sha256": hashes["sha256"],
        "last_modified": lm.astimezone(timezone.utc).isoformat(timespec="seconds") if lm else None,
        "poly": poly.name,
    }


def run(cfg: RegionConfig, ws: Workspace, log: logging.Logger) -> dict:
    out_dir = ws.dir(STAGE)
    records = [fetch_one(url, "primary", out_dir, log) for url in cfg.sources]
    records += [fetch_one(url, "supplement", out_dir, log) for url in cfg.supplement_sources]
    primary_lm = records[0]["last_modified"]
    if primary_lm and http.snapshot_id(datetime.fromisoformat(primary_lm)) != ws.snapshot:
        log.warning("primary Last-Modified %s does not match snapshot %s (explicit --snapshot?)", primary_lm, ws.snapshot)
    snapshot = {
        "region": cfg.id, "snapshot": ws.snapshot,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": records,
    }
    (out_dir / "snapshot.json").write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    log.info("fetched %d files, %.2f GB", len(records), sum(r["size"] for r in records) / 1e9)
    return {"files": len(records), "bytes": sum(r["size"] for r in records)}

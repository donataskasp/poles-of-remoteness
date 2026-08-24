import hashlib
import json
import os

import pytest

from poles import cli, fetch, http
from poles.config import RegionConfig
from poles.workspace import Workspace


def _publish(docroot, name: str, data: bytes, *, md5: str | None = None, poly: bool = True) -> None:
    (docroot / name).write_bytes(data)
    (docroot / f"{name}.md5").write_text(f"{md5 or hashlib.md5(data).hexdigest()}  {name.replace('-latest', '-260819')}\n")
    if poly:
        (docroot / name.replace("-latest.osm.pbf", ".poly")).write_text("x\n1\n 0 0\n 1 0\n 1 1\n 0 1\n 0 0\nEND\nEND\n")


def _cfg(cfg: RegionConfig, base: str, names: list[str]) -> RegionConfig:
    urls = [f"{base}/{n}" for n in names]
    return RegionConfig(**{**cfg.__dict__, "sources": urls[:1], "supplement_sources": urls[1:]})


def test_resume_partial_download(http_server, tmp_path, log):
    base, docroot, requests = http_server
    data = os.urandom(100_000)
    _publish(docroot, "a-latest.osm.pbf", data)
    dest = tmp_path / "a-latest.osm.pbf"
    dest.write_bytes(data[:40_000])
    size = http.download(f"{base}/a-latest.osm.pbf", dest, log, expected_size=len(data))
    assert size == len(data) and dest.read_bytes() == data
    assert ("GET", "/a-latest.osm.pbf", "bytes=40000-") in requests


def test_download_restarts_when_partial_file_is_too_large(http_server, tmp_path, log):
    base, docroot, _ = http_server
    data = os.urandom(10_000)
    _publish(docroot, "b-latest.osm.pbf", data)
    dest = tmp_path / "b-latest.osm.pbf"
    dest.write_bytes(os.urandom(20_000))
    http.download(f"{base}/b-latest.osm.pbf", dest, log, expected_size=len(data))
    assert dest.read_bytes() == data


def test_checksum_mismatch_raises_and_deletes_file(http_server, tmp_path, cfg, log):
    base, docroot, _ = http_server
    _publish(docroot, "c-latest.osm.pbf", b"hello world", md5="0" * 32)
    ws = Workspace(tmp_path / "work", "europe", "2026-08-19")
    with pytest.raises(fetch.FetchError, match="checksum mismatch"):
        fetch.run(_cfg(cfg, base, ["c-latest.osm.pbf"]), ws, log)
    assert not (ws.dir("fetch") / "c-latest.osm.pbf").exists()
    assert not (ws.dir("fetch") / "snapshot.json").exists()


def test_snapshot_id_from_last_modified(http_server, cfg):
    base, docroot, _ = http_server
    _publish(docroot, "d-latest.osm.pbf", b"data")
    info = http.head(f"{base}/d-latest.osm.pbf")
    assert http.snapshot_id(info["last_modified"]) == "2026-08-19"
    assert cli.resolve_snapshot(_cfg(cfg, base, ["d-latest.osm.pbf"])) == "2026-08-19"


def test_parse_checksum_line_takes_the_hash_only():
    assert http.parse_checksum_line("db177178703cbb0d69077af5caa8b200  europe-260819.osm.pbf\n") == "db177178703cbb0d69077af5caa8b200"
    with pytest.raises(ValueError):
        http.parse_checksum_line("<html>302 Found</html>")


def test_snapshot_json_lists_every_source(http_server, tmp_path, cfg, log):
    base, docroot, _ = http_server
    blobs = {n: os.urandom(5_000 + i) for i, n in enumerate(["e-latest.osm.pbf", "f-latest.osm.pbf", "g-latest.osm.pbf"])}
    for name, data in blobs.items():
        _publish(docroot, name, data)
    ws = Workspace(tmp_path / "work", "europe", "2026-08-19")
    meta = fetch.run(_cfg(cfg, base, list(blobs)), ws, log)
    snap = json.loads((ws.dir("fetch") / "snapshot.json").read_text())
    assert [s["file"] for s in snap["sources"]] == list(blobs)
    assert [s["role"] for s in snap["sources"]] == ["primary", "supplement", "supplement"]
    for s in snap["sources"]:
        data = blobs[s["file"]]
        assert s["size"] == len(data) and s["md5"] == hashlib.md5(data).hexdigest() and s["sha256"] == hashlib.sha256(data).hexdigest()
        assert s["last_modified"] == "2026-08-19T22:18:15+00:00"
        assert (ws.dir("fetch") / s["poly"]).read_text().startswith("x\n")
    assert snap["snapshot"] == "2026-08-19" and meta["files"] == 3


def test_existing_complete_file_is_verified_not_redownloaded(http_server, tmp_path, cfg, log):
    base, docroot, requests = http_server
    data = os.urandom(8_000)
    _publish(docroot, "h-latest.osm.pbf", data)
    ws = Workspace(tmp_path / "work", "europe", "2026-08-19")
    (ws.dir("fetch") / "h-latest.osm.pbf").write_bytes(data)
    fetch.run(_cfg(cfg, base, ["h-latest.osm.pbf"]), ws, log)
    assert not any(m == "GET" and p == "/h-latest.osm.pbf" for m, p, _ in requests)

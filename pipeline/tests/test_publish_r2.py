import json
import socket
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from poles.publish import r2
from poles.publish.r2 import PublishError, R2Config

BUCKET = "poles-test"     # moto rejects bucket names shorter than three characters, as S3 does


def _files(tmp_path):
    for name, value in [("token", "tok-123"), ("key", "AKIAEXAMPLE"), ("secret", "s3cr3t")]:
        (tmp_path / name).write_text(value + "\n")
    return {"POLES_R2_ACCOUNT_ID": "acct", "POLES_R2_BUCKET": BUCKET, "POLES_R2_TOKEN_FILE": str(tmp_path / "token"),
            "POLES_R2_ACCESS_KEY_ID_FILE": str(tmp_path / "key"), "POLES_R2_SECRET_FILE": str(tmp_path / "secret")}


def test_config_from_env_names_every_missing_variable(tmp_path):
    with pytest.raises(PublishError) as exc:
        R2Config.from_env({})
    for name in ("POLES_R2_ACCOUNT_ID", "POLES_R2_BUCKET", "POLES_R2_TOKEN_FILE", "POLES_R2_ACCESS_KEY_ID_FILE", "POLES_R2_SECRET_FILE"):
        assert name in str(exc.value)
    cfg = R2Config.from_env(_files(tmp_path))
    assert cfg.bucket == BUCKET and cfg.base is None and r2.read_secret(cfg.token_file) == "tok-123"
    with pytest.raises(PublishError, match="secret"):
        r2.read_secret(tmp_path / "nope")


def test_config_keeps_an_explicit_base_without_its_trailing_slash(tmp_path):
    env = dict(_files(tmp_path), POLES_R2_BASE="https://data.example.org/")
    assert R2Config.from_env(env).base == "https://data.example.org"
    assert R2Config.from_env(dict(_files(tmp_path), POLES_R2_BASE="")).base is None


def test_read_secret_refuses_an_empty_file(tmp_path):
    (tmp_path / "blank").write_text("\n \n")
    with pytest.raises(PublishError, match="empty"):
        r2.read_secret(tmp_path / "blank")


class _Api(BaseHTTPRequestHandler):
    calls: list = []

    def _reply(self, result):
        body = json.dumps({"success": True, "errors": [], "result": result}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _fail(self, status, errors):
        body = json.dumps({"success": False, "errors": errors, "result": None}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _record(self, method):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        _Api.calls.append((method, self.path, self.headers.get("Authorization"), body))
        return body

    def do_POST(self):
        self._record("POST")
        self._reply({"name": BUCKET})

    def do_PUT(self):
        self._record("PUT")
        self._reply({"domain": "pub-abc.r2.dev", "enabled": True} if "domains" in self.path else {})

    def log_message(self, *a):
        pass


class _BucketExistsApi(_Api):
    """Cloudflare answers a second create with HTTP 409 and error code 10004."""

    def do_POST(self):
        self._record("POST")
        self._fail(409, [{"code": 10004, "message": "The bucket you tried to create already exists."}])


class _ForbiddenApi(_Api):
    def do_POST(self):
        self._record("POST")
        self._fail(403, [{"code": 10000, "message": "Authentication error"}])


class _HtmlApi(_Api):
    """An edge maintenance page or a proxy answering 200 with HTML where the API's JSON belongs."""

    def do_POST(self):
        self._record("POST")
        body = b"<html><body>under maintenance</body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _closed_port() -> int:
    """A port nothing listens on: bind one, release it, hand back the number."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextmanager
def _serving(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


@pytest.fixture
def api():
    _Api.calls = []
    with _serving(_Api) as base:
        yield base, _Api.calls


def test_ensure_bucket_creates_enables_domain_and_cors(tmp_path, api, log):
    base_url, calls = api
    cfg = R2Config.from_env(_files(tmp_path))
    base = r2.ensure_bucket(cfg, log, api_base=base_url)
    assert base == "https://pub-abc.r2.dev"
    assert [c[:2] for c in calls] == [("POST", "/accounts/acct/r2/buckets"),
                                      ("PUT", f"/accounts/acct/r2/buckets/{BUCKET}/domains/managed"),
                                      ("PUT", f"/accounts/acct/r2/buckets/{BUCKET}/cors")]
    assert all(c[2] == "Bearer tok-123" for c in calls)
    assert calls[0][3] == {"name": BUCKET} and calls[1][3] == {"enabled": True}
    rule = calls[2][3]["rules"][0]
    assert rule["allowed"]["origins"] == ["*"] and set(rule["allowed"]["methods"]) == {"GET", "HEAD"}
    assert "Accept-Ranges" in rule["exposeHeaders"] and "Content-Range" in rule["exposeHeaders"]


def test_ensure_bucket_refuses_a_base_mismatch(tmp_path, api, log):
    base_url, _ = api
    env = dict(_files(tmp_path), POLES_R2_BASE="https://data.example.org")
    with pytest.raises(PublishError, match="pub-abc.r2.dev"):
        r2.ensure_bucket(R2Config.from_env(env), log, api_base=base_url)
    agrees = dict(_files(tmp_path), POLES_R2_BASE="https://pub-abc.r2.dev")
    assert r2.ensure_bucket(R2Config.from_env(agrees), log, api_base=base_url) == "https://pub-abc.r2.dev"


def test_ensure_bucket_accepts_a_bucket_that_already_exists(tmp_path, log):
    _Api.calls = []
    with _serving(_BucketExistsApi) as base_url:
        assert r2.ensure_bucket(R2Config.from_env(_files(tmp_path)), log, api_base=base_url) == "https://pub-abc.r2.dev"
    assert [c[0] for c in _Api.calls] == ["POST", "PUT", "PUT"]


def test_ensure_bucket_raises_without_leaking_the_token(tmp_path, log):
    _Api.calls = []
    with _serving(_ForbiddenApi) as base_url:
        with pytest.raises(PublishError) as exc:
            r2.ensure_bucket(R2Config.from_env(_files(tmp_path)), log, api_base=base_url)
    assert "403" in str(exc.value) and "Authentication error" in str(exc.value)
    assert "tok-123" not in str(exc.value)


def test_ensure_bucket_refuses_a_response_that_is_not_json(tmp_path, log):
    _Api.calls = []
    with _serving(_HtmlApi) as base_url:
        with pytest.raises(PublishError) as exc:
            r2.ensure_bucket(R2Config.from_env(_files(tmp_path)), log, api_base=base_url)
    assert "under maintenance" in str(exc.value) and "/r2/buckets" in str(exc.value)
    assert "tok-123" not in str(exc.value)


def test_ensure_bucket_reports_an_api_it_cannot_reach(tmp_path, log):
    with pytest.raises(PublishError, match="unreachable"):
        r2.ensure_bucket(R2Config.from_env(_files(tmp_path)), log, api_base=f"http://127.0.0.1:{_closed_port()}")


def test_uploads_cap_the_parts_in_flight():
    assert r2.TRANSFER.max_concurrency == 2
    assert r2.TRANSFER.multipart_threshold == 8 * 1024 * 1024     # boto3's default, deliberately left alone


@mock_aws
def test_upload_tree_skips_same_size_and_sets_headers(tmp_path, log):
    client = boto3.client("s3", region_name="us-east-1")
    client.create_bucket(Bucket=BUCKET)
    a, b = tmp_path / "A.pmtiles", tmp_path / "x.json"
    a.write_bytes(b"\x00" * 1000)
    b.write_text("{}")
    items = [(a, "r/s/A.pmtiles"), (b, "r/s/x.json")]
    first = r2.upload_tree(client, BUCKET, items, log)
    assert first == {"uploaded": 2, "skipped": 0, "bytes": 1002}
    head = client.head_object(Bucket=BUCKET, Key="r/s/A.pmtiles")
    assert head["ContentType"] == "application/octet-stream" and head["CacheControl"] == r2.CACHE_CONTROL
    assert client.head_object(Bucket=BUCKET, Key="r/s/x.json")["ContentType"] == "application/json"
    second = r2.upload_tree(client, BUCKET, items, log)
    assert second == {"uploaded": 0, "skipped": 2, "bytes": 0}
    b.write_text('{"changed": true}')
    third = r2.upload_tree(client, BUCKET, items, log)
    assert third == {"uploaded": 1, "skipped": 1, "bytes": len('{"changed": true}')}


@mock_aws
def test_upload_tree_handles_empty_files_and_spare_workers(tmp_path, log):
    client = boto3.client("s3", region_name="us-east-1")
    client.create_bucket(Bucket=BUCKET)
    empty = tmp_path / "empty.json"
    empty.write_text("")
    items = [(empty, "r/s/empty.json")]
    assert r2.upload_tree(client, BUCKET, items, log, workers=8) == {"uploaded": 1, "skipped": 0, "bytes": 0}
    assert client.head_object(Bucket=BUCKET, Key="r/s/empty.json")["ContentLength"] == 0
    assert r2.upload_tree(client, BUCKET, items, log, workers=8) == {"uploaded": 0, "skipped": 1, "bytes": 0}
    assert r2.upload_tree(client, BUCKET, [], log) == {"uploaded": 0, "skipped": 0, "bytes": 0}


@mock_aws
def test_upload_tree_names_the_key_that_failed(tmp_path, log):
    client = boto3.client("s3", region_name="us-east-1")
    client.create_bucket(Bucket=BUCKET)
    good, bad = tmp_path / "good.json", tmp_path / "bad.json"
    good.write_text("{}")
    bad.write_text("{}")
    with pytest.raises(PublishError, match="r/s/bad.json"):
        r2.upload_tree(client, "no-such-bucket", [(bad, "r/s/bad.json")], log, workers=1)
    gone = [(good, "r/s/good.json"), (tmp_path / "vanished.png", "r/s/vanished.png")]
    with pytest.raises(PublishError, match="r/s/vanished.png"):     # one worker failing stops the whole upload
        r2.upload_tree(client, BUCKET, gone, log, workers=2)


@mock_aws
def test_s3_client_uses_the_key_pair_and_the_account_endpoint(tmp_path, log):
    cfg = R2Config.from_env(_files(tmp_path))
    default = r2.s3_client(cfg)
    assert default.meta.endpoint_url == "https://acct.r2.cloudflarestorage.com"
    assert default.meta.region_name == "auto" and default.meta.config.signature_version == "s3v4"
    assert default._request_signer._credentials.access_key == "AKIAEXAMPLE"    # no public accessor for this
    # moto only intercepts AWS-shaped endpoints, so the end-to-end upload goes through an S3 endpoint override.
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET)
    client = r2.s3_client(cfg, endpoint_url="https://s3.amazonaws.com")
    archive = tmp_path / "A.pmtiles"
    archive.write_bytes(b"\x01" * 2048)
    assert r2.upload_tree(client, BUCKET, [(archive, "r/s/A.pmtiles")], log) == {"uploaded": 1, "skipped": 0, "bytes": 2048}
    assert r2.upload_tree(client, BUCKET, [(archive, "r/s/A.pmtiles")], log) == {"uploaded": 0, "skipped": 1, "bytes": 0}
    head = client.head_object(Bucket=BUCKET, Key="r/s/A.pmtiles")
    assert head["ContentType"] == "application/octet-stream" and head["CacheControl"] == r2.CACHE_CONTROL


def test_s3_client_refuses_an_unreadable_key_file(tmp_path):
    env = dict(_files(tmp_path), POLES_R2_SECRET_FILE=str(tmp_path / "gone"))
    with pytest.raises(PublishError, match="gone"):
        r2.s3_client(R2Config.from_env(env))


def test_content_types():
    assert r2.content_type(Path("a.png")) == "image/png"
    assert r2.content_type(Path("a.html")) == "text/html; charset=utf-8"
    assert r2.content_type(Path("a.pmtiles")) == "application/octet-stream"
    assert r2.content_type(Path("a.JSON")) == "application/json"
    assert r2.content_type(Path("a.unknown-suffix")) == "application/octet-stream"


def test_verify_head_checks_every_key_and_ranges(http_server, log):
    base, docroot, requests = http_server
    (docroot / "r").mkdir()
    (docroot / "r" / "A.pmtiles").write_bytes(b"\x01" * 40_000)
    (docroot / "r" / "u.json").write_text("{}")
    out = r2.verify_head(base, ["r/A.pmtiles", "r/u.json"], ["r/A.pmtiles"], log)
    assert out["keys"] == 2 and out["range_ok"] == 1 and out["at"].endswith("+00:00")
    assert ("HEAD", "/r/A.pmtiles", None) in requests and ("GET", "/r/A.pmtiles", "bytes=0-16383") in requests
    with pytest.raises(PublishError, match="r/missing.png"):
        r2.verify_head(base, ["r/A.pmtiles", "r/missing.png"], [], log)


def test_verify_head_accepts_a_file_shorter_than_the_range(http_server, log):
    base, docroot, _ = http_server
    (docroot / "small.pmtiles").write_bytes(b"\x01" * 100)
    assert r2.verify_head(base, ["small.pmtiles"], ["small.pmtiles"], log)["range_ok"] == 1


class _IgnoresRange(BaseHTTPRequestHandler):
    """Answers HEAD, but serves the whole body with 200 for a range request, as a proxy without range support would."""
    body = b"\x02" * 40_000

    def _serve(self, send_body):
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        if send_body:
            self.wfile.write(self.body)

    def do_GET(self):
        self._serve(True)

    def do_HEAD(self):
        self._serve(False)

    def log_message(self, *a):
        pass


def test_verify_head_fails_when_the_server_ignores_the_range(log):
    with _serving(_IgnoresRange) as base:
        with pytest.raises(PublishError) as exc:
            r2.verify_head(base, ["r/A.pmtiles"], ["r/A.pmtiles"], log)
    assert "r/A.pmtiles" in str(exc.value) and "200" in str(exc.value)


def test_verify_head_reports_an_unreachable_base(log):
    with pytest.raises(PublishError, match="r/A.pmtiles"):
        r2.verify_head(f"http://127.0.0.1:{_closed_port()}", ["r/A.pmtiles"], [], log)


class _NoLength(BaseHTTPRequestHandler):
    """A HEAD 200 that does not say how big the object is, so the key count would attest nothing."""

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, *a):
        pass


def test_verify_head_requires_a_content_length(log):
    with _serving(_NoLength) as base:
        with pytest.raises(PublishError, match="without Content-Length"):
            r2.verify_head(base, ["r/A.pmtiles"], [], log)


class _Flaky(BaseHTTPRequestHandler):
    """Answers the first `fail_times` requests for each method and path with 429, then serves the object."""
    hits: dict = {}
    fail_times = 1
    body = b"\x03" * 40_000

    def _serve(self, send_body):
        seen = self.hits[(self.command, self.path)] = self.hits.get((self.command, self.path), 0) + 1
        if seen <= self.fail_times:
            self.send_response(429)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        ranged = self.headers.get("Range") is not None
        data = self.body[:r2.RANGE_BYTES] if ranged else self.body
        self.send_response(206 if ranged else 200)
        self.send_header("Content-Length", str(len(data)))
        if ranged:
            self.send_header("Content-Range", f"bytes 0-{len(data) - 1}/{len(self.body)}")
        self.end_headers()
        if send_body:
            self.wfile.write(data)

    def do_GET(self):
        self._serve(True)

    def do_HEAD(self):
        self._serve(False)

    def log_message(self, *a):
        pass


def test_verify_head_retries_a_rate_limited_key(monkeypatch, log):
    assert r2.RETRY_PAUSES == (1.0, 2.0, 4.0) and 429 in r2.RETRY_STATUSES and 503 in r2.RETRY_STATUSES
    monkeypatch.setattr(r2, "RETRY_PAUSES", (0.0, 0.0, 0.0))     # the wait itself is not what is under test
    flaky = type("Flaky", (_Flaky,), {"hits": {}})
    with _serving(flaky) as base:
        out = r2.verify_head(base, ["r/A.pmtiles"], ["r/A.pmtiles"], log)
    assert out["keys"] == 1 and out["range_ok"] == 1
    assert flaky.hits[("HEAD", "/r/A.pmtiles")] == 2 and flaky.hits[("GET", "/r/A.pmtiles")] == 2


def test_verify_head_gives_up_when_the_rate_limit_holds(monkeypatch, log):
    monkeypatch.setattr(r2, "RETRY_PAUSES", (0.0, 0.0, 0.0))
    always = type("Always", (_Flaky,), {"hits": {}, "fail_times": 99})
    with _serving(always) as base:
        with pytest.raises(PublishError, match="429"):
            r2.verify_head(base, ["r/A.pmtiles"], [], log)
    assert always.hits[("HEAD", "/r/A.pmtiles")] == 4            # the first attempt plus three retries

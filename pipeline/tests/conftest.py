import logging
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from poles.config import load_region

REGIONS = Path(__file__).resolve().parents[1] / "regions"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def regions_dir() -> Path:
    return REGIONS


@pytest.fixture
def cfg():
    return load_region(REGIONS / "europe.yaml")


@pytest.fixture(scope="session")
def tiny_pbf(tmp_path_factory) -> Path:
    """tiny.osm converted to PBF at test time; keeps binaries out of git and proves osmium is installed."""
    if shutil.which("osmium") is None:
        pytest.fail("osmium-tool is required for the extract tests (brew install osmium-tool)")
    out = tmp_path_factory.mktemp("tiny") / "tiny-latest.osm.pbf"
    subprocess.run(["osmium", "cat", "--overwrite", "-o", str(out), str(FIXTURES / "tiny.osm")], check=True)
    return out


@pytest.fixture
def log() -> logging.Logger:
    logger = logging.getLogger("poles.test")
    logger.setLevel(logging.DEBUG)
    return logger


class _RangeHandler(BaseHTTPRequestHandler):
    """Serves files from `directory` with Range support and a fixed Last-Modified; records requests."""
    directory: Path = Path(".")
    requests: list[tuple[str, str, str | None]] = []
    last_modified = "Wed, 19 Aug 2026 22:18:15 GMT"

    def log_message(self, *args):  # keep pytest output clean
        pass

    def _serve(self, send_body: bool):
        path = self.directory / self.path.lstrip("/")
        self.requests.append((self.command, self.path, self.headers.get("Range")))
        if not path.is_file():
            self.send_error(404)
            return
        data = path.read_bytes()
        start, end = 0, len(data) - 1
        status = 200
        rng = self.headers.get("Range")
        if rng and rng.startswith("bytes="):
            start = int(rng[6:].split("-")[0])
            status = 206
        self.send_response(status)
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Last-Modified", self.last_modified)
        self.send_header("Accept-Ranges", "bytes")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
        self.end_headers()
        if send_body:
            self.wfile.write(data[start:])

    def do_GET(self):
        self._serve(True)

    def do_HEAD(self):
        self._serve(False)


@pytest.fixture
def http_server(tmp_path):
    """Yields (base_url, docroot, requests). Put files in docroot, fetch them at base_url/<name>."""
    docroot = tmp_path / "www"
    docroot.mkdir()
    handler = type("Handler", (_RangeHandler,), {"directory": docroot, "requests": []})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", docroot, handler.requests
    finally:
        server.shutdown()
        thread.join()
        server.server_close()

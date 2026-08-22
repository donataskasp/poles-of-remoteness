"""report.json, report.html and contact-sheet.html for the validate stage (spec 6.8).

report.json is the machine-readable record: every check result, the summary counts, and the poles the
stage excluded. report.html is the same table for a human. contact-sheet.html is the review page: one
card per unit and scenario with a satellite mosaic around the winner, so an owner can see at a glance
that a pole sits in a bog and not in a car park.
"""
from __future__ import annotations

import base64
import html
import json
import math
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from ..units import Unit
from .checks import CheckResult

ESRI_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
ESRI_ATTRIBUTION = "Imagery: Esri, Maxar, Earthstar Geographics, and the GIS User Community"
USER_AGENT = "poles-pipeline contact sheet (validation review page)"
# 1x1 transparent PNG, drawn where a tile would not download.
BLANK_PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
CSS = """body{font:14px/1.4 system-ui,sans-serif;margin:24px;color:#222;background:#fafafa}h1{font-size:20px}table{border-collapse:collapse}
td,th{border:1px solid #ccc;padding:4px 8px;text-align:left}.fail{background:#fdd}.warn{background:#ffe9b3}.ok{background:#e6f4e6}
.card{display:inline-block;vertical-align:top;margin:8px;padding:8px;border:1px solid #ccc;background:#fff;width:784px}
.mosaic{position:relative;width:768px;height:768px;display:grid;grid-template-columns:repeat(3,256px)}.mosaic img{display:block;width:256px;height:256px}
.cross{position:absolute;width:24px;height:24px;margin:-12px 0 0 -12px;border:2px solid #ff0;border-radius:50%;box-shadow:0 0 0 2px #000}
.meta{margin-top:6px}.warning{color:#a60;font-weight:600}footer{margin-top:24px;color:#666}"""


def write_report_json(results: list[CheckResult], path: Path, extra: dict | None = None) -> dict:
    per_check: dict[str, dict[str, int]] = {}
    for r in results:
        slot = per_check.setdefault(r.check, {"passed": 0, "failed": 0})
        slot["passed" if r.passed else "failed"] += 1
    summary = {"blocking_failures": sum(1 for r in results if r.blocking and not r.passed),
               "warnings": sum(1 for r in results if not r.blocking and not r.passed), "per_check": per_check}
    payload = {**(extra or {}), "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "summary": summary,
               "results": [r.to_dict() for r in results]}
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    return summary


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _details(details: dict) -> str:
    return html.escape(json.dumps(details, ensure_ascii=False, default=str))


def _excluded_table(excluded: list[dict], names: dict[str, str]) -> str:
    """The poles the stage dropped, grouped by unit: whoever reads the report has to see them by name."""
    rows = []
    for e in sorted(excluded, key=lambda e: (e["unit"], e["scenario"], e["rank"])):
        rows.append(f'<tr class="warn"><td>{html.escape(names.get(e["unit"], e["unit"]))}</td><td>{e["scenario"]}</td>'
                    f'<td>{e["rank"]}</td><td>{e["lat"]:.5f}, {e["lon"]:.5f}</td><td>{e["dist_m"] / 1000:.2f} km</td>'
                    f'<td><code>{_details(e["details"])}</code></td></tr>')
    return (f"<h2>{_plural(len(excluded), 'excluded pole')}</h2>"
            "<p>Closer to the edge of the data than to the nearest road, so the road that would beat it may "
            "simply be outside the extract. These stay in the poles stage output; every stage after this one "
            "skips them.</p>"
            "<table><tr><th>Unit</th><th>Scenario</th><th>Rank</th><th>Position</th><th>Distance</th>"
            f"<th>Details</th></tr>{''.join(rows)}</table>")


def write_report_html(results: list[CheckResult], units: list[Unit], path: Path, title: str,
                      excluded: list[dict] | None = None) -> None:
    blocking = [r for r in results if r.blocking and not r.passed]
    warnings = [r for r in results if not r.blocking and not r.passed]
    names = {u.code: u.name_en or u.code for u in units}
    rows = []
    for r in sorted(results, key=lambda r: (r.unit, r.scenario, r.check)):
        cls = "ok" if r.passed else ("fail" if r.blocking else "warn")
        rows.append(f'<tr class="{cls}"><td>{html.escape(names.get(r.unit, r.unit))}</td><td>{r.scenario}</td><td>{r.check}</td>'
                    f'<td>{"pass" if r.passed else ("FAIL" if r.blocking else "warning")}</td><td><code>{_details(r.details)}</code></td></tr>')
    page = (f"<!doctype html><meta charset='utf-8'><title>{html.escape(title)}</title><style>{CSS}</style><h1>{html.escape(title)}</h1>"
            f"<p>{_plural(len(blocking), 'blocking failure')}, {_plural(len(warnings), 'warning')}, {len(results)} results over {len(units)} units.</p>"
            f"{_excluded_table(excluded, names) if excluded else ''}"
            f"<h2>Checks</h2><table><tr><th>Unit</th><th>Scenario</th><th>Check</th><th>Result</th><th>Details</th></tr>{''.join(rows)}</table>")
    path.write_text(page, encoding="utf-8")


def tile_xy(lon: float, lat: float, z: int) -> tuple[float, float]:
    n = 2 ** z
    x = (lon + 180.0) / 360.0 * n
    lat_r = math.radians(lat)
    y = (1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi) / 2.0 * n
    return x, y


def fetch_esri_tile(z: int, x: int, y: int) -> bytes:
    req = urllib.request.Request(ESRI_URL.format(z=z, x=x, y=y), headers={"User-Agent": USER_AGENT})
    last: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return resp.read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1 + attempt)
    raise RuntimeError(f"tile {z}/{x}/{y} failed three times: {last}")


def _mime(data: bytes) -> str:
    """Esri serves JPEG over most land and PNG over the empty tiles; a data URI declaring the wrong one is
    at the mercy of the browser's sniffing, so read it off the magic bytes."""
    return "image/jpeg" if data[:2] == b"\xff\xd8" else "image/png"


def _km(d_m: float) -> str:
    return f"{d_m / 1000:.2f} km"


def _mosaic(lon: float, lat: float, zoom: int, fetch_tile) -> tuple[str, int]:
    """The 3x3 tile mosaic around lon/lat with a crosshair, and how many tiles would not download.

    A tile server that drops one request must not cost the whole report, so a failed tile becomes a blank
    and the count travels back to the card.
    """
    fx, fy = tile_xy(lon, lat, zoom)
    cx, cy = int(fx), int(fy)
    imgs, failed = [], 0
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            try:
                tile = fetch_tile(zoom, cx + dx, cy + dy)
            except Exception:  # noqa: BLE001
                tile, failed = BLANK_PNG, failed + 1
            data = base64.b64encode(tile).decode("ascii")
            imgs.append(f'<img src="data:{_mime(tile)};base64,{data}" alt="">')
    px = (fx - cx + 1) * 256
    py = (fy - cy + 1) * 256
    return f'<div class="mosaic">{"".join(imgs)}<div class="cross" style="left:{px:.0f}px;top:{py:.0f}px"></div></div>', failed


def _place_line(place: dict) -> str:
    if not place or place.get("name") is None:
        return "nearest place: none in the place layer"
    return f"nearest place: {html.escape(str(place['name']))} ({place.get('type')}, {_km(place['dist_m'])})"


def write_contact_sheet(poles: dict[str, list[dict]], units: list[Unit], results: list[CheckResult], path: Path,
                        fetch_tile=fetch_esri_tile, zoom: int = 13, title: str = "",
                        excluded: list[dict] | None = None) -> None:
    entries = {(s, e["unit"]): e for s, es in poles.items() for e in es}
    dropped = {(e["scenario"], e["unit"], e["rank"]) for e in excluded or []}
    flagged: dict[tuple[str, str], list[str]] = {}
    for r in results:
        if r.passed or r.check not in ("holes", "reference"):
            continue
        text = "probable import gap: no road within 10 km, dense roads 10 to 30 km out" if r.check == "holes" \
            else f"reference {r.details.get('name') or r.details.get('source')}: {json.dumps({k: v for k, v in r.details.items() if k in ('ref_m', 'ours_m', 'moved_m', 'note')}, ensure_ascii=False)}"
        flagged.setdefault((r.scenario, r.unit), []).append(text)
    cards = []
    for u in units:
        for s in sorted(poles):
            e = entries.get((s, u.code))
            head = f"<h2>{html.escape(u.name_en or u.code)} ({u.code}) scenario {s}</h2>"
            out = [p for p in (e or {}).get("poles", []) if (s, u.code, p["rank"]) not in dropped]
            gone = len((e or {}).get("poles", [])) - len(out)
            note = f'<p class="warning">{_plural(gone, "pole")} excluded beyond the data edge</p>' if gone else ""
            if not e or not out:
                reason = html.escape((e or {}).get("reason") or "no poles") if not gone else "every pole excluded"
                cards.append(f'<div class="card">{head}{note}<p class="warning">{reason}</p></div>')
                continue
            p = out[0]
            way, place = p["nearest_way"], p["nearest_place"] or {}
            way_txt = " ".join(str(v) for v in (way.get("highway"), way.get("name") or way.get("ref")) if v)
            mosaic, failed = _mosaic(p["lon"], p["lat"], zoom, fetch_tile)
            lines = [f"rank {p['rank']}: <b>{_km(p['dist_m'])}</b> from the nearest drivable way at {p['lat']:.5f}, {p['lon']:.5f}",
                     f"nearest way: {html.escape(way_txt)} (osm way {way['id']}, {way.get('country')})",
                     _place_line(place)]
            for w in flagged.get((s, u.code), []):
                lines.append(f'<span class="warning">{html.escape(w)}</span>')
            if failed:
                lines.append(f'<span class="warning">{_plural(failed, "satellite tile")} did not download</span>')
            cards.append(f'<div class="card">{head}{note}{mosaic}<div class="meta">{"<br>".join(lines)}</div></div>')
    page = (f"<!doctype html><meta charset='utf-8'><title>{html.escape(title)}</title><style>{CSS}</style><h1>{html.escape(title)}</h1>"
            f"{''.join(cards)}<footer>{ESRI_ATTRIBUTION}. Map data: OpenStreetMap contributors, ODbL.</footer>")
    path.write_text(page, encoding="utf-8")

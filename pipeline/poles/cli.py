"""poles run <region> [--stage X] [--snapshot YYYY-MM-DD] [--work DIR] [--regions-dir DIR] [--force]"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import http
from .config import ConfigError, RegionConfig, load_region
from .logsetup import get_logger
from .runner import run_pipeline
from .stages import ORDER, registry
from .workspace import Workspace


def regions_dir(explicit: str | None) -> Path:
    return Path(explicit or os.environ.get("POLES_REGIONS") or Path(__file__).resolve().parents[1] / "regions")


def resolve_snapshot(cfg: RegionConfig) -> str:
    info = http.head(cfg.sources[0])
    if info["last_modified"] is None:
        raise ConfigError(f"{cfg.sources[0]} sent no Last-Modified header; pass --snapshot")
    return http.snapshot_id(info["last_modified"])


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="poles", description="Pole of remoteness pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run the pipeline for a region")
    r.add_argument("region", help="region id, resolved to <regions-dir>/<region>.yaml")
    r.add_argument("--stage", choices=ORDER, help="run this stage only")
    r.add_argument("--snapshot", help="YYYY-MM-DD; default: Last-Modified date of the primary source")
    r.add_argument("--work", default=os.environ.get("POLES_WORK", "work"), help="work directory (default: ./work or $POLES_WORK)")
    r.add_argument("--regions-dir", help="directory of region YAML files (default: pipeline/regions or $POLES_REGIONS)")
    r.add_argument("--force", action="store_true", help="rerun stages even if their done.json exists")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    path = regions_dir(args.regions_dir) / f"{args.region}.yaml"
    if not path.is_file():
        print(f"poles: unknown region '{args.region}': no {path}", file=sys.stderr)
        return 2
    try:
        cfg = load_region(path)
        snapshot = args.snapshot or resolve_snapshot(cfg)
    except ConfigError as e:
        print(f"poles: {e}", file=sys.stderr)
        return 2
    ws = Workspace(args.work, cfg.id, snapshot)
    log = get_logger(ws)
    log.info("poles run %s snapshot %s work %s%s", cfg.id, snapshot, ws.base, " (forced)" if args.force else "")
    if not args.snapshot:
        log.info("snapshot taken from the primary source's Last-Modified; pass --snapshot %s to resume this one later", snapshot)
    run_pipeline(cfg, ws, log, only=args.stage, force=args.force, registry=registry())
    return 0


if __name__ == "__main__":
    sys.exit(main())

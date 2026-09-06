#!/usr/bin/env python3
"""Find (and only on request delete) the detail objects in R2 that no published site document references.

Issue #57: detail rasters used to be keyed by rank (`detail/<code>/A-1`), so a re-search that reorders a
unit's poles left the old objects behind. The new keys carry the pole's identity, which makes the stale
rank-keyed pairs orphans: listed under `<region>/<snapshot>/detail/` and named by no unit document. This
script lists that prefix, collects every `detail` value from `<data>/<region>/units/*.json` (both
scenarios, every pole), and reports the difference. A key whose stem (its name without the final
extension) is referenced is kept, so one pole's `.png` and `.json` are kept or dropped together.

Dry run by default: nothing goes without --delete, and deletion only ever touches keys under
`<region>/<snapshot>/detail/<code>/`; archives, validation files and anything directly under `detail/`
are refused by a guard before every delete call. Needs the five R2 variables of pipeline/README.md:
POLES_R2_ACCOUNT_ID, POLES_R2_BUCKET, POLES_R2_TOKEN_FILE, POLES_R2_ACCESS_KEY_ID_FILE, POLES_R2_SECRET_FILE.

Usage (from the repository root):
  pipeline/.venv/bin/python dev/prune-r2.py             # dry run, writes the orphan list
  pipeline/.venv/bin/python dev/prune-r2.py --delete    # after reviewing that list
  pipeline/.venv/bin/python dev/prune-r2.py --self-test # offline check against a fake client
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from poles.errors import PolesError  # noqa: E402
from poles.publish import r2  # noqa: E402

SCENARIOS, BATCH, PREVIEW = ("A", "B"), 1000, 20


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def referenced_stems(data: Path, region: str) -> set[str]:
    """Every `detail` value in a region's unit documents, as a key stem relative to `<region>/<snapshot>/`."""
    stems: set[str] = set()
    for unit in load_json(data / region / "units.json")["units"]:
        doc = load_json(data / region / "units" / f"{unit['code']}.json")
        for scenario in SCENARIOS:
            for pole in doc.get(scenario, {}).get("poles", []):
                if pole.get("detail"):
                    stems.add(pole["detail"])
    return stems


def list_prefix(client, bucket: str, prefix: str) -> list[tuple[str, int]]:
    pages = client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix)
    return [(o["Key"], o["Size"]) for page in pages for o in page.get("Contents", [])]


def classify(listed: list[tuple[str, int]], snapshot_prefix: str, stems: set[str]) -> dict:
    """Split the listed keys into referenced, orphaned, and skipped (anything not `detail/<code>/<file>`)."""
    kept, orphans, skipped = [], [], []
    for key, size in listed:
        rel = key[len(snapshot_prefix):]
        parts = rel.split("/")
        if len(parts) != 3 or parts[0] != "detail" or not parts[1] or not parts[2]:
            skipped.append(key)
            continue
        stem = rel.rsplit(".", 1)[0] if "." in parts[2] else rel
        (kept if stem in stems else orphans).append((key, size))
    return {"kept": kept, "orphans": orphans, "skipped": skipped}


def assert_safe(keys: list[str], detail_prefix: str) -> None:
    """Refuse anything outside `<region>/<snapshot>/detail/<code>/`. Runs before every delete call."""
    for key in keys:
        rest = key[len(detail_prefix):] if key.startswith(detail_prefix) else ""
        if rest.count("/") != 1 or not rest.split("/")[1] or key.endswith(".pmtiles") or "/validation/" in key:
            raise RuntimeError(f"refusing to delete {key}: only {detail_prefix}<code>/<file> may be deleted")


def delete_keys(client, bucket: str, keys: list[str], detail_prefix: str, log) -> int:
    assert_safe(keys, detail_prefix)
    for start in range(0, len(keys), BATCH):
        chunk = keys[start:start + BATCH]
        assert_safe(chunk, detail_prefix)
        client.delete_objects(Bucket=bucket, Delete={"Objects": [{"Key": k} for k in chunk], "Quiet": True})
        log.write("".join(f"deleted {k}\n" for k in chunk))
    return len(keys)


def run(client, bucket: str, data: Path, out: Path, delete: bool) -> dict:
    summary = {"bucket": bucket, "regions": [], "deleted": 0}
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as log:
        log.write(f"# prune-r2 {date.today().isoformat()} bucket {bucket} {'DELETE' if delete else 'dry run'}\n")
        for entry in load_json(data / "regions.json")["regions"]:
            region, snapshot = entry["id"], entry["snapshot"]
            detail_prefix = f"{region}/{snapshot}/detail/"
            listed = list_prefix(client, bucket, detail_prefix)
            stems = referenced_stems(data, region)
            split = classify(listed, f"{region}/{snapshot}/", stems)
            orphans = split["orphans"]
            orphan_bytes = sum(size for _, size in orphans)
            print(f"\n== {region} {snapshot} ==\nlisted under {detail_prefix}: {len(listed)} objects\n"
                  f"referenced by the unit documents: {len(stems)} stems, {len(split['kept'])} objects\n"
                  f"orphans: {len(orphans)} objects, {orphan_bytes / 1e6:.1f} MB")
            if split["skipped"]:
                print(f"skipped (not detail/<code>/<file>, never deleted): {len(split['skipped'])}"
                      f" e.g. {split['skipped'][0]}")
            print("\n".join(f"  {key}" for key, _ in orphans[:PREVIEW]) or "  (no orphans)")
            if len(orphans) > PREVIEW:
                print(f"  ... {len(orphans) - PREVIEW} more, full list in {out}")
            log.write(f"\n# {region} {snapshot}: {len(orphans)} orphans, {orphan_bytes} bytes\n")
            log.write("".join(f"{key} {size}\n" for key, size in orphans))
            record = {"region": region, "snapshot": snapshot, "listed": len(listed), "deleted": 0,
                      "referenced_objects": len(split["kept"]), "referenced_stems": len(stems),
                      "orphans": len(orphans), "orphan_bytes": orphan_bytes, "skipped": len(split["skipped"])}
            if delete and orphans:
                record["deleted"] = delete_keys(client, bucket, [k for k, _ in orphans], detail_prefix, log)
                summary["deleted"] += record["deleted"]
                print(f"deleted {record['deleted']} objects")
            summary["regions"].append(record)
    print(f"\nwrote {out}")
    if not delete:
        print("dry run: nothing was deleted; pass --delete to remove the orphans listed above")
    return summary


class _FakeClient:
    """Offline stand-in for the boto3 S3 client: the two calls this script makes and nothing else."""

    def __init__(self, objects: list[tuple[str, int]]):
        self.objects, self.deleted = objects, []

    def get_paginator(self, name: str):
        if name != "list_objects_v2":
            raise AssertionError(name)
        outer = self

        class _Paginator:
            def paginate(self, Bucket, Prefix):  # noqa: N803 (boto3 spelling)
                hits = [{"Key": k, "Size": s} for k, s in outer.objects if k.startswith(Prefix)]
                for start in range(0, max(len(hits), 1), 2):  # more than one page, to exercise the paginator
                    yield {"Contents": hits[start:start + 2]}

        return _Paginator()

    def delete_objects(self, Bucket, Delete):  # noqa: N803 (boto3 spelling)
        self.deleted += [o["Key"] for o in Delete["Objects"]]
        return {"Deleted": [{"Key": o["Key"]} for o in Delete["Objects"]]}


def self_test() -> None:
    """Whole run against a fake client: a referenced pair kept, a rank-keyed pair deleted, the rest refused."""
    tmp = Path(tempfile.mkdtemp(prefix="prune-r2-selftest-"))
    data = tmp / "data"
    (data / "r" / "units").mkdir(parents=True)
    for rel, doc in (("regions.json", {"regions": [{"id": "r", "snapshot": "s"}]}),
                     ("r/units.json", {"units": [{"code": "lt"}]}),
                     ("r/units/lt.json", {"A": {"poles": [{"detail": "detail/lt/A-54.4_23.5"}]},
                                          "B": {"poles": [{"detail": None}]}})):
        (data / rel).write_text(json.dumps(doc), encoding="utf-8")
    client = _FakeClient([("r/s/detail/lt/A-54.4_23.5.png", 10), ("r/s/detail/lt/A-54.4_23.5.json", 20),
                          ("r/s/detail/lt/A-1.png", 30), ("r/s/detail/lt/A-1.json", 40),
                          ("r/s/detail/published.json", 50), ("r/s/A.pmtiles", 60), ("r/s/validation/r.json", 70)])
    record = run(client, "b", data, tmp / "out.txt", delete=True)["regions"][0]
    assert (record["listed"], record["referenced_objects"], record["skipped"]) == (5, 2, 1), record
    assert (record["orphans"], record["orphan_bytes"], record["deleted"]) == (2, 70, 2), record
    assert sorted(client.deleted) == ["r/s/detail/lt/A-1.json", "r/s/detail/lt/A-1.png"], client.deleted
    for bad in ("r/s/A.pmtiles", "r/s/validation/r.json", "r/s/detail/published.json", "o/s/detail/lt/A-1.png"):
        try:
            assert_safe([bad], "r/s/detail/")
            raise AssertionError(f"the guard let through {bad}")
        except RuntimeError:
            pass
    print(f"self-test passed (scratch under {tmp})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=ROOT / "site" / "data", help="published site data directory")
    ap.add_argument("--out", type=Path, default=ROOT / "work" / f"prune-r2-{date.today().isoformat()}.txt",
                    help="where the full orphan list (and the deletion log) is written")
    ap.add_argument("--delete", action="store_true", help="actually delete the orphans; dry run without it")
    ap.add_argument("--self-test", action="store_true", help="run the offline check against a fake client and exit")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    try:
        cfg = r2.R2Config.from_env(os.environ)
    except PolesError as exc:
        sys.exit(f"prune-r2: {exc}")
    run(r2.s3_client(cfg), cfg.bucket, args.data, args.out, args.delete)


if __name__ == "__main__":
    main()

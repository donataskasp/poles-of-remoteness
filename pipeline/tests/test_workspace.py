from poles.workspace import Workspace


def test_workspace_done_marker_roundtrip(tmp_path):
    ws = Workspace(tmp_path, "europe", "2026-08-19")
    assert not ws.is_done("fetch")
    ws.mark_done("fetch", {"duration_s": 1.5, "files": 6})
    assert ws.is_done("fetch")
    meta = ws.meta("fetch")
    assert meta["duration_s"] == 1.5 and meta["files"] == 6
    assert meta["stage"] == "fetch" and meta["region"] == "europe" and meta["snapshot"] == "2026-08-19"
    assert meta["finished_at"].endswith("+00:00")
    ws.clear_done("fetch")
    assert not ws.is_done("fetch")
    ws.clear_done("fetch")  # idempotent


def test_workspace_dirs_are_per_region_snapshot_stage(tmp_path):
    ws = Workspace(tmp_path, "europe", "2026-08-19")
    grid = ws.dir("grid")
    assert grid == tmp_path / "europe" / "2026-08-19" / "grid" and grid.is_dir()
    assert ws.base == tmp_path / "europe" / "2026-08-19"
    other = Workspace(tmp_path, "north-america", "2026-09-01")
    assert other.dir("grid") != grid
    assert ws.shared_dir() == other.shared_dir() == tmp_path / "shared"
    assert ws.shared_dir().is_dir()

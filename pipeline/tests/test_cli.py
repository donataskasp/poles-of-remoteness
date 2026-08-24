from poles import cli
from poles.runner import run_pipeline
from poles.stages import ORDER, registry
from poles.workspace import Workspace


def _stubs(calls: list[str]):
    def make(name):
        def stage(cfg, ws, log):
            calls.append(name)
            return {"n": 1}
        return stage
    return {name: make(name) for name in ORDER}


def test_registry_lists_all_seven_stages_in_order():
    assert ORDER == ("fetch", "extract", "classify", "grid", "poles", "validate", "publish")
    assert tuple(registry()) == ORDER


def test_run_executes_stages_in_order_and_skips_done(tmp_path, cfg, log):
    calls: list[str] = []
    ws = Workspace(tmp_path, "europe", "2026-08-19")
    ws.mark_done("extract", {})
    executed = run_pipeline(cfg, ws, log, only=None, force=False, registry=_stubs(calls))
    assert calls == ["fetch", "classify", "grid", "poles", "validate", "publish"]
    assert executed == calls
    assert all(ws.is_done(name) for name in ORDER)
    meta = ws.meta("fetch")
    assert meta["n"] == 1 and "duration_s" in meta and "peak_rss_self_bytes" in meta and "disk_bytes" in meta


def test_stage_flag_runs_single_stage(tmp_path, cfg, log):
    calls: list[str] = []
    ws = Workspace(tmp_path, "europe", "2026-08-19")
    run_pipeline(cfg, ws, log, only="grid", force=False, registry=_stubs(calls))
    assert calls == ["grid"]
    assert ws.is_done("grid") and not ws.is_done("fetch")


def test_force_reruns_done_stage(tmp_path, cfg, log):
    calls: list[str] = []
    ws = Workspace(tmp_path, "europe", "2026-08-19")
    ws.mark_done("grid", {"n": 0})
    run_pipeline(cfg, ws, log, only="grid", force=False, registry=_stubs(calls))
    assert calls == []
    run_pipeline(cfg, ws, log, only="grid", force=True, registry=_stubs(calls))
    assert calls == ["grid"] and ws.meta("grid")["n"] == 1


def test_unimplemented_stage_stops_the_run(tmp_path, cfg, log):
    calls: list[str] = []
    reg = _stubs(calls)
    reg["poles"] = None
    run_pipeline(cfg, ws := Workspace(tmp_path, "europe", "2026-08-19"), log, only=None, force=False, registry=reg)
    assert calls == ["fetch", "extract", "classify", "grid"]
    assert not ws.is_done("poles")


def test_failing_stage_leaves_no_done_marker(tmp_path, cfg, log):
    def boom(cfg, ws, log):
        raise RuntimeError("osmium exploded")
    reg = _stubs([])
    reg["fetch"] = boom
    ws = Workspace(tmp_path, "europe", "2026-08-19")
    try:
        run_pipeline(cfg, ws, log, only="fetch", force=False, registry=reg)
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected the stage error to propagate")
    assert not ws.is_done("fetch")


def test_unknown_region_fails_with_message(tmp_path, capsys):
    rc = cli.main(["run", "atlantis", "--snapshot", "2026-01-01", "--work", str(tmp_path)])
    assert rc == 2
    assert "unknown region 'atlantis'" in capsys.readouterr().err


def test_cli_resolves_region_file_and_workspace(tmp_path, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(cli, "registry", lambda: _stubs(calls))
    rc = cli.main(["run", "europe", "--stage", "fetch", "--snapshot", "2026-08-19", "--work", str(tmp_path)])
    assert rc == 0 and calls == ["fetch"]
    assert (tmp_path / "europe" / "2026-08-19" / "fetch" / "done.json").is_file()
    assert (tmp_path / "europe" / "2026-08-19" / "log.txt").is_file()


def test_run_cmd_failure_names_the_command(log):
    from poles.shell import ToolError, run_cmd
    try:
        run_cmd(["sh", "-c", "echo nope >&2; exit 3"], log)
    except ToolError as e:
        assert "exit 3" in str(e) and "sh -c" in str(e) and "nope" in str(e)
    else:
        raise AssertionError("expected ToolError")


def test_run_cmd_measures_duration_and_rss(log):
    from poles.shell import run_cmd
    res = run_cmd(["sh", "-c", "sleep 0.2"], log)
    assert res.returncode == 0 and res.duration_s >= 0.2 and res.max_rss_bytes > 0


def test_run_cmd_failure_reads_the_tail_from_a_redirected_stderr_file(tmp_path, log):
    from poles.shell import ToolError, run_cmd
    err = tmp_path / "stderr.log"
    try:
        run_cmd(["sh", "-c", "echo nope >&2; exit 3"], log, stderr_path=err)
    except ToolError as e:
        assert "exit 3" in str(e) and "nope" in str(e)
    else:
        raise AssertionError("expected ToolError")
    assert "nope" in err.read_text(encoding="utf-8")

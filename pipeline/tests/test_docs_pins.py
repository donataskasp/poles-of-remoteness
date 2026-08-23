"""Executable doc pins: the docs that claim to describe the code are checked against it.

A failing test here means a doc drifted, not that the code is wrong. Fix the doc (or the table) in the same
commit as the change that moved the code."""
from pathlib import Path

import pytest
import yaml

from poles.stages import ORDER

ROOT = Path(__file__).resolve().parents[2]
REGIONS = sorted((ROOT / "pipeline" / "regions").glob("*.yaml"))
REGION_CONFIGS = [p for p in REGIONS if not p.name.endswith("-refs.yaml")]


def _text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


@pytest.mark.parametrize("stage", ORDER)
def test_every_stage_is_in_the_pipeline_readme_and_the_pipeline_diagram(stage):
    assert f"`{stage}`" in _text("pipeline/README.md")
    assert stage in _text("docs/diagrams/01-pipeline.md")


@pytest.mark.parametrize("path", REGION_CONFIGS, ids=lambda p: p.stem)
def test_every_region_config_key_is_documented(path):
    keys = yaml.safe_load(path.read_text(encoding="utf-8")).keys()
    readme = _text("pipeline/README.md")
    missing = [k for k in keys if f"`{k}`" not in readme]
    assert not missing, f"{path.name}: keys without a row in pipeline/README.md: {missing}"


@pytest.mark.parametrize("path", REGION_CONFIGS, ids=lambda p: p.stem)
def test_every_region_has_a_status_line_in_overview(path):
    region_id = yaml.safe_load(path.read_text(encoding="utf-8"))["id"]
    assert f"`{region_id}`" in _text("docs/OVERVIEW.md")


def test_every_diagram_is_indexed_and_carries_the_two_required_sections():
    index = _text("docs/diagrams/README.md")
    files = sorted((ROOT / "docs" / "diagrams").glob("[0-9][0-9]-*.md"))
    assert files, "no diagrams"
    for f in files:
        assert f.name in index, f"{f.name} missing from docs/diagrams/README.md"
        body = f.read_text(encoding="utf-8")
        assert "## At a glance" in body and "```mermaid" in body, f"{f.name}: no at-a-glance diagram"
        assert "Reflects the code at " in body, f"{f.name}: no reflects line"


def test_no_em_dashes_in_the_docs_touched_by_this_round():
    for rel in ("CLAUDE.md", "docs/OVERVIEW.md", "docs/DECISIONS.md", "docs/LOG.md", "pipeline/README.md", "README.md",
                *(f"docs/diagrams/{p.name}" for p in (ROOT / "docs" / "diagrams").glob("*.md"))):
        assert "\u2014" not in _text(rel), rel

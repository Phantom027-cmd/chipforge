"""Docs must not drift: generated references are current, and every YAML example in the docs is valid
(and renders, when it is a complete song)."""
import re
import subprocess
import sys
from pathlib import Path

import pytest

from chipforge import loads
from tests.conftest import ROOT

DOCS = ["README.md", "QUICKREF.md", "SONG_FORMAT.md", "CUE_GUIDE.md", "AGENT_WORKFLOW.md", "SKILL.md"]


def test_generated_docs_are_current():
    r = subprocess.run([sys.executable, "-m", "chipforge.docgen", "--check"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def _yaml_blocks():
    for doc in DOCS:
        p = ROOT / doc
        if not p.exists():
            continue
        for i, block in enumerate(re.findall(r"```yaml\n(.*?)```", p.read_text(encoding="utf-8"), re.S)):
            yield f"{doc}#{i}", block


@pytest.mark.parametrize("name,block", list(_yaml_blocks()))
def test_doc_examples_are_valid_songs(name, block):
    if "chipforge:" not in block:
        pytest.skip("fragment, not a complete song")
    song = loads(block, file=name)
    from chipforge.render import render
    r = render(song, stems=False)
    assert r.mix.shape[0] > 0


def test_quickref_is_one_page():
    lines = (ROOT / "QUICKREF.md").read_text(encoding="utf-8").splitlines()
    assert len(lines) <= 150, f"QUICKREF.md is {len(lines)} lines; keep it under 150"

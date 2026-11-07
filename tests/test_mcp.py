"""MCP tools exercised in-process (the stdio transport is the SDK's)."""
import asyncio
import json
from pathlib import Path

import pytest

mcp = pytest.importorskip("mcp")
from chipforge import mcp_server as M  # noqa: E402


def _call(name, **args):
    return asyncio.run(M.server.call_tool(name, args))


def test_tool_list():
    names = {t.name for t in asyncio.run(M.server.list_tools())}
    assert names == {"get_quickref", "list_presets", "validate_song", "render_song", "analyze_audio",
                     "compare_versions", "read_feedback", "new_song_from_template", "build_review_page"}


def test_quickref_and_presets():
    assert "chipforge: 1" in _call("get_quickref").content[0].text
    txt = _call("list_presets", category="kit").content[0].text
    assert "kit.nes:" in txt and "[pieces:" in txt
    assert "no category" in _call("list_presets", category="zzz").content[0].text


def test_template_validate_render_feedback(tmp_path):
    p = tmp_path / "v.yml"
    r = _call("new_song_from_template", cue="victory", path=str(p), title="Win", tempo=150)
    assert "wrote" in r.content[0].text and p.exists()
    assert _call("validate_song", path=str(p)).content[0].text.startswith("ok: 'Win'")
    assert "unknown cue" in _call("new_song_from_template", cue="nope", path=str(p)).content[0].text
    r = _call("render_song", path=str(p), out_dir=str(tmp_path / "out"), formats="wav", stems=False)
    types = [c.type for c in r.content]
    assert types[0] == "text" and "image" in types
    assert "rendered 'Win'" in r.content[0].text and "analysis:" in r.content[0].text
    assert "no feedback yet" in _call("read_feedback", path=str(p)).content[0].text
    (tmp_path / "feedback.json").write_text(json.dumps({"entries": [{"time": "2026-11-07T10:00", "at": 2.5, "note": "too bright", "rating": 3}]}))
    txt = _call("read_feedback", path=str(p)).content[0].text
    assert "too bright" in txt and "@ 2.5s" in txt


def test_validate_error_is_short_and_located(tmp_path):
    p = tmp_path / "bad.yml"
    p.write_text("chipforge: 1\ntitle: x\ncue: boss\ntempo: 120\nchannels: {l: {preset: lead.pulse2}}\npatterns: {A: {bars: 1}}\narrangement: [A]\n")
    txt = _call("validate_song", path=str(p)).content[0].text
    assert txt.startswith("error:") and "bad.yml:5" in txt and "lead.pulse25" in txt


@pytest.mark.parametrize("tpl", sorted(Path(M.TEMPLATES).glob("*.yml")), ids=lambda p: p.stem)
def test_templates_render(tpl):
    from chipforge import load
    from chipforge.render import render
    r = render(load(tpl), stems=False)
    assert r.mix.shape[0] > 0 and abs(r.mix).max() > 0.05

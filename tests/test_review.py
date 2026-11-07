"""Review page: version snapshots, page build, feedback save via the local server."""
import json
import urllib.request
from pathlib import Path

from chipforge import loads
from chipforge.export import write_all
from chipforge.render import render
from chipforge.review import build_page, save_feedback, serve, snapshot_version
from tests.conftest import MINI


def _render(tmp_path, text, name="mini.yml"):
    p = tmp_path / name
    p.write_text(text)
    write_all(render(loads(text), stems=True), tmp_path / "out", formats=("ogg",))
    return p


def test_snapshot_build_and_feedback(tmp_path):
    p = _render(tmp_path, MINI)
    out = tmp_path / "out"
    v1 = snapshot_version(p, out)
    assert v1["version"] == "v1" and (out / "versions" / v1["audio"]).exists() and "layer1" in v1["stems"]
    assert snapshot_version(p, out)["version"] == "v1"              # unchanged song -> same version
    p.write_text(MINI.replace("tempo: 150", "tempo: 140"))
    write_all(render(loads(p.read_text()), stems=False), out, formats=("ogg",))
    assert snapshot_version(p, out)["version"] == "v2"
    page = build_page(p, out)
    html = page.read_text(encoding="utf-8")
    assert "data:audio/ogg;base64," in html and '"version": "v2"' in html and "<script>" in html
    save_feedback(out, p, [{"time": "2026-11-07T10:00:00", "version": "v2", "at": 1.2, "note": "nice", "rating": 5}])
    save_feedback(out, p, [{"time": "2026-11-07T10:00:00", "version": "v2", "at": 1.2, "note": "nice", "rating": 5}])
    fb = json.loads((out / "feedback.json").read_text())
    assert len(fb["entries"]) == 1                                   # de-duplicated
    html = build_page(p, out).read_text(encoding="utf-8")
    assert '"note": "nice"' in html                                   # existing feedback embedded


def test_server_roundtrip(tmp_path):
    p = _render(tmp_path, MINI)
    out = tmp_path / "out"
    snapshot_version(p, out)
    build_page(p, out)
    httpd, url = serve(out, p, port=0, open_browser=False, block=False)
    try:
        assert b"ChipForge review" in urllib.request.urlopen(url).read()
        body = json.dumps({"entries": [{"time": "2026-11-07T11:00:00", "version": "v1", "at": None, "note": "approved", "verdict": "approve"}]}).encode()
        req = urllib.request.Request(url.replace("review.html", "feedback"), data=body, headers={"Content-Type": "application/json"})
        assert json.loads(urllib.request.urlopen(req).read())["ok"]
        fb = json.loads(urllib.request.urlopen(url.replace("review.html", "feedback.json")).read())
        assert fb["entries"][0]["verdict"] == "approve"
    finally:
        httpd.shutdown()
        httpd.server_close()
    from chipforge import mcp_server as M
    import asyncio
    txt = asyncio.run(M.server.call_tool("read_feedback", {"path": str(out)})).content[0].text
    assert "approved" in txt

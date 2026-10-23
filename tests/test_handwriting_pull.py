"""Handwriting from the cloud: rclone copy (never sync) of the kinds Handwritten notes reads into its folder, new
files start a scan, metered connections are skipped, a failure is told once."""

from __future__ import annotations

import pytest

RCLONE = """#!/bin/sh
echo "$@" >> @LOG@
[ -f "$FAIL" ] && { echo "Failed to copy: couldn't find remote" >&2; exit 1; }
[ "$1" = copy ] && : > "$3/page-07.pdf"
exit 0
"""
NMCLI = '#!/bin/sh\necho "$@" >> @LOG@\necho "$METERED"\n'


@pytest.fixture
def app(env, load_addon, fake_programs, tmp_path, monkeypatch):
    d = fake_programs({"rclone": RCLONE, "nmcli": NMCLI})
    monkeypatch.setenv("FAIL", str(tmp_path / "fail"))
    monkeypatch.setenv("METERED", "no")
    load_addon("handwriting-pull", env.app)
    env.app.settings.set("handwritten.folder", str(tmp_path / "scans"))
    env.app.settings.set("handwritten.local_model", "fake-vision")  # nothing is read in these tests
    env.app.settings.set("handwritten.cloud", False)
    env.on("handwritten")
    env.app.settings.set("hw_pull.remote", "cloud:Handwritten")
    env.on("hw_pull")
    return env.app, d


def test_new_pages_are_copied_never_synced_and_read_at_once(app, env, monkeypatch):
    a, d = app
    scans = []
    monkeypatch.setattr(a.modules["handwritten"], "spawn", lambda force=False: scans.append(1) or True)
    said = env.say("/hwpull now")
    assert "1 new page file: page-07.pdf" in said
    log = (d / "rclone.log").read_text()
    assert log.startswith("copy cloud:Handwritten ") and "--max-depth 1" in log and "--include *.pdf" in log
    assert "sync" not in log
    assert scans == [1]
    assert "1 new" in env.say("/hwpull")


def test_a_metered_connection_waits(app, monkeypatch):
    a, d = app
    monkeypatch.setenv("METERED", "yes (guessed)")
    ok, said = a.modules["hw_pull"].pull("scheduled")
    assert not ok and "metered" in said and not (d / "rclone.log").exists()


def test_a_failure_is_told_once(app, env, tmp_path):
    a, _d = app
    (tmp_path / "fail").write_text("x")
    m = a.modules["hw_pull"]
    m.pull("scheduled")
    m.pull("scheduled")
    told = [t for t in env.fake.texts() if "Couldn't copy handwritten pages" in t]
    assert len(told) == 1
    assert m.health_check().probe(False)[0] is False

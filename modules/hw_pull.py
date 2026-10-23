"""Handwriting from the cloud: your tablet's notes app saves pages to a cloud folder (Google Drive, OneDrive,
Dropbox, Nextcloud...), and this copies the new ones with rclone into Handwritten notes' folder, where Kurooto writes
them out. It's for when that cloud folder isn't synced to this computer already (no desktop client, or a mount you'd
rather not keep running).

    every 2 hours     rclone copy <your remote> <Handwritten notes' folder>: only the kinds Handwritten notes reads,
                      only the folder's top level; never `sync`, so nothing on this computer is ever deleted. New
                      files start a scan at once.
    metered networks  skipped while the connection is metered (a phone's hotspot), on Linux with NetworkManager
    /hwpull           when it last pulled and what; /hwpull now pulls now

rclone reaches your cloud itself, with the sign-in you gave it (`rclone config`): Kurooto never sees that sign-in and
can't see what rclone sends. It only starts rclone and nmcli, as its card says.
"""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path

from kurooto.core import proc
from kurooto.core.config import register_defaults
from kurooto.core.state import jload, jsave
from kurooto.modules.base import Command, Incoming, Module

register_defaults(
    "hw_pull",
    {
        "remote": "",  # the rclone remote and folder your notes app saves to, e.g. "gdrive:Handwritten"
        "every": "every 2h",  # how often to look
        "unmetered_only": True,  # skip while the connection is metered (Linux with NetworkManager)
        "timeout_min": 30,  # a pull that takes longer is stopped
    },
)

KINDS = ("pdf", "png", "jpg", "jpeg", "webp", "heic")  # what Handwritten notes reads
REMOTE = re.compile(r"^[\w .-]+:[^\n\0]*$")


class HandwritingPull(Module):
    id = "hw_pull"
    title = "Handwriting from the cloud"
    description = "Copies new handwritten pages from a cloud folder (with rclone) into Handwritten notes' folder."
    privacy = "rclone fetches your pages from your cloud with its own sign-in; nothing is uploaded or deleted."
    requires = ("handwritten",)
    processes = ("rclone",)
    processes_intermittent = True

    def __init__(self, app):
        super().__init__(app)
        self.state_file = Path(app.paths.state) / "hw-pull.json"
        self._busy = threading.Lock()

    def rclone(self) -> str | None:
        return proc.which("rclone")

    def target(self) -> Path | None:
        hw = self.app.modules.get("handwritten")
        return hw.folder() if hw is not None else None

    def ready(self):
        if not self.rclone():
            return False, "rclone isn't installed (rclone.org), and its remote set up with `rclone config`"
        remote = str(self.setting("remote") or "").strip()
        if not remote:
            return False, 'name the rclone remote and folder, e.g. "gdrive:Handwritten" (Set up)'
        if not REMOTE.match(remote) or remote.startswith("-"):
            return False, f"{remote!r} isn't an rclone remote and folder (name:path)"
        return True, ""

    def setup_form(self) -> dict:
        return {
            "intro": "Set up the cloud in rclone first (`rclone config`, a terminal step), then name the remote and "
            'the folder your notes app saves to, e.g. "gdrive:Handwritten". Kurooto never sees rclone\'s sign-in.',
            "links": [["rclone's setup guide", "https://rclone.org/docs/"]],
            "fields": [
                {"name": "remote", "label": "rclone remote:folder", "type": "text", "placeholder": "gdrive:Notes"}
            ],
        }

    def configure(self, values: dict) -> dict:
        remote = str(values.get("remote") or "").strip()
        if not REMOTE.match(remote) or remote.startswith("-"):
            return {"ok": False, "message": 'Give it as remote:folder, e.g. "gdrive:Handwritten".'}
        self.app.settings.set("hw_pull.remote", remote)
        return {"ok": True, "message": f"Pulling from {remote}."}

    def start(self):
        self.every("pull", self.setting("every") or "every 2h", lambda p: self.pull("scheduled"))

    # ------------------------------------------------------------------------------------------------ work
    def metered(self) -> bool:
        """Is the connection metered? (NetworkManager's word for it; False when nobody can say.)"""
        exe = proc.which("nmcli")
        if not exe:
            return False
        r = proc.run([exe, "-t", "-f", "GENERAL.METERED", "general"], timeout=10)
        if not r.ok:
            r = proc.run([exe, "-t", "-g", "GENERAL.METERED", "device", "show"], timeout=10)
        return bool(re.search(r"\byes\b", (r.out or "").lower()))

    def _rec(self) -> dict:
        return jload(self.state_file, {}) or {}

    def _save(self, **kw) -> dict:
        rec = {**self._rec(), **kw}
        jsave(self.state_file, rec)
        return rec

    def pull(self, why: str = "asked") -> tuple[bool, str]:
        ok, need = self.ready()
        if not ok:
            return False, need
        if why != "asked" and self.setting("unmetered_only") and self.metered():
            self._save(skipped=time.time())
            return False, "skipped: the connection is metered"
        dest = self.target()
        if dest is None:
            return False, "Handwritten notes isn't there"
        dest.mkdir(parents=True, exist_ok=True)
        before = {f.name for f in dest.iterdir() if f.is_file()}
        args = [self.rclone() or "rclone", "copy", str(self.setting("remote")), str(dest), "--max-depth", "1"]
        for k in KINDS:
            args += ["--include", f"*.{k}", "--include", f"*.{k.upper()}"]
        r = proc.run(args, timeout=float(self.setting("timeout_min") or 30) * 60)
        if not r.ok:
            err = ((r.err or r.out or "rclone failed").strip().splitlines() or ["rclone failed"])[-1][:200]
            rec = self._save(last_try=time.time(), last_error=err)
            self.app.events.emit("hw_pull", ok=False, error=err)
            if why != "asked" and time.time() - float(rec.get("told") or 0) > 20 * 3600:
                self.app.notify(f"Couldn't copy handwritten pages from the cloud: {err}", why="hw_pull.failed")
                self._save(told=time.time())
            return False, f"rclone didn't work: {err}"
        new = sorted({f.name for f in dest.iterdir() if f.is_file()} - before)
        self._save(last_ok=time.time(), last_try=time.time(), last_error="", last_new=new[:20], n_new=len(new))
        self.app.events.emit("hw_pull", ok=True, new=len(new))
        if new:
            hw = self.app.modules.get("handwritten")
            if hw is not None and self.app.is_on("handwritten"):
                hw.spawn()  # read them now, not at the next 15-minute look
        return True, f"{len(new)} new page file{'s' if len(new) != 1 else ''}" + (
            f": {', '.join(new[:5])}" if new else ""
        )

    # ------------------------------------------------------------------------------------------- telling
    def health_check(self):
        from kurooto.core.health import Check

        def probe(net: bool):
            ok, why = self.ready()
            if not ok:
                return False, why
            rec = self._rec()
            if rec.get("last_error") and float(rec.get("last_try") or 0) > float(rec.get("last_ok") or 0):
                return False, f"the last pull failed: {rec['last_error']}"
            return True, "pulling" if rec.get("last_ok") else "not pulled yet"

        return Check("hw_pull", "Handwriting from the cloud", module=self.id, probe=probe, help="/hwpull now tries")

    def status_lines(self) -> list[str]:
        rec = self._rec()
        if not rec.get("last_ok"):
            return ["Handwriting pull: not pulled yet"]
        return [f"Handwriting pull: {time.strftime('%d %b %H:%M', time.localtime(rec['last_ok']))}"]

    def commands(self):
        return [Command("hwpull", "handwriting from the cloud: when it last pulled; /hwpull now pulls now", self._cmd)]

    def _cmd(self, msg: Incoming, arg: str) -> str:
        if arg.strip().lower() == "now":
            if not self._busy.acquire(blocking=False):
                return "A pull is going already."
            try:
                return self.pull("asked")[1].capitalize() + "."
            finally:
                self._busy.release()
        rec = self._rec()
        lines = [f"From {self.setting('remote') or '(not set)'} into {self.target()} ({self.setting('every')})."]
        if rec.get("last_ok"):
            lines.append(f"Last pulled {time.strftime('%d %b %H:%M', time.localtime(rec['last_ok']))}: "
                         f"{rec.get('n_new', 0)} new.")  # fmt: skip
        if rec.get("last_error") and float(rec.get("last_try") or 0) > float(rec.get("last_ok") or 0):
            lines.append(f"Last try failed: {rec['last_error']}")
        return "\n".join(lines)

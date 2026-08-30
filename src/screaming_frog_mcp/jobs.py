"""Background job tracking for crawls.

A crawl takes minutes; an MCP tool call is expected to answer in seconds. So a
crawl is forked as a detached child and tracked here.

THE TRAP THIS MODULE EXISTS TO AVOID
------------------------------------
Liveness cannot be checked with os.kill(pid, 0). A finished child whose parent
never wait()s becomes a zombie, and os.kill reports a zombie as alive, so a
crawl that finished in 55 seconds still polls "running" forever. The Popen
handle is kept and poll() is used instead, which also reaps. Only when the
handle is gone (the server restarted since launch) does it fall back to
inspecting the process state, where a Z state means finished.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_PROCS: dict[str, subprocess.Popen] = {}


class Jobs:
    def __init__(self, root: Path):
        self.dir = root / ".jobs"

    # ── persistence ──────────────────────────────────────────────────────────

    def _path(self, job_id: str) -> Path:
        return self.dir / f"{job_id}.json"

    def read(self, job_id: str) -> dict:
        p = self._path(job_id)
        if not p.exists():
            raise ValueError(f"No such job: {job_id}")
        return json.loads(p.read_text(encoding="utf-8"))

    def write(self, job: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self._path(job["job_id"]).write_text(json.dumps(job, indent=2), encoding="utf-8")

    def latest(self) -> str | None:
        self.dir.mkdir(parents=True, exist_ok=True)
        files = sorted(self.dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
        return files[-1].stem if files else None

    # ── lifecycle ────────────────────────────────────────────────────────────

    def launch(self, args: list[str], out_dir: Path, folder: str, meta: dict) -> dict:
        """Fork a detached child running `python -m screaming_frog_mcp.runner`."""
        cmd = [sys.executable, "-u", "-m", "screaming_frog_mcp.runner"] + args
        out_dir.mkdir(parents=True, exist_ok=True)
        with open(out_dir / "runner.log", "w", encoding="utf-8") as log:
            proc = subprocess.Popen(
                cmd, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True,
                env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
            )
        job_id = f"{folder}-{proc.pid}"
        _PROCS[job_id] = proc
        job = {
            "job_id": job_id,
            "pid": proc.pid,
            "output_dir": str(out_dir),
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "state": "running",
            **meta,
        }
        self.write(job)
        return job

    def handle(self, job_id: str) -> subprocess.Popen | None:
        return _PROCS.get(job_id)

    def running(self, job: dict) -> bool:
        proc = _PROCS.get(job["job_id"])
        if proc is not None:
            return proc.poll() is None            # poll() also reaps

        pid = job["pid"]                          # server restarted since launch
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        if sys.platform == "win32":
            return True
        try:
            state = subprocess.run(["ps", "-o", "state=", "-p", str(pid)],
                                   capture_output=True, text=True, timeout=10).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return True
        return bool(state) and not state.startswith("Z")

    def cancel(self, job: dict) -> None:
        pid = job["pid"]
        try:
            if sys.platform == "win32":
                os.kill(pid, signal.SIGTERM)
            else:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
        except OSError:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        job["state"] = "cancelled"
        self.write(job)

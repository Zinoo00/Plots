#!/usr/bin/env python3
"""Play a short, scripted stretch of work into the demo workspace, one CLI write every few seconds, the way a Claude
Code session would. Keep the app open while it runs: every change shows up live. Made for screen recordings.

    python3 demo/play.py              (a step every 3 s; --gap 5 for slower, --reset to re-seed first)
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

DEMO = Path(__file__).resolve().parent
HOME = Path(os.environ.get("PLOTS_HOME") or (DEMO / ".home")).resolve()
if HOME == (Path.home() / ".plots").resolve():
    raise SystemExit("err play.py only writes to demo data (PLOTS_HOME is your real ~/.plots)")
ENGINE = DEMO.parent / "plots.py"

STEPS = [
    ("Two-factor setup is done", ["set", "0140", "done", "-m", "TOTP verify works; review round 2 passed."]),
    ("its commit is recorded", ["commit", "BE", "4f1c2a9d0", "TOTP setup and verify"]),
    ("the Pilot batch is finished", ["log", "Pilot batch done: all four Account screens."]),
    ("Tags and filters starts", ["set", "0230", "fix", "-m", "Tag chips and the filter bar."]),
    ("Claude asks you something", ["decision", "add", "Allow emoji in tag names?", "-s", "ask",
                                   "-d", "Yes, one per tag, at the start.", "--screens", "0230"]),
    ("the editor passes review", ["set", "0220", "done", "-m", "Autosave and the toolbar are in; round 2 passed."]),
    ("Appearance starts", ["set", "0420", "fix", "-m", "Light, dark and automatic themes."]),
]


def main():
    args = sys.argv[1:]
    gap = float(args[args.index("--gap") + 1]) if "--gap" in args else 3.0
    env = dict(os.environ, PLOTS_HOME=str(HOME))
    env.pop("PLOTS_WS", None)
    if "--reset" in args or not HOME.exists():
        subprocess.run([sys.executable, "-I", str(DEMO / "seed.py")], env=env, check=True, stdout=subprocess.DEVNULL)
        time.sleep(gap)
    for i, (what, cmd) in enumerate(STEPS):
        if i:
            time.sleep(gap)
        r = subprocess.run([sys.executable, "-I", str(ENGINE), "--ws", "juniper"] + cmd, env=env,
                           capture_output=True, text=True)
        print("%d/%d %s: %s" % (i + 1, len(STEPS), what, (r.stdout or r.stderr).strip()), flush=True)


if __name__ == "__main__":
    main()

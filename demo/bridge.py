#!/usr/bin/env python3
"""A stand-in for "your Claude project" in the demo: it answers the app's Chat with short, made-up replies built from
the demo data, so Chat can be recorded without starting a Claude Code session. It keeps the bridge heartbeat that
`plots bridge watch` keeps, claims each message, shows the thread working for a moment, then replies.

    PLOTS_HOME=demo/.home python3 demo/bridge.py        (demo/run.sh starts it for you)
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

DEMO = Path(__file__).resolve().parent
os.environ.setdefault("PLOTS_HOME", str(DEMO / ".home"))
if Path(os.environ["PLOTS_HOME"]).resolve() == (Path.home() / ".plots").resolve():
    raise SystemExit("err the demo bridge only runs on demo data (PLOTS_HOME is your real ~/.plots)")
sys.path.insert(0, str(DEMO.parent))
import plots as E  # noqa: E402

THINK = float(os.environ.get("PLOTS_DEMO_THINK") or 4)     # seconds a thread "works" before it answers


def answer(w: dict, text: str) -> str:
    with E.ws_context(w):
        d = E.load()
    st = E.stats(d)
    by = {s["id"]: s for s in d["screens"]}
    t = text.lower()
    blocked = [s for s in d["screens"] if s["status"] == "Blocked"]
    flight = [s for s in d["screens"] if s["status"] == "Fixing"]
    nxt = sorted((s for s in d["screens"] if s["status"] == "Up next"), key=lambda s: s["order"])
    waiting = [x for x in d["decisions"] if x["status"] in ("Waiting on you", "Please confirm")]
    named = [by[k] for k in by if k in t or k.replace(w.get("idPrefix") or "", "", 1) in t.split()]
    if named:
        s = named[0]
        return "%s (%s) is %s. %s" % (s["name"], s["id"], s["status"].lower(), s["note"] or "Nothing noted yet.")
    if "block" in t:
        if not blocked:
            return "Nothing is blocked right now."
        return " ".join("%s is blocked: %s" % (s["name"], s["note"]) for s in blocked)
    if "next" in t or "left" in t or "plan" in t:
        return ("In flight: %s. Up next: %s." % (", ".join(s["name"] for s in flight) or "nothing",
                                                ", ".join(s["name"] for s in nxt) or "nothing queued"))
    if "decision" in t or "waiting" in t:
        if not waiting:
            return "No decisions are waiting on you."
        return "Waiting on you: " + "; ".join("#%d %s" % (x["n"], x["topic"]) for x in waiting) + "."
    return ("%d of %d done (%.0f%%). %d in flight, %d not started, %d decision%s waiting on you."
            % (st["done"], st["total"], st["pct"], st["working"], st["not_started"], len(waiting),
               "" if len(waiting) == 1 else "s"))


def main():
    print("demo bridge: answering Chat for workspaces with notes=project in %s" % E.HOME, flush=True)
    started = {}
    while True:
        E._write_json(E.BRIDGE_FILE, {"pid": os.getpid(), "t": time.time()})
        for w in E.reg_load()["workspaces"]:
            for x in E.project_pending(w):
                key = (w["id"], x["id"])
                if not x["claimed"]:
                    E.project_claim(w, x["id"], x.get("to") or "Demo thread", where="mac")
                    E.project_thread(w, x["id"], state="working", progress="Reading the workspace")
                    started[key] = time.time()
                elif key not in started:
                    started[key] = time.time()
                elif time.time() - started[key] >= THINK:
                    E.project_reply(w, x["id"], answer(w, x["text"]))
                    started.pop(key, None)
                    print("answered %s #%d" % key, flush=True)
        time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass

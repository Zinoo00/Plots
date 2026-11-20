#!/usr/bin/env python3
"""Seed the Plots demo: a made-up project ("Juniper", a notes app getting a new web client) with items in every
status, decisions, a log, shared commits, two small git repos with lane worktrees (for the Code card) and a few
answered Chat conversations. Everything lives in demo/.home (PLOTS_HOME) and demo/.work, so your own Plots data
is never read or written. Safe to run again: it starts from scratch each time.

    python3 demo/seed.py
"""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

DEMO = Path(__file__).resolve().parent
ROOT = DEMO.parent
HOME = Path(os.environ.get("PLOTS_DEMO_HOME") or (DEMO / ".home")).resolve()
WORK = (DEMO / ".work").resolve()
PROJECT = WORK / "juniper"
DOCS = WORK / "juniper-docs"
ENGINE = ROOT / "plots.py"

if HOME in (Path.home(), Path.home() / ".plots") or HOME == ROOT:
    raise SystemExit("err refusing to seed into %s (it is wiped first)" % HOME)

ENV = dict(os.environ, PLOTS_HOME=str(HOME))
ENV.pop("PLOTS_WS", None)
ENV.pop("PLOTS_NOTE", None)


def plots(*args, cwd=None):
    r = subprocess.run([sys.executable, "-I", str(ENGINE)] + [str(a) for a in args], cwd=cwd or PROJECT, env=ENV,
                       capture_output=True, text=True)
    if r.returncode:
        raise SystemExit("err plots %s: %s" % (" ".join(map(str, args)), (r.stderr or r.stdout).strip()))
    return r.stdout.strip()


# --------------------------------------------------------------------------- git: two repos and lane worktrees

BASE = dt.datetime.now().replace(second=0, microsecond=0) - dt.timedelta(days=13)


def git(repo, *args, when=None):
    env = dict(ENV, GIT_AUTHOR_NAME="Demo", GIT_AUTHOR_EMAIL="demo@example.com",
               GIT_COMMITTER_NAME="Demo", GIT_COMMITTER_EMAIL="demo@example.com", GIT_CONFIG_GLOBAL="/dev/null",
               GIT_CONFIG_NOSYSTEM="1")
    if when:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = when.strftime("%Y-%m-%dT%H:%M:%S")
    r = subprocess.run(["git", "-C", str(repo), "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false"]
                       + list(args), env=env, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit("err git %s: %s" % (" ".join(args), r.stderr.strip()))
    return r.stdout.strip()


def commit(repo, path, text, msg, day, hour=10):
    f = Path(repo) / path
    f.parent.mkdir(parents=True, exist_ok=True)
    with f.open("a") as fh:
        fh.write(text + "\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg, when=BASE + dt.timedelta(days=day, hours=hour))
    return git(repo, "rev-parse", "--short=9", "HEAD")


def make_repos():
    shared = {}
    for side, files in (("be", ("api/auth.py", "api/notes.py", "api/share.py")),
                        ("fe", ("src/pages/SignIn.tsx", "src/pages/Editor.tsx", "src/pages/Share.tsx"))):
        repo = PROJECT / side
        repo.mkdir(parents=True)
        git(repo, "init", "-q", "-b", "main")
        commit(repo, "README.md", "# juniper-%s" % side, "Start the v2 %s" % ("API" if side == "be" else "web client"), 0, 9)
        shared[side] = [
            commit(repo, files[0], "# sign in", "Sign-in and sign-up on the new session API", 2),
            commit(repo, files[1], "# notes", "Notes list: paging and empty state", 5),
            commit(repo, files[2], "# share", "Share dialog: invite by email", 8),
            commit(repo, files[0], "# reset", "Password reset with one-time links", 10),
        ]
        lanes = (("two-factor", "feature/jn0140-two-factor", files[0], "TOTP setup and verify", 11),
                 ("editor", "feature/jn0220-editor", files[1], "Editor toolbar and autosave", 12),
                 ("public-links", "feature/jn0320-public-links", files[2], "Public links with expiry", 12))
        for lane, branch, path, msg, day in lanes:
            wt = WORK / "lanes" / lane / side
            wt.parent.mkdir(parents=True, exist_ok=True)
            git(repo, "worktree", "add", "-q", "-b", branch, str(wt), "main")
            commit(wt, path, "# " + msg, msg, day, 14)
        commit(repo, "CHANGELOG.md", "- v2 progress", "Changelog for the pilot batch", 12, 16)   # main moves on
    return shared


# --------------------------------------------------------------------------- the workspace

ITEMS = [  # id, name, group, batch
    ("0110", "Sign in", "Account", "Pilot"), ("0120", "Sign up", "Account", "Pilot"),
    ("0130", "Password reset", "Account", "Pilot"), ("0140", "Two-factor setup", "Account", "Pilot"),
    ("0210", "Notes list", "Notes", "Core"), ("0220", "Note editor", "Notes", "Core"),
    ("0230", "Tags and filters", "Notes", "Core"), ("0240", "Trash", "Notes", "Core"),
    ("0250", "Search", "Notes", "Core"), ("0260", "Attachments", "Notes", "Core"),
    ("0310", "Share dialog", "Sharing", "Core"), ("0320", "Public links", "Sharing", "Core"),
    ("0330", "Collaborators", "Sharing", "Core"), ("0410", "Profile", "Settings", "Polish"),
    ("0420", "Appearance", "Settings", "Polish"), ("0430", "Notifications", "Settings", "Polish"),
    ("0440", "Export data", "Settings", "Polish"), ("0450", "Billing", "Settings", "Polish"),
]

# the story, oldest first: (ids, status, note)
STORY = [
    ("0110", "fix", "Porting the form to the new session API."),
    ("0120", "fix", "Sign-up shares the sign-in form; adding the terms checkbox."),
    ("0110", "done", "Signs in against the v2 API; remember-me works; review passed."),
    ("0210", "fix", "Paging with a cursor instead of offsets."),
    ("0120", "done", "Email verification link lands on the new welcome page."),
    ("0130", "fix", "One-time links expire after 30 minutes."),
    ("0210", "done", "Paging, empty state and keyboard navigation in."),
    ("0310", "fix", "Invite by email; roles are view and edit."),
    ("0120", "testing", "Testing on Safari and Firefox."),
    ("0130", "done", "Reset flow done; rate-limited to 5 an hour."),
    ("0310", "done", "Invites send; pending invites show in the list."),
    ("0410", "fix", "Avatar upload moved to the new storage service."),
    ("0120", "tested", "Tested on Safari, Firefox and Chrome."),
    ("0130", "testing", "Testing the expired-link path."),
    ("0410", "done", "Profile saves inline; avatar crops to a square."),
    ("0250", "fix", "Search runs on the server now; highlighting the matches."),
    ("0130", "tested", "Expired and reused links both show the right message."),
    ("0130", "merged", "Merged into main with the sign-in work."),
    ("0250", "done", "Server-side search with highlighted matches."),
    ("0440", "oos", "Export stays on the old client for this release (decision #4)."),
    ("0250", "testing", "Testing search with 10k notes."),
    ("0260", "fix", "Drag and drop upload works; size limits still open."),
    ("0260", "blocked", "Waiting on decision #3: the attachment size limit on the free plan."),
    ("0230,0420", "next", ""),
    ("0140", "fix", "QR code renders; wiring the TOTP verify call next."),
    ("0220", "fix", "Toolbar done, autosave every 2 seconds; fixing review round 2 notes."),
    ("0320", "fix", "Links get an expiry date; the copy button is next."),
]

DETAILS = {
    "0110": ["review=round 1 passed", "p1=0", "p2=0", "p3=1"],
    "0140": ["be=feature/jn0140-two-factor", "fe=feature/jn0140-two-factor", "p1=1", "p2=2", "p3=0", "review=round 1"],
    "0220": ["be=feature/jn0220-editor", "fe=feature/jn0220-editor", "p1=2", "p2=3", "p3=4", "review=round 2",
             "checks=#2,#5"],
    "0250": ["p1=0", "p2=1", "p3=2", "review=round 1 passed"],
    "0260": ["p1=1", "p2=0", "p3=1", "checks=#3"],
    "0320": ["be=feature/jn0320-public-links", "fe=feature/jn0320-public-links", "p1=0", "p2=1", "p3=0"],
}

DECISIONS = [  # topic, flags, then later changes
    ("Keep the old /n/<id> note URLs, or move to /notes/<id>?",
     ["-s", "ask", "-d", "Move to /notes/<id> and redirect the old path with a 301.", "--screens", "0210,0220"],
     ["confirmed", "-d", "Move to /notes/<id>; the old path redirects with a 301."]),
    ("Markdown flavour in the editor: CommonMark or GitHub-flavoured?",
     ["-s", "ask", "-d", "GitHub-flavoured: tables and task lists are the most requested.", "--screens", "0220"],
     ["decided", "-d", "GitHub-flavoured Markdown, with tables and task lists."]),
    ("Attachment size limit on the free plan",
     ["-s", "wait", "--screens", "0260"], None),
    ("Keep Export data on the old client for this release?",
     ["-s", "ask", "-d", "Yes: it moves with the Settings batch in the next release.", "--screens", "0440"],
     ["decided", "-d", "Export stays on the old client until the next release."]),
    ("Sign shared devices out after 30 minutes idle?",
     ["-s", "ask", "-d", "30 minutes idle on devices marked shared; 30 days otherwise.", "--screens", "0110,0140"], None),
]

LOG = [
    "Pilot batch started: Account screens first.",
    "Sign in done: the first screen on the v2 API.",
    "Core batch started.",
    "Pilot batch: 3 of 4 done; two-factor is in flight.",
    "Search moved to the server; 10k-note test passed locally.",
    "Attachments blocked on the size limit (decision #3).",
]

CHATS = [  # (question, context, title, thread, answer), answered by the demo's Claude project
    ("What's left before the Pilot batch is done?", ["jn0140"], "Pilot batch status", "Account thread",
     "Three of the four Pilot screens are done, and Password reset is already merged. Only Two-factor setup is "
     "left: the QR code renders, and the TOTP verify call is next. It has one P1 finding open (the code input "
     "accepts letters). I expect it done tomorrow."),
    ("Why is Attachments blocked?", ["jn0260"], "Attachments", "Notes thread",
     "Upload works, but it waits on decision #3, the size limit on the free plan. Once you pick a number, the "
     "remaining work is about an hour: the limit check, the error message and a test."),
]


def _work_slots(start: dt.datetime, end: dt.datetime) -> list:
    """(from, to) working-hour windows (09:00-18:00) between start and end."""
    out, day = [], start.replace(hour=0, minute=0)
    while day <= end:
        a, b = max(day.replace(hour=9), start), min(day.replace(hour=18), end)
        if a < b and day.weekday() < 5:
            out.append((a, b))
        day += dt.timedelta(days=1)
    return out


def _spread(n: int, start: dt.datetime, end: dt.datetime) -> list:
    """n increasing times inside working hours between start and end."""
    slots = _work_slots(start, end)
    total = sum((b - a).total_seconds() for a, b in slots)
    out = []
    for i in range(n):
        off = total * (i + 1) / (n + 1)
        for a, b in slots:
            w = (b - a).total_seconds()
            if off <= w:
                out.append(a + dt.timedelta(seconds=off))
                break
            off -= w
    return [t.strftime("%Y-%m-%d %H:%M") for t in out]


def spread_times(data_path: Path):
    """Spread the story's timestamps over the last two weeks (the CLI stamps everything 'now')."""
    d = json.loads(data_path.read_text(encoding="utf-8"))
    end = dt.datetime.now() - dt.timedelta(minutes=20)
    evs = d.get("events", [])
    for e, t in zip(evs, _spread(len(evs), BASE, end)):
        e["t"] = t
    last = {e["id"]: e["t"] for e in evs}
    for s in d["screens"]:
        s["updated"] = last.get(s["id"], BASE.strftime("%Y-%m-%d 09:00"))
    log = d.get("log", [])
    for x, t in zip(log, _spread(len(log), BASE + dt.timedelta(hours=2), end - dt.timedelta(minutes=30))):
        x["t"] = t
    for i, c in enumerate(d.get("commits", [])):
        c["date"] = (BASE.replace(hour=10, minute=0) + dt.timedelta(days=[2, 5, 8, 10][i // 2 % 4])).strftime("%Y-%m-%d %H:%M")
    d["updated"] = (end + dt.timedelta(minutes=16)).strftime("%Y-%m-%d %H:%M")
    data_path.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def seed_chat(home: Path, wid: str):
    """Answered conversations, written the way the Claude project bridge writes them."""
    os.environ["PLOTS_HOME"] = str(home)
    sys.path.insert(0, str(ROOT))
    import plots as E  # noqa: E402  (reads PLOTS_HOME at import)
    w = E.ws_find(E.reg_load(), wid)
    for q, ctx, title, thread, answer in CHATS:
        n = E.note_add(w, q, delay=0, context=ctx)
        E.notes_update(w, E.project_handoff)
        E.project_claim(w, n["id"], thread, where="mac")
        E.note_change(w, n["id"], "title", title)
        E.project_reply(w, n["id"], answer)
        E.note_change(w, n["id"], "seen")


def stop_running_demo():
    """A demo server or bridge left running would lose its pid file when the home is wiped: stop them first."""
    pid = HOME / "run" / "demo-bridge.pid"
    try:
        os.kill(int(pid.read_text().strip()), 15)
    except (OSError, ValueError):
        pass
    if (HOME / "workspaces.json").exists():
        subprocess.run([sys.executable, "-I", str(ENGINE), "stop"], env=ENV, capture_output=True)


def main():
    stop_running_demo()
    for p in (HOME, WORK):
        if p.exists():
            shutil.rmtree(p)
    HOME.mkdir(parents=True)
    PROJECT.mkdir(parents=True)
    DOCS.mkdir(parents=True)
    shared = make_repos()

    plots("ws", "user", "Alex")
    plots("init", "Juniper web v2", "--prefix", "jn", "--id", "juniper")
    plots("ws", "set", "juniper", "color=green", "notes=project")
    for sid, name, group, batch in ITEMS:
        plots("add", sid, name, "--menu", group, "--batch", batch)
    for i, (ids, st, note) in enumerate(STORY):
        args = ["set", ids, st] + (["-m", note] if note else [])
        plots(*args)
        if i == 6:
            for topic, flags, _ in DECISIONS[:2]:
                plots("decision", "add", topic, *flags)
        if i == 15:
            for topic, flags, _ in DECISIONS[2:]:
                plots("decision", "add", topic, *flags)
    for n, (_, _, later) in enumerate(DECISIONS, 1):
        if later:
            plots("decision", n, *later)
    for sid, kv in DETAILS.items():
        plots("detail", sid, *kv)
    for line in LOG:
        plots("log", line)
    msgs = ["Sign-in and sign-up on the new session API", "Notes list: paging and empty state",
            "Share dialog: invite by email", "Password reset with one-time links"]
    for i, msg in enumerate(msgs):
        plots("commit", "BE", shared["be"][i], msg)
        plots("commit", "FE", shared["fe"][i], msg)

    # a second, smaller workspace, so the switcher has something to switch to
    plots("init", "Juniper docs site", "--prefix", "dc", "--id", "docs", cwd=DOCS)
    for sid, name in (("01", "Getting started"), ("02", "Editor guide"), ("03", "Sharing guide"), ("04", "API reference")):
        plots("--ws", "docs", "add", sid, name, "--menu", "Guides", "--batch", "Docs")
    plots("--ws", "docs", "set", "01", "done", "-m", "Rewritten for v2.")
    plots("--ws", "docs", "set", "02", "fix", "-m", "Screenshots of the new editor.")
    plots("ws", "use", "juniper")

    reg = json.loads((HOME / "workspaces.json").read_text(encoding="utf-8"))
    wmap = {w["id"]: w for w in reg["workspaces"]}
    spread_times(Path(wmap["juniper"]["data"]))
    seed_chat(HOME, "juniper")
    print("ok demo seeded: PLOTS_HOME=%s" % HOME)
    print(plots("status"))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Plots hooks for Claude Code (stdlib only, fast: this runs after every tool call).

session-start  In a folder a Plots workspace tracks: one short line of context (progress, what's waiting,
               how to update it) and PLOTS_WS / PLOTS_SESSION for later shell commands.
tool / prompt  The first session that runs a workspace's command (`plots …`)
               becomes that workspace's working session; another one takes over only by reading the inbox
               (`<cli> inbox`, not --peek), so a side job that logs a line doesn't take the user's notes.
               Whatever the user sends from the Plots app for it (notes, answers, status changes, instructions
               relayed by a note's fork) is handed to the working session at its own next tool call or prompt
               (not a subagent's), and marked read, so it lands even mid-task.
Forks that answer notes (PLOTS_NOTE is set, or the session started as a fork) stay quiet.
"""
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None

HOME = Path(os.environ.get("PLOTS_HOME") or (Path.home() / ".plots"))
SESS = HOME / "sessions"


def load(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save(p, obj):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".tmp-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def roots(w):
    out = [w.get("root")] + list(w.get("sessionRoots") or [])
    return [str(Path(r).expanduser()) for r in out if r]


def ws_for_path(reg, path):
    try:
        p = str(Path(path).resolve())
    except OSError:
        return None
    best, depth = None, -1
    for w in reg.get("workspaces", []):
        for r in roots(w):
            if (p == r or p.startswith(r.rstrip("/") + "/")) and len(r) > depth:
                best, depth = w, len(r)
    return best


def ws_by_command(reg, cmd, cwd):
    """The workspace a shell command updates: a workspace's own command or marker, or `plots` (by --ws, the
    session's $PLOTS_WS or the folder)."""
    hit = lambda word: re.search(r"(^|[\s;&|(/])" + re.escape(word) + r"(\s|$)", cmd)
    for w in reg.get("workspaces", []):
        words = {m.strip() for m in (w.get("markers") or []) if m.strip()}
        if w.get("cli") and w.get("cli") != "plots":
            words.add(w["cli"])
        if any(hit(x) for x in words):
            return w
    if hit("plots"):
        m = re.search(r"--ws[ =](\S+)", cmd)
        key = m.group(1) if m else os.environ.get("PLOTS_WS")
        if key:
            return next((x for x in reg.get("workspaces", []) if x.get("id") == key), None)
        return ws_for_path(reg, cwd)
    return None


def emit(event, context=None, title=None):
    out = {"hookEventName": event}
    if context:
        out["additionalContext"] = context
    if title:
        out["sessionTitle"] = title
    print(json.dumps({"hookSpecificOutput": out}, ensure_ascii=False))


def user_name(reg):
    return reg.get("user") or "the user"


def summary(w, data, reg):
    sc = data.get("screens", [])
    oos = sum(1 for s in sc if s.get("status") == "Out of scope")
    total = len(sc) - oos
    done = sum(1 for s in sc if s.get("status") in ("Done", "Testing", "Tested", "Merged"))
    working = sum(1 for s in sc if s.get("status") in ("Fixing", "In flight", "In progress", "In review",
                                                       "Fixing review notes", "Blocked"))
    waiting = sum(1 for d in data.get("decisions", []) if d.get("status") in ("Waiting on you", "Please confirm"))
    unread = sum(1 for i in data.get("inbox", []) if not i.get("read"))
    return done, total, working, waiting, unread


def claims_inbox(reg, w, cmd, cwd):
    """The command reads w's inbox (`<cli> inbox`, not --peek): how a session takes a workspace over."""
    names = {w.get("cli") or "plots", "plots"} | {m.strip() for m in (w.get("markers") or []) if m.strip()}
    reads = re.compile(r"(^|[\s(/])(%s)(\s+(--json|--(ws|workspace)[ =]\S+))*\s+inbox(\s|$)"
                       % "|".join(re.escape(x) for x in sorted(names)))
    for part in re.split(r"&&|\|\||[;|&\n]", cmd):
        if reads.search(part) and "--peek" not in part and (ws_by_command(reg, part, cwd) or {}).get("id") == w["id"]:
            return True
    return False


def register(w, inp, claim=False):
    """This session becomes w's working session when none is recorded, stays it when it already is (refreshed once
    a minute), and takes it from another session only with a claim (reading the inbox)."""
    sid = inp.get("session_id")
    if not sid:
        return
    cur = load(SESS / ("%s.json" % w["id"]), {}) or {}
    if cur.get("id") and cur.get("id") != sid and not claim:
        return
    if cur.get("id") != sid or time.time() - cur.get("t", 0) > 60:
        save(SESS / ("%s.json" % w["id"]),
             {"id": sid, "cwd": inp.get("cwd"), "transcript": inp.get("transcript_path"), "t": time.time()})


def deliver(w, sid, reg):
    """New items from the app for this workspace, marked read; None when there is nothing new."""
    cur = load(SESS / ("%s.json" % w["id"]), {}) or {}
    if cur.get("id") != sid:
        return None
    data_path = Path(w["data"]).expanduser()
    try:
        st = data_path.stat()
    except OSError:
        return None
    sig = "%d-%d" % (st.st_mtime_ns, st.st_size)
    state_p = SESS / "seen" / ("%s.json" % w["id"])
    state = load(state_p, {}) or {}
    if state.get("sig") == sig:
        return None
    items = []
    status_of = {}
    lock = open(str(data_path) + ".lock", "a+")
    try:
        if fcntl:
            fcntl.flock(lock, fcntl.LOCK_EX)
        data = load(data_path, {}) or {}
        status_of = {x.get("id"): x.get("status") for x in data.get("screens", [])}
        for i in data.get("inbox", []):
            if not i.get("read"):
                items.append(dict(i))
                i["read"] = True
        if items:
            save(data_path, data)
            st = data_path.stat()
            sig = "%d-%d" % (st.st_mtime_ns, st.st_size)
    finally:
        if fcntl:
            fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()
    save(state_p, {"sig": sig, "t": time.time()})
    if not items:
        return None
    who = user_name(reg)
    lines = []
    for i in items:
        t = (i.get("t") or "")[11:16]
        kind = i.get("kind", "note")
        if kind == "relay":
            what = "instruction relayed by the fork that answered %s's note%s" % (who, (" #%s" % i["note"]) if i.get("note") else "")
        elif kind == "decision":
            what = "answer to decision #%s" % i.get("ref")
        elif kind == "status":
            what = "%s moved %s in the app" % (who, i.get("ref"))
        elif i.get("ref"):
            st = i.get("st") or status_of.get(i.get("ref"))
            what = "note on %s%s" % (i.get("ref"), (
                " (it's %s: if this reports a bug, set it back to fix first)" % st if st in ("Testing", "Tested", "Merged")
                else (" (%s)" % st if st else "")))
        else:
            what = "note"
        lines.append("- [%s] %s: %s" % (t, what, i.get("text", "")))
    cli = w.get("cli") or "plots"
    return ("New from %s in the Plots app (%s workspace), sent while you were working. Treat these as %s's "
            "instructions and fold them into what you're doing now; they're marked read (`%s inbox` won't show them "
            "again):\n%s") % (who, w.get("name", w["id"]), who, cli, "\n".join(lines))


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        inp = json.load(sys.stdin)
    except ValueError:
        inp = {}
    reg = load(HOME / "workspaces.json", {}) or {}
    if not reg.get("workspaces"):
        return
    if os.environ.get("PLOTS_NOTE"):          # a fork answering a note: never the working session
        return
    sid = inp.get("session_id")
    cwd = inp.get("cwd") or os.getcwd()

    if mode == "session-start":
        if inp.get("source") == "fork":
            return
        w = ws_for_path(reg, cwd)
        env = os.environ.get("PLOTS_WS")
        if not w and env:
            w = next((x for x in reg["workspaces"] if x.get("id") == env), None)
        if not w:
            return
        ef = os.environ.get("CLAUDE_ENV_FILE")
        if ef:
            try:
                with open(ef, "a", encoding="utf-8") as f:
                    f.write("export PLOTS_WS=%s\n" % w["id"])
                    if sid:
                        f.write("export PLOTS_SESSION=%s\n" % sid)
            except OSError:
                pass
        data = load(Path(w["data"]).expanduser(), {}) or {}
        done, total, working, waiting, unread = summary(w, data, reg)
        cli = w.get("cli") or "plots"
        who = user_name(reg)
        ctx = ("This folder is tracked in Plots as the \"%s\" workspace: %d of %d done, %d in flight, %d decision%s "
               "waiting on %s. Keep it current with `%s` (use the plots skill): status changes, log lines, "
               "decisions, commits.%s Running `%s inbox` reads what's waiting, and it also makes this session the "
               "one Plots hands new items from %s to, after each tool call.") % (
            w.get("name", w["id"]), done, total, working, waiting, "" if waiting == 1 else "s", who, cli,
            (" %d unread in the inbox: run `%s inbox` first." % (unread, cli)) if unread else "", cli, who)
        emit("SessionStart", ctx)
        return

    if mode in ("tool", "prompt"):
        if mode == "tool" and inp.get("tool_name") == "Bash":
            cmd = (inp.get("tool_input") or {}).get("command") or ""
            # the Claude project's bridge reads every workspace's notes; it never becomes a working session
            w = ws_by_command(reg, cmd, cwd) if cmd and not re.search(r"\bplots\s+(--json\s+)?bridge\b", cmd) else None
            if w:
                register(w, inp, claims_inbox(reg, w, cmd, cwd))
        # a subagent's tool call arrives with the session's own session_id (and an agent_id): what's new from the
        # app is for the session itself, so it waits for the session's next tool call or prompt
        if inp.get("agent_id"):
            return
        texts = []
        for w in reg["workspaces"]:
            t = deliver(w, sid, reg)
            if t:
                texts.append(t)
        if texts:
            emit("PostToolUse" if mode == "tool" else "UserPromptSubmit", "\n\n".join(texts))


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 - a hook must never get in the way
        pass

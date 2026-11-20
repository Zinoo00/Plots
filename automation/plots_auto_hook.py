#!/usr/bin/env python3
"""Plots hooks for Claude Code: keep Plots current without anyone asking (stdlib only; never blocks a tool).

  post-tool  (PostToolUse / PostToolUseFailure)
      - a `git commit` (also --amend, cherry-pick, revert) in a lane worktree: the commit goes into the workspace's
        commits (an amend replaces the commit it amended; cherry-picks and merges only touch the tail), the page (from
        the lane's branch, feature/pag1010e-dev → pag1010e) gets an '[auto: …]' tail on its ▶ line, its be/fe branch
        if empty, and Not started / Up next → Fixing;
      - a test or type-check run in one lane (npm test, vitest, jest, gradle test, tsc): the
        parsed result goes into that page's '[auto: …]' tail;
      - edits and commits in a lane, and Plots writes (plots MCP tools, `plots` set|note|…), are
        remembered for the stop check.
  stop       (Stop / SubagentStop)
      An agent (or a session's turn) that edited or committed in a lane but wrote nothing to Plots after its last
      such step is asked once to update the page's ▶ line (and status) before it finishes.

Only sessions started after the automation was installed (~/.plots/auto/installed) are touched, so agents that
were already running carry on as before. PLOTS_AUTO=0 turns it off; forks answering Plots notes are skipped.
"""
from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import plots_lanes as L  # noqa: E402

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

RUNS = L.AUTO_DIR / "runs"
LOG = L.AUTO_DIR / "hook.log"
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
MCP_WRITES = {"set_page_status", "set_lane_line", "log_event", "record_commit", "add_decision", "update_decision"}


def log(msg: str) -> None:
    try:
        L.AUTO_DIR.mkdir(parents=True, exist_ok=True)
        if LOG.exists() and LOG.stat().st_size > 2_000_000:
            os.replace(LOG, LOG.with_suffix(".log.1"))
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%m-%d %H:%M:%S"), msg))
    except OSError:
        pass


# --------------------------------------------------------------------------- per-run state (one file per session/agent)

def run_key(inp: dict) -> str:
    sid = (inp.get("session_id") or "nosession").replace("/", "_")
    aid = (inp.get("agent_id") or "").replace("/", "_")
    return sid + ("." + aid if aid else "")


@contextlib.contextmanager
def run_state(key: str):
    """Load, let the caller change, save — under a per-run lock (one agent's parallel tool calls run hooks at once).
    Setting st['_drop'] removes the run."""
    RUNS.mkdir(parents=True, exist_ok=True)
    p = RUNS / (key + ".json")
    lk = open(str(p) + ".lock", "a+")
    try:
        if fcntl:
            fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            st = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            st = {}
        before = json.dumps(st, sort_keys=True)
        yield st
        if st.pop("_drop", False):
            for f in (p, Path(str(p) + ".lock")):
                with contextlib.suppress(OSError):
                    f.unlink()
        elif json.dumps(st, sort_keys=True) != before:
            fd, tmp = tempfile.mkstemp(dir=str(RUNS), prefix=".run-", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(st, f, ensure_ascii=False)
            os.replace(tmp, p)
    finally:
        if fcntl:
            with contextlib.suppress(OSError):
                fcntl.flock(lk, fcntl.LOCK_UN)
        lk.close()


def sweep_runs() -> None:
    """Runs of sessions that ended without a stop go after two days."""
    try:
        cutoff = time.time() - 2 * 86400
        for p in RUNS.glob("*.json*"):
            if p.stat().st_mtime < cutoff:
                p.unlink()
    except OSError:
        pass


def note_lane_work(key: str, lanes: list) -> None:
    pages = {}
    for info in lanes:
        for pid in L.pages_of_branch(L.branch_of(info["repo"])):
            pages[pid] = info["lane"]
    if not pages:
        return
    with run_state(key) as st:
        now = time.time()
        st.setdefault("first", now)
        st["last"] = now
        st.setdefault("pages", {}).update(pages)


def note_plots_write(key: str) -> None:
    with run_state(key) as st:
        st["wrote"] = time.time()


# --------------------------------------------------------------------------- post-tool

def _output(inp: dict):
    r = inp.get("tool_response")
    failed = inp.get("hook_event_name") == "PostToolUseFailure"
    interrupted = False
    if isinstance(r, dict):
        out = "\n".join(str(r.get(k) or "") for k in ("stdout", "stderr", "output"))
        interrupted = bool(r.get("interrupted") or r.get("is_interrupt") or r.get("backgroundTaskId"))
        if isinstance(r.get("exit_code"), int) and r["exit_code"] != 0:
            failed = True
    elif isinstance(r, str):
        out = r
    else:
        out = ""
    if inp.get("error"):
        out += "\n" + str(inp["error"])
        failed = True
    if inp.get("is_interrupt"):
        interrupted = True
    return out, failed, interrupted


def _has_commit(repo: str, h: str) -> bool:
    try:
        return subprocess.run(["git", "-C", repo, "cat-file", "-e", h + "^{commit}"],
                              capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _commit_repo(c: dict, lanes: list):
    """The lane worktree a commit was made in, proven by its hash: the command's lanes first, then the other side of
    those lanes (be and fe share a branch name), then any lane on that branch. None when it isn't a lane commit."""
    tried, order = set(), []

    def push(x):
        if x and x["repo"] not in tried:
            tried.add(x["repo"])
            order.append(x)

    for x in lanes:
        push(x)
    for x in lanes:
        other = "fe" if x["side"] == "be" else "be"
        repo = str(Path(x["root"]) / x["lane"] / other)
        if (Path(repo) / ".git").exists():
            push({"lane": x["lane"], "side": other, "repo": repo, "root": x["root"]})
    if c["branch"]:
        for x in L.all_lane_repos():
            if L.branch_of(x["repo"]) == c["branch"]:
                push(x)
    for x in order:
        if (not c["branch"] or L.branch_of(x["repo"]) == c["branch"]) and _has_commit(x["repo"], c["hash"]):
            return x
    return None


def post_tool(inp: dict) -> None:
    tool = inp.get("tool_name") or ""
    key = run_key(inp)
    if tool.startswith("mcp__plots__"):
        if tool.split("__")[-1] in MCP_WRITES:
            note_plots_write(key)
        return
    ti = inp.get("tool_input") or {}
    if tool in EDIT_TOOLS:
        info = L.lane_of_path(ti.get("file_path") or ti.get("notebook_path"))
        if info:
            note_lane_work(key, [info])
        return
    if tool != "Bash":
        return
    cmd = ti.get("command") or ""
    if L.writes_plots(cmd):
        note_plots_write(key)
    action = L.git_action(cmd)
    kind = None if (action or ti.get("run_in_background")) else L.test_kind(cmd)
    if not action and not kind:
        return
    out, failed, interrupted = _output(inp)
    if interrupted:
        return
    lanes = L.lanes_in_command(cmd, inp.get("cwd"))
    commits = L.commits_in(cmd, out) if action else []
    if not commits and not (kind and lanes):
        return
    import plots_writes as T              # the engine only when there is something to write
    done = []
    for c in commits:
        info = _commit_repo(c, lanes)
        if not info:
            continue                          # not a lane commit (another repo): Plots isn't about it
        pages = L.pages_of_branch(c["branch"] or L.branch_of(info["repo"]))
        try:
            w = T.resolve_ws(None, pages)
            for pid in (pages or [None]):
                rep = T.last_commit(pid, info["side"]) if (pid and c["action"] == "amend") else None
                done += T.record_activity(w, pid, commit=c, side=info["side"], branch=c["branch"], replaces=rep)
        except T.Refused as e:
            log("commit %s: %s" % (c["hash"], e))
        if c["action"] in ("commit", "amend", "revert"):
            note_lane_work(key, [info])
    if kind and lanes and not commits:
        pages = {pid for info in lanes for pid in L.pages_of_branch(L.branch_of(info["repo"]))}
        redirected = any(">" in " ".join(t) for t in L.segments(cmd) if L._test_of(t))
        res = L.test_result(kind, out, failed, redirected)
        one_lane = len({x["lane"] for x in lanes}) == 1
        if res and one_lane and len(pages) == 1:   # one lane and page, or nothing: never spread over several
            pid = pages.pop()
            try:
                done += T.record_activity(T.resolve_ws(None, [pid]), pid, test=res)
            except T.Refused as e:
                log("test %s: %s" % (pid, e))
    done = [d for d in done if d]
    if done:
        log("%s %s" % (key[:20], "; ".join(done)))


# --------------------------------------------------------------------------- stop

STOP_TEXT = (
    "Plots check before you finish: you changed code for these pages but haven't updated Plots since your "
    "last change there:\n%s\n"
    "Update them now with the plots MCP tools: set_lane_line(ids, line) with one plain sentence on where the page "
    "stands and what comes next, and set_page_status(ids, status, line) if the status changed (next when you stop "
    "with work left, done only after the re-review passes, blocked with the reason; never testing/tested/merged). "
    "Without the MCP tools: plots set <ids> <status> -m '<line>'. Your commits and test runs are already recorded. If the ▶ line above is already right, "
    "just finish.")


def stop(inp: dict) -> None:
    key = run_key(inp)
    with run_state(key) as st:
        if not st.get("pages") or inp.get("stop_hook_active") or st.get("asked") or st.get("wrote", 0) >= st.get("last", 0):
            st["_drop"] = True
            pages = None
        else:
            st["asked"] = True
            pages = dict(st["pages"])
    sweep_runs()
    if not pages:
        return
    import plots_writes as T
    lines = []
    try:
        w = T.resolve_ws(None, list(pages))
        by_id = {s["id"]: s for s in T.read(w).get("screens", [])}
        for pid, lane in pages.items():
            s = by_id.get(pid)
            if s:
                line, _ = L.split_note(s.get("note", ""))
                lines.append("- %s %s (lane %s, %s) ▶ %s" % (pid, s.get("name", ""), lane, s["status"], (line or "(none)")[:160]))
    except (Exception, SystemExit) as e:  # noqa: BLE001
        log("stop read: %r" % e)
    if not lines:
        with run_state(key) as st:
            st["_drop"] = True
        return
    print(json.dumps({"decision": "block", "reason": STOP_TEXT % "\n".join(lines)}, ensure_ascii=False))
    log("%s asked for a ▶ update: %s" % (key[:20], ", ".join(pages)))


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if os.environ.get("PLOTS_AUTO") == "0" or os.environ.get("PLOTS_NOTE"):
        return
    try:
        inp = json.load(sys.stdin)
    except ValueError:
        return
    if not isinstance(inp, dict) or not L.session_is_new(inp.get("transcript_path")):
        return
    if mode == "post-tool":
        post_tool(inp)
    elif mode == "stop":
        stop(inp)


if __name__ == "__main__":
    try:
        main()
    except BaseException as e:  # noqa: BLE001 - a hook must never get in the way (the engine raises SystemExit)
        log("error: %r" % e)
    sys.exit(0)

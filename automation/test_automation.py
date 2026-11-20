#!/usr/bin/env python3
"""Tests for the Plots MCP server and hooks. Everything runs on a copy: a temp PLOTS_HOME with a small seeded
workspace, and temp git lanes. Your real Plots data is never read or written.

    python3 -I test_automation.py            (from anywhere)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TMP = Path(tempfile.mkdtemp(prefix="plots-auto-test-"))
HOME = TMP / "home"
LANES = TMP / "lanes"
os.environ["PLOTS_HOME"] = str(HOME)
os.environ["PLOTS_LANE_ROOTS"] = str(LANES)
os.environ.pop("PLOTS_WS", None)
os.environ.pop("PLOTS_AUTO", None)
os.environ.pop("PLOTS_NOTE", None)

(HOME / "workspaces/demo").mkdir(parents=True)
DATA = HOME / "workspaces/demo/progress.json"


def _seed_screen(sid, name, order):
    return {"id": sid, "name": name, "menu": "Pages", "status": "Not started", "note": "", "updated": "2026-01-05 09:00",
            "order": order, "covers": [], "myNotes": "", "batch": "Pilot", "p1": 0, "p2": 0, "p3": 0, "review": "",
            "be": "", "fe": "", "checks": [], "findings": "", "report": ""}


DATA.write_text(json.dumps({"title": "Demo", "updated": "2026-01-05 09:00", "branch": "main", "meta": {"idPrefix": "pag"},
                            "screens": [_seed_screen("pag1010e", "Sign in", 1), _seed_screen("pag1011e", "Profile", 2),
                                        _seed_screen("pag2020e", "Settings", 3)],
                            "menus": ["Pages"], "batches": ["Pilot"], "decisions": [], "log": [], "events": [],
                            "commits": [], "inbox": []}))
(HOME / "workspaces.json").write_text(json.dumps({"version": 1, "current": "demo", "user": "You", "workspaces": [
    {"id": "demo", "name": "Demo", "data": str(DATA), "root": None, "color": "orange", "cli": "plots",
     "idPrefix": "pag", "markers": [], "sessionRoots": []}]}))


def _set_screen(pid, **kv):
    d = json.loads(DATA.read_text())
    s = next(x for x in d["screens"] if x["id"] == pid)
    s.update(kv)
    DATA.write_text(json.dumps(d, ensure_ascii=False))


def _screen(pid):
    return next(x for x in json.loads(DATA.read_text())["screens"] if x["id"] == pid)


def _git(cwd, *a):
    return subprocess.run(["git", "-C", str(cwd)] + list(a), capture_output=True, text=True, check=True).stdout


def make_lane(name, branch):
    for side in ("be", "fe"):
        r = LANES / name / side
        r.mkdir(parents=True)
        _git(r, "init", "-q", "-b", branch)
        _git(r, "config", "user.email", "t@t")
        _git(r, "config", "user.name", "t")
        (r / "a.txt").write_text(side)
        _git(r, "add", ".")
        _git(r, "commit", "-q", "-m", "init")


make_lane("two-factor", "feature/pag1010e-dev")
make_lane("shared", "feature/shared-base-dev")
(HOME / "auto").mkdir(parents=True)
(HOME / "auto/installed").write_text(str(time.time() - 5))

sys.path.insert(0, str(HERE))
import plots_lanes as L  # noqa: E402
import plots_writes as T  # noqa: E402

W = T.resolve_ws(None, ["pag1010e"])


class Lanes(unittest.TestCase):
    def test_paths_and_branches(self):
        info = L.lane_of_path(LANES / "two-factor/fe/src/x.tsx")
        self.assertEqual((info["lane"], info["side"]), ("two-factor", "fe"))
        self.assertIsNone(L.lane_of_path(LANES / "two-factor/tracker/x"))
        self.assertEqual(L.branch_of(info["repo"]), "feature/pag1010e-dev")
        self.assertEqual(L.pages_of_branch("feature/pag2020e-dev"), ["pag2020e"])
        self.assertEqual(L.pages_of_branch("feature/shared-base-dev"), [])

    def test_lanes_in_command(self):
        got = L.lanes_in_command('cd "$L/two-factor/fe" && npm test', None)
        self.assertEqual([(x["lane"], x["side"]) for x in got], [("two-factor", "fe")])
        got = L.lanes_in_command("git -C %s/two-factor status" % LANES, None)
        self.assertEqual(sorted(x["side"] for x in got), ["be", "fe"])
        self.assertEqual(L.lanes_in_command("ls two-factor-v2", None), [])
        got = L.lanes_in_command("cd $L/shared/fe && npx vitest run", str(LANES / "two-factor/fe"))
        self.assertEqual([(x["lane"], x["side"]) for x in got], [("shared", "fe")])      # the named lane, not the cwd

    def test_commit_parse(self):
        out = "[feature/pag1010e-dev 3e9d1c7f2] fix(pag1010e): paging bar\n 1 file changed"
        c = L.commits_in("git commit -m x", out)
        self.assertEqual(c, [{"branch": "feature/pag1010e-dev", "hash": "3e9d1c7f2", "msg": "fix(pag1010e): paging bar", "action": "commit"}])
        self.assertEqual(L.commits_in("git -C x commit --amend --no-edit", out)[0]["action"], "amend")
        self.assertEqual(L.commits_in("git cherry-pick abc", out)[0]["action"], "cherry-pick")
        self.assertEqual(L.commits_in('echo "git commit" > x.txt', out), [])
        self.assertEqual(L.commits_in("git log", out), [])
        self.assertEqual(L.commits_in("git commit", "[main (root-commit) abcdef1] init")[0]["branch"], "main")

    def test_test_results(self):
        self.assertEqual(L.test_kind("cd fe && npm test -- --run"), "npm test")
        self.assertEqual(L.test_kind("./gradlew :app:test --offline"), "gradle test")
        self.assertEqual(L.test_kind("npx tsc --noEmit -p ."), "tsc")
        self.assertIsNone(L.test_kind("git status"))
        self.assertEqual(L.test_result("vitest", " Tests  2 failed | 118 passed (120)\n"), "vitest 2 failed | 118 passed")
        self.assertEqual(L.test_result("npm test", "ℹ tests 40\nℹ pass 40\nℹ fail 0\n"), "npm test 40 pass, 0 fail")
        self.assertEqual(L.test_result("gradle test", "380 tests completed, 1 failed\nBUILD FAILED"), "gradle test 380 tests, 1 failed")
        self.assertEqual(L.test_result("tsc", "x.ts(1,1): error\nFound 55 errors in 9 files."), "tsc 55 errors")
        self.assertEqual(L.test_result("tsc", ""), "tsc 0 errors")
        self.assertIsNone(L.test_result("npm test", "nothing useful"))
        self.assertIsNone(L.test_result("npm test", "", failed=True))
        self.assertIsNone(L.test_result("tsc", "", redirected=True))

    def test_no_false_test_runs(self):
        for cmd in ("./gradlew build -x test", "./gradlew :app:assemble -x test --offline", "cat jest.config.js",
                    "git commit -q -m 'fix tsc errors'", "grep -rn tsc package.json", "echo npm test", "ls vitest.config.ts"):
            self.assertIsNone(L.test_kind(cmd), cmd)
        self.assertEqual(L.test_kind("cd fe && NODE_ENV=test npx tsc --noEmit -p ."), "tsc")
        self.assertEqual(L.test_kind("time ./node_modules/.bin/vitest run"), "vitest")

    def test_plots_writes_seen(self):
        self.assertTrue(L.writes_plots("python3 ~/w/plots/plots.py --ws demo note pag1010e 'x'"))
        self.assertTrue(L.writes_plots("plots log 'milestone'"))
        self.assertTrue(L.writes_plots("plots decision add 'Topic' -s ask -d x"))
        self.assertTrue(L.writes_plots("plots decision 30 decided -d 'x'"))
        for cmd in ("plots log -n 5", "plots decision 3", "plots ls", "plots show pag1010e",
                    "git -C ~/worktrees/editor/fe log --oneline", "cat plots.py"):
            self.assertFalse(L.writes_plots(cmd), cmd)

    def test_note_helpers(self):
        n = "▶ now (01-05 13:20): working\nolder note"
        self.assertEqual(L.with_lane_line(n, "now: new"), "▶ now: new\nolder note")
        n2 = L.with_auto_tail(n, "FE commit abc 13:45")
        self.assertEqual(n2, "▶ now (01-05 13:20): working [auto: FE commit abc 13:45]\nolder note")
        self.assertEqual(L.with_auto_tail(n2, "x"), "▶ now (01-05 13:20): working [auto: x]\nolder note")
        self.assertEqual(L.with_auto_tail("plain", "x"), "▶ [auto: x]\nplain")
        self.assertTrue(L.stamp_line("doing it", "2026-01-05 13:49").startswith("now (01-05 13:49): "))
        self.assertEqual(L.stamp_line("next: review", "2026-01-05 13:49"), "next: review")


class Writes(unittest.TestCase):
    def test_user_statuses(self):
        _set_screen("pag1010e", status="Merged", note="▶ old line\nkeep me")
        with self.assertRaises(T.Refused):
            T.set_page(W, "pag1010e", status="tested")
        rows = T.set_page(W, "pag1010e", status="fix", line="fixing review note")
        self.assertTrue(rows[0]["kept_user_status"])
        s = _screen("pag1010e")
        self.assertEqual(s["status"], "Merged")
        self.assertTrue(s["note"].startswith("▶ now (") and "fixing review note" in s["note"] and s["note"].endswith("keep me"))
        T.set_page(W, "pag1010e", status="done")
        self.assertEqual(_screen("pag1010e")["status"], "Done")
        rows = T.set_page(W, "pag1010e", status="tested", user_asked=True)
        self.assertEqual(rows[0]["to"], "Tested")
        rows = T.set_page(W, "pag1010e", status="blocked", line="waiting on decision #3")
        self.assertTrue(rows[0]["kept_user_status"])
        self.assertEqual(_screen("pag1010e")["status"], "Tested")
        with self.assertRaises(T.Refused):
            T.set_page(W, "pag1010e", status="oos")

    def test_activity(self):
        _set_screen("pag1010e", status="Up next", note="▶ queued\nhistory", fe="")
        c = {"branch": "feature/pag1010e-dev", "hash": "1234567ab", "msg": "fix: thing"}
        T.record_activity(W, "pag1010e", commit=c, side="fe", branch=c["branch"])
        s = _screen("pag1010e")
        self.assertEqual(s["status"], "Fixing")
        self.assertEqual(s["fe"], "feature/pag1010e-dev")
        self.assertIn("[auto: FE commit 1234567ab", s["note"])
        n = sum(1 for x in json.loads(DATA.read_text())["commits"] if x["hash"] == "1234567ab")
        T.record_activity(W, "pag1010e", commit=c, side="fe", branch=c["branch"])
        self.assertEqual(sum(1 for x in json.loads(DATA.read_text())["commits"] if x["hash"] == "1234567ab"), n)
        T.record_activity(W, "pag1010e", test="npm test 3 pass, 0 fail")
        self.assertRegex(_screen("pag1010e")["note"], r"^▶ queued \[auto: FE commit 1234567ab \d\d:\d\d · npm test 3 pass, 0 fail \d\d:\d\d\]\nhistory$")
        m = {"branch": "feature/pag1010e-dev", "hash": "fedcba987", "msg": "Merge branch 'develop'"}
        _set_screen("pag1010e", status="Up next")
        T.record_activity(W, "pag1010e", commit=m, side="be", branch=m["branch"])
        self.assertEqual(_screen("pag1010e")["status"], "Up next")      # a merge doesn't mean an agent is on it
        self.assertFalse(any(x["hash"] == "fedcba987" for x in json.loads(DATA.read_text())["commits"]))
        cp = {"branch": "feature/pag1010e-dev", "hash": "c0ffee123", "msg": "fix: shared", "action": "cherry-pick"}
        T.record_activity(W, "pag1010e", commit=cp, side="fe", branch=cp["branch"])
        self.assertEqual(_screen("pag1010e")["status"], "Up next")      # a cherry-pick brings existing work in
        self.assertFalse(any(x["hash"] == "c0ffee123" for x in json.loads(DATA.read_text())["commits"]))
        # an amend replaces the commit it amended
        a1 = {"branch": "feature/pag1010e-dev", "hash": "aaaa11111", "msg": "feat: one", "action": "commit"}
        T.record_activity(W, "pag1010e", commit=a1, side="be", branch=a1["branch"])
        a2 = {"branch": "feature/pag1010e-dev", "hash": "bbbb22222", "msg": "feat: one (amended)", "action": "amend"}
        T.record_activity(W, "pag1010e", commit=a2, side="be", branch=a2["branch"], replaces=T.last_commit("pag1010e", "be"))
        hs = [x["hash"] for x in json.loads(DATA.read_text())["commits"]]
        self.assertIn("bbbb22222", hs)
        self.assertNotIn("aaaa11111", hs)
        # automatic writes leave no undo snapshot; a fresh ▶ line drops the old tail
        undo = HOME / "workspaces/demo/.undo/progress"
        n = len(list(undo.glob("*.json"))) if undo.exists() else 0
        T.record_activity(W, "pag1010e", test="tsc 55 errors")
        self.assertEqual(len(list(undo.glob("*.json"))) if undo.exists() else 0, n)
        T.set_page(W, "pag1010e", line="fresh line")
        T.record_activity(W, "pag1010e", test="tsc 54 errors")
        self.assertNotIn("bbbb22222", _screen("pag1010e")["note"].splitlines()[0])


def mcp(*calls):
    msgs = [{"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"}, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}]
    for i, (name, args) in enumerate(calls):
        msgs.append({"jsonrpc": "2.0", "id": 10 + i, "method": "tools/call", "params": {"name": name, "arguments": args}})
    r = subprocess.run([sys.executable, str(HERE / "plots_mcp.py")], input="\n".join(json.dumps(m) for m in msgs) + "\n",
                       capture_output=True, text=True, timeout=60)
    return [json.loads(x) for x in r.stdout.splitlines() if x.strip()], r.stderr


class Mcp(unittest.TestCase):
    def test_tools(self):
        _set_screen("pag1010e", status="Fixing", note="▶ x\nold")
        out, err = mcp(("get_status", {}), ("get_status", {"ids": "pag1010e"}),
                       ("set_lane_line", {"ids": "pag1010e", "line": "review round 2 running"}),
                       ("set_page_status", {"ids": "1010e", "status": "next", "line": "waiting for review round 2"}),
                       ("set_page_status", {"ids": "pag1010e", "status": "merged"}),
                       ("log_event", {"text": "test log line"}),
                       ("record_commit", {"side": "FE", "hash": "abcabc123", "message": "m"}),
                       ("record_commit", {"side": "FE", "hash": "abcabc123", "message": "m"}),
                       ("add_decision", {"topic": "T", "proposal": "P", "ids": "pag1010e"}),
                       ("get_status", {"ids": "nope0000x"}))
        self.assertEqual(out[0]["result"]["serverInfo"]["name"], "plots", err)
        names = [t["name"] for t in out[1]["result"]["tools"]]
        for n in ("get_status", "set_page_status", "set_lane_line", "log_event"):
            self.assertIn(n, names)
        txt = [o["result"]["content"][0]["text"] for o in out[2:]]
        err_flags = [o["result"].get("isError", False) for o in out[2:]]
        self.assertIn("done", txt[0])
        self.assertIn("pag1010e", txt[1])
        self.assertIn("▶ line written on pag1010e", txt[2])
        self.assertIn("Fixing → Up next", txt[3])
        self.assertTrue(err_flags[4] and "user" in txt[4].lower())
        self.assertEqual(txt[5], "ok logged")
        self.assertIn("recorded", txt[6])
        self.assertIn("already recorded", txt[7])
        self.assertIn("decision #", txt[8])
        self.assertTrue(err_flags[9])
        s = _screen("pag1010e")
        self.assertEqual(s["status"], "Up next")
        self.assertTrue(s["note"].startswith("▶ now (") and "waiting for review round 2" in s["note"] and s["note"].endswith("\nold"))


def hook(mode, inp):
    r = subprocess.run([sys.executable, str(HERE / "plots_auto_hook.py"), mode], input=json.dumps(inp),
                       capture_output=True, text=True, timeout=60)
    return r.stdout.strip()


class Hooks(unittest.TestCase):
    def test_commit_test_and_stop(self):
        _set_screen("pag1010e", status="Up next", note="▶ queued\nold")
        fe = LANES / "two-factor/fe"
        (fe / "b.txt").write_text("x")
        _git(fe, "add", ".")
        out = subprocess.run(["git", "-C", str(fe), "commit", "-m", "feat(pag1010e): b"], capture_output=True, text=True).stdout
        sid = "s-%d" % time.time()
        base = {"session_id": sid, "transcript_path": str(TMP / "none.jsonl"), "cwd": str(TMP)}
        # an edit in the lane by a subagent, then its commit
        hook("post-tool", dict(base, hook_event_name="PostToolUse", agent_id="ag1", tool_name="Edit",
                               tool_input={"file_path": str(fe / "b.txt")}, tool_response={}))
        hook("post-tool", dict(base, hook_event_name="PostToolUse", agent_id="ag1", tool_name="Bash",
                               tool_input={"command": "cd %s && git commit -m 'feat(pag1010e): b'" % fe},
                               tool_response={"stdout": out, "stderr": ""}))
        s = _screen("pag1010e")
        h = _git(fe, "rev-parse", "--short=7", "HEAD").strip()
        self.assertEqual(s["status"], "Fixing")
        self.assertIn("FE commit " + h, s["note"])
        self.assertTrue(any(c["hash"].startswith(h) for c in json.loads(DATA.read_text())["commits"]))
        # a failing test run (PostToolUseFailure)
        hook("post-tool", dict(base, hook_event_name="PostToolUseFailure", agent_id="ag1", tool_name="Bash",
                               tool_input={"command": "cd $L/two-factor/fe && npm test"},
                               error="Exit code 1\nℹ pass 10\nℹ fail 2"))
        self.assertIn("npm test 10 pass, 2 fail", _screen("pag1010e")["note"])
        # the subagent stops without a Plots update → asked once
        r = hook("stop", dict(base, hook_event_name="SubagentStop", agent_id="ag1", stop_hook_active=False))
        self.assertEqual(json.loads(r)["decision"], "block")
        self.assertIn("pag1010e", json.loads(r)["reason"])
        self.assertEqual(hook("stop", dict(base, hook_event_name="SubagentStop", agent_id="ag1", stop_hook_active=True)), "")
        # another agent that updates Plots after its work isn't asked
        hook("post-tool", dict(base, hook_event_name="PostToolUse", agent_id="ag2", tool_name="Write",
                               tool_input={"file_path": str(fe / "c.txt")}, tool_response={}))
        hook("post-tool", dict(base, hook_event_name="PostToolUse", agent_id="ag2", tool_name="mcp__plots__set_lane_line",
                               tool_input={"ids": "pag1010e", "line": "x"}, tool_response={}))
        self.assertEqual(hook("stop", dict(base, hook_event_name="SubagentStop", agent_id="ag2")), "")
        # the main session's own turn didn't touch a lane → nothing
        self.assertEqual(hook("stop", dict(base, hook_event_name="Stop")), "")

    def test_side_and_stop_rules(self):
        _set_screen("pag1010e", status="Fixing", note="▶ x", be="")
        be = LANES / "two-factor/be"
        (be / "e.txt").write_text("x")
        _git(be, "add", ".")
        out = subprocess.run(["git", "-C", str(be), "commit", "-m", "be change"], capture_output=True, text=True).stdout
        base = {"session_id": "s3", "transcript_path": "", "cwd": str(LANES / "two-factor/fe")}
        hook("post-tool", dict(base, hook_event_name="PostToolUse", tool_name="Bash",
                               tool_input={"command": "git -C ../be commit -m 'be change'"}, tool_response={"stdout": out}))
        h = _git(be, "rev-parse", "--short=7", "HEAD").strip()
        row = next(c for c in json.loads(DATA.read_text())["commits"] if c["hash"].startswith(h))
        self.assertEqual(row["repo"], "BE")                                   # proven by the hash, not the cwd
        self.assertIn("BE commit", _screen("pag1010e")["note"])
        # a reviewer that only ran tests in a lane isn't asked to set a status
        hook("post-tool", dict(base, session_id="s4", agent_id="rev", hook_event_name="PostToolUse", tool_name="Bash",
                               tool_input={"command": "npx tsc --noEmit"}, tool_response={"stdout": "Found 55 errors."}))
        self.assertIn("tsc 55 errors", _screen("pag1010e")["note"])
        self.assertEqual(hook("stop", dict(base, session_id="s4", agent_id="rev", hook_event_name="SubagentStop")), "")
        # a test run over two pages' lanes is not spread onto both
        before = _screen("pag1010e")["note"]
        hook("post-tool", dict(base, session_id="s5", hook_event_name="PostToolUse", tool_name="Bash",
                               tool_input={"command": "cd $L/two-factor/fe && npx tsc; cd $L/shared/fe && npx tsc"},
                               tool_response={"stdout": "Found 3 errors."}))
        self.assertEqual(_screen("pag1010e")["note"], before)

    def test_shared_lane_commit_and_other_repos(self):
        be = LANES / "shared/be"
        (be / "d.txt").write_text("x")
        _git(be, "add", ".")
        out = subprocess.run(["git", "-C", str(be), "commit", "-m", "refactor: shared utils"], capture_output=True, text=True).stdout
        base = {"session_id": "s2", "transcript_path": "", "cwd": str(TMP)}
        hook("post-tool", dict(base, hook_event_name="PostToolUse", tool_name="Bash",
                               tool_input={"command": "git -C %s commit -m x" % be}, tool_response={"stdout": out}))
        h = _git(be, "rev-parse", "--short=7", "HEAD").strip()
        self.assertTrue(any(c["hash"].startswith(h) and c["repo"] == "BE" for c in json.loads(DATA.read_text())["commits"]))
        before = DATA.read_text()
        hook("post-tool", dict(base, hook_event_name="PostToolUse", tool_name="Bash",
                               tool_input={"command": "git commit -m x"}, tool_response={"stdout": "[main 1111111] x"}))
        self.assertEqual(DATA.read_text(), before)          # not a lane: nothing written

    def test_old_sessions_untouched(self):
        old = TMP / "old.jsonl"
        old.write_text("{}")
        (HOME / "auto/installed").write_text(str(time.time() + 60))   # installed "after" this transcript
        try:
            before = DATA.read_text()
            hook("post-tool", {"session_id": "old", "transcript_path": str(old), "cwd": str(LANES / "two-factor/fe"),
                               "hook_event_name": "PostToolUse", "tool_name": "Bash",
                               "tool_input": {"command": "npx tsc --noEmit"}, "tool_response": {"stdout": "Found 3 errors."}})
            self.assertEqual(DATA.read_text(), before)
        finally:
            (HOME / "auto/installed").write_text(str(time.time() - 5))


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)

"""Writes for the Plots MCP server and hooks, through the engine's own write path (plots.py: mutate() takes the
workspace lock, keeps an undo snapshot and writes atomically; the app picks the change up live).

plots.py itself is not edited: the running Plots server restarts itself whenever that file changes.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import sys
import tempfile

import plots_lanes as L

sys.path.insert(0, str(L.TRACKER))
import plots as E  # noqa: E402  (the engine)

USER_STATUSES = set(E.QA)         # Testing, Tested, Merged: the user's own testing and merging
BACK_TO_WORK = {"Fixing", "Up next", "Not started", "Blocked"}
PAGES_STATE = L.AUTO_DIR / "pages.json"    # per page: the latest commit and test run, for the [auto …] tail


class Refused(Exception):
    pass


# --------------------------------------------------------------------------- workspaces

def workspaces() -> list:
    return E.reg_load().get("workspaces", [])


def _has_screen(w: dict, ids: list) -> bool:
    try:
        with open(os.path.expanduser(w["data"]), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, KeyError):
        return False
    have = {s.get("id", "").lower() for s in data.get("screens", [])}
    pre = (data.get("meta") or {}).get("idPrefix") or w.get("idPrefix") or ""
    for i in ids:
        k = i.lower()
        if k in have or (pre and pre + k in have):
            return True
    return False


def resolve_ws(workspace=None, ids=None) -> dict:
    """workspace argument → $PLOTS_WS → the workspace that holds the ids → the app's current one."""
    reg = E.reg_load()
    for key in (workspace, os.environ.get("PLOTS_WS")):
        if key:
            w = E.ws_find(reg, key)
            if not w:
                raise Refused("no Plots workspace %r (have: %s)" % (key, ", ".join(x["id"] for x in reg["workspaces"])))
            return w
    plain = [i for i in (ids or []) if i and not i.startswith("@")]
    if plain:
        for w in reg["workspaces"]:
            if _has_screen(w, plain):
                return w
    w = E.ws_find(reg, reg.get("current")) or (reg["workspaces"][0] if reg["workspaces"] else None)
    if not w:
        raise Refused("no Plots workspaces yet")
    return w


def split_ids(spec) -> list:
    if isinstance(spec, (list, tuple)):
        spec = " ".join(str(x) for x in spec)
    return [p for p in re.split(r"[,\s]+", str(spec or "")) if p]


# --------------------------------------------------------------------------- engine calls

def cli(w: dict, argv: list) -> str:
    """Run one engine command (plots.py's cmd_*) in-process on workspace w; its printed line is returned."""
    fn = E.COMMANDS[argv[0]]
    buf = io.StringIO()
    try:
        with E.ws_context(w), contextlib.redirect_stdout(buf):
            fn(list(argv[1:]))
    except SystemExit as e:
        raise Refused(re.sub(r"^err ", "", str(e.code if e.code is not None else e))) from None
    return buf.getvalue().strip()


def _mutate(w: dict, fn, reason: str):
    try:
        with E.ws_context(w):
            return E.mutate(fn, reason)
    except SystemExit as e:
        raise Refused(re.sub(r"^err ", "", str(e.code if e.code is not None else e))) from None


def read(w: dict) -> dict:
    with E.ws_context(w):
        return E.load()


# --------------------------------------------------------------------------- status and the ▶ line

def set_page(w: dict, spec, status=None, line=None, user_asked=False) -> list:
    """Status and/or ▶ line for one or more items in one atomic write:
    - Testing, Tested and Merged belong to the user: never set them unless asked (user_asked).
    - an item in Testing/Tested/Merged keeps that status while it is being fixed again or is blocked (only the
      ▶ line is written); Done when the fix is in, so the user re-tests it. Out of scope on such an item needs user_asked too."""
    st = E.parse_status(status) if status else None
    if st in USER_STATUSES and not user_asked:
        raise Refused("%s is the user's own testing/merging status: set it only when asked (pass user_asked=true)" % st)
    ids = split_ids(spec)
    if not ids:
        raise Refused("no ids")

    def fn(data):
        t = E.now()
        sc = E.resolve_ids(data, " ".join(ids))
        if st == E.OOS and not user_asked:
            qa = [s["id"] for s in sc if s["status"] in USER_STATUSES]
            if qa:
                raise SystemExit("err %s: user set %s; Out of scope needs confirmation (user_asked=true)" % (", ".join(qa), "/".join(sorted(USER_STATUSES))))
        out = []
        for s in sc:
            old, new, kept = s["status"], s["status"], False
            if st:
                if old in USER_STATUSES and st in BACK_TO_WORK and not user_asked:
                    kept = True
                else:
                    new = st
            if new != old:
                data.setdefault("events", []).append({"t": t, "id": s["id"], "from": old, "to": new, "by": "claude"})
                s["status"] = new
            if line is not None and str(line).strip():
                s["note"] = L.with_lane_line(s.get("note", ""), L.stamp_line(line, t))
                _forget_auto(s["id"])
            s["updated"] = t
            out.append({"id": s["id"], "name": s.get("name", ""), "from": old, "to": new, "kept_user_status": kept})
        return out

    what = ("status %s" % st if st else "") + (" ▶ line" if line else "")
    return _mutate(w, fn, "mcp %s %s" % (" ".join(ids), what.strip()))


def describe(w: dict, spec) -> str:
    data = read(w)
    try:
        with E.ws_context(w):
            sc = E.resolve_ids(data, " ".join(split_ids(spec)))
    except SystemExit as e:
        raise Refused(re.sub(r"^err ", "", str(e.code))) from None
    out = []
    for s in sc:
        line, rest = L.split_note(s.get("note", ""))
        hist = [e for e in data.get("events", []) if e.get("id") == s["id"]][-3:]
        decs = [d for d in data.get("decisions", []) if s["id"] in (d.get("screens") or []) and d.get("status") in E.D_OPEN]
        out.append("%s %s · %s · updated %s" % (s["id"], s.get("name", ""), s["status"], s.get("updated", "")))
        out.append("  ▶ " + (line or "(no ▶ line yet)"))
        if rest:
            out.append("  earlier: " + rest.replace("\n", " ")[:400] + ("…" if len(rest) > 400 else ""))
        for k in ("be", "fe", "review", "report", "findings"):
            if s.get(k):
                out.append("  %s: %s" % (k, s[k]))
        if s.get("myNotes"):
            out.append("  User notes: " + s["myNotes"].replace("\n", " ")[:300])
        if decs:
            out.append("  open decisions: " + "; ".join("#%d %s (%s)" % (d["n"], d["topic"], d["status"]) for d in decs))
        if hist:
            out.append("  history: " + " · ".join("%s %s→%s (%s)" % (e["t"][5:], e.get("from"), e.get("to"), e.get("by", "")) for e in hist))
    return "\n".join(out) or "(no items)"


# --------------------------------------------------------------------------- automatic activity (hooks)

def _pages_state() -> dict:
    try:
        return json.loads(PAGES_STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_pages_state(obj: dict) -> None:
    PAGES_STATE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(PAGES_STATE.parent), prefix=".pages-", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, PAGES_STATE)


def _forget_auto(pid: str) -> None:
    """A fresh ▶ line starts a fresh [auto …] tail (called under the workspace lock)."""
    st = _pages_state()
    if st.pop(pid, None) is not None:
        _save_pages_state(st)


def _when(t: str, today: str) -> str:
    return t[11:16] if t[:10] == today else t[5:16]


def _tail(ps: dict, today: str) -> str:
    parts = []
    if ps.get("commit"):
        parts.append("%s %s" % (ps["commit"], _when(ps.get("commit_t", ""), today)))
    if ps.get("test"):
        parts.append("%s %s" % (ps["test"], _when(ps.get("test_t", ""), today)))
    return " · ".join(parts)


def _quiet_write(w: dict, fn):
    """The engine's lock and atomic write, without an undo snapshot: automatic tails and commit rows must not fill
    `plots undo` (it keeps 50) or push the user's own last change out of it."""
    try:
        with E.ws_context(w):
            with E.Lock():
                data = E.load()
                res = fn(data)
                if res:
                    data["updated"] = E.now()
                    E._write_json(E.DATA, data)
                return res
    except SystemExit as e:
        raise Refused(re.sub(r"^err ", "", str(e.code if e.code is not None else e))) from None


SYNC_ACTIONS = {"cherry-pick", "am"}     # bringing existing work in, like a merge: not new work on the page


def record_activity(w: dict, page=None, commit=None, test=None, side=None, branch=None, replaces=None) -> list:
    """One write for a commit or a test run seen in a lane:
    - a new commit: added to the workspace's commits (once per hash; an amend replaces the commit it amended); the
      page's be/fe branch is filled in when empty; a page in Not started / Up next moves to Fixing (an agent is on it);
    - a merge, cherry-pick or am only updates the tail;
    - the page's ▶ line gets an '[auto: …]' tail with its latest commit and test run."""
    side_u = (side or "").upper() or "REPO"
    sync = bool(commit and (commit["msg"].startswith("Merge ") or commit.get("action") in SYNC_ACTIONS))

    def fn(data):
        t = E.now()
        did = []
        if commit and not sync:
            h = commit["hash"]
            rows = data.setdefault("commits", [])
            if not any(c.get("hash", "")[:7] == h[:7] for c in rows[-400:]):
                old = None
                if replaces:
                    old = next((c for c in reversed(rows[-400:]) if c.get("hash", "")[:7] == replaces[:7]), None)
                if old is not None:
                    old.update(hash=h, msg=commit["msg"][:200], date=E.today())
                    did.append("commit %s %s (amended %s)" % (side_u, h, replaces))
                else:
                    rows.append({"repo": side_u, "date": E.today(), "hash": h, "msg": commit["msg"][:200]})
                    did.append("commit %s %s" % (side_u, h))
        if page:
            try:
                s = E.find_screen(data, page)
            except SystemExit:
                s = None
            if s:
                st = _pages_state()
                ps = st.setdefault(s["id"], {})
                if commit:
                    kind = "merge" if commit["msg"].startswith("Merge ") else (commit.get("action") if sync else "commit")
                    ps["commit"] = "%s %s %s" % (side_u, kind, commit["hash"][:9])
                    ps["commit_t"] = t
                    if not sync and side in ("be", "fe"):
                        ps.setdefault("last", {})[side] = commit["hash"]
                if test:
                    ps["test"], ps["test_t"] = test, t
                _save_pages_state(st)
                s["note"] = L.with_auto_tail(s.get("note", ""), _tail(ps, t[:10]))
                if commit and not sync and commit.get("action") != "amend":
                    if side in ("be", "fe") and branch and not s.get(side):
                        s[side] = branch
                    if s["status"] in ("Not started", "Up next"):
                        data.setdefault("events", []).append({"t": t, "id": s["id"], "from": s["status"], "to": "Fixing", "by": "claude"})
                        s["status"] = "Fixing"
                        did.append("%s → Fixing" % s["id"])
                s["updated"] = t
                did.append("%s ▶ auto" % s["id"])
        return did

    if not page and (not commit or sync):
        return []
    return _quiet_write(w, fn) or []


def last_commit(page: str, side: str):
    """The last commit the hooks recorded for a page's be/fe (to replace it when it is amended)."""
    return ((_pages_state().get(page) or {}).get("last") or {}).get(side)

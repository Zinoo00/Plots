#!/usr/bin/env python3
"""Plots: progress tracking for Claude Code projects. One JSON file per workspace, a tiny CLI, a local app.

Stdlib only, Python 3.8+.  `plots help` prints the cheat sheet.
Workspaces are listed in ~/.plots/workspaces.json (override the folder with PLOTS_HOME).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import uuid
import webbrowser
import zipfile
import datetime as dt
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape as _xesc

try:
    import fcntl  # macOS / Linux
except ImportError:  # pragma: no cover - Windows
    fcntl = None

VERSION = 6
APP_NAME = "Plots"
BUNDLE_ID = "local.plots.app"
ROOT = Path(__file__).resolve().parent          # the engine folder (holds app/)
APP_DIR = ROOT / "app"
HOME = Path(os.environ.get("PLOTS_HOME") or (Path.home() / ".plots"))
REGISTRY = HOME / "workspaces.json"
RUN_DIR = HOME / "run"
PORT = int(os.environ.get("PLOTS_PORT") or 4317)
HOST = "127.0.0.1"
PROG = "plots"          # the command name shown in messages

# The current workspace's files. The CLI picks one workspace per run; the server switches per request under
# _DATA_LOCK (see ws_context).
DATA = Path(os.environ.get("PLOTS_DATA") or (ROOT / "data" / "progress.json"))
UNDO_DIR = DATA.parent / ".undo"
WS = None                 # the current workspace (dict) or None
_DATA_LOCK = threading.RLock()

# The workflow is Not started → Fixing → Done → Testing → Tested → Merged. In progress, In review and
# Fixing review notes map to one status, Fixing (formerly In flight). Testing, Tested and Merged are
# reserved for the user's own testing and merging; a bug found in testing sends an item back to Fixing.
# Up next (queued) sits before Fixing, with Blocked and Out of scope alongside. Done, Testing, Tested
# and Merged all count as done.
STATUSES = ["Not started", "Up next", "Fixing", "Done", "Testing", "Tested", "Merged", "Blocked", "Out of scope"]
OOS = "Out of scope"  # not worked on; left out of totals, progress, "up next" and the working counts
WORKING = ["Fixing", "Blocked"]
FINISHED = ["Done", "Testing", "Tested", "Merged"]
QA = ["Testing", "Tested", "Merged"]       # mostly set by the user in the app
LEGACY_STATUS = {"In progress": "Fixing", "In review": "Fixing", "In flight": "Fixing", "Fixing review notes": "Fixing"}
S_ALIAS = {
    "ns": "Not started", "notstarted": "Not started", "todo": "Not started", "reset": "Not started",
    "next": "Up next", "upnext": "Up next", "queue": "Up next", "queued": "Up next",
    "fix": "Fixing", "fixes": "Fixing", "fixingreviewnotes": "Fixing", "bug": "Fixing", "bugfix": "Fixing",
    "flight": "Fixing", "inflight": "Fixing", "fly": "Fixing",
    "wip": "Fixing", "prog": "Fixing", "progress": "Fixing", "inprogress": "Fixing",
    "start": "Fixing", "started": "Fixing", "doing": "Fixing", "reopen": "Fixing",
    "review": "Fixing", "rev": "Fixing", "inreview": "Fixing",
    "done": "Done", "complete": "Done", "finished": "Done",
    "testing": "Testing", "test": "Testing", "intest": "Testing", "qa": "Testing",
    "tested": "Tested", "verified": "Tested", "checked": "Tested", "passed": "Tested", "pass": "Tested",
    "merged": "Merged", "merge": "Merged",
    "blocked": "Blocked", "block": "Blocked", "stuck": "Blocked",
    "oos": OOS, "out": OOS, "outofscope": OOS, "scope": OOS, "excluded": OOS,
}
D_STATUSES = ["Waiting on you", "Please confirm", "Decided", "Confirmed"]
D_OPEN = ["Waiting on you", "Please confirm"]
D_ALIAS = {
    "wait": "Waiting on you", "waiting": "Waiting on you", "you": "Waiting on you",
    "waitingonyou": "Waiting on you",
    "ask": "Please confirm", "please": "Please confirm", "pc": "Please confirm",
    "pleaseconfirm": "Please confirm",
    "decided": "Decided", "decide": "Decided",
    "confirmed": "Confirmed", "ok": "Confirmed",
}


# --------------------------------------------------------------------------- utils

def now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M")


def today() -> str:
    return dt.date.today().isoformat()


def _key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def parse_status(word: str) -> str:
    k = _key(word)
    for s in STATUSES:
        if _key(s) == k:
            return s
    if k in S_ALIAS:
        return S_ALIAS[k]
    raise SystemExit("err unknown status %r (use: ns next fix done testing tested merged blocked oos)" % word)


def parse_dstatus(word: str) -> str:
    k = _key(word)
    for s in D_STATUSES:
        if _key(s) == k:
            return s
    if k in D_ALIAS:
        return D_ALIAS[k]
    raise SystemExit("err unknown decision status %r (use: wait ask decided confirmed)" % word)


def split_list(v) -> list:
    if v is None:
        return []
    if isinstance(v, list):
        return v
    v = str(v).strip()
    if v in ("", "—", "-", "–"):
        return []
    return [x.strip() for x in re.split(r"[,\s]+", v) if x.strip()]


def checks_list(v) -> list:
    out = []
    for x in split_list(v):
        m = re.match(r"#?(\d+)$", x)
        if m:
            out.append(int(m.group(1)))
    return out


def clean(v) -> str:
    if v is None:
        return ""
    v = str(v).strip()
    return "" if v in ("—", "–", "-") else v


# --------------------------------------------------------------------------- workspaces

# workspace badge colours; graphite first (the app has no blue theme)
COLORS = ["gray", "green", "orange", "purple", "pink", "teal", "indigo", "red", "yellow", "blue"]


class FileLock:
    """An advisory lock on <path>.lock (fcntl), for files more than one process writes."""

    def __init__(self, path):
        self.path = Path(str(path) + ".lock")

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(self.path, "a+")
        if fcntl:
            fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        if fcntl:
            fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")
    return s[:32] or "workspace"


def _initials(name: str) -> str:
    words = [w for w in re.split(r"[\s\-_·()]+", str(name)) if w]
    latin = [w for w in words if w[0].isascii() and w[0].isalnum()]
    if len(latin) >= 2:
        return (latin[0][0] + latin[1][0]).upper()
    if latin:
        return latin[0][:2].upper()
    return words[0][:1] if words else "?"


def user_name() -> str:
    """What the app calls its user (the registry's "user", else the first name of this Mac's user)."""
    n = reg_load().get("user")
    if n:
        return n
    try:
        full = subprocess.run(["id", "-F"], capture_output=True, text=True, timeout=2).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        full = ""
    return (full.split() or [os.environ.get("USER", "you")])[0]


def reg_load() -> dict:
    try:
        reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
        if isinstance(reg, dict) and isinstance(reg.get("workspaces"), list):
            return reg
    except (OSError, ValueError):
        pass
    return {"version": 1, "current": None, "workspaces": []}


def reg_update(fn):
    """Load the registry, apply fn(reg) -> result, save it atomically."""
    with FileLock(REGISTRY):
        reg = reg_load()
        out = fn(reg)
        _write_json(REGISTRY, reg)
        return out


def ws_find(reg: dict, key) -> dict:
    if not key:
        return None
    k = str(key).strip().lower()
    for w in reg["workspaces"]:
        if w.get("id", "").lower() == k:
            return w
    for w in reg["workspaces"]:
        if w.get("name", "").lower() == k or _slug(w.get("name", "")) == k:
            return w
    return None


def _roots(w: dict) -> list:
    out = [w.get("root")] + list(w.get("sessionRoots") or [])
    return [str(Path(r).expanduser()) for r in out if r]


def ws_for_path(reg: dict, path) -> dict:
    """The workspace whose folder holds `path` (the deepest match wins)."""
    try:
        p = str(Path(path).resolve())
    except OSError:
        return None
    best, depth = None, -1
    for w in reg["workspaces"]:
        for r in _roots(w):
            if p == r or p.startswith(r.rstrip("/") + "/"):
                if len(r) > depth:
                    best, depth = w, len(r)
    return best


def ws_resolve(explicit=None, default_id=None) -> dict:
    """--ws, then $PLOTS_WS, then the workspace that holds the current folder, then the app's current one."""
    reg = reg_load()
    for key in (explicit, default_id, os.environ.get("PLOTS_WS")):
        if key:
            w = ws_find(reg, key)
            if not w:
                if key == default_id:
                    continue
                raise SystemExit("err no workspace %r (run: %s ws)" % (key, PROG))
            return w
    w = ws_for_path(reg, os.getcwd())
    if w:
        return w
    w = ws_find(reg, reg.get("current")) or (reg["workspaces"][0] if reg["workspaces"] else None)
    if not w:
        raise SystemExit("err no workspace yet: run `%s init \"Name\"` in your project folder" % PROG)
    return w


def use_ws(w: dict) -> None:
    global DATA, UNDO_DIR, WS
    WS = w
    DATA = Path(w["data"]).expanduser()
    UNDO_DIR = DATA.parent / ".undo" / DATA.stem


class ws_context:
    """Serialize work on one workspace's files inside the server (requests run on threads)."""

    def __init__(self, w):
        self.w = w

    def __enter__(self):
        _DATA_LOCK.acquire()
        self.saved = (DATA, UNDO_DIR, WS)
        use_ws(self.w)
        return self.w

    def __exit__(self, *exc):
        global DATA, UNDO_DIR, WS
        DATA, UNDO_DIR, WS = self.saved
        _DATA_LOCK.release()


def id_prefix(data: dict = None) -> str:
    if WS is not None and "idPrefix" in WS:
        return WS.get("idPrefix") or ""
    meta = (data or {}).get("meta") or {}
    return meta.get("idPrefix", "") if data is not None else ""


def new_data(name: str, prefix: str = "") -> dict:
    return {"title": name, "updated": now(), "branch": "", "meta": {"idPrefix": prefix},
            "screens": [], "menus": [], "batches": [], "decisions": [], "log": [], "events": [],
            "commits": [], "inbox": []}


def ws_add(name: str, root=None, data=None, wid=None, color=None, cli=None, prefix="") -> dict:
    name = str(name).strip() or "Workspace"
    root = str(Path(root).expanduser().resolve()) if root else None

    def fn(reg):
        base = _slug(wid or name)
        i, w_id = 2, base
        while ws_find(reg, w_id) and ws_find(reg, w_id).get("id") == w_id:
            w_id, i = "%s-%d" % (base, i), i + 1
        path = Path(data).expanduser().resolve() if data else HOME / "workspaces" / w_id / "progress.json"
        used = {w.get("color") for w in reg["workspaces"]}
        w = {"id": w_id, "name": name, "data": str(path), "root": root,
             "color": color or next((c for c in COLORS if c not in used), COLORS[len(reg["workspaces"]) % len(COLORS)]),
             "cli": cli or "plots", "idPrefix": prefix, "markers": [], "sessionRoots": [], "created": now()}
        if not path.exists():
            _write_json(path, new_data(name, prefix))
        reg["workspaces"].append(w)
        if not reg.get("current"):
            reg["current"] = w_id
        return w
    return reg_update(fn)


def ws_set(wid: str, **kv) -> dict:
    allowed = {"name", "root", "color", "cli", "idPrefix", "markers", "sessionRoots", "budget", "model", "effort", "data",
               "repos", "branchFilter", "notes"}

    def fn(reg):
        w = ws_find(reg, wid)
        if not w:
            raise SystemExit("err no workspace %r" % wid)
        for k, v in kv.items():
            if k not in allowed:
                raise SystemExit("err unknown workspace key %r (use: %s)" % (k, " ".join(sorted(allowed))))
            if k in ("root", "data") and v:
                v = str(Path(v).expanduser().resolve())
            if k == "notes" and v not in ("fork", "project"):
                raise SystemExit("err notes= takes fork (a fork of the working session answers) or project (your Claude project answers)")
            w[k] = v
        return w
    return reg_update(fn)


def ws_use(wid: str) -> dict:
    def fn(reg):
        w = ws_find(reg, wid)
        if not w:
            raise SystemExit("err no workspace %r" % wid)
        reg["current"] = w["id"]
        return w
    return reg_update(fn)


def ws_public(w: dict, with_stats=True) -> dict:
    out = {k: w.get(k) for k in ("id", "name", "color", "root", "data", "cli")}
    out["notes"] = w.get("notes") or "fork"
    out["initials"] = _initials(w.get("name", ""))
    p = Path(w["data"]).expanduser()
    out["exists"] = p.exists()
    if with_stats and out["exists"]:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            st = stats(d)
            out.update({"done": st["done"], "total": st["total"], "title": d.get("title", "")})
        except (OSError, ValueError, KeyError):
            pass
    return out


# --------------------------------------------------------------------------- storage

class Lock:
    def __enter__(self):
        DATA.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(str(DATA) + ".lock", "a+")
        if fcntl:
            fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        if fcntl:
            fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()


def load() -> dict:
    if not DATA.exists():
        raise SystemExit("err no data at %s (run: %s ws to see your workspaces)" % (DATA, PROG))
    with open(DATA, encoding="utf-8") as f:
        data = json.load(f)
    normalize_statuses(data)
    return data


def normalize_statuses(data: dict) -> bool:
    """In progress, In review, In flight and Fixing review notes are all Fixing now (also in the history, where a
    move among them disappears). True when something changed."""
    changed = False
    for s in data.get("screens", []):
        if s.get("status") in LEGACY_STATUS:
            s["status"] = LEGACY_STATUS[s["status"]]
            changed = True
    if any(e.get("from") in LEGACY_STATUS or e.get("to") in LEGACY_STATUS for e in data.get("events", [])):
        evs = []
        for e in data["events"]:
            f, t = LEGACY_STATUS.get(e.get("from"), e.get("from")), LEGACY_STATUS.get(e.get("to"), e.get("to"))
            if (f, t) != (e.get("from"), e.get("to")):
                if f == t:
                    continue
                e = dict(e, **{"from": f, "to": t})
            evs.append(e)
        data["events"] = evs
        changed = True
    return changed


def migrate_statuses() -> None:
    """Write the renamed statuses into the data file once (the page reads the file as it is)."""
    try:
        if not DATA.exists():
            return
        raw = DATA.read_text(encoding="utf-8")
        if not any('"%s"' % k in raw for k in LEGACY_STATUS):
            return
        with Lock():
            with open(DATA, encoding="utf-8") as f:
                data = json.load(f)
            prev = json.loads(json.dumps(data))
            if normalize_statuses(data):
                _snapshot(prev, "statuses renamed: In progress, In review, In flight and Fixing review notes are Fixing")
                _write_json(DATA, data)
    except (OSError, ValueError):
        pass


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, path)


def _snapshot(prev: dict, reason: str) -> None:
    UNDO_DIR.mkdir(parents=True, exist_ok=True)
    name = "%d.json" % int(time.time() * 1000)
    _write_json(UNDO_DIR / name, {"reason": reason, "t": now(), "data": prev})
    snaps = sorted(UNDO_DIR.glob("*.json"))
    for old in snaps[:-50]:
        try:
            old.unlink()
        except OSError:
            pass


def mutate(fn, reason: str):
    """Load, apply fn(data) -> result, stamp, snapshot for undo, write atomically."""
    with Lock():
        data = load()
        prev = json.loads(json.dumps(data))
        result = fn(data)
        data["updated"] = now()
        _snapshot(prev, reason)
        _write_json(DATA, data)
        return result


def find_screen(data: dict, ident: str):
    k = ident.strip().lower()
    for s in data["screens"]:  # exact id first
        if s["id"].lower() == k:
            return s
    pre = id_prefix(data)
    if pre and not k.startswith(pre):
        k = pre + k
    for s in data["screens"]:
        if s["id"].lower() == k:
            return s
    hits = [s for s in data["screens"] if k in [c.lower() for c in s.get("covers", [])]]
    if len(hits) == 1:
        return hits[0]
    raise SystemExit("err no screen %r" % ident)


def resolve_ids(data: dict, spec: str) -> list:
    out = []
    for part in [p for p in re.split(r"[,\s]+", spec) if p]:
        if part.startswith("@"):
            b = _key(part[1:])
            group = [s for s in data["screens"] if _key(s.get("batch", "")).startswith(b)]
            if not group:
                raise SystemExit("err no batch %r" % part)
            out.extend(group)
        else:
            out.append(find_screen(data, part))
    seen, uniq = set(), []
    for s in out:
        if s["id"] not in seen:
            seen.add(s["id"])
            uniq.append(s)
    return uniq


def find_decision(data: dict, n) -> dict:
    n = int(str(n).lstrip("#"))
    for d in data["decisions"]:
        if d["n"] == n:
            return d
    raise SystemExit("err no decision #%d" % n)


# --------------------------------------------------------------------------- stats

def stats(data: dict, screens=None) -> dict:
    sc = screens if screens is not None else data["screens"]
    by = {s: 0 for s in STATUSES}
    for s in sc:
        by[s["status"]] = by.get(s["status"], 0) + 1
    oos = by.get(OOS, 0)
    total = len(sc) - oos
    done = sum(by.get(s, 0) for s in FINISHED)
    working = sum(by.get(s, 0) for s in WORKING)
    f_total = sum(s.get("p1", 0) + s.get("p2", 0) + s.get("p3", 0) for s in sc if s["status"] != OOS)
    f_done = sum(s.get("p1", 0) + s.get("p2", 0) + s.get("p3", 0) for s in sc if s["status"] in FINISHED)
    return {
        "total": total, "oos": oos, "done": done, "working": working,
        "not_started": by["Not started"] + by["Up next"], "by": by,
        "pct": (100.0 * done / total) if total else 0.0,
        "findings": f_total, "findings_done": f_done,
        "waiting": [d for d in data.get("decisions", []) if d["status"] in D_OPEN],
        "unread": [i for i in data.get("inbox", []) if not i.get("read")],
    }


def up_next(data: dict, n: int = 6) -> list:
    queued = sorted([s for s in data["screens"] if s["status"] == "Up next"], key=lambda s: s.get("order", 999))
    rest = sorted([s for s in data["screens"] if s["status"] == "Not started"], key=lambda s: s.get("order", 999))
    return (queued + rest)[:n]


# --------------------------------------------------------------------------- xlsx import (stdlib)

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
       "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
       "pr": "http://schemas.openxmlformats.org/package/2006/relationships"}


def _col_index(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def read_xlsx(path) -> dict:
    """Return {sheet name: [[cell values...] per row]} using only the stdlib."""
    z = zipfile.ZipFile(str(path))
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.findall("m:si", _NS):
            shared.append("".join(t.text or "" for t in si.iter("{%s}t" % _NS["m"])))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    targets = {r.get("Id"): r.get("Target") for r in rels.findall("pr:Relationship", _NS)}
    out = {}
    for sh in wb.find("m:sheets", _NS).findall("m:sheet", _NS):
        rid = sh.get("{%s}id" % _NS["r"])
        target = targets[rid].lstrip("/")
        if not target.startswith("xl/"):
            target = "xl/" + target
        root = ET.fromstring(z.read(target))
        rows = []
        for row in root.iter("{%s}row" % _NS["m"]):
            cells = {}
            for c in row.findall("m:c", _NS):
                ref, t = c.get("r"), c.get("t")
                v = c.find("m:v", _NS)
                if t == "s" and v is not None:
                    val = shared[int(v.text)]
                elif t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter("{%s}t" % _NS["m"]))
                elif t == "b" and v is not None:
                    val = v.text == "1"
                elif v is not None and v.text is not None:
                    txt = v.text
                    if t in ("str", "e"):
                        val = txt
                    else:
                        try:
                            f = float(txt)
                            val = int(f) if f.is_integer() else f
                        except ValueError:
                            val = txt
                else:
                    val = None
                cells[_col_index(ref)] = val
            width = (max(cells) + 1) if cells else 0
            rows.append([cells.get(i) for i in range(width)])
        out[sh.get("name")] = rows
    return out


def _as_text_date(v) -> str:
    if isinstance(v, (int, float)) and v > 30000:  # Excel serial date
        d = dt.datetime(1899, 12, 30) + dt.timedelta(days=float(v))
        return d.strftime("%Y-%m-%d %H:%M") if d.hour or d.minute else d.strftime("%Y-%m-%d")
    return clean(v)


def _table(rows: list) -> list:
    if not rows:
        return []
    head = [clean(h) for h in rows[0]]
    out = []
    for r in rows[1:]:
        if not any(x not in (None, "") for x in r):
            continue
        out.append({head[i]: (r[i] if i < len(r) else None) for i in range(len(head)) if head[i]})
    return out


def import_xlsx(path) -> dict:
    sheets = read_xlsx(path)
    scr = _table(sheets.get("Screens", []))
    det = {clean(r.get("Screen")): r for r in _table(sheets.get("Details", []))}
    since = {}
    updated_at = ""
    title = Path(path).stem
    for r in sheets.get("Today", []):
        if r and isinstance(r[0], str) and r[0].endswith(" — daily progress"):
            title = r[0][:-len(" — daily progress")] or title
        if r and isinstance(r[0], str) and r[0].startswith("Last updated"):
            m = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2})", r[0])
            updated_at = m.group(1) if m else ""
        if r and len(r) > 2 and isinstance(r[0], str) and " — " in r[0] and r[2]:
            for sid in [x.strip().split(" ", 1)[0].lower() for x in r[0].split(" — ")[0].split(", ")]:
                since[sid] = _as_text_date(r[2])
    menus, screens = [], []
    for r in scr:
        sid = clean(r.get("Screen")).lower()
        d = det.get(sid, {})
        menu = clean(r.get("Menu"))
        if menu not in menus:
            menus.append(menu)
        upd = _as_text_date(r.get("Updated"))
        if sid in since and since[sid].startswith(upd[:10]):
            upd = since[sid]
        screens.append({
            "id": sid,
            "name": clean(r.get("Name")),
            "menu": menu,
            "status": parse_status(clean(r.get("Status")) or "Not started"),
            "note": clean(r.get("What's happening")),
            "updated": upd,
            "order": int(r.get("Fix order") or d.get("Fix order") or 999),
            "covers": split_list(r.get("Also covers")),
            "myNotes": clean(r.get("My notes")),
            "batch": clean(d.get("Fix batch")),
            "p1": int(d.get("P1") or 0), "p2": int(d.get("P2") or 0), "p3": int(d.get("P3") or 0),
            "review": clean(d.get("Review")),
            "be": clean(d.get("BE branch (commits on common)")),
            "fe": clean(d.get("FE branch (commits on common)")),
            "checks": checks_list(d.get("needs-check #")),
            "findings": clean(d.get("Findings file")),
            "report": clean(d.get("Fix report")),
        })
    batches = []
    for s in sorted(screens, key=lambda s: s["order"]):
        if s["batch"] and s["batch"] not in batches:
            batches.append(s["batch"])
    decisions = []
    for r in _table(sheets.get("Decisions", [])):
        decisions.append({
            "n": int(r.get("#") or 0),
            "topic": clean(r.get("Topic")),
            "status": parse_dstatus(clean(r.get("Status")) or "Please confirm"),
            "decision": clean(r.get("Decision")),
            "screens": [x.lower() for x in split_list(r.get("Screens"))],
            "myNotes": clean(r.get("My notes")),
        })
    log = [{"t": _as_text_date(r.get("When")), "text": clean(r.get("What changed"))}
           for r in _table(sheets.get("Log", []))]
    log.reverse()  # stored oldest first
    branch, commits = "", []
    cc = sheets.get("Common changes", [])
    if cc:
        m = re.search(r"on (\S+)", str(cc[0][3] if len(cc[0]) > 3 else ""))
        branch = m.group(1) if m else ""
        for r in cc[1:]:
            if not r or not any(r):
                continue
            commits.append({"repo": clean(r[0]), "date": _as_text_date(r[1]),
                            "hash": clean(r[2]), "msg": clean(r[3] if len(r) > 3 else "")})
        commits.reverse()  # stored oldest first
    events = []
    for s in sorted(screens, key=lambda s: (s["updated"], s["order"])):
        if s["status"] != "Not started":
            events.append({"t": s["updated"] or updated_at, "id": s["id"],
                           "from": "Not started", "to": s["status"], "by": "import"})
    return {
        "schema": 1,
        "title": title,
        "updated": updated_at or now(),
        "branch": branch,
        "menus": menus,
        "batches": batches,
        "screens": screens,
        "decisions": decisions,
        "log": log,
        "commits": commits,
        "events": events,
        "inbox": [],
    }


# --------------------------------------------------------------------------- xlsx export (stdlib)

_FILLS = {"Done": "C6EFCE", "Testing": "FFF2CC", "Tested": "A9D08E", "Merged": "E4DFEC", "Fixing": "FFEB9C",
          "Up next": "DDEBF7", "Blocked": "FFC7CE", OOS: "D9D9D9",
          "Waiting on you": "FFC7CE", "Please confirm": "FFEB9C", "Decided": "C6EFCE",
          "Confirmed": "C6EFCE"}
_FILL_ORDER = list(dict.fromkeys(_FILLS.values()))


def _style_xml() -> str:
    fills = ['<fill><patternFill patternType="none"/></fill>',
             '<fill><patternFill patternType="gray125"/></fill>',
             '<fill><patternFill patternType="solid"><fgColor rgb="FF1F4E78"/></patternFill></fill>']
    fills += ['<fill><patternFill patternType="solid"><fgColor rgb="FF%s"/></patternFill></fill>' % c
              for c in _FILL_ORDER]
    xfs = ['<xf fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>',
           '<xf fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>',
           '<xf fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/>',
           '<xf fontId="3" fillId="0" borderId="0" xfId="0" applyFont="1"/>',
           '<xf fontId="4" fillId="0" borderId="0" xfId="0" applyFont="1"/>',
           '<xf fontId="0" fillId="0" borderId="0" xfId="0" numFmtId="9" applyNumberFormat="1"/>']
    xfs += ['<xf fontId="0" fillId="%d" borderId="0" xfId="0" applyFill="1" applyAlignment="1"><alignment vertical="top"/></xf>' % (3 + i)
            for i in range(len(_FILL_ORDER))]
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<fonts count="5"><font><sz val="11"/><name val="Calibri"/></font>'
            '<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>'
            '<font><b/><sz val="18"/><color rgb="FF1F4E78"/><name val="Calibri"/></font>'
            '<font><b/><sz val="13"/><color rgb="FF1F4E78"/><name val="Calibri"/></font>'
            '<font><sz val="10"/><color rgb="FF595959"/><name val="Calibri"/></font></fonts>'
            '<fills count="%d">%s</fills>'
            '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            '<cellXfs count="%d">%s</cellXfs>'
            '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
            '</styleSheet>') % (len(fills), "".join(fills), len(xfs), "".join(xfs))


S_BODY, S_HEAD, S_TITLE, S_SECTION, S_MUTED, S_PCT = 0, 1, 2, 3, 4, 5


def _status_style(v) -> int:
    c = _FILLS.get(v)
    return 6 + _FILL_ORDER.index(c) if c else S_BODY


def _col_name(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _sheet_xml(rows, widths, freeze=False, autofilter=False) -> str:
    out = []
    for ri, row in enumerate(rows, start=1):
        cells = []
        for ci, cell in enumerate(row):
            if cell is None:
                continue
            if isinstance(cell, tuple):
                val, style = cell
            else:
                val, style = cell, S_BODY
            ref = "%s%d" % (_col_name(ci), ri)
            if val is None or val == "":
                if style:
                    cells.append('<c r="%s" s="%d"/>' % (ref, style))
                continue
            if isinstance(val, bool):
                val = "Yes" if val else "No"
            if isinstance(val, (int, float)):
                cells.append('<c r="%s" s="%d"><v>%s</v></c>' % (ref, style, val))
            else:
                cells.append('<c r="%s" s="%d" t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>'
                             % (ref, style, _xesc(str(val))))
        out.append('<row r="%d">%s</row>' % (ri, "".join(cells)))
    cols = "".join('<col min="%d" max="%d" width="%s" customWidth="1"/>' % (i + 1, i + 1, w)
                   for i, w in enumerate(widths))
    pane = ('<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
            'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>') if freeze else \
        '<sheetViews><sheetView workbookViewId="0"/></sheetViews>'
    af = ""
    if autofilter and rows:
        af = '<autoFilter ref="A1:%s%d"/>' % (_col_name(len(rows[0]) - 1), len(rows))
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '%s<cols>%s</cols><sheetData>%s</sheetData>%s</worksheet>') % (pane, cols, "".join(out), af)


def _head(cols):
    return [(c, S_HEAD) for c in cols]


def export_xlsx(data: dict, path) -> Path:
    st = stats(data)
    screens = data["screens"]
    working = [s for s in screens if s["status"] in WORKING]
    groups = {}
    for s in sorted(working, key=lambda s: s.get("order", 999)):
        groups.setdefault((s["status"], s["note"]), []).append(s)
    today_rows = [
        [("%s — daily progress" % data.get("title", APP_NAME), S_TITLE)],
        [("Last updated %s. Exported from %s." % (data.get("updated", ""), APP_NAME), S_MUTED)],
        [],
        [("At a glance", S_SECTION)],
        ["Screens done", st["done"], "of %d screen units" % st["total"]],
        ["Complete", (round(st["pct"] / 100.0, 4), S_PCT)],
        ["Being worked on now", st["working"], "fixing or blocked"],
        ["Not started yet", st["not_started"]],
        ["Out of scope", st["oos"], "not worked on; not counted in progress"],
        ["Decisions waiting on you", len(st["waiting"]), "see the Decisions sheet"],
        [],
        [("Working on now", S_SECTION)],
        _head(["Screens", "What's happening", "Since"]),
    ]
    for (status, note), group in groups.items():
        label = ", ".join("%s %s" % (s["id"], s["name"]) for s in group) + " — " + status
        today_rows.append([label, note, max(s["updated"] for s in group)])
    if not groups:
        today_rows.append(["Nothing in progress."])
    today_rows += [[], [("Up next", S_SECTION)], _head(["Screen", "Name", "Fix order"])]
    for s in up_next(data):
        today_rows.append([s["id"], s["name"], s["order"]])
    today_rows += [[], [("Recently finished", S_SECTION)], _head(["Screen", "Name", "Done on"])]
    done = sorted([s for s in screens if s["status"] in FINISHED], key=lambda s: s["updated"], reverse=True)[:10]
    for s in done:
        today_rows.append([s["id"], s["name"], s["updated"]])
    if not done:
        today_rows.append(["Nothing finished yet."])
    today_rows += [[], [("Progress by menu", S_SECTION)],
                   _head(["Menu", "Screens", "Done", "Working on", "Not started", "Complete"])]
    for m in data["menus"]:
        ms = stats(data, [s for s in screens if s["menu"] == m])
        today_rows.append([m, ms["total"], ms["done"], ms["working"], ms["not_started"],
                           (round(ms["pct"] / 100.0, 4), S_PCT)])

    scr_rows = [_head(["Menu", "Screen", "Name", "Status", "What's happening", "Updated",
                       "Fix order", "Also covers", "My notes"])]
    for s in screens:
        scr_rows.append([s["menu"], s["id"], s["name"], (s["status"], _status_style(s["status"])),
                         s["note"], s["updated"], s["order"], ", ".join(s["covers"]), s["myNotes"]])
    dec_rows = [_head(["#", "Topic", "Status", "Decision", "Screens", "My notes"])]
    for d in data["decisions"]:
        dec_rows.append([d["n"], d["topic"], (d["status"], _status_style(d["status"])), d["decision"],
                         ", ".join(d["screens"]) or "—", d["myNotes"]])
    log_rows = [_head(["When", "What changed"])] + [[e["t"], e["text"]] for e in reversed(data["log"])]
    det_rows = [_head(["Fix order", "Screen", "Fix batch", "P1", "P2", "P3", "Review",
                       "BE branch (commits on common)", "FE branch (commits on common)",
                       "needs-check #", "Findings file", "Fix report"])]
    for s in sorted(screens, key=lambda s: s.get("order", 999)):
        det_rows.append([s["order"], s["id"], s["batch"], s["p1"], s["p2"], s["p3"], s["review"] or "—",
                         s["be"] or "—", s["fe"] or "—",
                         ", ".join("#%d" % c for c in s["checks"]) or "—",
                         s["findings"] or "—", s["report"] or "—"])
    com_rows = [_head(["Repo", "Date", "Commit", "What changed on %s (newest first)" % data.get("branch", "")])]
    com_rows += [[c["repo"], c["date"], c["hash"], c["msg"]] for c in reversed(data["commits"])]

    sheets = [
        ("Today", _sheet_xml(today_rows, [44, 70, 18, 12, 12, 12])),
        ("Screens", _sheet_xml(scr_rows, [16, 11, 30, 18, 58, 16, 10, 18, 40], True, True)),
        ("Decisions", _sheet_xml(dec_rows, [5, 60, 16, 50, 40, 40], True, True)),
        ("Log", _sheet_xml(log_rows, [22, 120], True)),
        ("Details", _sheet_xml(det_rows, [9, 11, 13, 5, 5, 5, 26, 28, 28, 14, 24, 26], True, True)),
        ("Common changes", _sheet_xml(com_rows, [6, 12, 12, 140], True)),
    ]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
          '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
          + "".join('<Override PartName="/xl/worksheets/sheet%d.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' % (i + 1)
                    for i in range(len(sheets))) + '</Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>')
    wb = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
          + "".join('<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (_xesc(n), i + 1, i + 1)
                    for i, (n, _) in enumerate(sheets)) + '</sheets></workbook>')
    wbrels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
              + "".join('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet%d.xml"/>' % (i + 1, i + 1)
                        for i in range(len(sheets)))
              + '<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>' % (len(sheets) + 1)
              + '</Relationships>')
    tmp = path.with_name("." + path.name + ".tmp")
    with zipfile.ZipFile(str(tmp), "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("xl/workbook.xml", wb)
        z.writestr("xl/_rels/workbook.xml.rels", wbrels)
        z.writestr("xl/styles.xml", _style_xml())
        for i, (_, xml) in enumerate(sheets):
            z.writestr("xl/worksheets/sheet%d.xml" % (i + 1), xml)
    os.replace(tmp, path)
    return path


# --------------------------------------------------------------------------- CLI commands

def help_text() -> str:
    p = PROG
    return """%(p)s — Plots, progress for Claude Code projects. Every write prints one line. Add --json to any read.

Workspace: %(ws)s
  %(p)s                      summary: progress, next items, decisions waiting on you, inbox count
  %(p)s next [N]             next items to pick up, by fix order
  %(p)s ls [all|open|<status>|@<batch>|<group>]   compact list (default: active + up next)
  %(p)s show <id>            one item in full, with your note and its history
  %(p)s decisions [open|settled|all]          decisions (default: all, open first)
  %(p)s decision <n>                          one decision in full, with your answer
  %(p)s inbox [--peek]                        notes, answers and status changes left in the app
  %(p)s activity [N]                          latest log lines and status changes, newest first
  %(p)s log [-n N]                            latest log lines · %(p)s commits [N]: latest shared commits
  %(p)s code                                  worktrees and branches, and how far each is from the common branch

  %(p)s set <ids> <status> [-m "what's happening"]
                           ids: 0110 | 0110,0120 | @pilot (a whole batch)
                           status: ns next fix done testing tested merged blocked oos
  %(p)s note <ids> "what's happening"        change the note only
  %(p)s detail <id> key=value ...            review= be= fe= report= findings= checks=#2,#9 p1= p2= p3=
  %(p)s log "what changed"                   add a line to the Log
  %(p)s decision add "topic" [-s ask|wait|decided|confirmed] [-d "proposal to confirm"] [--screens ids]
  %(p)s decision <n> <status> [-d "decision"] [--screens ids]
  %(p)s commit <BE|FE> <hash> "message"      record a commit on the common branch
  %(p)s add <id> "name" --menu M --batch B [--order N]
  %(p)s undo                                 revert the last write

Chat in the app (a fork of your working session answers, or your Claude project with notes=project):
  %(p)s notes [N]                            the latest messages and their answers
  %(p)s relay "instruction"                  (inside a note's fork) pass an instruction on to the working session
  %(p)s sessions                             the Claude Code sessions a note can fork from
  With notes=project (%(p)s ws set <id> notes=project) your Claude project answers the app's Chat instead:
  %(p)s notes pending                        messages waiting for the project
  %(p)s notes reply <id> "answer"            answer one (it shows in the Chat) · notes fail <id> "why"
  %(p)s notes claim <id> --to "thread" [--where mac|cloud] [--url https://…] [--title "short title"]
                                             which thread has it (and what to call the conversation)
  %(p)s notes thread <id> [--state working|waiting|review|answered|idle|failed] [--progress "what it's doing"]
                                             [--where mac|cloud] [--url https://…]   the thread's card in the Chat
  %(p)s notes title <id> "short title"       name a conversation (default: its first message)
  plots bridge watch                     (the bridge) one JSON line per message handed to the project
  plots bridge claim|reply|fail|thread|title <ws> <id> …   the same, for any workspace

Workspaces (one per project; --ws <id> picks one for a single command):
  %(p)s ws                                   list them (* = the one the app shows)
  %(p)s init ["Name"] [--prefix P]           make a workspace for the current folder
  %(p)s ws add "Name" [--root DIR] [--data FILE]
  %(p)s ws use <id> · %(p)s ws set <id> key=value   (name= root= color= cli= budget= model= effort= sessionRoots=a,b
                                             repos=a,b branchFilter= notes=fork|project)
  %(p)s ws remove <id>                       forget a workspace (its data file stays)
  %(p)s ws user "Name"                       what the app and Claude call you

  %(p)s open | serve | stop                  the app, its local server (http://localhost:%(port)d) and stopping it
  %(p)s mcp                                  an MCP server (stdio) for Claude Desktop: status, items, notes
  %(p)s export [file.xlsx] | import <file.xlsx>""" % {
        "p": p, "port": PORT, "ws": ("%s (%s)" % (WS.get("name"), WS.get("id"))) if WS else "none yet"}


def _opt(args: list, *names, default=None):
    for n in names:
        if n in args:
            i = args.index(n)
            if i + 1 >= len(args):
                raise SystemExit("err %s needs a value" % n)
            val = args[i + 1]
            del args[i:i + 2]
            return val
    return default


def _flag(args: list, *names) -> bool:
    for n in names:
        if n in args:
            args.remove(n)
            return True
    return False


def _short(s: dict) -> str:
    return "%s %s" % (s["id"], s["name"])


JSON_OUT = False   # set by a global --json flag: read commands print JSON instead of text


def _emit(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=1))


def _screen_brief(s: dict) -> dict:
    return {k: s.get(k) for k in ("id", "name", "status", "menu", "batch", "order", "updated",
                                  "p1", "p2", "p3")}


def _history(data: dict, sid: str) -> list:
    return [e for e in data.get("events", []) if e.get("id") == sid]


def cmd_status(args):
    data = load()
    st = stats(data)
    by = st["by"]
    if JSON_OUT:
        return _emit({
            "title": data.get("title", APP_NAME), "updated": data.get("updated", ""),
            "total": st["total"], "done": st["done"], "pct": round(st["pct"], 1),
            "working": st["working"], "not_started": st["not_started"], "out_of_scope": st["oos"], "by_status": by,
            "findings": st["findings"], "findings_done": st["findings_done"],
            "next": [_screen_brief(s) for s in up_next(data, 4)],
            "waiting_on_user": [{"n": d["n"], "topic": d["topic"], "status": d["status"]} for d in st["waiting"]],
            "inbox_unread": len(st["unread"]),
        })
    parts = ["%d %s" % (by[k], k.lower()) for k in WORKING if by.get(k)]
    fin = ["%d %s" % (by[k], k.lower()) for k in QA if by.get(k)]
    print("%s · %d/%d done (%.0f%%%s) · %d working%s · %d not started%s · updated %s" % (
        data.get("title", APP_NAME), st["done"], st["total"], st["pct"], (", " + ", ".join(fin)) if fin else "",
        st["working"], (" (" + ", ".join(parts) + ")") if parts else "", st["not_started"],
        (" · %d out of scope" % st["oos"]) if st["oos"] else "", data.get("updated", "")))
    nx = up_next(data, 4)
    if nx:
        print("Next: " + ", ".join(_short(s) for s in nx))
    w = st["waiting"]
    print("Waiting on %s: %s · Inbox: %d new%s" % (
        user_name(), ", ".join("#%d" % d["n"] for d in w) or "none", len(st["unread"]),
        " (run: %s inbox)" % PROG if st["unread"] else ""))


def cmd_next(args):
    n = int(args[0]) if args else 6
    if JSON_OUT:
        return _emit([_screen_brief(s) for s in up_next(load(), n)])
    for s in up_next(load(), n):
        print("%2d  %s  %s · %s · P1 %d P2 %d P3 %d" % (s["order"], s["id"], s["name"], s["batch"],
                                                        s["p1"], s["p2"], s["p3"]))


def _match(data, s, tok):
    k = tok.lower()
    if k == "all":
        return True
    if k == "open":
        return s["status"] not in FINISHED and s["status"] != OOS
    if k in ("finished", "alldone"):
        return s["status"] in FINISHED
    if k.startswith("@"):
        return _key(s.get("batch", "")).startswith(_key(k[1:]))
    try:
        return s["status"] == parse_status(tok)
    except SystemExit:
        pass
    return k in s["menu"].lower()


def cmd_ls(args):
    data = load()
    sc = sorted(data["screens"], key=lambda s: s.get("order", 999))
    if args:
        sc = [s for s in sc if any(_match(data, s, t) for t in args)]
    else:
        sc = [s for s in sc if s["status"] in WORKING or s["status"] == "Up next"]
    if JSON_OUT:
        return _emit([_screen_brief(s) for s in sc])
    for s in sc:
        print("%-10s %-20s %s" % (s["id"], s["status"], s["name"]))
    if not sc:
        print("(none)")


def cmd_show(args):
    if not args:
        raise SystemExit("err usage: plots show <id>")
    data = load()
    s = find_screen(data, args[0])
    hist = _history(data, s["id"])
    if JSON_OUT:
        return _emit(dict(s, history=hist))
    print("%s %s · %s · %s · order %d" % (s["id"], s["name"], s["menu"], s["batch"], s["order"]))
    print("Status: %s%s" % (s["status"], (" (%s)" % s["updated"]) if s["updated"] else ""))
    if s["note"]:
        print("Note: " + s["note"])
    bits = ["Findings P1 %d P2 %d P3 %d" % (s["p1"], s["p2"], s["p3"])]
    if s["review"]:
        bits.append("Review: " + s["review"])
    if s["checks"]:
        bits.append("Checks " + ", ".join("#%d" % c for c in s["checks"]))
    print(" · ".join(bits))
    if s["be"] or s["fe"]:
        print("BE %s · FE %s" % (s["be"] or "—", s["fe"] or "—"))
    files = [f for f in (s["findings"], s["report"]) if f]
    if files or s["covers"]:
        print("Files: %s%s" % (" · ".join(files) or "—",
                               (" · also covers " + ", ".join(s["covers"])) if s["covers"] else ""))
    if s["myNotes"]:
        print("Your notes: " + s["myNotes"])
    if hist:
        print("History: " + " · ".join("%s %s (%s)" % (e["t"], e["to"], e.get("by", "")) for e in hist[-5:]))


def cmd_set(args):
    note = _opt(args, "-m", "--note")
    if len(args) < 2:
        raise SystemExit('err usage: plots set <ids> <status> [-m "note"]')
    status = parse_status(args[-1])
    spec = " ".join(args[:-1])

    def fn(data):
        sc = resolve_ids(data, spec)
        t = now()
        lines = []
        for s in sc:
            old = s["status"]
            if old != status:
                data.setdefault("events", []).append(
                    {"t": t, "id": s["id"], "from": old, "to": status, "by": "claude"})
            s["status"] = status
            if note is not None:
                s["note"] = note
            s["updated"] = t
            lines.append((s["id"], old))
        return lines

    lines = mutate(fn, "set %s %s" % (spec, status))
    if len(lines) == 1:
        sid, old = lines[0]
        print(("ok %s: %s → %s" % (sid, old, status)) if old != status else ("ok %s: already %s" % (sid, status)))
    else:
        print("ok %d screens → %s (%s)" % (len(lines), status, ", ".join(l[0] for l in lines)))


def cmd_note(args):
    if len(args) < 2:
        raise SystemExit('err usage: plots note <ids> "what\'s happening"')
    note, spec = args[-1], " ".join(args[:-1])

    def fn(data):
        sc = resolve_ids(data, spec)
        for s in sc:
            s["note"] = note
            s["updated"] = now()
        return [s["id"] for s in sc]

    ids = mutate(fn, "note %s" % spec)
    print("ok note on %s" % ", ".join(ids))


_DETAIL_KEYS = {"review", "be", "fe", "report", "findings", "checks", "p1", "p2", "p3",
                "batch", "order", "name", "menu", "covers", "note"}


def cmd_detail(args):
    if len(args) < 2:
        raise SystemExit("err usage: plots detail <id> key=value ...")
    sid, pairs = args[0], args[1:]

    def fn(data):
        s = find_screen(data, sid)
        changed = []
        for p in pairs:
            if "=" not in p:
                raise SystemExit("err expected key=value, got %r" % p)
            k, v = p.split("=", 1)
            k = k.strip().lower()
            if k not in _DETAIL_KEYS:
                raise SystemExit("err unknown key %r (use: %s)" % (k, " ".join(sorted(_DETAIL_KEYS))))
            if k in ("p1", "p2", "p3", "order"):
                s[k] = int(v)
            elif k == "checks":
                s[k] = checks_list(v)
            elif k == "covers":
                s[k] = [x.lower() for x in split_list(v)]
            elif k == "menu" and v not in data["menus"]:
                data["menus"].append(v)
                s[k] = v
            else:
                s[k] = clean(v)
            changed.append(k)
        s["updated"] = now()
        return s["id"], changed

    sid2, changed = mutate(fn, "detail %s" % sid)
    print("ok %s: %s" % (sid2, ", ".join(changed)))


def cmd_log(args):
    n = _opt(args, "-n", "--last")
    if not args:
        entries = load().get("log", [])[-int(n or 10):][::-1]
        if JSON_OUT:
            return _emit(entries)
        for e in entries:
            print("%s  %s" % (e["t"], e["text"]))
        if not entries:
            print("(log is empty)")
        return
    text = " ".join(args)

    def fn(data):
        data.setdefault("log", []).append({"t": now(), "text": text})

    mutate(fn, "log")
    print("ok logged")


def cmd_decision(args):
    if not args:
        raise SystemExit("err usage: plots decision add \"topic\" | plots decision <n> [status] [-d text]")
    text = _opt(args, "-d", "--decision")
    sflag = _opt(args, "-s", "--status")
    scr = _opt(args, "--screens")
    num = _opt(args, "-n", "--number")
    if args[0] == "add":
        topic = " ".join(args[1:]).strip()
        if not topic:
            raise SystemExit('err usage: plots decision add "topic"')
        status = parse_dstatus(sflag or "ask")

        def fn(data):
            ds = data.setdefault("decisions", [])
            n = int(num) if num else (max([d["n"] for d in ds] or [0]) + 1)
            if any(d["n"] == n for d in ds):
                raise SystemExit("err decision #%d exists" % n)
            ds.append({"n": n, "topic": topic, "status": status, "decision": text or "",
                       "screens": [s["id"] for s in resolve_ids(data, scr)] if scr else [],
                       "myNotes": ""})
            return n

        n = mutate(fn, "decision add")
        print("ok decision #%d added (%s)" % (n, status))
        return
    status = parse_dstatus(sflag or args[1]) if (sflag or len(args) > 1) else None
    if status is None and text is None and not scr:
        # nothing to change: show the decision instead of writing
        data = load()
        return _print_decision(data, find_decision(data, args[0]))

    def fn(data):
        d = find_decision(data, args[0])
        old = d["status"]
        if status:
            d["status"] = status
        if text is not None:
            d["decision"] = text
        if scr:
            d["screens"] = [s["id"] for s in resolve_ids(data, scr)]
        return d["n"], old, d["status"]

    n, old, new = mutate(fn, "decision %s" % args[0])
    print("ok decision #%d: %s" % (n, ("%s → %s" % (old, new)) if old != new else "updated"))


def _print_decision(data: dict, d: dict) -> None:
    names = {s["id"]: s["name"] for s in data["screens"]}
    if JSON_OUT:
        return _emit(dict(d, open=d["status"] in D_OPEN,
                          screen_names={i: names.get(i, "") for i in d.get("screens", [])}))
    print("#%d %s · %s" % (d["n"], d["topic"], d["status"]))
    if d.get("decision"):
        print(("Proposal: " if d["status"] in D_OPEN else "Decision: ") + d["decision"])
    if d.get("screens"):
        print("Screens: " + ", ".join("%s %s" % (i, names.get(i, "")) for i in d["screens"]))
    if d.get("myNotes"):
        print("Your answer: " + d["myNotes"])


def cmd_decisions(args):
    data = load()
    which = (args[0].lower() if args else "all")
    if which not in ("open", "settled", "all"):
        raise SystemExit("err usage: plots decisions [open|settled|all]")
    ds = sorted(data.get("decisions", []), key=lambda d: (d["status"] not in D_OPEN, d["n"]))
    if which == "open":
        ds = [d for d in ds if d["status"] in D_OPEN]
    elif which == "settled":
        ds = [d for d in ds if d["status"] not in D_OPEN]
    if JSON_OUT:
        return _emit(ds)
    for d in ds:
        extra = (" — " + d["decision"]) if d.get("decision") else ""
        mine = (" · You: " + d["myNotes"]) if d.get("myNotes") else ""
        print("#%-3d %-15s %s%s%s" % (d["n"], d["status"], d["topic"], extra, mine))
    if not ds:
        print("(none)")


def cmd_commits(args):
    data = load()
    n = int(args[0]) if args else 10
    cs = data.get("commits", [])[-n:][::-1]
    if JSON_OUT:
        return _emit({"branch": data.get("branch", ""), "commits": cs})
    print("Common branch: %s" % (data.get("branch") or "—"))
    for c in cs:
        print("%s %s %s  %s" % (c["date"], c["repo"], c["hash"], c["msg"]))


def cmd_activity(args):
    data = load()
    n = int(args[0]) if args else 15
    items = [dict(e, kind="log") for e in data.get("log", [])]
    items += [dict(e, kind="status") for e in data.get("events", [])]
    items.sort(key=lambda e: e.get("t", ""), reverse=True)
    items = items[:n]
    if JSON_OUT:
        return _emit(items)
    names = {s["id"]: s["name"] for s in data["screens"]}
    for e in items:
        if e["kind"] == "log":
            print("%s  log     %s" % (e["t"], e["text"]))
        else:
            print("%s  status  %s %s → %s (%s)" % (e["t"], e["id"], names.get(e["id"], ""), e["to"], e.get("by", "")))


def cmd_commit(args):
    branch = _opt(args, "--branch", "-b")
    if len(args) < 3:
        raise SystemExit('err usage: plots commit <BE|FE> <hash> "message"')
    repo, h, msg = args[0].upper(), args[1], " ".join(args[2:])

    def fn(data):
        if branch:
            data["branch"] = branch
        data.setdefault("commits", []).append({"repo": repo, "date": today(), "hash": h, "msg": msg})

    mutate(fn, "commit %s" % h)
    print("ok commit %s %s recorded" % (repo, h))


def cmd_inbox(args):
    peek = _flag(args, "--peek")
    data = {}
    if peek:
        data = load()
        items = [i for i in data.get("inbox", []) if not i.get("read")]
    else:
        with Lock():
            data = load()
            items = [dict(i) for i in data.get("inbox", []) if not i.get("read")]
            if items:
                for i in data["inbox"]:
                    i["read"] = True
                _write_json(DATA, data)
    if JSON_OUT:
        return _emit(items)
    if not items:
        print("inbox empty")
        return
    print("%d new from %s:" % (len(items), user_name()))
    status_of = {x["id"]: x["status"] for x in data.get("screens", [])}
    for i in items:
        ref = i.get("ref")
        kind = i.get("kind", "note")
        if kind == "relay":
            where = "note #%s" % i["note"] if i.get("note") else "a note"
            print("[%s] relay from %s's %s (answered by its fork): %s" % (i.get("t", "")[5:], user_name(), where, i.get("text", "")))
            continue
        where = ("#%s" % ref) if kind == "decision" else (ref or ("note #%s" % i["note"] if i.get("note") else "general"))
        # a note on a screen that is being tested is most likely a bug: it goes back to Fixing first
        st = (i.get("st") or status_of.get(ref)) if kind == "note" else None
        extra = (" [it's %s: if this is a bug, `%s set %s fix -m \"…\"` before fixing it]" % (st, PROG, ref)
                 if st in QA else (" [%s]" % st if st else ""))
        print("[%s] %s %s%s: %s" % (i.get("t", "")[5:], where, kind, extra, i.get("text", "")))


def cmd_add(args):
    menu = _opt(args, "--menu")
    batch = _opt(args, "--batch")
    order = _opt(args, "--order")
    if len(args) < 2 or not menu:
        raise SystemExit('err usage: plots add <id> "name" --menu M --batch B [--order N]')
    def fn(data):
        pre = id_prefix(data)
        sid = args[0].lower() if (not pre or args[0].lower().startswith(pre)) else pre + args[0].lower()
        if any(s["id"] == sid for s in data["screens"]):
            raise SystemExit("err %s exists" % sid)
        if menu not in data["menus"]:
            data["menus"].append(menu)
        if batch and batch not in data["batches"]:
            data["batches"].append(batch)
        data["screens"].append({
            "id": sid, "name": " ".join(args[1:]), "menu": menu, "status": "Not started", "note": "",
            "updated": now(), "order": int(order) if order else max([s["order"] for s in data["screens"]] or [0]) + 1,
            "covers": [], "myNotes": "", "batch": batch or "", "p1": 0, "p2": 0, "p3": 0, "review": "",
            "be": "", "fe": "", "checks": [], "findings": "", "report": ""})
        return sid

    sid = mutate(fn, "add %s" % args[0])
    print("ok %s added" % sid)


def cmd_undo(args):
    with Lock():
        snaps = sorted(UNDO_DIR.glob("*.json")) if UNDO_DIR.exists() else []
        if not snaps:
            print("nothing to undo")
            return
        snap = json.loads(snaps[-1].read_text(encoding="utf-8"))
        _write_json(DATA, snap["data"])
        snaps[-1].unlink()
    print("ok undid: %s (%s)" % (snap.get("reason", "?"), snap.get("t", "")))


def cmd_export(args):
    out = Path(args[0]) if args else Path.cwd() / ("progress-%s.xlsx" % today())
    export_xlsx(load(), out)
    print("ok exported %s" % out)


def cmd_import(args):
    if not args:
        raise SystemExit("err usage: plots import <tracker.xlsx> [--force]")
    force = _flag(args, "--force")
    new = import_xlsx(args[0])
    with Lock():
        if DATA.exists():
            if not force:
                old = load()
                # keep the app's own history and inbox across re-imports
                new["events"] = old.get("events", new["events"])
                new["inbox"] = old.get("inbox", [])
            _snapshot(load(), "import")
        _write_json(DATA, new)
    st = stats(new)
    print("ok imported %d screens, %d decisions, %d log lines, %d commits → %s" % (
        st["total"], len(new["decisions"]), len(new["log"]), len(new["commits"]), DATA))


# --------------------------------------------------------------------------- notes → a fork of the working session
#
# A note from the app waits NOTE_DELAY seconds (so it can still be edited or cancelled), then a fork of the
# Claude Code session that works on this workspace answers it: `claude -p --resume <session> --fork-session`.
# The fork starts with everything the working session knows, answers right away even while that session is
# busy, and can pass instructions on to it with `<cli> relay "…"` (they arrive in its inbox). Follow-ups in the
# same thread continue that fork. Notes live next to the data file in <name>.notes.json.

NOTE_DELAY = 8
NOTE_TIMEOUT = 15 * 60
OPEN_STATES = ("scheduled", "queued")
EDITABLE = ("held", "scheduled", "queued", "failed")
CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"


def notes_path(w: dict) -> Path:
    d = Path(w["data"]).expanduser()
    return d.parent / (d.stem + ".notes.json")


def notes_load(w: dict) -> dict:
    try:
        obj = json.loads(notes_path(w).read_text(encoding="utf-8"))
        if not isinstance(obj, dict):
            obj = {}
    except (OSError, ValueError):
        obj = {}
    obj.setdefault("notes", [])
    obj.setdefault("next", max([n.get("id", 0) for n in obj["notes"]] or [0]) + 1)
    return obj


def notes_update(w: dict, fn):
    p = notes_path(w)
    with FileLock(p):
        obj = notes_load(w)
        out = fn(obj)
        _write_json(p, obj)
    return out


def note_find(obj: dict, nid) -> dict:
    try:
        nid = int(str(nid).lstrip("#"))
    except ValueError:
        raise SystemExit("err no note %r" % nid)
    for n in obj["notes"]:
        if n.get("id") == nid:
            return n
    raise SystemExit("err no note #%d" % nid)


NOTES_KEEP = 500


def note_add(w: dict, text: str, delay=None, parent=None, target=None, to=None, local=False, context=None) -> dict:
    """A note, or a message from the Chat (delay 0). With your Claude project, `to` asks for a thread by name, or
    "new" for a new one (none: the project decides; a follow-up goes to its conversation's thread), and `local`
    asks for the work to run on this Mac. `context`: what was open beside the chat when it was sent (screen ids, or
    "#12" for a decision); Claude gets it with the message."""
    text = str(text or "").strip()[:8000]
    if not text:
        raise SystemExit("err empty note")

    def fn(obj):
        if parent is not None:
            note_find(obj, parent)
        n = {"id": obj["next"], "t": now(), "text": text, "state": "scheduled",
             "sendAt": time.time() + (NOTE_DELAY if delay is None else max(0, float(delay))),
             "parent": int(parent) if parent is not None else None, "target": target or None, "seen": True}
        if to:
            n["to"] = str(to).strip()[:120]
        if local:
            n["local"] = True
        refs = [str(x).strip()[:40] for x in (context or []) if str(x).strip()][:6]
        if refs:
            n["context"] = refs
        obj["next"] += 1
        obj["notes"].append(n)
        del obj["notes"][:-NOTES_KEEP]
        return n
    return notes_update(w, fn)


def note_root(obj: dict, n: dict) -> dict:
    """The first note of n's conversation (a conversation is a note and the follow-ups under it)."""
    by = {x.get("id"): x for x in obj["notes"]}
    r, k = n, 0
    while r.get("parent") and by.get(r["parent"]) and k < 200:
        r, k = by[r["parent"]], k + 1
    return r


def note_change(w: dict, nid, action: str, text=None) -> dict:
    """hold | edit | send | cancel | retry | seen, and for the note's whole conversation: title | archive | unarchive"""
    killed = []

    def fn(obj):
        n = note_find(obj, nid)
        st = n.get("state")
        if action == "hold":
            if st in ("scheduled", "queued"):
                n["state"] = "held"
        elif action == "edit":
            if st not in EDITABLE:
                raise SystemExit("err note #%d was already sent" % n["id"])
            if text is not None:
                t = str(text).strip()[:8000]
                if not t:
                    raise SystemExit("err empty note")
                if t != n["text"]:
                    n["text"], n["edited"] = t, now()
            n["state"], n["sendAt"] = "scheduled", time.time() + NOTE_DELAY
            n.pop("error", None)
        elif action == "send":
            if st in EDITABLE:
                n["state"], n["sendAt"] = "queued", time.time()
                n.pop("error", None)
        elif action == "retry":
            if st in ("failed", "cancelled"):
                n["state"], n["sendAt"] = "queued", time.time()
                n.pop("error", None)
        elif action == "cancel":
            if st == "sending":
                killed.append(n.get("pid"))
            if st in EDITABLE or st == "sending":
                n["state"] = "cancelled"
        elif action == "seen":
            n["seen"] = True
        elif action == "title":
            r = note_root(obj, n)
            t = re.sub(r"\s+", " ", str(text or "")).strip()[:120]
            if t:
                r["title"] = t
            else:
                r.pop("title", None)
            return dict(r)
        elif action in ("archive", "unarchive"):
            r = note_root(obj, n)
            if action == "archive":
                r["archived"] = now()
            else:
                r.pop("archived", None)
            return dict(r)
        else:
            raise SystemExit("err unknown note action %r" % action)
        return dict(n)
    out = notes_update(w, fn)
    for pid in killed:
        _kill_group(pid)
    return out


def notes_seen(w: dict, ids=None) -> int:
    want = None if ids is None else {int(x) for x in ids if str(x).lstrip("#").isdigit()}

    def fn(obj):
        k = 0
        for n in obj["notes"]:
            if not n.get("seen") and (want is None or n.get("id") in want):
                n["seen"] = True
                k += 1
        return k
    return notes_update(w, fn) if notes_path(w).exists() else 0


def note_forward(w: dict, nid) -> dict:
    """Put a note (and its answer) in the working session's inbox."""
    n = note_find(notes_load(w), nid)
    text = n["text"] + (("\n(The note's fork answered: %s)" % n["reply"]["text"]) if n.get("reply") else "")
    with ws_context(w):
        mutate(lambda d: d.setdefault("inbox", []).append(
            {"t": now(), "kind": "note", "ref": None, "text": text, "read": False, "note": n["id"]}), "app: note %d" % n["id"])

    def fn(obj):
        x = note_find(obj, nid)
        x["forwarded"] = now()
        return dict(x)
    return notes_update(w, fn)


def _kill_group(pid) -> None:
    """Stop a note's Claude run: TERM, then KILL a moment later if it's stuck (for example in a system call that
    waits for a macOS permission prompt)."""
    if not pid:
        return
    pid = int(pid)

    def send(sig):
        try:
            os.killpg(pid, sig)
        except OSError:
            try:
                os.kill(pid, sig)
            except OSError:
                pass
    send(signal.SIGTERM)

    def later():
        time.sleep(3)
        try:
            os.kill(pid, 0)
        except OSError:
            return
        send(signal.SIGKILL)
    threading.Thread(target=later, daemon=True).start()


# ---- Claude Code sessions (~/.claude/projects/<folder>/<session>.jsonl)

def _enc(path) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def _read_part(f: Path, n: int, tail: bool) -> str:
    try:
        with open(f, "rb") as fh:
            if tail:
                fh.seek(0, 2)
                size = fh.tell()
                fh.seek(max(0, size - n))
            return fh.read(n).decode("utf-8", "ignore")
    except OSError:
        return ""


_META_CACHE = {}


def _session_meta(f: Path, mtime: float) -> dict:
    key = (str(f), mtime)
    if key in _META_CACHE:
        return _META_CACHE[key]
    tail = _read_part(f, 400000, True)
    cwd = model = title = None
    for line in reversed(tail.splitlines()):
        if not line.startswith("{"):
            continue
        try:
            o = json.loads(line)
        except ValueError:
            continue
        cwd = cwd or o.get("cwd")
        if not model and o.get("type") == "assistant":
            m = (o.get("message") or {}).get("model")
            if m and not m.startswith("<"):
                model = m
        if not title:
            title = o.get("customTitle") or o.get("aiTitle") or (o.get("summary") if o.get("type") == "summary" else None)
        if cwd and model and title:
            break
    if not title:
        for line in _read_part(f, 200000, False).splitlines():
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if o.get("type") != "user" or o.get("isMeta") or o.get("isSidechain"):
                continue
            c = (o.get("message") or {}).get("content")
            if isinstance(c, list):
                c = next((b.get("text") for b in c if isinstance(b, dict) and b.get("type") == "text"), None)
            if isinstance(c, str) and c.strip() and not c.lstrip().startswith(("<", "[Note from", "Caveat:")):
                title = re.sub(r"\s+", " ", c.strip())[:90]
                break
    meta = {"cwd": cwd, "model": model, "title": title or "Untitled session", "tail": tail}
    if len(_META_CACHE) > 400:
        _META_CACHE.clear()
    _META_CACHE[key] = meta
    return meta


def _uses_tracker(tail: str, w: dict) -> bool:
    words = {w.get("cli") or "plots"} | {m.strip() for m in (w.get("markers") or []) if m.strip()}
    for word in words:
        if re.search(r'"command":\s*"(?:(?:[^"\\]|\\.){0,400}?[\s;&|(])?' + re.escape(word) + r'(?:\s|\\n|\\"|")', tail):
            return True
    return bool(w.get("data") and w["data"] in tail)


def _registered_session(w: dict):
    try:
        reg = json.loads((HOME / "sessions" / ("%s.json" % w["id"])).read_text(encoding="utf-8"))
        return reg.get("id")
    except (OSError, ValueError):
        return None


def list_sessions(w: dict, limit: int = 8) -> list:
    """Recent Claude Code sessions that work on this workspace, newest first (forks made for notes left out)."""
    if not CLAUDE_PROJECTS.is_dir():
        return []
    encs = [_enc(r) for r in _roots(w)]
    forks = {(n.get("fork") or {}).get("session") for n in notes_load(w)["notes"]}
    hinted = _registered_session(w)
    files = []
    cutoff = time.time() - 21 * 86400
    for d in CLAUDE_PROJECTS.iterdir():
        if not d.is_dir():
            continue
        in_root = any(d.name == e or d.name.startswith(e + "-") for e in encs)
        for f in d.glob("*.jsonl"):
            try:
                m = f.stat().st_mtime
            except OSError:
                continue
            if m >= cutoff and f.stem not in forks:
                files.append((m, f, in_root))
    files.sort(key=lambda x: x[0], reverse=True)
    out = []
    for m, f, in_root in files[:80]:
        meta = _session_meta(f, m)
        if ("Plots note " in meta["tail"][-6000:] or "Plots · note" in meta["tail"][-6000:]) and f.stem != hinted:
            continue
        uses = f.stem == hinted or _uses_tracker(meta["tail"], w)
        if not (in_root or uses):
            continue
        out.append({"id": f.stem, "title": meta["title"], "cwd": meta["cwd"], "model": meta["model"],
                    "active": m, "ago": _ago(m), "uses": uses, "hinted": f.stem == hinted})
        if len(out) >= limit:
            break
    out.sort(key=lambda s: (not s["hinted"], not s["uses"], -s["active"]))
    return out


def _ago(t: float) -> str:
    s = max(0, time.time() - t)
    if s < 90:
        return "just now"
    if s < 3600:
        return "%d min ago" % (s // 60)
    if s < 86400:
        return "%d h ago" % (s // 3600)
    return "%d d ago" % (s // 86400)


def claude_bin():
    c = os.environ.get("PLOTS_CLAUDE")
    if c and os.access(c, os.X_OK):
        return c
    h = Path.home()
    cands = [h / ".local/bin/claude", h / ".claude/local/claude", Path("/opt/homebrew/bin/claude"),
             Path("/usr/local/bin/claude")] + sorted(h.glob(".nvm/versions/node/*/bin/claude"), reverse=True)
    for c in cands:
        if c.exists() and os.access(str(c), os.X_OK):
            return str(c)
    return shutil.which("claude")


_LOGIN_PATH = None


def login_path() -> str:
    """The PATH of the user's login shell, so a fork finds the same commands as in Terminal."""
    global _LOGIN_PATH
    if _LOGIN_PATH is None:
        extra = [str(Path.home() / ".local/bin"), "/opt/homebrew/bin", "/usr/local/bin", str(ROOT)]
        p = ""
        sh = os.environ.get("SHELL") or "/bin/zsh"
        try:
            p = subprocess.run([sh, "-lc", 'printf %s "$PATH"'], capture_output=True, text=True, timeout=6).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
        parts = [x for x in (p or os.environ.get("PATH", "")).split(":") if x]
        for e in extra:
            if e not in parts:
                parts.append(e)
        _LOGIN_PATH = ":".join(parts)
    return _LOGIN_PATH


FORK_FRAME = """[Note from %(user)s · sent from the %(app)s app at %(t)s]
%(text)s

(You are a fork of the working session, opened only to answer this note while that session keeps going. Answer in a few short sentences of plain text; this goes straight to the app. You can read files and run read-only commands and `%(cli)s` commands, but don't edit files here. If %(user)s wants the working session to do or change something, run `%(cli)s relay "<the instruction, in your words>"` so it gets it at its next step, and say that you did.)"""

FOLLOW_FRAME = """[Follow-up from %(user)s · %(t)s]
%(text)s"""

FRESH_ROLE = """You answer notes that %(user)s sends from the %(app)s app about the "%(name)s" workspace, while the \
Claude Code session doing the work may be busy. Use `%(cli)s` (status, ls, show, decisions, activity, inbox --peek) and \
read-only tools to answer in a few short sentences of plain text. Don't edit files. If %(user)s wants the working \
session to do or change something, run `%(cli)s relay "<instruction>"` so it gets it at its next step, and say that you did."""


def note_context_line(w: dict, n: dict) -> str:
    """What was open beside the chat when the message was sent (a screen or a decision), as a line for Claude."""
    refs = [str(x) for x in (n.get("context") or []) if x]
    if not refs:
        return ""
    try:
        data = json.loads(Path(w["data"]).expanduser().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    out = []
    for r in refs:
        if r.startswith("#"):
            x = next((d for d in data.get("decisions", []) if "#%s" % d.get("n") == r), None)
            out.append("decision %s%s" % (r, " (%s, %s)" % (x.get("topic", ""), x.get("status", "")) if x else ""))
        else:
            sc = next((x for x in data.get("screens", []) if x.get("id") == r), None)
            out.append("%s%s" % (r, " (%s, %s)" % (sc.get("name", ""), sc.get("status", "")) if sc else ""))
    return "[Open next to the chat in the app: %s]" % "; ".join(out)


def _note_command(w: dict, n: dict, parent):
    cb = claude_bin()
    if not cb:
        raise RuntimeError("Claude Code isn't installed here (no `claude` command found)")
    cli = w.get("cli") or "plots"
    tools = ["Read", "Grep", "Glob", "Bash(%s:*)" % cli, "Bash(plots:*)", "Bash(git status:*)",
             "Bash(git log:*)", "Bash(git diff:*)", "Bash(git show:*)"]
    allowed = ",".join(dict.fromkeys(tools))
    logdir = RUN_DIR / "notes"
    logdir.mkdir(parents=True, exist_ok=True)
    for old in sorted(logdir.glob("*.log"), key=lambda f: f.stat().st_mtime)[:-30]:
        try:
            old.unlink()
        except OSError:
            pass
    # Read-only without touching the tool list: a fork that keeps the working session's tools and system prompt
    # reuses its prompt cache, so answering a note about a long session costs a fraction of re-reading it.
    # Edits are refused by a PreToolUse hook and by the default permission mode with nobody to approve them.
    guard = {"hooks": {"PreToolUse": [{"matcher": "Edit|Write|MultiEdit|NotebookEdit", "hooks": [{
        "type": "command",
        "command": "echo 'This is a read-only fork answering a Plots note: do not edit files; pass the change on "
                   "with `%s relay \"...\"` instead.' >&2; exit 2" % cli}]}]}}
    argv = [cb, "-p", "--allowedTools", allowed, "--settings", json.dumps(guard),
            "--permission-mode", "default", "--permission-prompts", "none",
            "--max-budget-usd", str(w.get("budget") or 3), "-n", "Plots note %d" % n["id"],
            "--debug-file", str(logdir / ("%s-%d.log" % (w["id"], n["id"])))]
    if w.get("effort"):
        argv += ["--effort", str(w["effort"])]
    when = dt.datetime.now().strftime("%H:%M")
    text = n["text"]
    cl = note_context_line(w, n)
    if cl:
        text = text + "\n\n" + cl
    fork = dict((parent or {}).get("fork") or {})
    if parent and fork.get("session"):
        argv += ["--resume", fork["session"]]
        prompt = FOLLOW_FRAME % {"t": when, "text": text, "user": user_name()}
        info = dict(fork, followUp=True)
    else:
        sess = None
        if n.get("target") != "new":
            ss = list_sessions(w, 12)
            sess = next((x for x in ss if x["id"] == n.get("target")), None) or (ss[0] if ss else None)
        if sess:
            argv += ["--resume", sess["id"], "--fork-session"]
            # the fork keeps Claude Code's own model choice (the user's default, with its context size, as the
            # working session most likely has); a workspace can still pin one with `ws set <id> model=…`
            if w.get("model"):
                argv += ["--model", w["model"]]
            prompt = FORK_FRAME % {"app": APP_NAME, "t": when, "text": text, "cli": cli, "user": user_name()}
            info = {"from": sess["id"], "fromTitle": sess["title"], "cwd": sess.get("cwd") or w.get("root"),
                    "model": sess.get("model")}
        else:
            sid = str(uuid.uuid4())
            argv += ["--strict-mcp-config", "--disallowedTools", "Edit,Write,NotebookEdit",
                     "--session-id", sid, "--append-system-prompt",
                     FRESH_ROLE % {"app": APP_NAME, "name": w.get("name"), "cli": cli, "user": user_name()}]
            prompt = text
            info = {"from": None, "fromTitle": "A new session", "session": sid,
                    "cwd": w.get("root") or str(Path(w["data"]).expanduser().parent)}
    cwd = info.get("cwd")
    # don't look inside a macOS-protected folder from the server (it would wait for a permission prompt)
    if not cwd or (not _protected(cwd) and not Path(cwd).is_dir()):
        root = w.get("root")
        cwd = root if root and (_protected(root) or Path(root).is_dir()) else str(Path.home())
        info["cwd"] = cwd
    argv += ["--output-format", "json", prompt]
    return argv, cwd, info


STALL_HINT = ("Still starting. If macOS asks whether Plots may access a folder (Desktop or Documents), choose Allow: "
              "Claude Code reads your project and skills there.")


def _protected(path) -> bool:
    home = str(Path.home())
    return any(str(path) == "%s/%s" % (home, n) or str(path).startswith("%s/%s/" % (home, n)) for n in PROTECTED)


def _startup_stalled(dbg: Path) -> bool:
    """The note's Claude run hasn't got past loading its settings and skills (it logs much more once it runs)."""
    try:
        size = dbg.stat().st_size
        tail = _read_part(dbg, 600, True)
    except OSError:
        return True          # not even started logging: waiting before Claude Code could start
    return size < 12000 and ("Loading skills" in tail or "setup()" in tail or "Loading MCP" in tail)


PROTECTED = ("Desktop", "Documents", "Downloads")


def protected_folders(w: dict, sessions: list) -> list:
    """The macOS-protected folders a note's fork will read (Plots needs permission for them)."""
    home = Path.home()
    paths = [w.get("root"), w.get("data")] + [x.get("cwd") for x in sessions]
    skills = home / ".claude" / "skills"
    if skills.is_dir():
        for f in skills.iterdir():
            try:
                if f.is_symlink():
                    # read the link only: following it would touch the protected folder from the server itself
                    t = os.readlink(str(f))
                    paths.append(os.path.normpath(t if os.path.isabs(t) else os.path.join(str(skills), t)))
            except OSError:
                pass
    out = set()
    for p in paths:
        if not p:
            continue
        for name in PROTECTED:
            root = str(home / name)
            if str(p) == root or str(p).startswith(root + "/"):
                out.add(root)
    return sorted(out)


def _last_json(text: str):
    for line in reversed((text or "").strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                continue
    try:
        return json.loads(text)
    except ValueError:
        return None


# ---- notes → your Claude project (workspace setting notes=project)
#
# Instead of forking a local session, a due note waits for the bridge: a Claude Code session on this Mac that a
# Claude project thread started (Remote Control). It runs `plots bridge watch`, hands each note to the project,
# which routes it to the thread that owns the work (or starts one). That thread answers with
# `<cli> notes reply <id> "…"`, and the answer shows in the app like a fork's. Follow-ups go to the same thread.
# The watch writes a heartbeat on every pass. Without a fresh one the bridge counts as gone: the notes no thread
# claimed go back to the queue and a fork answers them, as with notes=fork, so no note waits on a bridge that stopped.

BRIDGE_FILE = RUN_DIR / "bridge.json"
BRIDGE_STALE = 90          # seconds since the watch's last heartbeat before the bridge counts as gone


def bridge_alive() -> bool:
    try:
        t = float(json.loads(BRIDGE_FILE.read_text(encoding="utf-8")).get("t") or 0)
    except (OSError, ValueError, AttributeError, TypeError):
        return False
    return abs(time.time() - t) <= BRIDGE_STALE


def _unclaimed_handoff(n: dict) -> bool:
    fk = n.get("fork") or {}
    return n.get("state") == "sending" and bool(fk.get("project")) and not fk.get("claimed")


def project_handoff(obj):
    by = {n.get("id"): n for n in obj["notes"]}
    for n in obj["notes"]:
        if n.get("state") in OPEN_STATES and n.get("sendAt", 0) <= time.time():
            up = (by.get(n.get("parent")) or {}).get("fork") or {}
            ask = n.get("to") or None                       # the thread the user picked, or "new"
            to = None if ask == "new" else (ask or up.get("to"))
            n["state"], n["startedAt"] = "sending", time.time()
            n["fork"] = {"project": True, "followUp": bool(n.get("parent")), "to": to, "ask": ask,
                         "fromTitle": "Claude project"}
            n.pop("error", None)


def project_putback(obj) -> int:
    """The bridge is gone: what it was handed and no thread claimed goes back to the queue (a fork answers it)."""
    back = [n for n in obj["notes"] if _unclaimed_handoff(n)]
    for n in back:
        n["state"], n["sendAt"] = "queued", time.time()
        n.pop("fork", None)
    return len(back)


def _project_note(w: dict, obj: dict, n: dict) -> dict:
    by = {x.get("id"): x for x in obj["notes"]}
    chain, r = [], by.get(n.get("parent"))
    while r and len(chain) < 20:
        chain.insert(0, {"id": r["id"], "text": r.get("text", ""), "reply": (r.get("reply") or {}).get("text")})
        r = by.get(r.get("parent"))
    fk = n.get("fork") or {}
    root = note_root(obj, n)
    return {"ws": w["id"], "wsName": w.get("name"), "cli": w.get("cli") or "plots", "root": w.get("root"),
            "id": n["id"], "t": n.get("t"), "text": n.get("text", ""), "parent": n.get("parent"),
            "conversation": root.get("id"), "title": root.get("title"),
            "context": n.get("context") or [], "contextLine": note_context_line(w, n),
            "to": fk.get("to"), "ask": fk.get("ask"), "local": bool(n.get("local")),
            "claimed": bool(fk.get("claimed")), "earlier": chain}


def project_pending(w: dict, unclaimed_only=False) -> list:
    if w.get("notes") != "project" or not notes_path(w).exists():
        return []
    obj = notes_load(w)
    out = [_project_note(w, obj, n) for n in obj["notes"]
           if n.get("state") == "sending" and (n.get("fork") or {}).get("project")]
    return [x for x in out if not (unclaimed_only and x["claimed"])]


THREAD_STATES = ("working", "waiting", "review", "answered", "idle", "failed")
THREAD_WHERE = {"mac": "mac", "local": "mac", "computer": "mac", "here": "mac", "cloud": "cloud"}


def _thread_info(fk: dict, state=None, where=None, progress=None, url=None) -> None:
    th = dict(fk.get("thread") or {})
    if state is not None:
        st = str(state).strip().lower()
        if st not in THREAD_STATES:
            raise SystemExit("err thread state is one of: %s" % " ".join(THREAD_STATES))
        th["state"] = st
    if where is not None:
        wh = THREAD_WHERE.get(str(where).strip().lower())
        if not wh:
            raise SystemExit("err where is mac or cloud")
        th["where"] = wh
    if progress is not None:
        pr = re.sub(r"\s+", " ", str(progress)).strip()[:300]
        if pr:
            th["progress"] = pr
        else:
            th.pop("progress", None)
    if url is not None:
        u = str(url).strip()
        if u and not re.match(r"^https://", u):
            raise SystemExit("err the thread's link starts with https://")
        if u:
            th["url"] = u[:500]
        else:
            th.pop("url", None)
    if th:
        th["t"] = now()
        fk["thread"] = th


def project_claim(w: dict, nid, to=None, where=None, url=None) -> dict:
    def fn(obj):
        n = note_find(obj, nid)
        if n.get("state") != "sending" or not (n.get("fork") or {}).get("project"):
            raise SystemExit("err note #%d isn't waiting for your Claude project (it's %s)" % (n["id"], n.get("state")))
        n["fork"]["claimed"] = now()
        if to:
            n["fork"]["to"] = str(to)[:120]
        _thread_info(n["fork"], state="working", where=where, url=url)
        return dict(n)
    return notes_update(w, fn)


def project_thread(w: dict, nid, to=None, state=None, where=None, progress=None, url=None) -> dict:
    """The thread with a message reports on it: its state (working, waiting on you for an approval or an answer,
    a pull request ready for review, answered, idle, failed), where it runs, a line on what it's doing now, its link."""
    def fn(obj):
        n = note_find(obj, nid)
        if not (n.get("fork") or {}).get("project"):
            raise SystemExit("err note #%d isn't with your Claude project" % n["id"])
        if to:
            n["fork"]["to"] = str(to)[:120]
        _thread_info(n["fork"], state=state, where=where, progress=progress, url=url)
        return dict(n)
    return notes_update(w, fn)


def project_reply(w: dict, nid, text: str) -> dict:
    text = str(text or "").strip()[:8000]
    if not text:
        raise SystemExit("err empty answer")

    def fn(obj):
        n = note_find(obj, nid)
        if n.get("state") != "sending" or not (n.get("fork") or {}).get("project"):
            raise SystemExit("err note #%d isn't waiting for an answer (it's %s)" % (n["id"], n.get("state")))
        n["state"], n["seen"] = "answered", False
        n["reply"] = {"t": now(), "text": text, "ms": int((time.time() - n.get("startedAt", time.time())) * 1000)}
        n.pop("hint", None)
        th = (n["fork"].get("thread") or {})
        if th and th.get("state") in ("working", "waiting"):
            _thread_info(n["fork"], state="answered", progress="")
        return dict(n)
    return notes_update(w, fn)


def project_fail(w: dict, nid, why: str) -> dict:
    def fn(obj):
        n = note_find(obj, nid)
        if n.get("state") == "sending":
            n["state"], n["error"], n["seen"] = "failed", (str(why or "").strip() or "Your Claude project couldn't answer it.")[:1200], False
            if (n.get("fork") or {}).get("thread"):
                _thread_info(n["fork"], state="failed", progress="")
        return dict(n)
    return notes_update(w, fn)


class NoteRunner(threading.Thread):
    """Sends due notes, one at a time per workspace."""

    def __init__(self):
        super().__init__(daemon=True, name="notes")
        self.busy = set()

    def run(self):
        for w in reg_load()["workspaces"]:
            if notes_path(w).exists():
                try:
                    notes_update(w, self._recover)
                except Exception as e:  # noqa: BLE001
                    _srv_log("notes recover %s: %s" % (w.get("id"), e))
        while True:
            try:
                self.tick()
            except Exception as e:  # noqa: BLE001 - keep the runner alive
                _srv_log("notes tick: %s" % e)
            time.sleep(0.5)

    @staticmethod
    def _recover(obj):
        for n in obj["notes"]:
            if n.get("state") == "sending" and not (n.get("fork") or {}).get("project"):
                n["state"], n["error"] = "failed", "Interrupted: the app's server restarted. Press Retry to send it again."

    def tick(self):
        for w in reg_load()["workspaces"]:
            if w["id"] in self.busy or not notes_path(w).exists():
                continue
            obj = notes_load(w)
            if w.get("notes") == "project":
                if bridge_alive():
                    if any(n.get("state") in OPEN_STATES and n.get("sendAt", 0) <= time.time() for n in obj["notes"]):
                        notes_update(w, project_handoff)
                    continue
                if any(_unclaimed_handoff(n) for n in obj["notes"]):
                    k = notes_update(w, project_putback)
                    _srv_log("notes %s: the bridge stopped (no heartbeat in %ds), %d note(s) go to a fork"
                             % (w["id"], BRIDGE_STALE, k))
                    obj = notes_load(w)
            if any(n.get("state") == "sending" and not (n.get("fork") or {}).get("project") for n in obj["notes"]):
                continue
            due = [n for n in obj["notes"] if n.get("state") in OPEN_STATES and n.get("sendAt", 0) <= time.time()]
            if not due:
                continue
            nid = min(due, key=lambda n: n["id"])["id"]

            def claim(o, nid=nid):
                x = note_find(o, nid)
                if x.get("state") not in OPEN_STATES:
                    return False
                x["state"], x["startedAt"] = "sending", time.time()
                return True
            if notes_update(w, claim):
                self.busy.add(w["id"])
                threading.Thread(target=self.send, args=(w, nid), daemon=True).start()

    def send(self, w, nid):
        def fail(msg):
            def fn(o):
                x = note_find(o, nid)
                if x.get("state") == "sending":
                    x["state"], x["error"], x["seen"] = "failed", msg, False
            notes_update(w, fn)
        try:
            if os.environ.get("PLOTS_NO_FORKS"):      # the demo: Chat never starts a Claude Code session
                return fail("Chat forks are off here (PLOTS_NO_FORKS is set)")
            obj = notes_load(w)
            n = note_find(obj, nid)
            parent = note_find(obj, n["parent"]) if n.get("parent") else None
            argv, cwd, info = _note_command(w, n, parent)
            env = dict(os.environ)
            for k in list(env):
                if k == "CLAUDECODE" or k.startswith("CLAUDE_CODE_"):
                    env.pop(k)
            env.update({"PATH": login_path(), "PLOTS_WS": w["id"], "PLOTS_NOTE": str(nid)})
            # `cd` inside the child: if macOS holds it at a permission prompt, the server keeps going
            proc = subprocess.Popen(["/bin/sh", "-c", 'cd "$0" && exec "$@"', cwd] + argv, env=env,
                                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    start_new_session=True)

            def started(o):
                x = note_find(o, nid)
                x["pid"], x["fork"] = proc.pid, info
            notes_update(w, started)
            t0 = time.time()
            dbg = Path(argv[argv.index("--debug-file") + 1]) if "--debug-file" in argv else None
            hinted = False
            while True:
                try:
                    out, err = proc.communicate(timeout=4)
                    break
                except subprocess.TimeoutExpired:
                    pass
                waited = time.time() - t0
                if waited > NOTE_TIMEOUT:
                    _kill_group(proc.pid)
                    out, err = proc.communicate()
                    return fail("Claude took longer than %d minutes, so the note was stopped." % (NOTE_TIMEOUT // 60))
                # stuck while starting up: almost always macOS waiting for a folder permission
                if not hinted and waited > 20 and dbg is not None and _startup_stalled(dbg):
                    hinted = True

                    def hint(o):
                        x = note_find(o, nid)
                        if x.get("state") == "sending":
                            x["hint"] = STALL_HINT
                    notes_update(w, hint)
            res = _last_json(out.decode("utf-8", "ignore"))
            errtext = err.decode("utf-8", "ignore").strip()

            def done(o):
                x = note_find(o, nid)
                x.pop("pid", None)
                x.pop("hint", None)
                if x.get("state") != "sending":
                    return
                fk = dict(x.get("fork") or info)
                if res and res.get("session_id"):
                    fk["session"] = res["session_id"]
                x["fork"] = fk
                if res and not res.get("is_error") and res.get("result") is not None:
                    x["state"] = "answered"
                    x["reply"] = {"t": now(), "text": str(res.get("result")).strip(), "cost": res.get("total_cost_usd"),
                                  "turns": res.get("num_turns"), "ms": int((time.time() - t0) * 1000)}
                    x["seen"] = False
                else:
                    msg = (res or {}).get("result") or (res or {}).get("subtype") or errtext[-600:] or \
                        "Claude stopped with exit code %s." % proc.returncode
                    if (res or {}).get("subtype") == "error_max_budget_usd" or "budget" in str(msg).lower():
                        msg = "Stopped at the $%s budget for one note. Raise it with `%s ws set %s budget=5`." % (
                            w.get("budget") or 3, PROG, w["id"])
                    x["state"], x["error"], x["seen"] = "failed", str(msg)[:1200], False
            notes_update(w, done)
        except Exception as e:  # noqa: BLE001
            fail(str(e) or e.__class__.__name__)
        finally:
            self.busy.discard(w["id"])


def note_open(w: dict, nid, where: str = "desktop") -> str:
    """Open a note's fork as a normal Claude Code session (Claude desktop app or Terminal)."""
    n = note_find(notes_load(w), nid)
    fk = n.get("fork") or {}
    sid, cwd = fk.get("session"), fk.get("cwd") or w.get("root") or str(Path.home())
    if not sid:
        raise SystemExit("err note #%d has no session yet" % n["id"])
    cb = claude_bin() or "claude"
    if where == "terminal" and sys.platform == "darwin":
        cmd = "cd %s && %s --resume %s" % (_shq(cwd), _shq(cb), sid)
        subprocess.Popen(["osascript", "-e", 'tell application "Terminal" to do script "%s"' % cmd.replace("\\", "\\\\").replace('"', '\\"'),
                          "-e", 'tell application "Terminal" to activate'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return "terminal"
    env = dict(os.environ, PATH=login_path())
    subprocess.Popen(["/bin/sh", "-c", 'cd "$0" && exec "$@"', cwd, cb, "--resume", sid, "--desktop"], env=env,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    return "desktop"


def _shq(s: str) -> str:
    return "'" + str(s).replace("'", "'\\''") + "'"


def _srv_log(msg: str) -> None:
    try:
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        with open(RUN_DIR / "server.log", "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (now(), msg))
    except OSError:
        pass


# --------------------------------------------------------------------------- code: worktrees and branches
# Read-only git: list commands only, with optional locks off (no index refresh, nothing written into the repos).
# Scans run in the background on demand (the Code card) and are cached for CODE_TTL seconds, so a slow repo or
# a folder waiting on macOS's permission prompt never holds up the page.

GIT_TIMEOUT = 12
CODE_TTL = 30
_CODE = {}                      # workspace id -> {"t": scanned at, "data": {...}, "busy": bool}
_CODE_LOCK = threading.Lock()
_BRANCH_COUNT = re.compile(r"\s*\(\d+\)\s*$")    # "feature/x (3)": 3 commits on the common branch


def _git(repo, *args, timeout=GIT_TIMEOUT) -> str:
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0", GIT_PAGER="cat", LC_ALL="C")
    p = subprocess.run([shutil.which("git") or "/usr/bin/git", "-C", str(repo), "-c", "core.fsmonitor=false"]
                       + list(args), capture_output=True, timeout=timeout, env=env)
    if p.returncode != 0:
        msg = p.stderr.decode("utf-8", "replace").strip().splitlines()
        raise RuntimeError(msg[-1] if msg else "git %s failed" % args[0])
    return p.stdout.decode("utf-8", "replace")


def _gitdir_of(path: Path):
    """Where a checkout keeps its git data, read from its .git (a worktree's .git file names the folder)."""
    g = Path(path) / ".git"
    try:
        if g.is_file():
            t = g.read_text(encoding="utf-8", errors="replace").strip()
            if t.startswith("gitdir:"):
                d = t[7:].strip()
                return os.path.normpath(d if os.path.isabs(d) else str(Path(path) / d))
        elif g.is_dir():
            return str(g)
    except OSError:
        pass
    return None


def code_repos(w: dict) -> list:
    """The git checkouts a workspace works in: `repos` from its settings, else its root when that is a checkout,
    else the checkouts right inside its root (be/ and fe/, say)."""
    out = []
    for r in w.get("repos") or []:
        p = r.get("path") if isinstance(r, dict) else r
        if p:
            p = str(Path(p).expanduser())
            out.append({"name": (r.get("name") if isinstance(r, dict) else None) or Path(p).name, "path": p})
    if out:
        return out
    root = w.get("root")
    if not root:
        return []
    root = Path(root).expanduser()
    if _gitdir_of(root):
        return [{"name": root.name, "path": str(root)}]
    try:
        kids = sorted(d for d in root.iterdir() if d.is_dir() and not d.name.startswith("."))
    except OSError:
        return []
    for d in kids:
        if _gitdir_of(d):
            out.append({"name": d.name.upper() if len(d.name) <= 3 else d.name, "path": str(d)})
    return out


def _protected_of(path):
    home = str(Path.home())
    for n in PROTECTED:
        root = "%s/%s" % (home, n)
        if path and (str(path) == root or str(path).startswith(root + "/")):
            return n
    return None


def _parse_worktrees(text: str) -> list:
    out, cur = [], None
    for line in text.splitlines():
        if line.startswith("worktree "):
            cur = {"path": line[9:], "head": "", "branch": None, "detached": False, "locked": False,
                   "prunable": False, "bare": False}
            out.append(cur)
        elif cur is None:
            continue
        elif line.startswith("HEAD "):
            cur["sha"], cur["head"] = line[5:], line[5:12]
        elif line.startswith("branch "):
            b = line[7:]
            cur["branch"] = b[11:] if b.startswith("refs/heads/") else b
        elif line == "detached":
            cur["detached"] = True
        elif line == "bare":
            cur["bare"] = True
        elif line.startswith("locked"):
            cur["locked"] = True
        elif line.startswith("prunable"):
            cur["prunable"] = True
    return [x for x in out if not x["bare"]]


_REF_FIELDS = ["%(refname:short)", "%(objectname:short)", "%(committerdate:unix)", "%(worktreepath)",
               "%(upstream:track,nobracket)", "%(subject)"]


def _local_branches(repo, base):
    """Local branches, newest first: head, time, worktree, upstream state, subject, and ahead/behind `base`."""
    fmt = "%00".join(_REF_FIELDS)
    slow = False
    if base:
        try:
            refs = _git(repo, "for-each-ref", "--sort=-committerdate",
                        "--format=" + fmt + "%00%(ahead-behind:refs/heads/" + base + ")", "refs/heads")
        except RuntimeError:              # git before 2.41 has no ahead-behind: count per branch below
            refs, slow = _git(repo, "for-each-ref", "--sort=-committerdate", "--format=" + fmt, "refs/heads"), True
    else:
        refs = _git(repo, "for-each-ref", "--sort=-committerdate", "--format=" + fmt, "refs/heads")
    out = {}
    for line in refs.splitlines():
        f = line.split("\0")
        if len(f) < 6:
            continue
        ab = f[6].split() if len(f) > 6 else []
        out[f[0]] = {"head": f[1], "t": int(f[2] or 0), "wt": f[3] or None, "track": f[4] or "", "subject": f[5],
                     "ahead": int(ab[0]) if len(ab) == 2 else None, "behind": int(ab[1]) if len(ab) == 2 else None}
    if slow:
        for n, b in list(out.items())[:80]:
            try:
                behind, ahead = _git(repo, "rev-list", "--left-right", "--count",
                                     "refs/heads/%s...refs/heads/%s" % (base, n), timeout=5).split()
                b["ahead"], b["behind"] = int(ahead), int(behind)
            except (RuntimeError, ValueError, subprocess.TimeoutExpired):
                pass
    return out


def _screen_for_branch(name: str, by_branch: dict, ids: list):
    if name in by_branch:
        return by_branch[name]
    low = name.lower()
    hits = [i for i in ids if i and i.lower() in low]
    return max(hits, key=len) if hits else None


def code_scan(w: dict) -> dict:
    """Worktrees and branches of the workspace's repositories, with how far each branch is from the common one."""
    try:
        data = json.loads(Path(w["data"]).expanduser().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    base = (data.get("branch") or "").strip()
    screens = data.get("screens") or []
    ids = [s.get("id") for s in screens]
    by_branch = {}
    for s in screens:
        for k in ("be", "fe"):
            b = _BRANCH_COUNT.sub("", s.get(k) or "").strip()
            if b and b != "—":
                by_branch.setdefault(b, s.get("id"))
    # Branches that belong here: the common one, the screens' own, and (in repositories shared with other projects)
    # the ones named after the workspace's id prefix ("abc…"); with no prefix, every local branch.
    filt = (w.get("branchFilter") if "branchFilter" in w else id_prefix_of(w, data)) or ""

    def named(n):
        return n == base or n in by_branch or (filt.lower() in n.lower() if filt else True)

    root = Path(w["root"]).expanduser() if w.get("root") else None
    repos = code_repos(w)
    wts, branches, out_repos = [], {}, []
    for r in repos:
        rinfo = {"name": r["name"], "path": r["path"], "error": None, "base": False,
                 "protected": _protected_of(_gitdir_of(Path(r["path"]))) or _protected_of(r["path"])}
        out_repos.append(rinfo)
        try:
            listed = _parse_worktrees(_git(r["path"], "worktree", "list", "--porcelain"))
            has_base = False
            if base:
                try:
                    _git(r["path"], "rev-parse", "--verify", "--quiet", "refs/heads/" + base)
                    has_base = True
                except RuntimeError:
                    has_base = False
            rinfo["base"] = has_base
            local = _local_branches(r["path"], base if has_base else None)
        except subprocess.TimeoutExpired:
            rinfo["error"] = "timeout"
            continue
        except (OSError, RuntimeError) as e:
            rinfo["error"] = str(e) or "git failed"
            continue
        here_name = Path(r["path"]).name
        for x in listed:
            p = Path(x["path"])
            grouped = p.name == here_name and p.parent != p
            g = p.parent if grouped else p
            b = dict(local.get(x["branch"] or "", {}))
            t = b.get("t")
            if t is None and x.get("sha"):       # detached (or on a branch that is gone): ask about the commit itself
                try:
                    t = int(_git(r["path"], "log", "-1", "--format=%ct", x["sha"], timeout=5).strip() or 0)
                    if has_base:
                        behind, ahead = _git(r["path"], "rev-list", "--left-right", "--count",
                                             "refs/heads/%s...%s" % (base, x["sha"]), timeout=5).split()
                        b.update(ahead=int(ahead), behind=int(behind))
                except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
                    t = t or 0
            here = bool(root) and (p == root or root in p.parents or g == root)
            sib = bool(root) and g.parent == root.parent and g.name.startswith(root.name)
            name_rel = bool(x["branch"]) and named(x["branch"])
            wts.append({"repo": r["name"], "path": str(p), "group": str(g), "groupName": g.name,
                        "grouped": grouped, "branch": x["branch"], "head": x["head"], "t": t or 0,
                        "detached": x["detached"], "locked": x["locked"], "prunable": x["prunable"],
                        "ahead": b.get("ahead"), "behind": b.get("behind"), "here": here,
                        "rel": here or sib or name_rel,
                        "screen": _screen_for_branch(x["branch"], by_branch, ids) if x["branch"] else None})
        rel_paths = {x["path"] for x in wts if x["rel"] and x["repo"] == r["name"]}
        kept = 0
        for name, b in local.items():          # newest first
            if not (named(name) or (b["wt"] and b["wt"] in rel_paths)) or kept >= 80:
                continue
            kept += 1
            e = branches.setdefault(name, {"name": name, "repos": {}, "t": 0, "subject": "", "base": name == base,
                                           "screen": _screen_for_branch(name, by_branch, ids)})
            e["repos"][r["name"]] = {"head": b["head"], "t": b["t"], "ahead": b["ahead"], "behind": b["behind"],
                                     "track": b["track"], "wt": b["wt"]}
            if b["t"] >= e["t"]:
                e["t"], e["subject"] = b["t"], b["subject"]
    bl = sorted(branches.values(), key=lambda e: (not e["base"], -e["t"]))
    return {"ws": w["id"], "base": base, "filter": filt, "repos": out_repos, "worktrees": wts, "branches": bl}


def id_prefix_of(w: dict, data: dict) -> str:
    m = data.get("meta") or {}
    if "idPrefix" in m:
        return m.get("idPrefix") or ""
    return w.get("idPrefix") or ""


def _code_refresh(w: dict) -> None:
    try:
        res = code_scan(w)
    except Exception as e:  # noqa: BLE001 - a scan must never take the server down
        res = {"ws": w["id"], "repos": [], "worktrees": [], "branches": [], "error": str(e)}
    with _CODE_LOCK:
        c = _CODE.setdefault(w["id"], {"t": 0, "data": None, "busy": False})
        c.update(t=time.time(), data=res, busy=False)


def code_state(w: dict, force: bool = False) -> dict:
    """The last scan right away; a new one starts in the background when it is older than CODE_TTL."""
    with _CODE_LOCK:
        c = _CODE.setdefault(w["id"], {"t": 0, "data": None, "busy": False})
        if (force or time.time() - c["t"] > CODE_TTL) and not c["busy"]:
            c["busy"] = True
            threading.Thread(target=_code_refresh, args=(dict(w),), daemon=True).start()
        out = dict(c["data"] or {"ws": w["id"], "repos": [], "worktrees": [], "branches": []})
        out.update(busy=c["busy"], scanned=c["t"] or None)
    return out


def code_sig(w: dict) -> str:
    with _CODE_LOCK:
        c = _CODE.get(w["id"])
        return "%s" % (c["t"] if c else 0)


# --------------------------------------------------------------------------- local app server

_CT = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
       ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
       ".ico": "image/x-icon", ".json": "application/json", ".webmanifest": "application/manifest+json",
       ".woff2": "font/woff2"}


def _sig_of(path: Path) -> str:
    try:
        st = os.stat(path)
        return "%d-%d" % (st.st_mtime_ns, st.st_size)
    except OSError:
        return "missing"


def ws_sig(w: dict) -> str:
    """Changes whenever the workspace's data or its notes change (the page refreshes on it)."""
    return "%s.%s" % (_sig_of(Path(w["data"]).expanduser()), _sig_of(notes_path(w)))


def _data_sig():
    return _sig_of(DATA)


def build_id() -> str:
    """Changes when the engine or the page is updated (an open page reloads itself on it)."""
    return ".".join(_sig_of(p) for p in (ROOT / "plots.py", APP_DIR / "app.js", APP_DIR / "app.css", APP_DIR / "index.html"))


def _req_ws(q: dict) -> dict:
    reg = reg_load()
    key = (q.get("ws") or [None])[0]
    w = ws_find(reg, key) if key else None
    if not w:
        w = ws_find(reg, reg.get("current")) or (reg["workspaces"][0] if reg["workspaces"] else None)
    if not w:
        raise SystemExit("no workspace yet")
    return w


def _note_public(n: dict) -> dict:
    out = {k: v for k, v in n.items() if k not in ("pid",)}
    if n.get("state") == "scheduled":
        out["sendsIn"] = max(0.0, round(n.get("sendAt", 0) - time.time(), 1))
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "plots/%d" % VERSION

    def log_message(self, fmt, *a):  # keep the terminal quiet
        pass

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("localhost", "127.0.0.1", "[::1]")

    def _send(self, code, body=b"", ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False))

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, '{"error":"bad host"}')
        u = urlparse(self.path)
        path, q = u.path, parse_qs(u.query)
        try:
            if path == "/api/ping":
                return self._json({"ok": True, "app": "plots", "version": VERSION, "pid": os.getpid(),
                                   "engine": str(ROOT)})
            if path == "/api/workspaces":
                reg = reg_load()
                return self._json({"current": reg.get("current"),
                                   "workspaces": [ws_public(w) for w in reg["workspaces"]]})
            if path == "/api/events":
                return self._sse(q)
            w = _req_ws(q) if path.startswith("/api/") else None
            if path == "/api/state":
                try:
                    body = Path(w["data"]).expanduser().read_bytes()
                except OSError:
                    return self._json({"error": "no data", "ws": w["id"]}, 404)
                return self._send(200, body, extra={"X-Data-Sig": ws_sig(w), "X-Workspace": w["id"]})
            if path == "/api/notes":
                obj = notes_load(w)
                mode = w.get("notes") or "fork"
                return self._json({"ws": w["id"], "sig": ws_sig(w), "delay": NOTE_DELAY, "mode": mode,
                                   "bridge": bridge_alive() if mode == "project" else None,
                                   "notes": [_note_public(n) for n in obj["notes"]]})
            if path == "/api/sessions":
                ss = list_sessions(w)
                return self._json({"ws": w["id"], "sessions": ss, "claude": bool(claude_bin()),
                                   "protected": protected_folders(w, ss)})
            if path == "/api/code":
                return self._json(code_state(w, force=(q.get("force") or ["0"])[0] == "1"))
            if path.startswith("/api/export"):
                fd, tmp = tempfile.mkstemp(suffix=".xlsx")
                os.close(fd)
                try:
                    with ws_context(w):
                        export_xlsx(load(), tmp)
                    body = Path(tmp).read_bytes()
                finally:
                    os.unlink(tmp)
                name = "%s-progress-%s.xlsx" % (re.sub(r"[^A-Za-z0-9]+", "-", w.get("id", "plots")).upper(), today())
                return self._send(200, body, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                  {"Content-Disposition": 'attachment; filename="%s"' % name})
        except SystemExit as e:
            return self._json({"error": str(e)}, 404)
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        f = (APP_DIR / rel).resolve()
        try:
            f.relative_to(APP_DIR.resolve())
        except ValueError:
            return self._send(404, "not found", "text/plain")
        if not f.is_file():
            return self._send(404, "not found", "text/plain")
        return self._send(200, f.read_bytes(), _CT.get(f.suffix, "application/octet-stream"))

    do_HEAD = do_GET

    def _sse(self, q):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        last, beat, wsig, csig, bsig = None, time.time(), None, None, None
        try:
            while True:
                b = build_id()
                if b != bsig:                                   # the page compares it with the one it loaded with
                    self.wfile.write(("event: build\ndata: %s\n\n" % b).encode())
                    self.wfile.flush()
                    bsig = b
                try:
                    w = _req_ws(q)
                    sig = ws_sig(w)
                    cs = code_sig(w)
                except SystemExit:
                    sig, cs = "none", None
                reg_sig = _sig_of(REGISTRY)
                sent = False
                if reg_sig != wsig and wsig is not None:
                    self.wfile.write(("event: workspaces\ndata: %s\n\n" % reg_sig).encode())
                    sent = True
                if cs != csig and csig is not None:          # a scan of the repositories finished
                    self.wfile.write(("event: code\ndata: %s\n\n" % cs).encode())
                    sent = True
                csig = cs
                if sig != last:
                    self.wfile.write(("event: change\ndata: %s\n\n" % sig).encode())
                    last, sent = sig, True
                if not sent and time.time() - beat > 15:
                    self.wfile.write(b": ping\n\n")
                    sent, beat = True, time.time()
                if sent:
                    self.wfile.flush()
                wsig = reg_sig
                time.sleep(0.35)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def do_POST(self):
        if not self._host_ok() or self.headers.get("X-Plots") != "1":
            return self._json({"error": "forbidden"}, 403)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._json({"error": "bad json"}, 400)
        u = urlparse(self.path)
        path, q = u.path, parse_qs(u.query)
        parts = [x for x in path.split("/") if x]          # api, notes, 12, cancel
        try:
            if path == "/api/workspaces":
                w = ws_add(body.get("name", ""), root=body.get("root"), color=body.get("color"))
                return self._json({"ok": True, "workspace": ws_public(w)})
            if len(parts) >= 3 and parts[1] == "workspaces":
                if len(parts) == 4 and parts[3] == "use":
                    return self._json({"ok": True, "workspace": ws_public(ws_use(parts[2]))})
                kv = {k: v for k, v in body.items() if k in ("name", "color", "root", "budget", "sessionRoots", "model")}
                return self._json({"ok": True, "workspace": ws_public(ws_set(parts[2], **kv))})
            if path == "/api/shutdown":
                threading.Thread(target=lambda: (time.sleep(0.2), os._exit(0)), daemon=True).start()
                return self._json({"ok": True})
            w = _req_ws(q)
            if path.startswith("/api/screen/"):
                with ws_context(w):
                    res = self._post_screen(path.rsplit("/", 1)[1], body)
            elif path.startswith("/api/decision/"):
                with ws_context(w):
                    res = self._post_decision(path.rsplit("/", 1)[1], body)
            elif path == "/api/message":       # older pages: a note, sent the new way
                res = _note_public(note_add(w, body.get("text", ""), delay=0))
            elif path == "/api/notes":
                res = _note_public(note_add(w, body.get("text", ""), delay=body.get("delay"),
                                            parent=body.get("parent"), target=body.get("target"),
                                            to=body.get("to"), local=bool(body.get("local")),
                                            context=body.get("context") if isinstance(body.get("context"), list) else None))
            elif path == "/api/notes/seen":
                res = notes_seen(w, body.get("ids") if isinstance(body.get("ids"), list) else None)
            elif len(parts) == 4 and parts[1] == "notes" and parts[3] in ("hold", "edit", "send", "cancel", "retry", "seen",
                                                                          "title", "archive", "unarchive"):
                res = _note_public(note_change(w, parts[2], parts[3], body.get("text")))
            elif len(parts) == 4 and parts[1] == "notes" and parts[3] == "forward":
                res = _note_public(note_forward(w, parts[2]))
            elif len(parts) == 4 and parts[1] == "notes" and parts[3] == "open":
                res = note_open(w, parts[2], body.get("where") or "desktop")
            else:
                return self._json({"error": "not found"}, 404)
        except SystemExit as e:
            return self._json({"error": re.sub(r"^err ", "", str(e))}, 400)
        return self._json({"ok": True, "result": res})

    @staticmethod
    def _post_screen(sid, body):
        def fn(data):
            s = find_screen(data, sid)
            t = now()
            out = {}
            if "status" in body and body["status"] != s["status"]:
                new = parse_status(body["status"])
                data.setdefault("events", []).append(
                    {"t": t, "id": s["id"], "from": s["status"], "to": new, "by": "user"})
                # moving among Done, Testing, Tested and Merged is the user's own testing: recorded, not an instruction
                if not (s["status"] in FINISHED and new in FINISHED):
                    data.setdefault("inbox", []).append(
                        {"t": t, "kind": "status", "ref": s["id"], "text": "%s → %s" % (s["status"], new),
                         "read": False})
                s["status"], s["updated"] = new, t
                out["status"] = new
            if "myNotes" in body and body["myNotes"] != s["myNotes"]:
                s["myNotes"] = str(body["myNotes"])[:4000]
                if s["myNotes"].strip():
                    data.setdefault("inbox", []).append(
                        {"t": t, "kind": "note", "ref": s["id"], "text": s["myNotes"], "st": s["status"],
                         "read": False})
                out["myNotes"] = True
            return out
        return mutate(fn, "app: screen %s" % sid)

    @staticmethod
    def _post_decision(n, body):
        def fn(data):
            d = find_decision(data, n)
            t = now()
            out = {}
            if "status" in body and body["status"] != d["status"]:
                new = parse_dstatus(body["status"])
                data.setdefault("inbox", []).append(
                    {"t": t, "kind": "decision", "ref": d["n"],
                     "text": "%s → %s%s" % (d["status"], new,
                                           (" · " + body["myNotes"]) if body.get("myNotes") else ""),
                     "read": False})
                d["status"] = new
                out["status"] = new
            if "myNotes" in body and body["myNotes"] != d["myNotes"]:
                d["myNotes"] = str(body["myNotes"])[:4000]
                if "status" not in out and d["myNotes"].strip():
                    data.setdefault("inbox", []).append(
                        {"t": t, "kind": "decision", "ref": d["n"], "text": d["myNotes"], "read": False})
                out["myNotes"] = True
            return out
        return mutate(fn, "app: decision %s" % n)


def _ping(port=PORT):
    """The running server's ping answer, or None."""
    try:
        with urllib.request.urlopen("http://%s:%d/api/ping" % (HOST, port), timeout=0.6) as r:
            return json.loads(r.read() or b"{}") if r.status == 200 else None
    except Exception:
        return None


def _notes_busy() -> bool:
    for w in reg_load().get("workspaces", []):
        try:
            if any(n.get("state") == "sending" and not (n.get("fork") or {}).get("project")
                   for n in notes_load(w)["notes"]):
                return True
        except (OSError, ValueError, KeyError, SystemExit):
            continue
    return False


def _watch_engine(srv) -> None:
    """When plots.py is updated, the server restarts itself in place (the same process, so macOS keeps treating
    it as Plots' for folder permissions, and the app doesn't have to be rebuilt). It waits for a complete file
    and for notes a fork is answering (a note with your Claude project doesn't hold it up)."""
    me = Path(__file__).resolve()
    try:
        base = me.stat().st_mtime_ns
    except OSError:
        return
    while True:
        time.sleep(2)
        try:
            m = me.stat().st_mtime_ns
            if m == base:
                continue
            time.sleep(1)
            if me.stat().st_mtime_ns != m:
                continue                       # still being written
            compile(me.read_text(encoding="utf-8"), str(me), "exec")
        except (OSError, SyntaxError, ValueError):
            continue
        if _notes_busy():
            continue
        _srv_log("engine updated: restarting in place")
        try:
            srv.server_close()
        except OSError:
            pass
        os.execv(sys.executable, [sys.executable] + sys.argv)


def cmd_serve(args):
    port = int(_opt(args, "--port", default=PORT))
    srv = ThreadingHTTPServer((HOST, port), Handler)
    srv.daemon_threads = True
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    (RUN_DIR / "server.pid").write_text(str(os.getpid()))
    for w in reg_load().get("workspaces", []):      # statuses renamed since the data was written
        try:
            with ws_context(w):
                migrate_statuses()
        except SystemExit:
            pass
    NoteRunner().start()
    threading.Thread(target=_watch_engine, args=(srv,), daemon=True).start()
    print("%s → http://localhost:%d  (Ctrl+C to stop)" % (APP_NAME, port), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            if (RUN_DIR / "server.pid").read_text().strip() == str(os.getpid()):
                (RUN_DIR / "server.pid").unlink()
        except OSError:
            pass


def _open_window(url: str) -> None:
    if sys.platform == "darwin":
        if subprocess.run(["open", "-b", BUNDLE_ID], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            return
        for app in ("Google Chrome", "Microsoft Edge", "Brave Browser"):
            if Path("/Applications/%s.app" % app).exists():
                subprocess.Popen(["open", "-na", app, "--args", "--app=%s" % url, "--window-size=1440,960"])
                return
        subprocess.Popen(["open", url])
    else:
        webbrowser.open(url)


def start_server() -> bool:
    """Start the server in the background unless one already answers. Restarts an older one."""
    up = _ping()
    if up and up.get("app") == "plots" and up.get("version", 0) >= VERSION:
        return True
    if up:
        _stop_all()
        for _ in range(30):
            if not _ping():
                break
            time.sleep(0.1)
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    logf = open(RUN_DIR / "server.log", "ab")
    subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "serve"],
                     stdout=logf, stderr=logf, stdin=subprocess.DEVNULL, start_new_session=True)
    for _ in range(60):
        if _ping():
            return True
        time.sleep(0.1)
    return False


def cmd_open(args):
    url = "http://localhost:%d/" % PORT
    ok = start_server()
    if "--no-window" not in args:
        _open_window(url)
    print("ok app at %s" % url if ok else "err the server did not start (see %s)" % (RUN_DIR / "server.log"))


def _stop_all() -> bool:
    stopped = False
    up = _ping()
    if up and up.get("app") == "plots":
        try:
            req = urllib.request.Request("http://%s:%d/api/shutdown" % (HOST, PORT), data=b"{}", method="POST",
                                         headers={"X-Plots": "1", "Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=1).read()
            stopped = True
        except Exception:
            pass
    # this server's pid file
    for pidf in (RUN_DIR / "server.pid",):
        try:
            pid = int(pidf.read_text().strip())
            os.kill(pid, signal.SIGTERM)
            stopped = True
        except (OSError, ValueError):
            pass
        try:
            pidf.unlink()
        except OSError:
            pass
    return stopped


def cmd_stop(args):
    print("ok stopped" if _stop_all() else "not running")


# --------------------------------------------------------------------------- workspaces and notes (CLI)

def cmd_ws(args):
    ws_arg = _opt(args, "--ws")
    sub = args.pop(0) if args else "ls"
    if sub in ("ls", "list"):
        reg = reg_load()
        if JSON_OUT:
            return _emit({"current": reg.get("current"), "workspaces": [ws_public(w) for w in reg["workspaces"]]})
        if not reg["workspaces"]:
            print('no workspaces yet: run `%s init "Name"` in your project folder' % PROG)
        for w in reg["workspaces"]:
            p = ws_public(w)
            print("%s %-14s %-24s %s%s" % ("*" if w["id"] == reg.get("current") else " ", w["id"], w.get("name", ""),
                                            ("%d/%d done · " % (p["done"], p["total"])) if "done" in p else "",
                                            w.get("root") or w["data"]))
        return
    if sub == "add":
        root = _opt(args, "--root")
        data = _opt(args, "--data")
        wid = _opt(args, "--id")
        prefix = _opt(args, "--prefix", default="")
        if not args:
            raise SystemExit('err usage: %s ws add "Name" [--root DIR] [--data FILE] [--id ID]' % PROG)
        w = ws_add(" ".join(args), root=root, data=data, wid=wid, prefix=prefix)
        print("ok workspace %s (%s) · data %s" % (w["id"], w["name"], w["data"]))
        return
    if sub == "use":
        if not args:
            raise SystemExit("err usage: %s ws use <id>" % PROG)
        w = ws_use(args[0])
        print("ok the app shows %s (%s)" % (w["id"], w["name"]))
        return
    if sub == "set":
        if len(args) < 2:
            raise SystemExit("err usage: %s ws set <id> key=value ..." % PROG)
        kv = {}
        for pair in args[1:]:
            if "=" not in pair:
                raise SystemExit("err expected key=value, got %r" % pair)
            k, v = pair.split("=", 1)
            if k in ("sessionRoots", "markers", "repos"):
                v = [x for x in v.split(",") if x]
            elif k == "budget":
                v = float(v)
            kv[k] = v
        w = ws_set(args[0], **kv)
        print("ok %s: %s" % (w["id"], ", ".join(kv)))
        return
    if sub in ("remove", "rm"):
        if not args:
            raise SystemExit("err usage: %s ws remove <id>   (forgets the workspace; its data file stays)" % PROG)

        def fn(reg):
            w = ws_find(reg, args[0])
            if not w:
                raise SystemExit("err no workspace %r" % args[0])
            reg["workspaces"] = [x for x in reg["workspaces"] if x is not w]
            if reg.get("current") == w["id"]:
                reg["current"] = reg["workspaces"][0]["id"] if reg["workspaces"] else None
            return w
        w = reg_update(fn)
        print("ok forgot %s (its data stays at %s)" % (w["id"], w["data"]))
        return
    if sub == "user":
        name = " ".join(args).strip()
        if not name:
            print(user_name())
            return
        reg_update(lambda reg: reg.__setitem__("user", name))
        print("ok the app calls you %s" % name)
        return
    raise SystemExit("err usage: %s ws [ls|add|use|set|remove|user]" % PROG)


def cmd_init(args):
    prefix = _opt(args, "--prefix", default="")
    wid = _opt(args, "--id")
    name = " ".join(args).strip() or Path.cwd().name
    reg = reg_load()
    have = ws_for_path(reg, os.getcwd())
    if have and have.get("root") == str(Path.cwd().resolve()):
        print("ok %s already tracks this folder (%s)" % (have["id"], have["name"]))
        return
    w = ws_add(name, root=os.getcwd(), wid=wid, prefix=prefix)
    print("ok workspace %s (%s) for %s · data %s" % (w["id"], w["name"], w["root"], w["data"]))


def cmd_notes(args):
    sub = args[0] if args else ""
    if sub == "pending":
        res = project_pending(WS)
        if JSON_OUT:
            return _emit(res)
        if WS.get("notes") != "project":
            print("%s answers notes with a fork (notes=fork); `%s ws set %s notes=project` hands them to your Claude project"
                  % (WS["id"], PROG, WS["id"]))
        for x in res:
            print("#%d %s%s%s %s%s" % (x["id"], x["t"] or "", " (follow-up of #%s)" % x["parent"] if x["parent"] else "",
                                       " → %s" % x["to"] if x["to"] else "", x["text"].replace("\n", " ")[:200],
                                       " " + x["contextLine"] if x.get("contextLine") else ""))
        return
    if sub in ("claim", "reply", "fail", "thread", "title"):
        if len(args) < 2 or not args[1].lstrip("#").isdigit():
            raise SystemExit('err usage: %s notes claim <id> [--to "thread"] [--where mac|cloud] [--url U] [--title T] · notes reply <id> "answer" · '
                             'notes fail <id> "why" · notes thread <id> [--state S] [--progress "…"] [--where W] [--url U] · '
                             'notes title <id> "title"' % PROG)
        rest = args[2:]
        if sub == "thread":
            x = project_thread(WS, args[1], to=_opt(rest, "--to"), state=_opt(rest, "--state"), where=_opt(rest, "--where"),
                               progress=_opt(rest, "--progress"), url=_opt(rest, "--url"))
            print("ok note #%d: %s" % (x["id"], ", ".join("%s %s" % kv for kv in sorted((x["fork"].get("thread") or {}).items()) if kv[0] != "t")))
            return
        if sub == "title":
            x = note_change(WS, args[1], "title", " ".join(rest))
            print("ok conversation #%d is called %s" % (x["id"], x.get("title") or "after its first message"))
            return
        if sub == "claim":
            title = _opt(rest, "--title")
            x = project_claim(WS, args[1], _opt(rest, "--to"), where=_opt(rest, "--where"), url=_opt(rest, "--url"))
            if title:
                note_change(WS, args[1], "title", title)
            print("ok note #%d is with %s" % (x["id"], x["fork"].get("to") or "your Claude project"))
        elif sub == "reply":
            x = project_reply(WS, args[1], " ".join(rest))
            print("ok answered note #%d; it shows in the app" % x["id"])
        else:
            x = project_fail(WS, args[1], " ".join(rest))
            print("ok note #%d marked %s" % (x["id"], x["state"]))
        return
    n = int(args[0]) if args and args[0].isdigit() else 10
    obj = notes_load(WS)
    items = obj["notes"][-n:]
    if JSON_OUT:
        return _emit([_note_public(x) for x in items])
    if not items:
        print("no notes yet")
    for x in items:
        print("#%d %s [%s] %s" % (x["id"], x.get("t", ""), x.get("state"), x.get("text", "").replace("\n", " ")[:160]))
        if x.get("reply"):
            print("    → %s" % x["reply"]["text"].replace("\n", " ")[:300])
        if x.get("error"):
            print("    ! %s" % x["error"][:200])


def cmd_bridge(args):
    """The Claude project's bridge on this Mac: `watch` keeps the bridge's heartbeat fresh and prints one JSON line
    per note handed to the project (every workspace with notes=project), `pending` prints the ones not answered
    yet, and `claim`, `reply` and `fail` take the workspace first, so the bridge can answer a note in any of them."""
    usage = ('err usage: %s bridge [pending|watch] · bridge claim <ws> <id> [--to "thread"] [--where mac|cloud] [--url U] [--title T] · '
             'bridge reply <ws> <id> "answer" · bridge fail <ws> <id> "why" · '
             'bridge thread <ws> <id> [--state S] [--progress "…"] [--where W] [--url U] · bridge title <ws> <id> "title"' % PROG)
    sub = args[0] if args else "pending"
    if sub == "pending":
        out = [x for w in reg_load()["workspaces"] for x in project_pending(w)]
        if JSON_OUT:
            return _emit(out)
        for x in out:
            print(json.dumps(x, ensure_ascii=False))
        if not out:
            print("no notes waiting for your Claude project")
        return
    if sub == "watch":
        every = min(float(_opt(args, "--interval", default="2") or 2), BRIDGE_STALE / 3)
        seen = set()
        while True:
            _write_json(BRIDGE_FILE, {"pid": os.getpid(), "t": time.time()})     # read by bridge_alive()
            for w in reg_load()["workspaces"]:
                for x in project_pending(w, unclaimed_only=True):
                    key = (x["ws"], x["id"])
                    if key not in seen:
                        seen.add(key)
                        print(json.dumps(x, ensure_ascii=False), flush=True)
            time.sleep(every)
    if sub in ("claim", "reply", "fail", "thread", "title"):
        if len(args) < 3 or not args[2].lstrip("#").isdigit():
            raise SystemExit(usage)
        w = ws_find(reg_load(), args[1])
        if not w:
            raise SystemExit("err no workspace %r" % args[1])
        rest = args[3:]
        if sub == "thread":
            x = project_thread(w, args[2], to=_opt(rest, "--to"), state=_opt(rest, "--state"), where=_opt(rest, "--where"),
                               progress=_opt(rest, "--progress"), url=_opt(rest, "--url"))
            print("ok note #%d: %s" % (x["id"], ", ".join("%s %s" % kv for kv in sorted((x["fork"].get("thread") or {}).items()) if kv[0] != "t")))
            return
        if sub == "title":
            x = note_change(w, args[2], "title", " ".join(rest))
            print("ok conversation #%d is called %s" % (x["id"], x.get("title") or "after its first message"))
            return
        if sub == "claim":
            title = _opt(rest, "--title")
            x = project_claim(w, args[2], _opt(rest, "--to"), where=_opt(rest, "--where"), url=_opt(rest, "--url"))
            if title:
                note_change(w, args[2], "title", title)
            print("ok note #%d is with %s" % (x["id"], x["fork"].get("to") or "your Claude project"))
        elif sub == "reply":
            x = project_reply(w, args[2], " ".join(rest))
            print("ok answered note #%d; it shows in the app" % x["id"])
        else:
            x = project_fail(w, args[2], " ".join(rest))
            print("ok note #%d marked %s" % (x["id"], x["state"]))
        return
    raise SystemExit(usage)


def cmd_relay(args):
    text = " ".join(args).strip()
    if not text:
        raise SystemExit('err usage: %s relay "instruction for the working session"' % PROG)
    nid = os.environ.get("PLOTS_NOTE")
    mutate(lambda d: d.setdefault("inbox", []).append(
        {"t": now(), "kind": "relay", "ref": None, "text": text[:4000], "read": False,
         "note": int(nid) if nid and nid.isdigit() else None}), "relay")
    if nid and nid.isdigit():
        def fn(obj):
            try:
                x = note_find(obj, nid)
            except SystemExit:
                return
            x.setdefault("relayed", []).append({"t": now(), "text": text[:4000]})
        notes_update(WS, fn)
    print("ok passed to the working session; it sees it at its next step (%s inbox)" % PROG)


def cmd_code(args):
    """Worktrees and branches of the workspace's repositories (read-only git)."""
    res = code_scan(WS)
    if JSON_OUT:
        return _emit(res)
    if not res["repos"]:
        print("no git repositories found in %s (set them with `%s ws set %s repos=<path>,<path>`)" % (
            WS.get("root") or "the workspace", PROG, WS["id"]))
        return
    for r in res["repos"]:
        if r["error"]:
            print("%s: %s%s" % (r["name"], r["error"], " (needs access to ~/%s)" % r["protected"] if r["protected"] else ""))
    ab = lambda x: (" ↑%d ↓%d" % (x["ahead"], x["behind"])) if x.get("ahead") is not None else ""
    print("Worktrees")
    for x in sorted((x for x in res["worktrees"] if x["rel"]), key=lambda x: (not x["here"], -x["t"])):
        print("  %-28s %-3s %-36s %s%s%s" % (x["groupName"][:28], x["repo"], x["branch"] or "(detached %s)" % x["head"],
                                             _ago(x["t"]) if x["t"] else "", ab(x), "  ← here" if x["here"] else ""))
    others = sum(1 for x in res["worktrees"] if not x["rel"])
    if others:
        print("  … %d other worktree%s in these repositories" % (others, "" if others == 1 else "s"))
    print("Branches%s" % (" (ahead/behind %s)" % res["base"] if res["base"] else ""))
    for b in res["branches"][:40]:
        reps = ", ".join("%s%s" % (k, ab(v)) for k, v in b["repos"].items())
        print("  %-40s %-9s %s%s" % (b["name"][:40], _ago(b["t"]) if b["t"] else "", reps,
                                     "  · %s" % b["screen"] if b.get("screen") else ""))


def cmd_sessions(args):
    ss = list_sessions(WS)
    if JSON_OUT:
        return _emit(ss)
    if not ss:
        print("no Claude Code sessions found for %s (notes start a new session)" % WS["id"])
    for x in ss:
        print("%s  %-11s %s%s · %s" % (x["id"], x["ago"], x["title"][:70], " · uses %s" % (WS.get("cli") or PROG) if x["uses"] else "",
                                        x.get("cwd") or ""))


# --------------------------------------------------------------------------- MCP server (stdio)
# `plots mcp`: lets Claude Desktop (or any MCP client) read progress and send notes. Claude Code sessions use the
# CLI and the plugin instead, which cost no context until used.

MCP_TOOLS = [
    {"name": "workspaces", "description": "List the Plots workspaces (one per project) with their progress.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "status", "description": "Progress of one workspace: done/total, what's in flight, decisions waiting on the user, unread inbox, the latest log lines.",
     "inputSchema": {"type": "object", "properties": {"workspace": {"type": "string", "description": "Workspace id or name; default: the one the app shows"}}}},
    {"name": "list_items", "description": "Items (screens) of a workspace with their status. filter: all | open | finished | a status (ns, next, fix, done, testing, tested, merged, blocked, oos) | @batch | a group name.",
     "inputSchema": {"type": "object", "properties": {"workspace": {"type": "string"}, "filter": {"type": "string"}}}},
    {"name": "send_note", "description": "Send a note to Claude about a workspace, as from the Plots app. A fork of the Claude Code session working on it answers (the Plots app must be running); read the answer with `notes`.",
     "inputSchema": {"type": "object", "properties": {"workspace": {"type": "string"}, "text": {"type": "string"}}, "required": ["text"]}},
    {"name": "notes", "description": "The latest notes sent to Claude for a workspace and how they were answered.",
     "inputSchema": {"type": "object", "properties": {"workspace": {"type": "string"}, "count": {"type": "integer"}}}},
]


def _mcp_ws(args: dict) -> dict:
    reg = reg_load()
    key = (args or {}).get("workspace")
    w = ws_find(reg, key) if key else (ws_find(reg, reg.get("current")) or (reg["workspaces"][0] if reg["workspaces"] else None))
    if not w:
        raise SystemExit("no workspace %r" % key if key else "no workspaces yet")
    return w


def _mcp_call(name: str, args: dict) -> str:
    if name == "workspaces":
        reg = reg_load()
        rows = []
        for w in reg["workspaces"]:
            p = ws_public(w)
            rows.append("%s%s (%s): %s" % ("* " if w["id"] == reg.get("current") else "", w["name"], w["id"],
                                          "%d of %d done" % (p["done"], p["total"]) if "done" in p else "no data yet"))
        return "\n".join(rows) or "No workspaces yet."
    w = _mcp_ws(args)
    if name == "send_note":
        n = note_add(w, args.get("text", ""), delay=0)
        up = _ping()
        return "Sent as note #%d to %s.%s" % (n["id"], w["name"], "" if up else " Plots isn't running, so it will go out when the app opens.")
    if name == "notes":
        items = notes_load(w)["notes"][-int(args.get("count") or 8):]
        out = []
        for x in items:
            out.append("#%d [%s] %s" % (x["id"], x.get("state"), x.get("text", "")))
            if x.get("reply"):
                out.append("  → %s" % x["reply"]["text"])
            if x.get("error"):
                out.append("  ! %s" % x["error"])
        return "\n".join(out) or "No notes yet."
    with ws_context(w):
        data = load()
        if name == "status":
            st = stats(data)
            fl = [s for s in data["screens"] if s["status"] in WORKING]
            lines = ["%s: %d of %d done (%.0f%%), %d in flight, %d not started%s." % (
                w["name"], st["done"], st["total"], st["pct"], st["working"], st["not_started"],
                (", %d out of scope" % st["oos"]) if st["oos"] else "")]
            if fl:
                lines.append("Being worked on: " + "; ".join("%s %s (%s)%s" % (s["id"], s["name"], s["status"], (": " + s["note"]) if s.get("note") else "") for s in fl[:12]))
            if st["waiting"]:
                lines.append("Waiting on %s: %s" % (user_name(), "; ".join("#%d %s" % (d["n"], d["topic"]) for d in st["waiting"])))
            if st["unread"]:
                lines.append("Inbox: %d unread for the working session." % len(st["unread"]))
            logs = data.get("log", [])[-3:]
            if logs:
                lines.append("Latest: " + " | ".join("%s %s" % (l["t"], l["text"]) for l in reversed(logs)))
            return "\n".join(lines)
        if name == "list_items":
            f = (args.get("filter") or "").strip()
            sc = sorted(data["screens"], key=lambda s: s.get("order", 999))
            sc = [s for s in sc if _match(data, s, f)] if f else [s for s in sc if s["status"] in WORKING or s["status"] == "Up next"]
            return "\n".join("%s %s · %s%s" % (s["id"], s["name"], s["status"], (" · " + s["note"]) if s.get("note") else "") for s in sc) or "(none)"
    raise SystemExit("unknown tool %r" % name)


def cmd_mcp(args):
    def send(obj):
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
        if mid is None:
            continue                      # a notification
        try:
            if method == "initialize":
                res = {"protocolVersion": params.get("protocolVersion") or "2025-06-18",
                       "capabilities": {"tools": {}}, "serverInfo": {"name": "plots", "version": str(VERSION)},
                       "instructions": "Plots tracks Claude Code projects (workspaces). Use status for progress, send_note to ask the working session something."}
            elif method == "tools/list":
                res = {"tools": MCP_TOOLS}
            elif method == "tools/call":
                try:
                    text = _mcp_call(params.get("name"), params.get("arguments") or {})
                    res = {"content": [{"type": "text", "text": text}]}
                except SystemExit as e:
                    res = {"content": [{"type": "text", "text": re.sub(r"^err ", "", str(e))}], "isError": True}
            elif method == "ping":
                res = {}
            else:
                send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "unknown method %s" % method}})
                continue
            send({"jsonrpc": "2.0", "id": mid, "result": res})
        except Exception as e:  # noqa: BLE001
            send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": str(e)}})


COMMANDS = {
    "status": cmd_status, "s": cmd_status, "next": cmd_next, "ls": cmd_ls, "list": cmd_ls,
    "show": cmd_show, "set": cmd_set, "note": cmd_note, "detail": cmd_detail, "log": cmd_log,
    "decision": cmd_decision, "dec": cmd_decision, "decisions": cmd_decisions, "commit": cmd_commit,
    "commits": cmd_commits, "activity": cmd_activity, "inbox": cmd_inbox,
    "add": cmd_add, "undo": cmd_undo, "export": cmd_export, "import": cmd_import,
    "serve": cmd_serve, "open": cmd_open, "stop": cmd_stop,
    "ws": cmd_ws, "workspaces": cmd_ws, "init": cmd_init, "notes": cmd_notes, "relay": cmd_relay, "bridge": cmd_bridge,
    "sessions": cmd_sessions, "code": cmd_code, "mcp": cmd_mcp,
}


DEFAULT_WS = None          # main(default_ws=…) pins a workspace
NO_WS = {"serve", "open", "stop", "ws", "workspaces", "init", "mcp", "bridge"}


def main(argv=None, prog=None, default_ws=None):
    global JSON_OUT, PROG, DEFAULT_WS
    if prog:
        PROG = prog
    if default_ws:
        DEFAULT_WS = default_ws
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--json" in argv:
        argv.remove("--json")
        JSON_OUT = True
    ws_arg = _opt(argv, "--ws", "--workspace")
    pinned = None
    cmd = argv.pop(0) if argv else "status"
    if cmd in ("help", "-h", "--help"):
        try:
            use_ws(pinned or ws_resolve(ws_arg, DEFAULT_WS))
        except SystemExit:
            pass
        print(help_text())
        return
    fn = COMMANDS.get(cmd)
    if not fn:
        raise SystemExit("err unknown command %r — run: %s help" % (cmd, PROG))
    try:
        if cmd not in NO_WS:
            use_ws(pinned or ws_resolve(ws_arg, DEFAULT_WS))
            migrate_statuses()
        elif ws_arg:
            argv = ["--ws", ws_arg] + argv
        fn(argv)
    except SystemExit:
        raise


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        pass

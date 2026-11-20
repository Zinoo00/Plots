"""Light helpers shared by the Plots MCP server and the Plots hooks (stdlib only; no engine import, so the hooks
stay fast on the common path).

- lanes: a lane is a folder under a lane root (default ~/worktrees; PLOTS_LANE_ROOTS, colon-separated) with be/ and fe/ git worktrees;
  the page a lane works on comes from its branch name (feature/pag1010e-dev → pag1010e).
- the ▶ line: the first line of an item's note, "▶ now (01-05 13:49): …" (read as "what's happening now").
  The hooks keep an "[auto …]" tail at its end with the latest commit and test run.
- commits and test runs: read from a Bash call's command and output.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

HOME = Path(os.environ.get("PLOTS_HOME") or (Path.home() / ".plots"))
AUTO_DIR = HOME / "auto"
INSTALLED = AUTO_DIR / "installed"          # epoch seconds; sessions that started before it are left alone
TRACKER = Path(__file__).resolve().parent.parent   # the engine folder (plots.py)
LANE_ROOTS = [Path(p).expanduser() for p in
              (os.environ.get("PLOTS_LANE_ROOTS") or str(Path.home() / "worktrees")).split(":") if p]
SIDES = ("be", "fe")
MARK = "▶ "

# --------------------------------------------------------------------------- lanes

# page ids in branch names: three letters, four digits, a letter (feature/pag1010e-dev); PLOTS_PAGE_RE overrides it
_PAGE_RE = re.compile(os.environ.get("PLOTS_PAGE_RE") or r"(?<![a-z0-9])([a-z]{3}\d{4}[a-z])(?![a-z0-9])")


def lane_of_path(p) -> dict:
    """{lane, side, repo, root} for a path inside a lane's be/ or fe/ worktree, else None."""
    if not p:
        return None
    try:
        p = os.path.normpath(os.path.abspath(os.path.expanduser(str(p))))
    except (TypeError, ValueError):
        return None
    for root in LANE_ROOTS:
        r = str(root).rstrip("/") + "/"
        if not p.startswith(r):
            continue
        parts = p[len(r):].split("/")
        if len(parts) >= 2 and parts[1] in SIDES:
            return {"lane": parts[0], "side": parts[1], "repo": str(root / parts[0] / parts[1]), "root": str(root)}
    return None


def branch_of(repo) -> str:
    """The checked-out branch of a worktree, read from its HEAD file (no git process). None when detached."""
    try:
        g = Path(repo) / ".git"
        if g.is_file():
            txt = g.read_text(encoding="utf-8").strip()
            gd = Path(txt.split(":", 1)[1].strip()) if txt.startswith("gitdir:") else None
            if gd and not gd.is_absolute():
                gd = (Path(repo) / gd).resolve()
        else:
            gd = g
        head = (gd / "HEAD").read_text(encoding="utf-8").strip() if gd else ""
    except OSError:
        return None
    return head[len("ref: refs/heads/"):] if head.startswith("ref: refs/heads/") else None


def pages_of_branch(branch) -> list:
    """Page ids named in a branch: feature/pag1010e-dev → [pag1010e]; shared branches name none."""
    return list(dict.fromkeys(_PAGE_RE.findall((branch or "").lower())))


def lane_names(root) -> list:
    try:
        return [n for n in os.listdir(root) if not n.startswith(".")]
    except OSError:
        return []


def lanes_in_command(cmd: str, cwd=None) -> list:
    """The lane worktrees a shell command works in: absolute or ~ paths, lane names (two-factor/fe, $L/two-factor),
    and the call's cwd. A bare lane name without be/fe counts for both sides."""
    found, seen = [], set()

    def add(info):
        if info and info["repo"] not in seen:
            seen.add(info["repo"])
            found.append(info)

    text = (cmd or "").replace("$HOME", str(Path.home())).replace("${HOME}", str(Path.home()))
    text = re.sub(r"(?<![\w/])~(?=/)", str(Path.home()), text)
    for root in LANE_ROOTS:
        names = sorted(lane_names(root), key=len, reverse=True)
        if not names:
            continue
        pat = re.compile(r"(?<![\w-])(%s)(?![\w-])(/(be|fe)(?![\w-]))?" % "|".join(re.escape(n) for n in names))
        for m in pat.finditer(text):
            lane, side = m.group(1), m.group(3)
            for sd in ([side] if side else list(SIDES)):
                if (root / lane / sd).is_dir():
                    add({"lane": lane, "side": sd, "repo": str(root / lane / sd), "root": str(root)})
    if not found:                         # the cwd only when the command names no lane itself
        add(lane_of_path(cwd))
    return found


def all_lane_repos() -> list:
    out = []
    for root in LANE_ROOTS:
        for lane in lane_names(root):
            for sd in SIDES:
                if (root / lane / sd / ".git").exists():
                    out.append({"lane": lane, "side": sd, "repo": str(root / lane / sd), "root": str(root)})
    return out


# --------------------------------------------------------------------------- the ▶ line

_AUTO_RE = re.compile(r"\s*\[auto[: ][^\]]*\]\s*$")


def split_note(note: str):
    """(▶ line without the mark, the rest). The line is None when the note has none."""
    note = (note or "").strip("\n")
    if note.startswith("▶"):
        first, _, rest = note.partition("\n")
        return first[1:].strip(), rest.strip()
    return None, note.strip()


def join_note(line, rest: str) -> str:
    rest = (rest or "").strip()
    if line is None:
        return rest
    return MARK + line.strip() + ("\n" + rest if rest else "")


def stamp_line(line: str, t: str) -> str:
    """'now (01-05 13:49): …' unless the line already says now/next."""
    line = re.sub(r"^\s*▶\s*", "", (line or "").strip()).replace("\n", " ")
    if re.match(r"(?i)^(now|next)\b", line):
        return line
    return "now (%s): %s" % (t[5:16], line)


def with_lane_line(note: str, line: str) -> str:
    """Replace the ▶ line (and its auto tail), keep the older notes below it."""
    _, rest = split_note(note)
    return join_note(line, rest)


def with_auto_tail(note: str, tail: str) -> str:
    """Put '[auto <tail>]' at the end of the ▶ line, replacing an earlier one; a note without a ▶ line gets one."""
    line, rest = split_note(note)
    base = _AUTO_RE.sub("", line or "").strip()
    return join_note((base + " " if base else "") + "[auto: %s]" % tail, rest)


# --------------------------------------------------------------------------- shell commands

_SEG_SPLIT = re.compile(r"&&|\|\||[;|\n]|\$\(|`|\(|\)")
_WRAPPERS = {"time", "nice", "env", "command", "exec", "nohup", "caffeinate", "sudo"}


def segments(cmd: str) -> list:
    """The simple commands of a shell line, each as a token list without leading VAR=… and wrappers (time, env …)."""
    out = []
    for part in _SEG_SPLIT.split(cmd or ""):
        toks = [t.strip("'\"") for t in part.split()]
        while toks and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", toks[0]) or toks[0] in _WRAPPERS or toks[0].startswith("-")):
            toks.pop(0)
        if toks:
            out.append(toks)
    return out


def _base(tok: str) -> str:
    return tok.rsplit("/", 1)[-1]


_COMMIT_OUT = re.compile(r"^\[(?P<branch>[^\]\n]+?) (?P<hash>[0-9a-f]{7,40})\] (?P<msg>.+)$", re.M)


def git_action(cmd: str):
    """'commit' / 'amend' / 'cherry-pick' / 'revert' / 'am' when the line runs that git command, else None."""
    for toks in segments(cmd):
        if _base(toks[0]) != "git":
            continue
        i = 1
        while i < len(toks) and toks[i].startswith("-"):
            i += 2 if toks[i] in ("-C", "-c", "--git-dir", "--work-tree") else 1
        sub = toks[i] if i < len(toks) else ""
        if sub == "commit":
            return "amend" if "--amend" in toks else "commit"
        if sub in ("cherry-pick", "revert", "am"):
            return sub
    return None


def commits_in(cmd: str, out: str) -> list:
    """[{branch, hash, msg, action}] from git's '[branch hash] message' lines after a commit / cherry-pick / revert."""
    action = git_action(cmd)
    if not action:
        return []
    res = []
    for m in _COMMIT_OUT.finditer(out or ""):
        br = re.sub(r"\s*\(root-commit\)$", "", m.group("branch")).strip()
        res.append({"branch": None if br.startswith("detached") else br, "hash": m.group("hash"),
                    "msg": m.group("msg").strip(), "action": action})
    return res


def _test_of(toks: list):
    b = _base(toks[0])
    rest = toks[1:]
    if b in ("npx", "bunx") or (b in ("pnpm", "yarn") and rest and rest[0] in ("exec", "dlx")):
        inner = [t for t in (rest[1:] if b in ("pnpm", "yarn") else rest) if not t.startswith("-")]
        return _test_of(inner) if inner else None
    if b in ("npm", "pnpm", "yarn"):
        args = [t for t in rest if not t.startswith("-")]
        if args[:1] == ["test"] or args[:2] == ["run", "test"] or args[:1] == ["t"]:
            return "npm test"
        return None
    if b in ("vitest", "jest"):
        return b
    if b == "tsc":
        return "tsc"
    if b in ("gradlew", "gradle"):
        tasks, skip = [], False
        for t in rest:
            if skip:
                skip = False
                continue
            if t in ("-x", "--exclude-task"):
                skip = True
                continue
            if not t.startswith("-"):
                tasks.append(t)
        if any(t == "test" or t.endswith(":test") or t == "check" or t.endswith(":check") for t in tasks):
            return "gradle test"
    return None


def test_kind(cmd: str):
    """The test or type-check runner a line starts (npm test, vitest, jest, gradle test, tsc)."""
    for toks in segments(cmd):
        k = _test_of(toks)
        if k:
            return k
    return None


def test_result(kind: str, out: str, failed: bool = False, redirected: bool = False) -> str:
    """One short phrase for a test or type-check run, or None when the output says nothing usable."""
    o = out or ""
    m = re.search(r"Tests?\s+((?:\d+ \w+(?: \| )?)+)\s*\(\d+\)", o)                      # vitest
    if m:
        return "%s %s" % (kind, m.group(1).strip())
    m = re.search(r"Tests:\s+([^\n]*?\d+ total)", o)                                      # jest
    if m:
        return "%s %s" % (kind, m.group(1).strip())
    p = re.findall(r"(?:^|\n)\s*(?:#|ℹ)\s*pass\s+(\d+)", o)                               # node --test
    f = re.findall(r"(?:^|\n)\s*(?:#|ℹ)\s*fail\s+(\d+)", o)
    if p or f:
        return "%s %s pass, %s fail" % (kind, p[-1] if p else "?", f[-1] if f else "?")
    m = re.search(r"(\d+) tests? completed(?:, (\d+) failed)?", o)                       # gradle
    if m:
        return "%s %s tests, %s failed" % (kind, m.group(1), m.group(2) or "0")
    m = re.search(r"Found (\d+) errors?", o)                                              # tsc
    if m:
        return "tsc %s errors" % m.group(1)
    if kind == "gradle test" and "BUILD FAILED" in o:
        return "gradle test: build failed"
    if kind == "gradle test" and "BUILD SUCCESSFUL" in o:
        return "gradle test: passed"
    if kind == "tsc" and not failed and not redirected and not o.strip():
        return "tsc 0 errors"
    return None


# --------------------------------------------------------------------------- plots writes seen in a shell call

_T_CLIS = {"plots", "plots.py"}
_T_WRITES = {"set", "note", "detail", "commit", "add", "undo"}


def writes_plots(cmd: str) -> bool:
    """The line writes to Plots through the CLI: plots set|note|detail|commit|add, log with
    text, decision add / decision <n> with a change. Reads (log -n 5, decision 3, ls, show …) don't count."""
    for toks in segments(cmd):
        if _base(toks[0]).startswith("python"):
            toks = toks[1:]
            while toks and toks[0].startswith("-"):      # python3 -I script …
                toks.pop(0)
            if not toks:
                continue
        b = _base(toks[0])
        if b not in _T_CLIS:
            continue
        args, i = [], 1
        while i < len(toks):
            if toks[i] in ("--ws", "--workspace"):
                i += 2
                continue
            if toks[i] != "--json":
                args.append(toks[i])
            i += 1
        if not args:
            continue
        sub, rest = args[0], args[1:]
        if sub in _T_WRITES:
            return True
        if sub == "log" and any(not a.startswith("-") for a in rest) and "-n" not in rest and "--last" not in rest:
            return True
        if sub in ("decision", "dec") and rest and (rest[0] == "add" or len(rest) > 1):
            return True
    return False


# --------------------------------------------------------------------------- gate

def installed_at() -> float:
    try:
        return float(INSTALLED.read_text().strip())
    except (OSError, ValueError):
        return 0.0


def session_is_new(transcript_path) -> bool:
    """Only sessions that started after the automation was installed (agents already running are left alone)."""
    t0 = installed_at()
    if not t0:
        return False
    if not transcript_path:
        return True
    try:
        st = os.stat(transcript_path)
    except OSError:
        return True                       # the transcript isn't written yet: a session that just started
    born = getattr(st, "st_birthtime", None) or st.st_ctime
    return born >= t0


def hhmm(t=None) -> str:
    return time.strftime("%H:%M", time.localtime(t or time.time()))

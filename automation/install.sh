#!/bin/bash
# Turn on the Plots MCP server and hooks for every Claude Code session started from now on (user scope).
# Running sessions and their agents are not touched: the hooks ignore sessions that started before this runs.
# Backs up ~/.claude/settings.json and ~/.claude.json first. Undo: uninstall.sh.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PY=/opt/homebrew/bin/python3
[ -x "$PY" ] || PY=$(command -v python3)
TS=$(date +%Y%m%d-%H%M%S)

cp -p ~/.claude/settings.json ~/.claude/settings.json.bak-$TS-plots
cp -p ~/.claude.json ~/.claude.json.bak-$TS-plots
echo "backups: ~/.claude/settings.json.bak-$TS-plots · ~/.claude.json.bak-$TS-plots"

mkdir -p ~/.plots/auto
"$PY" -c "import time;print(time.time())" > ~/.plots/auto/installed

# hooks + permission for the plots MCP tools (merged; nothing else in the file changes)
"$PY" - "$PY" "$HERE/plots_auto_hook.py" <<'PY'
import json, os, sys
py, hook = sys.argv[1], sys.argv[2]
p = os.path.expanduser("~/.claude/settings.json")
s = json.load(open(p))
def entry(mode, matcher=None):
    e = {"hooks": [{"type": "command", "command": '%s "%s" %s' % (py, hook, mode), "timeout": 20}]}
    return dict({"matcher": matcher}, **e) if matcher else e
hooks = s.setdefault("hooks", {})
for ev, e in (("PostToolUse", entry("post-tool", "Bash|Edit|Write|MultiEdit|NotebookEdit|mcp__plots__.*")),
              ("PostToolUseFailure", entry("post-tool", "Bash")),
              ("Stop", entry("stop")), ("SubagentStop", entry("stop"))):
    lst = hooks.setdefault(ev, [])
    if not any("plots_auto_hook.py" in h.get("command", "") for x in lst for h in x.get("hooks", [])):
        lst.append(e)
allow = s.setdefault("permissions", {}).setdefault("allow", [])
if "mcp__plots" not in allow:
    allow.append("mcp__plots")
tmp = p + ".tmp"
with open(tmp, "w") as f:
    json.dump(s, f, indent=2, ensure_ascii=False)
    f.write("\n")
os.replace(tmp, p)
print("hooks: PostToolUse, PostToolUseFailure, Stop, SubagentStop · allow: mcp__plots")
PY

# the MCP server (user scope)
claude mcp remove -s user plots >/dev/null 2>&1 || true
claude mcp add -s user plots -- "$PY" "$HERE/plots_mcp.py"
echo "done: sessions started from now on get the plots tools and hooks."

#!/bin/bash
# Turn the Plots MCP server and hooks off again (removes only what install.sh added).
set -euo pipefail
PY=/opt/homebrew/bin/python3
[ -x "$PY" ] || PY=$(command -v python3)
cp -p ~/.claude/settings.json ~/.claude/settings.json.bak-$(date +%Y%m%d-%H%M%S)-plots-off
"$PY" - <<'PY'
import json, os
p = os.path.expanduser("~/.claude/settings.json")
s = json.load(open(p))
for ev in list((s.get("hooks") or {}).keys()):
    keep = [x for x in s["hooks"][ev] if not any("plots_auto_hook.py" in h.get("command", "") for h in x.get("hooks", []))]
    if keep:
        s["hooks"][ev] = keep
    else:
        del s["hooks"][ev]
if s.get("hooks") == {}:
    del s["hooks"]
allow = (s.get("permissions") or {}).get("allow")
if allow and "mcp__plots" in allow:
    allow.remove("mcp__plots")
with open(p + ".tmp", "w") as f:
    json.dump(s, f, indent=2, ensure_ascii=False)
    f.write("\n")
os.replace(p + ".tmp", p)
PY
claude mcp remove -s user plots || true
rm -f ~/.plots/auto/installed
echo "Plots hooks and MCP server removed for new sessions."

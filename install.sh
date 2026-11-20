#!/bin/sh
# Sets Plots up on this Mac. Safe to run again; it only replaces its own files.
#   1. builds Plots.app (needs Xcode 26+) and copies it to ~/Applications
#   2. puts the `plots` command in ~/.local/bin (it runs the engine inside the app)
#   3. copies the Claude Code plugin to ~/.plots/claude-plugin and, with --claude, installs it
#   4. with --init "Name" [folder], starts tracking a project folder as a workspace
# Usage: sh install.sh [--claude] [--init "Project name" [/path/to/project]] [--no-build]
set -eu
src=$(cd "$(dirname "$0")" && pwd)
claude_plugin=0; build=1; init_name=""; init_dir=""
while [ $# -gt 0 ]; do
  case "$1" in
    --claude) claude_plugin=1 ;;
    --no-build) build=0 ;;
    --init) init_name=${2:-}; shift; case "${2:-}" in ""|--*) ;; *) init_dir=$2; shift ;; esac ;;
    *) echo "unknown option $1"; exit 2 ;;
  esac
  shift
done

major=$(sw_vers -productVersion | cut -d. -f1)
[ "$major" -ge 26 ] || { echo "err Plots needs macOS 26 or later (this Mac runs $(sw_vers -productVersion))"; exit 1; }
command -v python3 >/dev/null || { echo "err python3 not found (install Xcode's command line tools)"; exit 1; }

app="$HOME/Applications/Plots.app"
if [ "$build" = 1 ]; then
  command -v swiftc >/dev/null || { echo "err swiftc not found: install Xcode 26 or later, then run this again"; exit 1; }
  sh "$src/native/build.sh" --install
elif [ -d "$src/Plots.app" ]; then
  mkdir -p "$HOME/Applications"; rm -rf "$app"; cp -R "$src/Plots.app" "$app"
  echo "ok copied Plots.app to ~/Applications"
fi
[ -d "$app" ] || app="$src/Plots.app"
engine="$app/Contents/Resources/engine/plots.py"
[ -f "$engine" ] || engine="$src/plots.py"

mkdir -p "$HOME/.local/bin"
printf '#!/bin/sh\n# Plots CLI, installed by %s/install.sh\nexec python3 "%s" "$@"\n' "$src" "$engine" > "$HOME/.local/bin/plots"
chmod +x "$HOME/.local/bin/plots"
echo "ok plots command: ~/.local/bin/plots"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo "note: add ~/.local/bin to your PATH (for example in ~/.zshrc: export PATH=\"\$HOME/.local/bin:\$PATH\")" ;; esac

mkdir -p "$HOME/.plots"
rm -rf "$HOME/.plots/claude-plugin"
cp -R "$src/plugin" "$HOME/.plots/claude-plugin"
echo "ok Claude Code plugin: ~/.plots/claude-plugin"
if [ "$claude_plugin" = 1 ]; then
  if command -v claude >/dev/null; then
    claude plugin marketplace add "$HOME/.plots/claude-plugin" >/dev/null 2>&1 || claude plugin marketplace update plots >/dev/null 2>&1 || true
    claude plugin install plots@plots && echo "ok plugin installed (new Claude Code sessions pick it up)"
  else
    echo "skip: no claude command; install Claude Code, then run: claude plugin marketplace add ~/.plots/claude-plugin && claude plugin install plots@plots"
  fi
else
  echo "to add it to Claude Code: claude plugin marketplace add ~/.plots/claude-plugin && claude plugin install plots@plots"
fi

if [ -n "$init_name" ]; then
  ( cd "${init_dir:-$PWD}" && python3 "$engine" init "$init_name" )
fi
echo "optional, for Claude Desktop: add {\"plots\": {\"command\": \"$HOME/.local/bin/plots\", \"args\": [\"mcp\"]}} to mcpServers (Settings › Developer › Edit Config)"
echo "done. Open Plots from ~/Applications; in a project folder, \`plots init \"Name\"\` (or /plots:init in Claude Code) starts tracking it."

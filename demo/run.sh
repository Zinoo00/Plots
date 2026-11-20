#!/bin/sh
# The Plots demo, on its own port with its own made-up data (demo/.home), so your real workspaces are never touched.
# Chat is answered by demo/bridge.py; PLOTS_NO_FORKS keeps the server from ever starting a Claude Code session.
#   sh demo/run.sh            seed (first time), start the server and the chat bridge, open the page
#   sh demo/run.sh reset      re-seed from scratch, then start
#   sh demo/run.sh stop       stop the demo server and bridge
#   sh demo/run.sh env        print the variables, for running `plots` against the demo by hand
set -eu
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/.." && pwd)
export PLOTS_HOME="$here/.home"
export PLOTS_PORT="${PLOTS_PORT:-4399}"
export PLOTS_NO_FORKS=1
unset PLOTS_WS PLOTS_NOTE 2>/dev/null || true
pidf="$PLOTS_HOME/run/demo-bridge.pid"
url="http://127.0.0.1:$PLOTS_PORT/?ws=juniper#/overview"

stop() {
  python3 -I "$root/plots.py" stop >/dev/null 2>&1 || true
  if [ -f "$pidf" ]; then kill "$(cat "$pidf")" 2>/dev/null || true; rm -f "$pidf"; fi
}

case "${1:-start}" in
  stop) stop; echo "ok demo stopped" ;;
  env) printf 'export PLOTS_HOME="%s" PLOTS_PORT=%s PLOTS_NO_FORKS=1\n' "$PLOTS_HOME" "$PLOTS_PORT" ;;
  start|reset)
    stop
    if [ "${1:-start}" = reset ] || [ ! -f "$PLOTS_HOME/workspaces.json" ]; then python3 -I "$here/seed.py" >/dev/null; fi
    python3 -I "$root/plots.py" open --no-window >/dev/null
    mkdir -p "$PLOTS_HOME/run"
    nohup python3 -I "$here/bridge.py" >"$PLOTS_HOME/run/demo-bridge.log" 2>&1 &
    echo $! >"$pidf"
    echo "ok demo running at $url"
    echo "   live updates for a recording: python3 demo/play.py   ·   screenshots: node demo/capture.mjs"
    [ "${PLOTS_DEMO_NO_OPEN:-}" = 1 ] || open "$url" 2>/dev/null || true
    ;;
  *) echo "usage: sh demo/run.sh [start|reset|stop|env]"; exit 2 ;;
esac

# The Plots demo

A sandbox for screenshots, screen recordings and trying changes: a made-up project, **Juniper web v2** (a notes app
getting a new web client), with 18 items in every status, five decisions, a log, shared commits, two small git repos
with lane worktrees for the Code card, answered Chat conversations and a second workspace for the switcher.

It never touches your own Plots data and never starts a Claude Code session:

- its data lives in `demo/.home` (`PLOTS_HOME`) and its repos in `demo/.work`, both ignored by git;
- its server runs on port **4399** (yours stays on 4317);
- `PLOTS_NO_FORKS=1` stops the server from forking a Claude Code session for Chat, and `bridge.py` answers Chat
  instead, with short replies built from the demo data.

| File | What it does |
|---|---|
| `run.sh` | `sh demo/run.sh [start\|reset\|stop\|env]`: seed (first time), start the server and the chat bridge, open the page |
| `seed.py` | builds the demo from scratch (dates relative to today, so it always looks current) |
| `play.py` | a scripted stretch of work, one `plots` write every few seconds (`--gap 5`, `--reset`) |
| `bridge.py` | the stand-in for your Claude project that answers Chat |
| `capture.mjs` | Playwright screenshots and recordings into `docs/assets/` |

## Screenshots

```sh
cd demo && npm install                     # once: Playwright 1.61.1
node capture.mjs                           # all of them, light and dark, 1440×900 @2x
node capture.mjs --only overview,chat --dark
node capture.mjs --out /tmp/shots --scale 1
```

| Name | Shows |
|---|---|
| `overview` | the dashboard: items in flight, status wheel, screen map, progression, decisions waiting |
| `screens` | the list with the Note editor's details open (findings, review, branches, history) |
| `decisions` | decision #5 with its proposal and Confirm |
| `activity` | the timeline beside the Code card (worktrees and branches) |
| `chat` | the Chat panel with an answered question |
| `search` | the ⌘K palette |
| `phone` | the compact layout at 390×844 @3x |

Each run re-seeds first so the dates read "today"; `--no-reset` keeps the current data, `--keep` leaves the demo
running afterwards.

## Recordings

```sh
node capture.mjs --video live --dark       # docs/assets/live-dark.mp4 + .gif: play.py running against the overview
node capture.mjs --video chat --light      # docs/assets/chat-light.mp4 + .gif: a question typed into Chat and answered
```

Needs `ffmpeg` for the mp4 and gif (without it the raw .webm is kept).

To record by hand (QuickTime, CleanShot, the Mac app instead of the browser…):

```sh
sh demo/run.sh reset                       # fresh data, opens http://127.0.0.1:4399/?ws=juniper
python3 demo/play.py --gap 4               # start recording, then run this
```

To show the Mac app instead of the browser, start it against the demo:

```sh
eval "$(sh demo/run.sh env)" && ~/Applications/Plots.app/Contents/MacOS/Plots
```

Ideas worth a clip: changing a status with **S** and a number, confirming decision #5, `@` mentioning an item in Chat,
switching to the docs workspace, toggling Light / Dark, and **Export to Excel**.

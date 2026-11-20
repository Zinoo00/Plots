# Plots automation

Keeps Plots current without anyone asking: an MCP server the agents call, and Claude Code hooks that record lane work
on their own. Both write through the engine's own path (`plots.py` `mutate()` / `cmd_*`: the workspace lock, an undo
snapshot, an atomic write), so the app shows every change live.

| File | What it is |
|---|---|
| `plots_mcp.py` | stdio MCP server `plots`: `get_status`, `list_items`, `set_page_status`, `set_lane_line`, `log_event`, `record_commit`, `add_decision`, `update_decision`, `workspaces` |
| `plots_auto_hook.py` | hooks: `post-tool` (PostToolUse, PostToolUseFailure) and `stop` (Stop, SubagentStop) |
| `plots_writes.py` | the writes both use (status + ▶ line, the `[auto: …]` tail, commits) |
| `plots_lanes.py` | lanes, branches → item ids, the ▶ line, commit and test-output parsing (no engine import; fast) |
| `test_automation.py` | `python3 -I test_automation.py`: runs on a temp `PLOTS_HOME` with seeded data and temp git lanes |
| `install.sh` | registers it all for new sessions (backs up both config files first) |
| `uninstall.sh` | removes the hooks, the permission and the MCP server again (backs up settings first) |

## Lanes

A lane is a folder under a lane root with `be/` and `fe/` git worktrees, one lane per piece of work:

```
~/worktrees/                     # PLOTS_LANE_ROOTS (colon-separated) overrides it
  two-factor/be   feature/jn0140-two-factor
  two-factor/fe   feature/jn0140-two-factor
```

The item a lane works on comes from its branch name: three letters, four digits and a letter by default
(`feature/pag1010e-dev` → `pag1010e`); set `PLOTS_PAGE_RE` to a regular expression with one group for your own ids.

## What happens

- **A commit in a lane**: the commit goes into the workspace's commits (once per hash; an `--amend` replaces the commit
  it amended), the item's ▶ line gets `[auto: FE commit 3e9d1c7f2 13:45 · …]`, its be/fe branch is filled in when empty,
  and Not started / Up next → Fixing. Merges, cherry-picks and `git am` only update the tail. Shared lanes (no item in
  the branch) record the commit only.
- **A test or type-check run in one lane** (`npm test`, vitest, jest, `gradlew … test|check`, `tsc`): the parsed
  result goes into that item's `[auto: …]` tail (`npm test 40 pass, 0 fail 13:47`, `tsc 55 errors 13:48`). Unparsed
  output, or a command touching several lanes, writes nothing.
- Automatic writes use the engine's lock and atomic write but no undo snapshot, so `plots undo` still reverts your own
  and the agents' last change.
- **An agent stops** (SubagentStop, or a session's Stop) after editing or committing in a lane without writing to
  Plots since: it is asked once to update the ▶ line / status. The second stop always goes through.
- **Your testing stays yours**: Testing, Tested and Merged are never set by an agent unless you asked; an item in one of
  them keeps its status while it is fixed again (only the ▶ line is written) and goes to Done when the fix is in.

## Safety

- Only sessions whose transcript started after `~/.plots/auto/installed` are touched: agents already running carry on.
- `PLOTS_AUTO=0` turns the hooks off for a session; forks answering Plots notes (`PLOTS_NOTE`) are skipped.
- A hook never fails a tool call (errors go to `~/.plots/auto/hook.log`); per-run state is in `~/.plots/auto/runs/`.

## Registration (user scope, new sessions only)

`sh automation/install.sh` adds to `~/.claude/settings.json` the hooks `PostToolUse` (matcher
`Bash|Edit|Write|MultiEdit|NotebookEdit|mcp__plots__.*`), `PostToolUseFailure` (`Bash`), `Stop` and `SubagentStop`
→ `python3 <this folder>/plots_auto_hook.py post-tool|stop`, and `permissions.allow` `mcp__plots`; then
`claude mcp add -s user plots -- python3 <this folder>/plots_mcp.py`. Both config files are backed up first
(`*.bak-<time>-plots`).

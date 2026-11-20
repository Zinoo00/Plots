---
name: plots
description: Keep the project's Plots workspace up to date while you work on it (item fixing, done, blocked; back to fixing for a bug found in testing; testing, tested, merged when asked; a decision for the user; a log line; a shared commit), and act on what the user sends from the Plots app (notes, answers, status changes, Chat messages, instructions relayed by a fork). Also for answering the app's Chat as the workspace's Claude project (coordinator or thread). Use it whenever the session start says the folder is tracked in Plots, when the user mentions Plots, the progress app, its Chat or their notes, or when they ask to start tracking a project.
---

# Plots

Plots is a local progress tracker for Claude Code projects: one workspace per project, a Mac app the user
watches, and the `plots` command that you use to change it. Every write prints one line and the app updates
live. Never edit the JSON by hand.

`plots` picks the workspace from the folder you're in (or `$PLOTS_WS`); add `--ws <id>` to choose one.
`plots ws` lists them; `plots init "Name"` starts tracking the current folder.

## Start of a session

- `plots` prints a short summary: progress, the next items, the decisions waiting on the user and the inbox.
- If it shows `Inbox: N new`, run `plots inbox` (this marks them read) and act on what the user wrote.
- While you work, new items from the app also arrive on their own after a tool call (this plugin's hook) in the
  workspace's working session: the first session to run `plots`, or the last one to run `plots inbox`
  (`--peek` doesn't count). Treat them as the user's instructions and fold them into the current work.

## Writing

- Status plus a note for the user (plain language, 1–2 sentences):
  `plots set 0110 fix -m "Fixing the 8 review notes from round 1."`
  - statuses, in the order of the process: `ns` → `fix` → `done` → `testing` → `tested` → `merged`; also `next`
    (queued), `blocked`, `oos`. `fix` (Fixing) is all the work on an item; `wip` and `review` mean it too.
  - Testing, Tested and Merged are the user's own testing and merging, usually switched in the app: set them only
    when the user asks. All four of Done, Testing, Tested and Merged count as done.
  - A bug from testing: when the user reports a bug in an item that is Testing, Tested or Merged and wants it
    fixed, set it back to `fix` (with a note on what you're fixing) before you start, and to `done` when the fix
    is in; they move it to Testing again when they re-test.
  - ids: `0110`, `0110,0120`, or `@pilot` for a whole batch
- Note only: `plots note 0110 "…"` · details: `plots detail 0110 review="Round 2: passed" be="feature/x (5)"`
- Log line (what changed, written for the user): `plots log "0110 review round 2 passed; done."`
- Needs the user: `plots decision add "Topic" -s ask --screens 0110 -d "One sentence they can confirm"`
  (`ask` = please confirm, `wait` = blocked until they answer). Put the actual proposal in `-d`.
- The user answers in the app or in chat; record a chat answer right away:
  `plots decision 30 decided -d "…"` (`confirmed` when they accept the proposal as written).
- Shared commit: `plots commit BE 8a41f0c3e "feat: …"` · new item: `plots add 0150 "Name" --menu M --batch B`
- Several changes: chain them with `&&` in one shell call. `plots undo` reverts the last write.

## Reading

- `plots ls` (working + up next), `plots ls @core`, `plots ls blocked`, `plots next 3`
- `plots show 0110`, `plots decisions open`, `plots decision 30`, `plots activity`, `plots commits`
- `plots code`: the worktrees and branches of the workspace's repositories, and how far each is ahead of or behind
  the common branch (read-only git)
- `plots inbox --peek` shows new items without marking them read. Add `--json` to any read.
- `plots notes` shows the messages the user sent from the app's Chat and how they were answered.

## Chat in the app

The user chats with Claude from the app's Chat, a panel beside the page (where the sidebar is); what the page shows
goes with each message. Who answers depends on the workspace's `notes` setting:

- `notes=fork` (the default): a fork of the working session (`claude -p --resume … --fork-session`) answers each
  message right away, so the user gets a reply even while you're busy. If you are that fork (your first message
  says so): answer briefly, don't edit files, and pass anything the working session should do with
  `plots relay "<instruction>"`; it arrives in the working session's inbox and after its next tool call.
- `notes=project`: the workspace's Claude project answers. `plots bridge watch` (the bridge on the Mac) prints
  one JSON line per new message, and `plots notes pending` lists the ones not answered yet: `id`, `conversation`,
  `title`, `text`, `to` (the thread the user picked, or the one the conversation is with), `ask`, `local` (it has
  to run on the user's Mac), `context` (what the app showed beside the chat when the user sent it: an item id or
  `#12`; `contextLine` says it in words). Read a message about "this screen" or "it" as being about its context.
  - As the coordinator, answer in place with `plots notes reply <id> "answer"` (Markdown: lists, tables, code;
    item ids like `0110` and `#12` show as chips), or `plots notes fail <id> "why"`. Or hand the message to a
    thread: `plots notes claim <id> --to "<thread name>" --where mac|cloud --url <the thread's session link>
    --title "<3–6 word title>"`. Honour `to` when the user picked a thread; follow-ups go to the same thread.
    Name a conversation with `--title` or `plots notes title <id> "…"` (otherwise it's called after its first
    message).
  - As the thread: keep its card current with `plots notes thread <id> --state working|waiting|review
    --progress "<what you're doing, one line>"` (`waiting` while the user has to approve something in Claude),
    then answer with `plots notes reply <id> "…"`. Status changes you make with `plots set` while you work show
    in the conversation.
  - `plots bridge claim|reply|fail|thread|title <ws> <id> …` do the same with the workspace given first.

## Rules

- Notes are what the user reads in the app: what is happening and what comes next.
- The user's own notes (`myNotes`) belong to them: read them, never overwrite them.
- To show the app: `plots open`. An Excel copy for sharing: `plots export`.

# Plots plugin for Claude Code

Keeps a Plots workspace up to date while Claude Code works on a project, and hands what you send from the Plots
app (Your Notes, answers, status changes, Chat messages passed on to the working session) to the working session as
soon as it arrives, even in the middle of a task.

- **Skill** `plots`: how to use the `plots` command (status, log, decisions, relays, and answering the app's
  Chat as a fork or as the workspace's Claude project).
- **Hooks**: at session start, one line of context in tracked folders; after each tool call and prompt, anything
  new from the app for the workspace's working session (the first to run its command, or the last to run
  `<cli> inbox`; not a subagent).
- **Commands**: `/plots:init`, `/plots:status`, `/plots:notes`.

Install (the Plots app's menu does this too: Plots › Install Claude Code Plugin…):

```
claude plugin marketplace add ~/.plots/claude-plugin
claude plugin install plots@plots
```

It needs the `plots` command on PATH (Plots › Install Command Line Tool…, or `sh install.sh`).

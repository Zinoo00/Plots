---
description: Start tracking this project in Plots (one workspace per project)
argument-hint: "[workspace name]"
allowed-tools: Bash(plots:*)
---
Make a Plots workspace for the current folder:

1. Run `plots init "$ARGUMENTS"` (if no name was given, use a short, readable name for this project).
2. If the project has a list of work items (screens, pages, endpoints, tickets), add them with
   `plots add <id> "<name>" --menu <group> --batch <batch>`, chaining several with `&&`. Ask me before adding
   more than about 30, and show me the list you plan to add.
3. Run `plots` and tell me in one or two sentences what the app will show. Mention that I can open it with
   `plots open`, and that notes I send from the app reach this session after its next tool call.

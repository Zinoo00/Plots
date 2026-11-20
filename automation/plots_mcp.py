#!/usr/bin/env python3
"""Plots as a local MCP server (stdio, JSON-RPC 2.0, stdlib only) for Claude Code agents.

Tools: get_status, list_items, set_page_status, set_lane_line, log_event, record_commit, add_decision,
update_decision, workspaces. Every write goes through the engine's own write path (plots.py mutate / cmd_*), so
the Plots app shows it live. Register: claude mcp add -s user plots -- python3 <this file>
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import plots_lanes as L  # noqa: E402
import plots_writes as T  # noqa: E402

E = T.E
WS = {"type": "string", "description": "Workspace id (default: the one that holds the ids, else $PLOTS_WS, else the app's current one)."}
IDS = {"type": "string", "description": "Item ids: 'pag1010e', 'pag1010e,pag1011e', or '@batch'."}

TOOLS = [
    {"name": "get_status",
     "description": "What the user sees in Plots. Without ids: progress, items in flight, decisions waiting on the user, the latest log lines. "
                    "With ids: each item's status, ▶ line, earlier notes, branches, review, the user's own notes, open decisions and recent history.",
     "inputSchema": {"type": "object", "properties": {"workspace": WS, "ids": IDS}}},
    {"name": "list_items",
     "description": "Items with status and ▶ note. filter: all | open | finished | a status (ns, next, fix, done, testing, tested, merged, blocked, oos) | @batch | a menu name. Default: in flight and up next.",
     "inputSchema": {"type": "object", "properties": {"workspace": WS, "filter": {"type": "string"}}}},
    {"name": "set_page_status",
     "description": "Set the status of pages, optionally with a new ▶ line (one plain sentence for the user: what is happening and what comes next). "
                    "Statuses: ns, next (queued/waiting), fix (an agent is on it), done (re-review passed; user re-tests), blocked (say why in the line), oos. "
                    "testing/tested/merged belong to the user and are refused unless user_asked is true. A page the user set to Testing/Tested/Merged keeps that status "
                    "when you set fix/next (only the ▶ line is written); set done when the fix is in.",
     "inputSchema": {"type": "object", "properties": {
         "workspace": WS, "ids": IDS, "status": {"type": "string"},
         "line": {"type": "string", "description": "New ▶ line; 'now (MM-DD HH:MM): ' is added unless it starts with now/next."},
         "user_asked": {"type": "boolean", "description": "Only when the user asked for testing/tested/merged."}},
         "required": ["ids", "status"]}},
    {"name": "set_lane_line",
     "description": "Replace the ▶ line (the first line of each page's note, shown as 'what's happening now') and keep the older notes below it. "
                    "Status is not changed. Call it when you start on a page, at each phase change, when you ask the user something, and before you stop.",
     "inputSchema": {"type": "object", "properties": {"workspace": WS, "ids": IDS, "line": {"type": "string"}}, "required": ["ids", "line"]}},
    {"name": "log_event",
     "description": "Add a line to the workspace log (Activity): a milestone written for the user, e.g. 'pag1010e review round 2 passed; Done.'",
     "inputSchema": {"type": "object", "properties": {"workspace": WS, "text": {"type": "string"}}, "required": ["text"]}},
    {"name": "record_commit",
     "description": "Record a commit (BE or FE) in the workspace's commit list. Commits made in lane worktrees are recorded automatically by the "
                    "Plots hooks; use this for others. A hash already recorded is skipped.",
     "inputSchema": {"type": "object", "properties": {"workspace": WS, "side": {"type": "string", "enum": ["BE", "FE"]},
                                                      "hash": {"type": "string"}, "message": {"type": "string"}},
                     "required": ["side", "hash", "message"]}},
    {"name": "add_decision",
     "description": "Ask the user: add a decision card. proposal = one sentence they can confirm in one read. wait=true when the work is blocked until they answer.",
     "inputSchema": {"type": "object", "properties": {"workspace": WS, "topic": {"type": "string"}, "proposal": {"type": "string"},
                                                      "ids": IDS, "wait": {"type": "boolean"}}, "required": ["topic", "proposal"]}},
    {"name": "update_decision",
     "description": "Record the user's answer to decision #n: status decided (with their words in text) or confirmed (they accepted the proposal as written).",
     "inputSchema": {"type": "object", "properties": {"workspace": WS, "n": {"type": "integer"},
                                                      "status": {"type": "string", "enum": ["decided", "confirmed", "ask", "wait"]},
                                                      "text": {"type": "string"}}, "required": ["n", "status"]}},
    {"name": "workspaces",
     "description": "The Plots workspaces with their progress.",
     "inputSchema": {"type": "object", "properties": {}}},
]


def _row(r: dict) -> str:
    if r["kept_user_status"]:
        return "%s: kept %s (user status) and wrote the ▶ line; set done when the fix is in" % (r["id"], r["from"])
    return "%s: %s" % (r["id"], ("%s → %s" % (r["from"], r["to"])) if r["from"] != r["to"] else ("still %s" % r["to"]))


def call(name: str, a: dict) -> str:
    a = a or {}
    if name == "workspaces":
        return E._mcp_call("workspaces", {})
    ids = T.split_ids(a.get("ids"))
    w = T.resolve_ws(a.get("workspace"), ids)
    if name == "get_status":
        if ids:
            return T.describe(w, ids)
        return E._mcp_call("status", {"workspace": w["id"]})
    if name == "list_items":
        return E._mcp_call("list_items", {"workspace": w["id"], "filter": a.get("filter") or ""})
    if name == "set_page_status":
        rows = T.set_page(w, ids, status=a.get("status"), line=a.get("line"), user_asked=bool(a.get("user_asked")))
        return "\n".join(_row(r) for r in rows) + ("\n▶ line written." if a.get("line") else "")
    if name == "set_lane_line":
        if not str(a.get("line") or "").strip():
            raise T.Refused("line is empty")
        rows = T.set_page(w, ids, line=a["line"])
        return "▶ line written on %s." % ", ".join(r["id"] for r in rows)
    if name == "log_event":
        return T.cli(w, ["log", str(a.get("text") or "").strip() or "(empty)"])
    if name == "record_commit":
        h = str(a.get("hash") or "").strip()
        data = T.read(w)
        if any(c.get("hash", "")[:7] == h[:7] for c in data.get("commits", [])):
            return "commit %s is already recorded." % h
        return T.cli(w, ["commit", str(a.get("side") or "").upper(), h, str(a.get("message") or "")])
    if name == "add_decision":
        argv = ["decision", "add", str(a.get("topic") or ""), "-s", "wait" if a.get("wait") else "ask", "-d", str(a.get("proposal") or "")]
        if ids:
            argv += ["--screens", ",".join(ids)]
        return T.cli(w, argv)
    if name == "update_decision":
        argv = ["decision", str(int(a.get("n"))), str(a.get("status"))]
        if a.get("text"):
            argv += ["-d", str(a["text"])]
        return T.cli(w, argv)
    raise T.Refused("unknown tool %r" % name)


def main():
    def send(obj):
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    for stream, kw in ((sys.stdin, {"encoding": "utf-8", "errors": "replace"}), (sys.stdout, {"encoding": "utf-8"})):
        try:
            stream.reconfigure(**kw)
        except (AttributeError, ValueError):
            pass
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(msg, dict):
            continue                          # batches aren't used by Claude Code
        mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
        if not isinstance(params, dict):
            params = {}
        if mid is None:
            continue
        try:
            if method == "initialize":
                res = {"protocolVersion": params.get("protocolVersion") or "2025-06-18",
                       "capabilities": {"tools": {}}, "serverInfo": {"name": "plots", "version": "1"},
                       "instructions": "Plots is a live progress tracker. Keep it current while you work: set_lane_line when you start on a page, "
                                       "at each phase change and before you stop; set_page_status when the status changes (fix while you work on it, "
                                       "next when you stop with work left, done only after the re-review passes, blocked with the reason). "
                                       "Never set testing/tested/merged unless the user asked. Commits and test runs in lane worktrees are recorded automatically."}
            elif method == "tools/list":
                res = {"tools": TOOLS}
            elif method == "tools/call":
                try:
                    res = {"content": [{"type": "text", "text": call(params.get("name"), params.get("arguments") or {})}]}
                except T.Refused as e:
                    res = {"content": [{"type": "text", "text": str(e)}], "isError": True}
                except SystemExit as e:          # the engine's own refusals ("err no screen …")
                    res = {"content": [{"type": "text", "text": str(e.code).replace("err ", "", 1)}], "isError": True}
            elif method == "ping":
                res = {}
            else:
                send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "unknown method %s" % method}})
                continue
            send({"jsonrpc": "2.0", "id": mid, "result": res})
        except Exception as e:  # noqa: BLE001
            if os.environ.get("PLOTS_MCP_DEBUG"):
                traceback.print_exc(file=sys.stderr)
            send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": str(e)}})


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Quibbler CLI - Main command-line interface"""

import sys
import json
import argparse
from pathlib import Path

from quibbler.mcp_server import run_server as run_mcp_server
from quibbler.hook_server import run_server as run_hook_server
from quibbler.hook_forward import forward_hook
from quibbler.hook_display import display_feedback
from quibbler.iflow_config import get_iflow_auth_token


def cmd_mcp(args):
    """Run the MCP server via stdio"""
    run_mcp_server()


def cmd_hook_server(args):
    """Run the hook server"""
    port = getattr(args, "port", None) or 8081
    run_hook_server(port=port)


def _add_claude_hooks():
    """Add quibbler hooks to .claude/settings.json"""
    claude_dir = Path.cwd() / ".claude"
    settings_file = claude_dir / "settings.json"

    if not claude_dir.exists():
        claude_dir.mkdir(parents=True, exist_ok=True)
        print(f"Created {claude_dir}")

    _update_hooks_in_settings(settings_file)
    print(f"✓ Added quibbler hooks to {settings_file}")


def _add_iflow_hooks():
    """Add quibbler hooks to .iflow/settings.json"""
    iflow_dir = Path.cwd() / ".iflow"
    settings_file = iflow_dir / "settings.json"

    if not iflow_dir.exists():
        iflow_dir.mkdir(parents=True, exist_ok=True)
        print(f"Created {iflow_dir}")

    _update_hooks_in_settings(settings_file)
    print(f"✓ Added quibbler hooks to {settings_file}")


def _update_hooks_in_settings(settings_file: Path):
    """Helper to update hooks configuration in a settings file"""
    if settings_file.exists():
        with open(settings_file) as f:
            try:
                settings = json.load(f)
            except json.JSONDecodeError:
                settings = {}
    else:
        settings = {}

    if "hooks" not in settings:
        settings["hooks"] = {}

    # Add PreToolUse hook for quibbler hook notify
    settings["hooks"]["PreToolUse"] = [
        {
            "matcher": "*",
            "hooks": [{"type": "command", "command": "quibbler hook notify"}],
        }
    ]

    # Add PostToolUse hook for quibbler hook forward and notify
    settings["hooks"]["PostToolUse"] = [
        {
            "matcher": "*",
            "hooks": [
                {"type": "command", "command": "quibbler hook forward"},
                {"type": "command", "command": "quibbler hook notify"},
            ],
        }
    ]

    settings["hooks"]["UserPromptSubmit"] = [
        {
            "matcher": "*",
            "hooks": [{"type": "command", "command": "quibbler hook forward"}],
        }
    ]

    # Add Stop hook for quibbler hook notify
    settings["hooks"]["Stop"] = [
        {"hooks": [{"type": "command", "command": "quibbler hook notify"}]}
    ]

    with open(settings_file, "w") as f:
        json.dump(settings, f, indent=2)


def cmd_hook_add(args):
    """Add quibbler hooks to configuration settings"""
    # Check if we should default to iflow or claude
    # If explicitly requested or iflow detected, try iflow.
    # For now, we'll try to detect or just do both if unsure, or check args.

    is_iflow = False
    if get_iflow_auth_token():
        is_iflow = True

    # We could add an argument to force one or the other
    # But typically iflow users will have iflow installed/configured.

    if is_iflow:
        print("Detected iFlow configuration. Adding hooks to .iflow/settings.json")
        _add_iflow_hooks()
        print("\nNote: You can configure Quibbler history behavior in .quibbler/config.json:")
        print('  "max_history": 20 (default)')
        print('  "smart_pruning": true (default, keeps first user message)')
    else:
        print("Defaulting to Claude Code configuration. Adding hooks to .claude/settings.json")
        _add_claude_hooks()


def cmd_hook_forward(args):
    """Forward hook events to the server"""
    sys.exit(forward_hook())


def cmd_hook_notify(args):
    """Display quibbler feedback to the agent"""
    sys.exit(display_feedback())


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        prog="quibbler",
        description="Code review agent for AI coding assistants",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        title="Available commands",
        help="Available commands",
        metavar="{mcp,hook}",
        required=True,
    )

    # MCP command - runs MCP server via stdio
    parser_mcp = subparsers.add_parser(
        "mcp", help="Run MCP server (for Cursor, Claude Desktop, iFlow CLI, etc.)"
    )
    parser_mcp.set_defaults(func=cmd_mcp)

    # Hook command - has subcommands for server, add, forward, notify
    parser_hook = subparsers.add_parser("hook", help="Hook mode for Claude Code / iFlow CLI")
    # Default to 'server' if no subcommand given
    parser_hook.set_defaults(func=cmd_hook_server, port=None)

    hook_subparsers = parser_hook.add_subparsers(
        dest="hook_command",
        title="Hook commands",
        help="Hook mode commands",
        metavar="{server,add,forward,notify}",
    )

    # Hook server subcommand
    parser_hook_server = hook_subparsers.add_parser(
        "server", help="Run hook server (default: port 8081)"
    )
    parser_hook_server.add_argument(
        "port", type=int, nargs="?", help="Port to run on (default: 8081)"
    )
    parser_hook_server.set_defaults(func=cmd_hook_server)

    # Hook add subcommand
    parser_hook_add = hook_subparsers.add_parser(
        "add", help="Add hooks to settings.json (detects iFlow/Claude)"
    )
    parser_hook_add.set_defaults(func=cmd_hook_add)

    # Hook forward subcommand (used by hooks, not shown in main help)
    parser_hook_forward = hook_subparsers.add_parser(
        "forward", help="Forward hook events to server"
    )
    parser_hook_forward.set_defaults(func=cmd_hook_forward)

    # Hook notify subcommand (used by hooks, not shown in main help)
    parser_hook_notify = hook_subparsers.add_parser(
        "notify", help="Display feedback to agent"
    )
    parser_hook_notify.set_defaults(func=cmd_hook_notify)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

# Quibbler MCP & Hook Configuration Guide

This guide explains how to configure Quibbler with various AI coding assistants and IDEs using the Model Context Protocol (MCP) and Hook systems.

## Supported Providers

| Provider | MCP Support | Hook Support |
|----------|-------------|--------------|
| **Claude Code** | ✅ | ✅ |
| **iFlow CLI** | ✅ | ✅ |
| **Claude Desktop** | ✅ | ❌ |
| **Cursor** | ✅ | ❌ |
| **Gemini CLI** | ✅ | ❌ |
| **Zed** | ✅ | ❌ |
| **Google Antigravity** | ✅ | ❌ |

---

## 1. Environment Configuration

Quibbler supports the following environment variables to customize its behavior, specifically for context management and token efficiency.

| Variable | Description | Default |
|----------|-------------|---------|
| `QUIBBLER_MAX_CONTEXT_TOKENS` | Maximum estimated tokens allowed in the conversation history before compaction runs. | `128000` |
| `QUIBBLER_COMPACTION_THRESHOLD` | Percentage of max tokens (0.0 - 1.0) that triggers compaction. | `0.8` (80%) |
| `QUIBBLER_MODEL` | The model Quibbler uses for review (overrides config files). | `claude-haiku-4-5-20251001` or `Qwen3-Coder` (if iFlow) |

**Auto-Compaction Behavior:**
When the history size reaches the `COMPACTION_THRESHOLD` (e.g., 80% of 128k tokens), Quibbler automatically runs a "smart prune" operation. It preserves the System Prompt and the most recent messages, dropping older messages until usage drops to ~60%, ensuring the agent can continue working without hitting context limits.

---

## 2. MCP Configuration

### Claude Code

**Command Line:**
```bash
claude mcp add quibbler -- python3 -m quibbler.cli mcp
```

**Configuration File (`managed-mcp.json`):**
Located at `~/.claude/managed-mcp.json` (or OS equivalent).

```json
{
  "mcpServers": {
    "quibbler": {
      "command": "python3",
      "args": ["-m", "quibbler.cli", "mcp"],
      "env": {
        "QUIBBLER_MAX_CONTEXT_TOKENS": "200000"
      }
    }
  }
}
```

### iFlow CLI

**Command Line:**
```bash
iflow mcp add quibbler python3 -m quibbler.cli mcp
```

**Configuration File (`settings.json`):**
Located at `~/.iflow/settings.json`.

```json
{
  "mcpServers": {
    "quibbler": {
      "command": "python3",
      "args": ["-m", "quibbler.cli", "mcp"]
    }
  }
}
```

### Claude Desktop

**Configuration File (`claude_desktop_config.json`):**
*   macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
*   Windows: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "quibbler": {
      "command": "uv",
      "args": ["tool", "run", "quibbler", "mcp"]
    }
  }
}
```

### Cursor

**Configuration File (`.cursor/mcp.json`):**
Located in your project root or global settings.

```json
{
  "mcpServers": {
    "quibbler": {
      "command": "python3",
      "args": ["-m", "quibbler.cli", "mcp"]
    }
  }
}
```

### Gemini CLI

**Configuration File (`settings.json`):**
Usually located in `~/.gemini/settings.json` (check Gemini docs for platform specific path).

```json
{
  "mcpServers": {
    "quibbler": {
      "command": "python3",
      "args": ["-m", "quibbler.cli", "mcp"]
    }
  }
}
```

### Zed Editor

**Configuration File (`settings.json`):**
Open via `Cmd+Shift+P` -> `Open Settings`.

```json
{
  "context_servers": {
    "quibbler": {
      "command": "python3",
      "args": ["-m", "quibbler.cli", "mcp"]
    }
  }
}
```

### Google Antigravity (IDE)

**Via UI:**
1.  Open the **Agent** window.
2.  Select **MCP Servers** from the dropdown menu.
3.  Click **Add Custom Server** (or similar).
4.  Name: `quibbler`
5.  Command: `python3 -m quibbler.cli mcp`

---

## 3. Hook Configuration

Hooks allow Quibbler to passively monitor and intervene in agent sessions. Currently supported by Claude Code and iFlow CLI.

### Automatic Setup (Recommended)

Run this command in your project root. It automatically detects if you are using Claude Code or iFlow and updates the appropriate settings.

```bash
quibbler hook add
```

### Manual Setup (iFlow CLI)

Edit `.iflow/settings.json` in your project:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "*",
        "hooks": [
          { "type": "command", "command": "quibbler hook forward" },
          { "type": "command", "command": "quibbler hook notify" }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "matcher": "*",
        "hooks": [
          { "type": "command", "command": "quibbler hook forward" }
        ]
      }
    ]
  }
}
```

### Manual Setup (Claude Code)

Edit `.claude/settings.json` in your project:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "*",
        "hooks": [
          { "type": "command", "command": "quibbler hook forward" },
          { "type": "command", "command": "quibbler hook notify" }
        ]
      }
    ]
  }
}
```

### Running the Hook Server

For hooks to work, the Quibbler server must be running in the background:

```bash
quibbler hook server
```

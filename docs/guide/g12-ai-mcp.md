---
guide_id: g12-ai-mcp
title: AI & MCP Connection
level: 2
minutes: 30
needs: ["g01-install", "g02-settings"]
kind: 실습
---

# AI & MCP Connection

AoT offers two ways to add AI. The main one is **MCP**. You connect an AI app you already use
(Claude Desktop, Claude Code, and so on) to AoT, and that AI reads the site's sensor values, schedules and map, and proposes
device operations. MCP (Model Context Protocol) is an open standard that lets AI apps use the tools of outside systems.
The other is the **Built-in AI** that comes inside AoT, which you can turn on if you need it.

Either way, moving a device or changing a setting runs only after a person approves it.

## When you finish this chapter { #goal }

- You connect an AI app to AoT through MCP and ask the AI about the site's status
- You know how to approve an operation the AI proposes

## Before you start { #prepare }

- AoT that you can log in to with an administrator account ([Installation](g01-install.md#check))
- An AI app that supports MCP (this chapter uses Claude Desktop and Claude Code as examples)
- If you use the AI app on a different computer from AoT, a network where the two computers can reach each other (Tailscale from [Network Connection](g03-network.md) is recommended)

## Steps { #steps }

### 1. Turn on external AI access { #step-1 }

In **Manage** → **System Management** → **General Settings**, under the **AI Service** section, check that **Enable External MCP Server** is on.
It is on at first. If you turn it off, every MCP request is rejected.

If you installed with Docker, the MCP server is already running as the `aot_mcp` container (port 5700).

### 2. Create an access key { #step-2 }

AI apps come into AoT with a user API key. If you create **one key per AI app**, you can later cut off just one app.

1. In **Manage** → **System Management** → **Users**, open the user the AI will act for and go to the **API Key** section.
2. Choose **Permissions**. With **Full access**, the AI can propose the operations the role allows; with **Read only**, it only reads.
3. Choose **AI Tools**. This is the range of tools shown to the AI.
   - **Operations**: tools you use every day, such as reading values, operating devices, schedules and notes (recommended at first)
   - **Operations + configuration**: also the tools that create and edit inputs, outputs, functions, the map and dashboards. The list gets longer, so the AI's answers may slow down
4. In the **Issue New Key** row, type the app name (for example `Claude Desktop`) in the input box and click **Generate**.
5. **Copy** the **New Key** that appears. The key is shown **only this once**.

The people who can create keys are administrators who can edit users.

### 3. Decide the MCP address { #step-3 }

How you connect depends on **which computer the AI app is on**.

| Where the AI app is | How to connect | Section in this chapter |
|---|---|---|
| The same computer where AoT is installed | The AI app runs the MCP server directly (stdio) | [Step 4](#step-4) |
| A different computer (a laptop, etc.) | Connect over the network (HTTP), address `http://<AoT computer address>:5700/mcp` | [Step 5](#step-5) |

The MCP server in a Docker installation at first accepts **only connections from the AoT computer itself**. To connect from another computer,
write the address to listen on in `docker/.env` and start it again. Use a private network address or a Tailscale address.

```bash
# docker/.env
AOT_MCP_BIND=100.64.0.10      # Tailscale address of the AoT computer (example)
```

```bash
docker compose -f docker/docker-compose.prod.yml up -d
```

Check that it opened from the computer where the AI app is. A response containing the AoT name and version means it worked.

```bash
curl http://100.64.0.10:5700/mcp/info
```

!!! danger "Do not open the MCP port to the internet"
    Do not put `0.0.0.0` in `AOT_MCP_BIND` or open port 5700 on your router. The MCP server runs over unencrypted
    HTTP. Use it only inside a private network or Tailscale.

### 4. Connect from the same computer (stdio) { #step-4 }

Have the AI app run the MCP server directly inside the container. Put the key you copied in step 2 in place of `<key>`.

**Claude Desktop**: add this to `mcpServers` in the settings file (`claude_desktop_config.json`) and restart Claude Desktop.

```json
{
  "mcpServers": {
    "aot": {
      "command": "docker",
      "args": ["compose", "-f", "/opt/AoT/docker/docker-compose.prod.yml",
               "exec", "-T", "-e", "AOT_MCP_API_KEY=<key>",
               "aot_mcp", "python", "aot/aot_mcp_server.py"]
    }
  }
}
```

**Claude Code**:

```bash
claude mcp add aot -- docker compose -f /opt/AoT/docker/docker-compose.prod.yml exec -T -e AOT_MCP_API_KEY=<key> aot_mcp python aot/aot_mcp_server.py
```

`/opt/AoT` is the folder where you downloaded AoT. If you put it somewhere else, change it to that path.

### 5. Connect from another computer (HTTP) { #step-5 }

Enter the address from step 3 and the key from step 2 in the AI app. The key is sent in the `X-API-KEY` header.

**Claude Code**:

```bash
claude mcp add --transport http aot http://100.64.0.10:5700/mcp --header "X-API-KEY: <key>"
```

**Claude Desktop**: Claude Desktop cannot attach to a remote server directly from its settings file, so it goes through the relay tool `mcp-remote`
(Node.js must be installed). `--allow-http` is needed when attaching to an unencrypted private network address.

```json
{
  "mcpServers": {
    "aot": {
      "command": "npx",
      "args": ["mcp-remote", "http://100.64.0.10:5700/mcp",
               "--header", "X-API-KEY:${AOT_KEY}", "--allow-http"],
      "env": { "AOT_KEY": "<key>" }
    }
  }
}
```

Other apps that support MCP work the same way: enter the same address and the `X-API-KEY` header.

If the AI app asks for permission every time it calls a tool, open the app's connector (tool) permission settings after connecting and set AoT's **read-only tools** to **always allow**, so lookups no longer ask. Changes such as operating a device still go through AoT's own approval, so the other tools can stay on **needs approval**.

### 6. Ask and approve { #step-6 }

1. In the AI app, ask something like "Tell me the current temperature and humidity in the Site B greenhouse." The AI reads the values with AoT's tools and answers.
2. A request that moves a device, such as "Open the side vent to 30%," does not run right away; it becomes **awaiting approval**. The AI tells you
   what it intends to do and that the request is awaiting approval.
3. Check the details and answer clearly, for example "Approve that request." The AI passes the approval to AoT and the operation runs.
   Only keys of users with the administrator or editor role can approve. If you do not approve within 15 minutes, the request is dropped.

What the AI can do never goes beyond the role of the user who owns the key, or the permissions and AI tool range from step 2.

### 7. Turn on the built-in AI (optional) { #step-7 }

If you want to talk to AI directly inside AoT, turn on the built-in AI. It works separately from the MCP connection, so MCP works even if you leave it off.

1. In **Manage** → **System Management** → **General Settings**, under **AI Service**, turn on **Enable AI Service**. An **AI** menu appears at the top of the screen.
2. In **AI** → **Connection**, under **Built-in AI**, choose an **Engine** (Anthropic, OpenAI, Google Gemini, local Ollama, etc.) and click **Add**, then
   enter that service's **API Key** and **Model**, click **Save**, and **Activate** it.

For detailed settings, see the [AI overview](../ai/overview.md).

## Check { #check }

You are done when the AI app answers with AoT's actual values when you ask about the site, and device operation requests come in as awaiting approval.

- Does `aot` show as connected in the AI app's MCP list?
- Is **Enable External MCP Server** on?
- Did you create a separate key for each app? (They are told apart by name in the **Issued Keys** list.)

## Site A { #site-a }

Site A connects Claude Desktop on an office laptop to AoT over Tailscale ([step 5](#step-5)). The key is created with the **Operations** range,
so the AI checks irrigation schedules and soil moisture and proposes valve operations, and the person in charge approves them.

## Site B { #site-b }

Site B uses Claude Code on the AoT computer in the control room next to the greenhouse, so it uses the same-computer connection ([step 4](#step-4)).
To refine the environment control settings together with the AI, it keeps one separate key with the **Operations + configuration** range.

## Troubleshooting { #trouble }

| Symptom | What to check |
|---|---|
| The AI app cannot connect | Whether `curl http://<address>:5700/mcp/info` responds, and whether you started it again after changing `AOT_MCP_BIND` |
| Every request is rejected | **Enable External MCP Server** is off |
| An authentication error occurs | Whether you entered the key exactly, without leading or trailing spaces, and whether that key has not been revoked in the **Issued Keys** list |
| Values can be read but no device operations are proposed | The key's **Permissions** is **Read only**, or the user's role has no control permission |
| The AI cannot create settings | The key's **AI Tools** is **Operations**. To hand over configuration too, use an **Operations + configuration** key |
| An approved operation did not run | More than 15 minutes passed before approval. Make the request again |

## Learn more { #more }

- [AI overview](../ai/overview.md)
- [General settings](../Configuration-Settings.md)

# Local Linux Assistant

A lightweight, privacy-first Linux desktop assistant for low-end computers. It uses deterministic intent routing for common requests and the official Model Context Protocol (MCP) Python SDK as a strict capability boundary. It does not need a local model, a GPU, Docker, or a paid API.

The MVP deliberately does **not** expose a shell or attempt unrestricted desktop control.

## Architecture

```text
User → CLI → Assistant Core → Rule Router ─┐
                         ↘ Optional LLM ───┤
                                          ↓
                                     MCP Client
                                    (local stdio)
                                      ↙       ↘
                            Linux MCP Server  Web MCP Server
                             system/files/apps  SearXNG/fetch
```

The core discovers tools dynamically from independent MCP servers. Providers never execute processes or access files directly. Every tool call follows validation → permission → server security policy → execution.

## Features

- System, CPU, RAM, disk, and battery status
- Allowlisted directory listing and small text-file reads
- Confirmed directory creation inside configured user roots
- Confirmed launch of a closed application allowlist
- SearXNG web search with normalized results
- Public-web fetch with scheme, DNS/IP, redirect, timeout, type, and size checks
- Optional Ollama responses without automatic startup or model downloads
- JSON-line audit logs containing metadata only
- Maximum two concurrent tool jobs and no background model/service

## Requirements

- Ubuntu/Debian-based Linux (initial target; other Linux distributions may work)
- Python 3.10 or newer
- 8 GB RAM supported; no dedicated GPU required
- Internet only for initial Python package installation and optional web search

The application automatically selects lightweight mode at 8 GB RAM or below. It never preloads embeddings or starts a model.

## Install

```bash
git clone <repository-url> local-assistant
cd local-assistant
chmod +x scripts/*.sh
./scripts/install.sh
```

The installer detects Linux and Python, creates `.venv`, installs the package, creates `~/.config/local-assistant/config.yaml`, runs health checks, and starts the CLI. It does not install system packages or require root.

For development:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
python -m app.main
```

Copy `.env.example` to `.env` to override runtime values. The environment is the active configuration source in this MVP; `config/default.yaml` documents packaged defaults and is copied for future UI/config migration.

## Optional SearXNG

Search uses SearXNG's JSON API and defaults to `http://localhost:8080`. Local tools remain available when SearXNG is down.

Use any trusted SearXNG instance during development:

```bash
SEARXNG_URL=https://your-instance.example python -m app.main
```

Or run the included loopback-only development container:

```bash
docker compose up -d searxng
docker compose ps
```

The included `config/searxng/settings.yml` enables JSON output and avoids relying on a root-owned anonymous configuration volume. Wait until `docker compose ps` reports the service as healthy. Docker is optional and is never required by the assistant itself.

## Use

```bash
python -m app.main
```

Example requests:

```text
show system information
what is my cpu usage?
what is my ram usage?
how much disk space do I have?
show files in Downloads
create a folder called test
open firefox
search the web for FastAPI
find recent news about Linux
show me the current directory
```

Write and execute operations display a confirmation prompt. `exit` or Ctrl-D closes the assistant.

## Run MCP servers directly

The assistant normally owns both stdio subprocesses:

```bash
python -m servers.linux_server.server
python -m servers.web_server.server
```

These commands speak MCP JSON-RPC on standard output, so they appear idle in a regular terminal. Do not print debugging output to their stdout.

## Security model

- There is no `execute_shell` tool. Raw LLM/user strings never reach a shell.
- `open_application` and `run_safe_command` map exact IDs to fixed argv arrays and use `shell=False`.
- Default file roots are `~/Documents`, `~/Downloads`, `~/Desktop`, `~/Pictures`, and `~/Projects`. Override them with a comma-separated `ASSISTANT_ALLOWED_PATHS` value.
- Folder names such as `Downloads` and `library` resolve to matching configured root names, including Windows folders mounted under `/mnt/c` in WSL.
- Symlink-aware resolved paths must remain under an allowed root. `.ssh`, `.gnupg`, browser credential areas, password stores, private keys, and sensitive filenames are blocked.
- Text reads accept a small extension allowlist and a hard 2 MB maximum.
- Page fetch rejects non-HTTP schemes, credentials in URLs, localhost, and private/reserved/link-local IP destinations. Every redirect is revalidated, requests time out within 10 seconds, and decoded response bytes are capped at 2 MB.
- The configured SearXNG endpoint is an operator-trusted service and may intentionally be localhost; arbitrary fetch URLs may not.
- MCP's schemas validate argument types, but the server policies remain the source of authority.
- LLM output is untrusted. Adding a provider cannot bypass routing, permissions, or MCP server validation.
- Audit logs omit prompts, file contents, URLs, paths, tokens, secrets, and tool arguments.

This is defense in depth for a small local assistant, not a sandbox for hostile native code. Run it as an unprivileged user.

## Optional Ollama

Ollama is disabled by default. The assistant checks for an existing executable only when configured; it never starts Ollama or downloads a model.

```bash
LLM_PROVIDER=ollama OLLAMA_MODEL=your-small-model python -m app.main
```

If Ollama or the configured model is unavailable, rule-based operation continues.

## Add a tool

1. Implement the operation in the appropriate `servers/*` module using native APIs or a fixed argv map.
2. Validate inputs inside the server; client checks are not security boundaries.
3. Decorate a strongly typed function with `@mcp.tool()` in that server's `server.py`.
4. Classify the tool in `app/core/permissions.py`.
5. Add deterministic routing only if it is a common request.
6. Add tests for normal behavior, denial cases, size/time limits, and injection attempts.

The tool manager discovers it automatically. A future server can be added to `ToolManager.SERVER_MODULES` without coupling it to an LLM provider.

## Add an LLM provider

Subclass `LLMProvider` from `app/core/llm.py`, implement async `generate(messages, tools=None)`, and select it during application startup. Provider-generated structured tool requests must still be converted to a known tool name and arguments, then processed by `PermissionManager` and `ToolManager`; never call tools from provider code.

## Tests and health checks

```bash
python -m pip install -e '.[dev]'
pytest
./scripts/healthcheck.sh
```

Tests cover routing, path containment, sensitive files, process injection, private/local URLs, redirects, malformed HTML, response limits, timeouts, search normalization, and Linux system tools.

## Troubleshooting

- **Web search unavailable:** verify `SEARXNG_URL`, test the instance's `/search?q=test&format=json`, and enable JSON format in SearXNG.
- **Folder rejected:** the Linux/WSL folder must actually exist and be under an allowed root. This project does not map Windows Explorer libraries automatically. Use an existing Linux folder, or add a WSL path such as `/mnt/c/Users/<you>/Downloads` to `ASSISTANT_ALLOWED_PATHS` before startup.
- **Application not installed:** an allowlisted name is still rejected when its executable is absent from `PATH`.
- **MCP server unavailable:** run `./scripts/healthcheck.sh`; ensure the same virtual environment contains `mcp`, `psutil`, and `httpx`.
- **No Ollama:** expected by default. Rule routing and all MCP tools remain available.

## Roadmap

- User-editable permissions and allowed-root UI
- Multiple dynamically configured MCP servers and optional Streamable HTTP
- Cloud LLM providers without tool-layer changes
- Safer browser integration and richer intent schemas
- Lightweight native desktop UI, packaging, and autostart controls

## License

MIT — see [LICENSE](LICENSE).

## Browser interface and voice

Run from the project directory (loads your existing `.env`):

```bash
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m app.web.server
```

Open **http://localhost:8765** in Windows Chrome. The backend binds only to
127.0.0.1; WSL localhost forwarding normally makes it accessible from Windows.
The CLI and SearXNG container continue to work independently.

Click **Enable voice**, allow the microphone, then say **“hello buddy, show system
information”**. Interim recognition results appear in the command box before the
final transcript is submitted. You can also say the wake phrase, pause, and speak
a command within 15 seconds. Enable voice again after a recognition error. Text
input remains available when speech recognition is unsupported.

This uses the [browser SpeechRecognition API](https://developer.mozilla.org/en-US/docs/Web/API/SpeechRecognition),
which has limited browser support and may send audio to an online recognition
service. Wake detection also uses that service while enabled; it is not a local,
always-on wake-word engine. Keep the tab open; background suspension and browser
endpointing can interrupt or split speech. Interim results reduce perceived delay
but do not guarantee a latency target. For a future offline version, replace this
with a local wake detector and streaming speech-to-text worker behind the same
command API. No audio is uploaded to this Python backend.

Examples (typed or spoken):

```text
create folder Projects/demo
create file Projects/notes.txt with content hello world
move Projects/notes.txt to Projects/demo/notes.txt
open windows calculator
open windows notepad
open windows_files
open windows_terminal
search the web for Python tutorials
```

Use exact destination paths for moves; parent folders must already exist. New
files must have a supported text extension. Existing files are never overwritten.
Moves support files and folders on the same filesystem, reject configured roots,
sensitive descendants, and directories containing symlinks. Cross-filesystem
moves are rejected instead of silently copying and deleting. Path checks are the
existing local-user policy, not protection against hostile concurrent filesystem
mutation.

File changes and application launches present the actual tool arguments for
approval. Approvals expire after two minutes and can only be used once. The API
requires a per-process token and rejects foreign Host/Origin headers. Do not
expose this local command service through a public tunnel or reverse proxy.

### Windows native apps from WSL

[WSL can directly execute Windows `.exe` programs](https://learn.microsoft.com/en-us/windows/wsl/filesystems).
The implementation adds explicit IDs in `security/command_policy.py`:
`windows_notepad` → `notepad.exe`, `windows_calculator` → `calc.exe`,
`windows_files` → `explorer.exe`, and `windows_terminal` → `wt.exe`.
Executables must be installed and discoverable on WSL's PATH; WSL interoperability
and Windows PATH import must be enabled. Launches use fixed argument arrays with
`shell=False`; no recognized speech is interpolated into PowerShell or cmd.exe.
A successful launch reports process creation, not verification of a visible window.

For Windows file operations, add only the folders you want to expose to
`ASSISTANT_ALLOWED_PATHS`, for example `/mnt/c/Users/<you>/Documents` and
`/mnt/c/Users/<you>/Downloads`. Preserve any existing Linux roots in the comma-separated
list. These aliases then resolve to Windows files through the mount. For future
apps outside PATH, add operator-controlled absolute executable paths to the
allowlist. If richer Windows desktop automation is needed later, use a Windows
companion service with authenticated, allowlisted operations; direct WSL interop
is sufficient for these launch-only operations.

### Relative paths and destination phrases

Relative paths use the **first entry in `ASSISTANT_ALLOWED_PATHS`**. For example,
with `/home/hacker/,/mnt/c/Users/Sys`, `create folder test` targets
`/home/hacker/test`, and `create file testing.txt in test folder` targets
`/home/hacker/test/testing.txt`. The parent folder must exist before creating a
file; missing parents produce a message identifying the folder to create.
There is no implicit `Projects` directory.

Standard folder aliases such as `Downloads` are discovered from existing direct
children of the configured roots (first match wins). An explicitly configured
root named `Downloads` takes precedence. Use full paths to disambiguate folders.
You can quote names with spaces, for example
`create file "meeting notes.txt" in "test" with content hello`.
Restart the server after changing allowed paths or adding a standard folder
that should become an alias.

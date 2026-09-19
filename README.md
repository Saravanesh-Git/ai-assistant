# A.M.I.G.O.

**Assistant for Managing Information & General Operations.** A personal command center for Linux and Windows through WSL. Use text or voice to launch apps, manage files, check your system, and open web searches in your desktop browser. No AI model, GPU, Docker, or paid API is required.

The browser UI features a responsive cyan HUD, an animated assistant core, real system readings, quick app launches, and a shared text/voice command stream. Animations respect your reduced-motion preference.

## Start

Requires Python 3.10+ on Linux or WSL. From the project directory:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
cp .env.example .env # only if you do not already have a .env
.venv/bin/python -m app.web.server
```

Open **http://localhost:8765**. For voice and Windows apps, open the page in Windows Chrome while the backend runs in WSL. WSL localhost forwarding normally connects the two. Restart the server after changing configuration or upgrading an already-running instance, then refresh the page.

The existing entry points remain compatible:

```bash
.venv/bin/python -m app.main    # terminal interface
local-assistant-ui            # browser interface, after installation
```

`./scripts/install.sh` also creates a virtual environment and starts the CLI. Runtime settings come from environment variables and `.env`; `config/default.yaml` is a reference, not an active configuration loader.

## Voice and text

1. Click **Enable voice** and grant the browser microphone permission.
2. Say **“Hey Amigo”**, with or without a command in the same sentence.
3. Keep giving commands. The assistant remains awake after commands, typed requests, and normal speech-service restarts. There is no wake timeout.
4. Say **“pause listening”**, **“pause conversation”**, or **“go to sleep”** to return to wake-word mode. Say **“Hey Amigo”** to resume.
5. Say **“stop listening”** or click **Turn off mic** to disable the microphone completely.

Speech transcripts appear below the command input without overwriting your typed draft. Final voice requests and typed requests share an ordered queue, so a follow-up request can wait for an action already running. Interim speech never executes. Enter sends text; Shift+Enter inserts a newline. The command guide lists examples and your configured file locations.

Voice uses the [browser SpeechRecognition API](https://developer.mozilla.org/en-US/docs/Web/API/SpeechRecognition), which has limited browser support and may send audio to an online speech service. Keep the tab open. Browser suspension, device sleep, permissions, and service outages can interrupt listening; a web page cannot guarantee an always-on background microphone. A normal [recognition end event](https://developer.mozilla.org/en-US/docs/Web/API/SpeechRecognition/end_event) restarts recognition while preserving the awake state. Persistent errors stop voice with an explanation, and text remains available. Reloading the page starts a new voice session. The Python backend receives text, not microphone audio.

## Commands

| Task | Examples |
| --- | --- |
| System | `show system information`, `show cpu`, `check ram`, `disk space`, `battery status` |
| Applications | `open calculator`, `open files`, `open terminal`, `open VS Code`, `open windows notepad`, `open windows edge` |
| Browser search | `search for northern lights in the web`, `search the web for Python tutorials`, `look up battery technology` |
| List/read | `show files in Downloads`, `read file demo/notes.txt` |
| Create | `create folder demo`, `create file notes.txt in demo with content hello` |
| Move | `move demo/notes.txt to demo/ideas.txt` |
| Predefined commands | `run pwd`, `run date`, `run whoami`, `run uname -r`, `run hostname -I` |

All normal actions execute immediately as your Linux/WSL account. **Only administrator actions require approval.** The old `ASSISTANT_CONFIRM_ACTIONS` setting is ignored, including when an existing `.env` sets it to `true`.

When an operation reports insufficient OS permissions, A.M.I.G.O. presents the exact operation and its arguments for approval. Approving invokes a single-use sudo worker for that operation; the web server stays unprivileged. You can also explicitly request `sudo create folder /opt/demo` or `create folder /opt/demo as administrator`. An approval expires after two minutes and cannot be reused or changed to authorize a different operation.

If sudo accepts an existing credential or a configured passwordless rule, the approved action proceeds immediately. Otherwise the UI requests your Linux sudo password in a masked field. The password is sent only to sudo over stdin, is never included in command arguments/audit logs/history, and is not persisted. Operation data is sent only after authentication succeeds. The CLI uses masked `getpass` input. An account without sudo privileges receives the actual denial; the app does not modify sudoers, ownership, or permissions to bypass it.

With one pending request, you may say **“approve administrator action”** or **“cancel administrator action”**. Passwords must be typed into the masked field; voice pauses when it receives focus. Browser microphone prompts and Windows UAC prompts remain controlled by their respective applications.

`run <command>` executes any installed command with arguments, using `shell=False`. Use **`run shell <command>`** explicitly for pipes, redirects, variables, or shell syntax. `sudo`/`su`/`pkexec`/`doas` launchers request administrator approval before execution. Failed commands that report permission errors offer an approved rerun and explain that the first attempt may have had partial effects. These are direct user commands, not model-generated execution.

Commands run from your Linux home, are non-interactive, and have a configurable timeout (`COMMAND_TIMEOUT_SECONDS`, default 120 seconds) and a 1 MB output cutoff. Interactive editors and installers that require a terminal should be opened in a terminal application. App requests support the built-in aliases, any executable on PATH, and executable paths. `open /path/to/file` uses the desktop's associated application.

## Windows and WSL

[WSL can directly run Windows executables](https://learn.microsoft.com/en-us/windows/wsl/filesystems). A.M.I.G.O. forwards the desktop/session environment to its MCP subprocesses, including the WSL interoperability variables.

On WSL, generic calculator, files, terminal, Chrome, and VS Code requests target their Windows versions. Explicit names include `windows_calculator`, `windows_notepad`, `windows_files`, `windows_terminal`, `windows_edge`, `windows_chrome`, and `windows_code`. Firefox continues to use the installed Linux application.

Executable discovery tries PATH, then known Windows installation locations on `/mnt/c`. Per-user installs use the current Windows profile, discovered with a fixed `cmd.exe /d /c echo %USERPROFILE%` command. No recognized speech or user path text is interpolated into cmd.exe or PowerShell. If profile discovery is unavailable, set:

```dotenv
ASSISTANT_WINDOWS_PROFILE=/mnt/c/Users/YourName
```

WSL interop must be enabled and the requested application installed. For nonstandard drive mounts or custom install locations, expose the executable on WSL's PATH. The Connections panel reports whether the Windows Explorer executable can be found; this is discovery, not a full desktop-automation health check. A launch response confirms process creation, not a visible window. CPU, memory, and storage readings describe the Linux/WSL environment running the backend.

### File locations

There is **no path allowlist**. `ASSISTANT_ALLOWED_PATHS` and the old YAML allowed directories no longer restrict access or choose a default directory. Your Linux account can operate anywhere the OS permits: `/`, `/home`, `/tmp`, `/opt`, `/etc`, and mounted Windows drives. Protected locations request sudo approval when necessary.

Relative paths start in the **actual Linux home of the account running A.M.I.G.O.** Named aliases include `home`, `root` (meaning `/`), `root home` (`/root`), `Downloads`, and `windows home`. Windows-specific aliases such as `windows Downloads` use the discovered Windows profile. An explicit path always wins. `C:\Users\YourName\Documents\notes.txt` maps to `/mnt/c/Users/YourName/Documents/notes.txt`, and `C:` or `C drive` maps to `/mnt/c`. For custom mount points, use their Linux paths explicitly.

Examples:

```text
show files in /
show files in /etc page 2
create folder reports at /home/yourname/work
create file /tmp/nested/project/settings.conf with content enabled=true
create file "meeting notes.txt" in "C:\Users\YourName\Documents"
find file invoice in /mnt/d
copy /home/yourname/report.csv to /mnt/c/Users/YourName/Desktop/report.csv
write file /tmp/settings.conf with content enabled=false
append file /tmp/settings.conf with content another=value
run ls -la /opt
run shell ls /etc | head
sudo create folder /opt/my-project
```

Creation accepts any filename or extension, including extensionless and hidden files, and creates missing parents. `create file` refuses to overwrite an existing path; `write file` explicitly replaces text, and `append file` appends it. Text is UTF-8; creating a `.pdf` or `.docx` filename does not generate that document format. File content responses and requests remain bounded to prevent browser/resource exhaustion.

Listings are paginated in groups of 200; broken symlinks and individual metadata errors do not hide the entire directory. `find file NAME in PATH` recursively searches names without following directory symlinks, reports unreadable directories, and stops at a time/result limit with a clear message. Narrow the search or explicitly request administrator execution when needed.

Copy and move accept Linux and mounted Windows destinations. Cross-filesystem moves copy to a temporary staging directory, commit without overwriting, and remove the source only after the copy succeeds. If source removal fails, the response reports the retained source instead of claiming a completed move. Existing destinations are never replaced by copy/move.

**Windows permissions:** [Windows ACLs still apply to mounted drives](https://learn.microsoft.com/en-us/windows/wsl/file-permissions). Linux sudo does not make the Windows account an administrator or override a denied Windows ACL, read-only mount, or locked file. The app reports those failures; native Windows elevation may require Windows UAC.

## Web searches

Search commands open `https://www.google.com/search?q=...` in the desktop's default browser. WSL uses PowerShell to activate the Windows HTTPS association, falling back to `wslview`, then installed Edge or Chrome browsers. Search URLs are never sent to File Explorer. Query text is URL-encoded and passed as data, never executed as shell code. Linux uses `xdg-open`. No popup permission or SearXNG service is needed. If no browser launcher works, the response explains that and provides a clickable search link.

The existing `search_web` MCP capability still supports structured SearXNG results for integrations. It is separate from the browser-opening command. To enable it:

```bash
docker compose up -d searxng
# or configure SEARXNG_URL to a trusted JSON-enabled instance
```

Public-page f
tch retains scheme, DNS/IP, redirect, timeout, MIME type, and response-size validation. A configured SearXNG instance is operator-trusted and may intentionally be local.

## Optional and future AI

Deterministic routing handles all supported commands before invoking any optional provider. The default `rule_based` provider needs no model or network service. Optional Ollama remains available:

```bash
LLM_PROVIDER=ollama OLLAMA_MODEL=your-model .venv/bin/python -m app.web.server
```

Ollama must already be installed and configured. A.M.I.G.O. never starts it or downloads models. If a provider cannot be initialized, the factory falls back to local rules; request-time failures are reported without disabling tools.

Both CLI and web use `app/providers/factory.py`. To add an AI integration:

1. Implement `LLMProvider.generate(messages, tools=None)` from `app/core/llm.py`.
2. Register a settings-to-provider factory in `PROVIDERS`.
3. Select it using `LLM_PROVIDER` and read any provider-specific settings in that adapter.

Providers currently generate text responses, without conversation persistence or automatic model tool calls. Future structured tool proposals must pass known-tool, argument, permission, and server validation before execution. Never give provider code a direct process/file executor. `app/web/static/voice.js` similarly isolates browser speech behind state, transcript, and command callbacks so a future local speech adapter can replace it without changing the command API.

```text
Browser (text / speech adapter) or CLI
                  ↓
           Assistant core
        deterministic intent router
          ↙                   ↘
 Known command          Optional text provider
       ↓
 Permission policy → MCP tool manager
                 ↙                  ↘
 Linux / WSL server             Web server
 system, files, apps, browser   SearXNG, fetch
```

The tool manager discovers independent stdio MCP servers. To add a capability, implement and validate it in its server, decorate it with `@mcp.tool()`, classify it in `app/core/permissions.py`, and add a deterministic route if appropriate. Unknown tools remain denied. Audit logs contain tool/status metadata, not prompts, paths, content, tokens, or arguments.

The local API binds to `127.0.0.1:8765`, checks Host/Origin, and requires a per-process token for commands and telemetry. Keep it on loopback rather than exposing it through a public tunnel. Run the assistant as your normal user.

## Verification

```bash
.venv/bin/python -m pytest
./scripts/healthcheck.sh
```

Tests cover routing, direct execution and exact-operation sudo approvals, Windows executable discovery, browser URL encoding and launcher failures, provider extension/fallback, API origin/token checks, machine-wide paths, overwrite protection, password handshakes, and cross-filesystem moves, public-web policy, and system tools.

Optional browser regression checks use simulated speech and desktop responses; they do not open real applications:

```bash
.venv/bin/python -m pip install playwright
.venv/bin/python -m playwright install chromium
.venv/bin/python scripts/verify_ui.py
```

These check persistent wake state, interim/final transcripts, queued commands, restart/pause/stop, denied microphone access, text fallback, output escaping, and layout widths from 320 to 1440 pixels. Screenshots go to `/tmp/amigo-desktop.png` and `/tmp/amigo-mobile.png`. Real microphone recognition and Windows window launches still require testing on a Windows/WSL desktop.

## Troubleshooting

- **Microphone blocked:** allow microphone access in the browser's site settings, then click Enable voice. Use Chrome on Windows if the browser has no speech API.
- **Windows app unavailable:** verify WSL interop, installation, PATH, and Windows profile discovery. `open windows calculator` is a useful first check.
- **Browser did not open:** restart the backend after updating. On WSL, verify Windows has a default HTTPS browser and working PowerShell/WSL interoperability; `wslview`, Edge, and Chrome are fallback launchers. On Linux, verify `xdg-open`. If launching fails, use the returned search link.
- **Permission denied:** approve the specific administrator request. If sudo is denied, verify that the Linux account can use sudo. On mounted Windows drives, check Windows permissions. Changing `ASSISTANT_ALLOWED_PATHS` is no longer necessary.
- **Dashboard disconnected:** ensure the backend is running, use `http://localhost:8765`, and refresh after a backend restart.
- **No AI provider:** expected by default. System, file, app, and browser tools continue to work.

MIT — see [LICENSE](LICENSE).

# Setup: Windows 11 GPU host (Dell XPS 15 / demo laptop)

This covers the machine that runs inference. Steps marked **(once)** only need doing once per machine.

## 1. System prerequisites (once)

1. **NVIDIA driver ≥ 570.** Install the latest Studio or Game Ready driver from nvidia.com, then check it:
   ```powershell
   nvidia-smi          # should show the GPU, e.g. GTX 1050 Ti, 4096 MiB
   ```
2. **Dev tools** (winget ships with Windows 11):
   ```powershell
   winget install Git.Git OpenJS.NodeJS.LTS astral-sh.uv GitHub.cli Microsoft.VisualStudioCode
   winget install Docker.DockerDesktop      # choose the WSL2 backend when asked
   git config --global core.longpaths true
   git config --global user.name  "Your Name"
   git config --global user.email "you@example.com"   # must match your GitHub account
   gh auth login
   ```
3. **Cap WSL2 memory** so Docker can't take 8 GB of a 16 GB machine. Create `%UserProfile%\.wslconfig`:
   ```ini
   [wsl2]
   memory=3GB
   processors=4
   ```
   Then run `wsl --shutdown` and restart Docker Desktop.

## 2. Ollama (once)

1. Install it **from ollama.com/download only**, not a third-party installer. The official build includes the CUDA 12 backend that Pascal GPUs (compute 6.1) need.
2. Set user environment variables, then **quit and restart Ollama** from the tray icon:
   ```powershell
   setx OLLAMA_HOST 127.0.0.1:11434       # never expose Ollama on the network
   setx OLLAMA_KEEP_ALIVE 30m             # avoid cold reloads while developing
   setx OLLAMA_CONTEXT_LENGTH 4096
   setx OLLAMA_FLASH_ATTENTION 1
   ```
3. Pull the models (about 5 GB total):
   ```powershell
   ollama pull llama3.2:3b
   ollama pull qwen3:4b
   ollama pull nomic-embed-text
   ```
4. **Check that the GPU is actually used:**
   ```powershell
   ollama run llama3.2:3b "Say hi in five words"
   ollama ps          # PROCESSOR column must say "100% GPU"
   ```
   If it says CPU, update the NVIDIA driver and reinstall Ollama from the official site.

## 3. Get the code

```powershell
gh repo clone <owner>/helpmate
cd helpmate
copy .env.example .env
cd backend; uv sync; cd ..
cd services\speech; uv sync; cd ..\..
cd web; npm install; cd ..
```

## 4. Run the stack

```powershell
./scripts/dev.ps1                 # backend :8000, speech :8001, web :5173 (all fakes by default)
./scripts/dev.ps1 -Mock           # web only, MSW mocks (no backend)
```
If Windows says *running scripts is disabled*, run this once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. Or use `powershell -ExecutionPolicy Bypass -File scripts\dev.ps1` each time.

To use real components, edit `.env`, one seam at a time:

| To use | Set | Also needs |
|---|---|---|
| Ollama | `HELPMATE_LLM=ollama` | step 2 |
| Real speech | `HELPMATE_STT=http`, `HELPMATE_TTS=http`, `SPEECH_ENGINE=real` | `./scripts/get_models.ps1` (downloads the Kokoro model, ~140 MB; the Whisper model downloads on first use) |
| Postgres | `HELPMATE_REPO=postgres` | `docker compose -f infra/docker-compose.yml up -d` |
| Web Push | `HELPMATE_NOTIFIER=webpush` + VAPID keys | `uv run python scripts/gen_vapid.py` (once; share the same keys across hosts) |

## 5. Phone access with Tailscale (week 4)

1. `winget install Tailscale.Tailscale`, sign in, and install the Tailscale app on your phone with the same account.
2. In the admin console: enable **MagicDNS** and **HTTPS certificates**. Rename this machine to `helpmate` so the URL survives a change of demo host.
3. Build the web app and serve it from FastAPI (a single origin):
   ```powershell
   cd web; npm run build; cd ..
   ./scripts/dev.ps1 -Prod                             # FastAPI serves web/dist at /
   tailscale serve --bg 8000                           # https://helpmate.<tailnet>.ts.net (tailnet only)
   ```
4. **Public demo only** (O7, after 2FA and rate limiting are on): `tailscale funnel --bg 8000`. Turn it off afterwards with `tailscale funnel --https=443 off`.
5. **iPhone:** open the URL in Safari → Share → **Add to Home Screen** → open it from the Home Screen → log in → tap *Enable notifications*. Push only works from the installed app. **Android:** in Chrome, *Enable notifications* works directly.

## Troubleshooting

- **`ollama ps` shows CPU:** the driver is too old or Ollama isn't the official build; see step 2.
- **Docker ports reachable from the LAN:** every port in `infra/docker-compose.yml` must be written `127.0.0.1:<port>:<port>`.
- **Timezone errors in tests:** make sure `tzdata` is installed (`uv sync` handles it). Windows has no system timezone database.
- **Shell script fails with `\r` in a container:** `.gitattributes` forces LF. Run `git add --renormalize .` once.

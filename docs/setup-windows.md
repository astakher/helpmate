# Setup: Windows 11 GPU host (Dell XPS 15 / demo laptop)

This covers the machine that runs inference. Steps marked **(once)** only need doing once per machine.

## 1. System prerequisites (once)

1. **NVIDIA driver ≥ 570.** Install the latest Studio or Game Ready driver from nvidia.com, then check it:
   ```powershell
   nvidia-smi          # should show the GPU, e.g. GTX 1050 Ti, 4096 MiB
   ```
   For GTX 10-series (Pascal) cards nvidia.com now lists it as a **"GeForce Security Update Driver"**
   (582.x on the XPS). That is the full driver, so take it. Pick *Custom → Perform a clean
   installation* and reboot afterwards.
2. **Dev tools** (winget ships with Windows 11):
   ```powershell
   winget install Git.Git OpenJS.NodeJS.22 astral-sh.uv GitHub.cli Microsoft.VisualStudioCode
   winget install Docker.DockerDesktop      # choose the WSL2 backend when asked
   ```
   Use `OpenJS.NodeJS.22`, not `OpenJS.NodeJS.LTS`: LTS is now Node 24, and CI pins 22.
   **Open a new terminal** afterwards, because winget's PATH changes don't reach terminals that were
   already open. Then:
   ```powershell
   git config --global core.longpaths true
   git config --global user.name  "Your Name"
   git config --global user.email "you@example.com"   # must match your GitHub account
   gh auth login        # GitHub.com → HTTPS → login with a web browser
   gh auth setup-git    # lets git push with gh's login
   ```
3. **Cap WSL2 memory** so Docker can't take 8 GB of a 16 GB machine. Create `%UserProfile%\.wslconfig`:
   ```ini
   [wsl2]
   memory=3GB
   processors=4
   ```
   Then run `wsl --shutdown` and restart Docker Desktop.

## 2. Ollama (once)

1. Install it **from ollama.com/download only**, or with `winget install Ollama.Ollama` (it downloads the
   official `OllamaSetup.exe` from github.com/ollama/ollama). Never use a third-party installer. The official
   build includes the CUDA 12 backend that Pascal GPUs (compute 6.1) need; its log shows it skipping CUDA 13
   and using `cuda_v12`, which is correct.
2. Set user environment variables, then **quit and restart Ollama** from the tray icon:
   ```powershell
   setx OLLAMA_HOST 127.0.0.1:11434       # never expose Ollama on the network
   setx OLLAMA_KEEP_ALIVE 30m             # avoid cold reloads while developing
   setx OLLAMA_CONTEXT_LENGTH 4096
   setx OLLAMA_FLASH_ATTENTION 1
   setx LLAMA_ARG_FIT_TARGET 512          # 4 GB cards: see below
   ```
   `setx` only affects programs started **afterwards**. After quitting from the tray, start Ollama again
   from the Start menu (not from a terminal that was open before `setx`). Check that it picked them up:
   the `server config` line in `%LOCALAPPDATA%\Ollama\server.log` should show `OLLAMA_CONTEXT_LENGTH:4096
   OLLAMA_FLASH_ATTENTION:true OLLAMA_KEEP_ALIVE:30m0s`.

   **Why `LLAMA_ARG_FIT_TARGET`:** Ollama 0.34 sizes the GPU offload to leave **1 GiB of VRAM free**. On a
   4 GB card that pushes 2 of llama3.2:3b's 29 layers to the CPU (`ollama ps` shows `17%/83% CPU/GPU`)
   even though about 1 GB is still free. Setting it to 512 MiB puts the whole model on the GPU.
3. Pull the models (about 5 GB total):
   ```powershell
   ollama pull llama3.2:3b
   ollama pull qwen3:4b
   ollama pull nomic-embed-text
   ```
   Note: `qwen3:4b` is now the **thinking-only 2507 build**. It ignores `think:false` and reasons for
   about a minute before each answer. Use `qwen3:4b-instruct` for a non-thinking comparison.
4. **Check that the GPU is actually used:**
   ```powershell
   ollama run llama3.2:3b "Say hi in five words"
   ollama ps          # PROCESSOR column must say "100% GPU"
   ```
   Measured on the XPS: llama3.2:3b = 100% GPU, 2.55 GB VRAM. qwen3:4b needs about 3.0 GB of the
   3.3 GB free, so it still spills 16% to the CPU with a 512 MiB target. That is expected on 4 GB.
5. **Run the model benchmark** after step 3 below, once the code is cloned. On the XPS it takes about 15 minutes
   (llama is done in under a minute; qwen3:4b's thinking takes the rest). It writes
   `docs/benchmarks/<hostname>.md` and `.json`; commit both:
   ```powershell
   cd backend
   uv run helpmate-bench --models llama3.2:3b qwen3:4b
   ```
   It reports load time, GPU % (anything under 100 means the model spilled to the CPU), VRAM, time to first token, tokens/s and tool-calling accuracy on 15 seed prompts. **Tool choice** is whether the model picked the right tool. **Args valid (strict)** is whether its arguments passed HelpMate's validation exactly as sent. **Args correct** is whether the content and time were right, even without a UTC offset. A big gap between the last two means the model gets the time right but leaves off the UTC offset, which tells A to accept local times in the tool arguments.

## 3. Get the code

```powershell
gh repo clone <owner>/helpmate
cd helpmate
copy .env.example .env
cd backend; uv sync; cd ..
cd services\speech; uv sync; cd ..\..
cd web; npm ci; cd ..
```
`npm ci` installs exactly what `package-lock.json` says, the same as CI.

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
| Real speech | `HELPMATE_STT=http`, `HELPMATE_TTS=http`, `SPEECH_ENGINE=real` | `./scripts/get_models.ps1` once: installs the `real` extra (faster-whisper, kokoro-onnx) and downloads Kokoro **fp32** (325 MB + 28 MB voices) and Whisper `base` (~145 MB). `dev.ps1` then starts speech with `uv run --extra real`. A plain `uv sync` in `services/speech` removes the extra again; use `uv sync --extra real`. Voice needs the mic, so use Chrome on `127.0.0.1` (or HTTPS on a phone, §5). |
| Postgres | `HELPMATE_REPO=postgres` | Docker Desktop (WSL2; `wsl --install --no-distribution` first, then reboot). Put a random `POSTGRES_PASSWORD` in `.env` (and the same one in `HELPMATE_DATABASE_URL`) **before** the first start, then `docker compose --env-file .env -f infra/docker-compose.yml up -d postgres`. The API runs the Alembic migrations and seeds an empty database at start-up. Contract suite against a throwaway DB: `docker exec helpmate-postgres-1 createdb -U helpmate helpmate_test`, then set `HELPMATE_TEST_DATABASE_URL=...helpmate_test` and run `uv run pytest tests/contracts`. |
| Real login + 2FA | `HELPMATE_AUTH=totp` | in **your own terminal**, from `backend/`: `uv run python ../scripts/set_password.py` (writes an argon2 hash to `.env`, never the password). Restart the API and sign in, then Settings → Two-step verification → scan → enter the first code → **Turn on**. Lost phone: `set_password.py --reset-2fa`. 5 wrong passwords lock sign-in for 15 min. |
| Web Push | `HELPMATE_NOTIFIER=webpush` + VAPID keys | `cd backend; uv run python ../scripts/gen_vapid.py --write` (once; share the same keys across hosts). Then `./scripts/dev.ps1 -Prod`, open `http://127.0.0.1:8000/settings` → **Enable notifications** → **Send a test notification**. Not on :5173: the dev server has no service worker. |

## 5. Phone access with Tailscale (week 4)

1. `winget install Tailscale.Tailscale` (UAC; publisher Tailscale Inc., from pkgs.tailscale.com), then sign in
   and name the machine in one step: `tailscale up --hostname=helpmate` (it prints a login link). Install the
   Tailscale app on your phone with the same account.
2. In the admin console (https://login.tailscale.com/admin/dns): **MagicDNS** on (the default) and **Enable
   HTTPS**. Enabling HTTPS publishes machine names such as `helpmate.<tailnet>.ts.net` in the public Certificate
   Transparency logs: the name becomes visible, but only your tailnet can reach it. The fixed name keeps the
   URL, the installed PWA and push subscriptions working if the demo moves to another laptop.
3. Build the web app and serve it from FastAPI (a single origin):
   ```powershell
   ./scripts/dev.ps1 -Prod                             # builds web/, FastAPI serves web/dist at /
   tailscale serve --bg http://127.0.0.1:8000          # https://helpmate.<tailnet>.ts.net (tailnet only)
   tailscale serve status                              # must say "(tailnet only)"
   ```
   The first HTTPS request takes ~20 s while the certificate is issued. The serve config **persists across
   reboots**; turn it off with `tailscale serve --https=443 off`. SSE chat streams incrementally through it
   (checked Sep 30), so no NDJSON fallback is needed.
4. **Public demo only** (O7, after 2FA and rate limiting are on): `tailscale funnel --bg 8000`. **Never with
   `HELPMATE_AUTH=dev`**: dev auth signs everyone in. Turn it off afterwards with `tailscale funnel --https=443 off`.
5. **iPhone:** open the URL in Safari → Share → **Add to Home Screen** → open it from the Home Screen → log in →
   Settings → *Enable notifications* → *Send a test notification*. Push only works from the installed app.
   **Android:** in Chrome, *Enable notifications* works directly. Measured Sep 30 on an iPhone 15 Pro: test push
   shown 1.0 s after sending.

## Troubleshooting

- **`ollama ps` shows CPU:** the driver is too old or Ollama isn't the official build; see step 2.
- **`ollama ps` shows a CPU/GPU split, but `nvidia-smi` shows free VRAM:** look for `cannot meet free memory
  target` in `%LOCALAPPDATA%\Ollama\server.log`. Set `LLAMA_ARG_FIT_TARGET=512` and restart Ollama (§2.2).
- **Settings in `server.log` show defaults (`OLLAMA_CONTEXT_LENGTH:0`, `KEEP_ALIVE:5m0s`):** Ollama was started
  from a process that was running before `setx`. Quit it from the tray and start it from the Start menu.
- **`gh`, `node` or `uv` "not recognized" right after installing:** open a new terminal (PATH is only read at start).
- **Test push says "sent" but nothing pops up:** Windows Settings → System → Notifications: notifications on,
  **Google Chrome** allowed, Do not disturb off. If the card says *blocked*, allow Notifications for the site
  (icon left of the address bar) and reload.
- **Push worked, then stopped after restarting the API:** the testbed keeps subscriptions in memory. Open
  Settings once; the page re-registers this browser automatically.
- **Chrome gets pushes but the iPhone doesn't, and the API log says `CERTIFICATE_VERIFY_FAILED ...
  web.push.apple.com`:** Windows downloads root CAs on demand, so Python's view of the store lacked Apple's root
  (COMODO ECC). `WebPushNotifier` verifies against certifi's bundle since Sep 30; update if you see this.
- **Voice: `TypeError: open() got an unexpected keyword argument 'metadata_errors'`:** PyAV 19 broke
  faster-whisper 1.2.1. `services/speech` pins `av<19`; run `uv sync --extra real` to get 18.x back.
- **Voice replies take many seconds to start:** check `/health` on :8001 says `kokoro-v1.0.onnx` (fp32). The
  int8 file is ~10x slower on CPUs without AVX-512 VNNI such as the i7-8750H.
- **Whisper slower than you'd like:** `SPEECH_WHISPER_LANGUAGE=en` skips language detection (1.2 s → 0.66 s for
  2.4 s of speech on the XPS) at the cost of auto-detecting other languages.
- **Docker ports reachable from the LAN:** every port in `infra/docker-compose.yml` must be written `127.0.0.1:<port>:<port>`.
- **Timezone errors in tests:** make sure `tzdata` is installed (`uv sync` handles it). Windows has no system timezone database.
- **Shell script fails with `\r` in a container:** `.gitattributes` forces LF. Run `git add --renormalize .` once.

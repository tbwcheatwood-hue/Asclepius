# Assistant

Local-first records for appointments, medications, reminders, notes, and memory. Open **http://localhost:9241/**. T.I.M. stays on **http://localhost:8070/**.

## Run

```bash
cd assistant
./start.sh
```

API: `http://127.0.0.1:9242`. The page on 9241 proxies `/api` to it.

```bash
cd assistant/backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
ASSISTANT_DB=/tmp/assistant-test.sqlite .venv/bin/python -m pytest -q
cd ../web && npm install && npm run typecheck
```

## Data

SQLite file: `assistant/data/assistant.sqlite`. Export downloads notes, memories, appointments, medications, and dose history. **Delete all records** in Settings removes those tables. Sample rows are marked and can be deleted from Today.

There is no cloud account. Copy the sqlite file to back it up. The app does not log medication names in the action list.

## Notifications and phone push

While the page on **9241** stays open, the app polls due reminders and appointment reminder times every 30 seconds.

- **Desktop:** `notify-send` when available.
- **Phone:** [GSConnect](https://extensions.gnome.org/extension/1319/kde-connect/) (`gnome-shell-extension-gsconnect`). Enable **Push due reminders to phone** in Settings and pick a paired device (or leave blank for the first connected phone).

Manual **Push to phone** on a reminder uses the same path without waiting for the due time.

Nothing runs when the browser is closed or the machine is off.

## Google Calendar (optional, read-only)

1. In [Google Cloud Console](https://console.cloud.google.com/), create an OAuth client (Desktop or Web) with redirect URI `http://127.0.0.1:9242/api/google/callback`.
2. In **Settings**, paste the client ID and secret, save, then **Connect Google Calendar**.
3. Use **Sync Google Calendar** on the Calendar screen (or **Sync now** in Settings). Google events appear with a **Google** badge and cannot be edited or cancelled here.

## Providers

Checked against current public docs and the local ALS install. No code was copied from these projects.

| Project | What was verified | Decision |
| --- | --- | --- |
| [Open WebUI calendar](https://docs.openwebui.com/features/calendar/) | Built-in events, recurrence, and AI tools. No Google/Outlook/CalDAV sync. License adds a branding restriction after v0.6.6. | Not embedded. Optional Google read sync is native OAuth; local appointments remain editable. |
| [MindRoom](https://github.com/mindroom-ai/mindroom) | Apache-2.0 app (SaaS directory is BUSL-1.1). Large agent stack, Python 3.12+. | Not embedded. Memory here is plain user-written text. |
| [MedTracker](https://github.com/damacus/med-tracker) | MIT, beta, self-hosted doses and stock. Its own docs say not to rely on it for clinical decisions. | Not embedded. Medication records are native and user-entered. |
| [Open Assistant](https://github.com/open-assistant-org/open-assistant) | BUSL-1.1. Personal use is allowed; production use is not. Docker app with many external connectors. | Not embedded. |

LM Studio's documented local API is OpenAI-compatible: `GET /v1/models` and `POST /v1/chat/completions` at `http://127.0.0.1:1234` ([docs](https://lmstudio.ai/docs/developer/openai-compat)). The app probes that URL. A chat call sends only the current message, and only after you select LM Studio, enter a model id, and check consent.

ALS (Loop Studio) defaults to `http://127.0.0.1:8888/`. In **Settings → AI provider**, choose **ALS Chat** and paste the **access token** from ALS Config. Quick save sends the current message to `POST /api/query` with `X-Router-Token`; JARVIS and your records stay separate unless you confirm a staged write.

With the provider set to **Off**, every screen still works.

## Safety

Chat will not save a note, memory, or reminder until you confirm. Questions about dose, diagnosis, or skipping a medication get a fixed refusal and are not sent to a model.

Repair prepares a diff. Approving it writes `assistant/repairs/proposal-N.diff` and does not change the running program, run a shell command, or commit. A safe isolated apply and rollback is not available here, so repair stays read-only.

## Accessibility

Keyboard access, visible focus, labeled controls, 44px targets, 100/125/150% text, a high-contrast theme, and reduced motion. Speech input uses the browser Web Speech API when that browser has it.

## JARVIS integration (Personal Jarvis)

Voice, agents, and tools run in **[Personal Jarvis](https://github.com/tbckdev/PersonalJarvis)**. This repo does not vendor it; point at your clone (default `~/Downloads/PersonalJarvis-main`).

| Layer | Port | Role |
| --- | --- | --- |
| JARVIS (headless) | **47821** | `jarvis serve` or launcher `--headless` |
| This UI | **9241** | Records + embedded JARVIS on the **JARVIS** tab |
| Records API | **9242** | Calendar, meds, reminders, SQLite, GSConnect, Google |

```bash
export JARVIS_ROOT="$HOME/Downloads/PersonalJarvis-main"
assistant/scripts/jarvis.sh install   # once (Python 3.11+, creates assistant/jarvis-venv)
assistant/scripts/jarvis.sh start   # terminal 1 → http://127.0.0.1:47821

cd assistant && ./start.sh          # terminal 2 → http://localhost:9241
```

Optional: `JARVIS_AUTO_START=1 ./start.sh` starts JARVIS in the background when the venv is installed.

Configure models and API keys inside JARVIS. The records app’s Quick save tab stays separate unless you confirm a staged write.

**LM Studio + Ollama:** With both local servers running, register them in `jarvis.toml`:

```bash
assistant/scripts/jarvis-wire-locals.py
# or: assistant/scripts/jarvis.sh wire-locals
```

That sets **LM Studio (local)** and **Ollama** in `jarvis.toml`, picks the first loaded chat model on each side, then restart JARVIS.

In JARVIS open **API Keys & Providers → Brain** and activate **LM Studio (local)** or **Ollama (local)**. The **Local models** section is still Ollama-centric (downloads); LM Studio models are listed on the LM Studio card after the server is running.

### JARVIS ↔ Assistant project (read/write/edit)

One-time link installs a JARVIS skill, wiki page, Agentic IDE recents, and file-search roots:

```bash
assistant/scripts/jarvis.sh link-assistant
```

Then in JARVIS: open **`agent-routing-lab`** in the **Agentic IDE** (full repo edit access), or call the loopback **Assistant Bridge** on port **9242**:

- `GET /api/jarvis-bridge/manifest` — paths, URLs, test commands
- `GET /api/jarvis-bridge/tree?path=assistant` — listing
- `GET|PUT /api/jarvis-bridge/file?path=…` — read/write source files under the repo

Bridge endpoints are **localhost-only**. Live user records still use the normal `/api/*` routes on **9242**.

### Dismissals and destructive actions

Acknowledging reminders, canceling appointments, deleting records, and bulk **Dismiss all due** require a confirmation dialog. The API rejects the action unless `confirmed: true` is sent in the body.

### Phone on your Wi‑Fi (LAN)

Settings → **Phone on your Wi‑Fi** → **Enable LAN access**, then restart with `assistant/start.sh` so the UI and API listen on your LAN. Pair your phone with the six-digit code. LAN sessions use bearer tokens plus CSRF on writes; public IPs are rejected.

**Quick save** in this app only stages `note:` / `remember:` / `remind me:` / `project:` with confirmation.

## Mobile access outside Wi‑Fi (ngrok)

| Port | Service | Expose via ngrok? |
| --- | --- | --- |
| **9241** | React UI (Vite) — open this in the browser | **Yes** |
| **9242** | FastAPI — `/api` only via the UI proxy | **No** (loopback) |

Setup: `sudo snap install ngrok`, `ngrok config add-authtoken <token>`, edit `assistant/secrets/mobile-tunnel.env` (see `config/mobile-tunnel.env.example`). Edge auth: `assistant/config/tp.yml` (Google OAuth).

```bash
/home/livingroom/agent-routing-lab/assistant/scripts/mobile-tunnel.sh
```

Same as:

```bash
ngrok http 127.0.0.1:9241 \
  --url https://your-nomad-subdomain.ngrok-free.dev \
  --traffic-policy-file /home/livingroom/agent-routing-lab/assistant/config/tp.yml
```

### NOMAD vs Assistant (two tunnels)

| URL | Local | App |
| --- | --- | --- |
| `https://your-nomad-subdomain.ngrok-free.dev` | **8080** | **NOMAD** (keep your existing ngrok) |
| Printed by `mobile-tunnel.sh` | **9241** | **Assistant** (second ngrok on inspector **:4041**) |

`mobile-tunnel.sh` does **not** stop NOMAD’s ngrok. Leave `NGROK_URL` empty for a random Assistant URL, or set a **second** reserved domain in `secrets/mobile-tunnel.env`.

### Phone instructions (Assistant URL only — not the NOMAD link)

1. Run `/home/livingroom/agent-routing-lab/assistant/scripts/mobile-tunnel.sh`
2. On the phone (cellular / other Wi‑Fi), open the **ASSISTANT** HTTPS URL from the terminal (QR), **not** `your NOMAD domain` (that is NOMAD).
3. Google sign-in → **Pair this device** → six-digit code from the terminal.
4. Ctrl+C stops the Assistant tunnel; NOMAD on :4040 keeps running.

## Limits

Google Calendar is read-only sync, not two-way. No background notification daemon beyond the open browser tab. ALS chat uses your Loop Studio routing; keep the token private. Generated text is labeled as generated, not as a fact. This is not a medical device.

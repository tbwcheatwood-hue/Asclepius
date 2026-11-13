# Asclepius

Local medical assistant for appointments, medication records, reminders, notes, and a personal health record on this computer.

Copyright © 2026 Timothy Cheatwood. All rights reserved.

This repository does not include a `LICENSE` file. The copyright notice does not grant permission to copy, modify, or redistribute the code.

The program lives in `assistant/`. Open **http://localhost:9241/** after it starts. Records stay in SQLite on the machine. There is no cloud account.

## What you need

- Node.js 20 or newer
- Python 3.11 or newer
- A browser
- Optional: [Personal Jarvis](https://github.com/tbckdev/PersonalJarvis) if you want the J.A.R.V.I.S. panel
- Optional: Docker, if you want Fasten Health on-prem
- Optional: `notify-send` and [GSConnect](https://extensions.gnome.org/extension/1319/kde-connect/) for reminder notifications

## 1. Clone and install

```bash
git clone https://github.com/tbwcheatwood-hue/Asclepius.git
cd Asclepius
python3 -m venv assistant/backend/.venv
assistant/backend/.venv/bin/pip install -r assistant/backend/requirements.txt
cd assistant/web && npm install && cd ../..
```

Meds Tracker uses a local copy of [MedTracker](https://github.com/terra-femme/MedTracker) in `vendor/MedTracker`. That upstream checkout does not ship a license file. The copy here includes UI changes used by this app: a wide desktop layout and a List view. Its database is created on your machine and is not in git.

## 2. Start Asclepius

```bash
cd assistant
./start.sh
```

Then open **http://127.0.0.1:9241/**. Use `http`, not `https`.

| Port | Role |
|------|------|
| **9241** | The web app |
| **9242** | The records API. The page proxies `/api` to it |
| **9255** | Meds Tracker, started with the app when `MEDTRACKER_AUTO_START` is not `0` |
| **47821** | J.A.R.V.I.S., only if you start Personal Jarvis |
| **9090** | Fasten Health on-prem, HTTPS inside Docker, only if you start it |
| **9091** | Local HTTP front for that Fasten instance |

`./start.sh` starts the API and the web app. It can also start Meds Tracker. It does not start Fasten or J.A.R.V.I.S. unless you turn those on as below.

## 3. Use the sections

The left navigation is the product. Speech input is on that same rail. A request is handled with the tab you are on, and a named action can use another tab. Deletes, dismissals, and new staged records wait for confirmation.

1. **Today.** Coming appointments and reminders. Dismissing due notices asks you to confirm.
2. **J.A.R.V.I.S.** The embedded Personal Jarvis panel, after that program is running. Open conversation stays there. Models and API keys are configured inside J.A.R.V.I.S., not in this repository.
3. **Calendar.** Local appointments, plus optional read-only Google events. Google events cannot be edited or cancelled here. Month, week, and day controls stay on the calendar page.
4. **Meds Tracker.** The embedded tracker has its own sign-in, schedule, and **List** of medications stored in its database. Assistant medication records on the API are separate. This app does not give dosing advice. A question about a dose, a diagnosis, or skipping a medication gets a fixed refusal and is not sent to a model.
5. **Reminders.** Create, acknowledge, delete, or push a reminder. Acknowledge, delete, and push ask you to confirm when J.A.R.V.I.S. is asked to do them. The on-screen push button sends immediately.
6. **Notes.** Notes you type. Deleting one asks you to confirm.
7. **Fasten Health.** Shows whether Fasten Health on-prem is running. You enter records there yourself or upload FHIR bundles you already exported. It does not sign in to clinics. J.A.R.V.I.S. can check that it is running. It does not read those records unless you later add that access yourself.
8. **Quick save.** Stages `note:`, `remember:`, `remind me:`, and `project:` until you confirm.
9. **Settings.** Provider, Google Calendar, LAN pairing, and delete-all. Tokens you paste here stay in the local database.

While the page stays open, due reminders are checked about every 30 seconds. Desktop notifications use `notify-send` when it exists. Phone push uses GSConnect when you enable it in Settings. Nothing is sent when the browser is closed or the computer is off.

## 4. Start J.A.R.V.I.S.

J.A.R.V.I.S. is [Personal Jarvis](https://github.com/tbckdev/PersonalJarvis). This repository does not include it.

```bash
export JARVIS_ROOT="$HOME/Downloads/PersonalJarvis-main"
assistant/scripts/jarvis.sh install
assistant/scripts/jarvis.sh start
```

`install` needs Python 3.11 or newer and creates `assistant/jarvis-venv`, which is not committed. Then run `cd assistant && ./start.sh` and open the J.A.R.V.I.S. tab.

`JARVIS_AUTO_START=1 ./start.sh` starts it in the background when that virtualenv already exists.

## 5. Start Fasten Health

Docker is required. From the repository root:

```bash
bash assistant/scripts/fasten.sh start
```

The script runs Fasten Health on-prem and a local HTTP front at `http://127.0.0.1:9091`. The Fasten Health section embeds that address. The first screen asks you to create an encryption key. That key stays on this computer. Fasten’s database and certificates are created under `vendor/fasten-onprem/` and are not part of git.

## 6. Optional Google Calendar

1. In Google Cloud Console, create an OAuth client with redirect URI `http://127.0.0.1:9242/api/google/callback`.
2. In **Settings**, paste the client ID and secret, save, then connect Google Calendar.
3. Sync from the calendar page or from Settings.

Synced events are read-only. The client secret stays in the local SQLite file.

## 7. Phone on the same Wi-Fi

In **Settings**, enable LAN access, then restart `assistant/start.sh` so the app listens on the network. Pair the phone with the six-digit code. LAN writes need the session token and CSRF. Public internet addresses are rejected.

A tunnel in `assistant/scripts/mobile-tunnel.sh` is optional and separate. Copy `assistant/config/mobile-tunnel.env.example` to `assistant/secrets/mobile-tunnel.env`, put your ngrok authtoken only in that untracked file, and copy `assistant/config/tp.yml.example` to `assistant/config/tp.yml` if you use the Google sign-in gate. Do not commit those filled-in files.

## 8. Checks

```bash
cd assistant/backend
ASSISTANT_DB=/tmp/assistant-test.sqlite .venv/bin/python -m pytest -q
cd ../web && npm run typecheck
```

## Data and limits

The database is `assistant/data/assistant.sqlite`. Export downloads notes, memories, appointments, medications, and dose history. **Delete all records** in Settings clears those tables. Copy the sqlite file if you want a backup.

Google Calendar sync is read-only. There is no notification daemon beyond the open browser tab. Generated provider text is labeled as generated, not as a fact. This is not a medical device.

Repair can write a diff under `assistant/repairs/`. Approving it does not change the running program.

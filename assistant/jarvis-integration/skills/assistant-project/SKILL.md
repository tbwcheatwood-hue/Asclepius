---
schema_version: "1"
name: assistant-project
version: "1.0.0"
description: |
  Full read/write/edit access to the Timothy Assistant project (calendar, meds,
  reminders, JARVIS embed, SQLite API). Use the Agentic IDE workspace or the
  loopback Assistant Bridge API on port 9242.
when_to_use: >-
  Use when the user asks to change the Assistant app, records API, web UI,
  JARVIS integration scripts, tests, or SQLite data for assistant/.
category: engineering
tags: [assistant, agent-routing-lab, local-first, api]
author: assistant-integration
license: Apache-2.0
requires_tools: []
risk_policy:
  default_tier: monitor
---

# Assistant project (agent-routing-lab)

You may **read, write, and edit every part** of this project when the user asks.
Prefer the paths below so edits stay consistent with how the app runs locally.

## Locations

| What | Path |
| --- | --- |
| Repository root | `/home/livingroom/agent-routing-lab` |
| Assistant app | `/home/livingroom/agent-routing-lab/assistant` |
| Records API (FastAPI) | `assistant/backend/app/` |
| Web UI (Vite/React) | `assistant/web/src/` |
| SQLite data | `assistant/data/assistant.sqlite` |
| JARVIS scripts | `assistant/scripts/jarvis.sh`, `jarvis-wire-locals.py` |
| Start everything | `assistant/start.sh` |

## URLs (this machine)

- UI: `http://127.0.0.1:9241/`
- API: `http://127.0.0.1:9242/`
- JARVIS headless: `http://127.0.0.1:47821/`

## Agentic IDE

Open **`/home/livingroom/agent-routing-lab`** as the workspace folder. All agents
and terminals may edit any file under that tree (backend, web, scripts, README).

## Assistant Bridge API (loopback only)

Manifest and file I/O without driving the browser UI:

```bash
curl -s http://127.0.0.1:9242/api/jarvis-bridge/manifest
curl -s "http://127.0.0.1:9242/api/jarvis-bridge/tree?path=assistant"
curl -s "http://127.0.0.1:9242/api/jarvis-bridge/file?path=assistant/README.md"
curl -s -X PUT http://127.0.0.1:9242/api/jarvis-bridge/file \
  -H 'Content-Type: application/json' \
  -d '{"path":"assistant/jarvis-integration/notes.txt","content":"..."}'
```

Writes are restricted to the repo root and rejected from the public internet.

## Records API (user data)

Use normal Assistant endpoints on **9242** for live data (appointments, meds,
reminders, notes, memories, settings, Google sync, LAN). Destructive actions
need `{"confirmed": true}` in the JSON body.

## Verify after code changes

```bash
cd /home/livingroom/agent-routing-lab/assistant/backend
ASSISTANT_DB=/tmp/assistant-test.sqlite .venv/bin/python -m pytest -q
cd ../web && npm run typecheck
```

Restart `assistant/start.sh` after backend route changes so port **9242** is current.

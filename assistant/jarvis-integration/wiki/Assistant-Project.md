# Assistant project

Local-first **Assistant** lives in `agent-routing-lab/assistant`.

- **9241** — React UI (Today, JARVIS tab, calendar, meds, settings)
- **9242** — FastAPI + SQLite (`data/assistant.sqlite`)
- **47821** — Personal Jarvis (headless)

JARVIS is linked via `assistant/scripts/jarvis-link-assistant.sh` (skill +
Agentic IDE recents + bridge API). Ask JARVIS to open the repo in the Agentic
IDE or use `/api/jarvis-bridge/*` on loopback.

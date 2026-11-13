#!/usr/bin/env bash
# Give Personal Jarvis full context + tooling for the assistant repo.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO="$(cd "$ROOT/.." && pwd)"
INTEG="$ROOT/jarvis-integration"
VENV="$ROOT/jarvis-venv"
if [[ -n "${LOCALAPPDATA:-}" ]]; then
  JARVIS_DATA="$LOCALAPPDATA/Jarvis"
else
  JARVIS_DATA="$HOME/.jarvis"
fi

mkdir -p "$JARVIS_DATA/skills/assistant-project"
cp -f "$INTEG/skills/assistant-project/SKILL.md" "$JARVIS_DATA/skills/assistant-project/SKILL.md"

VAULT="$HOME/Downloads/PersonalJarvis-main/wiki/obsidian-vault"
if [[ -d "$VAULT" ]]; then
  cp -f "$INTEG/wiki/Assistant-Project.md" "$VAULT/Assistant-Project.md"
fi

if [[ -x "$VENV/bin/python" ]]; then
  "$VENV/bin/python" - "$REPO" <<'PY'
import sys
from pathlib import Path

repo = Path(sys.argv[1]).resolve()
from jarvis.agentic_ide import recents

recents.remember(str(repo), terminals=2, agents={"claude": 1, "codex": 1})
print(f"Agentic IDE recents: {repo}")
PY
fi

if [[ -x "$ROOT/backend/.venv/bin/python" ]]; then
  ASSISTANT_DB="$ROOT/data/assistant.sqlite" "$ROOT/backend/.venv/bin/python" - "$REPO" "$ROOT" <<'PY'
import sqlite3
import sys
from pathlib import Path

repo, assistant = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
db = Path(__import__("os").environ["ASSISTANT_DB"])
roots = f"{assistant}\n{repo}"
conn = sqlite3.connect(db)
conn.execute(
    """INSERT INTO settings (key, value) VALUES ('file_search_roots', ?)
       ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
    (roots,),
)
conn.commit()
conn.close()
print("Assistant file_search_roots updated")
PY
fi

echo "Installed JARVIS skill → $JARVIS_DATA/skills/assistant-project/"
echo "Open Agentic IDE workspace: $REPO"
echo "Bridge API: http://127.0.0.1:9242/api/jarvis-bridge/manifest"
echo "Re-scan skills in JARVIS (or restart) if the skill does not appear yet."

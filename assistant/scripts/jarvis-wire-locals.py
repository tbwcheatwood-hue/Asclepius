#!/usr/bin/env python3
"""Register LM Studio (local-openai) and Ollama in Personal Jarvis jarvis.toml."""

from __future__ import annotations

import json
import re
import sys

import httpx

LMSTUDIO = "http://127.0.0.1:1234"
OLLAMA = "http://127.0.0.1:11434"

EMBED_RE = re.compile(r"embed", re.I)


def _chat_models_lmstudio() -> list[str]:
    try:
        response = httpx.get(f"{LMSTUDIO.rstrip('/')}/v1/models", timeout=4.0)
        response.raise_for_status()
        data = response.json().get("data") or []
        ids = [str(item.get("id", "")).strip() for item in data if item.get("id")]
        return [mid for mid in ids if mid and not EMBED_RE.search(mid)]
    except httpx.HTTPError as exc:
        print(f"LM Studio not reachable at {LMSTUDIO}: {exc}", file=sys.stderr)
        return []


def _chat_models_ollama() -> list[str]:
    try:
        response = httpx.get(f"{OLLAMA.rstrip('/')}/api/tags", timeout=4.0)
        response.raise_for_status()
        models = response.json().get("models") or []
        names = [str(item.get("name", "")).strip() for item in models if item.get("name")]
        return [name for name in names if name and not EMBED_RE.search(name)]
    except httpx.HTTPError as exc:
        print(f"Ollama not reachable at {OLLAMA}: {exc}", file=sys.stderr)
        return []


def main() -> int:
    from jarvis.core.config import resolve_config_path
    from jarvis.core.config_writer import (
        set_brain_provider_model,
        set_provider_base_url,
        set_provider_flag,
    )

    path = resolve_config_path()
    lm_models = _chat_models_lmstudio()
    ollama_models = _chat_models_ollama()

    set_provider_base_url("lmstudio", LMSTUDIO, path=path)
    set_provider_base_url("local-openai", LMSTUDIO, path=path)
    set_provider_flag("ollama", "autostart", True, path=path)
    set_provider_base_url("ollama", OLLAMA, path=path)

    if lm_models:
        pick = lm_models[0]
        for provider in ("lmstudio", "local-openai"):
            set_brain_provider_model(
                provider,
                model=pick,
                deep_model=pick,
                tool_model=pick,
                path=path,
            )
        print(f"LM Studio (lmstudio): {LMSTUDIO} model={pick}")
    else:
        print(f"lmstudio: saved base URL {LMSTUDIO}; load a model in LM Studio and pick it in JARVIS.")

    if ollama_models:
        pick = ollama_models[0]
        set_brain_provider_model(
            "ollama",
            model=pick,
            deep_model=pick,
            tool_model=pick,
            path=path,
        )
        print(f"ollama: {OLLAMA} model={pick}")
    else:
        print(
            "ollama: saved base URL; no chat models pulled yet "
            "(only embedding tags found). Example: ollama pull qwen3.5:4b",
        )

    print(f"Updated {path}")
    print("Restart JARVIS (assistant/scripts/jarvis.sh start) if it was already running.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

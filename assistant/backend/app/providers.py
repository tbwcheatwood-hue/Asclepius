"""Isolated provider adapters for LM Studio and ALS (Loop Studio) chat."""

from __future__ import annotations

from typing import Any

import httpx

LMSTUDIO_DEFAULT = "http://127.0.0.1:1234"
ALS_DEFAULT = "http://127.0.0.1:8888"

# LM Studio's local server documents an OpenAI-compatible API:
# https://lmstudio.ai/docs/developer/openai-compat
def probe_lmstudio(base_url: str, client: httpx.Client | None = None) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/v1/models"
    own = client is None
    http = client or httpx.Client(timeout=2.0)
    try:
        response = http.get(url)
    except httpx.HTTPError:
        return {
            "id": "lmstudio",
            "state": "unreachable",
            "models": [],
            "chat": True,
            "endpoint": url,
            "detail": "LM Studio did not respond. Start its local server or edit the endpoint.",
        }
    finally:
        if own:
            http.close()
    if response.status_code != 200:
        return {
            "id": "lmstudio",
            "state": "error",
            "models": [],
            "chat": True,
            "endpoint": url,
            "detail": f"LM Studio returned HTTP {response.status_code}.",
        }
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    models = []
    for item in payload.get("data") or []:
        model_id = item.get("id")
        if isinstance(model_id, str) and model_id:
            models.append(model_id)
    return {
        "id": "lmstudio",
        "state": "connected" if models else "no-models",
        "models": models,
        "chat": True,
        "endpoint": url,
        "detail": "OpenAI-compatible /v1/models. Chat uses /v1/chat/completions and sends only the current message.",
    }


def probe_als(
    base_url: str,
    api_token: str = "",
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    root = base_url.rstrip("/")
    url = root + "/"
    own = client is None
    http = client or httpx.Client(timeout=4.0)
    token = api_token.strip()
    chat = bool(token)
    try:
        response = http.get(url)
    except httpx.HTTPError:
        return {
            "id": "als",
            "state": "unreachable",
            "models": [],
            "chat": chat,
            "endpoint": root + "/api/query",
            "detail": "ALS did not respond on this address.",
        }
    finally:
        if own:
            http.close()
    state = "reachable" if response.status_code < 500 else "error"
    detail = "Loop Studio is up. Add an access token (Config → Access token in ALS) to enable chat."
    if token:
        own2 = client is None
        http2 = client or httpx.Client(timeout=4.0)
        try:
            auth = http2.get(
                root + "/api/models",
                headers={"X-Router-Token": token},
            )
            if auth.status_code == 401:
                state = "unauthorized"
                detail = "Token rejected. Copy the access token from ALS Config and save it here."
            elif auth.status_code == 503:
                state = "no-token-configured"
                detail = "ALS requires a token on the server. Run setup-token.sh in the ALS install."
            elif auth.status_code < 500:
                state = "connected"
                detail = "POST /api/query with your message (orchestrated ALS chat)."
        except httpx.HTTPError:
            state = "error"
            detail = "Could not reach ALS /api/query."
        finally:
            if own2:
                http2.close()
    return {
        "id": "als",
        "state": state,
        "models": [],
        "chat": chat and state == "connected",
        "endpoint": root + "/api/query",
        "detail": detail,
    }


def complete_als_chat(
    base_url: str,
    api_token: str,
    user_text: str,
    client: httpx.Client | None = None,
) -> str:
    token = api_token.strip()
    if not token:
        raise ValueError("ALS access token is missing. Add it under Settings → AI provider.")
    url = base_url.rstrip("/") + "/api/query"
    body = {"prompt": user_text}
    headers = {"Content-Type": "application/json", "X-Router-Token": token}
    own = client is None
    http = client or httpx.Client(timeout=120.0)
    try:
        response = http.post(url, json=body, headers=headers)
        response.raise_for_status()
        payload = response.json()
    finally:
        if own:
            http.close()
    if not payload.get("success", True) and payload.get("error"):
        raise RuntimeError(str(payload["error"]))
    responses = payload.get("responses")
    if not isinstance(responses, list):
        raise RuntimeError("ALS returned an unexpected response shape.")
    parts: list[str] = []
    for item in responses:
        if not isinstance(item, dict):
            continue
        for key in ("response", "content", "text", "output", "message"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
                break
        model = item.get("model") or item.get("provider")
        if model and parts:
            parts[-1] = f"[{model}] {parts[-1]}"
    if not parts:
        raise RuntimeError("ALS returned no assistant text.")
    return "\n\n".join(parts)


def complete_lmstudio(base_url: str, model: str, user_text: str, client: httpx.Client | None = None) -> str:
    url = base_url.rstrip("/") + "/v1/chat/completions"
    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You help organize the user's own notes. "
                    "Do not give medical advice, dosing instructions, or diagnosis. "
                    "If asked for medical advice, say you cannot provide it."
                ),
            },
            {"role": "user", "content": user_text},
        ],
        "temperature": 0.2,
    }
    own = client is None
    http = client or httpx.Client(timeout=30.0)
    try:
        response = http.post(url, json=body)
        response.raise_for_status()
        payload = response.json()
        return str(payload["choices"][0]["message"]["content"])
    finally:
        if own:
            http.close()

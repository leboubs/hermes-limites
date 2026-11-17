"""Backend du widget « limites » : abonnements Claude, Codex, OpenCode Go et
dépense OpenRouter du jour.

Chaque source est interrogée ici, côté passerelle — les jetons OAuth restent sur
la machine et ne transitent jamais par la page. Une source en panne renvoie
``{"ok": false, "error": ...}`` sans empêcher les autres de répondre.

Routes :
    GET /data   -> instantané complet (cache mémoire 45 s)
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:
    from fastapi import APIRouter
except ImportError:  # le fichier est aussi importé par les tests hors passerelle
    APIRouter = None  # type: ignore[assignment]

PARIS = ZoneInfo("Europe/Paris")
HERMES_HOME = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))
CACHE_TTL = 45.0
HTTP_TIMEOUT = 12.0

_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {"at": 0.0, "payload": None}


# --------------------------------------------------------------------------
# utilitaires
# --------------------------------------------------------------------------


def _env(name: str) -> str:
    """Variable d'environnement, sinon la ligne du .env de Hermes."""
    value = os.environ.get(name, "").strip()
    if value:
        return value
    for path in (HERMES_HOME / ".env", Path.home() / ".hermes" / ".env"):
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith(f"{name}="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            continue
    return ""


DEFAULT_HEADERS = {
    # Sans User-Agent de navigateur/CLI, trois des quatre backends répondent 403.
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36",
    "Accept": "application/json",
}


def _http_json(url: str, headers: dict[str, str]) -> Any:
    merged = dict(DEFAULT_HEADERS)
    merged.update(headers)
    request = urllib.request.Request(url, headers=merged, method="GET")
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def _iso(value: Any) -> str | None:
    """Époque (s ou ms) ou ISO -> ISO 8601 en heure de Paris."""
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
            number = float(value)
            if number > 1e11:
                number /= 1000.0
            return datetime.fromtimestamp(number, tz=timezone.utc).astimezone(PARIS).isoformat()
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(PARIS).isoformat()
    except (ValueError, OSError, OverflowError):
        return None
    return None


def _percent(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(100.0, number))


# --------------------------------------------------------------------------
# Claude (abonnement, OAuth Claude Code)
# --------------------------------------------------------------------------


def claude_limits() -> dict[str, Any]:
    creds = Path.home() / ".claude" / ".credentials.json"
    try:
        token = json.loads(creds.read_text(encoding="utf-8"))["claudeAiOauth"]["accessToken"]
    except (OSError, KeyError, ValueError) as exc:
        return {"ok": False, "error": f"jeton Claude illisible ({exc.__class__.__name__})"}
    try:
        payload = _http_json(
            "https://api.anthropic.com/api/oauth/usage",
            {
                "Authorization": f"Bearer {token}",
                "anthropic-beta": "oauth-2025-04-20",
                "User-Agent": "claude-code/2.0.0",
            },
        )
    except urllib.error.HTTPError as exc:
        hint = "jeton expiré ?" if exc.code in (401, 403) else ""
        return {"ok": False, "error": f"HTTP {exc.code} {hint}".strip()}
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return {"ok": False, "error": f"réseau ({exc.__class__.__name__})"}

    windows = []
    for key, label in (("five_hour", "Fenêtre 5 h"), ("seven_day", "Semaine")):
        block = payload.get(key) or {}
        percent = _percent(block.get("utilization"))
        if percent is None:
            continue
        windows.append({"label": label, "percent": percent, "resets_at": _iso(block.get("resets_at"))})
    if not windows:
        return {"ok": False, "error": "réponse sans fenêtre"}
    extra = payload.get("extra_usage") or {}
    return {
        "ok": True,
        "windows": windows,
        "plan": "abonnement",
        "credits_enabled": bool(extra.get("is_enabled")),
    }


# --------------------------------------------------------------------------
# Codex (abonnement ChatGPT)
# --------------------------------------------------------------------------


def codex_limits() -> dict[str, Any]:
    auth = Path.home() / ".codex" / "auth.json"
    try:
        data = json.loads(auth.read_text(encoding="utf-8"))
        tokens = data.get("tokens") or {}
        token = tokens.get("access_token") or data.get("OPENAI_API_KEY") or ""
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": f"auth Codex illisible ({exc.__class__.__name__})"}
    if not token:
        return {"ok": False, "error": "aucun jeton Codex"}
    headers = {
        "Authorization": f"Bearer {token}",
        "originator": "codex_cli_rs",
    }
    if tokens.get("account_id"):
        headers["chatgpt-account-id"] = str(tokens["account_id"])
    try:
        payload = _http_json("https://chatgpt.com/backend-api/codex/usage", headers)
    except urllib.error.HTTPError as exc:
        hint = "jeton expiré ?" if exc.code in (401, 403) else ""
        return {"ok": False, "error": f"HTTP {exc.code} {hint}".strip()}
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return {"ok": False, "error": f"réseau ({exc.__class__.__name__})"}

    rate = payload.get("rate_limit") or {}
    windows = []
    labels = {"primary_window": "Fenêtre principale", "secondary_window": "Fenêtre secondaire"}
    for key, label in labels.items():
        block = rate.get(key) or {}
        percent = _percent(block.get("used_percent"))
        if percent is None:
            continue
        seconds = block.get("limit_window_seconds")
        if isinstance(seconds, (int, float)) and seconds > 0:
            hours = seconds / 3600.0
            label = "Semaine" if hours >= 100 else f"Fenêtre {hours:.0f} h"
        windows.append(
            {
                "label": label,
                "percent": percent,
                "resets_at": _iso(block.get("reset_at") or block.get("reset_after_seconds")),
            }
        )
    if not windows:
        return {"ok": False, "error": "réponse sans fenêtre"}
    credits = payload.get("credits") or {}
    return {
        "ok": True,
        "windows": windows,
        "plan": payload.get("plan_type"),
        "limit_reached": bool(rate.get("limit_reached")),
        "credits": credits.get("balance") if credits.get("has_credits") else None,
    }


# --------------------------------------------------------------------------
# OpenCode Go (abonnement)
# --------------------------------------------------------------------------


def opencode_limits() -> dict[str, Any]:
    key = _env("OPENCODE_GO_API_KEY")
    if not key:
        return {"ok": False, "error": "OPENCODE_GO_API_KEY absente"}
    try:
        payload = _http_json(
            "https://opencode.ai/zen/go/v1/usage",
            {"Authorization": f"Bearer {key}"},
        )
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": f"HTTP {exc.code}"}
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return {"ok": False, "error": f"réseau ({exc.__class__.__name__})"}

    usage = payload.get("usage") or {}
    windows = []
    for key_name, label in (("rolling", "Fenêtre glissante"), ("weekly", "Semaine"), ("monthly", "Mois")):
        block = usage.get(key_name) or {}
        percent = _percent(block.get("percent"))
        if percent is None:
            continue
        windows.append({"label": label, "percent": percent, "resets_at": _iso(block.get("resetsAt"))})
    if not windows:
        return {"ok": False, "error": "réponse sans fenêtre"}
    return {"ok": True, "windows": windows, "plan": "go"}


# --------------------------------------------------------------------------
# OpenRouter : plafond de clé + dépense du jour (comptabilité locale Hermes)
# --------------------------------------------------------------------------


def _profile_databases() -> list[tuple[str, Path]]:
    """Toutes les bases Hermes : profil par défaut puis chaque profil nommé.

    La dépense n'est pas centralisée : un sous-agent ou un worker tourne sous son
    propre profil et écrit dans SA base. Lire seulement celle du profil courant
    affichait 0 $ alors que Charlie avait dépensé la journée.
    """
    databases: list[tuple[str, Path]] = [("default", HERMES_HOME / "state.db")]
    for db in sorted((HERMES_HOME / "profiles").glob("*/state.db")):
        databases.append((db.parent.name, db))
    return [(name, path) for name, path in databases if path.exists()]


def _openrouter_today() -> tuple[float | None, dict[str, float]]:
    """Dépense OpenRouter depuis minuit (Paris), total et par profil."""
    midnight = datetime.now(tz=PARIS).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    per_profile: dict[str, float] = {}
    seen_any = False
    for name, db in _profile_databases():
        try:
            with sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5) as conn:
                row = conn.execute(
                    """
                    SELECT COALESCE(SUM(CASE WHEN actual_cost_usd > 0 THEN actual_cost_usd
                                             ELSE estimated_cost_usd END), 0)
                      FROM session_model_usage
                     WHERE last_seen >= ?
                       AND (billing_provider LIKE '%openrouter%'
                            OR billing_base_url LIKE '%openrouter%')
                    """,
                    (midnight,),
                ).fetchone()
        except sqlite3.Error:
            continue
        seen_any = True
        amount = float(row[0]) if row and row[0] else 0.0
        if amount > 0:
            per_profile[name] = round(amount, 4)
    if not seen_any:
        return None, {}
    return round(sum(per_profile.values()), 4), per_profile


def openrouter_limits() -> dict[str, Any]:
    key = _env("OPENROUTER_API_KEY")
    if not key:
        return {"ok": False, "error": "OPENROUTER_API_KEY absente"}
    headers = {"Authorization": f"Bearer {key}"}
    result: dict[str, Any] = {"ok": True}
    try:
        keyinfo = _http_json("https://openrouter.ai/api/v1/key", headers).get("data") or {}
        budgets = keyinfo.get("budgets") or []
        budget = budgets[0] if budgets else {}
        result["limit"] = budget.get("limit_usd", keyinfo.get("limit"))
        result["remaining"] = budget.get("remaining_usd", keyinfo.get("limit_remaining"))
        result["window_spend"] = budget.get("spend_usd")
        result["reset"] = budget.get("reset_interval") or keyinfo.get("limit_reset")
        result["resets_at"] = _iso(budget.get("resets_at") or keyinfo.get("resets_at"))
    except (urllib.error.URLError, TimeoutError, ValueError, AttributeError) as exc:
        result = {"ok": False, "error": f"clé ({exc.__class__.__name__})"}
    try:
        credits = _http_json("https://openrouter.ai/api/v1/credits", headers).get("data") or {}
        result["credits_total"] = credits.get("total_credits")
        result["credits_used"] = credits.get("total_usage")
    except (urllib.error.URLError, TimeoutError, ValueError):
        pass
    result["today_usd"], result["today_by_profile"] = _openrouter_today()
    return result


# --------------------------------------------------------------------------
# agrégation
# --------------------------------------------------------------------------


SOURCES = {
    "claude": ("Claude", claude_limits),
    "codex": ("Codex", codex_limits),
    "opencode": ("OpenCode Go", opencode_limits),
    "openrouter": ("OpenRouter", openrouter_limits),
}


def collect() -> dict[str, Any]:
    sources: dict[str, Any] = {}
    for source_id, (label, reader) in SOURCES.items():
        try:
            entry = reader()
        except Exception as exc:  # une source ne casse jamais l'instantané
            entry = {"ok": False, "error": f"{exc.__class__.__name__}: {exc}"[:160]}
        entry["label"] = label
        sources[source_id] = entry
    return {
        "fetched_at": datetime.now(tz=PARIS).isoformat(),
        "timezone": "Europe/Paris",
        "sources": sources,
    }


def snapshot(force: bool = False) -> dict[str, Any]:
    now = time.time()
    with _LOCK:
        cached = _CACHE["payload"]
        if cached is not None and not force and now - float(_CACHE["at"]) < CACHE_TTL:
            return cached
    payload = collect()
    with _LOCK:
        _CACHE["payload"] = payload
        _CACHE["at"] = now
    return payload


if APIRouter is not None:
    router = APIRouter()

    @router.get("/data")
    def data(force: bool = False):
        return snapshot(force=force)
else:  # pragma: no cover - import hors passerelle
    router = None

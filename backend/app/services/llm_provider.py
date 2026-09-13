"""
Admin-configurable LLM provider - one platform-wide provider, chosen by an
admin, used by drift explanation (services/summary.py) today and the
planned "explain this prediction" feature later. Both go through call_llm()
below; neither builds its own client.

Three providers, all reusing the same two call shapes that already existed
in summary.py before this module:
  - "groq"    - the Groq SDK (OpenAI-compatible), same as the old
                hardcoded try_groq().
  - "gemini"  - the Gemini REST call, same as the old hardcoded
                try_gemini().
  - "on_prem" - the SAME Groq SDK call as "groq", just with base_url
                pointed at the admin's own endpoint instead of Groq's
                default. The Groq client is a generic OpenAI-compatible
                client (base_url is a real constructor kwarg), and most
                self-hosted inference servers (vLLM, Ollama's OpenAI
                mode, TGI, LocalAI) speak that same protocol - so this
                is not a second mechanism, it's the first one with a
                different base_url. This is the whole point of the
                feature: a regulated customer points "on_prem" at their
                own infrastructure and no inference call ever leaves it.

Fail-soft throughout - call_llm() never raises, always returns a string,
matching generate_summary()'s existing contract. Critically, "on_prem"
never falls back to "groq"/"gemini" on failure - that branch doesn't
exist for it - so an on-prem misconfiguration degrades to an honest
"unavailable" message instead of silently sending the prompt externally.

See DECISIONS.md for the key-storage tradeoff (Fernet, key derived from
SECRET_KEY - not a dedicated secret or KMS).
"""

import os
import base64
import hashlib
import requests as req
from groq import Groq
from cryptography.fernet import Fernet

from backend.app.database import SessionLocal
from backend.app.db.models import LLMProviderConfig

PROVIDERS = ("groq", "gemini", "on_prem")
DEFAULT_MODEL = "openai/gpt-oss-20b"

# Legacy env vars - still consulted when no admin config has been saved
# yet, so an existing deployment's drift explanations keep working
# unchanged the moment this ships. Once an admin saves a provider, this
# is never consulted again.
_LEGACY_GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
_LEGACY_GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")


# ---- Key encryption ---------------------------------------------------

def _fernet() -> Fernet:
    secret = os.environ.get("SECRET_KEY", "change-this-in-production-use-a-long-random-string")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def encrypt_key(plaintext: str) -> str:
    if not plaintext:
        return ""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_key(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except Exception:
        # Ciphertext from a different SECRET_KEY (e.g. rotated without
        # migrating stored keys) - treat as "no key" rather than 500.
        return ""


def mask_key(plaintext: str) -> str | None:
    if not plaintext:
        return None
    tail = plaintext[-4:] if len(plaintext) >= 4 else plaintext
    return "•" * 8 + tail


# ---- Config CRUD --------------------------------------------------------

def get_config(db) -> LLMProviderConfig | None:
    return db.query(LLMProviderConfig).first()


def save_config(db, provider: str, endpoint_url: str | None, api_key: str | None,
                 model_name: str, admin_id: int) -> LLMProviderConfig:
    """api_key=None (not "") keeps whatever key is already stored - lets an
    admin change the model name or provider without re-pasting the key."""
    if provider not in PROVIDERS:
        raise ValueError("Unknown provider: " + str(provider))

    cfg = get_config(db)
    if cfg is None:
        cfg = LLMProviderConfig(provider=provider, model_name=model_name or DEFAULT_MODEL)
        db.add(cfg)

    cfg.provider = provider
    cfg.endpoint_url = endpoint_url or None
    cfg.model_name = model_name or DEFAULT_MODEL
    if api_key is not None:
        cfg.api_key_encrypted = encrypt_key(api_key) if api_key else None
    cfg.updated_by = admin_id
    db.commit()
    db.refresh(cfg)
    return cfg


# ---- The call shapes (reused, not duplicated) ----------------------------

def _call_openai_compatible(api_key: str, model: str, prompt: str, base_url: str | None = None) -> str:
    # Same call the old try_groq() made - the Groq SDK is a generic
    # OpenAI-compatible client, so this one function serves both "groq"
    # (base_url left at its default) and "on_prem" (base_url overridden).
    client = Groq(api_key=api_key or "not-required", base_url=base_url) if base_url else Groq(api_key=api_key)
    response = client.chat.completions.create(
        messages=[
            {"role": "system", "content": "You are a concise, honest MLOps observability assistant."},
            {"role": "user", "content": prompt}
        ],
        model=model,
        max_tokens=400,
        temperature=0.3,
    )
    return response.choices[0].message.content.strip()


def _call_gemini(api_key: str, model: str, prompt: str) -> str:
    # Same call the old try_gemini() made, model parameterized instead of
    # hardcoded to gemini-2.0-flash.
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    r = req.post(url, json=body, timeout=15)
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()


def _dispatch(provider: str, endpoint_url: str | None, api_key: str, model: str, prompt: str) -> str:
    if provider == "groq":
        return _call_openai_compatible(api_key, model, prompt)
    if provider == "gemini":
        return _call_gemini(api_key, model, prompt)
    if provider == "on_prem":
        return _call_openai_compatible(api_key, model, prompt, base_url=endpoint_url)
    raise ValueError("Unknown provider: " + str(provider))


# ---- Public entry points --------------------------------------------------

def call_llm(prompt: str) -> str:
    """Used by generate_summary() today, and the planned prediction-
    explanation feature later. Opens its own short-lived session - callers
    never need to thread a db session through just to read this config."""
    db = SessionLocal()
    try:
        cfg = get_config(db)
    finally:
        db.close()

    if cfg is None:
        return _legacy_fallback(prompt)

    key = decrypt_key(cfg.api_key_encrypted) if cfg.api_key_encrypted else ""
    try:
        return _dispatch(cfg.provider, cfg.endpoint_url, key, cfg.model_name, prompt)
    except Exception as e:
        # No fallback to another provider here on purpose - see module
        # docstring. Especially for on_prem, failing soft and saying so is
        # the correct behavior, not quietly trying an external vendor.
        return f"LLM summary unavailable ({cfg.provider}): {str(e)[:100]}"


def _legacy_fallback(prompt: str) -> str:
    """No admin config saved yet - exactly the old generate_summary()
    behavior (env vars, Groq then Gemini), so nothing breaks on upgrade."""
    if _LEGACY_GROQ_KEY:
        try:
            return _call_openai_compatible(_LEGACY_GROQ_KEY, DEFAULT_MODEL, prompt)
        except Exception:
            pass  # fall through to Gemini, same as before
    if _LEGACY_GEMINI_KEY:
        try:
            return _call_gemini(_LEGACY_GEMINI_KEY, "gemini-2.0-flash", prompt)
        except Exception as e:
            return f"LLM summary unavailable (both providers failed): {str(e)[:100]}"
    return "LLM summary unavailable: no provider configured."


def test_connection(provider: str, endpoint_url: str | None, api_key: str, model: str) -> tuple[bool, str]:
    """Live-tests candidate settings without persisting anything. Never
    raises - always (ok, message)."""
    if provider not in PROVIDERS:
        return False, "Unknown provider."
    if provider in ("groq", "gemini") and not api_key:
        return False, "An API key is required to test this provider."
    if provider == "on_prem" and not endpoint_url:
        return False, "An endpoint URL is required to test on-prem."
    try:
        text = _dispatch(provider, endpoint_url, api_key, model or DEFAULT_MODEL,
                          "Reply with exactly one word: ok")
        return True, (text[:200] if text else "Connected, but got an empty response.")
    except Exception as e:
        return False, str(e)[:200]

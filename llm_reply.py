"""llm_reply.py - LLM-powered natural replies via an OpenAI-compatible API.

Reads credentials from `.env` (project root) or environment variables:
    LLM_API_KEY   - API key (required; when missing LLM_ENABLED=False)
    LLM_BASE_URL  - API base URL, defaults to DeepSeek (https://api.deepseek.com/v1)
    LLM_MODEL     - model name, defaults to deepseek-chat

The key is kept ONLY in `.env` (excluded by .gitignore), never in source code.
When the key is missing, LLM_ENABLED=False and the bot falls back to the
built-in bilingual templates, so existing functionality is unaffected.
"""
import os

import requests


def _load_dotenv(path=".env"):
    """Minimal .env loader: fills os.environ without overriding existing vars."""
    if not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError as e:
        print(f"llm_reply: failed to load .env: {e}")


_load_dotenv()

LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")
LLM_ENABLED = bool(LLM_API_KEY)

SYSTEM_PROMPT = (
    "You are the friendly support assistant for a vacation rental business, "
    "chatting with guests on Telegram. Reply naturally, warmly and concisely, "
    "like a real property manager. The 'Reply language' field in the user "
    "message is MANDATORY: always reply in exactly that language, even when "
    "the guest message itself is only digits, symbols or has no language "
    "cues (e.g. a menu choice '1'). Never mention that you are an AI or a "
    "bot. When context is provided, keep the key details (request type, "
    "property ID, priority, approval options, escalation notice) in your "
    "reply."
)


def llm_reply(user_message: str, context: str, lang: str) -> str:
    """Generate a natural reply with an OpenAI-compatible chat completion API.

    Raises an exception on any failure; the caller is expected to fall back
    to the bilingual templates.
    """
    lang_hint = "Chinese (zh)" if lang == "zh" else "English (en)"
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Guest message: {user_message}\n\n"
                    f"Internal context: {context}\n\n"
                    f"Reply language: {lang_hint}"
                ),
            },
        ],
        "temperature": 0.7,
    }
    url = LLM_BASE_URL.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    r = requests.post(url, headers=headers, json=payload, timeout=15)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()

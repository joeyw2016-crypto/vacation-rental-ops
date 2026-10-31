
import os

import requests

# Credentials come from .env / environment only. Real values are NEVER
# hard-coded here; keep them in .env (excluded by .gitignore).
CLICKUP_TOKEN = os.environ.get("CLICKUP_TOKEN", "YOUR_CLICKUP_TOKEN_HERE")
CLICKUP_LIST_ID = os.environ.get("CLICKUP_LIST_ID", "YOUR_CLICKUP_LIST_ID_HERE")
CLICKUP_ENABLED = (
    CLICKUP_TOKEN != "YOUR_CLICKUP_TOKEN_HERE"
    and CLICKUP_LIST_ID != "YOUR_CLICKUP_LIST_ID_HERE"
)


def create_task(title: str, description: str) -> dict:
    """Create a task under the configured ClickUp List."""
    url = f"https://api.clickup.com/api/v2/list/{CLICKUP_LIST_ID}/task"
    headers = {
        "Authorization": CLICKUP_TOKEN,
        "Content-Type": "application/json",
    }
    payload = {"name": title, "description": description}
    r = requests.post(url, headers=headers, json=payload, timeout=20)
    r.raise_for_status()
    return r.json()

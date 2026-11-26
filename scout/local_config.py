"""Local settings that are never committed. Standard library only.

The verified project ID for the live connector lives in scott.local.json at the project root, which
.gitignore keeps out of every commit:

    {"verified_free_project": "<your verified free-tier project ID>"}

scott.local.example.json shows the shape. A missing or unreadable file, or one still holding the
placeholder, means no project is verified, so the live-run binding gate stays closed. Nothing here
reads an API key or touches the network.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / 'scott.local.json'  # tests point this at a temporary file
PLACEHOLDER = 'YOUR-VERIFIED-FREE-PROJECT-ID'


def verified_project(path=None):
    """The verified free-tier project ID from the local config file, or None (gate closed)."""
    try:
        data = json.loads(Path(path or CONFIG_PATH).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    value = data.get('verified_free_project') if isinstance(data, dict) else None
    if not isinstance(value, str) or not value.strip() or value.strip() == PLACEHOLDER:
        return None
    return value.strip()

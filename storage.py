#!/usr/bin/env python3
"""
storage.py — Local disk persistence for target server credentials.

Stores server connection profiles (IP, username, password) in a JSON
file on local disk so they survive across application restarts.

NOTE: Passwords are stored in PLAINTEXT on disk. This is intentional
per operator requirement for internal infrastructure tooling.
Ensure the storage file has appropriate filesystem permissions.
"""

import json
import os
from typing import List, Dict

# ---------------------------------------------------------------------------
# Storage path — lives alongside the application in the project directory
# ---------------------------------------------------------------------------
_STORAGE_DIR = os.path.dirname(os.path.abspath(__file__))
SERVERS_FILE = os.path.join(_STORAGE_DIR, "saved_servers.json")


def load_servers() -> List[Dict[str, str]]:
    """
    Load saved server profiles from disk.

    Returns
    -------
    list[dict]
        Each dict has keys: 'host', 'username', 'password'.
        Returns a single empty entry if no saved data exists.
    """
    if not os.path.exists(SERVERS_FILE):
        return [{"host": "", "username": "", "password": ""}]

    try:
        with open(SERVERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Validate structure
        if not isinstance(data, list) or not data:
            return [{"host": "", "username": "", "password": ""}]

        # Ensure each entry has all required keys
        servers = []
        for entry in data:
            servers.append({
                "host": entry.get("host", ""),
                "username": entry.get("username", ""),
                "password": entry.get("password", ""),
            })

        return servers if servers else [{"host": "", "username": "", "password": ""}]

    except (json.JSONDecodeError, IOError, TypeError):
        return [{"host": "", "username": "", "password": ""}]


def save_servers(servers: List[Dict[str, str]]) -> bool:
    """
    Persist server profiles to disk as JSON.

    Parameters
    ----------
    servers : list[dict]
        Each dict should have keys: 'host', 'username', 'password'.

    Returns
    -------
    bool
        True if saved successfully, False on error.
    """
    try:
        # Only save entries that have at least a host defined
        to_save = [
            {
                "host": s.get("host", "").strip(),
                "username": s.get("username", "").strip(),
                "password": s.get("password", ""),
            }
            for s in servers
        ]

        with open(SERVERS_FILE, "w", encoding="utf-8") as f:
            json.dump(to_save, f, indent=2, ensure_ascii=False)

        return True

    except (IOError, TypeError) as exc:
        return False


def delete_saved_servers() -> bool:
    """
    Remove the saved servers file from disk.

    Returns
    -------
    bool
        True if deleted or file didn't exist, False on error.
    """
    try:
        if os.path.exists(SERVERS_FILE):
            os.remove(SERVERS_FILE)
        return True
    except IOError:
        return False

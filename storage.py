import json
import os
from typing import List, Dict

_STORAGE_DIR = os.path.dirname(os.path.abspath(__file__))
SERVERS_FILE = os.path.join(_STORAGE_DIR, "saved_servers.json")


def load_servers() -> List[Dict[str, str]]:
    if not os.path.exists(SERVERS_FILE):
        return [{"host": "", "username": "", "password": ""}]

    try:
        with open(SERVERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list) or not data:
            return [{"host": "", "username": "", "password": ""}]

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
    try:
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
    try:
        if os.path.exists(SERVERS_FILE):
            os.remove(SERVERS_FILE)
        return True
    except IOError:
        return False

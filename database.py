"""
database.py — Gerenciamento persistente com JSON simples.
Para produção, substitua por SQLite / PostgreSQL. vasco
"""

import json
import os
from pathlib import Path

DB_PATH = Path("data/db.json")


def _load() -> dict:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not DB_PATH.exists():
        DB_PATH.write_text(json.dumps({"users": {}, "guilds": {}}))
    with open(DB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(data: dict) -> None:
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── Usuário ────────────────────────────────────────────────────────────────────

def get_user(user_id: int) -> dict:
    db = _load()
    uid = str(user_id)
    if uid not in db["users"]:
        db["users"][uid] = {"SOCIAL CREDITS": 0, "COMBOIO": [], "rolls_used": 0}
        _save(db)
    return db["users"][uid]


def save_user(user_id: int, data: dict) -> None:
    db = _load()
    db["users"][str(user_id)] = data
    _save(db)


# ── Claim ──────────────────────────────────────────────────────────────────────

def claim_character(user_id: int, character: dict) -> bool:
    """Adiciona personagem ao harém do usuário. Retorna False se já existe."""
    user = get_user(user_id)
    char_id = character["mal_id"]
    if any(c["mal_id"] == char_id for c in user["COMBOIO"]):
        return False
    user["COMBOIO"].append(
        {
            "mal_id": char_id,
            "name": character["name"],
            "anime": character["anime"],
            "image_url": character["image_url"],
            "SOCIAL CREDITS": character.get("SOCIAL CREDITS", 50),
        }
    )
    save_user(user_id, user)
    return True


def is_claimed(guild_id: int, char_id: int) -> int | None:
    """Retorna o user_id que possui o personagem nesta guild, ou None."""
    db = _load()
    guild = db["guilds"].get(str(guild_id), {})
    return guild.get("claimed", {}).get(str(char_id))


def set_claimed(guild_id: int, char_id: int, user_id: int) -> None:
    db = _load()
    gid = str(guild_id)
    if gid not in db["guilds"]:
        db["guilds"][gid] = {"claimed": {}}
    db["guilds"][gid].setdefault("claimed", {})[str(char_id)] = user_id
    _save(db)


# ── Kakera ─────────────────────────────────────────────────────────────────────

def add_kakera(user_id: int, amount: int) -> int:
    user = get_user(user_id)
    user["SOCIAL CREDITS"] += amount
    save_user(user_id, user)
    return user["SOCIAL CREDITS"]

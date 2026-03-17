"""
database.py — Persistência JSON local.
Chaves padronizadas: "Equipe" (personagens), "Cols" (moeda).
"""
 
import json
import time
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
    db  = _load()
    uid = str(user_id)
    if uid not in db["users"]:
        db["users"][uid] = {
            "Cols":           0,
            "Equipe":         [],
            "rolls_used":     0,
            "last_claim":     0,
            "last_kakera_char": None,
            "combates":       {"vitorias": 0, "derrotas": 0},
        }
        _save(db)
    user = db["users"][uid]
 
    # ── Migração completa de campos antigos ───────────────────────────────────
    # harem → Equipe (chave renomeada)
    if "harem" in user and "Equipe" not in user:
        user["Equipe"] = user.pop("harem")
    # kakera → Cols (chave renomeada)
    if "kakera" in user and "Cols" not in user:
        user["Cols"] = user.pop("kakera")
 
    # Campos que podem estar faltando em usuários antigos
    user.setdefault("Equipe", [])
    user.setdefault("Cols", 0)
    user.setdefault("rolls_used", 0)
    user.setdefault("combates", {"vitorias": 0, "derrotas": 0})
    user.setdefault("last_claim", 0)
    user.setdefault("last_kakera_char", None)
 
    # Migra personagens dentro da Equipe (kakera → Cols)
    changed = False
    for char in user["Equipe"]:
        if "kakera" in char and "Cols" not in char:
            char["Cols"] = char.pop("kakera")
            changed = True
        char.setdefault("Cols", 50)
        char.setdefault("genres", [])
        char.setdefault("stats", {})
        char.setdefault("favorites", 0)
        char.setdefault("gender", "Unknown")
 
    if changed:
        db["users"][uid] = user
        _save(db)
 
    return user
 
 
def save_user(user_id: int, data: dict) -> None:
    db = _load()
    db["users"][str(user_id)] = data
    _save(db)
 
 
# ── Claim ──────────────────────────────────────────────────────────────────────
 
def claim_character(user_id: int, character: dict) -> bool:
    """
    Adiciona personagem à Equipe do usuário.
    Retorna False se o personagem já estiver na equipe.
    """
    db   = _load()
    uid  = str(user_id)
    user = get_user(user_id)
 
    char_id = character["mal_id"]
    if any(c["mal_id"] == char_id for c in user["Equipe"]):
        return False
 
    user["Equipe"].append({
        "mal_id":    char_id,
        "name":      character["name"],
        "anime":     character["anime"],
        "image_url": character["image_url"],
        "Cols":      character.get("Cols", 50),
        "favorites": character.get("favorites", 0),
        "genres":    character.get("genres", []),
        "stats":     character.get("stats", {}),
    })
 
    # Salva tudo de uma vez (evita race condition com last_claim)
    db["users"][uid] = user
    _save(db)
    return True
 
 
def update_last_claim(user_id: int) -> None:
    """Atualiza apenas o timestamp do último claim, sem sobrescrever Equipe."""
    db  = _load()
    uid = str(user_id)
    if uid not in db["users"]:
        get_user(user_id)
        db = _load()
    db["users"][uid]["last_claim"] = time.time()
    _save(db)
 
 
# ── Guild claims ───────────────────────────────────────────────────────────────
 
def is_claimed(guild_id: int, char_id: int) -> int | None:
    db    = _load()
    guild = db["guilds"].get(str(guild_id), {})
    return guild.get("claimed", {}).get(str(char_id))
 
 
def set_claimed(guild_id: int, char_id: int, user_id: int) -> None:
    db  = _load()
    gid = str(guild_id)
    db["guilds"].setdefault(gid, {"claimed": {}})
    db["guilds"][gid].setdefault("claimed", {})[str(char_id)] = user_id
    _save(db)
 
 
# ── Cols (moeda) ───────────────────────────────────────────────────────────────
 
def add_cols(user_id: int, amount: int) -> int:
    db  = _load()
    uid = str(user_id)
    if uid not in db["users"]:
        get_user(user_id)
        db = _load()
    db["users"][uid]["Cols"] = db["users"][uid].get("Cols", 0) + amount
    _save(db)
    return db["users"][uid]["Cols"]
 
 
# Alias para retrocompatibilidade
def add_kakera(user_id: int, amount: int) -> int:
    return add_cols(user_id, amount)
 
 
# ── Combate ────────────────────────────────────────────────────────────────────
 
def record_combat_result(winner_id: int, loser_id: int, cols_prize: int) -> None:
    """Registra resultado de um combate e distribui Cols."""
    db = _load()
 
    for uid, key in [(str(winner_id), "vitorias"), (str(loser_id), "derrotas")]:
        db["users"].setdefault(uid, {}).setdefault("combates", {"vitorias": 0, "derrotas": 0})
        db["users"][uid]["combates"][key] = db["users"][uid]["combates"].get(key, 0) + 1
 
    # Premio ao vencedor
    db["users"][str(winner_id)]["Cols"] = db["users"][str(winner_id)].get("Cols", 0) + cols_prize
 
    _save(db)
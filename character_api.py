"""
character_api.py — Jikan v4 com duas fontes de dados:

  1. fetch_top_characters()   — ranking direto dos mais populares do MAL
                                (/characters?order_by=favorites)
  2. _fetch_characters_from_anime() — via lista de animes (pool + perfis MAL)

Gênero é resolvido no endpoint /characters/{id} e cacheado.
"""

import aiohttp
import asyncio
import json
import random
from pathlib import Path
from stats_engine import generate_stats

CACHE_FILE     = Path("cache/characters.json")
ANIME_IDS_FILE = Path("cache/anime_ids.json")   # IDs acumulados (pool + perfis)
JIKAN_BASE     = "https://api.jikan.moe/v4"

# ── Pool base (seed inicial) ───────────────────────────────────────────────────
_BASE_ANIME_IDS: list[int] = list(dict.fromkeys([
    1, 30, 199, 269, 20, 21,
    11061, 4382, 33486, 40748, 38000, 37779, 34134, 20583, 27775, 21127, 6702,
    11757, 25013, 31240, 37349, 19815, 32182, 38474, 48583, 50265,
    1535, 9253, 5114, 16498, 49387, 39617, 23273,
    2904, 1575, 35760,
    39535, 33352, 22319,
    14467, 20707, 34572,
    6547, 28223,
    40028, 40456, 13601, 18671, 38408, 42897,
]))

# Alias público para sugestões/outros cogs
POPULAR_ANIME_IDS = _BASE_ANIME_IDS


# ── Anime ID pool persistente ──────────────────────────────────────────────────

def _load_anime_ids() -> list[int]:
    """Carrega o pool acumulado de anime IDs (base + perfis MAL)."""
    ANIME_IDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if ANIME_IDS_FILE.exists():
        with open(ANIME_IDS_FILE, "r") as f:
            return json.load(f)
    _save_anime_ids(_BASE_ANIME_IDS)
    return list(_BASE_ANIME_IDS)


def _save_anime_ids(ids: list[int]) -> None:
    with open(ANIME_IDS_FILE, "w") as f:
        json.dump(list(dict.fromkeys(ids)), f)


def add_anime_ids(new_ids: list[int]) -> int:
    """
    Adiciona novos anime IDs ao pool persistente.
    Retorna quantos IDs realmente novos foram adicionados.
    """
    current = set(_load_anime_ids())
    added   = [i for i in new_ids if i not in current]
    if added:
        _save_anime_ids(list(current) + added)
    return len(added)


def get_anime_pool_size() -> int:
    return len(_load_anime_ids())


# ── Cache de personagens ───────────────────────────────────────────────────────

def _load_cache() -> list[dict]:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if CACHE_FILE.exists():
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def _save_cache(characters: list[dict]) -> None:
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(characters, f, indent=2, ensure_ascii=False)


def _calc_cols(favorites: int) -> int:
    if favorites >= 50_000: return 1000
    if favorites >= 20_000: return 500
    if favorites >= 5_000:  return 200
    if favorites >= 1_000:  return 100
    if favorites >= 100:    return 75
    return 50


# ── Rate-limit helper ──────────────────────────────────────────────────────────

async def _safe_get(session: aiohttp.ClientSession, url: str, retries: int = 3) -> dict | None:
    """GET com retry automático em caso de 429 (rate limit)."""
    for attempt in range(retries):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    return await resp.json()
                if resp.status == 429:
                    wait = 2 ** attempt  # 1s, 2s, 4s
                    await asyncio.sleep(wait)
                    continue
                return None
        except asyncio.TimeoutError:
            await asyncio.sleep(1)
        except Exception:
            return None
    return None


# ── Gênero do personagem ───────────────────────────────────────────────────────

async def _fetch_character_gender(session: aiohttp.ClientSession, mal_id: int) -> str:
    data = await _safe_get(session, f"{JIKAN_BASE}/characters/{mal_id}")
    if not data:
        return "Unknown"
    gender = data.get("data", {}).get("gender") or "Unknown"
    if gender == "Female": return "Female"
    if gender == "Male":   return "Male"
    return "Unknown"


# ── Info do anime ──────────────────────────────────────────────────────────────

async def _fetch_anime_info(session: aiohttp.ClientSession, anime_id: int) -> tuple[str, list[str]]:
    data = await _safe_get(session, f"{JIKAN_BASE}/anime/{anime_id}")
    if not data:
        return "Unknown Anime", []
    d      = data.get("data", {})
    titles = d.get("titles", [])
    title  = "Unknown Anime"
    for preferred in ("English", "Default"):
        for t in titles:
            if t.get("type") == preferred and t.get("title"):
                title = t["title"]
                break
        if title != "Unknown Anime":
            break
    if title == "Unknown Anime" and titles:
        title = titles[0].get("title", "Unknown Anime")
    genres: list[str] = []
    for source in ("genres", "themes", "demographics"):
        for g in d.get(source, []):
            n = g.get("name", "")
            if n and n not in genres:
                genres.append(n)
    return title, genres


# ── Personagens de um anime ────────────────────────────────────────────────────

async def _fetch_characters_from_anime(
    session: aiohttp.ClientSession, anime_id: int
) -> list[dict]:
    anime_name, genres = await _fetch_anime_info(session, anime_id)
    await asyncio.sleep(0.5)

    data = await _safe_get(session, f"{JIKAN_BASE}/anime/{anime_id}/characters")
    if not data:
        return []

    characters = []
    for entry in data.get("data", []):
        char = entry.get("character", {})
        role = entry.get("role", "")
        if role not in ("Main", "Supporting"):
            continue
        image_url = char.get("images", {}).get("jpg", {}).get("image_url") or ""
        if not image_url or "questionmark" in image_url:
            continue
        favorites = char.get("favorites", 0)
        mal_id    = char["mal_id"]
        stats     = generate_stats(favorites=favorites, genres=genres, seed=mal_id)

        if role == "Main":
            gender = await _fetch_character_gender(session, mal_id)
            await asyncio.sleep(0.35)
        else:
            gender = "Unknown"

        characters.append({
            "mal_id":    mal_id,
            "name":      char.get("name", "???"),
            "anime":     anime_name,
            "anime_id":  anime_id,
            "genres":    genres,
            "image_url": image_url,
            "favorites": favorites,
            "Cols":      _calc_cols(favorites),
            "stats":     stats,
            "gender":    gender,
            "source":    "anime",
        })
    return characters


# ── TOP CHARACTERS do MAL (fonte principal) ────────────────────────────────────

async def fetch_top_characters(
    pages: int = 5,
    progress_callback=None
) -> int:
    """
    Busca os personagens mais populares do MAL via ranking de favoritos.
    Cada página retorna 25 personagens → pages=5 = top 125.
    Cada personagem recebe gênero + anime + stats completos.

    progress_callback(current, total, char_name): chamado a cada personagem salvo.
    """
    existing     = _load_cache()
    existing_ids = {c["mal_id"] for c in existing}
    new_chars    = []
    total_fetched = pages * 25

    async with aiohttp.ClientSession() as session:
        for page in range(1, pages + 1):
            url  = f"{JIKAN_BASE}/characters?order_by=favorites&sort=desc&limit=25&page={page}"
            data = await _safe_get(session, url)
            if not data:
                continue

            entries = data.get("data", [])
            for i, entry in enumerate(entries):
                mal_id    = entry["mal_id"]
                favorites = entry.get("favorites", 0)
                image_url = entry.get("images", {}).get("jpg", {}).get("image_url") or ""
                name      = entry.get("name", "???")

                if mal_id in existing_ids or not image_url or "questionmark" in image_url:
                    continue

                # Gênero já vem no endpoint /characters (campo gender)
                gender = entry.get("gender") or "Unknown"
                if gender not in ("Female", "Male"):
                    gender = "Unknown"

                # Busca anime principal via /characters/{id}/anime
                anime_name = "Unknown Anime"
                anime_id   = 0
                genres: list[str] = []

                anime_data = await _safe_get(session, f"{JIKAN_BASE}/characters/{mal_id}/anime")
                if anime_data and anime_data.get("data"):
                    # Pega o anime com mais membros (mais relevante)
                    anime_entries = sorted(
                        anime_data["data"],
                        key=lambda x: x.get("anime", {}).get("members", 0) or 0,
                        reverse=True,
                    )
                    best = anime_entries[0].get("anime", {})
                    anime_id   = best.get("mal_id", 0)
                    anime_name = best.get("title", "Unknown Anime")

                    if anime_id:
                        _, genres = await _fetch_anime_info(session, anime_id)
                        await asyncio.sleep(0.4)

                # Se gênero ainda desconhecido, tenta /characters/{id}
                if gender == "Unknown":
                    gender = await _fetch_character_gender(session, mal_id)
                    await asyncio.sleep(0.3)

                stats = generate_stats(favorites=favorites, genres=genres, seed=mal_id)

                char = {
                    "mal_id":    mal_id,
                    "name":      name,
                    "anime":     anime_name,
                    "anime_id":  anime_id,
                    "genres":    genres,
                    "image_url": image_url,
                    "favorites": favorites,
                    "Cols":      _calc_cols(favorites),
                    "stats":     stats,
                    "gender":    gender,
                    "source":    "top_characters",
                }
                new_chars.append(char)
                existing_ids.add(mal_id)

                if progress_callback:
                    current = (page - 1) * 25 + i + 1
                    progress_callback(current, total_fetched, name)

                await asyncio.sleep(0.5)

            # Pausa entre páginas para evitar rate-limit
            await asyncio.sleep(1.5)

    all_chars = existing + new_chars
    _save_cache(all_chars)
    return len(new_chars)


# ── Anime list de perfil MAL ───────────────────────────────────────────────────

async def fetch_user_animelist(username: str) -> tuple[list[int], str | None]:
    """
    Busca a lista de animes assistidos/assistindo de um usuário MAL.
    Retorna (lista de anime_ids, erro ou None).
    """
    all_ids: list[int] = []
    page = 1

    async with aiohttp.ClientSession() as session:
        while True:
            url  = f"{JIKAN_BASE}/users/{username}/animelist?status=completed&page={page}"
            data = await _safe_get(session, url)
            if not data:
                if page == 1:
                    return [], f"Usuário **{username}** não encontrado ou lista privada."
                break

            entries = data.get("data", [])
            if not entries:
                break

            for entry in entries:
                anime = entry.get("anime", {})
                aid   = anime.get("mal_id")
                if aid:
                    all_ids.append(aid)

            # Verifica paginação
            pagination = data.get("pagination", {})
            if not pagination.get("has_next_page", False):
                break
            page += 1
            await asyncio.sleep(0.6)

    return all_ids, None


async def import_from_user_animelist(
    username: str,
    max_animes: int = 30,
) -> tuple[int, int, str | None]:
    """
    Importa personagens da lista de animes de um usuário MAL.
    Retorna (novos_personagens, novos_animes_no_pool, erro).
    """
    anime_ids, error = await fetch_user_animelist(username)
    if error:
        return 0, 0, error

    # Adiciona ao pool persistente
    new_in_pool = add_anime_ids(anime_ids)

    # Limita quantos vamos processar agora (os que não estão no cache ainda)
    existing     = _load_cache()
    existing_ids = {c["mal_id"] for c in existing}
    cached_anime_ids = {c.get("anime_id") for c in existing}

    to_fetch = [aid for aid in anime_ids if aid not in cached_anime_ids]
    to_fetch = to_fetch[:max_animes]

    if not to_fetch:
        return 0, new_in_pool, None

    new_chars: list[dict] = []
    async with aiohttp.ClientSession() as session:
        for anime_id in to_fetch:
            chars = await _fetch_characters_from_anime(session, anime_id)
            for c in chars:
                if c["mal_id"] not in existing_ids:
                    c["source"] = f"mal_user:{username}"
                    new_chars.append(c)
                    existing_ids.add(c["mal_id"])
            await asyncio.sleep(0.8)

    _save_cache(existing + new_chars)
    return len(new_chars), new_in_pool, None


# ── populate_cache (via pool de animes) ───────────────────────────────────────

async def populate_cache(max_animes: int = 10) -> int:
    """Popula o cache usando o pool acumulado de anime IDs."""
    existing     = _load_cache()
    existing_ids = {c["mal_id"] for c in existing}

    # Migração retroativa de campos faltantes
    changed = False
    for char in existing:
        if "stats" not in char:
            char["stats"] = generate_stats(
                favorites=char.get("favorites", 0),
                genres=char.get("genres", []),
                seed=char["mal_id"],
            )
            changed = True
        if "Cols" not in char:
            char["Cols"] = char.pop("kakera", _calc_cols(char.get("favorites", 0)))
            changed = True
        if "gender" not in char:
            char["gender"] = "Unknown"
            changed = True
        if "source" not in char:
            char["source"] = "anime"
            changed = True
    if changed:
        _save_cache(existing)

    pool        = _load_anime_ids()
    ids_to_fetch = random.sample(pool, min(max_animes, len(pool)))
    new_chars: list[dict] = []

    async with aiohttp.ClientSession() as session:
        for anime_id in ids_to_fetch:
            chars = await _fetch_characters_from_anime(session, anime_id)
            for c in chars:
                if c["mal_id"] not in existing_ids:
                    new_chars.append(c)
                    existing_ids.add(c["mal_id"])
            await asyncio.sleep(0.8)

    all_chars = existing + new_chars
    _save_cache(all_chars)
    return len(new_chars)


# ── update_genders ─────────────────────────────────────────────────────────────

async def update_genders(limit: int = 50) -> int:
    chars    = _load_cache()
    unknown  = [c for c in chars if c.get("gender", "Unknown") == "Unknown"]
    to_fetch = unknown[:limit]
    if not to_fetch:
        return 0

    id_map  = {c["mal_id"]: c for c in chars}
    updated = 0

    async with aiohttp.ClientSession() as session:
        for char in to_fetch:
            gender = await _fetch_character_gender(session, char["mal_id"])
            id_map[char["mal_id"]]["gender"] = gender
            if gender != "Unknown":
                updated += 1
            await asyncio.sleep(0.4)

    _save_cache(list(id_map.values()))
    return updated


# ── Public ─────────────────────────────────────────────────────────────────────

def get_random_character(gender_filter: str | None = None) -> dict | None:
    chars = _load_cache()
    if not chars:
        return None
    if gender_filter:
        filtered = [c for c in chars if c.get("gender") == gender_filter]
        if len(filtered) >= 5:
            return random.choice(filtered)
    return random.choice(chars)


def cache_size() -> int:
    return len(_load_cache())


def gender_stats() -> dict:
    chars = _load_cache()
    out = {"Female": 0, "Male": 0, "Unknown": 0}
    for c in chars:
        g = c.get("gender", "Unknown")
        out[g] = out.get(g, 0) + 1
    return out


_calc_kakera = _calc_cols

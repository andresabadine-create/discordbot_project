"""
character_api.py — Busca personagens reais na API Jikan v4 (MyAnimeList).
Resultados são cacheados em cache/characters.json para evitar rate-limit.
Inclui busca de gêneros e geração de stats RPG via stats_engine.
"""

import aiohttp
import asyncio
import json
import random
from pathlib import Path
from stats_engine import generate_stats

CACHE_FILE = Path("cache/characters.json")
JIKAN_BASE = "https://api.jikan.moe/v4"

POPULAR_ANIME_IDS = [
    1, 16498, 11757, 9253, 1535, 21, 20, 269, 6702, 19815,
    14467, 22319, 33486, 38000, 40748, 31240, 5114, 33352,
    35760, 37779, 48583, 50265, 49387,
]

def _load_cache() -> list[dict]:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if CACHE_FILE.exists():
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def _save_cache(characters: list[dict]) -> None:
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(characters, f, indent=2, ensure_ascii=False)

def _calc_kakera(favorites: int) -> int:
    if favorites >= 50_000: return 1000
    if favorites >= 20_000: return 500
    if favorites >= 5_000:  return 200
    if favorites >= 1_000:  return 100
    if favorites >= 100:    return 75
    return 50

async def _fetch_anime_info(session: aiohttp.ClientSession, anime_id: int) -> tuple[str, list[str]]:
    url = f"{JIKAN_BASE}/anime/{anime_id}"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as resp:
            if resp.status != 200:
                return "Unknown Anime", []
            data = (await resp.json()).get("data", {})
            titles = data.get("titles", [])
            title = "Unknown Anime"
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
                for g in data.get(source, []):
                    name = g.get("name", "")
                    if name and name not in genres:
                        genres.append(name)
            return title, genres
    except Exception:
        return "Unknown Anime", []

async def _fetch_characters_from_anime(session: aiohttp.ClientSession, anime_id: int) -> list[dict]:
    anime_name, genres = await _fetch_anime_info(session, anime_id)
    await asyncio.sleep(0.5)
    url = f"{JIKAN_BASE}/anime/{anime_id}/characters"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
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
                mal_id = char["mal_id"]
                stats = generate_stats(favorites=favorites, genres=genres, seed=mal_id)
                characters.append({
                    "mal_id": mal_id,
                    "name": char.get("name", "???"),
                    "anime": anime_name,
                    "anime_id": anime_id,
                    "genres": genres,
                    "image_url": image_url,
                    "favorites": favorites,
                    "kakera": _calc_kakera(favorites),
                    "stats": stats,
                })
            return characters
    except Exception:
        return []

async def populate_cache(max_animes: int = 10) -> int:
    existing = _load_cache()
    existing_ids = {c["mal_id"] for c in existing}
    changed = False
    for char in existing:
        if "stats" not in char:
            char["stats"] = generate_stats(
                favorites=char.get("favorites", 0),
                genres=char.get("genres", []),
                seed=char["mal_id"],
            )
            changed = True
    if changed:
        _save_cache(existing)
    ids_to_fetch = random.sample(POPULAR_ANIME_IDS, min(max_animes, len(POPULAR_ANIME_IDS)))
    new_chars: list[dict] = []
    async with aiohttp.ClientSession() as session:
        for anime_id in ids_to_fetch:
            chars = await _fetch_characters_from_anime(session, anime_id)
            for c in chars:
                if c["mal_id"] not in existing_ids:
                    new_chars.append(c)
                    existing_ids.add(c["mal_id"])
            await asyncio.sleep(0.6)
    all_chars = existing + new_chars
    _save_cache(all_chars)
    return len(new_chars)

def get_random_character() -> dict | None:
    chars = _load_cache()
    if not chars:
        return None
    return random.choice(chars)

async def fetch_single_character(char_id: int) -> dict | None:
    async with aiohttp.ClientSession() as session:
        url = f"{JIKAN_BASE}/characters/{char_id}/full"
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as resp:
                if resp.status != 200:
                    return None
                data = (await resp.json()).get("data", {})
                anime_list = data.get("anime", [])
                anime_entry = anime_list[0]["anime"] if anime_list else {}
                anime_name = anime_entry.get("title", "Unknown Anime")
                anime_id = anime_entry.get("mal_id", 0)
                favorites = data.get("favorites", 0)
                genres: list[str] = []
                if anime_id:
                    _, genres = await _fetch_anime_info(session, anime_id)
                stats = generate_stats(favorites=favorites, genres=genres, seed=char_id)
                return {
                    "mal_id": data["mal_id"],
                    "name": data.get("name", "???"),
                    "anime": anime_name,
                    "genres": genres,
                    "image_url": data.get("images", {}).get("jpg", {}).get("image_url", ""),
                    "favorites": favorites,
                    "kakera": _calc_kakera(favorites),
                    "stats": stats,
                    "about": (data.get("about") or "")[:300],
                }
        except Exception:
            return None

def cache_size() -> int:
    return len(_load_cache())

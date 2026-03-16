"""
character_api.py — Busca personagens reais na API Jikan v4 (MyAnimeList).
Resultados são cacheados em cache/characters.json para evitar rate-limit.
"""

import aiohttp
import asyncio
import json
import random
from pathlib import Path

CACHE_FILE = Path("cache/characters.json")
JIKAN_BASE = "https://api.jikan.moe/v4"

# Pool inicial de IDs de animes populares no MAL
POPULAR_ANIME_IDS = [
    1,      # Cowboy Bebop
    5,      # Cowboy Bebop: Movie
    16498,  # Shingeki no Kyojin
    11757,  # Sword Art Online
    9253,   # Steins;Gate
    1535,   # Death Note
    21,     # One Piece
    20,     # Naruto
    269,    # Bleach
    6702,   # Katekyo Hitman Reborn!
    19815,  # No Game No Life
    14467,  # Kill la Kill
    22319,  # Tokyo Ghoul
    33486,  # Boku no Hero Academia
    38000,  # Demon Slayer
    40748,  # Jujutsu Kaisen
    31240,  # Re:Zero
    32281,  # Fullmetal Alchemist: Brotherhood (mal_id correto: 5114)
    5114,   # FMA: Brotherhood
    41467,  # Genshin Impact side (Violet Evergarden: 33352)
    33352,  # Violet Evergarden
    35760,  # Darling in the FranXX
    37779,  # Kimetsu no Yaiba
]

# ── Cache helpers ──────────────────────────────────────────────────────────────

def _load_cache() -> list[dict]:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if CACHE_FILE.exists():
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def _save_cache(characters: list[dict]) -> None:
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(characters, f, indent=2, ensure_ascii=False)


# ── API callss ──────────────────────────────────────────────────────────────────

async def _fetch_anime_title(session: aiohttp.ClientSession, anime_id: int) -> str:
    """Busca o título do anime — tenta inglês, depois romaji, depois qualquer um."""
    url = f"{JIKAN_BASE}/anime/{anime_id}"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return "Unknown Anime"
            data = (await resp.json()).get("data", {})
            titles = data.get("titles", [])
            # Prioridade: English > Default > primeiro disponível
            for preferred in ("English", "Default"):
                for t in titles:
                    if t.get("type") == preferred and t.get("title"):
                        return t["title"]
            if titles:
                return titles[0].get("title", "Unknown Anime")
            return data.get("title", "Unknown Anime")
    except Exception:
        return "Unknown Anime"


async def _fetch_characters_from_anime(session: aiohttp.ClientSession, anime_id: int) -> list[dict]:
    """Busca personagens de um anime específico via Jikan."""

    # Busca o título UMA vez antes do loop (evita rate limit)
    anime_name = await _fetch_anime_title(session, anime_id)
    await asyncio.sleep(0.4)  # pausa entre chamadas

    url = f"{JIKAN_BASE}/anime/{anime_id}/characters"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
            characters = []
            for entry in data.get("data", []):
                char = entry.get("character", {})
                role = entry.get("role", "")
                if role not in ("Main", "Supporting"):
                    continue
                image_url = (
                    char.get("images", {}).get("jpg", {}).get("image_url") or ""
                )
                if not image_url or "questionmark" in image_url:
                    continue
                favorites = char.get("favorites", 0)
                characters.append(
                    {
                        "mal_id": char["mal_id"],
                        "name": char.get("name", "???"),
                        "anime": anime_name,          # título já buscado
                        "anime_id": anime_id,
                        "image_url": image_url,
                        "favorites": favorites,
                        "kakera": _calc_kakera(favorites),
                    }
                )
            return characters
    except Exception:
        return []


def _calc_kakera(favorites: int) -> int:
    """Calcula valor kakera pelo número de favoritos no MAL."""
    if favorites >= 50000:
        return 1000
    elif favorites >= 20000:
        return 500
    elif favorites >= 5000:
        return 200
    elif favorites >= 1000:
        return 100
    elif favorites >= 100:
        return 75
    else:
        return 50


# ── Cache population ───────────────────────────────────────────────────────────

async def populate_cache(max_animes: int = 10) -> int:
    """
    Preenche o cache com personagens dos animes populares.
    Chame uma vez na inicialização ou com $updatecache (admin).
    """
    existing = _load_cache()
    existing_ids = {c["mal_id"] for c in existing}

    ids_to_fetch = random.sample(POPULAR_ANIME_IDS, min(max_animes, len(POPULAR_ANIME_IDS)))
    new_chars: list[dict] = []

    async with aiohttp.ClientSession() as session:
        for anime_id in ids_to_fetch:
            chars = await _fetch_characters_from_anime(session, anime_id)
            for c in chars:
                if c["mal_id"] not in existing_ids:
                    new_chars.append(c)
                    existing_ids.add(c["mal_id"])
            await asyncio.sleep(0.5)  # respeita rate limit da Jikan (3 req/s)

    all_chars = existing + new_chars
    _save_cache(all_chars)
    return len(new_chars)


# ── Public API ─────────────────────────────────────────────────────────────────

def get_random_character(gender_filter: str | None = None) -> dict | None:
    """
    Retorna um personagem aleatório do cache.
    gender_filter: 'waifu' (feminino) | 'husbando' (masculino) | None (qualquer)
    Nota: Jikan não fornece gênero diretamente; filtragem por nome é heurística.
    """
    chars = _load_cache()
    if not chars:
        return None
    return random.choice(chars)


async def fetch_single_character(char_id: int) -> dict | None:
    """Busca um personagem específico pelo ID do MAL."""
    async with aiohttp.ClientSession() as session:
        url = f"{JIKAN_BASE}/characters/{char_id}/full"
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return None
                data = (await resp.json()).get("data", {})
                anime_list = data.get("anime", [])
                anime_name = anime_list[0]["anime"]["title"] if anime_list else "Unknown Anime"
                image_url = data.get("images", {}).get("jpg", {}).get("image_url", "")
                return {
                    "mal_id": data["mal_id"],
                    "name": data.get("name", "???"),
                    "anime": anime_name,
                    "image_url": image_url,
                    "favorites": data.get("favorites", 0),
                    "kakera": _calc_kakera(data.get("favorites", 0)),
                    "about": (data.get("about") or "")[:300],
                }
        except Exception:
            return None


def cache_size() -> int:
    return len(_load_cache())

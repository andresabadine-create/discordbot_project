"""
stats_engine.py — Motor de geração de status RPG para personagens.

Lógica:
  1. Base de todos os stats calculada pela popularidade do personagem (favorites MAL)
  2. Multiplicadores aplicados por gênero do anime (Action → Força alta, etc.)
  3. Variação aleatória pequena (±8%) para diferenciar personagens do mesmo anime
  4. Star rating (⭐) calculado pelo poder total somado
"""

import random
import math

# ── Ícones dos stats ───────────────────────────────────────────────────────────
STAT_ICONS = {
    "forca":         "⚔️",
    "inteligencia":  "🧠",
    "vida":          "❤️",
    "agilidade":     "⚡",
}

STAT_LABELS = {
    "forca":         "Força",
    "inteligencia":  "Inteligência",
    "vida":          "Vida",
    "agilidade":     "Agilidade",
}

# ── Pesos por gênero (multiplicador sobre o valor base) ───────────────────────
# Cada gênero afeta os 4 stats independentemente.
# 1.0 = neutro  |  >1.0 = boost  |  <1.0 = redução
GENRE_WEIGHTS: dict[str, dict[str, float]] = {
    "Action":        {"forca": 1.50, "inteligencia": 0.90, "vida": 1.20, "agilidade": 1.30},
    "Adventure":     {"forca": 1.20, "inteligencia": 1.00, "vida": 1.20, "agilidade": 1.20},
    "Comedy":        {"forca": 0.80, "inteligencia": 0.90, "vida": 0.90, "agilidade": 0.85},
    "Drama":         {"forca": 0.90, "inteligencia": 1.20, "vida": 1.20, "agilidade": 0.90},
    "Fantasy":       {"forca": 1.10, "inteligencia": 1.30, "vida": 1.20, "agilidade": 1.00},
    "Magic":         {"forca": 0.80, "inteligencia": 1.60, "vida": 1.00, "agilidade": 1.10},
    "Supernatural":  {"forca": 1.20, "inteligencia": 1.20, "vida": 1.20, "agilidade": 1.20},
    "Horror":        {"forca": 1.10, "inteligencia": 1.00, "vida": 1.40, "agilidade": 1.20},
    "Mystery":       {"forca": 0.80, "inteligencia": 1.50, "vida": 0.90, "agilidade": 0.90},
    "Psychological": {"forca": 0.70, "inteligencia": 1.70, "vida": 0.80, "agilidade": 0.90},
    "Thriller":      {"forca": 1.00, "inteligencia": 1.40, "vida": 1.00, "agilidade": 1.20},
    "Sci-Fi":        {"forca": 1.00, "inteligencia": 1.40, "vida": 1.00, "agilidade": 1.10},
    "Mecha":         {"forca": 1.40, "inteligencia": 1.30, "vida": 1.30, "agilidade": 0.90},
    "Military":      {"forca": 1.40, "inteligencia": 1.10, "vida": 1.30, "agilidade": 1.00},
    "Sports":        {"forca": 1.30, "inteligencia": 1.00, "vida": 1.20, "agilidade": 1.60},
    "Romance":       {"forca": 0.75, "inteligencia": 1.10, "vida": 1.10, "agilidade": 0.80},
    "Slice of Life": {"forca": 0.70, "inteligencia": 1.00, "vida": 1.00, "agilidade": 0.80},
    "School":        {"forca": 0.85, "inteligencia": 1.10, "vida": 0.90, "agilidade": 0.90},
    "Demons":        {"forca": 1.50, "inteligencia": 1.00, "vida": 1.30, "agilidade": 1.20},
    "Vampire":       {"forca": 1.30, "inteligencia": 1.10, "vida": 1.50, "agilidade": 1.30},
    "Martial Arts":  {"forca": 1.60, "inteligencia": 0.90, "vida": 1.30, "agilidade": 1.50},
    "Game":          {"forca": 1.00, "inteligencia": 1.50, "vida": 1.00, "agilidade": 1.10},
    "Isekai":        {"forca": 1.30, "inteligencia": 1.20, "vida": 1.20, "agilidade": 1.10},
    "Ecchi":         {"forca": 0.80, "inteligencia": 0.85, "vida": 0.90, "agilidade": 0.90},
    "Harem":         {"forca": 0.85, "inteligencia": 0.90, "vida": 0.90, "agilidade": 0.90},
    "Music":         {"forca": 0.75, "inteligencia": 1.10, "vida": 0.90, "agilidade": 1.00},
    "Historical":    {"forca": 1.10, "inteligencia": 1.20, "vida": 1.10, "agilidade": 1.00},
    "Samurai":       {"forca": 1.50, "inteligencia": 1.00, "vida": 1.20, "agilidade": 1.40},
}

# Gênero neutro (sem correspondência na tabela)
_DEFAULT_WEIGHTS: dict[str, float] = {
    "forca": 1.0, "inteligencia": 1.0, "vida": 1.0, "agilidade": 1.0
}


# ── Base por popularidade ──────────────────────────────────────────────────────

def _base_from_favorites(favorites: int) -> int:
    """Retorna o valor base dos stats conforme favoritos no MAL."""
    if favorites >= 50_000: return 110
    if favorites >= 20_000: return 95
    if favorites >= 10_000: return 82
    if favorites >= 5_000:  return 70
    if favorites >= 1_000:  return 57
    if favorites >= 100:    return 44
    return 30


# ── Combinação de pesos dos gêneros ───────────────────────────────────────────

def _merged_weights(genres: list[str]) -> dict[str, float]:
    """
    Combina os multiplicadores de todos os gêneros via média ponderada.
    Gêneros desconhecidos são ignorados (usam neutro no merge).
    """
    if not genres:
        return _DEFAULT_WEIGHTS.copy()

    known = [GENRE_WEIGHTS[g] for g in genres if g in GENRE_WEIGHTS]
    if not known:
        return _DEFAULT_WEIGHTS.copy()

    merged = {}
    for stat in ("forca", "inteligencia", "vida", "agilidade"):
        merged[stat] = sum(w[stat] for w in known) / len(known)
    return merged


# ── Gerador principal ──────────────────────────────────────────────────────────

def generate_stats(favorites: int, genres: list[str], seed: int | None = None) -> dict[str, int]:
    """
    Gera os 4 stats RPG de um personagem.

    Args:
        favorites: Número de favoritos no MAL (popularidade do personagem).
        genres:    Lista de gêneros do anime (ex: ["Action", "Fantasy"]).
        seed:      Semente aleatória para reprodutibilidade (usa mal_id).

    Returns:
        Dict com as chaves: forca, inteligencia, vida, agilidade (valores int).
    """
    rng = random.Random(seed)
    base = _base_from_favorites(favorites)
    weights = _merged_weights(genres)

    stats = {}
    for stat, mult in weights.items():
        raw = base * mult
        # Variação aleatória ±8%
        variation = rng.uniform(0.92, 1.08)
        value = int(raw * variation)
        # Clamp 10–999
        stats[stat] = max(10, min(999, value))

    return stats


# ── Star rating ────────────────────────────────────────────────────────────────

def star_rating(stats: dict[str, int]) -> str:
    """Retorna estrelas (⭐) baseado no poder total (soma dos 4 stats)."""
    total = sum(stats.values())
    if total >= 350: return "⭐⭐⭐⭐⭐"
    if total >= 280: return "⭐⭐⭐⭐"
    if total >= 210: return "⭐⭐⭐"
    if total >= 140: return "⭐⭐"
    return "⭐"


# ── Barra visual ───────────────────────────────────────────────────────────────

def stat_bar(value: int, max_val: int = 150, length: int = 10) -> str:
    """Gera uma barra de progresso em texto para exibição no embed."""
    filled = round((value / max_val) * length)
    filled = max(0, min(length, filled))
    return "█" * filled + "░" * (length - filled)


# ── Formata bloco de stats para embed ─────────────────────────────────────────

def format_stats_field(stats: dict[str, int]) -> str:
    """Retorna string formatada com ícone, barra e valor para o embed."""
    lines = []
    for key in ("forca", "inteligencia", "vida", "agilidade"):
        val = stats.get(key, 0)
        icon  = STAT_ICONS[key]
        label = STAT_LABELS[key]
        bar   = stat_bar(val)
        lines.append(f"{icon} **{label:<14}** `{bar}` **{val}**")
    return "\n".join(lines)

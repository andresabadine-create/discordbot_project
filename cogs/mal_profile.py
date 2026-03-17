"""
cogs/mal_profile.py — Integração com perfil MyAnimeList do usuário.

Comandos:
  $linkmal <username>   — vincula o perfil MAL ao Discord
  $malperfil [@user]    — exibe o perfil MAL vinculado
  $importarmal          — importa animes assistidos → adiciona personagens ao cache
  $deslinkarmal         — remove o vínculo

Admin:
  $topchars [páginas]   — busca top N×25 personagens mais populares do MAL
"""

import discord
from discord.ext import commands
from discord import ui
import aiohttp
import asyncio
import json
from pathlib import Path
from datetime import datetime

from character_api import (
    fetch_user_animelist,
    import_from_user_animelist,
    fetch_top_characters,
    cache_size,
    gender_stats,
    get_anime_pool_size,
    add_anime_ids,
)
from database import get_user, save_user

JIKAN_BASE = "https://api.jikan.moe/v4"
MAL_PROFILES_FILE = Path("data/mal_profiles.json")


# ── Persistência de perfis ─────────────────────────────────────────────────────

def _load_profiles() -> dict:
    MAL_PROFILES_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not MAL_PROFILES_FILE.exists():
        MAL_PROFILES_FILE.write_text(json.dumps({}))
    with open(MAL_PROFILES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_profiles(data: dict) -> None:
    with open(MAL_PROFILES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_mal_username(discord_id: int) -> str | None:
    profiles = _load_profiles()
    entry    = profiles.get(str(discord_id))
    return entry["username"] if entry else None


def link_mal(discord_id: int, username: str, mal_data: dict) -> None:
    profiles = _load_profiles()
    profiles[str(discord_id)] = {
        "username":   username,
        "linked_at":  datetime.utcnow().isoformat(),
        "mal_id":     mal_data.get("mal_id"),
        "avatar":     mal_data.get("images", {}).get("jpg", {}).get("image_url", ""),
        "anime_count": mal_data.get("statistics", {}).get("anime", {}).get("completed", 0),
        "last_import": None,
    }
    _save_profiles(profiles)


def unlink_mal(discord_id: int) -> bool:
    profiles = _load_profiles()
    if str(discord_id) not in profiles:
        return False
    del profiles[str(discord_id)]
    _save_profiles(profiles)
    return True


def update_last_import(discord_id: int) -> None:
    profiles = _load_profiles()
    if str(discord_id) in profiles:
        profiles[str(discord_id)]["last_import"] = datetime.utcnow().isoformat()
        _save_profiles(profiles)


# ── Busca dados do perfil MAL ──────────────────────────────────────────────────

async def fetch_mal_profile(username: str) -> tuple[dict | None, str | None]:
    url = f"{JIKAN_BASE}/users/{username}/full"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as resp:
                if resp.status == 404:
                    return None, f"Usuário **{username}** não encontrado no MyAnimeList."
                if resp.status == 403:
                    return None, f"O perfil de **{username}** é privado."
                if resp.status != 200:
                    return None, "Erro ao acessar a API do MAL. Tente novamente."
                data = (await resp.json()).get("data", {})
                return data, None
    except Exception as e:
        return None, f"Erro de conexão: {e}"


# ── View de confirmação de link ────────────────────────────────────────────────

class LinkConfirmView(ui.View):
    def __init__(self, user: discord.Member, mal_username: str, mal_data: dict):
        super().__init__(timeout=60)
        self.user         = user
        self.mal_username = mal_username
        self.mal_data     = mal_data
        self.confirmed    = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ Não é sua confirmação!", ephemeral=True)
            return False
        return True

    @ui.button(label="✅  Confirmar vínculo", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        link_mal(self.user.id, self.mal_username, self.mal_data)
        self.confirmed = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="✅ Perfil MAL vinculado!",
                description=(
                    f"Seu perfil **[{self.mal_username}](https://myanimelist.net/profile/{self.mal_username})**"
                    f" foi vinculado com sucesso!\n\n"
                    f"Use `$importarmal` para importar seus animes e adicionar personagens ao bot."
                ),
                color=0x2ECC71,
            ),
            view=self,
        )
        self.stop()

    @ui.button(label="❌  Cancelar", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="❌ Vínculo cancelado.", embed=None, view=self)
        self.stop()


# ── Cog ────────────────────────────────────────────────────────────────────────

class MalProfile(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── $linkmal <username> ────────────────────────────────────────────────────

    @commands.command(name="linkmal", aliases=["vinculormal", "setmal"])
    @commands.cooldown(1, 30, commands.BucketType.user)
    async def link_mal_cmd(self, ctx: commands.Context, *, username: str):
        """Vincula seu perfil do MyAnimeList ao Discord."""
        # Verifica se já tem vínculo
        existing = get_mal_username(ctx.author.id)
        if existing:
            await ctx.send(embed=discord.Embed(
                description=(
                    f"⚠️ Você já tem o perfil **{existing}** vinculado!\n"
                    f"Use `$deslinkarmal` para remover antes de vincular outro."
                ),
                color=0xFFA500,
            ))
            return

        async with ctx.typing():
            mal_data, error = await fetch_mal_profile(username)

        if error:
            await ctx.send(embed=discord.Embed(description=f"❌ {error}", color=0xFF0000))
            return

        stats    = mal_data.get("statistics", {}).get("anime", {})
        completed = stats.get("completed", 0)
        watching  = stats.get("watching", 0)
        days      = stats.get("days_watched", 0)
        avatar    = mal_data.get("images", {}).get("jpg", {}).get("image_url", "")
        about     = (mal_data.get("about") or "")[:150]

        embed = discord.Embed(
            title=f"🎌 Vincular perfil MAL?",
            description=(
                f"**[{username}](https://myanimelist.net/profile/{username})**\n\n"
                f"📺 Completados: **{completed}** | Assistindo: **{watching}**\n"
                f"⏱️ Dias assistidos: **{days}**\n"
                + (f"\n_{about}_" if about else "")
            ),
            color=0x2E51A2,
        )
        if avatar:
            embed.set_thumbnail(url=avatar)
        embed.set_footer(text="Confirme para vincular. Seus animes alimentarão o banco de personagens!")

        view = LinkConfirmView(ctx.author, username, mal_data)
        msg  = await ctx.send(embed=embed, view=view)
        await view.wait()

    # ── $malperfil [@user] ─────────────────────────────────────────────────────

    @commands.command(name="malperfil", aliases=["malprofile", "mal"])
    async def mal_profile_cmd(self, ctx: commands.Context, member: discord.Member | None = None):
        """Exibe o perfil MAL vinculado de um usuário."""
        target   = member or ctx.author
        username = get_mal_username(target.id)

        if not username:
            if target == ctx.author:
                await ctx.send(embed=discord.Embed(
                    description=(
                        "❌ Você não tem um perfil MAL vinculado!\n"
                        "Use `$linkmal <seu_usuário_mal>` para vincular."
                    ),
                    color=0xFF6B6B,
                ))
            else:
                await ctx.send(embed=discord.Embed(
                    description=f"❌ **{target.display_name}** não tem perfil MAL vinculado.",
                    color=0xFF6B6B,
                ))
            return

        async with ctx.typing():
            mal_data, error = await fetch_mal_profile(username)

        if error:
            await ctx.send(embed=discord.Embed(description=f"❌ {error}", color=0xFF0000))
            return

        stats     = mal_data.get("statistics", {}).get("anime", {})
        completed = stats.get("completed", 0)
        watching  = stats.get("watching", 0)
        dropped   = stats.get("dropped", 0)
        days      = stats.get("days_watched", 0)
        mean      = stats.get("mean_score", 0)
        avatar    = mal_data.get("images", {}).get("jpg", {}).get("image_url", "")

        # Info de importação
        profiles      = _load_profiles()
        profile_entry = profiles.get(str(target.id), {})
        last_import   = profile_entry.get("last_import")
        last_import_str = last_import[:10] if last_import else "Nunca"

        embed = discord.Embed(
            title=f"🎌 Perfil MAL — {target.display_name}",
            description=f"**[{username}](https://myanimelist.net/profile/{username})**",
            color=0x2E51A2,
        )
        if avatar:
            embed.set_thumbnail(url=avatar)

        embed.add_field(name="✅ Completados",   value=f"**{completed}**",        inline=True)
        embed.add_field(name="📺 Assistindo",     value=f"**{watching}**",         inline=True)
        embed.add_field(name="🗑️ Abandonados",    value=f"**{dropped}**",          inline=True)
        embed.add_field(name="⏱️ Dias assistidos",value=f"**{days}**",             inline=True)
        embed.add_field(name="⭐ Nota média",      value=f"**{mean}**",             inline=True)
        embed.add_field(name="📥 Última importação", value=last_import_str,         inline=True)

        embed.set_footer(text="Use $importarmal para importar seus animes ao bot!")
        await ctx.send(embed=embed)

    # ── $importarmal ──────────────────────────────────────────────────────────

    @commands.command(name="importarmal", aliases=["importmal", "syncmal"])
    @commands.cooldown(1, 3600, commands.BucketType.user)  # 1h de cooldown
    async def import_mal_cmd(self, ctx: commands.Context, max_animes: int = 20):
        """Importa seus animes do MAL e adiciona personagens ao bot. (cooldown: 1h)"""
        username = get_mal_username(ctx.author.id)
        if not username:
            await ctx.send(embed=discord.Embed(
                description="❌ Você não tem perfil MAL vinculado!\nUse `$linkmal <usuário>` primeiro.",
                color=0xFF6B6B,
            ))
            return

        max_animes = min(max_animes, 50)  # Limite máximo por importação

        msg = await ctx.send(embed=discord.Embed(
            title="📥 Importando lista MAL...",
            description=(
                f"Buscando animes de **{username}**...\n"
                f"Isso pode demorar alguns minutos dependendo do tamanho da lista.\n\n"
                f"*(Processando até **{max_animes}** animes novos)*"
            ),
            color=0x2E51A2,
        ))

        new_chars, new_in_pool, error = await import_from_user_animelist(
            username, max_animes=max_animes
        )

        if error:
            await msg.edit(embed=discord.Embed(
                description=f"❌ {error}", color=0xFF0000
            ))
            return

        update_last_import(ctx.author.id)

        stats = gender_stats()
        embed = discord.Embed(
            title="✅ Importação concluída!",
            description=(
                f"📺 **{new_in_pool}** novos animes adicionados ao pool\n"
                f"👤 **{new_chars}** novos personagens no cache\n\n"
                f"**Cache total:** {cache_size()} personagens\n"
                f"♀️ {stats['Female']} femininos | ♂️ {stats['Male']} masculinos\n\n"
                f"Obrigado por contribuir com o banco de personagens! 🎉"
            ),
            color=0x2ECC71,
        )
        embed.set_footer(text=f"Importado de {username} • Cooldown: 1h")
        await msg.edit(embed=embed)

    # ── $deslinkarmal ──────────────────────────────────────────────────────────

    @commands.command(name="deslinkarmal", aliases=["unlinkmal", "removemal"])
    async def unlink_mal_cmd(self, ctx: commands.Context):
        """Remove o vínculo do seu perfil MAL."""
        success = unlink_mal(ctx.author.id)
        if success:
            await ctx.send(embed=discord.Embed(
                description="✅ Perfil MAL desvinculado com sucesso.",
                color=0x2ECC71,
            ))
        else:
            await ctx.send(embed=discord.Embed(
                description="❌ Você não tem perfil MAL vinculado.",
                color=0xFF6B6B,
            ))

    # ── $topchars [páginas] [admin] ───────────────────────────────────────────

    @commands.command(name="topchars", aliases=["topcars", "fetchpopular"])
    @commands.has_permissions(administrator=True)
    async def fetch_top_chars_cmd(self, ctx: commands.Context, pages: int = 5):
        """[Admin] Busca os top N×25 personagens mais populares do MAL direto do ranking."""
        pages = min(pages, 20)  # máx 500 personagens por chamada
        total = pages * 25

        msg = await ctx.send(embed=discord.Embed(
            title="🌟 Buscando Top Personagens MAL...",
            description=(
                f"Buscando as **{pages} páginas** do ranking de favoritos\n"
                f"*(até **{total}** personagens com gênero + stats completos)*\n\n"
                f"⏳ Isso pode levar **{pages * 2}–{pages * 4} minutos** devido ao rate-limit da API.\n"
                f"O bot continuará funcionando normalmente durante o processo."
            ),
            color=0xFFD700,
        ))

        counter = {"done": 0}

        def progress(current, total_items, name):
            counter["done"] = current
            # Atualiza mensagem a cada 10 personagens
            if current % 10 == 0:
                ctx.bot.loop.create_task(
                    msg.edit(embed=discord.Embed(
                        title="🌟 Buscando Top Personagens MAL...",
                        description=(
                            f"**{current}/{total_items}** personagens processados\n"
                            f"Último: *{name}*\n\n"
                            f"Cache atual: **{cache_size()}** personagens"
                        ),
                        color=0xFFD700,
                    ))
                )

        added = await fetch_top_characters(pages=pages, progress_callback=progress)
        stats = gender_stats()

        await msg.edit(embed=discord.Embed(
            title="✅ Top Personagens importados!",
            description=(
                f"**+{added}** novos personagens adicionados ao cache!\n\n"
                f"**Cache total:** {cache_size()}\n"
                f"♀️ Femininos: **{stats['Female']}**\n"
                f"♂️ Masculinos: **{stats['Male']}**\n"
                f"❓ Desconhecido: **{stats['Unknown']}**"
            ),
            color=0xFFD700,
        ))

    # ── $malstats [admin] ──────────────────────────────────────────────────────

    @commands.command(name="malstats")
    @commands.has_permissions(administrator=True)
    async def mal_stats_cmd(self, ctx: commands.Context):
        """[Admin] Estatísticas completas do banco de personagens."""
        profiles = _load_profiles()
        stats    = gender_stats()
        total    = cache_size()
        pool     = get_anime_pool_size()

        embed = discord.Embed(title="📊 Stats do Banco de Personagens", color=0x9B59B6)
        embed.add_field(name="👤 Total personagens",  value=f"**{total}**",                inline=True)
        embed.add_field(name="🎌 Pool de animes",      value=f"**{pool}** IDs",             inline=True)
        embed.add_field(name="🔗 Perfis MAL linkados", value=f"**{len(profiles)}**",         inline=True)
        embed.add_field(name="♀️ Femininos",           value=f"**{stats['Female']}**",       inline=True)
        embed.add_field(name="♂️ Masculinos",          value=f"**{stats['Male']}**",          inline=True)
        embed.add_field(name="❓ Desconhecido",         value=f"**{stats['Unknown']}**",      inline=True)

        pct = round((stats['Female'] + stats['Male']) / max(1, total) * 100)
        embed.add_field(
            name="📈 Cobertura de gênero",
            value=f"**{pct}%** identificados",
            inline=False,
        )

        if profiles:
            contributors = "\n".join(
                f"• **{v['username']}** (importado em {(v.get('last_import') or 'nunca')[:10]})"
                for v in list(profiles.values())[:8]
            )
            embed.add_field(name="🤝 Contribuidores MAL", value=contributors, inline=False)

        embed.set_footer(text="$topchars [N] para importar top populares | $importarmal para importar do perfil")
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(MalProfile(bot))

"""
cogs/characters.py — Comandos principais de roll e claim, estilo Mudae.
Inclui exibição de stats RPG no embed e comando $status.
"""

import discord
from discord.ext import commands
from discord import ui
import asyncio
import time
import aiohttp
from character_api import get_random_character, populate_cache, cache_size, fetch_single_character, _calc_kakera
from database import get_user, save_user, claim_character, is_claimed, set_claimed, add_kakera
from stats_engine import format_stats_field, star_rating, generate_stats

# ── Constantes visuais ─────────────────────────────────────────────────────────

KAKERA_EMOJI   = "💲"
HEART_EMOJI    = "🟩"
KAKERA_COLOR   = 0x9B59B6
WAIFU_COLOR    = 0xFF69B4
HUSBANDO_COLOR = 0x4169E1
CLAIM_COLOR    = 0x2ECC71

ROLL_COOLDOWN  = 3
CLAIM_COOLDOWN = 450  # 7 min


# ── Embed builder ──────────────────────────────────────────────────────────────

def _build_character_embed(
    character: dict,
    color: int = WAIFU_COLOR,
    footer: str | None = None,
) -> discord.Embed:
    """Constrói o embed estilo 'prévia de link' do Mudae com stats RPG."""
    kakera = character.get("col", 50)
    stats  = character.get("stats")
    genres = character.get("genres", [])
    genre_str = ", ".join(genres[:3]) if genres else "—"

    stars = star_rating(stats) if stats else "⭐"

    embed = discord.Embed(
        title=f"{stars}  {character['name']}",
        description=f"✨ *{character['anime']}*\n🎭 `{genre_str}`",
        color=color,
    )
    embed.set_image(url=character["image_url"])

    # ── Stats RPG ──────────────────────────────────────────────────────────────
    if stats:
        embed.add_field(
            name="📊 Status",
            value=format_stats_field(stats),
            inline=False,
        )

    # ── Info row ───────────────────────────────────────────────────────────────
    embed.add_field(name=f"{KAKERA_EMOJI} Col", value=f"**{kakera}**", inline=True)
    embed.add_field(name="❤️ Favoritos", value=f"**{character.get('favorites', 0):,}**", inline=True)

    if footer:
        embed.set_footer(text=footer)
    else:
        embed.set_footer(text="🟩 Claim  •  💲 Kakera")

    return embed


# ── View (botões) ──────────────────────────────────────────────────────────────

class CharacterView(ui.View):
    def __init__(self, character: dict, roller_id: int):
        super().__init__(timeout=60)
        self.character = character
        self.roller_id = roller_id
        self.claimed   = False

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(view=self)
        except Exception:
            pass

    @ui.button(label="🟩  Recruit", style=discord.ButtonStyle.danger, custom_id="claim_btn")
    async def claim_button(self, interaction: discord.Interaction, button: ui.Button):
        user     = interaction.user
        guild_id = interaction.guild_id
        char_id  = self.character["mal_id"]

        owner_id = is_claimed(guild_id, char_id)
        if owner_id:
            owner = interaction.guild.get_member(owner_id) or f"<@{owner_id}>"
            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"❌ **{self.character['name']}** já pertence a {owner}!",
                    color=0xFF0000,
                ),
                ephemeral=True,
            )
            return

        db_user    = get_user(user.id)
        last_claim = db_user.get("last_claim", 0)
        elapsed    = time.time() - last_claim
        if elapsed < CLAIM_COOLDOWN:
            remaining = int(CLAIM_COOLDOWN - elapsed)
            m, s = divmod(remaining, 60)
            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"⏳ Próximo claim em **{m}m {s}s**.",
                    color=0xFF6B6B,
                ),
                ephemeral=True,
            )
            return

        success = claim_character(user.id, self.character)
        if success:
            db_user["last_claim"] = time.time()
            save_user(user.id, db_user)
            set_claimed(guild_id, char_id, user.id)

        self.claimed      = True
        button.disabled   = True
        button.label      = f"💖  {user.display_name}"
        button.style      = discord.ButtonStyle.success
        for item in self.children:
            if getattr(item, "custom_id", None) == "kakera_btn":
                item.disabled = True

        embed = _build_character_embed(
            self.character, color=CLAIM_COLOR,
            footer=f"✨ Casado(a) com {user.display_name}!",
        )
        await interaction.response.edit_message(embed=embed, view=self)
        await interaction.followup.send(
            f"{HEART_EMOJI} **{user.mention}** acabou de recrutar"
            f"**{self.character['name']}** de *{self.character['anime']}*!"
        )

    @ui.button(label="💲 Col", style=discord.ButtonStyle.secondary, custom_id="kakera_btn")
    async def kakera_button(self, interaction: discord.Interaction, button: ui.Button):
        if self.claimed:
            await interaction.response.send_message(
                "❌ Este personagem já foi reivindicado!", ephemeral=True
            )
            return

        user        = interaction.user
        db_user     = get_user(user.id)
        kakera_gain = self.character.get("Col", 50)

        if db_user.get("last_kakera_char") == self.character["mal_id"]:
            await interaction.response.send_message(
                "❌ Você já coletou os cols deste personagem!", ephemeral=True
            )
            return

        total = add_kakera(user.id, kakera_gain)
        db_user["last_kakera_char"] = self.character["mal_id"]
        save_user(user.id, db_user)

        button.disabled = True
        button.label    = f"🔮  +{kakera_gain}"
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(
            f"{KAKERA_EMOJI} **{user.mention}** coletou **{kakera_gain} Cols** "
            f"de {self.character['name']}! *(Total: {total})*"
        )


# ── Cog principal ──────────────────────────────────────────────────────────────

class Characters(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.loop.create_task(self._init_cache())

    async def _init_cache(self):
        await self.bot.wait_until_ready()
        if cache_size() < 30:
            print("  ⏳ Populando cache de personagens (pode demorar ~60s)...")
            added = await populate_cache(max_animes=8)
            print(f"  ✔ Cache pronto: {cache_size()} personagens (+{added} novos)")

    # ── $wa ────────────────────────────────────────────────────────────────────

    @commands.command(name="wa", aliases=["waifu", "w"])
    @commands.cooldown(1, ROLL_COOLDOWN, commands.BucketType.user)
    async def roll_waifu(self, ctx: commands.Context):
        """Rola um personagem aleatório."""
        await self._roll(ctx, color=WAIFU_COLOR)

    # ── $ha ────────────────────────────────────────────────────────────────────

    @commands.command(name="ha", aliases=["husbando", "h"])
    @commands.cooldown(1, ROLL_COOLDOWN, commands.BucketType.user)
    async def roll_husbando(self, ctx: commands.Context):
        """Rola um personagem aleatório."""
        await self._roll(ctx, color=HUSBANDO_COLOR)

    # ── Roll compartilhado ─────────────────────────────────────────────────────

    async def _roll(self, ctx: commands.Context, color: int = WAIFU_COLOR):
        if cache_size() == 0:
            await ctx.send(embed=discord.Embed(
                description="⏳ Cache ainda carregando, tente em instantes...",
                color=0xFFA500,
            ))
            return

        character = get_random_character()
        if not character:
            await ctx.send("❌ Nenhum personagem encontrado no cache!")
            return

        # Garante que o personagem tem stats (retrocompatibilidade)
        if "stats" not in character:
            character["stats"] = generate_stats(
                favorites=character.get("favorites", 0),
                genres=character.get("genres", []),
                seed=character["mal_id"],
            )

        guild_id = ctx.guild.id if ctx.guild else 0
        owner_id = is_claimed(guild_id, character["mal_id"])

        if owner_id:
            owner      = ctx.guild.get_member(owner_id) if ctx.guild else None
            owner_name = owner.display_name if owner else f"<@{owner_id}>"
            embed = _build_character_embed(character, color=0x95A5A6,
                                           footer=f"💍 Casado(a) com {owner_name}")
            view = None
        else:
            embed = _build_character_embed(character, color=color)
            view  = CharacterView(character, roller_id=ctx.author.id)

        msg = await ctx.send(embed=embed, view=view)
        if view:
            view.message = msg

    # ── $status <nome> ─────────────────────────────────────────────────────────

    @commands.command(name="status", aliases=["stats", "st"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def show_status(self, ctx: commands.Context, *, name: str):
        """Exibe os status RPG detalhados de um personagem do harém."""
        target_user = get_user(ctx.author.id)
        harem = target_user.get("harem", [])

        # Busca no harém primeiro (case-insensitive)
        character = next(
            (c for c in harem if name.lower() in c["name"].lower()), None
        )

        if not character:
            await ctx.send(
                embed=discord.Embed(
                    description=f"❌ **{name}** não encontrado no seu harém.\n"
                                f"Use `$lookup {name}` para buscar na API.",
                    color=0xFF6B6B,
                )
            )
            return

        stats = character.get("stats")
        if not stats:
            stats = generate_stats(
                favorites=character.get("favorites", 0),
                genres=character.get("genres", []),
                seed=character["mal_id"],
            )

        stars     = star_rating(stats)
        total_pow = sum(stats.values())
        genres    = character.get("genres", [])

        embed = discord.Embed(
            title=f"📊 Status — {character['name']}",
            description=(
                f"✨ *{character['anime']}*\n"
                f"🎭 `{', '.join(genres[:3]) if genres else '—'}`\n\n"
                f"**Classificação:** {stars}\n"
                f"**Poder Total:** `{total_pow}`"
            ),
            color=WAIFU_COLOR,
        )
        embed.set_thumbnail(url=character.get("image_url", ""))
        embed.add_field(
            name="Atributos",
            value=format_stats_field(stats),
            inline=False,
        )
        embed.add_field(name=f"{KAKERA_EMOJI} Col", value=f"**{character.get('Col', 50)}**", inline=True)
        embed.add_field(name="❤️ Favoritos", value=f"**{character.get('favorites', 0):,}**", inline=True)
        embed.set_footer(text="Stats gerados pelo gênero do anime + popularidade do personagem")

        await ctx.send(embed=embed)

    # ── $lookup ────────────────────────────────────────────────────────────────

    @commands.command(name="lookup", aliases=["char", "character"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def lookup_character(self, ctx: commands.Context, *, name: str):
        """Busca um personagem pelo nome no MAL."""
        async with ctx.typing():
            url = f"https://api.jikan.moe/v4/characters?q={name}&limit=1"
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        await ctx.send("❌ Erro ao consultar a API.")
                        return
                    data    = await resp.json()
                    results = data.get("data", [])
                    if not results:
                        await ctx.send(f"❌ Nenhum personagem encontrado para **{name}**.")
                        return
                    r          = results[0]
                    anime_list = r.get("anime", [])
                    anime_name = anime_list[0]["anime"]["title"] if anime_list else "Unknown"
                    favorites  = r.get("favorites", 0)

                    character = {
                        "mal_id":    r["mal_id"],
                        "name":      r.get("name", "???"),
                        "anime":     anime_name,
                        "genres":    [],
                        "image_url": r.get("images", {}).get("jpg", {}).get("image_url", ""),
                        "favorites": favorites,
                        "kakera":    _calc_kakera(favorites),
                        "stats":     generate_stats(favorites=favorites, genres=[], seed=r["mal_id"]),
                    }

        embed = _build_character_embed(character, color=WAIFU_COLOR,
                                       footer="💡 Use $wa para rolar personagens aleatórios")
        view = CharacterView(character, roller_id=ctx.author.id)
        msg  = await ctx.send(embed=embed, view=view)
        view.message = msg

    # ── $harem ─────────────────────────────────────────────────────────────────

    @commands.command(name="team", aliases=["mm"])
    async def show_harem(self, ctx: commands.Context, member: discord.Member | None = None):
        """Exibe o harém de um usuário."""
        target = member or ctx.author
        user   = get_user(target.id)
        harem  = user.get("team", [])

        if not harem:
            await ctx.send(embed=discord.Embed(
                description=f"💔 {target.mention} ainda não tem personagens!\nUse `$wa` para rolar.",
                color=0xFF6B6B,
            ))
            return

        per_page     = 5
        pages        = [harem[i:i+per_page] for i in range(0, len(harem), per_page)]
        kakera_total = user.get("Col", 0)

        embed = discord.Embed(
            title=f"Equipe de {target.display_name}",
            description=f"{KAKERA_EMOJI} **{kakera_total} Col** | **{len(harem)} personagens**",
            color=WAIFU_COLOR,
        )
        for char in pages[0]:
            stats     = char.get("stats", {})
            total_pow = sum(stats.values()) if stats else 0
            stars     = star_rating(stats) if stats else "⭐"
            embed.add_field(
                name=f"{stars} {char['name']}",
                value=f"*{char['anime']}*  •  {KAKERA_EMOJI}{char['Col']}  •  ⚡`{total_pow}`",
                inline=False,
            )
        if pages[0]:
            embed.set_thumbnail(url=pages[0][0]["image_url"])
        embed.set_footer(text=f"Página 1/{len(pages)} • Use $status <nome> para detalhes")
        await ctx.send(embed=embed)

    # ── $kakera ────────────────────────────────────────────────────────────────

    @commands.command(name="Col", aliases=["CC"])
    async def show_kakera(self, ctx: commands.Context, member: discord.Member | None = None):
        target = member or ctx.author
        user   = get_user(target.id)
        total  = user.get("Col", 0)
        embed  = discord.Embed(
            title=f"{KAKERA_EMOJI} Cols de {target.display_name}",
            description=f"**{total:,}** {KAKERA_EMOJI}",
            color=KAKERA_COLOR,
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        await ctx.send(embed=embed)

    # ── $updatecache (admin) ───────────────────────────────────────────────────

    @commands.command(name="updatecache")
    @commands.has_permissions(administrator=True)
    async def update_cache(self, ctx: commands.Context, amount: int = 5):
        msg   = await ctx.send(f"⏳ Buscando personagens de **{amount}** animes...")
        added = await populate_cache(max_animes=amount)
        await msg.edit(content=f"✅ Cache atualizado! **+{added}** novos personagens. Total: **{cache_size()}**")


async def setup(bot: commands.Bot):
    await bot.add_cog(Characters(bot))

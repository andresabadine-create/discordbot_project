"""
cogs/characters.py — Roll, Claim, Equipe, Status.
"""

import discord
from discord.ext import commands
from discord import ui
import asyncio
import time
import aiohttp

from character_api import get_random_character, populate_cache, cache_size, _calc_kakera, update_genders, gender_stats
from database import get_user, save_user, claim_character, update_last_claim, is_claimed, set_claimed, add_cols
from stats_engine import format_stats_field, star_rating, generate_stats

# ── Constantes ─────────────────────────────────────────────────────────────────
COL_EMOJI      = "💲"
HEART_EMOJI    = "🟩"
KAKERA_COLOR   = 0x9B59B6
WAIFU_COLOR    = 0xFF69B4
HUSBANDO_COLOR = 0x4169E1
CLAIM_COLOR    = 0x2ECC71

ROLL_COOLDOWN  = 3
CLAIM_COOLDOWN = 450  # 7.5 min


# ── Embed ──────────────────────────────────────────────────────────────────────

def build_character_embed(
    character: dict,
    color: int = WAIFU_COLOR,
    footer: str | None = None,
) -> discord.Embed:
    cols      = character.get("Cols", 50)
    stats     = character.get("stats")
    genres    = character.get("genres", [])
    genre_str = ", ".join(genres[:3]) if genres else "—"
    stars     = star_rating(stats) if stats else "⭐"

    embed = discord.Embed(
        title=f"{stars}  {character['name']}",
        description=f"✨ *{character['anime']}*\n🎭 `{genre_str}`",
        color=color,
    )
    embed.set_image(url=character["image_url"])

    if stats:
        embed.add_field(name="📊 Status", value=format_stats_field(stats), inline=False)

    embed.add_field(name=f"{COL_EMOJI} Cols",  value=f"**{cols}**",                              inline=True)
    embed.add_field(name="❤️ Favoritos",        value=f"**{character.get('favorites', 0):,}**",   inline=True)

    embed.set_footer(text=footer or f"{HEART_EMOJI} Recruit  •  {COL_EMOJI} Cols  •  $batalha para combates")
    return embed


# ── View ───────────────────────────────────────────────────────────────────────

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

    @ui.button(label="🟩  Recruit", style=discord.ButtonStyle.success, custom_id="claim_btn")
    async def claim_button(self, interaction: discord.Interaction, button: ui.Button):
        try:
            user     = interaction.user
            guild_id = interaction.guild_id
            char_id  = self.character["mal_id"]

            # Normaliza chave de valor (retrocompatibilidade kakera → Cols)
            if "Cols" not in self.character:
                self.character["Cols"] = self.character.pop("kakera", 50)

            # Já foi recrutado nesta guild?
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

            # Cooldown
            db_user    = get_user(user.id)
            last_claim = db_user.get("last_claim", 0)
            elapsed    = time.time() - last_claim
            if elapsed < CLAIM_COOLDOWN:
                remaining = int(CLAIM_COOLDOWN - elapsed)
                m, s = divmod(remaining, 60)
                await interaction.response.send_message(
                    embed=discord.Embed(
                        description=f"⏳ Próximo recruit em **{m}m {s}s**.",
                        color=0xFF6B6B,
                    ),
                    ephemeral=True,
                )
                return

            # Executa claim atomicamente
            success = claim_character(user.id, self.character)
            if success:
                set_claimed(guild_id, char_id, user.id)
                update_last_claim(user.id)

            self.claimed    = True
            button.disabled = True
            button.label    = f"✅  {user.display_name}"
            button.style    = discord.ButtonStyle.secondary
            for item in self.children:
                if getattr(item, "custom_id", None) == "cols_btn":
                    item.disabled = True

            embed = build_character_embed(
                self.character, color=CLAIM_COLOR,
                footer=f"✨ Recrutado por {user.display_name}!",
            )
            await interaction.response.edit_message(embed=embed, view=self)
            await interaction.followup.send(
                f"{HEART_EMOJI} **{user.mention}** recrutou "
                f"**{self.character['name']}** de *{self.character['anime']}*!"
            )

        except Exception as e:
            print(f"[ERRO claim_button] {type(e).__name__}: {e}")
            try:
                await interaction.response.send_message(
                    embed=discord.Embed(
                        description=f"❌ Erro interno ao recrutar. Tente novamente.",
                        color=0xFF0000,
                    ),
                    ephemeral=True,
                )
            except Exception:
                pass

    @ui.button(label="💲 Cols", style=discord.ButtonStyle.secondary, custom_id="cols_btn")
    async def cols_button(self, interaction: discord.Interaction, button: ui.Button):
        try:
            # Normaliza chave de valor (retrocompatibilidade kakera → Cols)
            if "Cols" not in self.character:
                self.character["Cols"] = self.character.pop("kakera", 50)

            if self.claimed:
                await interaction.response.send_message(
                    "❌ Este personagem já foi recrutado!", ephemeral=True
                )
                return

            user      = interaction.user
            db_user   = get_user(user.id)
            cols_gain = self.character.get("Cols", 50)

            if db_user.get("last_kakera_char") == self.character["mal_id"]:
                await interaction.response.send_message(
                    "❌ Você já coletou os Cols deste personagem!", ephemeral=True
                )
                return

            total = add_cols(user.id, cols_gain)
            db_user = get_user(user.id)
            db_user["last_kakera_char"] = self.character["mal_id"]
            save_user(user.id, db_user)

            button.disabled = True
            button.label    = f"💲 +{cols_gain}"
            await interaction.response.edit_message(view=self)
            await interaction.followup.send(
                f"{COL_EMOJI} **{user.mention}** coletou **{cols_gain} Cols** "
                f"de {self.character['name']}! *(Total: {total})*"
            )

        except Exception as e:
            print(f"[ERRO cols_button] {type(e).__name__}: {e}")
            try:
                await interaction.response.send_message(
                    embed=discord.Embed(
                        description="❌ Erro interno ao coletar Cols. Tente novamente.",
                        color=0xFF0000,
                    ),
                    ephemeral=True,
                )
            except Exception:
                pass


# ── Cog ────────────────────────────────────────────────────────────────────────

class Characters(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.loop.create_task(self._init_cache())

    async def _init_cache(self):
        await self.bot.wait_until_ready()
        if cache_size() < 50:
            print("  ⏳ Populando cache de personagens (pode demorar ~90s)...")
            added = await populate_cache(max_animes=12)
            print(f"  ✔ Cache pronto: {cache_size()} personagens (+{added} novos)")

    # ── $f / $femea ────────────────────────────────────────────────────────────

    @commands.command(name="f", aliases=["femea", "wa", "waifu"])
    @commands.cooldown(1, ROLL_COOLDOWN, commands.BucketType.user)
    async def roll_femea(self, ctx: commands.Context):
        """Rola um personagem feminino aleatório."""
        await self._roll(ctx, color=WAIFU_COLOR, gender_filter="Female")

    # ── $cu / $macho ───────────────────────────────────────────────────────────

    @commands.command(name="cu", aliases=["macho", "ha", "husbando"])
    @commands.cooldown(1, ROLL_COOLDOWN, commands.BucketType.user)
    async def roll_macho(self, ctx: commands.Context):
        """Rola um personagem masculino aleatório."""
        await self._roll(ctx, color=HUSBANDO_COLOR, gender_filter="Male")

    # ── Roll compartilhado ─────────────────────────────────────────────────────

    async def _roll(self, ctx: commands.Context, color: int, gender_filter: str | None = None):
        if cache_size() == 0:
            await ctx.send(embed=discord.Embed(
                description="⏳ Cache ainda carregando, tente em instantes...",
                color=0xFFA500,
            ))
            return

        character = get_random_character(gender_filter=gender_filter)
        if not character:
            await ctx.send("❌ Nenhum personagem encontrado no cache!")
            return

        # Retrocompatibilidade: garante campos obrigatórios
        if "stats" not in character:
            character["stats"] = generate_stats(
                favorites=character.get("favorites", 0),
                genres=character.get("genres", []),
                seed=character["mal_id"],
            )
        if "Cols" not in character:
            character["Cols"] = character.pop("kakera", 50)

        guild_id = ctx.guild.id if ctx.guild else 0
        owner_id = is_claimed(guild_id, character["mal_id"])

        if owner_id:
            owner      = ctx.guild.get_member(owner_id) if ctx.guild else None
            owner_name = owner.display_name if owner else f"<@{owner_id}>"
            embed = build_character_embed(character, color=0x95A5A6,
                                          footer=f"💍 Recrutado por {owner_name}")
            view = None
        else:
            embed = build_character_embed(character, color=color)
            view  = CharacterView(character, roller_id=ctx.author.id)

        msg = await ctx.send(embed=embed, view=view)
        if view:
            view.message = msg

    # ── $status ────────────────────────────────────────────────────────────────

    @commands.command(name="status", aliases=["stats", "st"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def show_status(self, ctx: commands.Context, *, name: str):
        """Exibe os status RPG de um personagem da sua Equipe."""
        db_user   = get_user(ctx.author.id)
        equipe    = db_user.get("Equipe", [])
        character = next((c for c in equipe if name.lower() in c["name"].lower()), None)

        if not character:
            await ctx.send(embed=discord.Embed(
                description=f"❌ **{name}** não encontrado na sua Equipe.\nUse `$lookup {name}` para buscar.",
                color=0xFF6B6B,
            ))
            return

        stats = character.get("stats") or generate_stats(
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
                f"**Classificação:** {stars}   **Poder Total:** `{total_pow}`"
            ),
            color=WAIFU_COLOR,
        )
        embed.set_thumbnail(url=character.get("image_url", ""))
        embed.add_field(name="Atributos", value=format_stats_field(stats), inline=False)
        embed.add_field(name=f"{COL_EMOJI} Cols",  value=f"**{character.get('Cols', 50)}**",           inline=True)
        embed.add_field(name="❤️ Favoritos",        value=f"**{character.get('favorites', 0):,}**",     inline=True)
        embed.set_footer(text="Stats gerados pelo gênero do anime + popularidade • Use $batalha para combater!")
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
                    character  = {
                        "mal_id":    r["mal_id"],
                        "name":      r.get("name", "???"),
                        "anime":     anime_name,
                        "genres":    [],
                        "image_url": r.get("images", {}).get("jpg", {}).get("image_url", ""),
                        "favorites": favorites,
                        "Cols":      _calc_kakera(favorites),
                        "stats":     generate_stats(favorites=favorites, genres=[], seed=r["mal_id"]),
                    }

        embed = build_character_embed(character, color=WAIFU_COLOR,
                                      footer="💡 Use $f ou $cu para rolar personagens aleatórios")
        view = CharacterView(character, roller_id=ctx.author.id)
        msg  = await ctx.send(embed=embed, view=view)
        view.message = msg

    # ── $team ──────────────────────────────────────────────────────────────────

    @commands.command(name="team", aliases=["equipe", "myteam"])
    async def show_team(self, ctx: commands.Context, member: discord.Member | None = None):
        """Exibe a Equipe de um usuário."""
        target   = member or ctx.author
        db_user  = get_user(target.id)
        equipe   = db_user.get("Equipe", [])
        cols_tot = db_user.get("Cols", 0)

        if not equipe:
            await ctx.send(embed=discord.Embed(
                description=f"💔 {target.mention} ainda não tem personagens!\nUse `$f` ou `$cu` para rolar.",
                color=0xFF6B6B,
            ))
            return

        per_page = 5
        pages    = [equipe[i:i+per_page] for i in range(0, len(equipe), per_page)]

        embed = discord.Embed(
            title=f"💖 Equipe de {target.display_name}",
            description=f"{COL_EMOJI} **{cols_tot:,} Cols** | **{len(equipe)} personagens**",
            color=WAIFU_COLOR,
        )
        for char in pages[0]:
            stats     = char.get("stats", {})
            total_pow = sum(stats.values()) if stats else 0
            stars     = star_rating(stats) if stats else "⭐"
            embed.add_field(
                name=f"{stars} {char['name']}",
                value=f"*{char['anime']}*  •  {COL_EMOJI}{char.get('Cols', 50)}  •  ⚡`{total_pow}`",
                inline=False,
            )
        if pages[0]:
            embed.set_thumbnail(url=pages[0][0]["image_url"])
        embed.set_footer(text=f"Página 1/{len(pages)} • $status <nome> para detalhes • $batalha @alguém para combater")
        await ctx.send(embed=embed)

    # ── $cols ──────────────────────────────────────────────────────────────────

    @commands.command(name="cols", aliases=["col", "kk"])
    async def show_cols(self, ctx: commands.Context, member: discord.Member | None = None):
        """Mostra o saldo de Cols."""
        target  = member or ctx.author
        db_user = get_user(target.id)
        total   = db_user.get("Cols", 0)
        embed   = discord.Embed(
            title=f"{COL_EMOJI} Cols de {target.display_name}",
            description=f"**{total:,}** {COL_EMOJI}",
            color=KAKERA_COLOR,
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        await ctx.send(embed=embed)

    # ── $updatecache (admin) ───────────────────────────────────────────────────

    @commands.command(name="updatecache")
    @commands.has_permissions(administrator=True)
    async def update_cache(self, ctx: commands.Context, amount: int = 5):
        """[Admin] Atualiza o cache buscando N animes."""
        msg   = await ctx.send(f"⏳ Buscando personagens de **{amount}** animes (inclui gênero para Main)...")
        added = await populate_cache(max_animes=amount)
        stats = gender_stats()
        await msg.edit(
            content=(
                f"✅ Cache atualizado! **+{added}** novos personagens. Total: **{cache_size()}**\n"
                f"♀️ Femininos: **{stats['Female']}** | ♂️ Masculinos: **{stats['Male']}** | ❓ Desconhecido: **{stats['Unknown']}**"
            )
        )

    @commands.command(name="updategender", aliases=["ug"])
    @commands.has_permissions(administrator=True)
    async def update_genders_cmd(self, ctx: commands.Context, amount: int = 50):
        """[Admin] Preenche gênero dos personagens Unknown no cache (N por vez)."""
        stats_before = gender_stats()
        msg = await ctx.send(
            f"⏳ Buscando gênero de até **{amount}** personagens desconhecidos...\n"
            f"*(Atualmente: ❓ {stats_before['Unknown']} desconhecidos)*"
        )
        updated = await update_genders(limit=amount)
        stats   = gender_stats()
        await msg.edit(content=(
            f"✅ Gênero atualizado para **{updated}** personagens!\n"
            f"♀️ Femininos: **{stats['Female']}** | ♂️ Masculinos: **{stats['Male']}** | ❓ Desconhecido: **{stats['Unknown']}**\n"
            f"*Use `$updategender {amount}` novamente para continuar preenchendo.*"
        ))

    @commands.command(name="cachestats", aliases=["cs"])
    @commands.has_permissions(administrator=True)
    async def cache_stats_cmd(self, ctx: commands.Context):
        """[Admin] Mostra estatísticas do cache de personagens."""
        stats = gender_stats()
        total = cache_size()
        embed = discord.Embed(title="📊 Cache Stats", color=0x9B59B6)
        embed.add_field(name="Total", value=f"**{total}**", inline=True)
        embed.add_field(name="♀️ Femininos", value=f"**{stats['Female']}**", inline=True)
        embed.add_field(name="♂️ Masculinos", value=f"**{stats['Male']}**", inline=True)
        embed.add_field(name="❓ Desconhecido", value=f"**{stats['Unknown']}**", inline=True)
        pct_known = round((stats['Female'] + stats['Male']) / max(1, total) * 100)
        embed.set_footer(text=f"{pct_known}% dos personagens têm gênero identificado • Use $updategender para completar")
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Characters(bot))

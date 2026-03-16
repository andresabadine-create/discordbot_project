"""
cogs/characters.py — Comandos principais de roll e claim, estilo Mudae.
"""

import discord
from discord.ext import commands
from discord import ui
import asyncio
import random
from character_api import get_random_character, populate_cache, cache_size, fetch_single_character
from database import get_user, save_user, claim_character, is_claimed, set_claimed, add_kakera

# ── Constantes visuais ─────────────────────────────────────────────────────────

KAKERA_EMOJI = "🙈"
HEART_EMOJI   = "👽"

KAKERA_COLOR = 0x9B59B6  # roxo kakera
WAIFU_COLOR  = 0xFF69B4  # rosa waifu
HUSBANDO_COLOR = 0x4169E1  # azul husbando
CLAIM_COLOR  = 0x2ECC71  # verde claim

ROLL_COOLDOWN = 3   # segundos entre rolls
CLAIM_COOLDOWN = 900  # 15 min entre claims


# ── Views (Botões interativos) ─────────────────────────────────────────────────

class CharacterView(ui.View):
    """View com botões de Claim e Kakera, expira em 60 segundos."""

    def __init__(self, character: dict, roller_id: int):
        super().__init__(timeout=60)
        self.character = character
        self.roller_id = roller_id
        self.claimed = False

    async def on_timeout(self):
        # Desabilita todos os botões ao expirar
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(view=self)
        except Exception:
            pass

    # ── Botão: Claim / Marrry ───────────────────────────────────────────────────

    @ui.button(label="👽  Sequestre", style=discord.ButtonStyle.danger, custom_id="claim_btn")
    async def claim_button(self, interaction: discord.Interaction, button: ui.Button):
        user = interaction.user
        guild_id = interaction.guild_id
        char_id = self.character["mal_id"]

        # Verifica se já foi reivindicado nesta guild
        owner_id = is_claimed(guild_id, char_id)
        if owner_id:
            owner = interaction.guild.get_member(owner_id) or f"<@{owner_id}>"
            embed = discord.Embed(
                description=f"❌ **{self.character['name']}** já pertence a {owner}!",
                color=0xFF0000,
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Cooldown de claim (15 min)
        db_user = get_user(user.id)
        import time
        last_claim = db_user.get("last_claim", 0)
        elapsed = time.time() - last_claim
        if elapsed < CLAIM_COOLDOWN:
            remaining = int(CLAIM_COOLDOWN - elapsed)
            m, s = divmod(remaining, 60)
            embed = discord.Embed(
                description=f"⏳ Próximo sequestro em **{m}m {s}s**.",
                color=0xFF6B6B,
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Executa o claim
        import time
        success = claim_character(user.id, self.character)
        if success:
            db_user["last_claim"] = time.time()
            save_user(user.id, db_user)
            set_claimed(guild_id, char_id, user.id)

        self.claimed = True
        button.disabled = True
        button.label = f"👽  {user.display_name}"
        button.style = discord.ButtonStyle.success

        # Desabilita botão de kakera também
        for item in self.children:
            if hasattr(item, "custom_id") and item.custom_id == "kakera_btn":
                item.disabled = True

        embed = _build_character_embed(
            self.character,
            color=CLAIM_COLOR,
            footer=f"✨ Sequestrado por {user.display_name}!",
        )
        await interaction.response.edit_message(embed=embed, view=self)

        # Mensagem pública de claim
        await interaction.followup.send(
            f"{HEART_EMOJI} **{user.mention}** acabou de sequestrar o/a "
            f"**{self.character['name']}** de *{self.character['anime']}*!"
        )

    # ── Botão: Kakera ──────────────────────────────────────────────────────────

    @ui.button(label=f"🇨🇳  SOCIAL CREDITS", style=discord.ButtonStyle.secondary, custom_id="kakera_btn")
    async def kakera_button(self, interaction: discord.Interaction, button: ui.Button):
        if self.claimed:
            await interaction.response.send_message(
                "❌ Este personagem já foi sequestrado!", ephemeral=True
            )
            return

        user = interaction.user
        db_user = get_user(user.id)
        kakera_gained = self.character.get("SOCIAL CREDITS", 50)

        # Impede coletar kakera do próprio roll mais de uma vez
        if db_user.get("last_kakera_char") == self.character["mal_id"]:
            await interaction.response.send_message(
                "❌ Você já coletou os social credits deste personagem!", ephemeral=True
            )
            return

        total = add_kakera(user.id, kakera_gained)
        db_user["last_kakera_char"] = self.character["mal_id"]
        save_user(user.id, db_user)

        button.disabled = True
        button.label = f"🇨🇳  +{kakera_gained}"

        await interaction.response.edit_message(view=self)
        await interaction.followup.send(
            f"{KAKERA_EMOJI} **{user.mention}** coletou **{kakera_gained} social credits** "
            f"de {self.character['name']}! *(Total: {total})*",
            ephemeral=False,
        )


# ── Embed builder ──────────────────────────────────────────────────────────────

def _build_character_embed(
    character: dict,
    color: int = WAIFU_COLOR,
    footer: str | None = None,
) -> discord.Embed:
    """Constrói o embed estilo 'prévia de link' do Mudae."""
    kakera = character.get("SOCIAL CREDITS", 50)

    embed = discord.Embed(
        title=character["name"],
        description=f"✨ *{character['anime']}*",
        color=color,
    )
    embed.set_image(url=character["image_url"])
    embed.add_field(
        name=f"{KAKERA_EMOJI} SOCIAL CREDIT",
        value=f"**{kakera}**",
        inline=True,
    )
    embed.add_field(
        name="👽 Favoritos (MAL)",
        value=f"**{character.get('favorites', 0):,}**",
        inline=True,
    )
    if footer:
        embed.set_footer(text=footer)
    else:
        embed.set_footer(text="Use 👽 para sequestrar • 🙈 para coletar SOCIAL CREDITS")

    return embed


# ── Cog principal ──────────────────────────────────────────────────────────────

class Characters(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.loop.create_task(self._init_cache())

    async def _init_cache(self):
        await self.bot.wait_until_ready()
        if cache_size() < 30:
            print("  ⏳ Populando cache de personagens (pode demorar ~30s)...")
            added = await populate_cache(max_animes=8)
            print(f"  ✔ Cache pronto: {cache_size()} personagens (+{added} novos)")

    # ── $wa / $waifu ───────────────────────────────────────────────────────────

    @commands.command(name="wa", aliases=["waifu", "w"])
    @commands.cooldown(1, ROLL_COOLDOWN, commands.BucketType.user)
    async def roll_waifu(self, ctx: commands.Context):
        """Rola um personagem feminino aleatório."""
        await self._roll(ctx, color=WAIFU_COLOR)

    # ── $ha / $husbando ────────────────────────────────────────────────────────

    @commands.command(name="ha", aliases=["husbando", "h"])
    @commands.cooldown(1, ROLL_COOLDOWN, commands.BucketType.user)
    async def roll_husbando(self, ctx: commands.Context):
        """Rola um personagem masculino aleatório."""
        await self._roll(ctx, color=HUSBANDO_COLOR)

    # ── Lógica de roll compartilhada ───────────────────────────────────────────

    async def _roll(self, ctx: commands.Context, color: int = WAIFU_COLOR):
        if cache_size() == 0:
            embed = discord.Embed(
                description="⏳ Cache ainda carregando, tente em instantes...",
                color=0xFFA500,
            )
            await ctx.send(embed=embed)
            return

        character = get_random_character()
        if not character:
            await ctx.send("❌ Nenhum personagem encontrado no cache!")
            return

        guild_id = ctx.guild.id if ctx.guild else 0
        owner_id = is_claimed(guild_id, character["mal_id"])

        if owner_id:
            owner = ctx.guild.get_member(owner_id) if ctx.guild else None
            owner_name = owner.display_name if owner else f"<@{owner_id}>"
            embed = _build_character_embed(character, color=0x95A5A6,
                                           footer=f"💍 Sequestrado pelo {owner_name}")
            view = None
        else:
            embed = _build_character_embed(character, color=color)
            view = CharacterView(character, roller_id=ctx.author.id)

        msg = await ctx.send(embed=embed, view=view)
        if view:
            view.message = msg

    # ── $lookup <nome> ─────────────────────────────────────────────────────────

    @commands.command(name="lookup", aliases=["char", "character"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def lookup_character(self, ctx: commands.Context, *, name: str):
        """Busca um personagem pelo nome no MAL."""
        async with ctx.typing():
            url = f"https://api.jikan.moe/v4/characters?q={name}&limit=1"
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        await ctx.send("❌ Erro ao consultar a API.")
                        return
                    data = await resp.json()
                    results = data.get("data", [])
                    if not results:
                        await ctx.send(f"❌ Nenhum personagem encontrado para **{name}**.")
                        return
                    r = results[0]
                    anime_list = r.get("anime", [])
                    anime_name = anime_list[0]["anime"]["title"] if anime_list else "Unknown"
                    favorites = r.get("favorites", 0)
                    character = {
                        "mal_id": r["mal_id"],
                        "name": r.get("name", "???"),
                        "anime": anime_name,
                        "image_url": r.get("images", {}).get("jpg", {}).get("image_url", ""),
                        "favorites": favorites,
                        "SOCIAL CREDIT": _calc_kakera_public(favorites),
                    }

            embed = _build_character_embed(character, color=WAIFU_COLOR,
                                           footer="💡 Use $wa para rolar personagens aleatórios")
            view = CharacterView(character, roller_id=ctx.author.id)
            msg = await ctx.send(embed=embed, view=view)
            view.message = msg

    # ── $harem ─────────────────────────────────────────────────────────────────

    @commands.command(name="harem", aliases=["mm", "mywaifu"])
    async def show_harem(self, ctx: commands.Context, member: discord.Member | None = None):
        """Exibe o harém de um usuário."""
        target = member or ctx.author
        user = get_user(target.id)
        harem = user.get("harem", [])

        if not harem:
            embed = discord.Embed(
                description=f"💔 {target.mention} ainda não tem personagens no comboio!\nUse `$wa` para rolar.",
                color=0xFF6B6B,
            )
            await ctx.send(embed=embed)
            return

        # Paginação simples (5 por embed)
        per_page = 5
        pages = [harem[i:i+per_page] for i in range(0, len(harem), per_page)]
        kakera_total = user.get("kakera", 0)

        embed = discord.Embed(
            title=f"💖 Comboio de {target.display_name}",
            description=f"{KAKERA_EMOJI} **{kakera_total} SOCIAL CREDITS** | **{len(harem)} personagens**",
            color=WAIFU_COLOR,
        )
        for char in pages[0]:
            embed.add_field(
                name=char["name"],
                value=f"*{char['anime']}*  •  {KAKERA_EMOJI}{char['SOCIAL CREDITS']}",
                inline=False,
            )
        if pages[0]:
            embed.set_thumbnail(url=pages[0][0]["image_url"])
        embed.set_footer(text=f"Página 1/{len(pages)}")
        await ctx.send(embed=embed)

    # ── $kakera ────────────────────────────────────────────────────────────────

    @commands.command(name="SOCIAL CREDITS", aliases=["kk"])
    async def show_kakera(self, ctx: commands.Context, member: discord.Member | None = None):
        """Mostra o saldo de kakera de um usuário."""
        target = member or ctx.author
        user = get_user(target.id)
        total = user.get("SOCIAL CREDITS", 0)

        embed = discord.Embed(
            title=f"{KAKERA_EMOJI} SOCIAL CREDITS de {target.display_name}",
            description=f"**{total:,}** {KAKERA_EMOJI}",
            color=KAKERA_COLOR,
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        await ctx.send(embed=embed)

    # ── $updatecache (admin) ───────────────────────────────────────────────────

    @commands.command(name="updatecache")
    @commands.has_permissions(administrator=True)
    async def update_cache(self, ctx: commands.Context, amount: int = 5):
        """[Admin] Atualiza o cache de personagens buscando de novos animes."""
        msg = await ctx.send(f"⏳ Buscando personagens de **{amount}** animes...")
        added = await populate_cache(max_animes=amount)
        await msg.edit(content=f"✅ Cache atualizado! **+{added}** novos personagens. Total: **{cache_size()}**")


def _calc_kakera_public(favorites: int) -> int:
    if favorites >= 50000: return 1000
    if favorites >= 20000: return 500
    if favorites >= 5000:  return 200
    if favorites >= 1000:  return 100
    if favorites >= 100:   return 75
    return 50


async def setup(bot: commands.Bot):
    await bot.add_cog(Characters(bot))

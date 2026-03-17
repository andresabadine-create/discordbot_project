"""
cogs/profile.py — Perfil do usuário com estatísticas.
"""

import discord
from discord.ext import commands
from database import get_user
from stats_engine import star_rating

COL_EMOJI   = "💲"
WAIFU_COLOR = 0xFF69B4


class Profile(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="profile", aliases=["p", "me"])
    async def profile(self, ctx: commands.Context, member: discord.Member | None = None):
        """Exibe o perfil completo de um usuário."""
        target  = member or ctx.author
        db_user = get_user(target.id)

        equipe      = db_user.get("Equipe", [])
        cols        = db_user.get("Cols", 0)
        rolls_used  = db_user.get("rolls_used", 0)
        combates    = db_user.get("combates", {"vitorias": 0, "derrotas": 0})
        vitorias    = combates.get("vitorias", 0)
        derrotas    = combates.get("derrotas", 0)
        total_chars = len(equipe)
        valor_total = sum(c.get("Cols", 0) for c in equipe)

        embed = discord.Embed(
            title=f"📋 Perfil — {target.display_name}",
            color=WAIFU_COLOR,
        )
        embed.set_thumbnail(url=target.display_avatar.url)

        # ── Stats do jogador ───────────────────────────────────────────────────
        embed.add_field(name=f"{COL_EMOJI} Cols",       value=f"**{cols:,}**",       inline=True)
        embed.add_field(name="💖 Personagens",           value=f"**{total_chars}**",  inline=True)
        embed.add_field(name="🎲 Rolls feitos",          value=f"**{rolls_used}**",   inline=True)
        embed.add_field(name="⚔️ Vitórias",              value=f"**{vitorias}**",     inline=True)
        embed.add_field(name="💀 Derrotas",              value=f"**{derrotas}**",     inline=True)
        embed.add_field(name=f"{COL_EMOJI} Valor Equipe", value=f"**{valor_total:,}**", inline=True)

        # ── Top 3 da equipe ────────────────────────────────────────────────────
        if equipe:
            top = sorted(equipe, key=lambda c: sum(c.get("stats", {}).values()), reverse=True)[:3]
            top_lines = []
            for c in top:
                stats    = c.get("stats", {})
                stars    = star_rating(stats) if stats else "⭐"
                total_pw = sum(stats.values()) if stats else 0
                top_lines.append(f"{stars} **{c['name']}** — *{c['anime']}* — ⚡`{total_pw}`")
            embed.add_field(name="🏅 Top 3 da Equipe (por poder)", value="\n".join(top_lines), inline=False)
            embed.set_image(url=top[0]["image_url"])

        wr = round(vitorias / max(1, vitorias + derrotas) * 100) if (vitorias + derrotas) > 0 else 0
        embed.set_footer(text=f"Win Rate: {wr}% • Use $batalha @alguém para combater!")
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Profile(bot))

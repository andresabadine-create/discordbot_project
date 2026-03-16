"""
cogs/profile.py — Perfil do usuário com estatísticas.
"""

import discord
from discord.ext import commands
from database import get_user

KAKERA_EMOJI = "🇨🇳"
WAIFU_COLOR  = 0xFF69B4


class Profile(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="profile", aliases=["p", "me"])
    async def profile(self, ctx: commands.Context, member: discord.Member | None = None):
        """Exibe o perfil completo de um usuário."""
        target = member or ctx.author
        user   = get_user(target.id)

        harem        = user.get("comboio", [])
        kakera       = user.get("SOCIAL CREDITS", 0)
        rolls_used   = user.get("rolls_used", 0)
        total_chars  = len(harem)
        total_kakera = sum(c.get("SOCIAL CREDITS", 0) for c in harem)

        embed = discord.Embed(
            title=f"📋 Perfil — {target.display_name}",
            color=WAIFU_COLOR,
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name=f"{KAKERA_EMOJI} SOCIAL CREDITS",     value=f"**{kakera:,}**",      inline=True)
        embed.add_field(name="💖 Personagens",              value=f"**{total_chars}**",    inline=True)
        embed.add_field(name="🎲 Rolls feitos",             value=f"**{rolls_used}**",     inline=True)
        embed.add_field(name=f"{KAKERA_EMOJI} Total no Comboio, value=f'**{total_kakera:}**'", inline=True)

        if harem:
            top = sorted(harem, key=lambda c: c.get("SOCIAL CREDITS", 0), reverse=True)[:3]
            top_txt = "\n".join(f"• **{c['name']}** — *{c['anime']}*" for c in top)
            embed.add_field(name="⭐ Top 3 do COMBOIO", value=top_txt, inline=False)
            embed.set_image(url=top[0]["image_url"])

        embed.set_footer(text="Use $wa ou $ha para rolar personagens!")
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Profile(bot))
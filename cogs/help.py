"""
cogs/help.py — Comando $help customizado.
"""

import discord
from discord.ext import commands


class Help(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="help", aliases=["commands"])
    async def help_cmd(self, ctx: commands.Context):
        """Lista todos os comandos disponíveiss."""
        embed = discord.Embed(
            title="📖 Comandos do Bot",
            description="Clone do Mudae Bot — Colete personagens de animes!\nPrefixos: `$` ou `!`",
            color=0xFF69B4,
        )

        embed.add_field(
            name="🎲 Rolls",
            value=(
                "`$wa` / `$waifu` / `$w` — Rola personagem aleatório (waifu)\n"
                "`$ha` / `$husbando` / `$h` — Rola personagem aleatório (husbando)\n"
                "`$lookup <nome>` — Busca um personagem específico no MAL"
            ),
            inline=False,
        )
        embed.add_field(
            name="💖 Coleção",
            value=(
                "`$harem [@usuário]` — Veja seu harém ou de alguém\n"
                "`$kakera [@usuário]` — Veja o saldo de kakera\n"
                "`$profile [@usuário]` — Perfil completo"
            ),
            inline=False,
        )
        embed.add_field(
            name="⚙️ Admin",
            value="`$updatecache [N]` — Atualiza cache com N animes (padrão: 5)",
            inline=False,
        )
        embed.add_field(
            name=f"🔮 Sistema Kakera",
            value=(
                "Personagens possuem valor em **kakera** baseado nos favoritos do MAL.\n"
                "Clique em 🔮 no roll para coletar. Acumule para futuros upgrades!"
            ),
            inline=False,
        )
        embed.set_footer(text="Cooldown: 3s entre rolls • 15min entre claims")
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))
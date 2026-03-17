"""cogs/help.py"""
import discord
from discord.ext import commands

class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="ajuda", aliases=["help", "commands"])
    async def help_cmd(self, ctx):
        embed = discord.Embed(
            title="📖 Comandos — KIRITAO",
            description="Colete personagens, batalhe e ajude a expandir o banco!\nPrefixos: `$` ou `!`",
            color=0xFF69B4,
        )
        embed.add_field(name="🎲 Rolls", value=(
            "`$f` / `$femea` — Personagem **feminino** aleatório\n"
            "`$cu` / `$macho` — Personagem **masculino** aleatório\n"
            "`$lookup <nome>` — Busca no MAL\n"
            "*Cooldown: 3s*"
        ), inline=False)
        embed.add_field(name="💖 Equipe", value=(
            "`$team [@user]` — Ver Equipe\n"
            "`$status <nome>` — Stats RPG do personagem\n"
            "`$cols [@user]` — Saldo de Cols\n"
            "`$profile [@user]` — Perfil completo\n"
            "*Recruit cooldown: 7.5 min*"
        ), inline=False)
        embed.add_field(name="⚔️ Batalha", value=(
            "`$batalha @oponente` — Combate por turnos\n"
            "`$ranking` — Top vitórias\n"
            "*Cooldown: 30s*"
        ), inline=False)
        embed.add_field(name="🎌 Sugestões", value=(
            "`$sugerir <anime>` — Sugere um anime\n"
            "`$sugestoes` — Fila de sugestões\n"
            "`$votar <ID>` — Vota em sugestão\n"
            "`$sugestao <ID>` — Detalhes\n"
            "*Cooldown: 60s*"
        ), inline=False)
        embed.add_field(name="🔗 Perfil MyAnimeList", value=(
            "`$linkmal <usuário>` — Vincula seu perfil MAL\n"
            "`$malperfil [@user]` — Vê perfil MAL vinculado\n"
            "`$importarmal [N]` — Importa seus animes → adiciona personagens!\n"
            "`$deslinkarmal` — Remove vínculo MAL\n"
            "*Importação cooldown: 1h | máx 50 animes por vez*"
        ), inline=False)
        embed.add_field(name="⚙️ Admin", value=(
            "`$topchars [N]` — Importa top N×25 personagens do MAL\n"
            "`$updatecache [N]` — Update via pool de animes\n"
            "`$updategender [N]` — Preenche gêneros desconhecidos\n"
            "`$aprovar/rejeitar <ID>` — Gerencia sugestões\n"
            "`$setlogchannel #canal` — Canal de log\n"
            "`$autostatus` / `$malstats` — Painel de stats\n"
            "`$cachestats` — Stats do cache"
        ), inline=False)
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.set_footer(text="Cache automático: +3 animes/6h | Top chars: semanal | Gênero: +100/24h")
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Help(bot))

### modulos de import de api
import discord
from discord.ext import commands
import asyncio
import os
import sys
from dotenv import load_dotenv
 
load_dotenv()
 
# Garante que o diretório do bot está no path do Python
# (necessário para importar 'cogs.*' independente de onde o script é executado)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
 
# ─────────────────────────────────────────
#  Configuração do Bot
# ─────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
 
class MudaeBot(commands.Bot):
    async def setup_hook(self):
        """Carrega os cogs antes de conectar ao Discord."""
        for cog in ["cogs.characters", "cogs.profile", "cogs.help"]:
            try:
                await self.load_extension(cog)
                print(f"  ✔ Cog carregado: {cog}")
            except Exception as e:
                print(f"  ✘ Falha ao carregar {cog}: {e}")
 
 
bot = MudaeBot(
    command_prefix=["$", "!"],
    intents=intents,
    help_command=None,
    case_insensitive=True,
)
# ─────────────────────────────────────────
#  Eventos
# ─────────────────────────────────────────
@bot.event
async def on_ready():
    print(f"✅  Bot conectado como: {bot.user} (ID: {bot.user.id})")
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.playing,
            name="VASCO DA GAMA E NADA MAIS!",
        )
    )
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        remaining = round(error.retry_after, 1)
        embed = discord.Embed(
            description=f"⏳ Aguarde **{remaining}s** antes de rolar novamente.",
            color=0xFF6B6B,
        )
        await ctx.send(embed=embed, delete_after=5)
    elif isinstance(error, commands.CommandNotFound):
        pass  # ignora comandos desconhecidos silenciosamente
    else:
        raise error
# ─────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────
if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise ValueError("❌  Variável DISCORD_TOKEN não encontrada no .env")
    bot.run(token)
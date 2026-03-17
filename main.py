import discord
from discord.ext import commands
import os
import sys
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True


class KiritaoBot(commands.Bot):
    async def setup_hook(self):
        for cog in ["cogs.characters", "cogs.combat", "cogs.profile", "cogs.suggestions", "cogs.mal_profile", "cogs.help"]:
            try:
                await self.load_extension(cog)
                print(f"  ✔ Cog carregado: {cog}")
            except Exception as e:
                print(f"  ✘ Falha ao carregar {cog}: {e}")


bot = KiritaoBot(
    command_prefix=["$", "!"],
    intents=intents,
    help_command=None,
    case_insensitive=True,
)


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
            description=f"⏳ Aguarde **{remaining}s** antes de usar este comando novamente.",
            color=0xFF6B6B,
        )
        await ctx.send(embed=embed, delete_after=5)
    elif isinstance(error, commands.CommandNotFound):
        pass
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Argumento faltando. Use `$ajuda` para ver os comandos.")
    else:
        raise error


if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise ValueError("❌  Variável DISCORD_TOKEN não encontrada no .env")
    bot.run(token)

"""
cogs/combat.py — Sistema de combate por turnos entre personagens.

Fluxo:
  1. $batalha @oponente  — desafiante envia convite (botões Aceitar/Recusar)
  2. Ambos escolhem um personagem da Equipe via Select Menu
  3. Combate simulado turno a turno (até 10 turnos ou HP = 0)
  4. Vencedor recebe Cols como prêmio
"""

import discord
from discord.ext import commands
from discord import ui
import random
import asyncio

from database import get_user, record_combat_result
from stats_engine import star_rating, stat_bar

# ── Constantes ─────────────────────────────────────────────────────────────────

COL_EMOJI    = "💲"
MAX_TURNS    = 10
BASE_PRIZE   = 150   # Cols para o vencedor
BONUS_PRIZE  = 10    # Cols extras por turno sobrevivido

# ── Frases de combate ──────────────────────────────────────────────────────────

ATAQUE_NORMAL = [
    "**{a}** desferiu um golpe certeiro em **{d}**!",
    "**{a}** lançou um ataque rápido contra **{d}**!",
    "**{a}** avançou ferozmente sobre **{d}**!",
    "**{a}** acertou **{d}** com um golpe poderoso!",
    "**{a}** investiu contra **{d}** sem hesitar!",
    "**{a}** usou toda a sua força contra **{d}**!",
]

ATAQUE_CRITICO = [
    "💥 **CRÍTICO!** **{a}** destruiu as defesas de **{d}**!",
    "💥 **GOLPE FATAL!** **{a}** acertou em cheio **{d}**!",
    "💥 **CRÍTICO!** **{a}** causou um dano devastador em **{d}**!",
    "💥 **ATAQUE PERFEITO!** **{a}** não deu chance a **{d}**!",
]

DESVIO = [
    "**{d}** desviou habilmente do ataque de **{a}**! *(0 de dano)*",
    "**{d}** esquivou no último segundo! *(0 de dano)*",
    "**{d}** usou sua agilidade para escapar ileso! *(0 de dano)*",
    "**{a}** errou o ataque! **{d}** saiu ileso!",
]

ESPECIAL_INT = [
    "🧠 **{a}** usou sua inteligência para enfraquecer **{d}** antes do golpe!",
    "🧠 **{a}** previu os movimentos de **{d}** e acertou o ponto fraco!",
    "🧠 **{a}** calculou o ataque perfeito contra **{d}**!",
]

VITORIA = [
    "🏆 **{w}** venceu o combate gloriosamente!",
    "🏆 **{w}** demonstrou ser o mais forte!",
    "🏆 **{w}** saiu vitorioso(a) dessa batalha épica!",
]

EMPATE = [
    "🤝 Empate! Ambos chegaram ao limite ao mesmo tempo!",
    "🤝 Que batalha! Ninguém saiu vencedor dessa!",
]


# ── HP Bar ─────────────────────────────────────────────────────────────────────

def hp_bar(current: int, max_hp: int, length: int = 12) -> str:
    ratio  = max(0, current / max_hp)
    filled = round(ratio * length)
    bar    = "█" * filled + "░" * (length - filled)
    if ratio > 0.5:
        color = "🟢"
    elif ratio > 0.25:
        color = "🟡"
    else:
        color = "🔴"
    return f"{color} `{bar}` **{current}/{max_hp}**"


# ── Simulação de combate ────────────────────────────────────────────────────────

def simulate_combat(char_a: dict, char_b: dict) -> dict:
    """
    Simula o combate completo entre dois personagens.
    Retorna dict com log de turnos, vencedor e estatísticas.
    """
    stats_a = char_a.get("stats", {})
    stats_b = char_b.get("stats", {})

    # HP = vida * 5 (range ~50–500)
    max_hp_a = stats_a.get("vida", 50) * 5
    max_hp_b = stats_b.get("vida", 50) * 5
    hp_a     = max_hp_a
    hp_b     = max_hp_b

    # Agilidade determina ordem (maior age primeiro por padrão)
    # Pequena variação aleatória para não ser determinístico
    speed_a = stats_a.get("agilidade", 50) + random.randint(-5, 5)
    speed_b = stats_b.get("agilidade", 50) + random.randint(-5, 5)
    first   = "a" if speed_a >= speed_b else "b"

    turns_log: list[dict] = []
    turn_count = 0

    while hp_a > 0 and hp_b > 0 and turn_count < MAX_TURNS:
        turn_count += 1
        turn_events: list[str] = []

        # Define ordem do turno
        order = [("a", "b"), ("b", "a")] if first == "a" else [("b", "a"), ("a", "b")]

        for attacker_key, defender_key in order:
            if hp_a <= 0 or hp_b <= 0:
                break

            if attacker_key == "a":
                atk_stats, def_stats = stats_a, stats_b
                atk_name, def_name   = char_a["name"], char_b["name"]
                atk_hp, def_hp       = hp_a, hp_b
            else:
                atk_stats, def_stats = stats_b, stats_a
                atk_name, def_name   = char_b["name"], char_a["name"]
                atk_hp, def_hp       = hp_b, hp_a

            forca     = atk_stats.get("forca", 50)
            intel     = atk_stats.get("inteligencia", 50)
            agi_atk   = atk_stats.get("agilidade", 50)
            agi_def   = def_stats.get("agilidade", 50)

            # ── Chance de desvio ──────────────────────────────────────────────
            agi_diff    = agi_def - agi_atk
            dodge_chance = max(0.02, min(0.25, agi_diff / 400))
            if random.random() < dodge_chance:
                ev = random.choice(DESVIO).format(a=atk_name, d=def_name)
                turn_events.append(ev)
                continue

            # ── Cálculo de dano base ──────────────────────────────────────────
            variation = random.uniform(0.80, 1.20)
            damage    = int(forca * variation)

            # ── Redução por agilidade do defensor ─────────────────────────────
            reduction = int(agi_def * 0.15)
            damage    = max(1, damage - reduction)

            # ── Bônus de Inteligência (especial) ─────────────────────────────
            intel_bonus  = 0
            special_used = False
            intel_chance = min(0.30, intel / 350)
            if random.random() < intel_chance:
                intel_bonus  = int(intel * random.uniform(0.30, 0.55))
                special_used = True
                ev = random.choice(ESPECIAL_INT).format(a=atk_name, d=def_name)
                turn_events.append(ev)

            # ── Crítico ───────────────────────────────────────────────────────
            crit_chance = min(0.20, forca / 600)
            is_crit     = random.random() < crit_chance
            if is_crit:
                damage = int(damage * 1.75)
                ev     = random.choice(ATAQUE_CRITICO).format(a=atk_name, d=def_name)
            else:
                ev = random.choice(ATAQUE_NORMAL).format(a=atk_name, d=def_name)
            turn_events.append(ev)

            total_dmg = damage + intel_bonus
            ev_dmg    = f"  ↳ `-{total_dmg} HP`"
            if intel_bonus:
                ev_dmg += f" *(+{intel_bonus} bônus INT)*"
            if is_crit:
                ev_dmg += " *(CRÍTICO!)*"
            turn_events.append(ev_dmg)

            # Aplica dano
            if attacker_key == "a":
                hp_b = max(0, hp_b - total_dmg)
            else:
                hp_a = max(0, hp_a - total_dmg)

        turns_log.append({
            "turn":    turn_count,
            "events":  turn_events,
            "hp_a":    hp_a,
            "hp_b":    hp_b,
            "max_a":   max_hp_a,
            "max_b":   max_hp_b,
        })

    # ── Resultado ──────────────────────────────────────────────────────────────
    if hp_a > 0 and hp_b <= 0:
        winner, loser = "a", "b"
    elif hp_b > 0 and hp_a <= 0:
        winner, loser = "b", "a"
    elif hp_a == hp_b:
        winner = loser = "draw"
    else:
        # Fim por turnos — ganha quem tem mais % de HP
        winner = "a" if (hp_a / max_hp_a) >= (hp_b / max_hp_b) else "b"
        loser  = "b" if winner == "a" else "a"

    prize = BASE_PRIZE + (turn_count * BONUS_PRIZE)

    return {
        "turns":     turns_log,
        "winner":    winner,
        "loser":     loser,
        "hp_a":      hp_a,
        "hp_b":      hp_b,
        "max_hp_a":  max_hp_a,
        "max_hp_b":  max_hp_b,
        "turn_count": turn_count,
        "prize":     prize,
    }


# ── Select de personagem ───────────────────────────────────────────────────────

class CharacterSelect(ui.Select):
    def __init__(self, equipe: list[dict], placeholder: str):
        options = []
        for i, char in enumerate(equipe[:25]):  # discord limita 25 opções
            stats     = char.get("stats", {})
            total_pow = sum(stats.values()) if stats else 0
            stars     = star_rating(stats) if stats else "⭐"
            options.append(discord.SelectOption(
                label=f"{char['name'][:50]}",
                description=f"{stars} {char['anime'][:40]} • ⚡{total_pow}",
                value=str(i),
                emoji="⚔️",
            ))
        super().__init__(placeholder=placeholder, options=options, min_values=1, max_values=1)
        self.equipe   = equipe
        self.selected = None

    async def callback(self, interaction: discord.Interaction):
        idx            = int(self.values[0])
        self.selected  = self.equipe[idx]
        self.disabled  = True
        await interaction.response.edit_message(
            content=f"✅ **{self.selected['name']}** selecionado! Aguardando o oponente...",
            view=self.view,
        )
        self.view.stop()


class SelectView(ui.View):
    def __init__(self, equipe: list[dict], placeholder: str, user_id: int):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.select  = CharacterSelect(equipe, placeholder)
        self.add_item(self.select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "❌ Este select não é para você!", ephemeral=True
            )
            return False
        return True

    @property
    def chosen(self) -> dict | None:
        return self.select.selected


# ── Challenge View ─────────────────────────────────────────────────────────────

class ChallengeView(ui.View):
    def __init__(self, challenger: discord.Member, opponent: discord.Member):
        super().__init__(timeout=60)
        self.challenger = challenger
        self.opponent   = opponent
        self.accepted   = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.opponent.id:
            await interaction.response.send_message(
                "❌ Apenas o desafiado pode aceitar/recusar!", ephemeral=True
            )
            return False
        return True

    @ui.button(label="⚔️  Aceitar", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: ui.Button):
        self.accepted = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f"✅ **{self.opponent.display_name}** aceitou o desafio! Preparando o combate...",
            view=self,
        )
        self.stop()

    @ui.button(label="🏳️  Recusar", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f"❌ **{self.opponent.display_name}** recusou o desafio.",
            view=self,
        )
        self.stop()


# ── Cog ────────────────────────────────────────────────────────────────────────

class Combat(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── $batalha @oponente ─────────────────────────────────────────────────────

    @commands.command(name="batalha", aliases=["battle", "luta", "fight", "bt"])
    @commands.cooldown(1, 30, commands.BucketType.user)
    async def batalha(self, ctx: commands.Context, opponent: discord.Member):
        """Desafia outro usuário para um combate entre personagens."""

        challenger = ctx.author

        # Validações básicas
        if opponent.bot:
            await ctx.send("❌ Você não pode desafiar um bot!")
            return
        if opponent.id == challenger.id:
            await ctx.send("❌ Você não pode se desafiar!")
            return

        ch_user = get_user(challenger.id)
        op_user = get_user(opponent.id)

        if not ch_user.get("Equipe"):
            await ctx.send(f"❌ **{challenger.display_name}**, sua Equipe está vazia! Use `$f` ou `$cu` para recrutar.")
            return
        if not op_user.get("Equipe"):
            await ctx.send(f"❌ **{opponent.display_name}** não tem personagens na Equipe ainda!")
            return

        # ── 1. Envio do desafio ─────────────────────────────────────────────

        embed_challenge = discord.Embed(
            title="⚔️ Desafio de Batalha!",
            description=(
                f"**{challenger.mention}** desafia **{opponent.mention}** para um combate!\n\n"
                f"Você tem **60 segundos** para aceitar ou recusar."
            ),
            color=0xFF6B00,
        )
        embed_challenge.set_footer(text="Apenas o desafiado pode responder.")

        challenge_view = ChallengeView(challenger, opponent)
        msg = await ctx.send(embed=embed_challenge, view=challenge_view)
        await challenge_view.wait()

        if not challenge_view.accepted:
            return

        # ── 2. Seleção de personagens ───────────────────────────────────────

        # Desafiante escolhe
        ch_select_view = SelectView(
            equipe=ch_user["Equipe"],
            placeholder="Escolha seu personagem...",
            user_id=challenger.id,
        )
        ch_msg = await ctx.send(
            content=f"⚔️ {challenger.mention}, **escolha seu personagem para a batalha!**",
            view=ch_select_view,
        )
        await ch_select_view.wait()

        if not ch_select_view.chosen:
            await ctx.send("⏰ Tempo esgotado! O desafiante não escolheu um personagem.")
            return

        # Oponente escolhe
        op_select_view = SelectView(
            equipe=op_user["Equipe"],
            placeholder="Escolha seu personagem...",
            user_id=opponent.id,
        )
        op_msg = await ctx.send(
            content=f"⚔️ {opponent.mention}, **escolha seu personagem para a batalha!**",
            view=op_select_view,
        )
        await op_select_view.wait()

        if not op_select_view.chosen:
            await ctx.send("⏰ Tempo esgotado! O oponente não escolheu um personagem.")
            return

        char_a = ch_select_view.chosen  # personagem do desafiante
        char_b = op_select_view.chosen  # personagem do oponente

        # ── 3. Anúncio do confronto ─────────────────────────────────────────

        stats_a   = char_a.get("stats", {})
        stats_b   = char_b.get("stats", {})
        stars_a   = star_rating(stats_a) if stats_a else "⭐"
        stars_b   = star_rating(stats_b) if stats_b else "⭐"
        total_a   = sum(stats_a.values()) if stats_a else 0
        total_b   = sum(stats_b.values()) if stats_b else 0

        embed_vs = discord.Embed(
            title="⚔️ BATALHA INICIADA!",
            description=(
                f"**{challenger.display_name}** usa **{char_a['name']}** {stars_a}\n"
                f"*{char_a['anime']}* — ⚡ Poder: `{total_a}`\n\n"
                f"**VS**\n\n"
                f"**{opponent.display_name}** usa **{char_b['name']}** {stars_b}\n"
                f"*{char_b['anime']}* — ⚡ Poder: `{total_b}`"
            ),
            color=0xFF6B00,
        )
        if char_a.get("image_url"):
            embed_vs.set_thumbnail(url=char_a["image_url"])
        if char_b.get("image_url"):
            embed_vs.set_image(url=char_b["image_url"])

        await ctx.send(embed=embed_vs)
        await asyncio.sleep(2)

        # ── 4. Simulação e exibição por turnos ──────────────────────────────

        result = simulate_combat(char_a, char_b)

        for turn_data in result["turns"]:
            t       = turn_data["turn"]
            hp_a    = turn_data["hp_a"]
            hp_b    = turn_data["hp_b"]
            max_a   = turn_data["max_a"]
            max_b   = turn_data["max_b"]
            events  = turn_data["events"]

            bar_a = hp_bar(hp_a, max_a)
            bar_b = hp_bar(hp_b, max_b)

            embed_turn = discord.Embed(
                title=f"⚔️ Turno {t}/{result['turn_count']}",
                description="\n".join(events),
                color=0x2C3E50,
            )
            embed_turn.add_field(
                name=f"**{char_a['name']}** ({challenger.display_name})",
                value=bar_a,
                inline=False,
            )
            embed_turn.add_field(
                name=f"**{char_b['name']}** ({opponent.display_name})",
                value=bar_b,
                inline=False,
            )
            await ctx.send(embed=embed_turn)
            await asyncio.sleep(1.8)

        # ── 5. Resultado final ──────────────────────────────────────────────

        winner_key = result["winner"]
        prize      = result["prize"]

        if winner_key == "draw":
            embed_result = discord.Embed(
                title="🤝 EMPATE!",
                description=random.choice(EMPATE),
                color=0x95A5A6,
            )
            embed_result.set_footer(text="Nenhum Cols foi distribuído neste combate.")
            await ctx.send(embed=embed_result)
            return

        if winner_key == "a":
            winner_member = challenger
            loser_member  = opponent
            winner_char   = char_a
            loser_char    = char_b
            winner_id     = challenger.id
            loser_id      = opponent.id
        else:
            winner_member = opponent
            loser_member  = challenger
            winner_char   = char_b
            loser_char    = char_a
            winner_id     = opponent.id
            loser_id      = challenger.id

        # Registra no banco
        record_combat_result(winner_id, loser_id, prize)

        winner_user_data = get_user(winner_id)
        new_cols         = winner_user_data.get("Cols", 0)
        combates         = winner_user_data.get("combates", {})
        vitorias         = combates.get("vitorias", 0)

        embed_result = discord.Embed(
            title=f"🏆 {random.choice(VITORIA).format(w=winner_char['name'])}",
            description=(
                f"**{winner_member.mention}** venceu com **{winner_char['name']}**!\n"
                f"**{loser_member.mention}** foi derrotado com **{loser_char['name']}**.\n\n"
                f"💲 **+{prize} Cols** para {winner_member.display_name}! *(Total: {new_cols:,})*\n"
                f"🏆 Vitórias de {winner_member.display_name}: **{vitorias}**"
            ),
            color=0xFFD700,
        )
        if winner_char.get("image_url"):
            embed_result.set_thumbnail(url=winner_char["image_url"])
        embed_result.set_footer(text=f"Combate durou {result['turn_count']} turnos • $batalha para jogar novamente")
        await ctx.send(embed=embed_result)

    # ── $ranking ───────────────────────────────────────────────────────────────

    @commands.command(name="ranking", aliases=["rank", "top"])
    async def ranking(self, ctx: commands.Context):
        """Exibe o ranking de vitórias em combate do servidor."""
        import json
        from pathlib import Path
        db_path = Path("data/db.json")
        if not db_path.exists():
            await ctx.send("❌ Nenhum combate registrado ainda!")
            return

        with open(db_path, "r", encoding="utf-8") as f:
            db = json.load(f)

        users_data = db.get("users", {})
        ranked = []
        for uid, udata in users_data.items():
            combates = udata.get("combates", {})
            vitorias = combates.get("vitorias", 0)
            if vitorias > 0:
                member = ctx.guild.get_member(int(uid))
                name   = member.display_name if member else f"Usuário {uid}"
                ranked.append((name, vitorias, combates.get("derrotas", 0), udata.get("Cols", 0)))

        if not ranked:
            await ctx.send("❌ Nenhum combate registrado ainda! Use `$batalha @alguém`.")
            return

        ranked.sort(key=lambda x: x[1], reverse=True)
        medals = ["🥇", "🥈", "🥉"]

        embed = discord.Embed(
            title="🏆 Ranking de Batalhas",
            color=0xFFD700,
        )
        lines = []
        for i, (name, wins, losses, cols) in enumerate(ranked[:10]):
            medal = medals[i] if i < 3 else f"`{i+1}.`"
            wr    = round(wins / max(1, wins + losses) * 100)
            lines.append(
                f"{medal} **{name}** — {wins}V / {losses}D *(WR: {wr}%)* — {COL_EMOJI}{cols:,}"
            )
        embed.description = "\n".join(lines)
        embed.set_footer(text="Use $batalha @alguém para jogar!")
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Combat(bot))

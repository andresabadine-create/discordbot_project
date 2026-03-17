"""
cogs/suggestions.py — Sistema de sugestões de animes + agendador automático.

Fluxo:
  Usuário → $sugerir <nome do anime>
         → Bot busca na API e mostra prévia
         → Usuário confirma com botão
         → Sugestão entra na fila com votos
         → Admin aprova ($aprovar) ou rejeita ($rejeitar)
         → Cache é atualizado com os novos personagens

Agendador automático:
  → A cada 6h, popula silenciosamente 3 animes aleatórios do pool
  → A cada 24h, roda $updategender em 100 personagens Unknown
"""

import discord
from discord.ext import commands
from discord import ui
import aiohttp
import asyncio
import json
from pathlib import Path
from datetime import datetime, timedelta

from character_api import populate_cache, cache_size, update_genders, gender_stats, _calc_cols, fetch_top_characters
from stats_engine import generate_stats

# ── Arquivo de sugestões ───────────────────────────────────────────────────────

SUGGESTIONS_FILE = Path("data/suggestions.json")
JIKAN_BASE       = "https://api.jikan.moe/v4"

COL_EMOJI = "💲"

# ── Helpers de persistência ────────────────────────────────────────────────────

def _load_suggestions() -> dict:
    SUGGESTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not SUGGESTIONS_FILE.exists():
        SUGGESTIONS_FILE.write_text(json.dumps({
            "pending":  [],   # aguardando aprovação admin
            "approved": [],   # aprovadas e já processadas
            "rejected": [],   # rejeitadas
        }, indent=2))
    with open(SUGGESTIONS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_suggestions(data: dict) -> None:
    with open(SUGGESTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _find_pending(suggestion_id: int) -> dict | None:
    db = _load_suggestions()
    return next((s for s in db["pending"] if s["id"] == suggestion_id), None)


# ── Busca anime na API ─────────────────────────────────────────────────────────

async def search_anime(query: str) -> list[dict]:
    """Busca animes pelo nome na Jikan API. Retorna até 5 resultados."""
    url = f"{JIKAN_BASE}/anime?q={query}&limit=5&type=tv,movie,ova"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return []
                data    = await resp.json()
                results = []
                for entry in data.get("data", []):
                    titles = entry.get("titles", [])
                    title  = entry.get("title", "???")
                    for t in titles:
                        if t.get("type") == "English" and t.get("title"):
                            title = t["title"]
                            break
                    results.append({
                        "mal_id":   entry["mal_id"],
                        "title":    title,
                        "score":    entry.get("score") or 0,
                        "members":  entry.get("members", 0),
                        "episodes": entry.get("episodes") or "?",
                        "year":     entry.get("year") or "?",
                        "image":    entry.get("images", {}).get("jpg", {}).get("image_url", ""),
                        "genres":   [g["name"] for g in entry.get("genres", [])],
                        "synopsis": (entry.get("synopsis") or "")[:200],
                    })
                return results
    except Exception:
        return []


# ── View de confirmação da sugestão ───────────────────────────────────────────

class ConfirmSuggestionView(ui.View):
    def __init__(self, anime: dict, suggester: discord.Member, log_channel_id: int | None):
        super().__init__(timeout=60)
        self.anime           = anime
        self.suggester       = suggester
        self.log_channel_id  = log_channel_id
        self.confirmed       = False

    @ui.button(label="✅  Confirmar sugestão", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.suggester.id:
            await interaction.response.send_message(
                "❌ Apenas quem fez a sugestão pode confirmar!", ephemeral=True
            )
            return

        db   = _load_suggestions()
        # Verifica se já foi sugerido
        all_ids = [s["mal_id"] for s in db["pending"] + db["approved"] + db["rejected"]]
        if self.anime["mal_id"] in all_ids:
            await interaction.response.send_message(
                "⚠️ Este anime já foi sugerido anteriormente!", ephemeral=True
            )
            self.stop()
            return

        # ID sequencial
        all_suggestions = db["pending"] + db["approved"] + db["rejected"]
        new_id = (max((s["id"] for s in all_suggestions), default=0) + 1)

        suggestion = {
            "id":           new_id,
            "mal_id":       self.anime["mal_id"],
            "title":        self.anime["title"],
            "genres":       self.anime["genres"],
            "image":        self.anime["image"],
            "score":        self.anime["score"],
            "members":      self.anime["members"],
            "suggester_id": self.suggester.id,
            "suggester":    self.suggester.display_name,
            "votes":        [self.suggester.id],   # suggester já vota automaticamente
            "created_at":   datetime.utcnow().isoformat(),
            "status":       "pending",
        }
        db["pending"].append(suggestion)
        _save_suggestions(db)

        self.confirmed = True
        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(
            embed=discord.Embed(
                title="✅ Sugestão enviada!",
                description=(
                    f"**{self.anime['title']}** foi adicionado à fila de sugestões.\n"
                    f"ID da sugestão: `#{new_id}`\n\n"
                    f"Um admin irá analisar em breve. Use `$votar {new_id}` para apoiar!"
                ),
                color=0x2ECC71,
            ),
            view=self,
        )

        # Notifica canal de log se configurado
        if self.log_channel_id:
            ch = interaction.guild.get_channel(self.log_channel_id)
            if ch:
                embed_log = _build_suggestion_embed(suggestion, color=0xFFA500)
                await ch.send(
                    content="📬 **Nova sugestão de anime!**",
                    embed=embed_log,
                )
        self.stop()

    @ui.button(label="❌  Cancelar", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.suggester.id:
            await interaction.response.send_message("❌ Não é sua sugestão!", ephemeral=True)
            return
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="❌ Sugestão cancelada.", embed=None, view=self
        )
        self.stop()


# ── Embed de sugestão ──────────────────────────────────────────────────────────

def _build_suggestion_embed(suggestion: dict, color: int = 0xFFA500) -> discord.Embed:
    genres = ", ".join(suggestion.get("genres", [])[:4]) or "—"
    votes  = len(suggestion.get("votes", []))
    embed  = discord.Embed(
        title=f"🎌 #{suggestion['id']} — {suggestion['title']}",
        description=f"🎭 `{genres}`",
        color=color,
    )
    embed.add_field(name="⭐ Nota MAL",     value=f"**{suggestion['score']}**",              inline=True)
    embed.add_field(name="👥 Membros",      value=f"**{suggestion['members']:,}**",           inline=True)
    embed.add_field(name="👍 Votos",        value=f"**{votes}**",                             inline=True)
    embed.add_field(name="👤 Sugerido por", value=suggestion["suggester"],                    inline=True)
    embed.add_field(name="📅 Data",
                    value=suggestion["created_at"][:10],                                      inline=True)
    if suggestion.get("image"):
        embed.set_thumbnail(url=suggestion["image"])
    return embed


# ── Agendador automático ───────────────────────────────────────────────────────

class AutoUpdater:
    """Executa tarefas periódicas de atualização do cache."""

    def __init__(self, bot: commands.Bot):
        self.bot         = bot
        self._cache_task = None
        self._gender_task = None

    def start(self):
        self._cache_task    = self.bot.loop.create_task(self._auto_cache_loop())
        self._gender_task   = self.bot.loop.create_task(self._auto_gender_loop())
        self._topchar_task  = self.bot.loop.create_task(self._auto_top_chars_loop())

    def stop(self):
        if self._cache_task:   self._cache_task.cancel()
        if self._gender_task:  self._gender_task.cancel()
        if self._topchar_task: self._topchar_task.cancel()

    async def _auto_cache_loop(self):
        """A cada 6h, adiciona 3 animes aleatórios ao cache."""
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            await asyncio.sleep(6 * 3600)  # espera 6 horas
            try:
                before = cache_size()
                added  = await populate_cache(max_animes=3)
                after  = cache_size()
                print(f"[AutoUpdater] Cache: +{added} personagens novos ({before}→{after})")
            except Exception as e:
                print(f"[AutoUpdater] Erro no cache: {e}")

    async def _auto_gender_loop(self):
        """A cada 24h, preenche gênero de até 100 personagens Unknown."""
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            await asyncio.sleep(24 * 3600)
            try:
                updated = await update_genders(limit=100)
                stats   = gender_stats()
                print(
                    f"[AutoUpdater] Gênero: +{updated} identificados | "
                    f"♀{stats['Female']} ♂{stats['Male']} ❓{stats['Unknown']}"
                )
            except Exception as e:
                print(f"[AutoUpdater] Erro no gender: {e}")

    async def _auto_top_chars_loop(self):
        """A cada 7 dias, busca as 3 primeiras páginas do ranking de favoritos MAL."""
        await self.bot.wait_until_ready()
        await asyncio.sleep(30)  # aguarda inicialização completa
        while not self.bot.is_closed():
            try:
                added = await fetch_top_characters(pages=3)
                print(f"[AutoUpdater] Top chars: +{added} novos personagens do ranking MAL")
            except Exception as e:
                print(f"[AutoUpdater] Erro top chars: {e}")
            await asyncio.sleep(7 * 24 * 3600)  # repete a cada 7 dias


# ── Cog principal ──────────────────────────────────────────────────────────────

class Suggestions(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot           = bot
        self.log_channel   = None   # ID do canal de log (configurável)
        self.auto_updater  = AutoUpdater(bot)
        bot.loop.create_task(self._start_auto_updater())

    async def _start_auto_updater(self):
        await self.bot.wait_until_ready()
        self.auto_updater.start()
        print("  ✔ AutoUpdater iniciado (cache: 6h | gênero: 24h)")

    # ── $sugerir <nome> ────────────────────────────────────────────────────────

    @commands.command(name="sugerir", aliases=["suggest", "addanime"])
    @commands.cooldown(1, 60, commands.BucketType.user)
    async def suggest_anime(self, ctx: commands.Context, *, query: str):
        """Sugere um anime para adicionar ao banco de personagens."""
        async with ctx.typing():
            results = await search_anime(query)

        if not results:
            await ctx.send(embed=discord.Embed(
                description=f"❌ Nenhum anime encontrado para **{query}**.",
                color=0xFF0000,
            ))
            return

        # Usa o primeiro resultado (mais relevante)
        anime = results[0]

        embed = discord.Embed(
            title=f"🎌 Você quer sugerir este anime?",
            description=(
                f"**{anime['title']}**\n"
                f"🎭 `{', '.join(anime['genres'][:4]) or '—'}`\n"
                f"⭐ Nota: **{anime['score']}** | 👥 Membros: **{anime['members']:,}**\n"
                f"📺 Episódios: **{anime['episodes']}** | 📅 Ano: **{anime['year']}**\n\n"
                f"_{anime['synopsis']}..._"
            ),
            color=0xFFA500,
        )
        if anime["image"]:
            embed.set_thumbnail(url=anime["image"])
        embed.set_footer(text="Confirme abaixo para enviar a sugestão para análise.")

        view = ConfirmSuggestionView(anime, ctx.author, self.log_channel)
        msg  = await ctx.send(embed=embed, view=view)
        await view.wait()

    # ── $sugestoes ─────────────────────────────────────────────────────────────

    @commands.command(name="sugestoes", aliases=["suggestions", "fila"])
    async def list_suggestions(self, ctx: commands.Context):
        """Lista as sugestões pendentes de aprovação."""
        db      = _load_suggestions()
        pending = db["pending"]

        if not pending:
            await ctx.send(embed=discord.Embed(
                description="📭 Nenhuma sugestão pendente no momento!\nUse `$sugerir <anime>` para sugerir.",
                color=0x95A5A6,
            ))
            return

        embed = discord.Embed(
            title=f"📋 Sugestões Pendentes ({len(pending)})",
            description="Use `$votar <ID>` para apoiar uma sugestão!",
            color=0xFFA500,
        )
        for s in pending[:10]:
            votes  = len(s.get("votes", []))
            genres = ", ".join(s.get("genres", [])[:2]) or "—"
            embed.add_field(
                name=f"#{s['id']} — {s['title']}",
                value=f"👍 **{votes} votos** | 🎭 {genres} | 👤 {s['suggester']}",
                inline=False,
            )
        if len(pending) > 10:
            embed.set_footer(text=f"Mostrando 10 de {len(pending)} sugestões.")
        await ctx.send(embed=embed)

    # ── $votar <id> ────────────────────────────────────────────────────────────

    @commands.command(name="votar", aliases=["vote", "apoiar"])
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def vote_suggestion(self, ctx: commands.Context, suggestion_id: int):
        """Vota em uma sugestão pendente pelo ID."""
        db         = _load_suggestions()
        suggestion = next((s for s in db["pending"] if s["id"] == suggestion_id), None)

        if not suggestion:
            await ctx.send(embed=discord.Embed(
                description=f"❌ Sugestão `#{suggestion_id}` não encontrada ou já foi processada.",
                color=0xFF0000,
            ))
            return

        if ctx.author.id in suggestion["votes"]:
            await ctx.send(embed=discord.Embed(
                description=f"❌ Você já votou na sugestão `#{suggestion_id}`!",
                color=0xFF6B6B,
            ), delete_after=5)
            return

        suggestion["votes"].append(ctx.author.id)
        _save_suggestions(db)

        votes = len(suggestion["votes"])
        embed = discord.Embed(
            title=f"👍 Voto registrado!",
            description=(
                f"**{suggestion['title']}** agora tem **{votes} voto(s)**!\n"
                f"Com 10+ votos, admins são incentivados a aprovar mais rapidamente."
            ),
            color=0x2ECC71,
        )
        await ctx.send(embed=embed)

    # ── $aprovar <id> [admin] ──────────────────────────────────────────────────

    @commands.command(name="aprovar", aliases=["approve"])
    @commands.has_permissions(administrator=True)
    async def approve_suggestion(self, ctx: commands.Context, suggestion_id: int):
        """[Admin] Aprova uma sugestão e carrega os personagens no cache."""
        db         = _load_suggestions()
        idx        = next((i for i, s in enumerate(db["pending"]) if s["id"] == suggestion_id), None)

        if idx is None:
            await ctx.send(f"❌ Sugestão `#{suggestion_id}` não encontrada na fila.")
            return

        suggestion = db["pending"].pop(idx)
        suggestion["status"]      = "approved"
        suggestion["approved_by"] = ctx.author.display_name
        suggestion["approved_at"] = datetime.utcnow().isoformat()
        db["approved"].append(suggestion)
        _save_suggestions(db)

        msg = await ctx.send(
            f"✅ Sugestão `#{suggestion_id}` aprovada! Carregando **{suggestion['title']}**..."
        )

        # Injeta o anime_id na lista e popula
        from character_api import POPULAR_ANIME_IDS, _load_cache, _save_cache, _fetch_characters_from_anime
        import aiohttp as _aiohttp

        before = cache_size()
        new_chars = []
        existing_ids = {c["mal_id"] for c in _load_cache()}

        async with _aiohttp.ClientSession() as session:
            chars = await _fetch_characters_from_anime(session, suggestion["mal_id"])
            for c in chars:
                if c["mal_id"] not in existing_ids:
                    new_chars.append(c)
                    existing_ids.add(c["mal_id"])

        if new_chars:
            all_chars = _load_cache() + new_chars
            _save_cache(all_chars)

        added = len(new_chars)
        after = cache_size()

        # Notifica quem sugeriu
        suggester = ctx.guild.get_member(suggestion["suggester_id"])
        if suggester:
            try:
                await suggester.send(
                    embed=discord.Embed(
                        title="🎉 Sua sugestão foi aprovada!",
                        description=(
                            f"**{suggestion['title']}** foi adicionado ao bot com **{added}** novos personagens!\n"
                            f"Obrigado por contribuir! 🙌"
                        ),
                        color=0x2ECC71,
                    )
                )
            except Exception:
                pass  # DM desativada

        await msg.edit(content=(
            f"✅ **{suggestion['title']}** aprovado e carregado!\n"
            f"**+{added}** novos personagens adicionados. Cache: **{before} → {after}**"
        ))

    # ── $rejeitar <id> [reason] [admin] ───────────────────────────────────────

    @commands.command(name="rejeitar", aliases=["reject", "deny"])
    @commands.has_permissions(administrator=True)
    async def reject_suggestion(self, ctx: commands.Context, suggestion_id: int, *, reason: str = "Sem motivo informado."):
        """[Admin] Rejeita uma sugestão da fila."""
        db  = _load_suggestions()
        idx = next((i for i, s in enumerate(db["pending"]) if s["id"] == suggestion_id), None)

        if idx is None:
            await ctx.send(f"❌ Sugestão `#{suggestion_id}` não encontrada.")
            return

        suggestion = db["pending"].pop(idx)
        suggestion["status"]      = "rejected"
        suggestion["rejected_by"] = ctx.author.display_name
        suggestion["rejected_at"] = datetime.utcnow().isoformat()
        suggestion["reason"]      = reason
        db["rejected"].append(suggestion)
        _save_suggestions(db)

        # Notifica quem sugeriu
        suggester = ctx.guild.get_member(suggestion["suggester_id"])
        if suggester:
            try:
                await suggester.send(
                    embed=discord.Embed(
                        title="❌ Sua sugestão foi recusada",
                        description=(
                            f"**{suggestion['title']}** não foi aprovado.\n"
                            f"**Motivo:** {reason}"
                        ),
                        color=0xFF0000,
                    )
                )
            except Exception:
                pass

        await ctx.send(
            f"🗑️ Sugestão `#{suggestion_id}` (**{suggestion['title']}**) rejeitada.\n"
            f"**Motivo:** {reason}"
        )

    # ── $sugestao <id> ─────────────────────────────────────────────────────────

    @commands.command(name="sugestao", aliases=["suggestion"])
    async def view_suggestion(self, ctx: commands.Context, suggestion_id: int):
        """Vê detalhes de uma sugestão específica."""
        db = _load_suggestions()
        all_s = db["pending"] + db["approved"] + db["rejected"]
        suggestion = next((s for s in all_s if s["id"] == suggestion_id), None)

        if not suggestion:
            await ctx.send(f"❌ Sugestão `#{suggestion_id}` não encontrada.")
            return

        colors  = {"pending": 0xFFA500, "approved": 0x2ECC71, "rejected": 0xFF0000}
        status  = {"pending": "⏳ Pendente", "approved": "✅ Aprovada", "rejected": "❌ Rejeitada"}
        color   = colors.get(suggestion["status"], 0x95A5A6)
        embed   = _build_suggestion_embed(suggestion, color=color)
        embed.add_field(name="📌 Status", value=status.get(suggestion["status"], "?"), inline=True)

        if suggestion["status"] == "rejected" and suggestion.get("reason"):
            embed.add_field(name="💬 Motivo da rejeição", value=suggestion["reason"], inline=False)
        if suggestion["status"] == "approved":
            embed.add_field(name="✅ Aprovado por", value=suggestion.get("approved_by", "?"), inline=True)

        await ctx.send(embed=embed)

    # ── $setlogchannel [admin] ─────────────────────────────────────────────────

    @commands.command(name="setlogchannel", aliases=["logcanal"])
    @commands.has_permissions(administrator=True)
    async def set_log_channel(self, ctx: commands.Context, channel: discord.TextChannel | None = None):
        """[Admin] Define o canal onde novas sugestões são notificadas."""
        self.log_channel = channel.id if channel else None
        if channel:
            await ctx.send(f"✅ Canal de log definido para {channel.mention}.")
        else:
            await ctx.send("✅ Canal de log removido.")

    # ── $autostatus [admin] ────────────────────────────────────────────────────

    @commands.command(name="autostatus")
    @commands.has_permissions(administrator=True)
    async def auto_status(self, ctx: commands.Context):
        """[Admin] Mostra o status do agendador automático e cache."""
        stats   = gender_stats()
        total   = cache_size()
        db      = _load_suggestions()
        pending = len(db["pending"])
        approved = len(db["approved"])

        embed = discord.Embed(
            title="🤖 Status do Bot",
            color=0x9B59B6,
        )
        embed.add_field(name="📦 Cache total",       value=f"**{total}** personagens",           inline=True)
        embed.add_field(name="♀️ Femininos",          value=f"**{stats['Female']}**",              inline=True)
        embed.add_field(name="♂️ Masculinos",         value=f"**{stats['Male']}**",                inline=True)
        embed.add_field(name="❓ Gênero desconhecido",value=f"**{stats['Unknown']}**",             inline=True)
        embed.add_field(name="📋 Sugestões pendentes",value=f"**{pending}**",                      inline=True)
        embed.add_field(name="✅ Sugestões aprovadas",value=f"**{approved}**",                     inline=True)
        embed.add_field(
            name="⏰ Agendador automático",
            value=(
                "🔄 Cache: **a cada 6h** (+3 animes)\n"
                "🔄 Gênero: **a cada 24h** (+100 personagens)"
            ),
            inline=False,
        )
        embed.set_footer(text="Use $sugestoes para ver a fila | $updategender para forçar update de gênero")
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Suggestions(bot))

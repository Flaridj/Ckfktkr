import discord
from discord.ext import commands
import random
import string
import asyncio
from datetime import datetime
from dotenv import load_dotenv
import os

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

load_dotenv() 

bot = commands.Bot(command_prefix="&", intents=intents)

RED = 0xFF0000
FOOTER_TEXT = "Loup Garou By Nyr"
FOOTER_ICON = None
EMBED_IMAGE_URL = "https://cdn.discordapp.com/attachments/1381995165794701323/1382005101576847451/IMG_0675.webp?ex=6849940c&is=6848428c&hm=08fd1472afc209aca86d38035ec06d12939c5717a6ee09c012ee76a3a658d4ab"

OWNER_ID = 1254402109563076722

ROLES_BASE = [
    "Loup-garou", "Loup-garou",  # 2 loups
    "Voyante",
    "Sorcière",
    "Chasseur",
    "Villageois"
]

games = {}  # channel_id -> Game


def generate_code(length=6):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))


class Player:
    def __init__(self, member):
        self.member = member
        self.role = None
        self.ready = False
        self.alive = True
        self.vote = None


class Game:
    def __init__(self, channel, creator):
        self.channel = channel
        self.creator = creator  # stocke l'auteur de &create
        self.code = generate_code()
        self.players = []
        self.started = False
        self.phase = "waiting"  # waiting, night, day, ended
        self.night_actions = {}

    def assign_roles(self):
        n = len(self.players)
        roles = ROLES_BASE.copy()
        if n > len(roles):
            roles += ["Villageois"] * (n - len(roles))
        else:
            roles = roles[:n]
        random.shuffle(roles)
        for i, player in enumerate(self.players):
            player.role = roles[i]

    def all_ready(self):
        return all(p.ready for p in self.players if p.alive)


async def send_embed(channel, title="", description="", color=RED):
    embed = discord.Embed(title=title, description=description, color=color)
    embed.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
    embed.set_image(url=EMBED_IMAGE_URL)
    await channel.send(embed=embed)


@bot.command()
async def create(ctx):
    if ctx.channel.id in games and games[ctx.channel.id].phase != "ended":
        await send_embed(ctx.channel, title="Erreur", description="Une partie est déjà en cours dans ce salon.")
        return
    game = Game(ctx.channel, ctx.author)
    games[ctx.channel.id] = game
    await send_embed(ctx.channel,
                     title="Nouvelle partie créée",
                     description=f"Code de la partie : `{game.code}`\nPour rejoindre, faites `&join {game.code}`.\n"
                                 f"Seul {ctx.author.name} peut lancer la partie avec `&start`.")


@bot.command()
async def join(ctx, code: str):
    game = next((g for g in games.values() if g.code == code and not g.started), None)
    if not game:
        await send_embed(ctx.channel, title="Erreur", description="Partie introuvable ou déjà démarrée.")
        return
    if any(p.member.id == ctx.author.id for p in game.players):
        await send_embed(ctx.channel, title="Erreur", description="Vous êtes déjà inscrit dans cette partie.")
        return
    game.players.append(Player(ctx.author))
    await send_embed(ctx.channel,
                     title="Nouveau joueur",
                     description=f"{ctx.author.name} a rejoint la partie ! ({len(game.players)} joueurs)")


@bot.command()
async def start(ctx):
    game = games.get(ctx.channel.id)
    if not game:
        await send_embed(ctx.channel, title="Erreur", description="Aucune partie créée dans ce salon.")
        return

    if ctx.author.id != game.creator.id:
        await send_embed(ctx.channel, title="Erreur", description="Seul le créateur de la partie peut la lancer.")
        return

    if game.started:
        await send_embed(ctx.channel, title="Erreur", description="La partie a déjà démarré.")
        return

    if len(game.players) < 2:
        await send_embed(ctx.channel, title="Erreur", description="Il faut au moins 2 joueurs pour commencer.")
        return

    game.started = True
    game.assign_roles()

    embed = discord.Embed(
        title="La partie démarre !",
        description="Cliquez sur le bouton ci-dessous pour voir votre rôle.",
        color=RED
    )
    embed.set_footer(text=FOOTER_TEXT)
    embed.set_image(url=EMBED_IMAGE_URL)
    await ctx.channel.send(embed=embed)

    for p in game.players:
        embed_player = discord.Embed(
            title="Révélation du rôle",
            description=f"{p.member.name}, cliquez sur le bouton ci-dessous pour découvrir votre rôle.",
            color=RED
        )
        embed_player.set_footer(text=FOOTER_TEXT)
        embed_player.set_image(url=EMBED_IMAGE_URL)
        await ctx.channel.send(embed=embed_player, view=RoleRevealButton(p, game))


@bot.event
async def on_ready():
    print(f"Bot connecté comme {bot.user}")


class RoleRevealButton(discord.ui.View):
    def __init__(self, player: Player, game: Game):
        super().__init__(timeout=None)
        self.player = player
        self.game = game

    @discord.ui.button(label="Voir mon rôle", style=discord.ButtonStyle.blurple)
    async def reveal(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.player.member.id:
            await interaction.response.send_message("Ce bouton n'est pas pour vous.", ephemeral=True)
            return
        embed = discord.Embed(
            title="Votre rôle",
            description=f"Vous êtes **{self.player.role}**.",
            color=RED
        )
        embed.set_footer(text=FOOTER_TEXT)
        embed.set_image(url=EMBED_IMAGE_URL)
        self.player.ready = True
        await interaction.response.send_message(embed=embed, ephemeral=True)

        if self.game.all_ready():
            await send_embed(self.game.channel,
                             title="Tous les joueurs sont prêts ! La nuit tombe...")
            await start_night_phase(self.game)


async def start_night_phase(game: Game):
    game.phase = "night"
    game.night_actions = {}
    loups = [p for p in game.players if p.role == "Loup-garou" and p.alive]
    if not loups:
        await send_embed(game.channel,
                         title="Fin de partie",
                         description="Pas de loups-garous vivants, la partie est terminée.")
        game.phase = "ended"
        return
    await send_embed(game.channel,
                     title="Phase de nuit – Loups-garous",
                     description="Loups-garous, cliquez sur le bouton correspondant pour tuer un joueur.")

    view = KillView(game, loups)
    await game.channel.send(view=view)


class KillView(discord.ui.View):
    def __init__(self, game: Game, loups: list[Player]):
        super().__init__(timeout=None)
        self.game = game
        self.loups = loups
        self.killed = None
        targets = [p for p in game.players if p.alive and p.role != "Loup-garou"]
        for target in targets:
            self.add_item(KillButton(target, self))
        self.votes = {}

    async def check_votes(self):
        if len(self.votes) == len(self.loups):
            count = {}
            for tgt in self.votes.values():
                count[tgt] = count.get(tgt, 0) + 1
            max_votes = max(count.values())
            max_targets = [t for t, c in count.items() if c == max_votes]
            self.killed = random.choice(max_targets)
            self.game.night_actions["kill"] = self.killed
            self.killed.alive = False
            await send_embed(self.game.channel,
                             title="Fin de la nuit",
                             description=f"Les loups-garous ont tué {self.killed.member.name}.")
            await start_day_phase(self.game)
            self.stop()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        is_loup = any(l.member.id == interaction.user.id for l in self.loups)
        if not is_loup:
            await interaction.response.send_message("Vous n'êtes pas un loup-garou.", ephemeral=True)
        return is_loup

    async def on_timeout(self):
        await send_embed(self.game.channel,
                         title="Fin de la nuit",
                         description="Les loups n'ont pas voté à temps, personne n'a été tué.")
        await start_day_phase(self.game)


class KillButton(discord.ui.Button):
    def __init__(self, target: Player, view: KillView):
        super().__init__(label=target.member.name, style=discord.ButtonStyle.danger)
        self.target = target
        self.view_ref = view

    async def callback(self, interaction: discord.Interaction):
        self.view_ref.votes[interaction.user.id] = self.target
        await interaction.response.send_message(f"Vous avez voté pour tuer {self.target.member.name}.", ephemeral=True)
        await self.view_ref.check_votes()


async def start_day_phase(game: Game):
    game.phase = "day"
    alive = [p for p in game.players if p.alive]

    await send_embed(game.channel,
                     title="Phase de jour",
                     description="Votez pour éliminer un suspect en cliquant sur les boutons ci-dessous.")

    view = VoteView(game)
    for p in alive:
        view.add_item(VoteButton(p))

    await game.channel.send(view=view)


class VoteView(discord.ui.View):
    def __init__(self, game: Game):
        super().__init__(timeout=None)
        self.game = game
        self.votes = {}

    async def check_votes(self):
        alive = [p for p in self.game.players if p.alive]
        if len(self.votes) == len(alive):
            count = {}
            for tgt in self.votes.values():
                count[tgt] = count.get(tgt, 0) + 1
            max_votes = max(count.values())
            max_targets = [t for t, c in count.items() if c == max_votes]
            eliminated = random.choice(max_targets)
            eliminated.alive = False
            await send_embed(self.game.channel,
                             title="Fin du jour",
                             description=f"{eliminated.member.name} a été éliminé.")
            # Vérifier conditions de fin etc ici
            self.stop()

    async def on_timeout(self):
        await send_embed(self.game.channel,
                         title="Fin du jour",
                         description="Les joueurs n'ont pas voté à temps, personne n'a été éliminé.")
        self.stop()


class VoteButton(discord.ui.Button):
    def __init__(self, target: Player):
        super().__init__(label=target.member.name, style=discord.ButtonStyle.secondary)
        self.target = target

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        view.votes[interaction.user.id] = self.target
        await interaction.response.send_message(f"Vous avez voté pour {self.target.member.name}.", ephemeral=True)
        await view.check_votes()


bot.run(DISCORD_TOKEN)

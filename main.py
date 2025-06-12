import discord
from discord.ext import commands
import random
import string
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()  # charge le .env pour le token

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# Config de base
DEFAULT_COLOR = 0xFF0000
FOOTER_TEXT = "Loup Garou By Nyr"
EMBED_IMAGE_URL = "https://cdn.discordapp.com/attachments/1381995165794701323/1382005101576847451/IMG_0675.webp?ex=6849940c&is=6848428c&hm=08fd1472afc209aca86d38035ec06d12939c5717a6ee09c012ee76a3a658d4ab"
OWNER_ID = 1254402109563076722

bot = commands.Bot(command_prefix="&", intents=intents)

# Stockage partie / config / stats / blacklist
games = {}           # channel_id -> Game
user_stats = {}      # user_id -> {'win': int, 'loss': int}
blacklist = set()    # user_id blacklisté
bot_color = DEFAULT_COLOR  # configurable via setup

# --- Rôles étendus ---
ROLES_BASE = [
    "Loup-garou", "Loup-garou", "Loup-garou", # 3 loups
    "Voyante",
    "Sorcière",
    "Chasseur",
    "Cupidon",
    "Petite fille",
    "Ancien",
    "Villageois",
    "Villageois"
]

# === UTILITAIRES ===

def generate_code(length=6):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

def embed_with_footer(title="", description="", color=None):
    if color is None:
        color = bot_color
    embed = discord.Embed(title=title, description=description, color=color)
    embed.set_footer(text=FOOTER_TEXT)
    embed.set_image(url=EMBED_IMAGE_URL)
    return embed

async def send_embed(channel, title="", description="", color=None):
    embed = embed_with_footer(title=title, description=description, color=color)
    await channel.send(embed=embed)

def is_owner(ctx):
    return ctx.author.id == OWNER_ID

# === CLASSES DE BASE ===

class Player:
    def __init__(self, member):
        self.member = member
        self.role = None
        self.ready = False
        self.alive = True
        self.vote = None

class Game:
    def __init__(self, channel):
        self.channel = channel
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

# === COMMANDES BASIQUES ===

@bot.command()
async def create(ctx):
    if ctx.channel.id in games and games[ctx.channel.id].phase != "ended":
        await send_embed(ctx.channel, title="Erreur", description="Une partie est déjà en cours dans ce salon.")
        return
    game = Game(ctx.channel)
    games[ctx.channel.id] = game
    await send_embed(ctx.channel,
                     title="Nouvelle partie créée",
                     description=f"Code de la partie : `{game.code}`\nPour rejoindre, faites `&join {game.code}`.")

@bot.command()
async def join(ctx, code: str):
    if ctx.author.id in blacklist:
        await send_embed(ctx.channel, title="Erreur", description="Vous êtes blacklisté et ne pouvez pas rejoindre de partie.")
        return
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
    await try_start_game(game)

async def try_start_game(game: Game):
    owner_in_game = any(p.member.id == OWNER_ID for p in game.players)

    # Mode solo pour owner (1 joueur)
    if owner_in_game and len(game.players) == 1 and not game.started:
        game.started = True
        game.assign_roles()
        for p in game.players:
            embed = embed_with_footer(title="Révélation du rôle",
                                     description=f"{p.member.name}, cliquez sur le bouton ci-dessous pour découvrir votre rôle.")
            await game.channel.send(embed=embed, view=RoleRevealButton(p, game))
        return

    # Min 2 joueurs pour démarrer la partie normalement
    if len(game.players) >= 2 and not game.started:
        game.started = True
        game.assign_roles()
        embed = embed_with_footer(title="La partie démarre !",
                                 description="Cliquez sur le bouton ci-dessous pour voir votre rôle.")
        await game.channel.send(embed=embed)
        for p in game.players:
            embed_player = embed_with_footer(title="Révélation du rôle",
                                            description=f"{p.member.name}, cliquez sur le bouton ci-dessous pour découvrir votre rôle.")
            await game.channel.send(embed=embed_player, view=RoleRevealButton(p, game))


# === VUE POUR RÉVÉLER LE RÔLE ===

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
        embed = embed_with_footer(title="Votre rôle",
                                  description=f"Vous êtes **{self.player.role}**.")
        self.player.ready = True
        await interaction.response.send_message(embed=embed, ephemeral=True)

        # Dès que tous ont cliqué, on passe à la nuit
        if self.game.all_ready():
            await send_embed(self.game.channel,
                             title="Tous les joueurs sont prêts ! La nuit tombe...")
            await start_night_phase(self.game)

# === PHASES DU JEU ===

async def start_night_phase(game: Game):
    game.phase = "night"
    game.night_actions = {}
    loups = [p for p in game.players if p.role == "Loup-garou" and p.alive]
    if not loups:
        await send_embed(game.channel,
                         title="Fin de partie",
                         description="Pas de loups-garous vivants, la partie est terminée.")
        game.phase = "ended"
        await record_winloss(game, winner="villageois")
        return
    # Informer les loups
    await send_embed(game.channel,
                     title="Phase de nuit – Loups-garous",
                     description="Loups-garous, cliquez sur le bouton correspondant pour tuer un joueur.")
    # Vue de vote loups
    view = KillView(game, loups)
    await game.channel.send(view=view)

class KillView(discord.ui.View):
    def __init__(self, game: Game, loups: list[Player]):
        super().__init__(timeout=120)
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
        super().__init__(timeout=120)
        self.game = game
        self.votes = {}

    async def check_votes(self):
        alive = [p for p in self.game.players if p.alive]
        if len(self.votes) == len(alive):
            count = {}
            for target in self.votes.values():
                count[target] = count.get(target, 0) + 1
            max_votes = max(count.values())
            eliminated = [p for p, c in count.items() if c == max_votes]
            if len(eliminated) == 1:
                elim = eliminated[0]
                elim.alive = False
                await send_embed(self.game.channel,
                                 title="Élimination",
                                 description=f"{elim.member.name} a été éliminé par vote.")
            else:
                await send_embed(self.game.channel,
                                 title="Vote nul",
                                 description="Égalité aux votes, personne n'est éliminé.")
            await check_end_game(self.game)
            if self.game.phase != "ended":
                await start_night_phase(self.game)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        voter = next((p for p in self.game.players if p.member.id == interaction.user.id), None)
        if voter is None or not voter.alive:
            await interaction.response.send_message("Vous ne pouvez pas voter.", ephemeral=True)
            return False
        return True

class VoteButton(discord.ui.Button):
    def __init__(self, target: Player):
        super().__init__(label=target.member.name, style=discord.ButtonStyle.primary)
        self.target = target

    async def callback(self, interaction: discord.Interaction):
        view: VoteView = self.view
        voter = next((p for p in view.game.players if p.member.id == interaction.user.id), None)
        if voter is None or not voter.alive:
            await interaction.response.send_message("Vous ne pouvez pas voter.", ephemeral=True)
            return
        view.votes[voter] = self.target
        await interaction.response.send_message(f"Vous avez voté pour {self.target.member.name}.", ephemeral=True)
        await view.check_votes()

async def check_end_game(game: Game):
    loups = [p for p in game.players if p.role == "Loup-garou" and p.alive]
    villageois = [p for p in game.players if p.role != "Loup-garou" and p.alive]
    if len(loups) == 0:
        await send_embed(game.channel,
                         title="Victoire villageoise",
                         description="Les villageois ont gagné !")
        game.phase = "ended"
        await record_winloss(game, winner="villageois")
    elif len(loups) >= len(villageois):
        await send_embed(game.channel,
                         title="Victoire des loups-garous",
                         description="Les loups-garous ont gagné !")
        game.phase = "ended"
        await record_winloss(game, winner="loup")

async def record_winloss(game: Game, winner: str):
    for p in game.players:
        if p.member.id not in user_stats:
            user_stats[p.member.id] = {'win': 0, 'loss': 0}
        if winner == "loup":
            if p.role == "Loup-garou" and p.alive:
                user_stats[p.member.id]['win'] += 1
            else:
                user_stats[p.member.id]['loss'] += 1
        elif winner == "villageois":
            if p.role != "Loup-garou" and p.alive:
                user_stats[p.member.id]['win'] += 1
            else:
                user_stats[p.member.id]['loss'] += 1

# === COMMANDES OWNER ===

@bot.command()
async def wl(ctx, user: discord.Member):
    if not is_owner(ctx):
        await send_embed(ctx.channel, title="Erreur", description="Commande réservée à l'owner.")
        return
    stats = user_stats.get(user.id, {'win': 0, 'loss': 0})
    await send_embed(ctx.channel,
                     title=f"Stats de {user.name}",
                     description=f"Victoires : {stats['win']}\nDéfaites : {stats['loss']}")

@bot.command()
async def bl(ctx, user: discord.Member):
    if not is_owner(ctx):
        await send_embed(ctx.channel, title="Erreur", description="Commande réservée à l'owner.")
        return
    blacklist.add(user.id)
    await send_embed(ctx.channel, title="Blacklist", description=f"{user.name} a été blacklisté.")

# === SETUP COMMANDE AVEC MENU DÉROULANT ===

class SetupMenu(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Rouge", description="Couleur rouge pour les embeds", value="red"),
            discord.SelectOption(label="Bleu", description="Couleur bleu pour les embeds", value="blue"),
            discord.SelectOption(label="Vert", description="Couleur verte pour les embeds", value="green"),
            discord.SelectOption(label="Blanc", description="Couleur blanche pour les embeds", value="white"),
        ]
        super().__init__(placeholder="Choisissez une couleur pour les embeds", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        global bot_color
        choice = self.values[0]
        colors = {
            "red": 0xFF0000,
            "blue": 0x0000FF,
            "green": 0x00FF00,
            "white": 0xFFFFFF,
        }
        bot_color = colors.get(choice, DEFAULT_COLOR)
        await interaction.response.send_message(f"Couleur des embeds changée en {choice}.", ephemeral=True)

class SetupView(discord.ui.View):
    def __init__(self):
        super().__init__()
        self.add_item(SetupMenu())

@bot.command()
async def setup(ctx):
    if not is_owner(ctx):
        await send_embed(ctx.channel, title="Erreur", description="Commande réservée à l'owner.")
        return
    await ctx.send("Setup du bot : Choisissez la couleur des embeds", view=SetupView())

# === HELP SIMPLE ===

@bot.command()
async def help(ctx):
    description = (
        "**Commandes disponibles :**\n"
        "&create - Crée une nouvelle partie\n"
        "&join <code> - Rejoindre une partie\n"
        "&wl @user - Voir statistiques (owner uniquement)\n"
        "&bl @user - Blacklister un utilisateur (owner uniquement)\n"
        "&setup - Configurer la couleur des embeds (owner uniquement)\n"
    )
    await send_embed(ctx.channel, title="Aide", description=description)

# === RUN ===

bot.run(os.getenv("TOKEN"))

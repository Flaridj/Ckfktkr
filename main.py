import discord
from discord.ext import commands
import datetime
import asyncio
import os
from dotenv import load_dotenv
load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(command_prefix="&", intents=intents)

OWNER_ID = 1254402109563076722  # ta clé ne change pas
whitelist = {OWNER_ID, 550057085849567239}

missions = {}   # guild_id -> Mission
scores = {}     # guild_id -> {user_id: {"count":int,"total_time":float}}
mission_tasks = {}  # guild_id -> asyncio.Task

def convert_to_seconds(qty, unit):
    unit = unit.lower()
    if unit == "s":
        return qty
    if unit == "m":
        return qty * 60
    if unit == "h":
        return qty * 3600
    return None

class Mission:
    def __init__(self, guild, role, quota_vocal_s, quota_msg, temps_max_s,
                 role1, role2, channel, role_no_eligible1=None, role_no_eligible2=None):
        self.guild = guild
        self.role = role
        self.quota_vocal_s = quota_vocal_s
        self.quota_msg = quota_msg
        self.temps_max_s = temps_max_s
        self.role1 = role1
        self.role2 = role2
        self.channel = channel
        self.role_no_eligible1 = role_no_eligible1
        self.role_no_eligible2 = role_no_eligible2
        self.start_time = datetime.datetime.utcnow()
        self.finished_members = set()
        self.vocal_times = {}
        self.msg_counts = {}
        self.user_vocal_start = {}
        self.embed_message = None

    def time_left(self):
        elapsed = (datetime.datetime.utcnow() - self.start_time).total_seconds()
        return max(0, int(self.temps_max_s - elapsed))

    def has_ended(self):
        return self.time_left() <= 0

    def is_eligible(self, member):
        if self.role_no_eligible1 and self.role_no_eligible1 in member.roles:
            return False
        if self.role_no_eligible2 and self.role_no_eligible2 in member.roles:
            return False
        return True

async def start_mission_loop(guild_id):
    mission = missions[guild_id]
    channel = mission.channel

    while True:
        # update finish status for all members
        for member in mission.role.members:
            if mission.is_eligible(member):
                await check_finish(member, mission)

        # build embed
        time_left = mission.time_left()
        count_finished = len(mission.finished_members)
        total = sum(1 for m in mission.role.members if mission.is_eligible(m))

        embed = discord.Embed(
            title="🍥 Suivi de la mission",
            description=(
                f"👥 Membres ayant fini : **{count_finished}/{total}**\n"
                f"⏳ Temps restant : **{str(datetime.timedelta(seconds=time_left))}**"
            ),
            color=0xFFA500
        )

        try:
            if mission.embed_message is None:
                msg = await channel.send(embed=embed)
                mission.embed_message = msg
            else:
                await mission.embed_message.edit(embed=embed)
        except Exception as e:
            print("❌ Erreur embed:", e)

        if mission.has_ended():
            await channel.send(f"🍙 Fin de la mission pour le rôle {mission.role.name}")
            missions.pop(guild_id, None)
            mission_tasks.pop(guild_id, None)
            break

        await asyncio.sleep(3)

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ Connecté en tant que {bot.user}")

@bot.tree.command(name="mission", description="Lancer une mission pour un rôle donné")
@discord.app_commands.describe(
    role="Rôle à surveiller",
    quota_vocal="Durée vocale requise (1-50)",
    unit_vocal="Unité (s,m,h)",
    quota_msg="Nombre de messages requis (1-50)",
    temps_max="Temps max",
    unit_max="Unité (s,m,h)",
    role1="Rôle 1 si réussi",
    role2="Rôle 2 si réussi",
    role_no_eligible1="Rôle non éligible 1 (opt.)",
    role_no_eligible2="Rôle non éligible 2 (opt.)"
)
async def mission(
    interaction: discord.Interaction,
    role: discord.Role,
    quota_vocal: int,
    unit_vocal: str,
    quota_msg: int,
    temps_max: int,
    unit_max: str,
    role1: discord.Role,
    role2: discord.Role,
    role_no_eligible1: discord.Role=None,
    role_no_eligible2: discord.Role=None
):
    if interaction.user.id not in whitelist:
        return await interaction.response.send_message("❌ t pas autorisé", ephemeral=True)
    if not (1<=quota_vocal<=50 and 1<=quota_msg<=50):
        return await interaction.response.send_message("⚠️ quotas 1 à 50", ephemeral=True)

    qv = convert_to_seconds(quota_vocal, unit_vocal)
    tm = convert_to_seconds(temps_max, unit_max)
    if qv is None or tm is None:
        return await interaction.response.send_message("⚠️ unités s,m ou h", ephemeral=True)

    m = Mission(interaction.guild, role, qv, quota_msg, tm,
                role1, role2, interaction.channel,
                role_no_eligible1, role_no_eligible2)
    missions[interaction.guild.id] = m

    embed = discord.Embed(
        title="🏯 Mission lancée",
        description=(
            f"Role surv : **{role.name}**\n"
            f"🎧 vocal : {quota_vocal}{unit_vocal}\n"
            f"💬 msg : {quota_msg}\n"
            f"⏱️ max : {temps_max}{unit_max}\n"
            f"🏆 gains : {role1.name} , {role2.name}"
        ),
        color=0xFFA500
    )
    no_text=""
    if role_no_eligible1: no_text+=f"🚫 non élig : {role_no_eligible1.name}\n"
    if role_no_eligible2: no_text+=f"🚫 non élig : {role_no_eligible2.name}\n"
    if no_text: embed.add_field(name="⚠️ exclu", value=no_text, inline=False)

    await interaction.response.send_message(embed=embed)

    task = asyncio.create_task(start_mission_loop(interaction.guild.id))
    mission_tasks[interaction.guild.id] = task

@bot.event
async def on_voice_state_update(member, before, after):
    m = missions.get(member.guild.id)
    if not m or member not in m.role.members or not m.is_eligible(member):
        return

    uid = member.id
    if before.channel is None and after.channel is not None:
        m.user_vocal_start[uid] = datetime.datetime.utcnow()
    elif before.channel is not None and after.channel is None:
        start = m.user_vocal_start.pop(uid, None)
        if start:
            delta = (datetime.datetime.utcnow() - start).total_seconds()
            m.vocal_times[uid] = m.vocal_times.get(uid,0)+delta
            await check_finish(member, m)

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return
    m = missions.get(message.guild.id)
    if not m or message.author not in m.role.members or not m.is_eligible(message.author):
        return
    uid=message.author.id
    m.msg_counts[uid]=m.msg_counts.get(uid,0)+1
    await check_finish(message.author, m)

async def check_finish(member, m):
    uid=member.id
    if uid in m.finished_members:
        return
    v = m.vocal_times.get(uid,0)
    if uid in m.user_vocal_start:
        v += (datetime.datetime.utcnow()-m.user_vocal_start[uid]).total_seconds()
    c = m.msg_counts.get(uid,0)
    if v>=m.quota_vocal_s and c>=m.quota_msg:
        m.finished_members.add(uid)
        try:
            await member.add_roles(m.role1, m.role2)
        except: pass
        # enregistrer score
        gs = scores.setdefault(m.guild.id,{})
        data = gs.setdefault(uid,{"count":0,"total_time":0.0})
        data["count"]+=1
        data["total_time"]+=(datetime.datetime.utcnow()-m.start_time).total_seconds()

@bot.tree.command(name="missiontop", description="classement global missions")
async def missiontop(interaction: discord.Interaction):
    gs=scores.get(interaction.guild.id)
    if not gs:
        return await interaction.response.send_message("❌ aucun score", ephemeral=True)
    sorted_ = sorted(gs.items(), key=lambda x:(-x[1]["count"],x[1]["total_time"]))
    embed=discord.Embed(title="🍙 Top missions",color=0xFFA500)
    lines=[]
    for i,(uid,d) in enumerate(sorted_[:10],start=1):
        u=interaction.guild.get_member(uid)
        name=u.display_name if u else str(uid)
        lines.append(f"**{i}.** {name} — 🏯 {d['count']} , ⏳ {int(d['total_time'])}s")
    embed.description="\n".join(lines)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="wl", description="gérer whitelist")
@discord.app_commands.describe(action="add/remove", user="membre")
async def wl(interaction: discord.Interaction, action: str, user: discord.Member):
    if interaction.user.id!=OWNER_ID:
        return await interaction.response.send_message("❌ t pas owner", ephemeral=True)
    act=action.lower()
    if act=="add":
        whitelist.add(user.id)
        await interaction.response.send_message(f"✅ {user.display_name} ajouté")
    elif act=="remove":
        whitelist.discard(user.id)
        await interaction.response.send_message(f"✅ {user.display_name} retiré")
    else:
        await interaction.response.send_message("❌ add ou remove", ephemeral=True)

bot.run(os.getenv("DISCORD_TOKEN"))

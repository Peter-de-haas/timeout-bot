import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import re
import os
import json
from datetime import datetime, timezone
import logging

# ---- Logging (journalctl) ----
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s'
)

# ---- Config ----
TOKEN = os.getenv("DISCORD_TOKEN")
COOLDOWN_ROLE_ID = int(os.getenv("COOLDOWN_ROLE_ID"))
TIMEOUTS_FILE = "/home/cronrunner/timeout-bot/timeouts.json"

if not TOKEN or not COOLDOWN_ROLE_ID:
    raise RuntimeError("DISCORD_TOKEN of COOLDOWN_ROLE_ID ontbreekt")

# ---- Bot ----
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ---- State ----
timeouts: dict[str, dict] = {}
release_tasks: dict[str, asyncio.Task] = {}

# ---- Utils ----
def parse_duration(tijd: str | None) -> int:
    if not tijd:
        return 15 * 60
    m = re.fullmatch(r"(\d+)([mh]?)", tijd.lower())
    if not m:
        return 15 * 60
    value, unit = m.groups()
    value = int(value)
    return value * 60 if unit == "m" else value * 3600

def load_timeouts():
    global timeouts
    if os.path.isfile(TIMEOUTS_FILE):
        try:
            with open(TIMEOUTS_FILE, "r") as f:
                timeouts = json.load(f)
        except Exception:
            timeouts = {}

def save_timeouts():
    with open(TIMEOUTS_FILE, "w") as f:
        json.dump(timeouts, f, indent=2)

# ---- Release logic ----
async def release_timeout(user_id: str, guild: discord.Guild):
    try:
        t = timeouts.get(user_id)
        if not t:
            return

        delay = t["end_ts"] - int(datetime.now(timezone.utc).timestamp())
        if delay > 0:
            await asyncio.sleep(delay)

        # Check again (might be early-released)
        t = timeouts.get(user_id)
        if not t:
            return

        member = guild.get_member(int(user_id))
        if not member:
            return

        bot_member = guild.me
        cooldown_role = guild.get_role(COOLDOWN_ROLE_ID)

        restored = [
            guild.get_role(rid)
            for rid in t.get("roles", [])
            if guild.get_role(rid)
            and guild.get_role(rid) < bot_member.top_role
        ]

        if cooldown_role and cooldown_role < bot_member.top_role:
            await member.remove_roles(cooldown_role)

        if restored:
            await member.add_roles(*restored)

        timeouts.pop(user_id, None)
        save_timeouts()
        logging.info(f"{member} is automatisch vrijgegeven uit kleurplaat")

    except asyncio.CancelledError:
        pass

# ---- /kleurplaat ----
@tree.command(name="kleurplaat", description="Ik wil naar de kleurhoek.")
@app_commands.describe(tijd="Bijv. 10m, 1h (standaard 15m)")
async def kleurplaat(interaction: discord.Interaction, tijd: str | None = None):
    await interaction.response.defer(ephemeral=True)

    if interaction.guild is None:
        await interaction.followup.send("Ik luister alleen in TEMS.")
        return

    member = interaction.user
    guild = interaction.guild
    bot_member = guild.me
    cooldown_role = guild.get_role(COOLDOWN_ROLE_ID)

    if cooldown_role in member.roles:
        await interaction.followup.send("Je bent al aan het kleuren.")
        return

    seconds = parse_duration(tijd)
    end_ts = int(datetime.now(timezone.utc).timestamp()) + seconds

    removable = []
    skipped = []

    for role in member.roles:
        if role == guild.default_role or role == cooldown_role:
            continue
        if role < bot_member.top_role:
            removable.append(role)
        else:
            skipped.append(role.name)

    # Remove roles safely
    for r in removable:
        try:
            await member.remove_roles(r)
        except discord.Forbidden:
            skipped.append(r.name)

    try:
        if cooldown_role < bot_member.top_role:
            await member.add_roles(cooldown_role)
    except discord.Forbidden:
        skipped.append(cooldown_role.name)

    timeouts[str(member.id)] = {
        "end_ts": end_ts,
        "roles": [r.id for r in removable]
    }
    save_timeouts()

    task = asyncio.create_task(release_timeout(str(member.id), guild))
    release_tasks[str(member.id)] = task

    await interaction.followup.send(
        f"🖍️ Je bent aan het kleuren voor {seconds // 60} minuten."
    )

# ---- /klaar ----
@tree.command(name="klaar", description="Ik wil stoppen met kleuren.")
async def klaar(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    if interaction.guild is None:
        await interaction.followup.send("Ik luister alleen in TEMS.")
        return

    member = interaction.user
    guild = interaction.guild
    bot_member = guild.me
    cooldown_role = guild.get_role(COOLDOWN_ROLE_ID)

    if cooldown_role not in member.roles:
        await interaction.followup.send("Je bent niet aan het kleuren.")
        return

    task = release_tasks.pop(str(member.id), None)
    if task:
        task.cancel()

    t = timeouts.pop(str(member.id), None)
    if t:
        restored = [
            guild.get_role(rid)
            for rid in t.get("roles", [])
            if guild.get_role(rid)
            and guild.get_role(rid) < bot_member.top_role
        ]

        if cooldown_role < bot_member.top_role:
            await member.remove_roles(cooldown_role)
        if restored:
            await member.add_roles(*restored)

        save_timeouts()

    await interaction.followup.send("🖍️ Je kleurtijd is vervroegd afgelopen.")
    logging.info(f"{member} heeft zichzelf vervroegd vrijgegeven uit kleurplaat")

# ---- /kleurplaat-override ----
@tree.command(
    name="kleurplaat-override",
    description="Beëindig iemands kleurplaat (mod/admin)"
)
@app_commands.describe(
    gebruiker="Gebruiker die uit de kleurplaat moet"
)
@app_commands.checks.has_permissions(moderate_members=True)
async def kleurplaat_override(
    interaction: discord.Interaction,
    gebruiker: discord.Member
):
    await interaction.response.defer(ephemeral=True)

    guild = interaction.guild
    bot_member = guild.me
    cooldown_role = guild.get_role(COOLDOWN_ROLE_ID)

    user_id = str(gebruiker.id)

    if user_id not in timeouts and cooldown_role not in gebruiker.roles:
        await interaction.followup.send(
            f"{gebruiker.mention} is niet aan het kleuren."
        )
        return

    # Cancel async task if running
    task = release_tasks.pop(user_id, None)
    if task:
        task.cancel()

    t = timeouts.pop(user_id, None)

    restored_roles = []
    if t:
        restored_roles = [
            guild.get_role(rid)
            for rid in t.get("roles", [])
            if guild.get_role(rid)
            and guild.get_role(rid) < bot_member.top_role
        ]

    try:
        if cooldown_role and cooldown_role < bot_member.top_role:
            await gebruiker.remove_roles(cooldown_role)

        if restored_roles:
            await gebruiker.add_roles(*restored_roles)

    except discord.Forbidden:
        await interaction.followup.send(
            "❌ Ik heb niet genoeg rechten om rollen te herstellen."
        )
        logging.error(
            f"Override mislukt voor {gebruiker}: onvoldoende permissies"
        )
        return

    save_timeouts()

    await interaction.followup.send(
        f"🛑 {gebruiker.mention} is handmatig uit de kleurplaat gehaald."
    )

    logging.info(
        f"{interaction.user} heeft kleurplaat override uitgevoerd op {gebruiker}"
    )


# ---- Ready ----
@bot.event
async def on_ready():
    load_timeouts()
    logging.info(f"Kleurplaat bot online als {bot.user}")
    await tree.sync()
    logging.info("Slash commands gesynchroniseerd")

bot.run(TOKEN)

import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import re
import os
import json
from datetime import datetime, timedelta
import logging

# ---- Logging setup ----
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
)
logger = logging.getLogger(__name__)

# ---- Config ----
TOKEN = os.getenv("DISCORD_TOKEN")
COOLDOWN_ROLE_ID = int(os.getenv("COOLDOWN_ROLE_ID"))
TIMEOUT_FILE = "timeouts.json"  # persistent opslag

if not TOKEN or not COOLDOWN_ROLE_ID:
    raise RuntimeError("Missing DISCORD_TOKEN or COOLDOWN_ROLE_ID")

# ---- Intents ----
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ---- Load/save persistent timeouts ----
def load_timeouts():
    if os.path.exists(TIMEOUT_FILE):
        with open(TIMEOUT_FILE, "r") as f:
            return json.load(f)
    return {}

def save_timeouts(data):
    with open(TIMEOUT_FILE, "w") as f:
        json.dump(data, f)

timeouts = load_timeouts()  # dict: user_id -> {roles: [id], end: timestamp}

# ---- Duration parser ----
def parse_duration(tijd: str) -> int:
    match = re.fullmatch(r"(\d+)([mh]?)", tijd.lower())
    if not match:
        return 15 * 60
    value, unit = match.groups()
    value = int(value)
    return value * 60 if unit == "m" else value * 3600

# ---- Self-timeout command ----
@tree.command(name="kleurplaat", description="Ik wil naar de kleurhoek.")
@app_commands.describe(
    tijd="Tijd om te kleuren (bijv. 10m, 1h). Standaard 15m."
)
async def kleurplaat(interaction: discord.Interaction, tijd: str = "15m"):
    if interaction.guild is None:
        await interaction.response.send_message(
            "Dit commando kan alleen in een server worden gebruikt.",
            ephemeral=True
        )
        return

    member = interaction.user
    guild = interaction.guild
    bot_member = guild.me
    cooldown_role = guild.get_role(COOLDOWN_ROLE_ID)

    if cooldown_role is None:
        logger.error(f"Kleurplaat rol niet gevonden voor guild {guild.name}")
        await interaction.response.send_message("Kleurplaat rol niet gevonden.", ephemeral=True)
        return

    seconds = parse_duration(tijd)

    if str(member.id) in timeouts:
        await interaction.response.send_message("Je bent al aan het kleuren.", ephemeral=True)
        return

    removable_roles = []
    skipped_roles = []
    for role in member.roles:
        if role == guild.default_role or role == cooldown_role:
            continue
        if role < bot_member.top_role:
            removable_roles.append(role)
        else:
            skipped_roles.append(role.name)

    # Verwijder rollen
    if removable_roles:
        await member.remove_roles(*removable_roles)
        logger.info(f"{member} rollen verwijderd: {[r.name for r in removable_roles]}")
    if skipped_roles:
        logger.warning(f"{member} kon deze rollen niet aanpassen: {skipped_roles}")

    # Voeg cooldown rol toe
    if cooldown_role < bot_member.top_role:
        await member.add_roles(cooldown_role)
    else:
        logger.warning(f"{member} kon cooldown rol niet krijgen, rol boven bot")

    # Sla timeout op
    end_time = (datetime.utcnow() + timedelta(seconds=seconds)).timestamp()
    timeouts[str(member.id)] = {
        "roles": [r.id for r in removable_roles],
        "end": end_time
    }
    save_timeouts(timeouts)
    logger.info(f"{member} begonnen met kleuren voor {seconds // 60} minuten (einde: {datetime.utcfromtimestamp(end_time)})")

    await interaction.response.send_message(f"🖍️ Je bent aan het kleuren voor {seconds // 60} minuten.", ephemeral=True)

    # Wacht en herstel rollen automatisch
    await asyncio.sleep(seconds)
    # Check of timeout nog bestaat (kan zijn vervroegd beëindigd)
    if str(member.id) in timeouts:
        await restore_roles(member, guild, bot_member, cooldown_role)
        logger.info(f"{member} cooldown automatisch afgelopen")

# ---- Early release command ----
@tree.command(name="klaar", description="Ik wil stoppen met kleuren.")
async def klaar(interaction: discord.Interaction):
    member = interaction.user
    guild = interaction.guild
    bot_member = guild.me
    cooldown_role = guild.get_role(COOLDOWN_ROLE_ID)

    if interaction.guild is None:
        await interaction.response.send_message(
            "Dit commando kan alleen in een server worden gebruikt.",
            ephemeral=True
        )
        return

    if str(member.id) not in timeouts:
        await interaction.response.send_message("Je bent helemaal niet aan het kleuren.", ephemeral=True)
        return

    await restore_roles(member, guild, bot_member, cooldown_role)
    logger.info(f"{member} cooldown vroegtijdig beëindigd")
    await interaction.response.send_message("🖍️ Je cooldown is vervroegd afgelopen.", ephemeral=True)

# ---- Restore helper ----
async def restore_roles(member, guild, bot_member, cooldown_role):
    data = timeouts.pop(str(member.id), None)
    if data is None:
        return
    save_timeouts(timeouts)
    restored_roles = []
    for rid in data["roles"]:
        role = guild.get_role(rid)
        if role and role < bot_member.top_role:
            restored_roles.append(role)
    if cooldown_role < bot_member.top_role:
        await member.remove_roles(cooldown_role)
    if restored_roles:
        await member.add_roles(*restored_roles)
    logger.info(f"{member} rollen hersteld: {[r.name for r in restored_roles]}")

# ---- Bot ready ----
@bot.event
async def on_ready():
    logger.info(f"Kleurplaat bot online als {bot.user}")
    await tree.sync()
    logger.info("Slash commands gesynchroniseerd")

# ---- Run ----
bot.run(TOKEN)

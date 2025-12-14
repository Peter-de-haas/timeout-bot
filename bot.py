import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import re
import os
import json
from datetime import datetime, timezone
import logging

# ---- Logging naar journalctl ----
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] %(message)s')

# ---- Config ----
TOKEN = os.getenv("DISCORD_TOKEN")
COOLDOWN_ROLE_ID = int(os.getenv("COOLDOWN_ROLE_ID"))
TIMEOUTS_FILE = "/home/cronrunner/timeout-bot/timeouts.json"

if not TOKEN or not COOLDOWN_ROLE_ID:
    raise RuntimeError("DISCORD_TOKEN of COOLDOWN_ROLE_ID ontbreekt")

# ---- Intents ----
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ---- Backup in-memory & persistent ----
role_backup = {}  # in-memory
timeouts = {}     # persistent, geladen uit JSON

# ---- Duration parser ----
def parse_duration(tijd: str) -> int:
    match = re.fullmatch(r"(\d+)([mh]?)", tijd.lower())
    if not match:
        return 15 * 60
    value, unit = match.groups()
    value = int(value)
    return value * 60 if unit == "m" else value * 3600

# ---- Load / Save timeouts ----
def load_timeouts():
    global timeouts
    if os.path.isfile(TIMEOUTS_FILE):
        with open(TIMEOUTS_FILE, "r") as f:
            try:
                timeouts = json.load(f)
            except json.JSONDecodeError:
                timeouts = {}
    else:
        timeouts = {}

def save_timeouts():
    with open(TIMEOUTS_FILE, "w") as f:
        json.dump(timeouts, f)

load_timeouts()

# ---- Kleurplaat command ----
@tree.command(name="kleurplaat", description="Ik wil naar de kleurhoek.")
@app_commands.describe(
    tijd="Tijd om te kleuren (bijv. 10m, 1h). Standaard 15m."
)
async def kleurplaat(interaction: discord.Interaction, tijd: str = "15m"):
    await interaction.response.send_message(content="\u200b", ephemeral=True) #minimale response

    if interaction.guild is None:
        logging.warning(f"{interaction.user} probeerde /kleurplaat in DM te gebruiken")
        return

    member = interaction.user
    guild = interaction.guild
    bot_member = guild.me
    cooldown_role = guild.get_role(COOLDOWN_ROLE_ID)
    if cooldown_role is None:
        logging.error("Cooldown role niet gevonden")
        return

    seconds = parse_duration(tijd)
    now_ts = int(datetime.now(timezone.utc).timestamp())
    end_ts = now_ts + seconds

    # Prevent stacking
    if cooldown_role in member.roles:
        logging.info(f"{member} probeert zichzelf opnieuw in kleurplaat te zetten")
        return

    # Determine removable roles
    removable_roles = []
    skipped_roles = []
    for role in member.roles:
        if role == guild.default_role or role == cooldown_role:
            continue
        if role < bot_member.top_role:
            removable_roles.append(role)
        else:
            skipped_roles.append(role.name)

    role_backup[member.id] = [r.id for r in removable_roles]

    # Remove removable roles
    if removable_roles:
        await member.remove_roles(*removable_roles)

    # Add cooldown role if manageable
    if cooldown_role < bot_member.top_role:
        await member.add_roles(cooldown_role)
    else:
        skipped_roles.append(cooldown_role.name)

    # Persistent opslaan
    timeouts[str(member.id)] = {
        "end_ts": end_ts,
        "roles": [r.id for r in removable_roles]
    }
    save_timeouts()
    logging.info(f"{member} is aan het kleuren voor {seconds//60} min, skipped: {skipped_roles}")

    # Wait asynchronously
    async def release():
        await asyncio.sleep(seconds)
        # check of member niet vroegtijdig is vrijgegeven
        t = timeouts.get(str(member.id))
        if t is None or int(datetime.now(timezone.utc).timestamp()) < t["end_ts"]:
            return

        restored_ids = t.get("roles", [])
        restored_roles = [
            guild.get_role(rid) for rid in restored_ids
            if guild.get_role(rid) and guild.get_role(rid) < bot_member.top_role
        ]
        if cooldown_role < bot_member.top_role:
            await member.remove_roles(cooldown_role)
        if restored_roles:
            await member.add_roles(*restored_roles)

        # verwijder uit persistent
        timeouts.pop(str(member.id), None)
        save_timeouts()
        logging.info(f"{member} is automatisch vrijgegeven uit kleurplaat")

    asyncio.create_task(release())

# ---- Klaar command ----
@tree.command(name="klaar", description="Ik wil stoppen met kleuren.")
async def klaar(interaction: discord.Interaction):
    await interaction.response.send_message(content="\u200b", ephemeral=True) #minimale response

    if interaction.guild is None:
        return

    member = interaction.user
    guild = interaction.guild
    bot_member = guild.me
    cooldown_role = guild.get_role(COOLDOWN_ROLE_ID)
    if cooldown_role not in member.roles:
        return

    t = timeouts.pop(str(member.id), None)
    if t:
        restored_ids = t.get("roles", [])
        restored_roles = [
            guild.get_role(rid) for rid in restored_ids
            if guild.get_role(rid) and guild.get_role(rid) < bot_member.top_role
        ]
        if cooldown_role < bot_member.top_role:
            await member.remove_roles(cooldown_role)
        if restored_roles:
            await member.add_roles(*restored_roles)
        save_timeouts()
        logging.info(f"{member} heeft zichzelf vervroegd vrijgegeven uit kleurplaat")

# ---- On Ready ----
@bot.event
async def on_ready():
    logging.info(f"Kleurplaat bot online als {bot.user}")
    await tree.sync()
    logging.info("Slash commands gesynchroniseerd")

# ---- Run ----
bot.run(TOKEN)

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
timeouts = {}     # persistent, loaded from JSON
release_tasks = {}  # running asyncio tasks

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

# ---- Async release helper ----
async def release_timeout(member_id: str, guild: discord.Guild):
    t = timeouts.get(member_id)
    if not t:
        return

    now_ts = int(datetime.now(timezone.utc).timestamp())
    if now_ts < t["end_ts"]:
        # still not ready to release
        await asyncio.sleep(t["end_ts"] - now_ts)

    t = timeouts.pop(member_id, None)
    if not t:
        return

    member = guild.get_member(int(member_id))
    if not member:
        return

    cooldown_role = guild.get_role(COOLDOWN_ROLE_ID)

    # Restore roles safely
    restored_roles = [
        guild.get_role(rid) for rid in t.get("roles", [])
        if guild.get_role(rid) and guild.get_role(rid) < guild.me.top_role
    ]

    # Remove cooldown role
    try:
        if cooldown_role and cooldown_role < guild.me.top_role and cooldown_role in member.roles:
            await member.remove_roles(cooldown_role)
    except discord.Forbidden:
        logging.warning(f"Cannot remove cooldown role from {member}")

    # Restore roles
    for r in restored_roles:
        try:
            await member.add_roles(r)
        except discord.Forbidden:
            logging.warning(f"Cannot restore role {r.name} for {member}")

    save_timeouts()
    logging.info(f"{member} is automatisch vrijgegeven uit kleurplaat")
    release_tasks.pop(member_id, None)

# ---- Kleurplaat command ----
@tree.command(name="kleurplaat", description="Ik wil naar de kleurhoek.")
@app_commands.describe(
    tijd="Tijd om te kleuren (bijv. 10m, 1h). Standaard 15m."
)
async def kleurplaat(interaction: discord.Interaction, tijd: str = None):
    member = interaction.user
    guild = interaction.guild

    if guild is None:
        await interaction.response.send_message(
            "Ik luister alleen in TEMS.",
            ephemeral=True
        )
        logging.warning(f"{member} probeerde /kleurplaat in DM te gebruiken")
        return

    bot_member = guild.me
    cooldown_role = guild.get_role(COOLDOWN_ROLE_ID)
    if cooldown_role is None:
        await interaction.response.send_message(
            "Kleurplaat rol niet gevonden.",
            ephemeral=True
        )
        logging.error("Cooldown role niet gevonden")
        return

    # Default to 15 minutes if tijd is None
    if not tijd:
        tijd = "15m"

    seconds = parse_duration(tijd)

    if cooldown_role in member.roles:
        await interaction.response.send_message(
            "Je bent al aan het kleuren.",
            ephemeral=True
        )
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

    # Remove roles safely
    for r in removable_roles:
        try:
            await member.remove_roles(r)
        except discord.Forbidden:
            skipped_roles.append(r.name)
            logging.warning(f"Cannot remove role {r.name} from {member}")

    # Add cooldown role safely
    try:
        if cooldown_role < bot_member.top_role:
            await member.add_roles(cooldown_role)
        else:
            skipped_roles.append(cooldown_role.name)
    except discord.Forbidden:
        skipped_roles.append(cooldown_role.name)
        logging.warning(f"Cannot add cooldown role to {member}")

    # Persistent opslaan
    now_ts = int(datetime.now(timezone.utc).timestamp())
    end_ts = now_ts + seconds
    timeouts[str(member.id)] = {
        "end_ts": end_ts,
        "roles": [r.id for r in removable_roles]
    }
    save_timeouts()

    # Respond immediately
    await interaction.response.send_message(
        content=f"🖍️ Je bent aan het kleuren voor {seconds // 60} minuten.",
        ephemeral=True
    )

    # Start background release task
    task = asyncio.create_task(release_timeout(str(member.id), guild))
    release_tasks[str(member.id)] = task
    logging.info(f"{member} is aan het kleuren voor {seconds // 60} min, skipped: {skipped_roles}")

# ---- Klaar command ----
@tree.command(name="klaar", description="Ik wil stoppen met kleuren.")
async def klaar(interaction: discord.Interaction):
    member = interaction.user
    guild = interaction.guild
    if guild is None:
        await interaction.response.send_message(
            "Ik luister alleen in TEMS.",
            ephemeral=True
        )
        return

    cooldown_role = guild.get_role(COOLDOWN_ROLE_ID)
    if cooldown_role not in member.roles:
        await interaction.response.send_message(
            "Je bent niet aan het kleuren.",
            ephemeral=True
        )
        return

    # Cancel async task if running
    task = release_tasks.pop(str(member.id), None)
    if task:
        task.cancel()

    t = timeouts.pop(str(member.id), None)
    restored_roles = []
    if t:
        for rid in t.get("roles", []):
            role = guild.get_role(rid)
            if role and role < guild.me.top_role:
                restored_roles.append(role)
    try:
        if cooldown_role < guild.me.top_role:
            await member.remove_roles(cooldown_role)
    except discord.Forbidden:
        logging.warning(f"Cannot remove cooldown role from {member}")

    for r in restored_roles:
        try:
            await member.add_roles(r)
        except discord.Forbidden:
            logging.warning(f"Cannot restore role {r.name} for {member}")

    save_timeouts()
    await interaction.response.send_message(
        "🖍️ Je kleurtijd is vervroegd afgelopen.",
        ephemeral=True
    )
    logging.info(f"{member} heeft zichzelf vervroegd vrijgegeven uit kleurplaat")

# ---- On Ready ----
@bot.event
async def on_ready():
    logging.info(f"Kleurplaat bot online als {bot.user}")
    await tree.sync()
    logging.info("Slash commands gesynchroniseerd")

# ---- Run ----
bot.run(TOKEN)

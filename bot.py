import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import re
import os
import json
from datetime import datetime, timedelta

# ---- Configuratie laden ----
TOKEN = os.getenv("DISCORD_TOKEN")
COOLDOWN_ROLE_ID = int(os.getenv("COOLDOWN_ROLE_ID"))

if not TOKEN or not COOLDOWN_ROLE_ID:
    raise RuntimeError("Ontbrekende DISCORD_TOKEN of COOLDOWN_ROLE_ID")

# ---- Intents ----
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ---- Tijdelijke opslag op disk ----
TIMEOUT_FILE = "/home/cronrunner/timeout-bot/timeouts.json"

def load_timeouts():
    try:
        with open(TIMEOUT_FILE, "r") as f:
            data = json.load(f)
            # zet tijdstempels terug naar datetime
            return {int(k): datetime.fromisoformat(v) for k, v in data.items()}
    except Exception:
        return {}

def save_timeouts(timeouts):
    data = {str(k): v.isoformat() for k, v in timeouts.items()}
    with open(TIMEOUT_FILE, "w") as f:
        json.dump(data, f)

timeouts = load_timeouts()  # member.id -> einde datetime
role_backup = {}            # in-memory: member.id -> lijst met rol ID's

# ---- Duur parser ----
def parse_duration(tijd: str) -> int:
    """
    Parse tijd zoals '10m', '1h'.
    Standaard 15 minuten bij ongeldige input.
    """
    match = re.fullmatch(r"(\d+)([mh]?)", tijd.lower())
    if not match:
        return 15 * 60
    value, unit = match.groups()
    value = int(value)
    return value * 60 if unit == "m" else value * 3600

# ---- /kleurplaat command ----
@tree.command(
    name="kleurplaat",
    description="Ik wil naar de kleurhoek."
)
@app_commands.describe(
    tijd="Tijd om te kleuren (bijv. 10m, 1h). Standaard 15 minuten."
)
async def kleurplaat(interaction: discord.Interaction, tijd: str = "15m"):
    if interaction.guild is None:
        await interaction.response.send_message(
            "Deze command kan alleen op de server gebruikt worden.",
            ephemeral=True
        )
        return

    member = interaction.user
    guild = interaction.guild
    bot_member = guild.me
    cooldown_role = guild.get_role(COOLDOWN_ROLE_ID)
    if cooldown_role is None:
        await interaction.response.send_message(
            "Kleurplaat-rol niet gevonden.",
            ephemeral=True
        )
        return

    # voorkom stacking
    if cooldown_role in member.roles:
        await interaction.response.send_message(
            "Je bent al aan het kleuren.",
            ephemeral=True
        )
        return

    seconds = parse_duration(tijd)
    einde = datetime.utcnow() + timedelta(seconds=seconds)
    timeouts[member.id] = einde
    save_timeouts(timeouts)

    # bepaal verwijderbare rollen
    removable_roles = [role for role in member.roles
                       if role.id != guild.id and role != cooldown_role and role < bot_member.top_role]
    role_backup[member.id] = [r.id for r in removable_roles]

    # verwijder rollen
    if removable_roles:
        await member.remove_roles(*removable_roles)

    # voeg cooldown rol toe
    if cooldown_role < bot_member.top_role:
        await member.add_roles(cooldown_role)
    else:
        print(f"⚠ Kon de Kleurplaat-rol niet toevoegen aan {member} (rol boven bot).")

    print(f"{member} is begonnen met kleuren voor {seconds//60} minuten.")

    # wacht
    await asyncio.sleep(seconds)

    # controleer of de gebruiker nog steeds in timeouts staat
    if member.id in timeouts and datetime.utcnow() >= timeouts[member.id]:
        restored_roles = []
        restored_ids = role_backup.pop(member.id, [])
        for rid in restored_ids:
            role = guild.get_role(rid)
            if role and role < bot_member.top_role:
                restored_roles.append(role)

        if cooldown_role < bot_member.top_role:
            await member.remove_roles(cooldown_role)
        if restored_roles:
            await member.add_roles(*restored_roles)

        timeouts.pop(member.id, None)
        save_timeouts(timeouts)

        print(f"{member} is klaar met kleuren.")

# ---- /klaar command ----
@tree.command(
    name="klaar",
    description="Ik wil stoppen met kleuren."
)
async def klaar(interaction: discord.Interaction):
    if interaction.guild is None:
        print(f"{interaction.user} probeerde /klaar buiten een server.")
        return

    member = interaction.user
    guild = interaction.guild
    bot_member = guild.me
    cooldown_role = guild.get_role(COOLDOWN_ROLE_ID)

    if cooldown_role not in member.roles:
        print(f"{member} was niet aan het kleuren maar trapt wel /klaar af.")
        return

    # herstel rollen
    restored_roles = []
    restored_ids = role_backup.pop(member.id, [])
    for rid in restored_ids:
        role = guild.get_role(rid)
        if role and role < bot_member.top_role:
            restored_roles.append(role)

    if cooldown_role < bot_member.top_role:
        await member.remove_roles(cooldown_role)
    if restored_roles:
        await member.add_roles(*restored_roles)

    timeouts.pop(member.id, None)
    save_timeouts(timeouts)

    print(f"{member} heeft vervroegd de kleurhoek verlaten.")

# ---- Bot klaar event ----
@bot.event
async def on_ready():
    print(f"Kleurplaat bot online als {bot.user}")
    await tree.sync()
    print("Slash commands gesynchroniseerd.")

# ---- Run ----
bot.run(TOKEN)

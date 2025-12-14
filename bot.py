import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import re
import os

# ---- Load config from environment ----
TOKEN = os.getenv("DISCORD_TOKEN")
COOLDOWN_ROLE_ID = int(os.getenv("COOLDOWN_ROLE_ID"))

if not TOKEN or not COOLDOWN_ROLE_ID:
    raise RuntimeError("Missing DISCORD_TOKEN or COOLDOWN_ROLE_ID")

# ---- Intents ----
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# Backup roles (in-memory)
role_backup = {}

# ---- Duration parser ----
def parse_duration(tijd: str) -> int:
    """
    Parse durations like:
    - 10m
    - 1h
    Defaults to 15 minutes if invalid
    """
    match = re.fullmatch(r"(\d+)([mh]?)", tijd.lower())
    if not match:
        return 15 * 60  # 15 minutes fallback

    value, unit = match.groups()
    value = int(value)

    return value * 60 if unit == "m" else value * 3600

# ---- Self-timeout command ----
@tree.command(
    name="kleurplaat",
    description="Ik wil naar de kleurhoek."
)
@app_commands.describe(
    tijd="Tijd om te kleuren (bijv. 10m, 1h) Standaard 15m."
)
async def kleurplaat(
    interaction: discord.Interaction,
    tijd: str = "15m"  # Default to 15 minutes
):
    if interaction.guild is None:
        await interaction.response.send_message(
            "LALALALALALALA IK LUISTER HIER NIET.",
            ephemeral=True
        )
        return

    member = interaction.user
    guild = interaction.guild
    bot_member = guild.me
    cooldown_role = guild.get_role(COOLDOWN_ROLE_ID)

    if cooldown_role is None:
        await interaction.response.send_message(
            "Kleurplaat kanaal rol niet gevonden.",
            ephemeral=True
        )
        return

    seconds = parse_duration(tijd)

    # Prevent stacking
    if cooldown_role in member.roles:
        await interaction.response.send_message(
            "Je bent al aan het kleuren.",
            ephemeral=True
        )
        return

    # Determine which roles are removable
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

    # Add cooldown role if bot can manage it
    if cooldown_role < bot_member.top_role:
        await member.add_roles(cooldown_role)
    else:
        skipped_roles.append(cooldown_role.name)

    msg = f"🖍️ Je bent aan het kleuren voor {seconds // 60} minutes."
    if skipped_roles:
        msg += f"\n⚠ Could not modify roles: {', '.join(skipped_roles)}"

    await interaction.response.send_message(msg)

    # Wait for duration
    await asyncio.sleep(seconds)

    # Restore roles safely
    restored_roles = []
    if member.id in role_backup:
        restored_ids = role_backup.pop(member.id)
        for rid in restored_ids:
            role = guild.get_role(rid)
            if role and role < bot_member.top_role:
                restored_roles.append(role)

    # Remove cooldown role if manageable
    if cooldown_role < bot_member.top_role:
        await member.remove_roles(cooldown_role)

    if restored_roles:
        await member.add_roles(*restored_roles)

    await interaction.followup.send(
        "🖍️ Jouw Kleur tijd is afgelopen."
    )

# ---- Early release command ----
@tree.command(
    name="klaar",
    description="Ik wil stoppen met kleuren."
)
async def klaar(interaction: discord.Interaction):
    member = interaction.user
    guild = interaction.guild
    bot_member = guild.me

    if interaction.guild is None:
        await interaction.response.send_message(
            "LALALALALALALA IK LUISTER HIER NIET.",
            ephemeral=True
        )
        return

    cooldown_role = guild.get_role(COOLDOWN_ROLE_ID)
    if cooldown_role not in member.roles:
        await interaction.response.send_message(
            "Je bent helemaal niet aan het kleuren.",
            ephemeral=True
        )
        return

    # Restore roles safely
    restored_roles = []
    if member.id in role_backup:
        restored_ids = role_backup.pop(member.id)
        for rid in restored_ids:
            role = guild.get_role(rid)
            if role and role < bot_member.top_role:
                restored_roles.append(role)

    # Remove cooldown role if manageable
    if cooldown_role < bot_member.top_role:
        await member.remove_roles(cooldown_role)

    if restored_roles:
        await member.add_roles(*restored_roles)

    await interaction.response.send_message(
        "🖍️ Jouw Kleur tijd is vervroegd afgelopen."
    )

# ---- Bot Ready ----
@bot.event
async def on_ready():
    print(f"Timeout bot online as {bot.user}")
    await tree.sync()
    print("Slash commands synced.")

# ---- Run Bot ----
bot.run(TOKEN)

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
def parse_duration(duration: str) -> int:
    """
    Parse durations like:
    - 10m
    - 1h
    Defaults to 15 minutes if invalid
    """
    match = re.fullmatch(r"(\d+)([mh]?)", duration.lower())
    if not match:
        return 900

    value, unit = match.groups()
    value = int(value)

    return value * 60 if unit == "m" else value * 3600

# ---- Self-timeout command ----
@tree.command(name="timeout", description="Put yourself in cooldown")
@app_commands.describe(
    duration="Duration (e.g. 10m, 1h). Defaults to 1h"
)
async def timeout(
    interaction: discord.Interaction,
    duration: str = "1h"
):
    # Must be used in a server
    if interaction.guild is None:
        await interaction.response.send_message(
            "This command can only be used in a server.",
            ephemeral=True
        )
        return

    member = interaction.user
    guild = interaction.guild
    bot_member = guild.me

    cooldown_role = guild.get_role(COOLDOWN_ROLE_ID)
    if cooldown_role is None:
        await interaction.response.send_message(
            "Cooldown role not found.",
            ephemeral=True
        )
        return

    seconds = parse_duration(duration)

    # Prevent stacking
    if cooldown_role in member.roles:
        await interaction.response.send_message(
            "You are already in cooldown.",
            ephemeral=True
        )
        return

    # Roles the bot is allowed to manage
    removable_roles = [
        role for role in member.roles
        if role.id != guild.id
        and role != cooldown_role
        and role < bot_member.top_role
    ]

    role_backup[member.id] = [r.id for r in removable_roles]

    # Remove roles
    for role in removable_roles:
        await member.remove_roles(role)

    # Add cooldown role
    if cooldown_role < bot_member.top_role:
        await member.add_roles(cooldown_role)
    else:
        await interaction.response.send_message(
            "Cooldown role is above the bot's role.",
            ephemeral=True
        )
        return

    await interaction.response.send_message(
        f"🧊 You have put yourself in cooldown for {seconds // 60} minutes."
    )

    # Wait
    await asyncio.sleep(seconds)

    # Restore
    if member.id in role_backup:
        restored_ids = role_backup.pop(member.id)
        restored_roles = [
            guild.get_role(rid)
            for rid in restored_ids
            if guild.get_role(rid)
            and guild.get_role(rid) < bot_member.top_role
        ]

        await member.remove_roles(cooldown_role)
        for role in restored_roles:
            await member.add_roles(role)

        await interaction.followup.send(
            "⏱️ Your cooldown has ended."
        )

# ---- Ready ----
@bot.event
async def on_ready():
    print(f"Timeout bot online as {bot.user}")
    await tree.sync()
    print("Slash commands synced.")

# ---- Run ----
bot.run(TOKEN)

import os
import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import re

# ---- Load credentials from environment ----
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
COOLDOWN_ROLE_ID = int(os.getenv("COOLDOWN_ROLE_ID"))

# ---- Intents ----
intents = discord.Intents.default()  # no privileged intents
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# Backup roles
role_backup = {}

# ---- Utility to parse durations like "10m", "1h" ----
def parse_duration(duration_str: str) -> int:
    """Return duration in seconds. Defaults to 3600 (1h) if invalid."""
    match = re.match(r"(\d+)([mh]?)$", duration_str.lower())
    if not match:
        return 3600
    value, unit = match.groups()
    value = int(value)
    if unit == "m":
        return value * 60
    return value * 3600  # default or 'h'

# ---- Timeout Command ----
@tree.command(name="timeout", description="Put a user in cooldown")
@app_commands.describe(
    member="User to timeout",
    duration="Duration (e.g., 10m, 1h). Defaults to 1h"
)
async def timeout(interaction: discord.Interaction, member: discord.Member, duration: str = "1h"):
    guild = interaction.guild
    bot_member = guild.me
    cooldown_role = guild.get_role(COOLDOWN_ROLE_ID)
    if cooldown_role is None:
        await interaction.response.send_message("Cooldown role not found!", ephemeral=True)
        return

    seconds = parse_duration(duration)

    # Save manageable roles
    original_roles = [
        role for role in member.roles
        if role.id != guild.id and role.id != COOLDOWN_ROLE_ID and role < bot_member.top_role
    ]
    role_backup[member.id] = [r.id for r in original_roles]

    # Track roles that cannot be modified
    skipped_roles = [
        role.name for role in member.roles
        if role.id != guild.id and role.id != COOLDOWN_ROLE_ID and role >= bot_member.top_role
    ]

    # Remove roles safely
    for r in original_roles:
        await member.remove_roles(r)

    # Add cooldown role if manageable
    if cooldown_role < bot_member.top_role:
        await member.add_roles(cooldown_role)
    else:
        skipped_roles.append(cooldown_role.name)

    msg = f"{member.mention} has been put in cooldown for {seconds//60} minutes."
    if skipped_roles:
        msg += f"\n⚠ Could not modify roles: {', '.join(skipped_roles)}"
    await interaction.response.send_message(msg)

    # Wait for duration
    await asyncio.sleep(seconds)

    # Restore roles safely
    if member.id in role_backup:
        restored_ids = role_backup.pop(member.id)
        restored_roles = [
            guild.get_role(rid) for rid in restored_ids
            if guild.get_role(rid) and guild.get_role(rid) < bot_member.top_role
        ]

        if cooldown_role < bot_member.top_role:
            await member.remove_roles(cooldown_role)

        for r in restored_roles:
            await member.add_roles(r)

        await interaction.followup.send(f"{member.mention} has been released from cooldown.")

# ---- Bot Ready ----
@bot.event
async def on_ready():
    print(f"Timeout bot online as {bot.user}")
    await tree.sync()
    print("Slash commands synced.")

# ---- Run Bot ----
bot.run(TOKEN)

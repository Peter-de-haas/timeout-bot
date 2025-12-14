import os
import re
import asyncio
import discord
from discord import app_commands
from discord.ext import commands

# ---- Load config from environment ----
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
COOLDOWN_ROLE_ID = int(os.getenv("COOLDOWN_ROLE_ID"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "info")

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is not set")

# ---- Intents (no privileged intents needed) ----
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ---- Role backup storage ----
role_backup: dict[int, list[int]] = {}

# ---- Duration parser ----
def parse_duration(duration: str | None) -> int:
    """Parse duration like 10m or 1h. Defaults to 1h."""
    if not duration:
        return 3600

    match = re.match(r"^(\d+)([mh]?)$", duration.lower())
    if not match:
        return 3600

    value, unit = match.groups()
    value = int(value)

    if unit == "m":
        return value * 60

    return value * 3600  # default = hours

# ---- Slash command ----
@tree.command(name="timeout", description="Put yourself in cooldown")
@app_commands.describe(duration="Duration (e.g. 10m, 1h). Defaults to 1h")
async def timeout(interaction: discord.Interaction, duration: str | None = None):
    member = interaction.user
    guild = interaction.guild
    bot_member = guild.me

    if interaction.channel_id != CHANNEL_ID:
        await interaction.response.send_message(
            "❌ You can only use this command in the cooldown channel.",
            ephemeral=True
        )
        return

    cooldown_role = guild.get_role(COOLDOWN_ROLE_ID)
    if not cooldown_role:
        await interaction.response.send_message(
            "❌ Cooldown role not found.",
            ephemeral=True
        )
        return

    seconds = parse_duration(duration)

    # Save removable roles
    removable_roles = [
        role for role in member.roles
        if role.id != guild.id
        and role.id != COOLDOWN_ROLE_ID
        and role < bot_member.top_role
    ]

    role_backup[member.id] = [r.id for r in removable_roles]

    # Remove roles
    if removable_roles:
        await member.remove_roles(*removable_roles, reason="Self-timeout")

    # Add cooldown role
    if cooldown_role < bot_member.top_role:
        await member.add_roles(cooldown_role, reason="Self-timeout")

    await interaction.response.send_message(
        f"⏳ You are now in cooldown for **{seconds // 60} minutes**."
    )

    # Wait
    await asyncio.sleep(seconds)

    # Restore roles
    restored_ids = role_backup.pop(member.id, [])
    restored_roles = [
        guild.get_role(rid)
        for rid in restored_ids
        if guild.get_role(rid) and guild.get_role(rid) < bot_member.top_role
    ]

    if cooldown_role < bot_member.top_role:
        await member.remove_roles(cooldown_role, reason="Cooldown expired")

    if restored_roles:
        await member.add_roles(*restored_roles, reason="Cooldown expired")

    await interaction.followup.send(
        "✅ Your cooldown has ended. Roles restored."
    )

# ---- Ready ----
@bot.event
async def on_ready():
    print(f"Timeout bot online as {bot.user}")
    await tree.sync()
    print("Slash commands synced.")

# ---- Run ----
bot.run(TOKEN)

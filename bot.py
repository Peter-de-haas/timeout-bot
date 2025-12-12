import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import argparse

# ---- Parse CLI arguments ----
parser = argparse.ArgumentParser()
parser.add_argument("--token", required=True)
parser.add_argument("--cooldown-channel", required=True)
parser.add_argument("--cooldown-role", required=True)
args = parser.parse_args()

TOKEN = args.token
COOLDOWN_CHANNEL_ID = int(args.cooldown_channel)
COOLDOWN_ROLE_ID = int(args.cooldown_role)

# ---- Intents ----
intents = discord.Intents.default()  # no privileged intents
bot = commands.Bot(command_prefix="!", intents=intents)

# ---- App Command Tree ----
tree = bot.tree

# Backup roles
role_backup = {}

# ---- Timeout Command ----
@tree.command(name="timeout", description="Put a user in cooldown for 1 hour")
@app_commands.describe(member="User to timeout")
async def timeout(interaction: discord.Interaction, member: discord.Member):

    guild = interaction.guild
    cooldown_role = guild.get_role(COOLDOWN_ROLE_ID)
    if cooldown_role is None:
        await interaction.response.send_message("Cooldown role not found!", ephemeral=True)
        return

    # Save original roles (except @everyone and cooldown role)
    original_roles = [role for role in member.roles if role.id != guild.id and role.id != COOLDOWN_ROLE_ID]
    role_backup[member.id] = [r.id for r in original_roles]

    # Remove roles
    for r in original_roles:
        await member.remove_roles(r)

    # Add cooldown role
    await member.add_roles(cooldown_role)
    await interaction.response.send_message(f"{member.mention} has been put in cooldown for 1 hour.")

    # Wait 1 hour
    await asyncio.sleep(3600)

    # Restore roles
    if member.id in role_backup:
        restored_ids = role_backup.pop(member.id)
        restored_roles = [guild.get_role(rid) for rid in restored_ids]
        await member.remove_roles(cooldown_role)
        for r in restored_roles:
            if r:
                await member.add_roles(r)
        await interaction.followup.send(f"{member.mention} has been released from cooldown.")

# ---- Bot Ready ----
@bot.event
async def on_ready():
    print(f"Timeout bot online as {bot.user}")
    # Sync slash commands with Discord
    await tree.sync()
    print("Slash commands synced.")

# ---- Run Bot ----
bot.run(TOKEN)

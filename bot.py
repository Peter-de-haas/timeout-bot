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
intents = discord.Intents.default()  # No privileged intents required
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
    bot_member = guild.me  # The bot's member object
    cooldown_role = guild.get_role(COOLDOWN_ROLE_ID)

    if cooldown_role is None:
        await interaction.response.send_message(
            "Cooldown role not found!", ephemeral=True
        )
        return

    # Save roles that can actually be removed (exclude @everyone & cooldown role)
    original_roles = [
        role for role in member.roles
        if role.id != guild.id and role.id != COOLDOWN_ROLE_ID and role < bot_member.top_role
    ]
    role_backup[member.id] = [r.id for r in original_roles]

    skipped_roles = [
        role.name for role in member.roles
        if role.id != guild.id and role.id != COOLDOWN_ROLE_ID and role >= bot_member.top_role
    ]

    # Remove manageable roles
    for r in original_roles:
        await member.remove_roles(r)

    # Add cooldown role if possible
    if cooldown_role < bot_member.top_role:
        await member.add_roles(cooldown_role)
    else:
        skipped_roles.append(cooldown_role.name)

    msg = f"{member.mention} has been put in cooldown for 1 hour."
    if skipped_roles:
        msg += f"\n⚠️ Could not modify roles: {', '.join(skipped_roles)}"
    await interaction.response.send_message(msg)

    # Wait 1 hour
    await asyncio.sleep(3600)

    # Restore roles
    if member.id in role_backup:
        restored_ids = role_backup.pop(member.id)
        restored_roles = [
            guild.get_role(rid) for rid in restored_ids if guild.get_role(rid) and guild.get_role(rid) < bot_member.top_role
        ]

        # Remove cooldown role safely
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

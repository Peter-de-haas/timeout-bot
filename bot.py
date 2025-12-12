import discord
from discord.ext import commands
import asyncio
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--token", required=True)
parser.add_argument("--cooldown-channel", required=True)
parser.add_argument("--cooldown-role", required=True)
args = parser.parse_args()

TOKEN = args.token
COOLDOWN_CHANNEL_ID = int(args.cooldown_channel)
COOLDOWN_ROLE_ID = int(args.cooldown_role)

intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Store original roles per user
role_backup = {}


@bot.event
async def on_ready():
    print(f"Timeout bot online as {bot.user}")


@bot.command(name="timeout")
@commands.has_permissions(manage_roles=True)
async def timeout(ctx, member: discord.Member):

    guild = ctx.guild
    cooldown_role = guild.get_role(COOLDOWN_ROLE_ID)

    if cooldown_role is None:
        return await ctx.send("Cooldown role not found!")

    # Save user's current roles (except @everyone and cooldown role)
    original_roles = [
        role for role in member.roles
        if role != guild.default_role and role.id != COOLDOWN_ROLE_ID
    ]

    role_backup[member.id] = [r.id for r in original_roles]

    # Remove roles
    for r in original_roles:
        await member.remove_roles(r)

    # Add cooldown role
    await member.add_roles(cooldown_role)

    await ctx.send(f"{member.mention} has been placed in cooldown for **1 hour**.")

    # Wait 1 hour
    await asyncio.sleep(3600)

    # Restore roles if still in backup
    if member.id in role_backup:

        restored_ids = role_backup.pop(member.id)
        restored_roles = [guild.get_role(rid) for rid in restored_ids]

        await member.remove_roles(cooldown_role)

        for r in restored_roles:
            if r is not None:
                await member.add_roles(r)

        await ctx.send(f"{member.mention} has been released from cooldown.")


bot.run(TOKEN)

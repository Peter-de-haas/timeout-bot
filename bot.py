import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import re
import os
import json
import time

# ---- Load config from environment ----
TOKEN = os.getenv("DISCORD_TOKEN")
COOLDOWN_ROLE_ID = int(os.getenv("COOLDOWN_ROLE_ID"))
TIMEOUT_FILE = "timeouts.json"

if not TOKEN or not COOLDOWN_ROLE_ID:
    raise RuntimeError("Missing DISCORD_TOKEN or COOLDOWN_ROLE_ID")

# ---- Intents ----
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ---- In-memory state ----
role_backup = {}       # member.id -> list of role IDs
cooldown_tasks = {}    # member.id -> asyncio.Task

# ---- Load timeouts from disk ----
if os.path.exists(TIMEOUT_FILE):
    try:
        with open(TIMEOUT_FILE, "r") as f:
            saved = json.load(f)
            for member_id, data in saved.items():
                role_backup[int(member_id)] = data["roles"]
                # We'll schedule tasks on bot startup below
    except Exception as e:
        print(f"Error loading {TIMEOUT_FILE}: {e}")

# ---- Save timeouts to disk ----
def save_timeouts():
    data = {
        str(member_id): {
            "roles": roles,
            "end_time": int(end_time)
        }
        for member_id, (roles, end_time) in persisted_timeouts.items()
    }
    with open(TIMEOUT_FILE, "w") as f:
        json.dump(data, f)

# We'll store in-memory both roles and end timestamps
persisted_timeouts = {}  # member.id -> (list of role ids, end timestamp)

# ---- Duration parser ----
def parse_duration(tijd: str) -> int:
    match = re.fullmatch(r"(\d+)([mh]?)", tijd.lower())
    if not match:
        return 15 * 60
    value, unit = match.groups()
    value = int(value)
    return value * 60 if unit == "m" else value * 3600

# ---- Helper to end kleurplaat ----
async def end_kleur(member: discord.Member, guild: discord.Guild, cooldown_role: discord.Role, early=False):
    cooldown_tasks.pop(member.id, None)
    persisted_timeouts.pop(member.id, None)
    save_timeouts()

    restored_roles = []
    if member.id in role_backup:
        restored_ids = role_backup.pop(member.id)
        for rid in restored_ids:
            role = guild.get_role(rid)
            if role and role < guild.me.top_role:
                restored_roles.append(role)

    if cooldown_role < guild.me.top_role:
        try:
            await member.remove_roles(cooldown_role)
        except discord.Forbidden:
            pass

    if restored_roles:
        try:
            await member.add_roles(*restored_roles)
        except discord.Forbidden:
            pass

    try:
        if early:
            await member.send("🖍️ Jouw Kleur tijd is vervroegd afgelopen.")
        else:
            await member.send("🖍️ Jouw Kleur tijd is afgelopen.")
    except:
        pass

# ---- /kleurplaat command ----
@tree.command(name="kleurplaat", description="Ik wil naar de kleurhoek.")
@app_commands.describe(
    tijd="Tijd om te kleuren (bijv. 10m, 1h). Standaard 15m."
)
async def kleurplaat(interaction: discord.Interaction, tijd: str = "15m"):
    if interaction.guild is None:
        await interaction.response.send_message("Dit commando kan alleen in een server gebruikt worden.", ephemeral=True)
        return

    member = interaction.user
    guild = interaction.guild
    bot_member = guild.me
    cooldown_role = guild.get_role(COOLDOWN_ROLE_ID)
    if cooldown_role is None:
        await interaction.response.send_message("Kleurplaat rol niet gevonden.", ephemeral=True)
        return

    if cooldown_role in member.roles:
        await interaction.response.send_message("Je bent al aan het kleuren.", ephemeral=True)
        return

    seconds = parse_duration(tijd)
    end_time = time.time() + seconds

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
    persisted_timeouts[member.id] = ([r.id for r in removable_roles], end_time)
    save_timeouts()

    if removable_roles:
        try:
            await member.remove_roles(*removable_roles)
        except discord.Forbidden:
            skipped_roles.extend([r.name for r in removable_roles])

    if cooldown_role < bot_member.top_role:
        try:
            await member.add_roles(cooldown_role)
        except discord.Forbidden:
            skipped_roles.append(cooldown_role.name)
    else:
        skipped_roles.append(cooldown_role.name)

    msg = f"🖍️ Je bent aan het kleuren voor {seconds // 60} minuten."
    if skipped_roles:
        msg += f"\n⚠ Kon deze rollen niet aanpassen: {', '.join(skipped_roles)}"

    await interaction.response.send_message(msg)

    # Schedule ending
    async def task_wrapper():
        remaining = end_time - time.time()
        if remaining > 0:
            try:
                await asyncio.sleep(remaining)
            except asyncio.CancelledError:
                return
        await end_kleur(member, guild, cooldown_role)

    cooldown_tasks[member.id] = asyncio.create_task(task_wrapper())

# ---- /klaar command ----
@tree.command(name="klaar", description="Ik wil stoppen met kleuren.")
async def klaar(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message("Dit commando kan alleen in een server gebruikt worden.", ephemeral=True)
        return

    member = interaction.user
    guild = interaction.guild
    cooldown_role = guild.get_role(COOLDOWN_ROLE_ID)

    if cooldown_role not in member.roles:
        await interaction.response.send_message("Je bent helemaal niet aan het kleuren.", ephemeral=True)
        return

    task = cooldown_tasks.pop(member.id, None)
    if task:
        task.cancel()
    await end_kleur(member, guild, cooldown_role, early=True)
    await interaction.response.send_message("🖍️ Jouw Kleur tijd is vervroegd afgelopen.")

# ---- Bot Ready ----
@bot.event
async def on_ready():
    print(f"Timeout bot online als {bot.user}")
    await tree.sync()
    print("Slash commands synced.")

    # Restore persisted timeouts
    for member_id_str, (roles, end_time) in [(str(k), v) for k, v in persisted_timeouts.items()]:
        member_id = int(member_id_str)
        member = discord.utils.get(bot.get_all_members(), id=member_id)
        if not member:
            continue
        guild = member.guild
        cooldown_role = guild.get_role(COOLDOWN_ROLE_ID)
        if not cooldown_role:
            continue

        remaining = end_time - time.time()
        if remaining <= 0:
            asyncio.create_task(end_kleur(member, guild, cooldown_role))
        else:
            async def task_wrapper(member=member, guild=guild, cooldown_role=cooldown_role, remaining=remaining):
                try:
                    await asyncio.sleep(remaining)
                except asyncio.CancelledError:
                    return
                await end_kleur(member, guild, cooldown_role)
            cooldown_tasks[member_id] = asyncio.create_task(task_wrapper())

# ---- Run ----
bot.run(TOKEN)

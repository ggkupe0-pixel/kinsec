import discord
from discord.ext import commands, tasks
import time
import datetime
import asyncio
from collections import defaultdict
import os  # Needed to read environment variables from Railway

# --- CONFIGURATION ---
# Railway securely handles this variable. Do not hardcode your token here!
BOT_TOKEN = os.getenv("BOT_TOKEN") 
LOG_CHANNEL_ID = 1508413816914837624  
BYPASS_ROLE_ID = 1468249091481010197  
WHITELISTED_USERS = [1394753272492851322, 1429477060577067019]

if not BOT_TOKEN:
    print("Error: BOT_TOKEN environment variable not found.")
    exit(1)

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.members = True
intents.guilds = True
intents.moderation = True
intents.voice_states = True 

bot = commands.Bot(command_prefix="kin.", intents=intents)

# --- LOCAL MEMORY STORAGE ---
kick_tracker = defaultdict(list)
ban_tracker = defaultdict(list)
spam_tracker = defaultdict(list)
poll_tracker = defaultdict(list)
thread_tracker = defaultdict(list)
join_history = []
leave_history = []

# --- HELPERS ---
def is_whitelisted(guild, user):
    if user.id in WHITELISTED_USERS:
        return True
    member = guild.get_member(user.id)
    if member and any(r.id == BYPASS_ROLE_ID for r in member.roles):
        return True
    return False

def check_rate_limit(user_id, tracker, limit, window):
    now = time.time()
    tracker[user_id] = [t for t in tracker[user_id] if now - t <= window]
    tracker[user_id].append(now)
    return len(tracker[user_id]) >= limit

async def send_mod_log(guild, action, actor, target, details):
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    if not log_channel: return
    
    embed = discord.Embed(title=f"Security Trigger: {action}", description=details, color=0x2B2D31, timestamp=discord.utils.utcnow())
    embed.add_field(name="Triggered By", value=f"{actor.mention}\nID: `{actor.id}`", inline=True)
    embed.add_field(name="Target", value=target, inline=True)
    embed.add_field(name="Time Occurred", value=f"<t:{int(time.time())}:F>\n(<t:{int(time.time())}:R>)", inline=False)
    embed.set_footer(text="Automated Security System")
    
    try: await log_channel.send(embed=embed)
    except discord.HTTPException: pass

# --- RICH PRESENCE LOOP ---
@tasks.loop(seconds=15)
async def presence_loop():
    members = sum(g.member_count for g in bot.guilds)
    vcs = sum(len(g.voice_channels) for g in bot.guilds)
    
    activities = [
        discord.Streaming(name="/rougekin", url="https://www.twitch.tv/discord"),
        discord.Activity(type=discord.ActivityType.watching, name=f"{vcs} vc{'s' if vcs != 1 else ''}"),
        discord.Activity(type=discord.ActivityType.watching, name=f"{members} members")
    ]
    
    presence_loop.idx = getattr(presence_loop, 'idx', 0)
    await bot.change_presence(activity=activities[presence_loop.idx])
    presence_loop.idx = (presence_loop.idx + 1) % len(activities)

@presence_loop.before_loop
async def before_presence_loop():
    await bot.wait_until_ready()

# --- SERVER SCAN EVENTS ---
@bot.event
async def on_member_join(member):
    join_history.append(datetime.datetime.now(datetime.timezone.utc))

@bot.event
async def on_member_remove(member):
    leave_history.append(datetime.datetime.now(datetime.timezone.utc))

# --- COMMANDS ---
@bot.command(name="scan")
async def scan(ctx):
    today = datetime.datetime.now(datetime.timezone.utc).date()
    joins = len([t for t in join_history if t.date() == today])
    leaves = len([t for t in leave_history if t.date() == today])
    
    embed = discord.Embed(title="Server Daily Scan", color=0x2B2D31)
    embed.add_field(name="Users who joined today", value=str(joins), inline=False)
    embed.add_field(name="Users who left today", value=str(leaves), inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name="kill")
@commands.has_permissions(ban_members=True)
async def kill(ctx, target: discord.User):
    target_member = ctx.guild.get_member(target.id)
    if target_member:
        if ctx.author.top_role.position <= target_member.top_role.position:
            await ctx.send("ur too under lmfao")
            return
    try:
        await ctx.guild.ban(target, reason="Hardban: Security Kill Command")
        await ctx.send(f"{target.mention} died.")
    except Exception as e:
        await ctx.send(f"Failed to kill: {e}")

@kill.error
async def kill_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("u dont have permission fag")

# --- ANTI-SPAM (THREADS) ---
@bot.event
async def on_thread_create(thread: discord.Thread):
    guild = thread.guild
    owner = thread.owner
    if not owner or owner.bot or is_whitelisted(guild, owner): return

    uid = owner.id
    if check_rate_limit(uid, thread_tracker, limit=3, window=5):
        thread_tracker[uid].clear()
        try:
            await asyncio.gather(
                thread.delete(),
                owner.timeout(datetime.timedelta(minutes=1), reason="Mass Thread Spam"),
                thread.parent.send(f"stfu {owner.mention}.")
            )
        except discord.HTTPException: pass

# --- ANTI-SPAM (TEXT & POLLS) ---
@bot.event
async def on_message(message: discord.Message):
    if not message.guild or message.author.bot or is_whitelisted(message.guild, message.author):
        await bot.process_commands(message)
        return

    uid = message.author.id

    if getattr(message, 'poll', None):
        if check_rate_limit(uid, poll_tracker, limit=3, window=5):
            poll_tracker[uid].clear()
            try:
                await asyncio.gather(
                    message.channel.purge(limit=10, check=lambda m: getattr(m, 'poll', None) and m.author == message.author),
                    message.author.timeout(datetime.timedelta(minutes=1), reason="Mass Poll Spam"),
                    message.channel.send(f"stfu {message.author.mention}.")
                )
            except discord.HTTPException: pass
            return

    if check_rate_limit(uid, spam_tracker, limit=5, window=5):
        spam_tracker[uid].clear()
        try:
            await asyncio.gather(
                message.channel.purge(limit=10, check=lambda m: m.author == message.author),
                message.author.timeout(datetime.timedelta(minutes=1), reason="Mass Spam Execution"),
                message.channel.send(f"stfu {message.author.mention}.")
            )
        except discord.HTTPException: pass
        return 

    await bot.process_commands(message)

# --- ANTI-NUKE & ANTI-BOT (AUDIT LOGS) ---
@bot.event
async def on_audit_log_entry_create(entry: discord.AuditLogEntry):
    guild = entry.guild
    actor = entry.user
    if actor.id == bot.user.id or is_whitelisted(guild, actor): return

    if entry.action == discord.AuditLogAction.kick:
        if check_rate_limit(actor.id, kick_tracker, limit=5, window=5):
            await guild.ban(actor, reason="Security: Mass Kick")

    elif entry.action == discord.AuditLogAction.ban:
        if check_rate_limit(actor.id, ban_tracker, limit=3, window=5):
            await guild.ban(actor, reason="Security: Mass Ban")

    elif entry.action == discord.AuditLogAction.bot_add:
        unauthorized_bot = entry.target
        if unauthorized_bot and getattr(unauthorized_bot, 'bot', False):
            try: await actor.send("you are not slick.")
            except discord.HTTPException: pass
            try:
                await asyncio.gather(
                    guild.ban(actor, reason="Security Protocol: Added Unauthorized Bot"),
                    guild.kick(unauthorized_bot, reason="Security Protocol: Unauthorized Bot")
                )
                await send_mod_log(guild, "Unauthorized Bot", actor, f"<@{unauthorized_bot.id}>", "Banned inviter and kicked bot.")
            except discord.HTTPException: pass

    elif entry.action == discord.AuditLogAction.member_role_update:
        if hasattr(entry.after, 'roles') and entry.target:
            for role in entry.after.roles:
                if role.permissions.administrator:
                    target_member = guild.get_member(entry.target.id)
                    if target_member:
                        try:
                            await asyncio.gather(
                                target_member.remove_roles(role, reason="Illegal Admin Assignment"),
                                guild.ban(actor, reason="Unauthorized Admin Role Lending")
                            )
                        except discord.HTTPException: pass

    elif entry.action == discord.AuditLogAction.role_update:
        if hasattr(entry.after, 'permissions') and entry.target:
            if entry.after.permissions.administrator and not entry.before.permissions.administrator:
                role = guild.get_role(entry.target.id)
                if role:
                    try:
                        await asyncio.gather(
                            role.edit(permissions=entry.before.permissions, reason="Illegal Admin Injection"),
                            guild.ban(actor, reason="Unauthorized Admin Permission Injection")
                        )
                    except discord.HTTPException: pass

    elif entry.action in (discord.AuditLogAction.channel_delete, discord.AuditLogAction.role_delete):
        try: await guild.ban(actor, reason="Anti Nuke: Structural Destruction Protection")
        except discord.HTTPException: pass

@bot.event
async def on_ready():
    print(f"Kinsec Active. Logged in as: {bot.user}")
    if not presence_loop.is_running():
        presence_loop.start()

bot.run(BOT_TOKEN)

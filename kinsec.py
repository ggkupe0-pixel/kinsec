import time
import datetime
import asyncio
from collections import defaultdict
import os
import random
import discord
from discord.ext import commands, tasks

# --- CONFIGURATION ---
BOT_TOKEN = os.getenv("BOT_TOKEN") 
LOG_CHANNEL_ID = 1508413816914837624       # Main channel for security & mod logs
DM_LOG_CHANNEL_ID = 1501262044127690913     # REPLACE THIS with your new DM logs channel ID
BYPASS_ROLE_ID = 1468249091481010197  
WHITELISTED_USERS = [1394753272492851322, 1429477060577067019]

if not BOT_TOKEN:
    print("Error: BOT_TOKEN environment variable is missing in Railway.")
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
def is_whitelisted(guild: discord.Guild, user: discord.abc.User) -> bool:
    if user.id in WHITELISTED_USERS:
        return True
    if guild:
        member = guild.get_member(user.id)
        if member and any(role.id == BYPASS_ROLE_ID for role in member.roles):
            return True
    return False

def check_rate_limit(user_id: int, tracker: dict, limit: int, window: int = 5) -> bool:
    now = time.time()
    tracker[user_id] = [t for t in tracker[user_id] if now - t <= window]
    tracker[user_id].append(now)
    return len(tracker[user_id]) >= limit

async def send_mod_log(guild: discord.Guild, action: str, actor: discord.abc.User, target: str, details: str):
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    if not log_channel:
        return

    embed = discord.Embed(
        title=f"Security Trigger: {action}",
        description=details,
        color=0x2B2D31,
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="Triggered By", value=f"{actor.mention}\nID: `{actor.id}`", inline=True)
    embed.add_field(name="Target", value=target, inline=True)
    
    current_time = int(time.time())
    embed.add_field(name="Time Occurred", value=f"<t:{current_time}:F>\n(<t:{current_time}:R>)", inline=False)
    embed.set_footer(text="Automated Security System")
    
    try:
        await log_channel.send(embed=embed)
    except discord.HTTPException:
        pass

# --- RICH PRESENCE LOOP ---
@tasks.loop(seconds=15)
async def presence_loop():
    members = sum(g.member_count for g in bot.guilds)
    vc_members = sum(len(vc.members) for g in bot.guilds for vc in g.voice_channels)
    
    activities = [
        discord.Streaming(name="/rougekin", url="https://www.twitch.tv/discord"),
        discord.Activity(type=discord.ActivityType.watching, name=f"{vc_members} in vc"),
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
        # Hierarchy check
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

@bot.command(name="call")
async def call(ctx, target: discord.User, *, message: str):
    # Strict whitelist check
    if ctx.author.id not in WHITELISTED_USERS:
        await ctx.send("u dont have permission fag")
        return

    delivered = False
    delivery_status_details = "Message delivered successfully."

    try:
        await target.send(message)
        delivered = True
    except discord.Forbidden:
        delivery_status_details = "Failed: User has DMs disabled or has blocked the bot."
    except discord.HTTPException as e:
        delivery_status_details = f"Failed: Network or API error ({e})"

    embed = discord.Embed(
        title="Direct Message Execution Log",
        description="A direct message command was triggered and processed.",
        color=0x2B2D31,
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="Target User", value=f"{target.mention} ({target.name})", inline=True)
    embed.add_field(name="Target ID", value=f"`{target.id}`", inline=True)
    embed.add_field(name="Executed By", value=f"{ctx.author.mention} (`{ctx.author.id}`)", inline=False)
    
    embed.add_field(name="Delivery Status", value="DELIVERED" if delivered else "FAILED", inline=True)
    embed.add_field(name="Delivery Details", value=delivery_status_details, inline=True)
    
    embed.add_field(name="Message Payload", value=f"
http://googleusercontent.com/immersive_entry_chip/0



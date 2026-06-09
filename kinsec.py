import time
import datetime
import asyncio
from collections import defaultdict
import os
import discord
from discord.ext import commands, tasks

# --- CONFIGURATION ---
BOT_TOKEN = os.getenv("BOT_TOKEN")

LOG_CHANNEL_ID = 1508413816914837624
DM_LOG_CHANNEL_ID = 1501262044127690913  # replace with your DM logs channel ID

BYPASS_ROLE_ID = 1468249091481010197

WHITELISTED_USERS = [
    1394753272492851322,
    1429477060577067019
]

if not BOT_TOKEN:
    print("Error: BOT_TOKEN environment variable is missing.")
    exit(1)

# --- INTENTS ---
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.members = True
intents.guilds = True
intents.moderation = True
intents.voice_states = True

bot = commands.Bot(command_prefix="kin.", intents=intents)

# --- MEMORY STORAGE ---
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

    tracker[user_id] = [
        t for t in tracker[user_id]
        if now - t <= window
    ]

    tracker[user_id].append(now)

    return len(tracker[user_id]) >= limit


async def send_mod_log(
    guild: discord.Guild,
    action: str,
    actor: discord.abc.User,
    target: str,
    details: str
):
    log_channel = guild.get_channel(LOG_CHANNEL_ID)

    if not log_channel:
        return

    embed = discord.Embed(
        title=f"Security Trigger: {action}",
        description=details,
        color=0x2B2D31,
        timestamp=discord.utils.utcnow()
    )

    embed.add_field(
        name="Triggered By",
        value=f"{actor.mention}\nID: `{actor.id}`",
        inline=True
    )

    embed.add_field(
        name="Target",
        value=target,
        inline=True
    )

    current_time = int(time.time())

    embed.add_field(
        name="Time Occurred",
        value=f"<t:{current_time}:F>\n(<t:{current_time}:R>)",
        inline=False
    )

    embed.set_footer(text="Automated Security System")

    try:
        await log_channel.send(embed=embed)
    except discord.HTTPException:
        pass


# --- RICH PRESENCE LOOP ---
@tasks.loop(seconds=15)
async def presence_loop():
    members = sum(g.member_count for g in bot.guilds)

    vc_members = sum(
        len(vc.members)
        for g in bot.guilds
        for vc in g.voice_channels
    )

    activities = [
        discord.Streaming(
            name="/rougekin",
            url="https://www.twitch.tv/discord"
        ),

        discord.Activity(
            type=discord.ActivityType.watching,
            name=f"{vc_members} in vc"
        ),

        discord.Activity(
            type=discord.ActivityType.watching,
            name=f"{members} members"
        )
    ]

    presence_loop.idx = getattr(presence_loop, "idx", 0)

    await bot.change_presence(
        activity=activities[presence_loop.idx]
    )

    presence_loop.idx = (
        presence_loop.idx + 1
    ) % len(activities)


@presence_loop.before_loop
async def before_presence_loop():
    await bot.wait_until_ready()


# --- MEMBER EVENTS ---
@bot.event
async def on_member_join(member):
    join_history.append(
        datetime.datetime.now(datetime.timezone.utc)
    )


@bot.event
async def on_member_remove(member):
    leave_history.append(
        datetime.datetime.now(datetime.timezone.utc)
    )


# --- ANTI LEND ADMIN EVENTS ---
@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    # Check if the member gained administrator permission
    before_admin = any(role.permissions.administrator for role in before.roles)
    after_admin = any(role.permissions.administrator for role in after.roles)

    if not before_admin and after_admin:
        guild = after.guild
        actor = None

        # Fetch Audit Logs to find the culprit
        try:
            async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.member_role_update):
                if entry.target.id == after.id:
                    actor = entry.user
                    break
        except discord.HTTPException:
            pass

        # If it was an unauthorized user handing out admin
        if actor and actor.id != bot.user.id and not is_whitelisted(guild, actor):
            try:
                # Strip newly added admin roles
                admin_roles_added = [
                    role for role in after.roles 
                    if role.permissions.administrator and role not in before.roles
                ]
                await after.remove_roles(*admin_roles_added, reason="Security: Anti Lend Admin")
                
                # Ban the rogue actor
                await guild.ban(actor, reason="Security: Anti Lend Admin (Unauthorized Assignment)")
                
                await send_mod_log(
                    guild,
                    "Anti Lend Admin (Role Assigned)",
                    actor,
                    after.mention,
                    "Unauthorized user attempted to give Administrator permissions to a member."
                )
            except discord.HTTPException:
                pass


@bot.event
async def on_guild_role_update(before: discord.Role, after: discord.Role):
    # Check if a role was edited to have administrator permission
    if not before.permissions.administrator and after.permissions.administrator:
        guild = after.guild
        actor = None

        # Fetch Audit Logs to find the culprit
        try:
            async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.role_update):
                if entry.target.id == after.id:
                    actor = entry.user
                    break
        except discord.HTTPException:
            pass

        # If it was an unauthorized user modifying role perms
        if actor and actor.id != bot.user.id and not is_whitelisted(guild, actor):
            try:
                # Revert permissions
                await after.edit(permissions=before.permissions, reason="Security: Anti Lend Admin Revert")
                
                # Ban the rogue actor
                await guild.ban(actor, reason="Security: Anti Lend Admin (Unauthorized Role Edit)")
                
                await send_mod_log(
                    guild,
                    "Anti Lend Admin (Role Edit)",
                    actor,
                    f"Role: {after.name}",
                    "Unauthorized user attempted to add Administrator permissions to a role."
                )
            except discord.HTTPException:
                pass


# --- COMMANDS ---
@bot.command(name="scan")
async def scan(ctx):
    today = datetime.datetime.now(
        datetime.timezone.utc
    ).date()

    joins = len([
        t for t in join_history
        if t.date() == today
    ])

    leaves = len([
        t for t in leave_history
        if t.date() == today
    ])

    embed = discord.Embed(
        title="Server Daily Scan",
        color=0x2B2D31
    )

    embed.add_field(
        name="Users joined today",
        value=str(joins),
        inline=False
    )

    embed.add_field(
        name="Users left today",
        value=str(leaves),
        inline=False
    )

    await ctx.send(embed=embed)


@bot.command(name="kill")
@commands.has_permissions(ban_members=True)
async def kill(ctx, target: discord.User):
    target_member = ctx.guild.get_member(target.id)

    if target_member:
        if ctx.author.top_role.position <= target_member.top_role.position:
            await ctx.send("You are below this member in role hierarchy.")
            return

    try:
        await ctx.guild.ban(
            target,
            reason="Hardban: Security Kill Command"
        )
        await ctx.send(f"{target.mention} has been banned.")
    except Exception as e:
        await ctx.send(f"Failed to ban user: {e}")


@kill.error
async def kill_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You do not have permission.")


# --- CALL COMMAND ---
@bot.command(name="call")
async def call(ctx, target: discord.User, *, message: str):
    if ctx.author.id not in WHITELISTED_USERS:
        await ctx.send("You do not have permission.")
        return

    delivered = False
    delivery_status_details = "Message delivered successfully."

    try:
        await target.send(message)
        delivered = True
    except discord.Forbidden:
        delivery_status_details = "Failed: User has DMs disabled or blocked the bot."
    except discord.HTTPException as e:
        delivery_status_details = f"Failed: API error ({e})"

    embed = discord.Embed(
        title="Direct Message Execution Log",
        description="A direct message command was triggered.",
        color=0x2B2D31,
        timestamp=discord.utils.utcnow()
    )

    embed.add_field(name="Target User", value=f"{target.mention} ({target.name})", inline=True)
    embed.add_field(name="Target ID", value=f"`{target.id}`", inline=True)
    embed.add_field(name="Executed By", value=f"{ctx.author.mention} (`{ctx.author.id}`)", inline=False)
    embed.add_field(name="Delivery Status", value="DELIVERED" if delivered else "FAILED", inline=True)
    embed.add_field(name="Delivery Details", value=delivery_status_details, inline=True)
    embed.add_field(name="Message Payload", value=f"```\n{message[:1000]}\n```",
    inline=False)
    embed.set_footer(text="Kinsec Security Core")

    log_channel = ctx.guild.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        await log_channel.send(embed=embed)

    await ctx.send(f"Process complete. Delivery status: **{'DELIVERED' if delivered else 'FAILED'}**.")


@call.error
async def call_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("Syntax: kin.call [user] [message]")


# --- DM ALL ---
@bot.command(name="dmall")
async def dmall(ctx, *, message_text: str):
    if ctx.author.id not in WHITELISTED_USERS:
        await ctx.send("You do not have permission.")
        return

    status_msg = await ctx.send("Initiating Mass DM broadcast...")

    success_count = 0
    fail_count = 0

    targets = [member for member in ctx.guild.members if not member.bot]
    total_targets = len(targets)

    for index, member in enumerate(targets):
        try:
            await member.send(message_text)
            success_count += 1
        except (discord.Forbidden, discord.HTTPException):
            fail_count += 1

        if (index + 1) % 5 == 0 or (index + 1) == total_targets:
            try:
                await status_msg.edit(
                    content=(
                        f"Broadcasting: {index + 1}/{total_targets}\n"
                        f"Sent: {success_count}\n"
                        f"Failed: {fail_count}"
                    )
                )
            except discord.HTTPException:
                pass

        if (index + 1) < total_targets:
            await asyncio.sleep(4)

    await ctx.send(f"Mass DM complete.\nSent: {success_count}\nFailed: {fail_count}")
    await send_mod_log(
        ctx.guild,
        "Mass DM Broadcast Executed",
        ctx.author,
        f"{success_count} Members",
        f"Sent message: '{message_text[:100]}...'"
    )


# --- MESSAGE EVENT ---
@bot.event
async def on_message(message: discord.Message):
    # DM LOGGER
    if message.guild is None:
        if message.author.bot:
            return

        log_channel = bot.get_channel(DM_LOG_CHANNEL_ID)
        if log_channel:
            embed = discord.Embed(
                title="Incoming Private DM Log",
                description=message.content if message.content else "[Attachment / No text]",
                color=0x2B2D31,
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="Sender", value=f"{message.author.mention}\n`{message.author}`", inline=True)
            embed.add_field(name="Sender ID", value=f"`{message.author.id}`", inline=True)
            embed.set_footer(text="Kinsec Privacy Core")

            try:
                await log_channel.send(embed=embed)
            except discord.HTTPException:
                pass
        return

    # IGNORE BOTS / WHITELIST
    if message.author.bot or is_whitelisted(message.guild, message.author):
        await bot.process_commands(message)
        return

    uid = message.author.id

    # POLL SPAM
    if getattr(message, "poll", None):
        if check_rate_limit(uid, poll_tracker, limit=3, window=5):
            poll_tracker[uid].clear()
            try:
                await asyncio.gather(
                    message.channel.purge(
                        limit=10,
                        check=lambda m: getattr(m, "poll", None) and m.author == message.author
                    ),
                    message.author.timeout(datetime.timedelta(minutes=1), reason="Mass Poll Spam"),
                    message.channel.send(f"stfu {message.author.mention}.")
                )
                await send_mod_log(
                    message.guild,
                    "Mass Poll Spam Muted",
                    message.author,
                    message.channel.mention,
                    "Polls purged and user timed out."
                )
            except discord.HTTPException:
                pass
        return

    # TEXT SPAM
    if check_rate_limit(uid, spam_tracker, limit=5, window=5):
        spam_tracker[uid].clear()
        try:
            await asyncio.gather(
                message.channel.purge(limit=10, check=lambda m: m.author == message.author),
                message.author.timeout(datetime.timedelta(minutes=1), reason="Mass Spam"),
                message.channel.send(f"stfu {message.author.mention}.")
            )
            await send_mod_log(
                message.guild,
                "Mass Spam Muted",
                message.author,
                message.channel.mention,
                "Messages purged and user timed out."
            )
        except discord.HTTPException:
            pass
        return

    await bot.process_commands(message)


# --- THREAD SPAM ---
@bot.event
async def on_thread_create(thread: discord.Thread):
    guild = thread.guild
    owner = thread.owner

    if not owner or owner.bot or is_whitelisted(guild, owner):
        return

    uid = owner.id

    if check_rate_limit(uid, thread_tracker, limit=3, window=5):
        thread_tracker[uid].clear()
        try:
            await asyncio.gather(
                thread.delete(),
                owner.timeout(datetime.timedelta(minutes=1), reason="Mass Thread Spam"),
                thread.parent.send(f"stfu {owner.mention}.")
            )
            await send_mod_log(
                guild,
                "Mass Thread Spam Halted",
                owner,
                "Multiple Threads",
                "User exceeded thread limits."
            )
        except discord.HTTPException:
            pass


# --- AUDIT LOG EVENTS ---
@bot.event
async def on_audit_log_entry_create(entry: discord.AuditLogEntry):
    guild = entry.guild
    actor = entry.user

    if not bot.user or actor.id == bot.user.id or is_whitelisted(guild, actor):
        return

    # MASS KICK
    if entry.action == discord.AuditLogAction.kick:
        if check_rate_limit(actor.id, kick_tracker, limit=5, window=5):
            await guild.ban(actor, reason="Security: Mass Kick")

    # MASS BAN
    elif entry.action == discord.AuditLogAction.ban:
        if check_rate_limit(actor.id, ban_tracker, limit=3, window=5):
            await guild.ban(actor, reason="Security: Mass Ban")

    # BOT ADD
    elif entry.action == discord.AuditLogAction.bot_add:
        unauthorized_bot = entry.target
        if unauthorized_bot and getattr(unauthorized_bot, "bot", False):
            try:
                await actor.send("you are not slick.")
            except discord.HTTPException:
                pass
            try:
                await asyncio.gather(
                    guild.ban(actor, reason="Unauthorized Bot Added"),
                    guild.kick(unauthorized_bot, reason="Unauthorized Bot")
                )
                await send_mod_log(
                    guild,
                    "Unauthorized Bot",
                    actor,
                    f"<@{unauthorized_bot.id}>",
                    "Banned inviter and kicked bot."
                )
            except discord.HTTPException:
                pass

    # CHANNEL / ROLE DELETE
    elif entry.action in (discord.AuditLogAction.channel_delete, discord.AuditLogAction.role_delete):
        try:
            await guild.ban(actor, reason="Anti-Nuke Protection")
        except discord.HTTPException:
            pass


# --- READY EVENT ---
@bot.event
async def on_ready():
    print(f"Kinsec Active. Logged in as: {bot.user}")
    if not presence_loop.is_running():
        presence_loop.start()


# --- START BOT ---
bot.run(BOT_TOKEN)


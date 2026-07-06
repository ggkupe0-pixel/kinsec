import time
import datetime
import asyncio
from collections import defaultdict
from typing import Optional, Dict, List
import os
import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiohttp
import json
import re
import base64

# --- CONFIGURATION ---
BOT_TOKEN = os.getenv("BOT_TOKEN")

LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0"))
DM_LOG_CHANNEL_ID = int(os.getenv("DM_LOG_CHANNEL_ID", "0"))

BYPASS_ROLE_ID = int(os.getenv("BYPASS_ROLE_ID", "0"))

WHITELISTED_USERS = [
    1394753272492851322,
    1429477060577067019
]

# Rate limiting constants
SPAM_LIMIT = 5
SPAM_WINDOW = 5
POLL_LIMIT = 3
POLL_WINDOW = 5
THREAD_LIMIT = 3
THREAD_WINDOW = 5
KICK_LIMIT = 5
KICK_WINDOW = 5
BAN_LIMIT = 3
BAN_WINDOW = 5
ROLE_DELETE_LIMIT = 3
ROLE_DELETE_WINDOW = 5
CHANNEL_DELETE_LIMIT = 3
CHANNEL_DELETE_WINDOW = 5

# Railway specific config
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

bot = commands.Bot(command_prefix="k.", intents=intents)

# --- MEMORY STORAGE ---
kick_tracker: Dict[int, List[float]] = defaultdict(list)
ban_tracker: Dict[int, List[float]] = defaultdict(list)
spam_tracker: Dict[int, List[float]] = defaultdict(list)
poll_tracker: Dict[int, List[float]] = defaultdict(list)
thread_tracker: Dict[int, List[float]] = defaultdict(list)
role_delete_tracker: Dict[int, List[float]] = defaultdict(list)
channel_delete_tracker: Dict[int, List[float]] = defaultdict(list)

join_history: List[datetime.datetime] = []
leave_history: List[datetime.datetime] = []

recently_deleted_roles: Dict[int, List[discord.Role]] = defaultdict(list)
recently_deleted_channels: Dict[int, List[discord.abc.GuildChannel]] = defaultdict(list)

# --- HELPERS ---
def is_whitelisted(guild: Optional[discord.Guild], user: discord.abc.User) -> bool:
    if user.id in WHITELISTED_USERS:
        return True

    if guild and BYPASS_ROLE_ID != 0:
        member = guild.get_member(user.id)
        if member and any(role.id == BYPASS_ROLE_ID for role in member.roles):
            return True

    return False


def check_rate_limit(
    user_id: int, 
    tracker: Dict[int, List[float]], 
    limit: int, 
    window: int = 5
) -> bool:
    now = time.time()
    
    tracker[user_id] = [
        t for t in tracker[user_id]
        if now - t <= window
    ]
    
    tracker[user_id].append(now)
    
    return len(tracker[user_id]) >= limit


def create_embed(
    title: str,
    description: str,
    color: int = 0x2B2D31,
    fields: Optional[List[tuple]] = None,
    thumbnail: Optional[str] = None,
    image: Optional[str] = None,
    footer: str = "Kinsec Security System • mi luv /rk"
) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=discord.utils.utcnow()
    )
    
    if fields:
        for name, value, inline in fields:
            embed.add_field(name=name, value=value, inline=inline)
    
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    
    if image:
        embed.set_image(url=image)
    
    embed.set_footer(text=footer)
    return embed


async def send_mod_log(
    guild: discord.Guild,
    action: str,
    actor: discord.abc.User,
    target: str,
    details: str
) -> None:
    if LOG_CHANNEL_ID == 0:
        return
        
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    
    if not log_channel:
        return
    
    current_time = int(time.time())
    fields = [
        ("Triggered By", f"{actor.mention}\nID: `{actor.id}`", True),
        ("Target", target, True),
        ("Time Occurred", f"<t:{current_time}:F>\n(<t:{current_time}:R>)", False)
    ]
    
    embed = create_embed(
        f"Security Trigger: {action}",
        details,
        fields=fields
    )
    
    try:
        await log_channel.send(embed=embed)
    except discord.HTTPException:
        pass


async def timeout_user(
    member: discord.Member,
    duration: int = 1,
    reason: str = "Rate limit exceeded"
) -> None:
    try:
        await member.timeout(
            datetime.timedelta(minutes=duration),
            reason=reason
        )
    except discord.HTTPException:
        pass


async def safe_ban(
    guild: discord.Guild,
    user: discord.abc.User,
    reason: str,
    delete_message_days: int = 0
) -> bool:
    try:
        await guild.ban(user, reason=reason, delete_message_days=delete_message_days)
        return True
    except discord.HTTPException:
        return False


async def get_audit_log_actor(
    guild: discord.Guild,
    action: discord.AuditLogAction,
    target_id: Optional[int] = None,
    limit: int = 5
) -> Optional[discord.User]:
    try:
        async for entry in guild.audit_logs(limit=limit, action=action):
            if target_id is None or entry.target.id == target_id:
                return entry.user
    except discord.HTTPException:
        pass
    return None


def format_number(num: int) -> str:
    """Format large numbers with K, M, B suffixes."""
    if num >= 1000000000:
        return f"{num/1000000000:.1f}B"
    elif num >= 1000000:
        return f"{num/1000000:.1f}M"
    elif num >= 1000:
        return f"{num/1000:.1f}K"
    else:
        return str(num)


# --- SOCIAL MEDIA API FUNCTIONS (FIXED) ---

async def fetch_instagram_data(username: str):
    """Fetch Instagram profile data using rapidapi or public endpoints."""
    try:
        # Try using Instagram's public API with proper headers
        async with aiohttp.ClientSession() as session:
            url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'application/json',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Host': 'www.instagram.com',
                'Sec-Fetch-Dest': 'empty',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Site': 'same-origin',
                'X-IG-App-ID': '936619743392459',
                'X-ASBD-ID': '198387',
                'X-IG-WWW-Claim': '0'
            }
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data and 'data' in data and 'user' in data['data']:
                        user_data = data['data']['user']
                        return {
                            'followers': user_data.get('edge_followed_by', {}).get('count', 0),
                            'following': user_data.get('edge_follow', {}).get('count', 0),
                            'posts': user_data.get('edge_owner_to_timeline_media', {}).get('count', 0),
                            'name': user_data.get('full_name', ''),
                            'profile_pic': user_data.get('profile_pic_url_hd', user_data.get('profile_pic_url', ''))
                        }
    except Exception as e:
        print(f"Instagram API error: {e}")
    
    # Fallback: Try to get from HTML
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://www.instagram.com/{username}/"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    # Find the JSON data in the HTML
                    json_match = re.search(r'window\._sharedData\s*=\s*({.*?});</script>', html)
                    if json_match:
                        data = json.loads(json_match.group(1))
                        user_data = data.get('entry_data', {}).get('ProfilePage', [{}])[0].get('graphql', {}).get('user', {})
                        if user_data:
                            return {
                                'followers': user_data.get('edge_followed_by', {}).get('count', 0),
                                'following': user_data.get('edge_follow', {}).get('count', 0),
                                'posts': user_data.get('edge_owner_to_timeline_media', {}).get('count', 0),
                                'name': user_data.get('full_name', ''),
                                'profile_pic': user_data.get('profile_pic_url_hd', user_data.get('profile_pic_url', ''))
                            }
    except Exception as e:
        print(f"Instagram fallback error: {e}")
    
    return None


async def fetch_tiktok_data(username: str):
    """Fetch TikTok profile data."""
    try:
        async with aiohttp.ClientSession() as session:
            # Use TikTok's public API
            url = f"https://www.tiktok.com/@{username}"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive'
            }
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    # Extract JSON data from script tags
                    json_pattern = r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">(.*?)</script>'
                    json_match = re.search(json_pattern, html, re.DOTALL)
                    if json_match:
                        data = json.loads(json_match.group(1))
                        user_info = data.get('__DEFAULT_SCOPE__', {}).get('webapp.user-detail', {}).get('userInfo', {})
                        if user_info and 'user' in user_info:
                            user = user_info['user']
                            stats = user_info.get('stats', {})
                            return {
                                'followers': stats.get('followerCount', 0),
                                'following': stats.get('followingCount', 0),
                                'posts': stats.get('videoCount', 0),
                                'likes': stats.get('heartCount', 0),
                                'name': user.get('nickname', ''),
                                'profile_pic': user.get('avatarMedium', user.get('avatarThumb', ''))
                            }
    except Exception as e:
        print(f"TikTok API error: {e}")
    return None


async def fetch_roblox_data(username: str):
    """Fetch Roblox profile data using official API."""
    try:
        async with aiohttp.ClientSession() as session:
            # Get user ID from username
            async with session.get(f"https://api.roblox.com/users/get-by-username?username={username}") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data and 'Id' in data:
                        user_id = data['Id']
                        
                        # Get user info
                        async with session.get(f"https://users.roblox.com/v1/users/{user_id}") as user_resp:
                            if user_resp.status == 200:
                                user_data = await user_resp.json()
                        
                        # Get followers count
                        async with session.get(f"https://friends.roblox.com/v1/users/{user_id}/friends/count") as friends_resp:
                            followers = 0
                            if friends_resp.status == 200:
                                friends_data = await friends_resp.json()
                                followers = friends_data.get('count', 0)
                        
                        # Get profile picture
                        async with session.get(f"https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={user_id}&size=420x420&format=Png") as img_resp:
                            profile_pic = ''
                            if img_resp.status == 200:
                                img_data = await img_resp.json()
                                if img_data and 'data' in img_data and len(img_data['data']) > 0:
                                    profile_pic = img_data['data'][0]['imageUrl']
                        
                        return {
                            'followers': followers,
                            'following': 0,
                            'posts': 0,
                            'visits': 0,
                            'name': user_data.get('name', ''),
                            'profile_pic': profile_pic
                        }
    except Exception as e:
        print(f"Roblox API error: {e}")
    return None


async def fetch_spotify_data(username: str):
    """Fetch Spotify profile data."""
    try:
        async with aiohttp.ClientSession() as session:
            # Spotify API requires authentication
            client_id = os.getenv("SPOTIFY_CLIENT_ID", "")
            client_secret = os.getenv("SPOTIFY_CLIENT_SECRET", "")
            
            if client_id and client_secret:
                # Get access token
                auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
                headers = {
                    'Authorization': f'Basic {auth}',
                    'Content-Type': 'application/x-www-form-urlencoded'
                }
                async with session.post('https://accounts.spotify.com/api/token', 
                                      data={'grant_type': 'client_credentials'},
                                      headers=headers) as token_resp:
                    if token_resp.status == 200:
                        token_data = await token_resp.json()
                        access_token = token_data.get('access_token')
                        
                        if access_token:
                            # Search for user profile
                            headers = {'Authorization': f'Bearer {access_token}'}
                            async with session.get(f"https://api.spotify.com/v1/users/{username}", headers=headers) as resp:
                                if resp.status == 200:
                                    data = await resp.json()
                                    return {
                                        'followers': data.get('followers', {}).get('total', 0),
                                        'following': 0,
                                        'playlists': 0,
                                        'tracks': 0,
                                        'name': data.get('display_name', ''),
                                        'profile_pic': data.get('images', [{}])[0].get('url', '') if data.get('images') else ''
                                    }
    except Exception as e:
        print(f"Spotify API error: {e}")
    
    # Fallback for Spotify - if API fails, return None
    return None


async def fetch_facebook_data(username: str):
    """Fetch Facebook profile data."""
    try:
        async with aiohttp.ClientSession() as session:
            # Facebook public profile
            url = f"https://www.facebook.com/{username}"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    # Try to find the profile name
                    name_match = re.search(r'<title>(.*?) \| Facebook</title>', html)
                    if name_match:
                        name = name_match.group(1)
                        return {
                            'name': name,
                            'profile_pic': f"https://graph.facebook.com/{username}/picture?type=large"
                        }
    except Exception as e:
        print(f"Facebook API error: {e}")
    return None


async def fetch_x_data(username: str):
    """Fetch X/Twitter profile data."""
    try:
        bearer_token = os.getenv("TWITTER_BEARER_TOKEN", "")
        
        if bearer_token:
            async with aiohttp.ClientSession() as session:
                headers = {'Authorization': f'Bearer {bearer_token}'}
                async with session.get(f"https://api.twitter.com/2/users/by/username/{username}", headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data and 'data' in data:
                            user_data = data['data']
                            # Get profile picture
                            profile_pic = user_data.get('profile_image_url', '').replace('_normal', '')
                            return {
                                'followers': user_data.get('public_metrics', {}).get('followers_count', 0),
                                'following': user_data.get('public_metrics', {}).get('following_count', 0),
                                'posts': user_data.get('public_metrics', {}).get('tweet_count', 0),
                                'likes': 0,
                                'name': user_data.get('name', ''),
                                'profile_pic': profile_pic
                            }
    except Exception as e:
        print(f"X API error: {e}")
    
    # Fallback: Try to scrape
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://x.com/{username}"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    # Try to find user data in JSON
                    json_match = re.search(r'<script type="application/json" data-state=".*?">(.*?)</script>', html)
                    if json_match:
                        data = json.loads(json_match.group(1))
                        # This is complex, we'll just return basic info
                        return {
                            'name': username,
                            'profile_pic': f"https://x.com/{username}/photo"
                        }
    except Exception as e:
        print(f"X fallback error: {e}")
    return None


# --- SOCIAL MEDIA CHECKER ---
class SocialMediaChecker:
    @staticmethod
    async def get_social_embed(platform: str, username: str) -> discord.Embed:
        platform_configs = {
            "instagram": {
                "color": 0xE1306C,
                "display_name": "Instagram",
                "emoji": "📸",
                "icon": "https://upload.wikimedia.org/wikipedia/commons/a/a5/Instagram_icon.png",
                "fetch_func": fetch_instagram_data
            },
            "tiktok": {
                "color": 0x000000,
                "display_name": "TikTok",
                "emoji": "🎵",
                "icon": "https://upload.wikimedia.org/wikipedia/commons/a/a9/TikTok_logo_icon.svg",
                "fetch_func": fetch_tiktok_data
            },
            "facebook": {
                "color": 0x1877F2,
                "display_name": "Facebook",
                "emoji": "📘",
                "icon": "https://upload.wikimedia.org/wikipedia/commons/5/51/Facebook_f_logo_%282019%29.svg",
                "fetch_func": fetch_facebook_data
            },
            "x": {
                "color": 0x000000,
                "display_name": "X",
                "emoji": "🐦",
                "icon": "https://upload.wikimedia.org/wikipedia/commons/thumb/c/ce/X_logo_2023.svg/300px-X_logo_2023.svg.png",
                "fetch_func": fetch_x_data
            },
            "roblox": {
                "color": 0x00B2E3,
                "display_name": "Roblox",
                "emoji": "🎮",
                "icon": "https://upload.wikimedia.org/wikipedia/commons/6/6e/Roblox_Logo_2022.png",
                "fetch_func": fetch_roblox_data
            },
            "spotify": {
                "color": 0x1DB954,
                "display_name": "Spotify",
                "emoji": "🎧",
                "icon": "https://upload.wikimedia.org/wikipedia/commons/1/19/Spotify_logo_without_text.svg",
                "fetch_func": fetch_spotify_data
            }
        }
        
        config = platform_configs.get(platform.lower())
        if not config:
            return None
        
        # Fetch real data
        data = await config['fetch_func'](username)
        
        # Create embed based on whether data was found
        if data:
            embed = discord.Embed(
                title=f"{config['emoji']} {config['display_name']} Profile",
                description=f"**@{username}**",
                color=config['color'],
                timestamp=discord.utils.utcnow()
            )
            
            # Add platform-specific stats
            if platform == "instagram":
                embed.add_field(
                    name="📊 Statistics",
                    value=f"**Followers:** {format_number(data.get('followers', 0))}\n"
                          f"**Following:** {format_number(data.get('following', 0))}\n"
                          f"**Posts:** {format_number(data.get('posts', 0))}",
                    inline=False
                )
                if data.get('name'):
                    embed.add_field(name="Full Name", value=data['name'], inline=False)
                
            elif platform == "tiktok":
                embed.add_field(
                    name="📊 Statistics",
                    value=f"**Followers:** {format_number(data.get('followers', 0))}\n"
                          f"**Following:** {format_number(data.get('following', 0))}\n"
                          f"**Posts:** {format_number(data.get('posts', 0))}\n"
                          f"**Likes:** {format_number(data.get('likes', 0))}",
                    inline=False
                )
                if data.get('name'):
                    embed.add_field(name="Nickname", value=data['name'], inline=False)
                
            elif platform == "facebook":
                if data.get('name'):
                    embed.add_field(name="Name", value=data['name'], inline=False)
                
            elif platform == "x":
                embed.add_field(
                    name="📊 Statistics",
                    value=f"**Followers:** {format_number(data.get('followers', 0))}\n"
                          f"**Following:** {format_number(data.get('following', 0))}\n"
                          f"**Posts:** {format_number(data.get('posts', 0))}",
                    inline=False
                )
                if data.get('name'):
                    embed.add_field(name="Display Name", value=data['name'], inline=False)
                
            elif platform == "roblox":
                embed.add_field(
                    name="📊 Statistics",
                    value=f"**Followers:** {format_number(data.get('followers', 0))}",
                    inline=False
                )
                if data.get('name'):
                    embed.add_field(name="Username", value=data['name'], inline=False)
                
            elif platform == "spotify":
                embed.add_field(
                    name="📊 Statistics",
                    value=f"**Followers:** {format_number(data.get('followers', 0))}",
                    inline=False
                )
                if data.get('name'):
                    embed.add_field(name="Display Name", value=data['name'], inline=False)
            
            # Add status
            embed.add_field(
                name="✅ Profile Status",
                value="Profile Found • Last Updated: Just Now",
                inline=False
            )
            
            # Set profile picture as thumbnail (top right)
            if data.get('profile_pic'):
                embed.set_thumbnail(url=data['profile_pic'])
            else:
                embed.set_thumbnail(url=config['icon'])
            
            embed.set_footer(text=f"Kinsec Social Checker • mi luv /rk")
            
        else:
            # User not found or private
            embed = discord.Embed(
                title=f"{config['emoji']} {config['display_name']} Profile",
                description=f"User **@{username}** not found or profile is private.",
                color=0xFF0000,
                timestamp=discord.utils.utcnow()
            )
            embed.set_thumbnail(url=config['icon'])
            embed.set_footer(text=f"Kinsec Social Checker • mi luv /rk")
        
        return embed


# --- RICH PRESENCE LOOP (STREAMING) ---
@tasks.loop(seconds=15)
async def presence_loop():
    if not bot.guilds:
        return
        
    total_members = sum(g.member_count for g in bot.guilds)
    total_vc = sum(
        len(vc.members)
        for g in bot.guilds
        for vc in g.voice_channels
    )
    
    activities = [
        discord.Streaming(
            name="Kinsec Security • mi luv /rk",
            url="https://www.twitch.tv/discord"
        ),
        discord.Streaming(
            name=f"Monitoring {total_members} members",
            url="https://www.twitch.tv/discord"
        ),
        discord.Streaming(
            name=f"Watching {total_vc} in voice",
            url="https://www.twitch.tv/discord"
        ),
        discord.Streaming(
            name="k.help for commands",
            url="https://www.twitch.tv/discord"
        )
    ]
    
    if not hasattr(presence_loop, "idx"):
        presence_loop.idx = 0
    
    await bot.change_presence(
        activity=activities[presence_loop.idx % len(activities)],
        status=discord.Status.online
    )
    
    presence_loop.idx += 1


@presence_loop.before_loop
async def before_presence_loop():
    await bot.wait_until_ready()


# --- MEMBER EVENTS ---
@bot.event
async def on_member_join(member: discord.Member):
    join_history.append(
        datetime.datetime.now(datetime.timezone.utc)
    )


@bot.event
async def on_member_remove(member: discord.Member):
    leave_history.append(
        datetime.datetime.now(datetime.timezone.utc)
    )


# --- ANTI LEND ADMIN EVENTS ---
@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    before_admin = any(role.permissions.administrator for role in before.roles)
    after_admin = any(role.permissions.administrator for role in after.roles)
    
    if before_admin or not after_admin:
        return
    
    guild = after.guild
    actor = await get_audit_log_actor(
        guild,
        discord.AuditLogAction.member_role_update,
        after.id
    )
    
    if actor and actor.id != bot.user.id and not is_whitelisted(guild, actor):
        try:
            admin_roles_added = [
                role for role in after.roles 
                if role.permissions.administrator and role not in before.roles
            ]
            
            if admin_roles_added:
                await after.remove_roles(*admin_roles_added, reason="Security: Anti Lend Admin")
            
            await guild.ban(actor, reason="Security: Anti Lend Admin (Unauthorized Assignment)")
            
            await send_mod_log(
                guild,
                "Anti Lend Admin (Role Assigned)",
                actor,
                after.mention,
                "Unauthorized user attempted to give Administrator permissions to a member."
            )
        except discord.HTTPException as e:
            print(f"Anti-lend admin error: {e}")


@bot.event
async def on_guild_role_update(before: discord.Role, after: discord.Role):
    if before.permissions.administrator or not after.permissions.administrator:
        return
    
    guild = after.guild
    actor = await get_audit_log_actor(
        guild,
        discord.AuditLogAction.role_update,
        after.id
    )
    
    if actor and actor.id != bot.user.id and not is_whitelisted(guild, actor):
        try:
            await after.edit(
                permissions=before.permissions,
                reason="Security: Anti Lend Admin Revert"
            )
            
            await guild.ban(actor, reason="Security: Anti Lend Admin (Unauthorized Role Edit)")
            
            await send_mod_log(
                guild,
                "Anti Lend Admin (Role Edit)",
                actor,
                f"Role: {after.name}",
                "Unauthorized user attempted to add Administrator permissions to a role."
            )
        except discord.HTTPException as e:
            print(f"Anti-lend admin role edit error: {e}")


# --- ROLE DELETION PROTECTION ---
@bot.event
async def on_guild_role_delete(role: discord.Role):
    guild = role.guild
    
    actor = await get_audit_log_actor(
        guild,
        discord.AuditLogAction.role_delete,
        role.id
    )
    
    if not actor or actor.id == bot.user.id or is_whitelisted(guild, actor):
        return
    
    recently_deleted_roles[actor.id].append(role)
    if len(recently_deleted_roles[actor.id]) > 10:
        recently_deleted_roles[actor.id] = recently_deleted_roles[actor.id][-10:]
    
    if check_rate_limit(actor.id, role_delete_tracker, ROLE_DELETE_LIMIT, ROLE_DELETE_WINDOW):
        role_delete_tracker[actor.id].clear()
        
        deleted_roles = recently_deleted_roles.get(actor.id, [])
        role_names = ", ".join([r.name for r in deleted_roles[-ROLE_DELETE_LIMIT:]])
        
        try:
            if await safe_ban(guild, actor, f"Security: Mass Role Deletion ({len(deleted_roles)} roles in {ROLE_DELETE_WINDOW}s)"):
                await send_mod_log(
                    guild,
                    "Mass Role Deletion Prevention",
                    actor,
                    f"Deleted {len(deleted_roles)} roles",
                    f"User deleted {len(deleted_roles)} roles in {ROLE_DELETE_WINDOW} seconds.\nRoles: {role_names}"
                )
        except discord.HTTPException as e:
            print(f"Mass role deletion ban error: {e}")


# --- CHANNEL DELETION PROTECTION ---
@bot.event
async def on_guild_channel_delete(channel: discord.abc.GuildChannel):
    guild = channel.guild
    
    actor = await get_audit_log_actor(
        guild,
        discord.AuditLogAction.channel_delete,
        channel.id
    )
    
    if not actor or actor.id == bot.user.id or is_whitelisted(guild, actor):
        return
    
    recently_deleted_channels[actor.id].append(channel)
    if len(recently_deleted_channels[actor.id]) > 10:
        recently_deleted_channels[actor.id] = recently_deleted_channels[actor.id][-10:]
    
    if check_rate_limit(actor.id, channel_delete_tracker, CHANNEL_DELETE_LIMIT, CHANNEL_DELETE_WINDOW):
        channel_delete_tracker[actor.id].clear()
        
        deleted_channels = recently_deleted_channels.get(actor.id, [])
        channel_names = ", ".join([f"#{c.name}" for c in deleted_channels[-CHANNEL_DELETE_LIMIT:]])
        
        try:
            if await safe_ban(guild, actor, f"Security: Mass Channel Deletion ({len(deleted_channels)} channels in {CHANNEL_DELETE_WINDOW}s)"):
                await send_mod_log(
                    guild,
                    "Mass Channel Deletion Prevention",
                    actor,
                    f"Deleted {len(deleted_channels)} channels",
                    f"User deleted {len(deleted_channels)} channels in {CHANNEL_DELETE_WINDOW} seconds.\nChannels: {channel_names}"
                )
        except discord.HTTPException as e:
            print(f"Mass channel deletion ban error: {e}")


# --- SOCIAL MEDIA CHECKER COMMANDS (PREFIX) ---
@bot.command(name="ins", aliases=["instagram"])
async def ins(ctx: commands.Context, username: str):
    embed = await SocialMediaChecker.get_social_embed("instagram", username)
    if embed:
        await ctx.send(embed=embed)
    else:
        await ctx.send("Failed to generate Instagram embed.")


@bot.command(name="tt", aliases=["tiktok"])
async def tiktok(ctx: commands.Context, username: str):
    embed = await SocialMediaChecker.get_social_embed("tiktok", username)
    if embed:
        await ctx.send(embed=embed)
    else:
        await ctx.send("Failed to generate TikTok embed.")


@bot.command(name="fb", aliases=["facebook"])
async def facebook(ctx: commands.Context, username: str):
    embed = await SocialMediaChecker.get_social_embed("facebook", username)
    if embed:
        await ctx.send(embed=embed)
    else:
        await ctx.send("Failed to generate Facebook embed.")


@bot.command(name="x", aliases=["twitter"])
async def x_profile(ctx: commands.Context, username: str):
    embed = await SocialMediaChecker.get_social_embed("x", username)
    if embed:
        await ctx.send(embed=embed)
    else:
        await ctx.send("Failed to generate X profile embed.")


@bot.command(name="rbx", aliases=["roblox"])
async def roblox(ctx: commands.Context, username: str):
    embed = await SocialMediaChecker.get_social_embed("roblox", username)
    if embed:
        await ctx.send(embed=embed)
    else:
        await ctx.send("Failed to generate Roblox embed.")


@bot.command(name="sp", aliases=["spotify"])
async def spotify(ctx: commands.Context, username: str):
    embed = await SocialMediaChecker.get_social_embed("spotify", username)
    if embed:
        await ctx.send(embed=embed)
    else:
        await ctx.send("Failed to generate Spotify embed.")


# --- SLASH COMMANDS ---
kinsec_group = app_commands.Group(name="kinsec", description="Kinsec security commands")

@kinsec_group.command(name="scan", description="Display daily member statistics")
async def slash_scan(interaction: discord.Interaction):
    today = datetime.datetime.now(datetime.timezone.utc).date()
    
    joins = len([
        t for t in join_history
        if t.date() == today
    ])
    
    leaves = len([
        t for t in leave_history
        if t.date() == today
    ])
    
    embed = create_embed(
        "Server Daily Scan",
        "Member activity statistics for today.",
        fields=[
            ("Users joined today", str(joins), False),
            ("Users left today", str(leaves), False)
        ]
    )
    
    await interaction.response.send_message(embed=embed)


@kinsec_group.command(name="kill", description="Hard ban a user (requires ban permissions)")
@app_commands.default_permissions(ban_members=True)
@app_commands.describe(target="The user to ban", reason="Reason for the ban")
async def slash_kill(
    interaction: discord.Interaction,
    target: discord.User,
    reason: str = "Hardban: Security Kill Command"
):
    target_member = interaction.guild.get_member(target.id)
    
    if target_member:
        if interaction.user.top_role.position <= target_member.top_role.position:
            await interaction.response.send_message(
                "You are below this member in role hierarchy.",
                ephemeral=True
            )
            return
    
    try:
        await interaction.guild.ban(
            target,
            reason=f"{reason} (executed by {interaction.user})"
        )
        
        embed = create_embed(
            "User Banned",
            f"{target.mention} has been banned.",
            fields=[
                ("User", f"{target.mention} ({target.name})", True),
                ("ID", f"`{target.id}`", True),
                ("Reason", reason, False),
                ("Executed By", interaction.user.mention, False)
            ],
            color=0xFF0000
        )
        
        await interaction.response.send_message(embed=embed)
        
        await send_mod_log(
            interaction.guild,
            "Manual Kill Command (Slash)",
            interaction.user,
            target.mention,
            f"User was manually banned by {interaction.user.mention}\nReason: {reason}"
        )
    except Exception as e:
        await interaction.response.send_message(
            f"Failed to ban user: {e}",
            ephemeral=True
        )


@kinsec_group.command(name="clean", description="Purge messages in a channel")
@app_commands.default_permissions(manage_messages=True)
@app_commands.describe(amount="Number of messages to delete (max 100)", user="Only delete messages from this user")
async def slash_clean(
    interaction: discord.Interaction,
    amount: app_commands.Range[int, 1, 100],
    user: Optional[discord.User] = None
):
    def check_message(m):
        return user is None or m.author == user
    
    try:
        deleted = await interaction.channel.purge(limit=amount, check=check_message)
        
        embed = create_embed(
            "Channel Cleaned",
            f"Deleted {len(deleted)} messages.",
            fields=[
                ("Channel", interaction.channel.mention, True),
                ("Deleted", str(len(deleted)), True),
                ("User Filter", user.mention if user else "None", True)
            ],
            color=0x00FF00
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
        await send_mod_log(
            interaction.guild,
            "Channel Clean (Slash)",
            interaction.user,
            interaction.channel.mention,
            f"Cleaned {len(deleted)} messages" + (f" from {user.mention}" if user else "")
        )
    except discord.HTTPException as e:
        await interaction.response.send_message(
            f"Failed to clean messages: {e}",
            ephemeral=True
        )


@kinsec_group.command(name="whois", description="Get information about a user")
@app_commands.describe(user="The user to look up")
async def slash_whois(
    interaction: discord.Interaction,
    user: discord.User
):
    member = interaction.guild.get_member(user.id)
    
    embed = create_embed(
        f"User Information: {user.name}",
        "",
        fields=[
            ("Username", f"{user.name}#{user.discriminator if hasattr(user, 'discriminator') else ''}", True),
            ("ID", f"`{user.id}`", True),
            ("Bot", "Yes" if user.bot else "No", True),
            ("Account Created", f"<t:{int(user.created_at.timestamp())}:F>", False),
            ("Joined Server", f"<t:{int(member.joined_at.timestamp())}:F>" if member else "Not in server", False),
            ("Roles", f"{len(member.roles) - 1} roles" if member else "N/A", False)
        ]
    )
    
    if member:
        embed.add_field(
            name="Top Role",
            value=member.top_role.mention,
            inline=True
        )
        embed.add_field(
            name="Permissions",
            value=f"Administrator: {'Yes' if member.guild_permissions.administrator else 'No'}",
            inline=True
        )
    
    await interaction.response.send_message(embed=embed)


# --- SOCIAL MEDIA SLASH COMMANDS ---
@kinsec_group.command(name="instagram", description="Check Instagram profile")
@app_commands.describe(username="Instagram username to check")
async def slash_instagram(
    interaction: discord.Interaction,
    username: str
):
    embed = await SocialMediaChecker.get_social_embed("instagram", username)
    if embed:
        await interaction.response.send_message(embed=embed)
    else:
        await interaction.response.send_message(
            "Failed to generate Instagram profile embed.",
            ephemeral=True
        )


@kinsec_group.command(name="tiktok", description="Check TikTok profile")
@app_commands.describe(username="TikTok username to check")
async def slash_tiktok(
    interaction: discord.Interaction,
    username: str
):
    embed = await SocialMediaChecker.get_social_embed("tiktok", username)
    if embed:
        await interaction.response.send_message(embed=embed)
    else:
        await interaction.response.send_message(
            "Failed to generate TikTok profile embed.",
            ephemeral=True
        )


@kinsec_group.command(name="facebook", description="Check Facebook profile")
@app_commands.describe(username="Facebook username to check")
async def slash_facebook(
    interaction: discord.Interaction,
    username: str
):
    embed = await SocialMediaChecker.get_social_embed("facebook", username)
    if embed:
        await interaction.response.send_message(embed=embed)
    else:
        await interaction.response.send_message(
            "Failed to generate Facebook profile embed.",
            ephemeral=True
        )


@kinsec_group.command(name="x", description="Check X/Twitter profile")
@app_commands.describe(username="X/Twitter username to check")
async def slash_x(
    interaction: discord.Interaction,
    username: str
):
    embed = await SocialMediaChecker.get_social_embed("x", username)
    if embed:
        await interaction.response.send_message(embed=embed)
    else:
        await interaction.response.send_message(
            "Failed to generate X profile embed.",
            ephemeral=True
        )


@kinsec_group.command(name="roblox", description="Check Roblox profile")
@app_commands.describe(username="Roblox username to check")
async def slash_roblox(
    interaction: discord.Interaction,
    username: str
):
    embed = await SocialMediaChecker.get_social_embed("roblox", username)
    if embed:
        await interaction.response.send_message(embed=embed)
    else:
        await interaction.response.send_message(
            "Failed to generate Roblox profile embed.",
            ephemeral=True
        )


@kinsec_group.command(name="spotify", description="Check Spotify profile")
@app_commands.describe(username="Spotify username to check")
async def slash_spotify(
    interaction: discord.Interaction,
    username: str
):
    embed = await SocialMediaChecker.get_social_embed("spotify", username)
    if embed:
        await interaction.response.send_message(embed=embed)
    else:
        await interaction.response.send_message(
            "Failed to generate Spotify profile embed.",
            ephemeral=True
        )


# Register the slash command group
bot.tree.add_command(kinsec_group)


# --- REGULAR COMMANDS ---
@bot.command(name="scan")
async def scan(ctx: commands.Context):
    today = datetime.datetime.now(datetime.timezone.utc).date()
    
    joins = len([
        t for t in join_history
        if t.date() == today
    ])
    
    leaves = len([
        t for t in leave_history
        if t.date() == today
    ])
    
    embed = create_embed(
        "Server Daily Scan",
        "Member activity statistics for today.",
        fields=[
            ("Users joined today", str(joins), False),
            ("Users left today", str(leaves), False)
        ]
    )
    
    await ctx.send(embed=embed)


@bot.command(name="kill")
@commands.has_permissions(ban_members=True)
async def kill(ctx: commands.Context, target: discord.User):
    target_member = ctx.guild.get_member(target.id)
    
    if target_member:
        if ctx.author.top_role.position <= target_member.top_role.position:
            await ctx.send("You are below this member in role hierarchy.")
            return
    
    try:
        await ctx.guild.ban(
            target,
            reason=f"Hardban: Security Kill Command (executed by {ctx.author})"
        )
        
        embed = create_embed(
            "User Banned",
            f"{target.mention} has been banned.",
            fields=[
                ("User", f"{target.mention} ({target.name})", True),
                ("ID", f"`{target.id}`", True),
                ("Executed By", ctx.author.mention, False)
            ],
            color=0xFF0000
        )
        
        await ctx.send(embed=embed)
        
        await send_mod_log(
            ctx.guild,
            "Manual Kill Command (Prefix)",
            ctx.author,
            target.mention,
            f"User was manually banned by {ctx.author.mention}"
        )
    except Exception as e:
        await ctx.send(f"Failed to ban user: {e}")


@kill.error
async def kill_error(ctx: commands.Context, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You do not have permission to use this command.")


@bot.command(name="call")
async def call(ctx: commands.Context, target: discord.User, *, message: str):
    if ctx.author.id not in WHITELISTED_USERS:
        await ctx.send("You do not have permission to use this command.")
        return
    
    delivered = False
    delivery_status_details = "Message delivered successfully."
    
    try:
        await target.send(message[:2000])
        delivered = True
    except discord.Forbidden:
        delivery_status_details = "Failed: User has DMs disabled or blocked the bot."
    except discord.HTTPException as e:
        delivery_status_details = f"Failed: API error ({e})"
    
    embed = create_embed(
        "Direct Message Execution Log",
        "A direct message command was triggered.",
        fields=[
            ("Target User", f"{target.mention} ({target.name})", True),
            ("Target ID", f"`{target.id}`", True),
            ("Executed By", f"{ctx.author.mention} (`{ctx.author.id}`)", False),
            ("Delivery Status", "DELIVERED" if delivered else "FAILED", True),
            ("Delivery Details", delivery_status_details, True),
            ("Message Payload", f"```\n{message[:1000]}\n```", False)
        ]
    )
    
    if LOG_CHANNEL_ID != 0:
        log_channel = ctx.guild.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(embed=embed)
    
    await ctx.send(f"Process complete. Delivery status: {'DELIVERED' if delivered else 'FAILED'}.")


@call.error
async def call_error(ctx: commands.Context, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("Syntax: `k.call [user] [message]`")


@bot.command(name="dmall")
async def dmall(ctx: commands.Context, *, message_text: str):
    if ctx.author.id not in WHITELISTED_USERS:
        await ctx.send("You do not have permission to use this command.")
        return
    
    confirm_msg = await ctx.send(
        f"Warning: You are about to DM **{len(ctx.guild.members)}** members. "
        "This action cannot be undone. Reply with `yes` to confirm or `no` to cancel. (10 second timeout)"
    )
    
    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel
    
    try:
        response = await bot.wait_for('message', timeout=10.0, check=check)
        if response.content.lower() not in ['yes', 'y']:
            await ctx.send("Mass DM cancelled.")
            return
    except asyncio.TimeoutError:
        await ctx.send("Mass DM cancelled due to timeout.")
        return
    
    status_msg = await ctx.send("Initiating Mass DM broadcast...")
    
    success_count = 0
    fail_count = 0
    
    targets = [
        member for member in ctx.guild.members 
        if not member.bot and not is_whitelisted(ctx.guild, member)
    ]
    total_targets = len(targets)
    
    for index, member in enumerate(targets, 1):
        try:
            await member.send(message_text[:2000])
            success_count += 1
            await asyncio.sleep(1)
        except (discord.Forbidden, discord.HTTPException):
            fail_count += 1
        
        if index % 5 == 0 or index == total_targets:
            try:
                await status_msg.edit(
                    content=(
                        f"Broadcasting: {index}/{total_targets}\n"
                        f"Sent: {success_count}\n"
                        f"Failed: {fail_count}"
                    )
                )
            except discord.HTTPException:
                pass
    
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
    if message.guild is None:
        if message.author.bot:
            return
        
        if DM_LOG_CHANNEL_ID != 0:
            log_channel = bot.get_channel(DM_LOG_CHANNEL_ID)
            if log_channel:
                embed = create_embed(
                    "Incoming Private DM Log",
                    message.content[:1024] if message.content else "[Attachment / No text]",
                    fields=[
                        ("Sender", f"{message.author.mention}\n`{message.author}`", True),
                        ("Sender ID", f"`{message.author.id}`", True)
                    ]
                )
                
                if message.attachments:
                    embed.add_field(
                        name="Attachments",
                        value="\n".join([f"- {a.filename}" for a in message.attachments[:5]]),
                        inline=False
                    )
                
                try:
                    await log_channel.send(embed=embed)
                except discord.HTTPException:
                    pass
        return
    
    if message.author.bot or is_whitelisted(message.guild, message.author):
        await bot.process_commands(message)
        return
    
    user_id = message.author.id
    
    if getattr(message, "poll", None):
        if check_rate_limit(user_id, poll_tracker, POLL_LIMIT, POLL_WINDOW):
            poll_tracker[user_id].clear()
            try:
                await asyncio.gather(
                    message.channel.purge(
                        limit=10,
                        check=lambda m: getattr(m, "poll", None) and m.author == message.author
                    ),
                    timeout_user(message.author, 1, "Mass Poll Spam"),
                    message.channel.send(f"{message.author.mention} - Please don't spam polls.")
                )
                await send_mod_log(
                    message.guild,
                    "Mass Poll Spam Muted",
                    message.author,
                    message.channel.mention,
                    "Polls purged and user timed out for 1 minute."
                )
            except discord.HTTPException:
                pass
        return
    
    if check_rate_limit(user_id, spam_tracker, SPAM_LIMIT, SPAM_WINDOW):
        spam_tracker[user_id].clear()
        try:
            await asyncio.gather(
                message.channel.purge(limit=10, check=lambda m: m.author == message.author),
                timeout_user(message.author, 1, "Mass Spam"),
                message.channel.send(f"{message.author.mention} - Please don't spam.")
            )
            await send_mod_log(
                message.guild,
                "Mass Spam Muted",
                message.author,
                message.channel.mention,
                "Messages purged and user timed out for 1 minute."
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
    
    user_id = owner.id
    
    if check_rate_limit(user_id, thread_tracker, THREAD_LIMIT, THREAD_WINDOW):
        thread_tracker[user_id].clear()
        try:
            await asyncio.gather(
                thread.delete(),
                timeout_user(owner, 1, "Mass Thread Spam"),
                thread.parent.send(f"{owner.mention} - Please don't create excessive threads.")
            )
            await send_mod_log(
                guild,
                "Mass Thread Spam Halted",
                owner,
                "Multiple Threads",
                f"User exceeded thread limit ({THREAD_LIMIT} in {THREAD_WINDOW}s)."
            )
        except discord.HTTPException:
            pass


# --- AUDIT LOG EVENTS ---
@bot.event
async def on_audit_log_entry_create(entry: discord.AuditLogEntry):
    guild = entry.guild
    actor = entry.user
    
    if not actor or not bot.user or actor.id == bot.user.id or is_whitelisted(guild, actor):
        return
    
    if entry.action == discord.AuditLogAction.kick:
        if check_rate_limit(actor.id, kick_tracker, KICK_LIMIT, KICK_WINDOW):
            try:
                await guild.ban(actor, reason="Security: Mass Kick Detection")
                await send_mod_log(
                    guild,
                    "Mass Kick Prevention",
                    actor,
                    "N/A",
                    f"User attempted mass kick ({KICK_LIMIT}+ kicks). User has been banned."
                )
            except discord.HTTPException:
                pass
    
    elif entry.action == discord.AuditLogAction.ban:
        if check_rate_limit(actor.id, ban_tracker, BAN_LIMIT, BAN_WINDOW):
            try:
                await guild.ban(actor, reason="Security: Mass Ban Detection")
                await send_mod_log(
                    guild,
                    "Mass Ban Prevention",
                    actor,
                    "N/A",
                    f"User attempted mass ban ({BAN_LIMIT}+ bans). User has been banned."
                )
            except discord.HTTPException:
                pass
    
    elif entry.action == discord.AuditLogAction.bot_add:
        unauthorized_bot = entry.target
        if unauthorized_bot and getattr(unauthorized_bot, "bot", False):
            try:
                await actor.send("You are not authorized to add bots. Your action has been logged.")
            except discord.HTTPException:
                pass
            
            try:
                await asyncio.gather(
                    guild.ban(actor, reason="Unauthorized Bot Added"),
                    guild.kick(unauthorized_bot, reason="Unauthorized Bot")
                )
                await send_mod_log(
                    guild,
                    "Unauthorized Bot Addition",
                    actor,
                    f"Bot: {unauthorized_bot.mention}",
                    "The user who added the bot has been banned and the bot has been kicked."
                )
            except discord.HTTPException:
                pass


# --- READY EVENT ---
@bot.event
async def on_ready():
    bot.uptime = time.time()
    
    print(f"Kinsec Security Bot Active")
    print(f"Logged in as: {bot.user}")
    print(f"Connected to {len(bot.guilds)} guilds")
    print(f"Monitoring {sum(g.member_count for g in bot.guilds)} members")
    print(f"Syncing slash commands...")
    
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands")
        print("Slash commands available:")
        for cmd in synced:
            if isinstance(cmd, app_commands.Command):
                print(f"  /kinsec {cmd.name}")
    except Exception as e:
        print(f"Failed to sync slash commands: {e}")
    
    if not presence_loop.is_running():
        presence_loop.start()


# --- ERROR HANDLING ---
@bot.event
async def on_command_error(ctx: commands.Context, error):
    if isinstance(error, commands.CommandNotFound):
        return
    
    if isinstance(error, commands.MissingPermissions):
        await ctx.send(f"You don't have permission: {error}")
        return
    
    print(f"Command error in {ctx.command}: {error}")
    await ctx.send(f"An error occurred: {error}")


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            f"You don't have permission to use this command.",
            ephemeral=True
        )
        return
    
    print(f"Slash command error in {interaction.command.name}: {error}")
    
    try:
        await interaction.response.send_message(
            f"An error occurred: {error}",
            ephemeral=True
        )
    except discord.HTTPException:
        await interaction.followup.send(
            f"An error occurred: {error}",
            ephemeral=True
        )


# --- START BOT ---
if __name__ == "__main__":
    try:
        bot.run(BOT_TOKEN)
    except discord.LoginFailure:
        print("Invalid bot token. Please check your BOT_TOKEN environment variable.")
    except Exception as e:
        print(f"Bot startup failed: {e}")

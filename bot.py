import os
import asyncio
import json
import aiohttp
import discord
from discord.ext import commands, tasks
import yaml
from datetime import datetime, timezone, timedelta
import random

# ------------------------------------------------------------------
# 1.  Environment sanity check
# ------------------------------------------------------------------
# Handle the case where DISCORD_TOKEN might be the first line without key
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    # Try to read the first line of .env as the token
    try:
        with open('.env', 'r') as f:
            first_line = f.readline().strip()
            if not first_line.startswith('DISCORD_TOKEN=') and len(first_line) > 50:
                TOKEN = first_line
    except:
        pass

CID     = int(os.getenv("CHANNEL_ID"))
CONTRACT = os.getenv("CONTRACT")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", 2)) # Default to 2 seconds
NETWORK = os.getenv("NETWORK", "").lower()

if NETWORK not in {"mainnet", "testnet"}:
    raise RuntimeError("NETWORK env must be 'mainnet' or 'testnet' (case-insensitive)")

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN not found in environment variables")

if not CONTRACT:
    raise RuntimeError("CONTRACT not found in environment variables")

# ------------------------------------------------------------------
# 2.  HTTP API Endpoint map
# ------------------------------------------------------------------
API_ENDPOINTS = {
    "mainnet": [
        "https://hyperion.wax.eosdetroit.io",
        "https://wax.eosusa.io",
        "https://api.wax.alohaeos.com",
        "https://hyperion-wax-mainnet.wecan.dev"
    ],
    "testnet": [
        "https://hyperion-wax-testnet.wecan.dev",
        "https://hyperion.testnet.wax.detroitledger.tech",
        "https://testnet.waxsweden.org",
        "https://api.waxtest.alohaeos.com",
        "https://waxtest.api.eosnation.io"
    ]
}
HTTP_URLS = API_ENDPOINTS[NETWORK]

# Track last seen transaction to avoid duplicates
last_seen_timestamp = None
processed_transactions = set()
bot_start_time = None

# Giveaway storage
active_giveaways = {}  # {message_id: giveaway_data}
giveaway_counter = 0

# Invite tracking storage
invite_data = {}  # {user_id: {invites: int, joins: int, left: int, fake: int}}
invite_cache = {}  # {invite_code: {inviter_id: int, uses: int}}
guild_invites = {}  # Cache of guild invites

# Load invite data from file
def load_invite_data():
    """Load invite data from JSON file"""
    global invite_data
    try:
        with open('invite_data.json', 'r') as f:
            invite_data = json.load(f)
            # Convert string keys back to integers
            invite_data = {int(k): v for k, v in invite_data.items()}
        print(f"Loaded invite data for {len(invite_data)} users")
    except FileNotFoundError:
        print("No existing invite data file found, starting fresh")
        invite_data = {}
    except Exception as e:
        print(f"Error loading invite data: {e}")
        invite_data = {}

def save_invite_data():
    """Save invite data to JSON file"""
    try:
        with open('invite_data.json', 'w') as f:
            json.dump(invite_data, f, indent=2)
        print(f"Saved invite data for {len(invite_data)} users")
    except Exception as e:
        print(f"Error saving invite data: {e}")

# Load invite data on startup
load_invite_data()

# ------------------------------------------------------------------
# 3.  Load configuration
# ------------------------------------------------------------------
def load_config():
    """Load configuration from config.yml"""
    try:
        with open('config.yml', 'r') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        print("Warning: config.yml not found. Role-based commands will be disabled.")
        return {}
    except Exception as e:
        print(f"Error loading config.yml: {e}")
        return {}

config = load_config()

# ------------------------------------------------------------------
# 4.  Discord client
# ------------------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True  # Required for message content

# Try to enable privileged intents for invite tracking
# These need to be enabled in Discord Developer Portal
try:
    invite_config = config.get('invite_tracking', {})
    if invite_config.get('enabled', False):
        print("Invite tracking is enabled, requesting privileged intents...")
        print("Make sure to enable 'Server Members Intent' and 'Message Content Intent' in Discord Developer Portal")
        intents.members = True  # Required for member events
        intents.invites = True  # Required for invite tracking
    else:
        print("Invite tracking is disabled in config")
except Exception as e:
    print(f"Warning: Could not configure invite tracking intents: {e}")

bot = commands.Bot(command_prefix='!', intents=intents)

def create_embed_for_action(action, act_name, act_data, custom_title=None):
    """Create a nicely formatted Discord embed for blockchain actions"""
    # Handle different timestamp formats
    timestamp_str = action.get("@timestamp", action.get("timestamp", ""))
    try:
        if timestamp_str.endswith('Z'):
            timestamp = datetime.fromisoformat(timestamp_str[:-1]).replace(tzinfo=timezone.utc)
        elif '+' in timestamp_str:
            timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        else:
            timestamp = datetime.fromisoformat(timestamp_str).replace(tzinfo=timezone.utc)
    except:
        timestamp = datetime.now(timezone.utc)
    
    # Use custom title if provided, otherwise use action name
    title = custom_title if custom_title else f"{act_name} on {CONTRACT}"
    
    # Extract wallet information
    wallet = None
    if 'from' in act_data:
        wallet = act_data['from']
    elif 'owner' in act_data:
        wallet = act_data['owner']
    elif 'to' in act_data and act_data.get('from'):
        wallet = act_data['from']
    
    # Create description with better formatting
    description_parts = []
    
    if wallet:
        description_parts.append(f"**Wallet:** `{wallet}`")
    
    # Only show detailed transaction data for setbeevar actions
    if act_name == "setbeevar":
        description_parts.append("")
        
        # Format setbeevar data nicely
        bee_type = act_data.get('type', 'Unknown')
        rarity = act_data.get('rarity', 'Unknown')
        category = act_data.get('category', 'Unknown')
        values = act_data.get('values', [])
        
        description_parts.append(f"**Bee Type:** `{bee_type.title()}`")
        description_parts.append(f"**Rarity:** `{rarity.title()}`")
        description_parts.append(f"**Category:** `{category.title()}`")
        
        if values and len(values) >= 4:
            description_parts.append("")
            description_parts.append("**New Earning Values:**")
            description_parts.append(f"🍯 **HUNY:** `{values[0]}`")
            description_parts.append(f"🌱 **PLN:** `{values[1]}`")
            description_parts.append(f"🪙 **BWAX:** `{values[2]}`")
            description_parts.append(f"👑 **RJ:** `{values[3]}`")
    elif act_name in ["claim", "unstake"]:
        # For other actions, show minimal details without JSON
        if act_name == "claim" and 'hiveitem' in act_data:
            description_parts.append("")
            description_parts.append(f"**Hive Item:** `{act_data['hiveitem']}`")
        elif act_name == "unstake" and 'asset_id' in act_data:
            description_parts.append("")
            description_parts.append(f"**Asset ID:** `{act_data['asset_id']}`")
            if 'hive_id' in act_data:
                description_parts.append(f"**Hive ID:** `{act_data['hive_id']}`")
    
    description = "\n".join(description_parts)
    
    # Set color based on action type
    color_map = {
        "setbeevar": 0xFFD700,      # Gold
        "sethivevar": 0xFF8C00,     # Dark Orange
        "stakehive": 0x32CD32,      # Lime Green
        "stakebees": 0x228B22,      # Forest Green
        "claim": 0x4169E1,          # Royal Blue
        "unstake": 0xFF6347,        # Tomato Red
        "transfer": 0x32CD32,       # Lime Green (for New Hive Staked)
    }
    
    color = color_map.get(act_name, 0xffaa00)  # Default orange
    
    embed = discord.Embed(
        title=title,
        description=description,
        url=f"https://{'wax-test' if NETWORK == 'testnet' else 'wax'}.bloks.io/transaction/{action['trx_id']}",
        timestamp=timestamp,
        color=color
    )
    
    # Remove transaction hash from footer since it's already linked in the title
    embed.set_footer(text=f"HoneyFarms Contract Activity")
    return embed

def create_transfer_embed(action, act_data):
    """Create special embeds for transfer actions with specific memos"""
    memo = act_data.get('memo', '')
    
    if memo == "stakehive":
        title = "🏠 New Hive Staked"
        asset_ids = act_data.get('asset_ids', [])
        
        # Create a clean description for hive staking
        description_parts = [
            f"**Wallet:** `{act_data.get('from', 'Unknown')}`",
            "",
            f"**Asset IDs:** `{', '.join(asset_ids) if asset_ids else 'Unknown'}`"
        ]
        
        return create_custom_embed(
            action, 
            title, 
            "\n".join(description_parts),
            0x32CD32  # Lime Green
        )
    
    elif memo.startswith("stakebees:"):
        title = "🐝 Bees Staked to Hive"
        try:
            hive_id = memo.split(":")[1]
            asset_ids = act_data.get('asset_ids', [])
            
            description_parts = [
                f"**Wallet:** `{act_data.get('from', 'Unknown')}`",
                "",
                f"**Hive ID:** `{hive_id}`",
                f"**Bee Asset IDs:** `{', '.join(asset_ids) if asset_ids else 'Unknown'}`"
            ]
            
            return create_custom_embed(
                action,
                title,
                "\n".join(description_parts),
                0x228B22  # Forest Green
            )
        except (ValueError, IndexError):
            return None
    
    return None

def create_custom_embed(action, title, description, color):
    """Create a custom embed with specified title, description and color"""
    timestamp_str = action.get("@timestamp", action.get("timestamp", ""))
    try:
        if timestamp_str.endswith('Z'):
            timestamp = datetime.fromisoformat(timestamp_str[:-1]).replace(tzinfo=timezone.utc)
        elif '+' in timestamp_str:
            timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        else:
            timestamp = datetime.fromisoformat(timestamp_str).replace(tzinfo=timezone.utc)
    except:
        timestamp = datetime.now(timezone.utc)
    
    embed = discord.Embed(
        title=title,
        description=description,
        url=f"https://{'wax-test' if NETWORK == 'testnet' else 'wax'}.bloks.io/transaction/{action['trx_id']}",
        timestamp=timestamp,
        color=color
    )
    
    # Remove transaction hash from footer since it's already linked in the title
    embed.set_footer(text=f"HoneyFarms Contract Activity")
    return embed

# Legacy function for backward compatibility
def embed_for(tx, act_name, data):
    return create_embed_for_action(tx, act_name, data)

# ------------------------------------------------------------------
# 5.  Discord slash commands
# ------------------------------------------------------------------
@bot.tree.command(
    name="clear",
    description="Clear all messages in the current channel (requires specific role)"
)
async def clear_command(interaction: discord.Interaction):
    """Slash command to clear all messages in the channel"""
    try:
        # Defer the response immediately to prevent timeout
        await interaction.response.defer(ephemeral=True)
        
        # Check if user has the required role
        required_role_id = config.get('permissions', {}).get('clear_command_role_id')
        
        if not required_role_id or required_role_id == "YOUR_ROLE_ID_HERE":
            await interaction.followup.send("❌ Clear command is not configured. Please set the role ID in config.yml", ephemeral=True)
            return
        
        # Check if user has the required role
        user_role_ids = [str(role.id) for role in interaction.user.roles]
        if required_role_id not in user_role_ids:
            await interaction.followup.send("❌ You don't have permission to use this command.", ephemeral=True)
            return
        
        # Delete all messages in the channel using purge (more efficient)
        deleted = await interaction.channel.purge(limit=None)
        
        # Send confirmation message
        embed = discord.Embed(
            title="🧹 Channel Cleared",
            description=f"Successfully deleted {len(deleted)} messages from this channel.",
            color=0x00ff00
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        
    except discord.Forbidden:
        embed = discord.Embed(
            title="❌ Permission Error",
            description="I don't have permission to delete messages in this channel.",
            color=0xff0000
        )
        try:
            await interaction.followup.send(embed=embed, ephemeral=True)
        except:
            # If followup fails, try original response (in case defer didn't work)
            await interaction.response.send_message(embed=embed, ephemeral=True)
    except Exception as e:
        print(f"Error in clear command: {e}")
        embed = discord.Embed(
            title="❌ Error",
            description=f"An error occurred while clearing the channel: {str(e)}",
            color=0xff0000
        )
        try:
            await interaction.followup.send(embed=embed, ephemeral=True)
        except:
            # If followup fails, try original response (in case defer didn't work)
            try:
                await interaction.response.send_message(embed=embed, ephemeral=True)
            except:
                pass  # Interaction already expired, but operation completed

@bot.tree.command(
    name="giveaway",
    description="Create a new giveaway with a reward and duration"
)
async def giveaway_command(
    interaction: discord.Interaction,
    reward: str,
    duration_minutes: int,
    description: str = None,
    required_role: discord.Role = None
):
    """Slash command to create a giveaway"""
    global giveaway_counter, active_giveaways
    
    try:
        # Defer the response immediately to prevent timeout
        await interaction.response.defer()
        
        # Check if user has the required role
        required_role_id = config.get('permissions', {}).get('giveaway_role_id')
        
        if not required_role_id or required_role_id == "YOUR_ROLE_ID_HERE":
            await interaction.followup.send("❌ Giveaway command is not configured. Please set the giveaway_role_id in config.yml", ephemeral=True)
            return
        
        # Check if user has the required role
        user_role_ids = [str(role.id) for role in interaction.user.roles]
        if required_role_id not in user_role_ids:
            await interaction.followup.send("❌ You don't have permission to use this command.", ephemeral=True)
            return
        
        # Validate duration
        if duration_minutes < 1 or duration_minutes > 10080:  # Max 1 week
            await interaction.followup.send("❌ Duration must be between 1 minute and 1 week (10080 minutes).", ephemeral=True)
            return
        
        # Calculate end time
        end_time = datetime.now(timezone.utc) + timedelta(minutes=duration_minutes)
        
        # Create giveaway embed
        giveaway_counter += 1
        
        embed = discord.Embed(
            title="🎉 GIVEAWAY 🎉",
            description=f"**Reward:** {reward}\n\n{description or 'React with 🎉 to enter!'}",
            color=0xFF6B6B,
            timestamp=end_time
        )
        
        embed.add_field(
            name="⏰ Ends",
            value=f"<t:{int(end_time.timestamp())}:R>",
            inline=True
        )
        
        embed.add_field(
            name="👥 Participants",
            value="0",
            inline=True
        )
        
        if required_role:
            embed.add_field(
                name="🔒 Required Role",
                value=required_role.mention,
                inline=True
            )
        
        embed.set_footer(text="Ends at")
        
        # Send the giveaway message
        message = await interaction.followup.send(embed=embed)
        
        # Add reaction
        await message.add_reaction("🎉")
        
        # Store giveaway data
        active_giveaways[message.id] = {
            'id': giveaway_counter,
            'reward': reward,
            'description': description,
            'end_time': end_time,
            'creator': interaction.user.id,
            'channel_id': interaction.channel.id,
            'participants': set(),
            'ended': False,
            'required_role_id': required_role.id if required_role else None
        }
        
        print(f"Created giveaway #{giveaway_counter} ending at {end_time}")
        
    except Exception as e:
        print(f"Error in giveaway command: {e}")
        embed = discord.Embed(
            title="❌ Error",
            description=f"An error occurred while creating the giveaway: {str(e)}",
            color=0xff0000
        )
        try:
            await interaction.followup.send(embed=embed, ephemeral=True)
        except:
            try:
                await interaction.response.send_message(embed=embed, ephemeral=True)
            except:
                pass

@bot.tree.command(
    name="end_giveaway",
    description="Manually end a giveaway and pick a winner"
)
async def end_giveaway_command(
    interaction: discord.Interaction,
    message_id: str
):
    """Slash command to manually end a giveaway"""
    try:
        # Defer the response immediately to prevent timeout
        await interaction.response.defer(ephemeral=True)
        
        # Check if user has the required role
        required_role_id = config.get('permissions', {}).get('giveaway_role_id')
        
        if not required_role_id or required_role_id == "YOUR_ROLE_ID_HERE":
            await interaction.followup.send("❌ End giveaway command is not configured. Please set the giveaway_role_id in config.yml", ephemeral=True)
            return
        
        # Check if user has the required role
        user_role_ids = [str(role.id) for role in interaction.user.roles]
        if required_role_id not in user_role_ids:
            await interaction.followup.send("❌ You don't have permission to use this command.", ephemeral=True)
            return
        
        try:
            msg_id = int(message_id)
        except ValueError:
            await interaction.followup.send("❌ Invalid message ID format.", ephemeral=True)
            return
        
        if msg_id not in active_giveaways:
            await interaction.followup.send("❌ Giveaway not found or already ended.", ephemeral=True)
            return
        
        giveaway = active_giveaways[msg_id]
        
        # Check if user is the creator or has admin permissions
        if giveaway['creator'] != interaction.user.id:
            await interaction.followup.send("❌ You can only end giveaways you created.", ephemeral=True)
            return
        
        # End the giveaway
        await end_giveaway(msg_id)
        await interaction.followup.send("✅ Giveaway ended successfully!", ephemeral=True)
        
    except Exception as e:
        print(f"Error in end_giveaway command: {e}")
        embed = discord.Embed(
            title="❌ Error",
            description=f"An error occurred while ending the giveaway: {str(e)}",
            color=0xff0000
        )
        try:
            await interaction.followup.send(embed=embed, ephemeral=True)
        except:
             pass

@bot.tree.command(
    name="list_giveaways",
    description="List all active giveaways"
)
async def list_giveaways_command(interaction: discord.Interaction):
    """Slash command to list active giveaways"""
    try:
        await interaction.response.defer(ephemeral=True)
        
        if not active_giveaways:
            await interaction.followup.send("📭 No active giveaways at the moment.", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="🎉 Active Giveaways",
            color=0xFF6B6B
        )
        
        for message_id, giveaway in active_giveaways.items():
            if not giveaway['ended']:
                time_left = giveaway['end_time'] - datetime.now(timezone.utc)
                if time_left.total_seconds() > 0:
                    # Build giveaway info
                    giveaway_info = f"**Reward:** {giveaway['reward']}\n**Participants:** {len(giveaway['participants'])}\n**Ends:** <t:{int(giveaway['end_time'].timestamp())}:R>\n**Message ID:** {message_id}"
                    
                    # Add required role info if present
                    if giveaway.get('required_role_id'):
                        role = interaction.guild.get_role(giveaway['required_role_id'])
                        if role:
                            giveaway_info += f"\n**Required Role:** {role.mention}"
                    
                    embed.add_field(
                        name=f"Giveaway #{giveaway['id']}",
                        value=giveaway_info,
                        inline=False
                    )
        
        if len(embed.fields) == 0:
            await interaction.followup.send("📭 No active giveaways at the moment.", ephemeral=True)
        else:
            await interaction.followup.send(embed=embed, ephemeral=True)
        
    except Exception as e:
         print(f"Error in list_giveaways command: {e}")
         await interaction.followup.send("❌ An error occurred while listing giveaways.", ephemeral=True)

@bot.tree.command(
    name="invites",
    description="Check your invite statistics or another user's invites"
)
async def invites_command(
    interaction: discord.Interaction,
    user: discord.Member = None
):
    """Slash command to check invite statistics"""
    try:
        await interaction.response.defer()
        
        target_user = user or interaction.user
        user_id = target_user.id
        
        # Get user's invite data
        user_invites = invite_data.get(user_id, {
            'invites': 0,
            'joins': 0,
            'left': 0,
            'fake': 0
        })
        
        # Calculate real invites (joins - left - fake)
        real_invites = user_invites['joins'] - user_invites['left'] - user_invites['fake']
        
        embed = discord.Embed(
            title=f"📊 Invite Statistics for {target_user.display_name}",
            color=0x00ff00
        )
        
        embed.add_field(
            name="📨 Total Invites Created",
            value=str(user_invites['invites']),
            inline=True
        )
        
        embed.add_field(
            name="✅ Successful Joins",
            value=str(user_invites['joins']),
            inline=True
        )
        
        embed.add_field(
            name="📈 Real Invites",
            value=str(max(0, real_invites)),
            inline=True
        )
        
        embed.add_field(
            name="❌ Members Left",
            value=str(user_invites['left']),
            inline=True
        )
        
        embed.add_field(
            name="🚫 Fake/Invalid",
            value=str(user_invites['fake']),
            inline=True
        )
        
        embed.set_thumbnail(url=target_user.display_avatar.url)
        embed.set_footer(text="Invite tracking system")
        
        await interaction.followup.send(embed=embed)
        
    except Exception as e:
        print(f"Error in invites command: {e}")
        embed = discord.Embed(
            title="❌ Error",
            description="An error occurred while fetching invite statistics.",
            color=0xff0000
        )
        try:
            await interaction.followup.send(embed=embed, ephemeral=True)
        except:
            pass

@bot.tree.command(
    name="leaderboard",
    description="Show the top inviters in the server"
)
async def leaderboard_command(interaction: discord.Interaction):
    """Slash command to show invite leaderboard"""
    try:
        await interaction.response.defer()
        
        if not invite_data:
            await interaction.followup.send("📭 No invite data available yet.", ephemeral=True)
            return
        
        # Sort users by real invites (joins - left - fake)
        sorted_users = []
        for user_id, data in invite_data.items():
            real_invites = data['joins'] - data['left'] - data['fake']
            if real_invites > 0:
                sorted_users.append((user_id, real_invites, data))
        
        sorted_users.sort(key=lambda x: x[1], reverse=True)
        
        if not sorted_users:
            await interaction.followup.send("📭 No users with successful invites yet.", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="🏆 Invite Leaderboard",
            description="Top inviters in the server",
            color=0xffd700
        )
        
        # Show top 10
        for i, (user_id, real_invites, data) in enumerate(sorted_users[:10]):
            user = bot.get_user(user_id)
            username = user.display_name if user else f"Unknown User ({user_id})"
            
            medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else f"{i+1}."
            
            embed.add_field(
                name=f"{medal} {username}",
                value=f"**{real_invites}** real invites\n({data['joins']} joins, {data['left']} left)",
                inline=False
            )
        
        embed.set_footer(text="Real invites = Joins - Left - Fake")
        
        await interaction.followup.send(embed=embed)
        
    except Exception as e:
        print(f"Error in leaderboard command: {e}")
        embed = discord.Embed(
            title="❌ Error",
            description="An error occurred while fetching the leaderboard.",
            color=0xff0000
        )
        try:
            await interaction.followup.send(embed=embed, ephemeral=True)
        except:
            pass

@bot.tree.command(
    name="reset_invites",
    description="Reset invite statistics for a user (Admin only)"
)
async def reset_invites_command(
    interaction: discord.Interaction,
    user: discord.Member
):
    """Slash command to reset invite statistics"""
    try:
        await interaction.response.defer(ephemeral=True)
        
        # Check if user has the required role
        required_role_id = config.get('permissions', {}).get('invite_admin_role_id')
        
        if not required_role_id or required_role_id == "YOUR_ROLE_ID_HERE":
            await interaction.followup.send("❌ Reset invites command is not configured. Please set the invite_admin_role_id in config.yml", ephemeral=True)
            return
        
        # Check if user has the required role
        user_role_ids = [str(role.id) for role in interaction.user.roles]
        if required_role_id not in user_role_ids:
            await interaction.followup.send("❌ You don't have permission to use this command.", ephemeral=True)
            return
        
        user_id = user.id
        
        if user_id in invite_data:
            del invite_data[user_id]
            await interaction.followup.send(f"✅ Reset invite statistics for {user.display_name}", ephemeral=True)
        else:
            await interaction.followup.send(f"❌ No invite data found for {user.display_name}", ephemeral=True)
        
    except Exception as e:
        print(f"Error in reset_invites command: {e}")
        await interaction.followup.send("❌ An error occurred while resetting invite statistics.", ephemeral=True)
  
  # ------------------------------------------------------------------
  # 6.  Invite tracking functions
  # ------------------------------------------------------------------

async def update_invite_cache(guild):
    """Update the invite cache for a guild"""
    try:
        invites = await guild.invites()
        guild_invites[guild.id] = {}
        
        for invite in invites:
            if invite.inviter:
                guild_invites[guild.id][invite.code] = {
                    'inviter_id': invite.inviter.id,
                    'uses': invite.uses or 0
                }
                
                # Initialize invite data for the inviter
                if invite.inviter.id not in invite_data:
                    invite_data[invite.inviter.id] = {
                        'invites': 0,
                        'joins': 0,
                        'left': 0,
                        'fake': 0
                    }
                
                # Count total invites created
                invite_data[invite.inviter.id]['invites'] = len([i for i in invites if i.inviter and i.inviter.id == invite.inviter.id])
        
        print(f"Updated invite cache for {guild.name}: {len(guild_invites[guild.id])} invites")
        
    except Exception as e:
        print(f"Error updating invite cache: {e}")

async def find_invite_used(guild, member):
    """Find which invite was used by comparing before/after"""
    try:
        current_invites = await guild.invites()
        
        if guild.id not in guild_invites:
            await update_invite_cache(guild)
            return None
        
        old_invites = guild_invites[guild.id]
        
        for invite in current_invites:
            if invite.code in old_invites:
                old_uses = old_invites[invite.code]['uses']
                if invite.uses > old_uses:
                    # This invite was used
                    inviter_id = old_invites[invite.code]['inviter_id']
                    
                    # Update cache
                    guild_invites[guild.id][invite.code]['uses'] = invite.uses
                    
                    return inviter_id
        
        return None
        
    except Exception as e:
        print(f"Error finding used invite: {e}")
        return None

  # ------------------------------------------------------------------
  # 7.  Giveaway functions
  # ------------------------------------------------------------------

@bot.event
async def on_reaction_add(reaction, user):
    """Handle reaction additions for giveaways"""
    # Ignore bot reactions
    if user.bot:
        return
    
    # Check if this is a giveaway message
    if reaction.message.id in active_giveaways:
        giveaway = active_giveaways[reaction.message.id]
        
        # Check if giveaway is still active
        if giveaway['ended'] or datetime.now(timezone.utc) > giveaway['end_time']:
            return
        
        # Check if reaction is the giveaway emoji
        if str(reaction.emoji) == "🎉":
            # Check if giveaway has a required role
            if giveaway.get('required_role_id'):
                # Check if user has the required role
                member = reaction.message.guild.get_member(user.id)
                if not member or not any(role.id == giveaway['required_role_id'] for role in member.roles):
                    # Remove the reaction since user doesn't have required role
                    try:
                        await reaction.remove(user)
                    except:
                        pass
                    return
            
            # Add user to participants
            giveaway['participants'].add(user.id)
            
            # Update the embed with new participant count
            await update_giveaway_embed(reaction.message, giveaway)

@bot.event
async def on_member_join(member):
    """Handle member joins and track invite usage"""
    try:
        guild = member.guild
        
        # Find which invite was used
        inviter_id = await find_invite_used(guild, member)
        
        if inviter_id:
            # Initialize invite data if not exists
            if inviter_id not in invite_data:
                invite_data[inviter_id] = {
                    'invites': 0,
                    'joins': 0,
                    'left': 0,
                    'fake': 0
                }
            
            # Check if this might be a fake account
            account_age = (datetime.now(timezone.utc) - member.created_at).days
            fake_threshold = config.get('invite_tracking', {}).get('fake_account_threshold_days', 7)
            is_fake = account_age < fake_threshold
            
            if is_fake:
                invite_data[inviter_id]['fake'] += 1
                print(f"Detected potential fake account: {member.name} (age: {account_age} days) invited by {inviter_id}")
            else:
                invite_data[inviter_id]['joins'] += 1
                print(f"Member {member.name} joined using invite from {inviter_id}")
            
            # Save invite data
            save_invite_data()
            
            # Update invite cache
            await update_invite_cache(guild)
            
            # Send notification if configured
            invite_config = config.get('invite_tracking', {})
            if invite_config.get('enabled', False) and 'invite_log_channel_id' in invite_config:
                channel = bot.get_channel(int(invite_config['invite_log_channel_id']))
            else:
                channel = None
            if channel and not is_fake:
                inviter = bot.get_user(inviter_id)
                inviter_name = inviter.display_name if inviter else f"User {inviter_id}"
                
                embed = discord.Embed(
                    title="👋 New Member Joined!",
                    description=f"**{member.mention}** joined the server\nInvited by: **{inviter_name}**",
                    color=0x00ff00,
                    timestamp=datetime.now(timezone.utc)
                )
                embed.set_thumbnail(url=member.display_avatar.url)
                embed.set_footer(text="Invite tracking system")
                
                try:
                    await channel.send(embed=embed)
                except:
                    pass  # Don't fail if we can't send to channel
        else:
            print(f"Could not determine invite used by {member.name}")
            # Update cache anyway
            await update_invite_cache(guild)
            
    except Exception as e:
        print(f"Error in on_member_join: {e}")

@bot.event
async def on_member_remove(member):
    """Handle member leaves and update invite statistics"""
    try:
        # Find who invited this member by checking our records
        # This is a simplified approach - in a production bot you'd want to store this data
        
        # For now, we'll just update the cache and log the leave
        print(f"Member {member.name} left the server")
        
        # Update invite cache
        await update_invite_cache(member.guild)
        
        # Save invite data
        save_invite_data()
        
        # Send notification if configured
        invite_config = config.get('invite_tracking', {})
        if invite_config.get('enabled', False) and 'invite_log_channel_id' in invite_config:
            channel = bot.get_channel(int(invite_config['invite_log_channel_id']))
        else:
            channel = None
        if channel:
            embed = discord.Embed(
                title="👋 Member Left",
                description=f"**{member.display_name}** left the server",
                color=0xff6b6b,
                timestamp=datetime.now(timezone.utc)
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.set_footer(text="Invite tracking system")
            
            try:
                await channel.send(embed=embed)
            except:
                pass  # Don't fail if we can't send to channel
                
    except Exception as e:
        print(f"Error in on_member_remove: {e}")

@bot.event
async def on_invite_create(invite):
    """Handle new invite creation"""
    try:
        if invite.inviter:
            print(f"New invite created by {invite.inviter.name}: {invite.code}")
            await update_invite_cache(invite.guild)
    except Exception as e:
        print(f"Error in on_invite_create: {e}")

@bot.event
async def on_invite_delete(invite):
    """Handle invite deletion"""
    try:
        print(f"Invite deleted: {invite.code}")
        await update_invite_cache(invite.guild)
    except Exception as e:
        print(f"Error in on_invite_delete: {e}")

@bot.event
async def on_reaction_remove(reaction, user):
    """Handle reaction removals for giveaways"""
    # Ignore bot reactions
    if user.bot:
        return
    
    # Check if this is a giveaway message
    if reaction.message.id in active_giveaways:
        giveaway = active_giveaways[reaction.message.id]
        
        # Check if giveaway is still active
        if giveaway['ended'] or datetime.now(timezone.utc) > giveaway['end_time']:
            return
        
        # Check if reaction is the giveaway emoji
        if str(reaction.emoji) == "🎉":
            # Remove user from participants
            giveaway['participants'].discard(user.id)
            
            # Update the embed with new participant count
            await update_giveaway_embed(reaction.message, giveaway)

async def update_giveaway_embed(message, giveaway):
    """Update the giveaway embed with current participant count"""
    try:
        embed = message.embeds[0]
        
        # Update participant count field
        for i, field in enumerate(embed.fields):
            if field.name == "👥 Participants":
                embed.set_field_at(i, name="👥 Participants", value=str(len(giveaway['participants'])), inline=True)
                break
        
        await message.edit(embed=embed)
    except Exception as e:
        print(f"Error updating giveaway embed: {e}")

async def end_giveaway(message_id):
    """End a giveaway and pick a winner"""
    if message_id not in active_giveaways:
        return
    
    giveaway = active_giveaways[message_id]
    giveaway['ended'] = True
    
    try:
        # Get the channel and message
        channel = bot.get_channel(giveaway['channel_id'])
        if not channel:
            print(f"Could not find channel {giveaway['channel_id']} for giveaway {giveaway['id']}")
            return
        
        message = await channel.fetch_message(message_id)
        if not message:
            print(f"Could not find message {message_id} for giveaway {giveaway['id']}")
            return
        
        # Pick a winner
        participants = list(giveaway['participants'])
        
        if not participants:
            # No participants
            embed = discord.Embed(
                title="🎉 GIVEAWAY ENDED 🎉",
                description=f"**Reward:** {giveaway['reward']}\n\n❌ No participants! No winner selected.",
                color=0x808080
            )
            embed.add_field(name="👥 Participants", value="0", inline=True)
            embed.set_footer(text="Giveaway ended")
            
            await message.edit(embed=embed)
            await channel.send("🎉 **Giveaway ended!** Unfortunately, no one participated. 😢")
        else:
            # Pick random winner
            winner_id = random.choice(participants)
            winner = bot.get_user(winner_id)
            winner_mention = winner.mention if winner else f"<@{winner_id}>"
            
            # Update embed
            embed = discord.Embed(
                title="🎉 GIVEAWAY ENDED 🎉",
                description=f"**Reward:** {giveaway['reward']}\n\n🏆 **Winner:** {winner_mention}",
                color=0x00FF00
            )
            embed.add_field(name="👥 Participants", value=str(len(participants)), inline=True)
            embed.add_field(name="🏆 Winner", value=winner_mention, inline=True)
            embed.set_footer(text="Giveaway ended")
            
            await message.edit(embed=embed)
            
            # Announce winner
            await channel.send(f"🎉 **Giveaway ended!** Congratulations {winner_mention}! You won: **{giveaway['reward']}** 🏆")
        
        # Remove from active giveaways
        del active_giveaways[message_id]
        print(f"Ended giveaway #{giveaway['id']}")
        
    except Exception as e:
        print(f"Error ending giveaway {giveaway['id']}: {e}")

@tasks.loop(minutes=1)
async def check_giveaways():
    """Check for expired giveaways every minute"""
    current_time = datetime.now(timezone.utc)
    expired_giveaways = []
    
    for message_id, giveaway in active_giveaways.items():
        if not giveaway['ended'] and current_time >= giveaway['end_time']:
            expired_giveaways.append(message_id)
    
    for message_id in expired_giveaways:
        await end_giveaway(message_id)

@tasks.loop(minutes=5)
async def save_invite_data_periodic():
    """Save invite data every 5 minutes"""
    save_invite_data()

# ------------------------------------------------------------------
# 7.  HTTP polling listener
# ------------------------------------------------------------------
async def http_listener():
    global last_seen_timestamp, processed_transactions, bot_start_time
    
    await bot.wait_until_ready()
    channel = bot.get_channel(CID)
    
    # Set bot start time to prevent processing old actions
    bot_start_time = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
    print(f"Bot started at: {bot_start_time}")
    
    # Wait 10 seconds after startup to avoid processing old actions
    print("Waiting 10 seconds to avoid processing old actions...")
    await asyncio.sleep(10)
    print("Starting to monitor for new actions...")
    
    current_url_index = 0
    consecutive_failures = 0
    
    while True:
        api_url = HTTP_URLS[current_url_index]
        
        try:
            async with aiohttp.ClientSession() as session:
                # Query for farmforhoney contract actions
                params = {
                    'account': CONTRACT,
                    'action': 'setbeevar,sethivevar,claim,unstake',
                    'limit': 20,
                    'sort': 'desc'
                }
                
                if last_seen_timestamp:
                    params['after'] = last_seen_timestamp
                
                print(f"Polling {api_url}/v2/history/get_actions...")
                
                async with session.get(f"{api_url}/v2/history/get_actions", params=params, timeout=30) as response:
                    if response.status == 200:
                        data = await response.json()
                        actions = data.get('actions', [])
                        
                        print(f"Found {len(actions)} actions from {api_url}")
                        
                        # Process actions in chronological order (reverse since we got desc)
                        for action in reversed(actions):
                            trx_id = action['trx_id']
                            
                            # Skip if we've already processed this transaction
                            if trx_id in processed_transactions:
                                continue
                            
                            # Skip actions that occurred before bot started
                            action_timestamp = action.get('@timestamp', action.get('timestamp', ''))
                            if bot_start_time and action_timestamp < bot_start_time:
                                continue
                                
                            processed_transactions.add(trx_id)
                            
                            # Keep only recent transactions in memory (last 1000)
                            if len(processed_transactions) > 1000:
                                processed_transactions = set(list(processed_transactions)[-500:])
                            
                            act = action['act']
                            act_name = act['name']
                            act_data = act['data']
                            
                            print(f"Processing {act_name} action: {act_data}")
                            
                            try:
                                # Create appropriate embed based on action type
                                if act_name == 'claim':
                                    embed = create_embed_for_action(action, act_name, act_data, "💰 Honey Claimed")
                                elif act_name == 'unstake':
                                    embed = create_embed_for_action(action, act_name, act_data, "📤 Asset Unstaked")
                                elif act_name == 'transfer':
                                    # Try to create special transfer embed first
                                    embed = create_transfer_embed(action, act_data)
                                    if not embed:
                                        # Fallback to generic transfer embed
                                        embed = create_embed_for_action(action, act_name, act_data)
                                else:
                                    embed = create_embed_for_action(action, act_name, act_data)
                                
                                await channel.send(embed=embed)
                                print(f"Sent {act_name} notification to Discord")
                            except Exception as e:
                                print(f"Error sending Discord message: {e}")
                        
                        # Update last seen timestamp
                        if actions:
                            last_seen_timestamp = actions[0]['@timestamp']
                        
                        # Also check for atomicassets logtransfer actions
                        await check_logtransfer_actions(session, api_url, channel)
                        
                        # Reset failure counter and URL index on success
                        consecutive_failures = 0
                        current_url_index = 0
                        
                    else:
                        print(f"HTTP {response.status} from {api_url}")
                        raise aiohttp.ClientError(f"HTTP {response.status}")
                        
        except Exception as e:
            print(f"Error polling {api_url}: {e}")
            consecutive_failures += 1
            
            # Try next URL
            current_url_index = (current_url_index + 1) % len(HTTP_URLS)
            
            # If we've tried all URLs multiple times, enter test mode
            if consecutive_failures >= len(HTTP_URLS) * 2:
                print("All HTTP endpoints failed multiple times. Entering test mode...")
                await test_mode_simulation(channel)
                return
        
        # Wait before next poll
        await asyncio.sleep(POLL_INTERVAL)

async def check_logtransfer_actions(session, api_url, channel):
    """Check for atomicassets logtransfer actions to farmforhoney"""
    global last_seen_timestamp
    try:
        params = {
            'account': 'atomicassets',
            'action': 'logtransfer',
            'limit': 10,
            'sort': 'desc'
        }
        
        # Only get transfers after the last seen timestamp to avoid spam on startup
        if last_seen_timestamp:
            params['after'] = last_seen_timestamp
        
        async with session.get(f"{api_url}/v2/history/get_actions", params=params, timeout=30) as response:
            if response.status == 200:
                data = await response.json()
                actions = data.get('actions', [])
                
                for action in actions:
                    trx_id = action['trx_id']
                    
                    # Skip if already processed
                    if trx_id in processed_transactions:
                        continue
                    
                    # Skip actions that occurred before bot started
                    action_timestamp = action.get('@timestamp', action.get('timestamp', ''))
                    if bot_start_time and action_timestamp < bot_start_time:
                        continue
                    
                    act_data = action['act']['data']
                    
                    # Only process transfers to our contract
                    if act_data.get('to') != CONTRACT:
                        continue
                    
                    processed_transactions.add(trx_id)
                    
                    # Create special embed for transfer actions
                    embed = create_transfer_embed(action, act_data)
                    if embed:
                        await channel.send(embed=embed)
                        memo = act_data.get('memo', '')
                        if memo == "stakehive":
                            print(f"Sent 'New Hive Staked' notification to Discord")
                        elif memo.startswith("stakebees:"):
                            print(f"Sent 'Bees Staked to Hive' notification to Discord")
                    else:
                        # Create a generic transfer embed as fallback
                        generic_embed = create_embed_for_action(action, "transfer", act_data)
                        await channel.send(embed=generic_embed)
                        print(f"Sent generic transfer notification to Discord")
                            
    except Exception as e:
        print(f"Error checking logtransfer actions: {e}")

# ------------------------------------------------------------------
# 8.  Entry-point
# ------------------------------------------------------------------
@bot.event
async def on_ready():
    print(f"[{NETWORK}] Logged in as {bot.user}")
    print(f"Monitoring contract: {CONTRACT}")
    print(f"Target channel ID: {CID}")
    print(f"Poll interval: {POLL_INTERVAL} seconds")
    channel = bot.get_channel(CID)
    if channel:
        print(f"Found target channel: {channel.name}")
    else:
        print(f"WARNING: Could not find channel with ID {CID}")
    
    # Initialize invite cache for all guilds (only if invite tracking is enabled)
    invite_config = config.get('invite_tracking', {})
    if invite_config.get('enabled', False):
        for guild in bot.guilds:
            try:
                await update_invite_cache(guild)
                print(f"Initialized invite cache for {guild.name}")
            except discord.Forbidden:
                print(f"Missing permissions to access invites for {guild.name}. Enable 'Manage Server' permission.")
            except Exception as e:
                print(f"Failed to initialize invite cache for {guild.name}: {e}")
    else:
        print("Invite tracking is disabled, skipping invite cache initialization")
    
    # Start giveaway checker
    if not check_giveaways.is_running():
        check_giveaways.start()
        print("Started giveaway checker task")
    
    # Start periodic invite data saving
    if not save_invite_data_periodic.is_running():
        save_invite_data_periodic.start()
        print("Started periodic invite data saving task")
    
    # Sync slash commands
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

async def main():
    print(f"Starting Discord bot for {NETWORK} network...")
    print(f"Available HTTP API URLs: {HTTP_URLS}")
    await asyncio.gather(
        bot.start(TOKEN),
        http_listener()
    )

if __name__ == "__main__":
    asyncio.run(main())
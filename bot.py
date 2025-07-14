import os
import asyncio
import json
import aiohttp
import discord
from datetime import datetime, timezone

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
NETWORK = os.getenv("NETWORK", "").lower()

if NETWORK not in {"mainnet", "testnet"}:
    raise RuntimeError("NETWORK env must be 'mainnet' or 'testnet' (case-insensitive)")

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN not found in environment variables")

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

# Test mode - if all endpoints fail, we'll simulate some activity
TEST_MODE = os.getenv("TEST_MODE", "false").lower() == "true"
CONTRACT = "farmforhoney"
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "10"))  # seconds between polls

# Track last seen transaction to avoid duplicates
last_seen_timestamp = None
processed_transactions = set()
bot_start_time = None

# ------------------------------------------------------------------
# 3.  Discord client
# ------------------------------------------------------------------
intents = discord.Intents.default()
client = discord.Client(intents=intents)

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
# 4.  HTTP polling listener
# ------------------------------------------------------------------
async def http_listener():
    global last_seen_timestamp, processed_transactions, bot_start_time
    
    await client.wait_until_ready()
    channel = client.get_channel(CID)
    
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

async def test_mode_simulation(channel):
    """Simulate blockchain events for testing purposes"""
    print("Test mode: Simulating setbeevar events every 30 seconds...")
    counter = 1
    
    while True:
        # Simulate a setbeevar action
        fake_trace = {
            "trx_id": f"test_transaction_{counter:04d}",
            "@timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        }
        
        fake_data = {
            "type": "queen",
            "rarity": "common",
            "category": "earning",
            "values": [4, 3, 2, 1]
        }
        
        print(f"Simulating setbeevar action: {fake_data}")
        
        # Create embed using the new formatting
        embed = create_embed_for_action(fake_trace, "setbeevar", fake_data, "[TEST MODE] 🐝 Bee Variables Updated")
        embed.color = 0xff0000  # Red color to indicate test mode
        
        try:
            await channel.send(embed=embed)
            print(f"Test message {counter} sent to Discord")
        except Exception as e:
            print(f"Error sending test message: {e}")
        
        counter += 1
        await asyncio.sleep(30)  # Wait 30 seconds between test messages

# ------------------------------------------------------------------
# 5.  Entry-point
# ------------------------------------------------------------------
@client.event
async def on_ready():
    print(f"[{NETWORK}] Logged in as {client.user}")
    print(f"Monitoring contract: {CONTRACT}")
    print(f"Target channel ID: {CID}")
    print(f"Poll interval: {POLL_INTERVAL} seconds")
    channel = client.get_channel(CID)
    if channel:
        print(f"Found target channel: {channel.name}")
    else:
        print(f"WARNING: Could not find channel with ID {CID}")

async def main():
    print(f"Starting Discord bot for {NETWORK} network...")
    print(f"Available HTTP API URLs: {HTTP_URLS}")
    await asyncio.gather(
        client.start(TOKEN),
        http_listener()
    )

if __name__ == "__main__":
    asyncio.run(main())
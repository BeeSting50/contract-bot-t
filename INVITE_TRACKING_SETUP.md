# Invite Tracking Setup Guide

This guide explains how to set up and use the invite tracking feature in your Discord bot.

## Features

### Invite Tracking System:
- **Real-time invite tracking**: Monitor who invites new members
- **Comprehensive statistics**: Track invites, joins, leaves, and fake accounts
- **Leaderboard system**: See top inviters in your server
- **Fake account detection**: Identify potentially fake accounts based on account age
- **Persistent data**: Invite data is saved and restored between bot restarts
- **Admin controls**: Reset invite data for specific users
- **Automatic notifications**: Get notified when members join/leave

### Giveaway System:
- **Role-restricted giveaways**: Require specific roles to participate
- **Automatic role verification**: Users without required roles are automatically removed
- **Enhanced giveaway display**: Shows required role information in embeds
- **Flexible participation**: Optional role requirements for inclusive giveaways

## Commands

### Invite Tracking Commands

#### `/invites [user]`
View invite statistics for yourself or another user.
- Shows total invites, successful joins, members who left, and fake accounts
- If no user is specified, shows your own statistics

#### `/leaderboard`
Display the top 10 inviters in the server.
- Shows ranking based on successful invites (total invites minus fake accounts)
- Updates in real-time as members join and leave

#### `/reset_invites <user>`
**Admin only** - Reset invite statistics for a specific user.
- Requires the role specified in `invite_admin_role_id`
- Completely clears all invite data for the target user

### Giveaway Commands

#### `/giveaway <prize> <duration> <winners> [required_role]`
Create a new giveaway with optional role restrictions.
- `prize`: What participants can win
- `duration`: How long the giveaway runs (e.g., "1h", "30m", "2d")
- `winners`: Number of winners to select
- `required_role`: (Optional) Role required to participate

**Examples:**
- `/giveaway "Discord Nitro" 1h 1` - Open giveaway for everyone
- `/giveaway "VIP Access" 24h 3 @VIP Members` - Restricted to VIP Members role

#### `/end_giveaway <message_id>`
**Admin only** - Manually end a giveaway early.

#### `/list_giveaways`
View all active giveaways with their details and required roles.

## Setup Instructions

### Step 1: Enable Privileged Intents

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications/)
2. Select your bot application
3. Navigate to the "Bot" section
4. Scroll down to "Privileged Gateway Intents"
5. Enable the following intents:
   - ✅ **Server Members Intent**
   - ✅ **Message Content Intent**
6. Save your changes

### Step 2: Configure Bot Permissions

Ensure your bot has the following permissions in your Discord server:
- ✅ **Manage Server** (to access invite information)
- ✅ **Send Messages**
- ✅ **Use Slash Commands**
- ✅ **Embed Links**
- ✅ **Read Message History**

### Step 3: Update Configuration

Edit your `config.yml` file:

```yaml
permissions:
  invite_admin_role_id: "YOUR_ADMIN_ROLE_ID_HERE"  # Role that can reset invite data

invite_tracking:
  enabled: true  # Set to true to enable invite tracking
  invite_log_channel_id: "YOUR_CHANNEL_ID_HERE"  # Channel for join/leave notifications
  fake_account_threshold_days: 7  # Accounts younger than this are flagged as potentially fake
```

### Step 4: Get Required IDs

#### Get Role ID:
1. Enable Developer Mode in Discord (User Settings > Advanced > Developer Mode)
2. Right-click on the role you want to use for admin permissions
3. Select "Copy ID"
4. Paste this ID as the `invite_admin_role_id` in your config

#### Get Channel ID:
1. Right-click on the channel where you want join/leave notifications
2. Select "Copy ID"
3. Paste this ID as the `invite_log_channel_id` in your config

### Step 5: Start the Bot

Once configured, restart your bot. You should see:

```
Invite tracking is enabled, requesting privileged intents...
Make sure to enable 'Server Members Intent' and 'Message Content Intent' in Discord Developer Portal
Initialized invite cache for YourServerName
Synced 7 command(s)
```

## Troubleshooting

### Error: "PrivilegedIntentsRequired"
**Solution**: Enable the required privileged intents in the Discord Developer Portal (Step 1 above).

### Error: "Missing permissions to access invites"
**Solution**: Ensure your bot has the "Manage Server" permission in your Discord server.

### Invite tracking not working
1. Check that `invite_tracking.enabled` is set to `true` in your config
2. Verify the bot has the required permissions
3. Ensure privileged intents are enabled
4. Check the bot logs for any error messages

### Commands not appearing
Run the bot and wait for the "Synced X command(s)" message. If commands still don't appear, try:
1. Kicking and re-inviting the bot
2. Checking bot permissions
3. Waiting up to an hour for Discord to sync commands

## Data Storage

Invite data is automatically saved to `invite_data.json` in your bot directory:
- Data is saved every 5 minutes automatically
- Data is saved immediately when members join/leave
- Data persists between bot restarts
- You can manually backup this file for safety

## Fake Account Detection

The system automatically detects potentially fake accounts based on:
- Account age (configurable threshold, default 7 days)
- These are tracked separately and don't count toward invite statistics
- Fake accounts are logged but don't send join notifications

## Example Usage

```
/invites @JohnDoe
# Shows: JohnDoe has 15 invites (12 joined, 2 left, 1 fake)

/leaderboard
# Shows top 10 inviters with their successful invite counts

/reset_invites @JohnDoe
# Clears all invite data for JohnDoe (admin only)
```

## Support

If you encounter issues:
1. Check the bot console logs for error messages
2. Verify all configuration settings
3. Ensure all permissions and intents are properly set
4. Test with a new member joining to verify functionality
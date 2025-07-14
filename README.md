# HoneyFarms Contract Bot

A Discord bot that monitors HoneyFarms smart contract activity on the WAX blockchain and sends notifications to Discord channels.

## Features

- Monitors farmforhoney contract actions (claim, unstake, transfer)
- Special formatting for stakehive transfers ("🏠 New Hive Staked")
- Special formatting for stakebees transfers ("🐝 Bees Staked to Hive")
- Prevents spam on startup by filtering historical actions
- Automatic failover between multiple Hyperion API endpoints

## Local Development

1. Clone the repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and fill in your values:
   ```bash
   cp .env.example .env
   ```
4. Run the bot:
   ```bash
   python3 bot.py
   ```

## Deployment on DigitalOcean App Platform

### Prerequisites
- A Discord bot token
- A GitHub repository with your code
- A DigitalOcean account

### Steps

1. **Push your code to GitHub**
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git remote add origin https://github.com/your-username/contract-bot-t.git
   git push -u origin main
   ```

2. **Create a new App on DigitalOcean**
   - Go to [DigitalOcean Apps](https://cloud.digitalocean.com/apps)
   - Click "Create App"
   - Choose "GitHub" as source
   - Select your repository and branch

3. **Configure the App**
   - DigitalOcean will auto-detect the `app.yaml` file
   - Update the GitHub repo URL in `app.yaml` to match your repository
   - Set the `DISCORD_TOKEN` environment variable as a secret

4. **Environment Variables**
   Set these in the DigitalOcean App Platform dashboard:
   - `DISCORD_TOKEN` (Secret) - Your Discord bot token
   - `CHANNEL_ID` - Discord channel ID to send notifications
   - `CONTRACT_NAME` - Smart contract name (default: farmforhoney)
   - `NETWORK` - Blockchain network (testnet/mainnet)
   - `POLL_INTERVAL` - Polling interval in seconds (default: 10)

5. **Deploy**
   - Click "Create Resources"
   - The app will automatically deploy and start running

### Monitoring

- View logs in the DigitalOcean dashboard under "Runtime Logs"
- The bot will automatically restart if it crashes
- Monitor Discord channel for notifications

## Configuration

### Supported Networks
- `testnet` - WAX Testnet
- `mainnet` - WAX Mainnet

### Monitored Actions
- `claim` - Honey claiming events
- `unstake` - Asset unstaking events
- `transfer` - Asset transfers (with special formatting for stakehive/stakebees)
- `setbeevar` - Bee variable updates
- `sethivevar` - Hive variable updates

## Troubleshooting

### Common Issues

1. **Bot not responding**
   - Check Discord token is valid
   - Verify bot has permissions in the target channel
   - Check runtime logs for errors

2. **No notifications appearing**
   - Verify CHANNEL_ID is correct
   - Check if contract has recent activity
   - Review API endpoint connectivity

3. **Deployment fails**
   - Ensure all required environment variables are set
   - Check GitHub repository is accessible
   - Verify app.yaml syntax

### Support

For issues or questions, check the runtime logs in DigitalOcean dashboard or review the bot's console output.
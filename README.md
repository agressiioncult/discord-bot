# Robux Plus Discord Bot

## Files
- `bot.py` — main Discord bot
- `requirements.txt` — Python packages
- `profile_logo.png` — C logo used by `/profile`
- `.env.example` — environment variable template

## Bot hosting
Set these environment variables/secrets on your host:

- `DISCORD_TOKEN` — your Discord bot token
- `ETHERSCAN_API_KEY` — needed for automatic Ethereum verification
- `BSCSCAN_API_KEY` — needed for automatic BSC USDT verification

Do NOT put the Discord token directly into `bot.py` or GitHub.

## Important Discord permissions
The bot needs appropriate permissions such as:
- View Channels
- Send Messages
- Embed Links
- Read Message History
- Manage Channels
- Manage Roles
- Ban Members
- Moderate Members
- Add Reactions

The bot's role must be above the Customer/10K+/20K+/30K+ roles.

## Price rules
- 5,000–10,000 Robux: $9.00 per 1,000
- 15,000+ Robux: $8.80 per 1,000
- Robux amounts are accepted in 5,000 increments.

## Payment verification
BTC/LTC use BlockCypher.
ETH uses Etherscan.
USDT on BSC uses BscScan through the Etherscan V2 API.
SOL uses the public Solana RPC.

For production use, verify explorer/API limits and test with small payments before opening the store.

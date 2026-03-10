# Deployment

## Docker (Recommended)

The system runs as two containers: the trading bot and the web dashboard.

### Prerequisites

- VPS with Docker and Docker Compose (Ubuntu 22.04+ recommended)
- Bybit testnet API keys ([get here](https://testnet.bybit.com/))
- Telegram bot token ([create via @BotFather](https://t.me/BotFather))

### Setup

```bash
# Clone
git clone https://github.com/AlexJumby/algo-trading.git ~/algo_trading
cd ~/algo_trading

# Create .env file with API keys
cat > .env << 'EOF'
BYBIT_API_KEY=your_testnet_api_key
BYBIT_API_SECRET=your_testnet_api_secret
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_chat_id
EOF

# Edit trading config
nano config/settings.yaml

# Build and start
docker compose up -d
```

### Check Logs

```bash
# All services
docker compose logs -f --tail=50

# Bot only
docker compose logs -f algo-trading-bot

# Dashboard only
docker compose logs -f algo-trading-dashboard
```

### Update

```bash
git fetch origin main
git reset --hard origin/main
docker compose build
docker compose up -d
```

### Stop

```bash
docker compose down
```

## Services

| Service | Port | Purpose |
|---------|------|---------|
| `algo-trading-bot` | — | Trading engine (no external port) |
| `algo-trading-dashboard` | 8080 | Web dashboard |

## Web Dashboard

Accessible at `http://your-vps-ip:8080`.

### Authentication

The dashboard is protected by Bearer token auth. All `/api/*` endpoints (except `/api/health`) require a valid token.

**Getting the token:**
- Auto-generated at startup — visible in dashboard container logs:
  ```bash
  docker compose logs algo-trading-dashboard | head -10
  # Look for: DASHBOARD AUTH TOKEN: <token>
  ```
- Or set a fixed token via env var in `docker-compose.yml`:
  ```yaml
  environment:
    - DASHBOARD_TOKEN=your-fixed-secret-token
  ```

The web UI prompts for the token on first visit and saves it in `localStorage`.

### Features

- Real-time equity curve chart
- Open positions table
- Recent trades history
- Portfolio status (equity, cash, drawdown)

Built with FastAPI + Bearer token auth. Auto-refreshes every 60 seconds.

## Telegram Notifications

The bot sends notifications to your Telegram chat:

| Event | When |
|-------|------|
| Trade Open | New position opened (symbol, side, price, size) |
| Trade Close | Position closed (PnL, holding time) |
| Trailing Stop | Stop-loss updated (new level) |
| Status Report | Every 4 hours (equity, positions, drawdown) |
| Rolling Metrics | 30-day Sharpe, win rate, expectancy |
| Degradation Alert | Rolling Sharpe drops below 0 |

### Get Your Chat ID

1. Message your bot on Telegram
2. Open `https://api.telegram.org/bot<TOKEN>/getUpdates`
3. Find `"chat":{"id": YOUR_CHAT_ID}`

## Running Without Docker

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export BYBIT_API_KEY=your_key
export BYBIT_API_SECRET=your_secret
export TELEGRAM_BOT_TOKEN=your_token
export TELEGRAM_CHAT_ID=your_id

# Run bot
python scripts/run_live.py --mode paper

# Run dashboard (separate terminal)
uvicorn dashboard.app:app --host 0.0.0.0 --port 8080
```

## CI/CD

GitHub Actions workflow (`.github/workflows/`):

1. **ci.yml** — runs on every push: `pytest` + `ruff` lint
2. **deploy.yml** — after CI passes on `main`: SSH to VPS, pull, rebuild, restart

### Setup CI/CD

Add these secrets in GitHub (Settings > Secrets > Actions):

| Secret | Value |
|--------|-------|
| `VPS_HOST` | Your VPS IP address |
| `VPS_USER` | SSH username (e.g., `root`) |
| `VPS_SSH_KEY` | Private SSH key (full content) |

## Security Notes

- Always use **testnet** keys for paper trading
- Never commit `.env` files (already in `.gitignore`)
- `settings.yaml` is in `.gitignore` — use `git add -f` to push config changes
- **Dashboard auth** — Bearer token required for all API endpoints (auto-generated or `DASHBOARD_TOKEN` env var)
- **Token redaction** — Telegram bot tokens are automatically scrubbed from all log output (`TokenRedactingFilter`)
- **httpx suppressed** — httpx/httpcore loggers forced to WARNING level to prevent token leak via URL logging
- **Config validation** — clear error if `settings.yaml` is missing or Docker creates a directory instead of bind-mounting a file
- **API retry** — transient exchange errors (network, rate limit, timeout) are retried with exponential backoff; order creation is never retried

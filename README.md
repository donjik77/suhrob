# Suhrob HOUSE Bot

Telegram-bot for a real estate company in Uzbekistan. Supports client property search, agent property management, subscription billing, and multi-role admin panel — all within a single bot.

## Stack

- Python 3.11+, aiogram 3.x
- PostgreSQL 15 + SQLAlchemy 2.0 (asyncpg)
- Redis (FSM storage)
- APScheduler (payment reminders, scheduled posts)
- Docker + docker-compose

## Quick Start

### 1. Clone and configure

```bash
cp .env.example .env
# Edit .env: set BOT_TOKEN, DEVELOPER_TELEGRAM_ID, DB_PASSWORD
```

### 2. Start services

```bash
docker-compose up -d db redis
```

### 3. Run migrations

```bash
docker-compose run --rm bot alembic upgrade head
```

### 4. Initialize data (first time only)

```bash
docker-compose run --rm bot python scripts/init.py
```

This creates the developer user, company, director, and a 30-day trial subscription.

### 5. Start the bot

```bash
docker-compose up -d bot
```

### Logs

```bash
docker-compose logs -f bot
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `BOT_TOKEN` | Telegram bot token from @BotFather |
| `DATABASE_URL` | PostgreSQL async connection string |
| `REDIS_URL` | Redis connection string |
| `DEVELOPER_TELEGRAM_ID` | Your Telegram user ID |
| `MEDIA_PATH` | Local path for media files |
| `LOG_LEVEL` | INFO / DEBUG / WARNING |
| `TIMEZONE` | e.g. Asia/Tashkent |

## Adding an Agent

Send `/start` to the bot from the agent's Telegram account, then in the database:

```sql
UPDATE users SET role = 'agent', company_id = 1
WHERE telegram_user_id = <agent_telegram_id>;
```

Or ask the developer to implement an agent invitation flow (not in MVP).

## Payment Settings

Update via bot (developer only): send `⚙️ Tizim sozlamalari` then use `/set_key`.

Keys:
- `monthly_price_usd` — subscription price in USD
- `currency_rate_uzs_per_usd` — UZS per 1 USD
- `payment_click_card`, `payment_click_holder`
- `payment_humo_card`, `payment_humo_holder`
- `payment_uzcard_card`, `payment_uzcard_holder`
- `payment_crypto_address`, `payment_crypto_network`

## Backup

```bash
# Manual backup
bash scripts/backup.sh

# Cron (daily at 3am)
0 3 * * * /path/to/suhrob_bot/scripts/backup.sh >> /var/log/suhrob_backup.log 2>&1
```

## Project Structure

```
suhrob_bot/
├── alembic/              # DB migrations
├── locales/uz.py         # All UI strings (Uzbek)
├── src/
│   ├── bot/
│   │   ├── handlers/     # client/, agent/, director/, developer/
│   │   ├── keyboards/    # Inline & reply keyboards
│   │   ├── middlewares/  # auth, subscription, logging
│   │   ├── filters/      # RoleFilter
│   │   └── states/       # FSM states
│   ├── db/
│   │   ├── models.py     # SQLAlchemy ORM models
│   │   ├── repositories/ # CRUD helpers
│   │   └── session.py
│   ├── services/         # Business logic
│   ├── scheduler/        # APScheduler jobs
│   ├── utils/            # currency, formatters, parsers
│   ├── config.py         # pydantic-settings
│   └── main.py           # Entry point
├── scripts/
│   ├── init.py           # First-time setup
│   └── backup.sh         # DB backup
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

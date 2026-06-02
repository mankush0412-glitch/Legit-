# 🚀 Legit Stocks Bot v2.0

Premium Telegram Session Account Selling Bot — Buy Account (OTP), Get Sessions (ZIP), UPI/USDT auto-deposit, Bulk Sessions, Referral %, Data Backup, Render keep-alive.

---

## ✨ All Features

### User Features
- **Main Menu** — Wallet balance display, all options accessible
- **Buy Account** — Select country → auto OTP delivery via Telethon → Get OTP Again → Logout Device
- **Get Sessions** — View your purchased sessions
- **Profile** — Balance, purchase history, referral stats
- **Deposit** — UPI (QR + UTR verification) or Crypto USDT
- **Support** — Message admin or contact support
- **Refer & Earn** — Referral links with bonus
- **History & Stats** — Full purchase and deposit history

### Admin Features (via `/admin` command)
- **Upload Sessions ZIP** — Upload ZIP containing `.session` files per country
- **Manage Prices** — Set price per country
- **Pending Deposits** — Approve/Reject UPI & Crypto deposits
- **All Users** — View user list
- **Broadcast** — Send message to all users
- **Add Balance** — Manually add/deduct balance
- **Bot Settings** — Update UPI ID, USDT address, support username, referral bonus
- **Manage Countries** — Add countries, enable/disable them

---

## Setup

### 1. Clone the repo

```bash
git clone <your-repo-url>
cd telegram-bot
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment

Copy `.env.example` to `.env` and fill in all values:

```bash
cp .env.example .env
```

| Variable | Description |
|----------|-------------|
| `BOT_TOKEN` | Your bot token from @BotFather |
| `ADMIN_IDS` | Your Telegram user ID(s), comma-separated |
| `MONGO_URI` | MongoDB Atlas connection string |
| `DB_NAME` | Database name (default: legit_stocks_bot) |
| `TELEGRAM_API_ID` | From https://my.telegram.org |
| `TELEGRAM_API_HASH` | From https://my.telegram.org |
| `UPI_ID` | Your UPI ID for payments |
| `UPI_NAME` | Your name for UPI |
| `USDT_ADDRESS` | USDT TRC20 wallet address |
| `SUPPORT_USERNAME` | Support Telegram username |
| `REFERRAL_BONUS` | Referral reward in ₹ |

### 4. Run locally

```bash
python -m bot.main
```

---

## Deploy on Render

1. Push this `telegram-bot/` folder to a GitHub repo
2. Create a new **Background Worker** on Render
3. Set **Build Command**: `pip install -r requirements.txt`
4. Set **Start Command**: `python -m bot.main`
5. Add all environment variables from `.env.example`
6. Deploy!

> ✅ Use **Web Service** (not Background Worker) — the FastAPI server provides `/health` for keep-alive pings.

---

## ⚡ Keep-Alive Setup (Free Render)

The bot includes a FastAPI HTTP server that prevents Render from sleeping:

1. Deploy on Render as **Web Service**
2. Copy your URL: `https://your-bot.onrender.com`
3. Set env var: `SELF_PING_URL=https://your-bot.onrender.com/health`
4. Add to **UptimeRobot** (free): monitor `https://your-bot.onrender.com/health` every 5 min

This keeps your bot running **non-stop for months!**

---

## 💰 Auto-Approval Payment System

### UPI (`AUTO_APPROVE_UPI=true`)
- User submits UTR → **balance added instantly** (no admin needed)
- Duplicate UTR check prevents abuse
- Admin still notified for records

### USDT TRC20 (`AUTO_APPROVE_CRYPTO=true`)
- User submits TxHash → bot **verifies on TRON blockchain** (free API, no key needed)
- Checks: correct address + correct amount (±$0.01 tolerance)
- If blockchain verify fails → falls back to admin review

---

## Adding Sessions

1. Login to your bot as admin
2. Send `/admin`
3. Click **Upload Sessions ZIP**
4. Select the country
5. Send a `.zip` file containing `.session` files
6. Add 2FA password as the file caption (leave blank if none)

The bot will automatically:
- Extract and validate each session file
- Connect via Telethon to verify it's authorized
- Read the phone number from the session
- Store it in MongoDB

---

## How OTP Delivery Works

1. User buys an account for a country
2. Bot picks an available session file
3. Bot connects to Telegram via Telethon using the session
4. Bot shows the phone number to the buyer
5. Buyer enters that phone number in Telegram app
6. Telegram sends login OTP **to the active session** (our file)
7. Bot reads the OTP automatically and sends it to the buyer
8. Buyer uses "Get OTP Again" to refresh
9. Buyer uses "Log Out Device" to terminate new sessions added

---

## MongoDB Collections

- `users` — User accounts, balances, referrals
- `sessions` — Session files (stored as binary)
- `countries` — Country config with prices
- `deposits` — Deposit requests and status
- `purchases` — Purchase records with OTP history
- `transactions` — Wallet credit/debit log
- `settings` — Bot configuration

---

## Tech Stack

- **Python 3.11+**
- **aiogram 3.x** — Telegram bot framework
- **motor** — Async MongoDB driver
- **telethon** — Telegram client for session management
- **MongoDB Atlas** — Database
- **qrcode + Pillow** — UPI QR code generation

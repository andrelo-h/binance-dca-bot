import os, time, schedule, requests, threading
from datetime import datetime
from binance.client import Client
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor

load_dotenv()

# ── Config ───────────────────────────────────
SYMBOL      = "ETHUSDT"
USDT_AMOUNT = 30.0
USE_TESTNET = os.getenv("USE_TESTNET", "True") == "True"

# ── Binance Client ───────────────────────────
if USE_TESTNET:
    client = Client(
        os.getenv("TESTNET_API_KEY"),
        os.getenv("TESTNET_SECRET_KEY"),
        testnet=True
    )
    client.RECV_WINDOW = 60000
    print("⚠  TESTNET MODE — no real money")
else:
    client = Client(
        os.getenv("BINANCE_API_KEY"),
        os.getenv("BINANCE_SECRET_KEY")
    )
    client.RECV_WINDOW = 60000
    print("🔴 LIVE MODE")

# ── PostgreSQL Database ───────────────────────
# Railway provides DATABASE_URL automatically when you add a Postgres plugin.
# Locally, add DATABASE_URL to your .env file.
DATABASE_URL = os.getenv("DATABASE_URL")

def get_db():
    """Open a new database connection."""
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def init_db():
    """Create the buys table if it doesn't exist."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS buys (
                    id          SERIAL PRIMARY KEY,
                    timestamp   TIMESTAMPTZ DEFAULT NOW(),
                    symbol      TEXT NOT NULL,
                    price       NUMERIC(18,8),
                    quantity    NUMERIC(18,8),
                    usdt_spent  NUMERIC(18,8),
                    order_id    TEXT
                )
            """)
        conn.commit()
    print("✅ Database ready")

# ── Telegram ──────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram(message):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"},
            timeout=10
        )
    except Exception as e:
        print(f"Telegram error: {e}")

def get_updates(offset=None):
    try:
        params = {"timeout": 30}
        if offset:
            params["offset"] = offset
        resp = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
            params=params,
            timeout=35
        )
        return resp.json().get("result", [])
    except Exception as e:
        print(f"Telegram poll error: {e}")
        return []

# ── Status Report ─────────────────────────────
def build_status_report():
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT price, quantity, usdt_spent, timestamp
                    FROM buys ORDER BY timestamp ASC
                """)
                rows = cur.fetchall()

        if not rows:
            return "📊 *DCA Bot Status*\n\nNo buys recorded yet."

        total_eth   = sum(float(r["quantity"])   for r in rows)
        total_spent = sum(float(r["usdt_spent"]) for r in rows)
        avg_price   = total_spent / total_eth if total_eth > 0 else 0
        num_buys    = len(rows)
        first_buy   = str(rows[0]["timestamp"])[:10]
        last_buy    = str(rows[-1]["timestamp"])[:10]

        try:
            current_price = float(client.get_symbol_ticker(symbol=SYMBOL)["price"])
            current_value = total_eth * current_price
            pnl_usdt      = current_value - total_spent
            pnl_pct       = (pnl_usdt / total_spent * 100)
            pnl_emoji     = "📈" if pnl_usdt >= 0 else "📉"
            pnl_sign      = "+" if pnl_usdt >= 0 else ""
            price_line    = f"💰 Current price:   ${current_price:,.2f}\n"
            value_line    = f"💼 Portfolio value:  ${current_value:,.2f}\n"
            pnl_line      = f"{pnl_emoji} Unrealized P&L:  {pnl_sign}${pnl_usdt:,.2f} ({pnl_sign}{pnl_pct:.1f}%)\n"
        except Exception:
            price_line = "💰 Current price: N/A\n"
            value_line = ""
            pnl_line   = ""

        mode      = "🟡 TESTNET" if USE_TESTNET else "🔴 LIVE"
        readiness = f"{num_buys}/4 testnet buys" if USE_TESTNET else "LIVE MODE"

        return (
            f"📊 *DCA Bot Status* — {mode}\n"
            f"─────────────────────\n"
            f"🪙 Total ETH:      `{total_eth:.6f} ETH`\n"
            f"💵 Total invested: `${total_spent:,.2f} USDT`\n"
            f"📐 Avg buy price:  `${avg_price:,.2f}`\n"
            f"🔢 Total buys:     {num_buys} ({readiness})\n"
            f"📅 First buy:      {first_buy}\n"
            f"📅 Last buy:       {last_buy}\n"
            f"─────────────────────\n"
            f"{price_line}"
            f"{value_line}"
            f"{pnl_line}"
            f"─────────────────────\n"
            f"⏰ Next buy: Monday 10:00"
        )
    except Exception as e:
        return f"❌ Status error: {str(e)}"

# ── Telegram Command Listener ─────────────────
def telegram_listener():
    print("📨 Telegram listener started — send /status or /help to your bot")
    offset = None
    while True:
        updates = get_updates(offset)
        for update in updates:
            offset = update["update_id"] + 1
            message = update.get("message", {})
            text    = message.get("text", "").strip().lower()
            chat_id = str(message.get("chat", {}).get("id", ""))

            if chat_id != str(TELEGRAM_CHAT_ID):
                continue  # ignore messages from other chats

            if text == "/status":
                send_telegram(build_status_report())
            elif text == "/help":
                send_telegram(
                    "🤖 *DCA Bot Commands*\n\n"
                    "/status — P&L report and portfolio summary\n"
                    "/help   — show this message"
                )
            elif text.startswith("/"):
                send_telegram(f"❓ Unknown command: `{text}`\nTry /help")

        time.sleep(5)

# ── DCA Buy ───────────────────────────────────
def execute_dca():
    try:
        price = float(client.get_symbol_ticker(symbol=SYMBOL)["price"])
        info  = client.get_symbol_info(SYMBOL)
        step  = float([f["stepSize"] for f in info["filters"]
                       if f["filterType"] == "LOT_SIZE"][0])
        decs  = len(f"{step:.8f}".rstrip("0").split(".")[1])
        qty   = round(USDT_AMOUNT / price, decs)

        order        = client.order_market_buy(symbol=SYMBOL, quantity=qty)
        filled_price = float(order["fills"][0]["price"])
        fee          = float(order["fills"][0]["commission"])

        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO buys (symbol, price, quantity, usdt_spent, order_id)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (SYMBOL, filled_price, qty, USDT_AMOUNT, str(order["orderId"]))
                )
            conn.commit()

        mode = "[TESTNET]" if USE_TESTNET else "[LIVE]"
        send_telegram(
            f"{mode} ✅ *DCA Buy Executed*\n"
            f"Bought: `{qty} ETH`\n"
            f"Price:  `${filled_price:,.2f}`\n"
            f"Fee:    `${fee:.4f}`\n"
            f"Time:   `{datetime.now().strftime('%Y-%m-%d %H:%M')}`"
        )
        print(f"✅ Bought {qty} ETH at ${filled_price:,.2f}")

    except Exception as e:
        send_telegram(f"❌ DCA Bot ERROR: `{str(e)}`")
        print(f"Error: {e}")

# ── Boot ──────────────────────────────────────
init_db()

# Start Telegram listener in background thread
threading.Thread(target=telegram_listener, daemon=True).start()

# Schedule weekly buy
schedule.every().monday.at("10:00").do(execute_dca)

# On testnet: run one buy immediately so you can verify it works
if USE_TESTNET:
    print("Running first test buy now...")
    execute_dca()

print("Bot running. Next scheduled buy: Monday 10:00")
print("Send /status to your Telegram bot to check P&L anytime.")

while True:
    schedule.run_pending()
    time.sleep(60)
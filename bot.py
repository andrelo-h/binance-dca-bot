import os, time, sqlite3, schedule, requests
from datetime import datetime
from binance.client import Client
from dotenv import load_dotenv

load_dotenv()

# ── Config ───────────────────────────────────
SYMBOL      = "ETHUSDT"
USDT_AMOUNT = 30.0
USE_TESTNET = os.getenv("USE_TESTNET", "True") == "True"

# ── Client ───────────────────────────────────
# ── Client ───────────────────────────────────
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

# ── Database ─────────────────────────────────
conn = sqlite3.connect("database.db", check_same_thread=False)
conn.execute("""
    CREATE TABLE IF NOT EXISTS buys (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT, symbol TEXT, price REAL,
        quantity REAL, usdt_spent REAL, order_id TEXT
    )
""")
conn.commit()

# ── Telegram ─────────────────────────────────
def send_telegram(message):
    token   = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message},
            timeout=10
        )
    except Exception as e:
        print(f"Telegram error: {e}")

# ── DCA Buy ──────────────────────────────────
def execute_dca():
    try:
        price = float(client.get_symbol_ticker(symbol=SYMBOL)["price"])
        info  = client.get_symbol_info(SYMBOL)
        step  = float([f["stepSize"] for f in info["filters"]
                       if f["filterType"] == "LOT_SIZE"][0])
        decs  = len(f"{step:.8f}".rstrip("0").split(".")[1])
        qty   = round(USDT_AMOUNT / price, decs)

        order = client.order_market_buy(symbol=SYMBOL, quantity=qty)
        filled_price = float(order["fills"][0]["price"])
        fee          = float(order["fills"][0]["commission"])

        conn.execute(
            "INSERT INTO buys VALUES (NULL,?,?,?,?,?,?)",
            (datetime.now().isoformat(), SYMBOL,
             filled_price, qty, USDT_AMOUNT, order["orderId"])
        )
        conn.commit()

        mode = "[TESTNET]" if USE_TESTNET else "[LIVE]"
        send_telegram(
            f"{mode} ✅ DCA Buy\n"
            f"Bought: {qty} ETH\n"
            f"Price: ${filled_price:,.2f}\n"
            f"Fee: ${fee:.4f}\n"
            f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
        print(f"✅ Bought {qty} ETH at ${filled_price:,.2f}")

    except Exception as e:
        send_telegram(f"❌ DCA Bot ERROR: {str(e)}")
        print(f"Error: {e}")

# ── Schedule: Every Monday at 10:00 ──────────
schedule.every().monday.at("10:00").do(execute_dca)

# ── Test immediately on start ─────────────────
if USE_TESTNET:
    print("Running first test buy now...")
    execute_dca()  # fires once on startup so you see it work

print("Bot running. Next scheduled buy: Monday 10:00")
while True:
    schedule.run_pending()
    time.sleep(60)
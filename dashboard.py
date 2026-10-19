import os
import sqlite3
import pandas as pd
import streamlit as st
from datetime import datetime
from binance.client import Client
from dotenv import load_dotenv

load_dotenv()

# ─── Page config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="DCA Bot Dashboard",
    page_icon="📊",
    layout="wide",
)

# ─── Theme override ───────────────────────────────────────────────────────────
st.markdown("""
<style>
    .block-container { padding-top: 1.5rem; }
    .metric-card {
        background: #1e222d;
        border-radius: 12px;
        padding: 1.2rem 1.5rem;
        border: 1px solid #2e3349;
    }
    .metric-label { font-size: 0.78rem; color: #8b96a5; text-transform: uppercase; letter-spacing: 0.07em; }
    .metric-value { font-size: 2rem; font-weight: 700; color: #f0f2f5; margin: 0.15rem 0; }
    .metric-delta-pos { font-size: 0.9rem; color: #00c96d; }
    .metric-delta-neg { font-size: 0.9rem; color: #ff4c6a; }
    .stDataFrame { border-radius: 10px; overflow: hidden; }
    h1 { font-size: 1.6rem !important; }
    h2 { font-size: 1.1rem !important; color: #8b96a5 !important; font-weight: 400 !important; }
</style>
""", unsafe_allow_html=True)

# ─── Binance client (read-only, testnet or live) ──────────────────────────────
USE_TESTNET = os.getenv("USE_TESTNET", "True") == "True"

@st.cache_resource(show_spinner=False)
def get_client():
    if USE_TESTNET:
        return Client(
            os.getenv("TESTNET_API_KEY"),
            os.getenv("TESTNET_SECRET_KEY"),
            testnet=True,
            {"recvWindow": 60000},
        )
    return Client(
        os.getenv("BINANCE_API_KEY"),
        os.getenv("BINANCE_SECRET_KEY"),
        {"recvWindow": 60000},
    )

# ─── Data loaders ────────────────────────────────────────────────────────────
DB_PATH = os.path.join(os.path.dirname(__file__), "database.db")

def load_buys() -> pd.DataFrame:
    """Read all DCA buys from SQLite."""
    if not os.path.exists(DB_PATH):
        return pd.DataFrame(columns=["id","timestamp","symbol","price","quantity","usdt_spent","order_id"])
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("SELECT * FROM buys ORDER BY timestamp ASC", conn, parse_dates=["timestamp"])
    conn.close()
    return df

def get_current_price(symbol: str = "ETHUSDT") -> float:
    try:
        client = get_client()
        return float(client.get_symbol_ticker(symbol=symbol)["price"])
    except Exception:
        return 0.0

# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    mode_badge = "🟡 TESTNET" if USE_TESTNET else "🔴 LIVE"

    st.title(f"📊 DCA Bot Dashboard  {mode_badge}")
    st.markdown("## ETH/USDT · Dollar-Cost Averaging tracker")

    df = load_buys()

    # ── Sidebar controls ──────────────────────────────────────────────────────
    with st.sidebar:
        st.image("https://cryptologos.cc/logos/ethereum-eth-logo.png", width=60)
        st.markdown("### DCA Bot")
        st.markdown("Automated weekly ETH buys")
        st.divider()
        auto_refresh = st.checkbox("Auto-refresh (30s)", value=False)
        if auto_refresh:
            import time
            st.info(f"Last updated: {datetime.now().strftime('%H:%M:%S')}")
        if st.button("🔄 Refresh now"):
            st.cache_resource.clear()
            st.rerun()
        st.divider()
        st.caption("Bot runs every Monday 10:00\nTestnet → Live after 4 buys")

    # ── Empty state ───────────────────────────────────────────────────────────
    if df.empty:
        st.info("No buys recorded yet. Run the bot to populate the dashboard.")
        st.code("python bot.py", language="bash")
        return

    # ── KPI calculations ──────────────────────────────────────────────────────
    total_eth      = df["quantity"].sum()
    total_spent    = df["usdt_spent"].sum()
    avg_price      = total_spent / total_eth if total_eth > 0 else 0
    num_buys       = len(df)
    current_price  = get_current_price()
    current_value  = total_eth * current_price
    pnl_usdt       = current_value - total_spent
    pnl_pct        = (pnl_usdt / total_spent * 100) if total_spent > 0 else 0
    pnl_color      = "#00c96d" if pnl_usdt >= 0 else "#ff4c6a"
    pnl_sign       = "+" if pnl_usdt >= 0 else ""

    # ── KPI row ───────────────────────────────────────────────────────────────
    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.metric("Total ETH", f"{total_eth:.6f} ETH")
    with col2:
        st.metric("Total Invested", f"${total_spent:,.2f}")
    with col3:
        st.metric("Avg Buy Price", f"${avg_price:,.2f}")
    with col4:
        st.metric("Current Price", f"${current_price:,.2f}" if current_price else "N/A")
    with col5:
        delta_str = f"{pnl_sign}${pnl_usdt:,.2f} ({pnl_sign}{pnl_pct:.1f}%)" if current_price else "N/A"
        st.metric("Unrealized P&L", f"${current_value:,.2f}" if current_price else "N/A", delta=delta_str)

    st.divider()

    # ── Charts ────────────────────────────────────────────────────────────────
    chart_col, table_col = st.columns([3, 2])

    with chart_col:
        st.subheader("📈 Portfolio Value vs. Cost Basis")

        df_chart = df.copy()
        df_chart = df_chart.sort_values("timestamp")
        df_chart["cumulative_eth"]   = df_chart["quantity"].cumsum()
        df_chart["cumulative_spent"] = df_chart["usdt_spent"].cumsum()
        df_chart["portfolio_value"]  = df_chart["cumulative_eth"] * current_price
        df_chart["avg_price_line"]   = df_chart["cumulative_spent"] / df_chart["cumulative_eth"]

        chart_data = df_chart[["timestamp", "cumulative_spent", "portfolio_value"]].set_index("timestamp")
        chart_data.columns = ["Cost Basis (USDT)", "Portfolio Value (USDT)"]

        st.line_chart(chart_data, use_container_width=True, height=280)

        # Average buy price vs current price bar
        if avg_price > 0 and current_price > 0:
            price_ratio = current_price / avg_price
            if price_ratio >= 1:
                st.success(f"✅ Current price (${current_price:,.2f}) is **{(price_ratio-1)*100:.1f}% above** your avg buy price (${avg_price:,.2f})")
            else:
                st.warning(f"⬇️ Current price (${current_price:,.2f}) is **{(1-price_ratio)*100:.1f}% below** your avg buy price (${avg_price:,.2f}) — DCA is working, keep buying")

    with table_col:
        st.subheader(f"📋 Buy History ({num_buys} buys)")

        display_df = df[["timestamp", "price", "quantity", "usdt_spent"]].copy()
        display_df["timestamp"] = display_df["timestamp"].dt.strftime("%Y-%m-%d %H:%M")
        display_df.columns = ["Date", "Price ($)", "ETH qty", "USDT spent"]
        display_df["Price ($)"]  = display_df["Price ($)"].apply(lambda x: f"${x:,.2f}")
        display_df["ETH qty"]    = display_df["ETH qty"].apply(lambda x: f"{x:.6f}")
        display_df["USDT spent"] = display_df["USDT spent"].apply(lambda x: f"${x:.2f}")

        st.dataframe(display_df, use_container_width=True, hide_index=True, height=280)

    st.divider()

    # ── DCA Stats ─────────────────────────────────────────────────────────────
    st.subheader("📊 DCA Statistics")
    stat1, stat2, stat3, stat4 = st.columns(4)

    with stat1:
        st.metric("Number of buys", num_buys)
    with stat2:
        if num_buys >= 2:
            first_buy  = df["timestamp"].min()
            last_buy   = df["timestamp"].max()
            days_active = (last_buy - first_buy).days
            st.metric("Days active", days_active)
        else:
            st.metric("Days active", "< 1 week")
    with stat3:
        best_buy = df.loc[df["price"].idxmin()]
        st.metric("Best buy price", f"${best_buy['price']:,.2f}")
    with stat4:
        avg_per_week = total_spent / max(num_buys, 1)
        st.metric("Avg per buy", f"${avg_per_week:.2f}")

    # ── Cumulative ETH chart ──────────────────────────────────────────────────
    st.subheader("🟢 ETH Accumulated Over Time")
    eth_chart = df_chart[["timestamp", "cumulative_eth"]].set_index("timestamp")
    eth_chart.columns = ["ETH Accumulated"]
    st.area_chart(eth_chart, use_container_width=True, height=200)

    # ── Roadmap progress ──────────────────────────────────────────────────────
    st.divider()
    st.subheader("🗺️ Testnet Progress → Live Readiness")
    progress_pct = min(num_buys / 4, 1.0)
    st.progress(progress_pct, text=f"{num_buys}/4 testnet buys complete {'✅ READY FOR LIVE' if num_buys >= 4 else '— keep running testnet'}")

    if num_buys >= 4:
        st.success("🚀 You've completed 4 testnet buy cycles. You're ready to switch to LIVE mode. Change `USE_TESTNET=False` in your `.env` file.")
    else:
        weeks_left = 4 - num_buys
        st.info(f"⏳ {weeks_left} more weekly buy{'s' if weeks_left > 1 else ''} needed before going live. Bot runs every Monday at 10:00.")

    # ── Auto refresh ──────────────────────────────────────────────────────────
    if auto_refresh:
        import time
        time.sleep(30)
        st.rerun()

if __name__ == "__main__":
    main()
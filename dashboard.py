import os
import streamlit as st
import pandas as pd
from datetime import datetime
from binance.client import Client
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor

load_dotenv()

# ─── Page config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="DCA Bot Dashboard",
    page_icon="📊",
    layout="wide",
)

# ─── Password protection ─────────────────────────────────────────────────────
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "changeme")

def check_password():
    """Show login form and block access until correct password is entered."""
    if st.session_state.get("authenticated"):
        return True

    st.markdown("""
    <style>
        .login-box {
            max-width: 380px;
            margin: 6rem auto;
            padding: 2.5rem;
            background: #1e222d;
            border-radius: 14px;
            border: 1px solid #2e3349;
            text-align: center;
        }
        .login-title { font-size: 1.5rem; font-weight: 700; color: #f0b429; margin-bottom: 0.5rem; }
        .login-sub   { font-size: 0.85rem; color: #8b96a5; margin-bottom: 1.5rem; }
    </style>
    <div class="login-box">
        <div class="login-title">📊 DCA Bot Dashboard</div>
        <div class="login-sub">Enter your password to continue</div>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        password = st.text_input("Password", type="password", label_visibility="collapsed",
                                  placeholder="Enter password…")
        if st.button("Unlock Dashboard", use_container_width=True):
            if password == DASHBOARD_PASSWORD:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("Incorrect password")
    return False

if not check_password():
    st.stop()  # everything below only runs after login

# ─── Theme ───────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .block-container { padding-top: 1.5rem; }
    .stDataFrame { border-radius: 10px; overflow: hidden; }
    h1 { font-size: 1.6rem !important; }
    h2 { font-size: 1.1rem !important; color: #8b949e !important; font-weight: 400 !important; }
</style>
""", unsafe_allow_html=True)

# ─── Binance client ───────────────────────────────────────────────────────────
USE_TESTNET = os.getenv("USE_TESTNET", "True") == "True"

@st.cache_resource(show_spinner=False)
def get_binance_client():
    if USE_TESTNET:
        c = Client(os.getenv("TESTNET_API_KEY"), os.getenv("TESTNET_SECRET_KEY"), testnet=True)
    else:
        c = Client(os.getenv("BINANCE_API_KEY"), os.getenv("BINANCE_SECRET_KEY"))
    c.RECV_WINDOW = 60000
    return c

# ─── Database ────────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL")

def load_buys() -> pd.DataFrame:
    """Read all DCA buys from PostgreSQL."""
    try:
        with psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM buys ORDER BY timestamp ASC")
                rows = cur.fetchall()
        if not rows:
            return pd.DataFrame(columns=["id","timestamp","symbol","price","quantity","usdt_spent","order_id"])
        df = pd.DataFrame(rows)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        for col in ["price", "quantity", "usdt_spent"]:
            df[col] = df[col].astype(float)
        return df
    except Exception as e:
        st.error(f"Database error: {e}")
        return pd.DataFrame(columns=["id","timestamp","symbol","price","quantity","usdt_spent","order_id"])

def get_current_price(symbol: str = "ETHUSDT") -> float:
    try:
        return float(get_binance_client().get_symbol_ticker(symbol=symbol)["price"])
    except Exception:
        return 0.0

# ─── Main dashboard ───────────────────────────────────────────────────────────
def main():
    mode_badge = "🟡 TESTNET" if USE_TESTNET else "🔴 LIVE"
    st.title(f"📊 DCA Bot Dashboard  {mode_badge}")
    st.markdown("## ETH/USDT · Dollar-Cost Averaging tracker")

    df = load_buys()

    # ── Sidebar ──────────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("### 🤖 DCA Bot")
        st.markdown("Automated weekly ETH accumulation")
        st.divider()

        if st.button("🔄 Refresh data"):
            st.cache_resource.clear()
            st.rerun()

        st.divider()
        st.caption("Buys every Monday at 10:00\nTestnet → Live after 4 cycles")
        st.divider()

        if st.button("🔒 Log out"):
            st.session_state["authenticated"] = False
            st.rerun()

    # ── Empty state ───────────────────────────────────────────────────────────
    if df.empty:
        st.info("No buys recorded yet. Run the bot to populate the dashboard.")
        st.code("python bot.py", language="bash")
        return

    # ── KPIs ─────────────────────────────────────────────────────────────────
    total_eth     = df["quantity"].sum()
    total_spent   = df["usdt_spent"].sum()
    avg_price     = total_spent / total_eth if total_eth > 0 else 0
    num_buys      = len(df)
    current_price = get_current_price()
    current_value = total_eth * current_price
    pnl_usdt      = current_value - total_spent
    pnl_pct       = (pnl_usdt / total_spent * 100) if total_spent > 0 else 0
    pnl_sign      = "+" if pnl_usdt >= 0 else ""

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Total ETH", f"{total_eth:.6f}")
    with col2:
        st.metric("Total Invested", f"${total_spent:,.2f}")
    with col3:
        st.metric("Avg Buy Price", f"${avg_price:,.2f}")
    with col4:
        st.metric("Current Price", f"${current_price:,.2f}" if current_price else "N/A")
    with col5:
        delta = f"{pnl_sign}${pnl_usdt:,.2f} ({pnl_sign}{pnl_pct:.1f}%)" if current_price else None
        st.metric("Unrealized P&L", f"${current_value:,.2f}" if current_price else "N/A", delta=delta)

    st.divider()

    # ── Charts ────────────────────────────────────────────────────────────────
    chart_col, table_col = st.columns([3, 2])

    df_chart = df.sort_values("timestamp").copy()
    df_chart["cum_eth"]    = df_chart["quantity"].cumsum()
    df_chart["cum_spent"]  = df_chart["usdt_spent"].cumsum()
    df_chart["port_value"] = df_chart["cum_eth"] * current_price

    with chart_col:
        st.subheader("📈 Portfolio Value vs Cost Basis")
        chart_data = df_chart[["timestamp","cum_spent","port_value"]].set_index("timestamp")
        chart_data.columns = ["Cost Basis (USDT)", "Portfolio Value (USDT)"]
        st.line_chart(chart_data, use_container_width=True, height=280)

        if avg_price > 0 and current_price > 0:
            ratio = current_price / avg_price
            if ratio >= 1:
                st.success(f"✅ ETH is **{(ratio-1)*100:.1f}% above** your avg buy (${avg_price:,.2f})")
            else:
                st.warning(f"⬇️ ETH is **{(1-ratio)*100:.1f}% below** your avg buy — DCA keeps working, stay the course")

    with table_col:
        st.subheader(f"📋 Buy History ({num_buys} buys)")
        display = df[["timestamp","price","quantity","usdt_spent"]].copy()
        display["timestamp"]  = display["timestamp"].dt.strftime("%Y-%m-%d %H:%M")
        display["price"]      = display["price"].apply(lambda x: f"${x:,.2f}")
        display["quantity"]   = display["quantity"].apply(lambda x: f"{x:.6f}")
        display["usdt_spent"] = display["usdt_spent"].apply(lambda x: f"${x:.2f}")
        display.columns = ["Date", "Price ($)", "ETH qty", "USDT spent"]
        st.dataframe(display, use_container_width=True, hide_index=True, height=280)

    st.divider()

    # ── Stats row ─────────────────────────────────────────────────────────────
    st.subheader("📊 DCA Statistics")
    s1, s2, s3, s4 = st.columns(4)
    with s1:
        st.metric("Total buys", num_buys)
    with s2:
        if num_buys >= 2:
            days = (df["timestamp"].max() - df["timestamp"].min()).days
            st.metric("Days active", days)
        else:
            st.metric("Days active", "< 1 week")
    with s3:
        best = df.loc[df["price"].idxmin()]
        st.metric("Best buy price", f"${float(best['price']):,.2f}")
    with s4:
        st.metric("Avg per buy", f"${total_spent / max(num_buys, 1):.2f}")

    # ── ETH accumulated area chart ────────────────────────────────────────────
    st.subheader("🟢 ETH Accumulated Over Time")
    eth_chart = df_chart[["timestamp","cum_eth"]].set_index("timestamp")
    eth_chart.columns = ["ETH Accumulated"]
    st.area_chart(eth_chart, use_container_width=True, height=200)

    # ── Fee tracker ───────────────────────────────────────────────────────────
    st.divider()
    st.subheader("💸 Fee Awareness")
    # Estimate fees as ~0.1% per trade (Binance standard)
    estimated_fees = total_spent * 0.001 * num_buys
    fee_pct        = (estimated_fees / total_spent * 100) if total_spent > 0 else 0
    f1, f2, f3 = st.columns(3)
    with f1:
        st.metric("Est. total fees paid", f"${estimated_fees:.4f}")
    with f2:
        st.metric("Fee % of invested", f"{fee_pct:.3f}%")
    with f3:
        st.metric("Fee per buy (0.1%)", f"${USDT_AMOUNT * 0.001:.3f}" if 'USDT_AMOUNT' not in dir() else "$0.030")

    # ── Testnet readiness progress ─────────────────────────────────────────────
    st.divider()
    st.subheader("🗺️ Testnet Progress → Live Readiness")
    progress = min(num_buys / 4, 1.0)
    label    = f"{num_buys}/4 testnet buys complete"
    if num_buys >= 4:
        label += " ✅ READY FOR LIVE"
    st.progress(progress, text=label)

    if num_buys >= 4:
        st.success("🚀 4 testnet cycles complete. Set `USE_TESTNET=False` in your Railway environment variables to go live.")
    else:
        st.info(f"⏳ {4 - num_buys} more Monday buy{'s' if 4-num_buys > 1 else ''} until live readiness. Bot runs automatically.")

USDT_AMOUNT = float(os.getenv("USDT_AMOUNT", "30.0"))

if __name__ == "__main__":
    main()
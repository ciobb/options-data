"""Streamlit dashboard for the US Stock Options Scanner.

Enter a stock ticker to see the top 10 calls and puts ranked by open interest.

Usage:
    streamlit run app.py
"""

from __future__ import annotations

import os
from datetime import datetime

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from fetcher import fetch_chains
from oi_history import save_snapshot, get_changes_for_ticker, get_history_table, snapshot_count, cleanup_old_snapshots
from oi_history import get_iv_stats_for_ticker
from chatbot import ask_deepseek

st.set_page_config(page_title="Options Scanner", page_icon="📊", layout="wide")


# ---- Data helpers ----
def top_by_oi(df: pd.DataFrame, ticker: str, option_type: str, n: int = 10,
              expiry: str | None = None) -> pd.DataFrame:
    subset = df[(df["ticker"] == ticker) & (df["optionType"] == option_type)]
    if expiry:
        subset = subset[subset["expiration"] == expiry]
    if subset.empty or "openInterest" not in subset.columns:
        return pd.DataFrame()
    return subset.sort_values("openInterest", ascending=False).head(n)


def _show_table(df: pd.DataFrame, oi_changes: dict[str, dict] | None = None,
                iv_stats: dict[str, dict] | None = None) -> None:
    if df.empty:
        st.info("No data.")
        return

    base_cols = ["strike", "expiration", "impliedVolatility", "openInterest",
                 "volume", "lastPrice", "bid", "ask", "contractSymbol"]
    greek_cols = [c for c in ["delta", "gamma", "theta"] if c in df.columns]
    available = [c for c in base_cols + greek_cols if c in df.columns]

    # Keep optionType for breakeven/prob calc, remove before display
    opt_types = df["optionType"].values if "optionType" in df.columns else None
    display = df[available].copy()

    display["impliedVolatility"] = (display["impliedVolatility"] * 100).round(1)
    display["strike"] = display["strike"].round(2)
    display["openInterest"] = display["openInterest"].astype("Int64")
    display["volume"] = display["volume"].astype("Int64")

    # Greeks formatting
    if "delta" in display.columns:
        display["delta"] = display["delta"].round(4)
    if "gamma" in display.columns:
        display["gamma"] = display["gamma"].round(4)
    if "theta" in display.columns:
        display["theta"] = display["theta"].round(4)

    # Breakeven: strike + ask (call) or strike - ask (put)
    breakevens: list[float] = []
    for i in range(len(display)):
        strike = display.iloc[i]["strike"]
        ask = display.iloc[i].get("ask")
        if ask is None or pd.isna(ask) or ask == 0:
            breakevens.append(0.0)
            continue
        opt_type = opt_types[i] if opt_types is not None else ""
        if opt_type == "call":
            breakevens.append(round(strike + ask, 2))
        elif opt_type == "put":
            breakevens.append(round(strike - ask, 2))
        else:
            breakevens.append(0.0)
    display["Breakeven"] = breakevens

    # Profit probability (≈ |delta| for puts, delta for calls)
    if "delta" in display.columns:
        probs: list[str] = []
        for i in range(len(display)):
            d = display.iloc[i]["delta"]
            if pd.isna(d):
                probs.append("—")
                continue
            opt_type = opt_types[i] if opt_types is not None else ""
            if opt_type == "put":
                prob = abs(d)
            else:
                prob = d
            probs.append(f"{prob * 100:.1f}%")
        display["Prob ITM"] = probs

    # IV Rank / Percentile
    if iv_stats:
        iv_ranks: list[str] = []
        iv_pcts: list[str] = []
        for _, row in display.iterrows():
            c = row["contractSymbol"]
            iv_st = iv_stats.get(c)
            if iv_st:
                iv_ranks.append(f"{iv_st['iv_rank']:.0f}")
                iv_pcts.append(f"{iv_st['iv_percentile']:.0f}%")
            else:
                iv_ranks.append("—")
                iv_pcts.append("—")
        display["IV Rank"] = iv_ranks
        display["IV %ile"] = iv_pcts

    # OI changes
    if oi_changes:
        oi_deltas: list[str] = []
        for _, row in display.iterrows():
            c = row["contractSymbol"]
            ch = oi_changes.get(c)
            if ch:
                sign = "+" if ch["change"] >= 0 else ""
                oi_deltas.append(f"{sign}{ch['change']:,} ({ch['pct_change']:+.1f}%)")
            else:
                oi_deltas.append("—")
        display["OI Δ"] = oi_deltas

    display = display.rename(columns={
        "strike": "Strike", "expiration": "Expiry",
        "impliedVolatility": "IV %", "openInterest": "Open Int",
        "volume": "Volume", "lastPrice": "Last",
        "bid": "Bid", "ask": "Ask", "contractSymbol": "Contract",
        "delta": "Delta", "gamma": "Gamma", "theta": "Theta",
    })

    col_config = {
        "IV %": st.column_config.NumberColumn(format="%.1f%%"),
        "Strike": st.column_config.NumberColumn(format="%.2f"),
        "Open Int": st.column_config.NumberColumn(format="%d"),
        "Volume": st.column_config.NumberColumn(format="%d"),
        "Last": st.column_config.NumberColumn(format="%.2f"),
        "Bid": st.column_config.NumberColumn(format="%.2f"),
        "Ask": st.column_config.NumberColumn(format="%.2f"),
        "Breakeven": st.column_config.NumberColumn(format="%.2f"),
        "Delta": st.column_config.NumberColumn(format="%.4f"),
        "Gamma": st.column_config.NumberColumn(format="%.4f"),
        "Theta": st.column_config.NumberColumn(format="%.4f"),
    }

    st.dataframe(display, width="stretch", hide_index=True, column_config=col_config)


# ---- Cached fetches ----
@st.cache_data(ttl=300, show_spinner=False)
def _fetch_cboe(ticker: str) -> pd.DataFrame:
    return fetch_chains([ticker], use_cboe=True)


@st.cache_data(ttl=600, show_spinner=False)
def _fetch_yfinance(ticker: str, max_workers: int = 8) -> pd.DataFrame:
    return fetch_chains([ticker], max_workers=max_workers)


def _fetch_ib(ticker: str, ib_host: str, ib_port: int, ib_client_id: int,
               ib_max_exps: int, ib_strike_min: float, ib_strike_max: float) -> pd.DataFrame:
    return fetch_chains(
        [ticker],
        ib_host=ib_host, ib_port=ib_port, ib_client_id=ib_client_id,
        ib_max_expirations=ib_max_exps,
        ib_min_strike_pct=ib_strike_min, ib_max_strike_pct=ib_strike_max,
    )


# ---- Main ----
def main() -> None:
    st.title("📊 Options Scanner")
    st.caption("Top calls & puts by open interest — free CBOE data, accurate OI")

    # Sidebar
    with st.sidebar:
        st.header("⚙️ Settings")
        provider = st.selectbox(
            "Data Provider",
            ["CBOE (free, OI ✅)", "yfinance", "Interactive Brokers"],
            index=0,
        )
        use_ib = provider == "Interactive Brokers"
        use_cboe = provider == "CBOE (free, OI ✅)"

        ib_host = ib_port = ib_client_id = ib_max_exps = ib_strike_min = ib_strike_max = None
        max_workers = 8
        if use_ib:
            st.subheader("🔗 IB Connection")
            ib_host = st.text_input("Host", value="127.0.0.1")
            ib_port = st.number_input("Port", value=7496, min_value=1000, max_value=9999)
            ib_client_id = st.number_input("Client ID", value=1, min_value=1, max_value=9999)
            ib_max_exps = st.slider("Max expirations", 1, 12, 4)
            ib_strike_min = st.slider("Strike min %", 50, 95, 70) / 100.0
            ib_strike_max = st.slider("Strike max %", 105, 200, 130) / 100.0
        elif not use_cboe:
            max_workers = st.slider("Concurrent fetchers", 2, 16, 8)

        top_n = st.slider("Show top N", 5, 50, 10)

        st.divider()

        if st.button("🗑️ Clear Cache", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

        st.caption(
            "⏰ GitHub Actions: Daily S&P 500 scan\n"
            "📦 Data retention: 365 days"
        )

        # ---- AI Chat in sidebar ----
        st.divider()
        st.subheader("🤖 AI Chat")

        if "chat_history" not in st.session_state:
            st.session_state["chat_history"] = []

        if df is not None and not df.empty:
            st.caption(f"Context: {ticker}, {len(df):,} contracts")

        for msg in st.session_state["chat_history"][-6:]:  # show last 6 msgs
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        if question := st.chat_input("Ask about the data..."):
            deepseek_key = os.getenv("DEEPSEEK_API_KEY", "")
            st.session_state["chat_history"].append({"role": "user", "content": question})
            with st.chat_message("assistant"):
                with st.spinner("..."):
                    answer = ask_deepseek(question, df, ticker, deepseek_key)
                st.markdown(answer)
                st.session_state["chat_history"].append({"role": "assistant", "content": answer})

        if st.session_state["chat_history"]:
            if st.button("🗑️ Clear Chat", use_container_width=True, key="clear_chat"):
                st.session_state["chat_history"] = []
                st.rerun()
    col1, col2 = st.columns([4, 1])
    with col1:
        ticker = st.text_input(
            "Stock Ticker",
            value="INTC",
            placeholder="e.g. AAPL, NVDA, INTC",
            max_chars=10,
        ).strip().upper()

    if not ticker:
        st.info("Enter a ticker above.")
        st.stop()

    # Fetch
    with st.spinner(f"Fetching {ticker} options data..."):
        try:
            if use_ib:
                df = _fetch_ib(ticker, ib_host, ib_port, ib_client_id,
                               ib_max_exps, ib_strike_min, ib_strike_max)
            elif use_cboe:
                df = _fetch_cboe(ticker)
            else:
                df = _fetch_yfinance(ticker, max_workers)
        except Exception as exc:
            st.error(f"Fetch failed: {exc}")
            if use_ib:
                st.warning("Verify TWS is running with API and OPRA subscription.")
            st.stop()

    if df.empty:
        st.error("No options data returned.")
        if use_ib:
            st.warning("Verify TWS is running with API and OPRA subscription.")
        st.stop()

    # Save OI snapshot and clean old data
    save_snapshot(df)
    cleanup_old_snapshots(keep_days=365)

    # Expiration filter — only valid expiry dates
    exp_dates = sorted(df["expiration"].unique())
    expiry_options = ["All expirations"] + exp_dates
    selected_expiry = st.selectbox(
        "📅 Filter by Expiration Date",
        expiry_options,
        index=0,
        help="Only dates with actual option expirations are listed.",
    )
    expiry_filter = None if selected_expiry == "All expirations" else selected_expiry

    # Get OI changes if historical snapshots exist
    calls = top_by_oi(df, ticker, "call", n=top_n, expiry=expiry_filter)
    puts = top_by_oi(df, ticker, "put", n=top_n, expiry=expiry_filter)
    all_contracts = (
        calls["contractSymbol"].tolist() + puts["contractSymbol"].tolist()
    )
    oi_changes = get_changes_for_ticker(ticker, all_contracts)
    iv_stats = get_iv_stats_for_ticker(ticker, all_contracts)
    has_iv = any(v is not None for v in iv_stats.values())

    # ---- Data display ----
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("📋 Ticker", ticker)
    c2.metric("📦 Contracts", f"{len(df):,}")
    c3.metric("🗓️ Expirations", f"{df['expiration'].nunique():,}")
    c4.metric("🕐 Retrieved", datetime.utcnow().strftime("%H:%M UTC"))

    st.divider()

    expiry_label = f" · Expiry: {expiry_filter}" if expiry_filter else ""
    st.subheader(f"📈 CALLS — Top {top_n} by Open Interest{expiry_label}")
    _show_table(calls, oi_changes, iv_stats)

    st.divider()

    st.subheader(f"📉 PUTS — Top {top_n} by Open Interest{expiry_label}")
    _show_table(puts, oi_changes, iv_stats)

    # OI History
    history_df = get_history_table(ticker, all_contracts)
    snap_count = snapshot_count()

    if not history_df.empty and snap_count >= 2:
        st.divider()
        st.subheader(f"📅 OI History — {snap_count} snapshots")
        st.dataframe(history_df, width="stretch", hide_index=True)
    else:
        st.caption(
            f"💡 Tracking: {snap_count} snapshot(s) saved so far. "
            "OI changes & IV Rank will populate after more snapshots accumulate."
        )


if __name__ == "__main__":
    main()

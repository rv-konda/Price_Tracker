"""A live Streamlit price dashboard powered by Yahoo Finance data."""

from pathlib import Path

import pandas as pd
import streamlit as st
import yfinance as yf


SNAPSHOT_FILE = Path("live_price_snapshots.csv")
DEFAULT_TICKERS = "FCX, SCCO"

CHART_RANGES = {
    "1 day": ("1d", "1m"),
    "5 days": ("5d", "5m"),
    "1 month": ("1mo", "30m"),
    "6 months": ("6mo", "1d"),
    "1 year": ("1y", "1d"),
}


def parse_tickers(raw_tickers):
    """Turn comma-separated input into unique uppercase ticker symbols."""
    tickers = [ticker.strip().upper() for ticker in raw_tickers.split(",")]
    return list(dict.fromkeys(ticker for ticker in tickers if ticker))


def fetch_quote(ticker):
    """Return the latest intraday price and its change from the previous close."""
    stock = yf.Ticker(ticker)

    intraday = stock.history(
        period="1d",
        interval="1m",
        auto_adjust=False,
        actions=False,
        prepost=False,
        repair=True,
        raise_errors=True,
    )

    daily = stock.history(
        period="5d",
        interval="1d",
        auto_adjust=False,
        actions=False,
        repair=True,
        raise_errors=True,
    )

    if intraday.empty or daily.empty:
        raise ValueError("Yahoo Finance returned no recent price data.")

    latest_timestamp = intraday.index[-1]
    latest_price = float(intraday["Close"].iloc[-1])

    earlier_sessions = daily[daily.index.date < latest_timestamp.date()]

    if not earlier_sessions.empty:
        previous_close = float(earlier_sessions["Close"].iloc[-1])
    elif len(daily) >= 2:
        previous_close = float(daily["Close"].iloc[-2])
    else:
        previous_close = latest_price

    price_change = latest_price - previous_close
    percent_change = price_change / previous_close if previous_close else 0.0

    return {
        "ticker": ticker,
        "timestamp": latest_timestamp,
        "price": latest_price,
        "change": price_change,
        "percent_change": percent_change,
    }


@st.cache_data(ttl=300, show_spinner=False)
def fetch_chart_data(tickers, chart_label):
    """Download chart prices and return one column per ticker."""
    period, interval = CHART_RANGES[chart_label]
    series = []

    for ticker in tickers:
        history = yf.Ticker(ticker).history(
            period=period,
            interval=interval,
            auto_adjust=True,
            actions=False,
            prepost=False,
            repair=True,
            raise_errors=True,
        )

        if not history.empty:
            prices = history["Close"].rename(ticker)
            prices.index = pd.to_datetime(prices.index).tz_localize(None)
            series.append(prices)

    if not series:
        return pd.DataFrame()

    return pd.concat(series, axis=1).sort_index()


def save_snapshots(quotes):
    """Store each unique ticker/timestamp observation in a CSV file."""
    new_rows = pd.DataFrame(
        {
            "timestamp": [
                quote["timestamp"].isoformat() for quote in quotes
            ],
            "ticker": [
                quote["ticker"] for quote in quotes
            ],
            "price": [
                quote["price"] for quote in quotes
            ],
            "change": [
                quote["change"] for quote in quotes
            ],
            "percent_change": [
                quote["percent_change"] for quote in quotes
            ],
        }
    )

    if SNAPSHOT_FILE.exists():
        existing = pd.read_csv(SNAPSHOT_FILE)
        snapshots = pd.concat(
            [existing, new_rows],
            ignore_index=True,
        )

        snapshots = snapshots.drop_duplicates(
            subset=["timestamp", "ticker"],
            keep="last",
        )
    else:
        snapshots = new_rows

    snapshots = snapshots.sort_values(
        ["timestamp", "ticker"]
    )

    snapshots.to_csv(SNAPSHOT_FILE, index=False)

    return snapshots


st.set_page_config(
    page_title="Live Price Tracker",
    page_icon="📈",
    layout="wide",
)

st.title("Live Price Tracker")

st.caption(
    "Latest market prices, daily movement, "
    "and historical performance."
)

with st.sidebar:
    st.header("Tracker settings")

    ticker_input = st.text_input(
        "Ticker symbols",
        value=DEFAULT_TICKERS,
        help="Separate multiple Yahoo Finance symbols with commas.",
    )

    chart_range = st.selectbox(
        "Chart range",
        list(CHART_RANGES),
        index=2,
    )

    auto_refresh = st.toggle(
        "Automatic refresh",
        value=True,
    )

    refresh_seconds = st.slider(
        "Refresh every (seconds)",
        15,
        300,
        30,
        step=15,
    )

    st.caption(
        "Yahoo Finance data may be delayed "
        "and is intended for personal research."
    )


tickers = parse_tickers(ticker_input)

run_every = refresh_seconds if auto_refresh else None


@st.fragment(run_every=run_every)
def show_dashboard():
    if not tickers:
        st.warning(
            "Enter at least one ticker symbol in the sidebar."
        )
        return

    quotes = []
    errors = []

    with st.spinner("Loading current prices..."):
        for ticker in tickers:
            try:
                quotes.append(fetch_quote(ticker))
            except Exception as exc:
                errors.append(f"{ticker}: {exc}")

    if quotes:
        metric_columns = st.columns(len(quotes))

        for column, quote in zip(metric_columns, quotes):
            delta = (
                f"{quote['change']:+.2f} "
                f"({quote['percent_change']:+.2%})"
            )

            column.metric(
                quote["ticker"],
                f"${quote['price']:,.2f}",
                delta,
            )

        latest_update = max(
            quote["timestamp"] for quote in quotes
        )

        st.caption(
            "Latest Yahoo Finance observation: "
            f"{latest_update:%Y-%m-%d %H:%M %Z}"
        )

        snapshots = save_snapshots(quotes)

        try:
            chart_data = fetch_chart_data(
                tuple(tickers),
                chart_range,
            )

            if chart_data.empty:
                st.info(
                    "No chart data was returned "
                    "for the selected range."
                )
            else:
                st.subheader(
                    f"Price history — {chart_range}"
                )

                st.line_chart(
                    chart_data,
                    height=420,
                )

        except Exception as exc:
            st.warning(
                "The current prices loaded, "
                f"but the chart did not: {exc}"
            )

        st.download_button(
            "Download recorded snapshots",
            data=snapshots.to_csv(
                index=False
            ).encode("utf-8"),
            file_name=SNAPSHOT_FILE.name,
            mime="text/csv",
        )

    if errors:
        st.warning(
            "Some symbols could not be loaded:\n\n"
            + "\n\n".join(errors)
        )


show_dashboard()
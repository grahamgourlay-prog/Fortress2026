#!/usr/bin/env python3
"""
Portfolio Data Fetcher  (yfinance edition)
==========================================
Fetches OHLCV data from Yahoo Finance for all tickers × all intervals
configured in portfolio_config.json. Saves one CSV per ticker/interval pair.

No API key required.

Usage:
    python3 fetch_portfolio.py                     # fetch all tickers & intervals, rebuild dashboard
    python3 fetch_portfolio.py --interval 1day     # fetch only the 1day interval
    python3 fetch_portfolio.py --ticker SWDA SGLN  # fetch only specific tickers
    python3 fetch_portfolio.py --no-dash           # fetch only, skip dashboard generation
    python3 fetch_portfolio.py --dash              # rebuild dashboard from existing CSVs, no fetch
"""

import argparse
import json
import sys
from pathlib import Path

try:
    import yfinance as yf
except ImportError:
    print("ERROR: yfinance not installed. Run: pip install yfinance --break-system-packages")
    sys.exit(1)

try:
    import pandas as pd
except ImportError:
    print("ERROR: pandas not installed. Run: pip install pandas --break-system-packages")
    sys.exit(1)

SCRIPT_DIR  = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "portfolio_config.json"

# Maps config interval id -> (yfinance interval string, yfinance period string)
INTERVAL_MAP = {
    "1h":    ("1h",  "60d"),   # ~60 days of hourly bars
    "1day":  ("1d",  "2y"),    # 2 years of daily bars
    "1week": ("1wk", "10y"),   # 10 years of weekly bars
}


def load_config():
    if not CONFIG_FILE.exists():
        print(f"ERROR: Config file not found: {CONFIG_FILE}")
        sys.exit(1)
    with open(CONFIG_FILE) as f:
        return json.load(f)


def fetch_ohlcv(symbol, yf_symbol, interval_id):
    """
    Fetch OHLCV data from Yahoo Finance via yfinance.
    Returns (DataFrame, None) on success or (None, error_string) on failure.
    Prices are normalised to GBP (not GBp pence) for LSE tickers.
    """
    if interval_id not in INTERVAL_MAP:
        return None, f"Unknown interval: {interval_id}"

    yf_interval, yf_period = INTERVAL_MAP[interval_id]

    try:
        ticker = yf.Ticker(yf_symbol)
        df = ticker.history(period=yf_period, interval=yf_interval, auto_adjust=True)

        if df is None or df.empty:
            return None, "No data returned"

        # Detect currency and convert pence -> pounds where needed.
        # Yahoo Finance returns some LSE ETFs in GBp (pence); normalise to GBP.
        currency = ""
        try:
            currency = ticker.fast_info.currency
        except Exception:
            try:
                currency = ticker.info.get("currency", "")
            except Exception:
                pass

        if currency == "GBp":
            for col in ["Open", "High", "Low", "Close"]:
                if col in df.columns:
                    df[col] = df[col] / 100.0

        # Standardise columns to lowercase
        df = df.reset_index()
        df.columns = [c.lower() for c in df.columns]

        # yfinance uses 'datetime' for intraday, 'date' for daily/weekly
        if "datetime" in df.columns:
            df = df.rename(columns={"datetime": "date"})

        # Keep only OHLCV columns
        cols = ["date", "open", "high", "low", "close"]
        if "volume" in df.columns:
            cols.append("volume")
        df = df[cols].copy()

        # Strip timezone info so CSV stays clean
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
        df = df.sort_values("date").reset_index(drop=True)

        return df, None

    except Exception as e:
        return None, f"Error: {e}"


def csv_path(output_dir, symbol, interval):
    return Path(output_dir) / f"{symbol.upper()}_{interval}.csv"


def save_csv(df, output_dir, symbol, interval):
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    path = csv_path(output_dir, symbol, interval)
    df.to_csv(path, index=False)
    return path


def main():
    parser = argparse.ArgumentParser(description="Portfolio Data Fetcher (yfinance)")
    parser.add_argument("--interval", nargs="+", metavar="IV",
                        help="Fetch only these interval(s), e.g. --interval 1day 1week")
    parser.add_argument("--ticker", nargs="+", metavar="SYM",
                        help="Fetch only these tickers by display symbol, e.g. --ticker SWDA SGLN")
    parser.add_argument("--no-dash", action="store_true",
                        help="Fetch data only, skip dashboard generation")
    parser.add_argument("--dash", action="store_true",
                        help="Rebuild dashboard from existing CSVs without fetching")
    args = parser.parse_args()

    config     = load_config()
    tickers    = config.get("tickers", [])
    intervals  = config.get("intervals", [{"id": "1day", "label": "1D"}])
    output_dir = SCRIPT_DIR / config.get("output_dir", "portfolio_data")

    # Apply filters
    if args.ticker:
        syms    = [s.upper() for s in args.ticker]
        tickers = [t for t in tickers if t["symbol"].upper() in syms]
    if args.interval:
        ivs       = args.interval
        intervals = [iv for iv in intervals if iv["id"] in ivs]

    # -- Fetch mode ------------------------------------------------------------
    if not args.dash:
        total = len(tickers) * len(intervals)
        print(f"\nFetching {len(tickers)} tickers x {len(intervals)} intervals "
              f"= {total} requests  (Yahoo Finance / yfinance)\n")
        print(f"{'Ticker':<8}  {'YF Symbol':<10}  {'Interval':<8}  Result")
        print("-" * 60)

        succeeded, failed = [], []

        for ticker in tickers:
            symbol    = ticker["symbol"]
            yf_symbol = ticker.get("yf_symbol", symbol)

            for iv in intervals:
                iv_id = iv["id"]
                print(f"  {symbol:<8}  {yf_symbol:<10}  {iv_id:<8} ", end="", flush=True)

                df, err = fetch_ohlcv(symbol, yf_symbol, iv_id)

                if df is not None:
                    save_csv(df, output_dir, symbol, iv_id)
                    print(f"OK  {len(df)} bars")
                    succeeded.append(f"{symbol}/{iv_id}")
                else:
                    print(f"FAIL  {err}")
                    failed.append((symbol, iv_id, err))

        print(f"\n{'-' * 60}")
        print(f"  Done: {len(succeeded)}/{total} succeeded")
        if failed:
            print(f"\n  Failed fetches:")
            for sym, iv, reason in failed:
                print(f"    {sym:<8} {iv:<8} {reason}")
        print()

    # -- Dashboard -------------------------------------------------------------
    if not args.no_dash:
        import subprocess
        gen = SCRIPT_DIR / "generate_dashboard.py"
        if gen.exists():
            print("Building dashboard...")
            subprocess.run([sys.executable, str(gen)], check=False)
        else:
            print("NOTE: generate_dashboard.py not found -- skipping dashboard.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Fetch full history stock data for the SeekingAlpha Top10 Quant portfolio."""

import json
import os
import sys
from datetime import datetime, timezone

import yfinance as yf

SYMBOLS = ["MU", "AMD", "CIEN", "CLS", "COHR", "ALL", "INCY", "B", "WLDN", "ATI"]
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def fetch_stock(symbol: str) -> dict:
    """Download full daily history for a single symbol and return as dict."""
    ticker = yf.Ticker(symbol)
    df = ticker.history(period="max", interval="1d", auto_adjust=True)
    if df.empty:
        print(f"WARNING: No data returned for {symbol}")
        return {"symbol": symbol, "dates": [], "close": [], "volume": []}

    df = df.reset_index()
    dates = [d.strftime("%Y-%m-%d") for d in df["Date"]]
    close = [round(float(v), 4) if v == v else None for v in df["Close"]]
    volume = [int(v) if v == v else 0 for v in df["Volume"]]

    return {
        "symbol": symbol,
        "dates": dates,
        "close": close,
        "volume": volume,
    }


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    all_data = {}
    errors = []

    for sym in SYMBOLS:
        print(f"Fetching {sym}...")
        try:
            data = fetch_stock(sym)
            all_data[sym] = data
            print(f"  {sym}: {len(data['dates'])} data points")
        except Exception as exc:
            print(f"  ERROR fetching {sym}: {exc}")
            errors.append(sym)

    if errors:
        print(f"\nFailed symbols: {errors}")

    # Write combined JSON
    output = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "symbols": SYMBOLS,
        "stocks": all_data,
    }

    out_path = os.path.join(OUTPUT_DIR, "stocks.json")
    with open(out_path, "w") as f:
        json.dump(output, f, separators=(",", ":"))

    size_mb = os.path.getsize(out_path) / (1024 * 1024)
    print(f"\nWrote {out_path} ({size_mb:.2f} MB)")

    if len(errors) == len(SYMBOLS):
        print("ALL symbols failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()

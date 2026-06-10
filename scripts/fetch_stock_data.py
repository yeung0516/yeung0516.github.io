#!/usr/bin/env python3
"""Fetch full history stock data for the SeekingAlpha Top10 Quant portfolio.

Supports progressive updates: each symbol tracks its own version and
last_updated timestamp. On each run, only the BATCH_SIZE oldest-updated
symbols are refreshed, spreading API load across multiple workflow runs.
"""

import json
import os
import sys
from datetime import datetime, timezone

import yfinance as yf

SYMBOLS = ["MU", "AMD", "CIEN", "CLS", "COHR", "ALL", "INCY", "B", "WLDN", "ATI"]
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

# Number of symbols to update per workflow run (progressive update batch size)
BATCH_SIZE = int(os.environ.get("STOCK_BATCH_SIZE", "3"))


def load_existing_data(out_path: str) -> dict:
    """Load existing stocks.json if available, for incremental updates."""
    if not os.path.exists(out_path):
        return {}
    try:
        with open(out_path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def get_symbols_to_update(existing: dict) -> list:
    """Return symbols sorted by oldest last_updated first, limited to BATCH_SIZE.

    New symbols (not yet in the dataset) are always prioritized.
    """
    stocks = existing.get("stocks", {})
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    symbol_times = []
    for sym in SYMBOLS:
        if sym in stocks and "last_updated" in stocks[sym]:
            symbol_times.append((sym, stocks[sym]["last_updated"]))
        else:
            # Never updated — use epoch to ensure highest priority
            symbol_times.append((sym, "1970-01-01T00:00:00Z"))

    # Sort by last_updated ascending (oldest first)
    symbol_times.sort(key=lambda x: x[1])

    return [sym for sym, _ in symbol_times[:BATCH_SIZE]]


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
    out_path = os.path.join(OUTPUT_DIR, "stocks.json")
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Load existing data for progressive update
    existing = load_existing_data(out_path)
    all_data = existing.get("stocks", {})

    # Determine which symbols to update this run
    symbols_to_update = get_symbols_to_update(existing)
    print(f"Progressive update: refreshing {len(symbols_to_update)}/{len(SYMBOLS)} "
          f"symbols this run: {symbols_to_update}")

    errors = []
    for sym in symbols_to_update:
        print(f"Fetching {sym}...")
        try:
            data = fetch_stock(sym)
            data["version"] = all_data.get(sym, {}).get("version", 0) + 1
            data["last_updated"] = now_str
            all_data[sym] = data
            print(f"  {sym}: {len(data['dates'])} data points (v{data['version']})")
        except Exception as exc:
            print(f"  ERROR fetching {sym}: {exc}")
            errors.append(sym)

    if errors:
        print(f"\nFailed symbols: {errors}")

    # Preserve existing data for symbols not updated this run
    for sym in SYMBOLS:
        if sym not in all_data:
            all_data[sym] = {
                "symbol": sym, "dates": [], "close": [], "volume": [],
                "version": 0, "last_updated": "1970-01-01T00:00:00Z",
            }

    # Write combined JSON
    output = {
        "updated": now_str,
        "symbols": SYMBOLS,
        "stocks": all_data,
    }

    with open(out_path, "w") as f:
        json.dump(output, f, separators=(",", ":"))

    size_mb = os.path.getsize(out_path) / (1024 * 1024)
    print(f"\nWrote {out_path} ({size_mb:.2f} MB)")

    if len(errors) == len(symbols_to_update):
        print("ALL targeted symbols failed this run!")
        sys.exit(1)


if __name__ == "__main__":
    main()

"""
inject_snp.py  –  One-off script to backfill snp_history into portfolio.json.
Run from the Portfolio directory:  python inject_snp.py
Requires: requests
"""

import json
import time
import requests
from datetime import datetime, timezone

PORTFOLIO_JSON = "portfolio.json"
SNP_TICKER = "%5EGSPC"           # URL-encoded ^GSPC
INITIAL_INVESTMENT = 50_000.0

def fetch_snp(start_ts: int, end_ts: int) -> list[dict]:
    """Fetch daily S&P 500 closes from Yahoo Finance (server-side, no CORS)."""
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{SNP_TICKER}"
        f"?interval=1d&period1={start_ts}&period2={end_ts}&events=history"
    )
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(url, headers=headers, timeout=15)
    r.raise_for_status()
    data = r.json()

    result = data["chart"]["result"][0]
    timestamps = result["timestamp"]
    closes     = result["indicators"]["quote"][0]["close"]

    points = []
    for ts, close in zip(timestamps, closes):
        if close is None:
            continue
        # Normalise to midnight UTC of that calendar day
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        points.append({"timestamp": int(dt.timestamp()), "close": round(close, 4)})

    return points

def main():
    with open(PORTFOLIO_JSON, "r") as f:
        portfolio = json.load(f)

    history = portfolio["history"]
    start_ts = history[0]["timestamp"]
    # Add one extra day so Yahoo returns the final day's close
    end_ts   = history[-1]["timestamp"] + 86_400

    print(f"Fetching S&P 500 from {datetime.utcfromtimestamp(start_ts).date()} "
          f"to {datetime.utcfromtimestamp(end_ts).date()} …")

    snp_points = fetch_snp(start_ts, end_ts)
    if not snp_points:
        print("ERROR: No S&P 500 data returned.")
        return

    # Scale so first close == $50,000
    first_close = snp_points[0]["close"]
    scale       = INITIAL_INVESTMENT / first_close
    print(f"First S&P close: {first_close:.2f}  |  scale factor: {scale:.6f}")

    snp_history = [
        {"timestamp": p["timestamp"], "equity": round(p["close"] * scale, 2)}
        for p in snp_points
    ]

    portfolio["snp_history"] = snp_history
    with open(PORTFOLIO_JSON, "w") as f:
        json.dump(portfolio, f, indent=2)

    print(f"Done. Injected {len(snp_history)} S&P 500 data points into {PORTFOLIO_JSON}.")

if __name__ == "__main__":
    main()

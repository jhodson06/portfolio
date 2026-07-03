"""
live_trader.py -- 15m ORB live/paper execution engine.
"""

import os
import sys
import json
import time
import signal
import logging
import subprocess
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta, time as dt_time
import pytz
import requests
import pandas as pd
from dotenv import load_dotenv

# Load Environment Variables
load_dotenv()

# --- Setup Logging ---
script_dir = os.path.dirname(os.path.abspath(__file__))
log_dir = os.path.join(script_dir, "logs")
os.makedirs(log_dir, exist_ok=True)

logger = logging.getLogger("live_trader")
logger.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

if not logger.handlers:
    # Set explicit utf-8 encoding for rotating file logs
    file_handler = RotatingFileHandler(
        os.path.join(log_dir, "live_trader.log"), maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

# --- Configuration & Credentials ---
# [REDACTED FOR SHOWCASE] 
# API keys, filesystem paths, and webhook URLs have been removed for public display.
API_KEY = "REDACTED"
SECRET_KEY = "REDACTED"
BASE_URL = "REDACTED"

# Run options
# Pull from env so deployments never accidentally run live with a stale hardcoded value.
# Set DRY_RUN=false in your .env or shell environment to route real orders.
_dry_run_env = os.getenv("DRY_RUN", "true").strip().lower()
DRY_RUN = _dry_run_env not in ("false", "0", "no")
STATE_FILE = os.path.join(script_dir, "live_state.json")
CONFIG_FILE = os.path.join(script_dir, "basket_config.json")

# Data feed matching the tape backtested
DATA_FEED = "iex"

# --- Constants ---
EST = pytz.timezone("US/Eastern")
MARKET_OPEN = dt_time(9, 30)
DEFAULT_MARKET_CLOSE = dt_time(16, 0)
PREMARKET_START = dt_time(9, 15)
DEFAULT_EOD_EXIT = dt_time(15, 55)
POLL_SECONDS = 30
ORDER_FILL_TIMEOUT = 10

# Audit-trail tag stamped on the parent entry order submitted by this bot.
# NOTE: Alpaca does NOT propagate client_order_id to child bracket legs (TP/SL),
# so this tag cannot be used to verify ownership during mid-day recovery.
# Phantom position recovery instead uses the bracket signature (both a limit
# AND a stop child leg must exist) as the ownership signal.
CLIENT_ORDER_TAG = "ORB"

# Multiplicative percentage slippage matching backtests
SLIPPAGE_PCT = 0.0010

# Minimum trigger price distance threshold to prevent sizing on noise
MIN_RISK_THRESHOLD = 0.10

# Percentage-based stop-loss fallback used when a position's SL bracket leg is
# missing on Alpaca (e.g. manually cancelled). Applied in both startup
# reconciliation and mid-day phantom recovery to keep TP reconstruction sane.
SL_FALLBACK_PCT = 0.02

# Minimum position trade size guard
MIN_TRADE_NOTIONAL = 100.0

# Live-only safety rail (not present in the backtest, intentionally more
# conservative): never let a single position exceed this share of equity,
# regardless of what the risk-based sizing calc asks for.
MAX_POSITION_EQUITY_PCT = 0.95

REQUIRED_CONFIG_KEYS = [
    "LONG_RISK_PERCENT", "LONG_TAKE_PROFIT_RATIO",
    "SHORT_RISK_PERCENT", "SHORT_TAKE_PROFIT_RATIO",
    "ORB_MINUTES", "CUTOFF_MINUTES",
    "TARGET_DECAY_START_HOUR", "TARGET_DECAY_START_MINUTE",
    "TARGET_DECAY_END_HOUR", "TARGET_DECAY_END_MINUTE",
    "FILTER_A", "FILTER_B", "FILTER_C",
]

# Matches the ticker basket filter analyze_basket.py uses.
EXCLUDED_TICKERS = ["MARA", "ARM"]

# Graceful shutdown flag, flipped by the signal handlers below.
_shutdown_requested = False


def _handle_shutdown_signal(signum, frame):
    global _shutdown_requested
    logger.warning(f"Received signal {signum}. Will shut down gracefully after the current cycle.")
    _shutdown_requested = True


def sleep_interruptible(seconds: float) -> bool:
    """
    Sleeps in standard increments, checking for shutdown signals.
    Returns True if shutdown was requested, False otherwise.
    """
    start_time = time.time()
    while time.time() - start_time < seconds:
        if _shutdown_requested:
            return True
        time.sleep(max(0.0, min(1.0, seconds - (time.time() - start_time))))
    return False


# Import Alpaca API (wrapped in try-except for dependency safety)
try:
    import alpaca_trade_api as tradeapi
    from alpaca_trade_api.rest import APIError  # noqa: F401  (kept for callers/future use)
except ImportError:
    logger.critical("Failed to import alpaca-trade-api. Install using 'pip install alpaca-trade-api'")
    sys.exit(1)


# --- Notifications ---
def send_notification(msg: str):
    logger.info(f"Notification: {msg}")
    # [REDACTED FOR SHOWCASE] Discord Webhook integration logic removed.


# --- Config Validation ---
def validate_config(basket_config: dict, symbols: list):
    """
    FIX: previously a missing key in basket_config.json would surface as an
    obscure KeyError deep inside execute_order or the filter checks, mid
    trading day. Fail fast, once, at startup instead.
    """
    problems = []
    for sym in symbols:
        cfg = basket_config.get(sym, {})
        missing = [k for k in REQUIRED_CONFIG_KEYS if k not in cfg]
        if missing:
            problems.append(f"{sym} missing keys: {missing}")
            continue
            
        # Value validation checks
        if not (0 <= cfg["LONG_RISK_PERCENT"] <= 0.10):
            problems.append(f"{sym} LONG_RISK_PERCENT must be between 0.0 and 0.10 (max 10% risk per trade)")
        if not (0 <= cfg["SHORT_RISK_PERCENT"] <= 0.10):
            problems.append(f"{sym} SHORT_RISK_PERCENT must be between 0.0 and 0.10 (max 10% risk per trade)")
        if cfg["ORB_MINUTES"] <= 0:
            problems.append(f"{sym} ORB_MINUTES must be greater than 0")
        if cfg["CUTOFF_MINUTES"] <= cfg["ORB_MINUTES"]:
            problems.append(f"{sym} CUTOFF_MINUTES must be greater than ORB_MINUTES")
            
        start_min = cfg["TARGET_DECAY_START_HOUR"] * 60 + cfg["TARGET_DECAY_START_MINUTE"]
        end_min = cfg["TARGET_DECAY_END_HOUR"] * 60 + cfg["TARGET_DECAY_END_MINUTE"]
        if end_min <= start_min:
            problems.append(f"{sym} TARGET_DECAY_END_HOUR/MINUTE must be later than TARGET_DECAY_START_HOUR/MINUTE")
        if cfg.get("LONG_TAKE_PROFIT_RATIO", 0) <= 0:
            problems.append(f"{sym} LONG_TAKE_PROFIT_RATIO must be positive")
        if cfg.get("SHORT_TAKE_PROFIT_RATIO", 0) <= 0:
            problems.append(f"{sym} SHORT_TAKE_PROFIT_RATIO must be positive")
            
    if problems:
        for p in problems:
            logger.critical(f"Config validation failed: {p}")
        raise ValueError("basket_config.json validation failed; see log for details.")


# --- Trading Calendar Helper ---
def get_session_info(api: "tradeapi.REST", date_val) -> dict:
    """
    Returns {'is_open': bool, 'open': time, 'close': time} for date_val.

    FIX: previously the script assumed every trading day runs 09:30-16:00.
    Early-close sessions (day before Thanksgiving, sometimes July 3rd /
    Christmas Eve, etc.) actually close at 13:00 ET; entries, decay, and
    EOD liquidation all need to key off the real session close.

    FIX: on a failed calendar lookup, default to "not a trading day"
    rather than "assume open on weekdays". If the calendar endpoint is
    unreachable, every other API call this cycle will likely fail too --
    it's safer to sit out an uncertain day than trade blind against
    stale/absent baselines.
    """
    try:
        calendar = api.get_calendar(start=str(date_val), end=str(date_val))
        if not calendar:
            return {"is_open": False, "open": None, "close": None}
        entry = calendar[0]
        return {"is_open": True, "open": entry.open, "close": entry.close}
    except Exception as e:
        logger.error(f"Error checking trading calendar: {e}")
        return {"is_open": False, "open": None, "close": None}


def get_next_session_start(api: "tradeapi.REST", from_date) -> datetime:
    """
    Returns the premarket start datetime (9:15 AM EST) of the next open
    trading session on or after `from_date`. Falls back to tomorrow at 9:15 AM
    if the calendar API is unavailable.
    """
    try:
        look_end = from_date + timedelta(days=10)
        calendar = api.get_calendar(start=str(from_date), end=str(look_end))
        now = datetime.now(EST)
        for entry in calendar:
            # entry.date may be a str or date object depending on SDK version
            entry_date = pd.Timestamp(entry.date).date() if isinstance(entry.date, str) else entry.date
            session_start = EST.localize(datetime.combine(entry_date, PREMARKET_START))
            if session_start > now:
                return session_start
    except Exception as e:
        logger.error(f"Failed to look up next trading session: {e}")
    # Fallback: tomorrow at premarket start
    tomorrow = (datetime.now(EST) + timedelta(days=1)).date()
    return EST.localize(datetime.combine(tomorrow, PREMARKET_START))


def _parse_calendar_time(value, fallback: dt_time) -> dt_time:
    """
    Normalises the 'open' / 'close' fields returned by api.get_calendar().
    Older SDK versions return bare strings (e.g. '09:30'), newer versions
    return datetime.time objects, and some return full datetime objects.
    """
    if value is None:
        return fallback
    if isinstance(value, datetime):
        return value.astimezone(EST).time()
    if isinstance(value, dt_time):
        return value
    if isinstance(value, str):
        try:
            return datetime.strptime(value[:5], "%H:%M").time()
        except ValueError:
            logger.warning(f"Unrecognised calendar time string '{value}'. Using fallback.")
            return fallback
    elif hasattr(value, "time"):  # e.g. pd.Timestamp or datetime
        return value.time()
    return fallback


# --- Portfolio Integration ---
def push_portfolio_update(api: "tradeapi.REST"):
    """
    Queries Alpaca for current account state, formats a JSON payload matching
    the required schema, writes it to the local frontend portfolio repo, and
    pushes the changes via Git. This runs at the end of every trading day.
    """
    # [REDACTED FOR SHOWCASE]
    # Automated GitHub integration and local filesystem paths have been removed.
    pass


# --- State Management & Crash Recovery ---
def save_state(state: dict):
    try:
        tmp_file = STATE_FILE + ".tmp"
        with open(tmp_file, "w") as f:
            json.dump(state, f, indent=4, default=str)
        os.replace(tmp_file, STATE_FILE)
    except Exception as e:
        logger.error(f"Failed to save state.json atomically: {e}")


def load_state() -> dict:
    state = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                state = json.load(f)
                logger.info("Loaded active session state from live_state.json")
        except Exception as e:
            logger.error(f"Failed to parse live_state.json: {e}")
    state.setdefault("orb_bounds", {})
    state.setdefault("trades", {})
    state.setdefault("sym_progress", {})
    return state


def reconstruct_state_from_alpaca(api: "tradeapi.REST", symbols: list, state: dict, basket_config: dict):
    """
    Startup Reconciliation: If the bot restarts mid-day, scans Alpaca's open positions
    and orders to reconstruct any missing trade entries in our state dictionary.

    FIX: original_tp is now calculated from entry_price and the config risk ratios,
    rather than reading the live limit order's current price. This prevents the decay
    loop from compounding on an already-decayed baseline after a mid-day restart.
    """
    if DRY_RUN:
        return

    try:
        positions = api.list_positions()
        open_orders = api.list_orders(status="open", limit=500)
        
        for pos in positions:
            sym = pos.symbol
            if sym in symbols and state["trades"].get(sym, {}).get("status") != "ENTERED":
                tp_order = next((o for o in open_orders if o.symbol == sym and o.type == "limit"), None)
                sl_order = next((o for o in open_orders if o.symbol == sym and o.type in ["stop", "stop_limit"]), None)

                entry_price = float(pos.avg_entry_price)
                side = "long" if float(pos.qty) > 0 else "short"
                cfg = basket_config.get(sym, {})

                # Recalculate the true original TP from config ratios to avoid
                # compounding decay on an already-decayed live limit price.
                tp_ratio = cfg.get("LONG_TAKE_PROFIT_RATIO") if side == "long" else cfg.get("SHORT_TAKE_PROFIT_RATIO")
                # If the SL leg is missing (e.g. manually cancelled), reconstruct a
                # percentage-based SL (SL_FALLBACK_PCT) so the TP ratio calculation stays realistic.
                sl_price = float(sl_order.stop_price) if sl_order else (
                    entry_price * (1 - SL_FALLBACK_PCT) if side == "long" else entry_price * (1 + SL_FALLBACK_PCT)
                )
                if sl_order is None:
                    logger.warning(f"[{sym}] No SL order found on Alpaca. Using {SL_FALLBACK_PCT:.0%} fallback SL: ${sl_price:.2f}")
                if tp_ratio and sl_price:
                    risk_per_share = abs(entry_price - sl_price)
                    original_tp = (entry_price + risk_per_share * tp_ratio) if side == "long" else (entry_price - risk_per_share * tp_ratio)
                else:
                    # Fallback: use the live TP order price if config ratios are unavailable
                    original_tp = float(tp_order.limit_price) if tp_order else entry_price

                state["trades"][sym] = {
                    "status": "ENTERED",
                    "side": side,
                    "shares": abs(int(float(pos.qty))),
                    "entry_price": entry_price,
                    "original_tp": original_tp,
                    "current_tp": float(tp_order.limit_price) if tp_order else original_tp,
                    "sl_price": sl_price,
                    "parent_order_id": None
                }
                logger.warning(f"Startup Reconciliation: Reconstructed trade state for {sym} from Alpaca. Position size: {pos.qty} shares, Entry: ${entry_price}, SL: ${sl_price}, Recalculated original TP: ${original_tp:.2f}")
                save_state(state)
    except Exception as e:
        logger.error(f"Failed to reconcile startup state from Alpaca: {e}")


# --- Pre-Market Baseline Fetcher ---
def fetch_premarket_metrics(api: "tradeapi.REST", symbols: list, basket_config: dict) -> dict:
    """
    [REDACTED FOR SHOWCASE]
    Computes each symbol's pre-market baseline metrics used for later filtering.
    Specific data points (such as relative volume calculations, average daily ranges, etc) 
    have been removed to protect the proprietary trading logic.
    """
    metrics = {}
    for sym in symbols:
        try:
            orb_minutes_val = int(basket_config.get(sym, {}).get("ORB_MINUTES", 15))
            
            # [BASELINE CALCULATION REDACTED]
            # Real script fetches daily and minute bars to build historical baselines.
            metrics[sym] = {
                "orb_minutes": orb_minutes_val,
                # "FILTER_A_BASELINE": ...,
                # "FILTER_B_BASELINE": ...
            }
            logger.info(f"[{sym}] Pre-market baseline loaded (Redacted).")

        except Exception as e:
            logger.error(f"Failed to fetch pre-market metrics for {sym}: {e}")

    return metrics


# --- Main Execution Engine ---
def run_trader():
    send_notification("🚀 Starting ORB Trading Bot...")

    if not API_KEY or not SECRET_KEY:
        logger.critical("API credentials missing from environment. Set ALPACA_API_KEY and ALPACA_SECRET_KEY.")
        sys.exit(1)

    api = tradeapi.REST(API_KEY, SECRET_KEY, BASE_URL, api_version="v2")

    try:
        account = api.get_account()
        logger.info(f"Successfully authenticated with Alpaca API. Current Equity: ${float(account.equity):,.2f}")
    except Exception as e:
        logger.critical(f"Alpaca connection failed: {e}")
        sys.exit(1)

    # Setup graceful shutdown signal handlers
    signal.signal(signal.SIGINT, _handle_shutdown_signal)
    signal.signal(signal.SIGTERM, _handle_shutdown_signal)

    if DRY_RUN:
        logger.warning("⚠️  DRY_RUN=true — No real orders will be sent to Alpaca. Set DRY_RUN=false in .env to go live.")
    else:
        logger.warning("🔴 LIVE MODE — DRY_RUN=false. Real orders will be routed to Alpaca!")

    while True:
        if _shutdown_requested:
            logger.info("Shutdown requested. Exiting main loop.")
            send_notification("🛑 Bot shutting down (signal received).")
            return
        try:
            now = datetime.now(EST)
            session = get_session_info(api, now.date())

            if not session["is_open"]:
                next_open = get_next_session_start(api, (now + timedelta(days=1)).date())
                sleep_seconds = (next_open - now).total_seconds()
                logger.info(
                    f"Non-trading day. Sleeping {sleep_seconds / 3600:.1f} hours until next session "
                    f"({next_open.strftime('%A %b %d at %I:%M %p %Z')})..."
                )
                sleep_interruptible(max(1, sleep_seconds))
                continue

            market_close_time = _parse_calendar_time(session["close"], DEFAULT_MARKET_CLOSE)
            market_end = now.replace(
                hour=market_close_time.hour, minute=market_close_time.minute, second=0, microsecond=0
            )

            premarket_start_dt = now.replace(
                hour=PREMARKET_START.hour, minute=PREMARKET_START.minute, second=0, microsecond=0
            )
            if now < premarket_start_dt:
                sleep_seconds = (premarket_start_dt - now).total_seconds()
                logger.info(f"Waiting for pre-market start at 9:15 AM EST. Sleeping for {sleep_seconds / 60:.1f} minutes...")
                sleep_interruptible(max(1, sleep_seconds))
                continue

            if now >= market_end:
                next_open = get_next_session_start(api, (now + timedelta(days=1)).date())
                sleep_seconds = (next_open - now).total_seconds()
                logger.info(
                    f"Market closed. Sleeping {sleep_seconds / 3600:.1f} hours until next session "
                    f"({next_open.strftime('%A %b %d at %I:%M %p %Z')})..."
                )
                sleep_interruptible(max(1, sleep_seconds))
                continue

            # --- DAILY TRADING SESSION ---
            logger.info("=== STARTING NEW DAILY SESSION ===")

            if not os.path.exists(CONFIG_FILE):
                logger.error(f"Config file not found at {CONFIG_FILE}. Retrying in 5 minutes.")
                sleep_interruptible(300)
                continue

            try:
                with open(CONFIG_FILE, "r") as f:
                    basket_config = json.load(f)
            except json.JSONDecodeError as e:
                logger.critical(f"basket_config.json contains invalid JSON: {e}")
                send_notification(f"⚠️ CRITICAL: basket_config.json is malformed — {e}")
                sys.exit(1)

            symbols = [
                sym for sym in basket_config.keys()
                if sym not in EXCLUDED_TICKERS and not sym.startswith("_")
            ]

            try:
                validate_config(basket_config, symbols)
            except (ValueError, TypeError) as e:
                logger.critical(str(e))
                send_notification(f"⚠️ CRITICAL CONFIGURATION ERROR: {e}")
                sys.exit(1)

            premarket_metrics = fetch_premarket_metrics(api, symbols, basket_config)

            state = load_state()
            current_date_str = now.strftime("%Y-%m-%d")

            if state.get("date") != current_date_str:
                state = {
                    "date": current_date_str,
                    "orb_bounds": {},        # {sym: {"high", "low", "rvol", "today_open"}}
                    "trades": {},             # {sym: {"status": ..., ...}}
                    "sym_progress": {},       # {sym: {"last_checked_bar": iso_ts or None}}
                }
                save_state(state)
                send_notification(f"🟢 Pre-market checks complete. Ready to monitor: {symbols}")
            else:
                reconstruct_state_from_alpaca(api, symbols, state, basket_config)

            # EOD exit target: 15:55, but never later than 5 minutes before
            # the actual (possibly early) session close.
            configured_eod = now.replace(
                hour=DEFAULT_EOD_EXIT.hour, minute=DEFAULT_EOD_EXIT.minute, second=0, microsecond=0
            )
            latest_safe_eod = market_end - timedelta(minutes=5)
            eod_exit_time = min(configured_eod, latest_safe_eod)

            # Derive market open time dynamically from the session calendar,
            # guarding against delayed opens or irregular schedule days.
            market_open_time = _parse_calendar_time(session.get("open"), MARKET_OPEN)

            while True:
                if _shutdown_requested:
                    save_state(state)
                    logger.info("Shutdown requested mid-session. State saved. Exiting.")
                    send_notification("🛑 Bot shutting down mid-session (signal received). State saved for recovery.")
                    return

                now = datetime.now(EST)
                if now >= market_end:
                    break

                if now.time() >= market_open_time:
                    run_intraday_checks(api, symbols, basket_config, premarket_metrics, state, eod_exit_time, market_open_time)
                    save_state(state)

                sleep_interruptible(POLL_SECONDS)

            logger.info("Market close reached. Resetting daily session state.")
            if os.path.exists(STATE_FILE):
                os.remove(STATE_FILE)
            
            # Push EOD account state to portfolio repo
            push_portfolio_update(api)

        except Exception as e:
            logger.error(f"Uncaught exception in main trading loop: {e}", exc_info=True)
            send_notification(f"⚠️ CRITICAL EXCEPTION: {e}")
            # Sleep to prevent tight crash loop
            sleep_interruptible(60)


# --- Intraday State & Strategy Engine ---
def run_intraday_checks(api: "tradeapi.REST", symbols: list, config: dict, baselines: dict, state: dict, eod_exit_time: datetime, market_open_time: dt_time = MARKET_OPEN):
    now = datetime.now(EST)
    current_minute = now.replace(second=0, microsecond=0)
    market_open_dt = now.replace(hour=market_open_time.hour, minute=market_open_time.minute, second=0, microsecond=0)

    # 0. Mid-day state sync: runs every 30s to detect SL/TP exits and recover
    #    any phantom positions that filled right as a cancel was in-transit.
    if not DRY_RUN:
        try:
            live_positions = api.list_positions()
            open_position_map = {p.symbol: p for p in live_positions}
            open_orders = api.list_orders(status="open", limit=500)

            for sym in symbols:
                trade_status = state["trades"].get(sym, {}).get("status")

                # Detect mid-day SL/TP exits: broker closed us out but state still says ENTERED
                if trade_status == "ENTERED" and sym not in open_position_map:
                    state["trades"][sym]["status"] = "COMPLETED"
                    state["trades"][sym]["exit_reason"] = "Stopped out / Target hit mid-day"
                    logger.info(f"[{sym}] Position no longer active on Alpaca. Marked COMPLETED.")
                    send_notification(f"🏁 [{sym}] Position closed mid-day (SL/TP hit).")

                # Detect phantom positions: cancel request raced with a fill;
                # broker holds shares but our state abandoned tracking them.
                # Ownership check: a bracket order always leaves exactly two
                # child legs — a limit (TP) AND a stop (SL). A manually-held
                # position with a single attached order won't satisfy both.
                # Requiring both legs dramatically reduces false-positive adoption
                # of positions the bot did not open.
                # NOTE: CLIENT_ORDER_TAG is not checked here because Alpaca does
                # not copy it from the parent to child legs.
                elif sym in open_position_map and trade_status not in ["ENTERED", "COMPLETED"]:
                    has_tp_leg = any(o.symbol == sym and o.type == "limit" for o in open_orders)
                    has_sl_leg = any(o.symbol == sym and o.type in ["stop", "stop_limit"] for o in open_orders)
                    if not (has_tp_leg and has_sl_leg):
                        continue  # Missing one or both bracket legs — not a bot position, leave it alone
                    pos = open_position_map[sym]
                    entry_price = float(pos.avg_entry_price)
                    side = "long" if float(pos.qty) > 0 else "short"
                    cfg = config.get(sym, {})
                    tp_order = next((o for o in open_orders if o.symbol == sym and o.type == "limit"), None)
                    sl_order = next((o for o in open_orders if o.symbol == sym and o.type in ["stop", "stop_limit"]), None)
                    # If the SL leg is missing (e.g. manually cancelled), reconstruct a
                    # percentage-based SL (SL_FALLBACK_PCT) so the TP ratio calculation stays realistic.
                    sl_price = float(sl_order.stop_price) if sl_order else (
                        entry_price * (1 - SL_FALLBACK_PCT) if side == "long" else entry_price * (1 + SL_FALLBACK_PCT)
                    )
                    if sl_order is None:
                        logger.warning(f"[{sym}] No SL order found on Alpaca. Using {SL_FALLBACK_PCT:.0%} fallback SL: ${sl_price:.2f}")
                    tp_ratio = cfg.get("LONG_TAKE_PROFIT_RATIO") if side == "long" else cfg.get("SHORT_TAKE_PROFIT_RATIO")
                    if tp_ratio and sl_price:
                        risk_per_share = abs(entry_price - sl_price)
                        original_tp = (entry_price + risk_per_share * tp_ratio) if side == "long" else (entry_price - risk_per_share * tp_ratio)
                    else:
                        original_tp = float(tp_order.limit_price) if tp_order else entry_price
                    state["trades"][sym] = {
                        "status": "ENTERED", "side": side,
                        "shares": abs(int(float(pos.qty))),
                        "entry_price": entry_price,
                        "original_tp": original_tp,
                        "current_tp": float(tp_order.limit_price) if tp_order else original_tp,
                        "sl_price": sl_price,
                        "parent_order_id": None,
                    }
                    logger.warning(f"[{sym}] Phantom position recovered! Was '{trade_status}' but found live on Alpaca. Resuming management.")
                    send_notification(f"⚠️ [{sym}] Phantom position recovered — resuming EOD management.")

                # Reconcile share count for positions that completed a partial fill after we stopped polling.
                elif trade_status == "ENTERED" and sym in open_position_map:
                    actual_live_qty = abs(int(float(open_position_map[sym].qty)))
                    if state["trades"][sym]["shares"] != actual_live_qty:
                        logger.info(
                            f"[{sym}] Share count trued-up after partial fill completion: "
                            f"{state['trades'][sym]['shares']} → {actual_live_qty} shares."
                        )
                        state["trades"][sym]["shares"] = actual_live_qty

        except Exception as e:
            logger.error(f"Error syncing mid-day positions from Alpaca: {e}")

    # 1. Establish ORB bounds for each symbol once its opening-range window has closed.
    for sym in symbols:
        if sym in state["orb_bounds"] or sym not in baselines:
            continue

        metrics = baselines[sym]
        orb_mins = metrics["orb_minutes"]
        orb_cutoff_dt = market_open_dt + timedelta(minutes=orb_mins)

        if now < orb_cutoff_dt:
            continue

        try:
            # ISO format handles timezone-aware localization automatically
            bars = api.get_bars(
                sym, tradeapi.TimeFrame.Minute,
                start=market_open_dt.isoformat(), end=orb_cutoff_dt.isoformat(),
                adjustment="all", feed=DATA_FEED,
            ).df

            if bars.empty:
                logger.warning(f"[{sym}] Waiting for completed ORB bars...")
                continue

            bars.index = pd.to_datetime(bars.index).tz_convert(EST)
            # Filter bars strictly within the first orb_mins of the market session
            orb_bars = bars[bars.index < orb_cutoff_dt]
            if orb_bars.empty:
                logger.warning(f"[{sym}] No ORB bars available after cutoff. Skipping {sym} for this session.")
                continue

            orb_high = float(orb_bars["high"].max())
            orb_low = float(orb_bars["low"].min())
            today_vol = float(orb_bars["volume"].sum())
            rvol = today_vol / metrics["avg_orb_volume"] if metrics["avg_orb_volume"] else 0.0

            state["orb_bounds"][sym] = {
                "high": orb_high,
                "low": orb_low,
                "rvol": rvol,
                "today_open": float(orb_bars["open"].iloc[0]),
            }
            logger.info(
                f"[{sym}] ORB bounds set. High: ${orb_high:.2f}, Low: ${orb_low:.2f}, "
                f"Today Vol: {today_vol:,.0f}, RVOL: {rvol:.2f}"
            )
        except Exception as e:
            logger.error(f"Error fetching ORB bounds for {sym}: {e}")

    # 2. Check for breakout entries.
    triggers = []
    for sym in symbols:
        if sym not in state["orb_bounds"] or sym in state["trades"] or sym not in baselines:
            continue
            
        # [ALPHA REDACTED FOR SHOWCASE]
        # Proprietary trade entry logic, including specific mathematical indicators, 
        # market filters, and asymmetric long/short breakout filtering have been 
        # removed from this public file.
        
        # In the real script, `triggers` is appended with validated breakout signals.
        pass

    # 3. Process simultaneous triggers with capital constraint limits.
    if triggers:
        try:
            account = api.get_account()
            total_equity = float(account.equity)

            invested_capital = 0.0
            if not DRY_RUN:
                positions = api.list_positions()
                invested_capital = sum(abs(float(pos.market_value)) for pos in positions)
            else:
                for s, tr in state.get("trades", {}).items():
                    if tr.get("status") == "ENTERED":
                        invested_capital += tr["shares"] * tr["entry_price"]

            available_equity = max(0.0, total_equity - invested_capital)
            capital_per_trade = available_equity / len(triggers)

            logger.info(
                f"Simultaneous triggers: {[t['sym'] for t in triggers]}. Total Equity: ${total_equity:,.2f}. "
                f"Available: ${available_equity:,.2f}. Capital per trade: ${capital_per_trade:,.2f}"
            )

            for t in triggers:
                try:
                    execute_order(api, t, total_equity, capital_per_trade, state)
                except Exception as e:
                    logger.error(f"[{t['sym']}] Unhandled exception in execute_order: {e}", exc_info=True)
                    state["trades"][t["sym"]] = {"status": "FAILED", "reason": f"execute_order exception: {e}"}
                    save_state(state)

        except Exception as e:
            logger.error(f"Error fetching account equity for trigger sizing: {e}")

    # 4. Dynamic target decay logic (runs during the afternoon).
    open_orders_cache = None  # Cache open orders once per cycle
    for sym in symbols:
        if sym not in state["trades"] or state["trades"][sym]["status"] != "ENTERED":
            continue

        trade = state["trades"][sym]
        cfg = config.get(sym)
        if cfg is None:
            continue

        try:
            decay_start = now.replace(
                hour=int(cfg["TARGET_DECAY_START_HOUR"]), minute=int(cfg["TARGET_DECAY_START_MINUTE"]),
                second=0, microsecond=0,
            )
            decay_end = now.replace(
                hour=int(cfg["TARGET_DECAY_END_HOUR"]), minute=int(cfg["TARGET_DECAY_END_MINUTE"]),
                second=0, microsecond=0,
            )

            if now < decay_start:
                continue

            total_duration = (decay_end - decay_start).total_seconds()
            elapsed = (now - decay_start).total_seconds()
            decay_fraction = min(1.0, max(0.0, elapsed / total_duration)) if total_duration > 0 else 1.0

            original_tp = trade["original_tp"]
            entry_price = trade["entry_price"]
            new_tp = original_tp - (original_tp - entry_price) * decay_fraction

            # Compute and log decay progress, updating state even in DRY_RUN
            prior_tp = trade.get("current_tp", original_tp)
            if abs(prior_tp - new_tp) > 0.005:
                logger.info(f"[{sym}] Target Decay progress: {decay_fraction:.1%}. TP: ${prior_tp:.2f} -> ${new_tp:.2f}")
            trade["current_tp"] = new_tp

            if DRY_RUN:
                continue

            try:
                if open_orders_cache is None:
                    open_orders_cache = api.list_orders(status="open", limit=500)
                tp_order = next((o for o in open_orders_cache if o.symbol == sym and o.type == "limit"), None)

                if tp_order is None:
                    logger.warning(f"[{sym}] No live TP order found on Alpaca — decay tracking continues in state but broker-side limit is inactive.")
                elif abs(float(tp_order.limit_price) - new_tp) > 0.05:
                    api.replace_order(tp_order.id, limit_price=round(new_tp, 2))
            except Exception as e:
                logger.error(f"[{sym}] Error updating decayed target order: {e}")
        except Exception as e:
            logger.error(f"[{sym}] Unhandled exception in decay loop: {e}", exc_info=True)

    # 5. EOD exit liquidation.
    if now >= eod_exit_time:
        entered_syms = [s for s in symbols if s in state["trades"] and state["trades"][s]["status"] == "ENTERED"]
        if entered_syms:
            liquidate_all(api, entered_syms, state)


# --- Sizer & Order Fills ---
def execute_order(api: "tradeapi.REST", t: dict, total_equity: float, capital_per_trade: float, state: dict):
    sym = t["sym"]
    side = t["side"]
    cfg = t["cfg"]
    entry_slippage_price = t["est_entry"]
    sl_price = t["sl_price"]
    risk_per_share = t["risk_per_share"]

    logger.info(f"⚠️ [{sym}] {side.upper()} Breakout Triggered at ${t['trigger_price']:.2f}")

    risk_percent = cfg["LONG_RISK_PERCENT"] if side == "long" else cfg["SHORT_RISK_PERCENT"]
    tp_ratio = cfg["LONG_TAKE_PROFIT_RATIO"] if side == "long" else cfg["SHORT_TAKE_PROFIT_RATIO"]

    desired_risk = total_equity * risk_percent
    desired_shares = int(desired_risk / risk_per_share)

    desired_capital = desired_shares * entry_slippage_price
    if desired_capital > capital_per_trade:
        shares = int(capital_per_trade / entry_slippage_price)
        logger.warning(f"[{sym}] Position size capped by capital limit. Reduced from {desired_shares} to {shares} shares.")
    else:
        shares = desired_shares

    max_shares = int((total_equity * MAX_POSITION_EQUITY_PCT) / entry_slippage_price)
    shares = min(shares, max_shares)

    # Position sizing micro-trade guard (invested > $100)
    if shares <= 0 or shares * entry_slippage_price < MIN_TRADE_NOTIONAL:
        logger.warning(
            f"[{sym}] Sized position (${shares * entry_slippage_price:,.2f}) below "
            f"${MIN_TRADE_NOTIONAL:.0f} minimum notional. Skipping trade."
        )
        state["trades"][sym] = {"status": "SKIPPED", "reason": "Below minimum trade notional"}
        return

    if side == "long":
        tp_price = entry_slippage_price + (risk_per_share * tp_ratio)
    else:
        tp_price = entry_slippage_price - (risk_per_share * tp_ratio)

    order_side = "buy" if side == "long" else "sell"

    logger.info(f"[{sym}] Compounding Sizing Base: ${total_equity:,.2f}. Risking {risk_percent:.2%}. Order Size: {shares} shares.")
    logger.info(f"[{sym}] Bracket Order details: Est. Entry: ${entry_slippage_price:.2f}, SL Stop: ${sl_price:.2f}, TP Limit: ${tp_price:.2f}")

    if DRY_RUN:
        send_notification(
            f"🧪 [DRY-RUN] {sym} {side.upper()} breakout entry simulated. Size: {shares} shares at "
            f"~${entry_slippage_price:.2f} (SL: ${sl_price:.2f}, TP: ${tp_price:.2f})"
        )
        state["trades"][sym] = {
            "status": "ENTERED", "side": side, "shares": shares,
            "entry_price": entry_slippage_price, "original_tp": tp_price,
            "current_tp": tp_price, "sl_price": sl_price,
        }
        save_state(state)
        return

    try:
        bracket_order = api.submit_order(
            symbol=sym, qty=shares, side=order_side, type="market", time_in_force="day",
            order_class="bracket",
            take_profit=dict(limit_price=round(tp_price, 2)),
            stop_loss=dict(stop_price=round(sl_price, 2)),
            client_order_id=f"{CLIENT_ORDER_TAG}-{sym}-{datetime.now(EST).strftime('%Y%m%d%H%M%S')}",
        )
        send_notification(
            f"🟢 [ORDER PLACED] {sym} {side.upper()} bracket order submitted. Size: {shares} shares. "
            f"Stop: ${sl_price:.2f}, Target: ${tp_price:.2f}. Waiting for fill..."
        )
        
        # Poll for fill status (up to ORDER_FILL_TIMEOUT seconds)
        filled = False
        actual_entry_price = entry_slippage_price
        actual_shares = shares
        ord_info = None
        for _ in range(ORDER_FILL_TIMEOUT):
            try:
                ord_info = api.get_order(bracket_order.id)
                if ord_info.status in ["filled", "partially_filled"]:
                    filled = True
                    actual_entry_price = float(ord_info.filled_avg_price)
                    actual_shares = int(float(ord_info.filled_qty))
                    break
                elif ord_info.status in ["rejected", "canceled"]:
                    break
            except Exception as e:
                logger.error(f"[{sym}] Error polling order status: {e}")
            if sleep_interruptible(1):
                break
            
        if filled:
            fill_type = ord_info.status  # "filled" or "partially_filled"
            send_notification(
                f"✅ [ORDER FILLED] {sym} {side.upper()} {fill_type}. "
                f"{actual_shares} shares @ ${actual_entry_price:.2f}. SL: ${sl_price:.2f}, TP: ${tp_price:.2f}"
            )
            state["trades"][sym] = {
                "status": "ENTERED", "side": side, "shares": actual_shares,
                "entry_price": actual_entry_price, "original_tp": tp_price,
                "current_tp": tp_price, "sl_price": sl_price,
                "parent_order_id": bracket_order.id,
            }
        else:
            status_str = ord_info.status if ord_info else "unknown"
            logger.error(f"[{sym}] Order not filled in time or failed. Status: {status_str}. Cancelling pending order...")
            try:
                if ord_info is None:
                    # All get_order polls raised exceptions — we don't know broker state.
                    # Attempt cancellation defensively; it's a no-op if the order already filled.
                    logger.warning(f"[{sym}] Order status unknown after polling. Attempting defensive cancel.")
                    api.cancel_order(bracket_order.id)
                elif ord_info.status not in ["rejected", "canceled", "filled"]:
                    api.cancel_order(bracket_order.id)
                elif ord_info.status == "rejected":
                    logger.info(f"[{sym}] Order was rejected by broker — no cancellation needed.")
            except Exception as e:
                logger.error(f"[{sym}] Failed to cancel hanging order: {e}")
            send_notification(f"⚠️ [ORDER FAILED] Order for {sym} failed to fill (cancelled). Status: {status_str}")
            state["trades"][sym] = {
                "status": "FAILED", 
                "reason": f"Order status: {status_str} (timeout cancelled)"
            }
        save_state(state)
    except Exception as e:
        logger.error(f"[{sym}] Failed to submit bracket order: {e}")
        send_notification(f"⚠️ [ORDER FAILED] Failed to place order for {sym}: {e}")
        state["trades"][sym] = {"status": "FAILED", "reason": str(e)}
        save_state(state)


# --- Liquidation Engine ---
def liquidate_all(api: "tradeapi.REST", symbols_to_close: list, state: dict):
    """
    FIX (critical): the previous version called api.cancel_all_orders()
    separately inside a per-symbol liquidate function, once per entered
    symbol. cancel_all_orders() cancels every open order on the *account*,
    not just the symbol being processed -- so on a multi-position basket
    day, liquidating the first symbol stripped stop-loss/take-profit
    protection off every other still-open position before their own
    liquidation ran, leaving them briefly unprotected. Orders are now
    cancelled once, up front, then each position is closed individually.
    """
    logger.info(f"🔴 Market close approaching. Executing EOD liquidation for: {symbols_to_close}")

    if DRY_RUN:
        for sym in symbols_to_close:
            send_notification(f"🧪 [DRY-RUN LIQUIDATED] Simulated exit for {sym} at Market price.")
            state["trades"][sym]["status"] = "COMPLETED"
            state["trades"][sym]["exit_reason"] = "EOD Exit"
        save_state(state)
        return

    try:
        # Cancel only open orders for the symbols we are liquidating, leaving other strategies untouched
        open_orders = api.list_orders(status="open", limit=500)
        target_orders = [o for o in open_orders if o.symbol in symbols_to_close]
        for order in target_orders:
            try:
                api.cancel_order(order.id)
            except Exception as e:
                logger.error(f"[{order.symbol}] Failed to cancel order {order.id}: {e}")
        # Poll up to 5 seconds for cancellations to complete
        for _ in range(5):
            still_open = [o for o in api.list_orders(status="open", limit=500) if o.symbol in symbols_to_close]
            if not still_open:
                break
            time.sleep(1)
    except Exception as e:
        logger.error(f"Error cancelling open orders during EOD liquidation: {e}")
        send_notification(f"⚠️ [LIQUIDATION WARNING] Failed to cancel open orders cleanly: {e}")

    for sym in symbols_to_close:
        try:
            api.close_position(sym)
            send_notification(f"🔴 [EOD LIQUIDATED] Closed active position in {sym} at market price.")
            state["trades"][sym]["status"] = "COMPLETED"
            state["trades"][sym]["exit_reason"] = "EOD Exit"
        except Exception as e:
            logger.error(f"[{sym}] Error during EOD liquidation: {e}")
            send_notification(f"⚠️ [LIQUIDATION FAILED] EOD liquidation failed for {sym}: {e}. Will retry next cycle.")
            # Keep status as ENTERED so the next 30-second cycle retries liquidation.
            # Do NOT mark LIQUIDATION_FAILED — that status has no retry path.
    save_state(state)


if __name__ == "__main__":
    run_trader()
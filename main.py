from fastapi import FastAPI
import requests
import time
import threading

app = FastAPI()

BASE_URL = "https://contract.mexc.com"

BOT_RUNNING = False
BALANCE = 1000.0
REALIZED_PNL = 0.0
WIN = 0
LOSS = 0

POSITIONS = []
CLOSED = []
LOGS = []
COOLDOWN = {}

SETTINGS = {
    "max_positions": 3,
    "max_same_side": 3,
    "balance_filter": True,
    "margin": 5.0,
    "leverage": 10,
    "tp_percent": 3.0,
    "sl_percent": 1.5,
    "trailing_start_percent": 1.5,
    "trailing_gap_percent": 0.8,
    "cooldown_sec": 300,
    "top_scan": 20
}


def log(msg):
    LOGS.insert(0, time.strftime("%H:%M:%S") + " " + msg)
    if len(LOGS) > 100:
        LOGS.pop()


@app.get("/")
def home():
    return {
        "status": "ok",
        "bot": "V3.1 FULL 13 indicator + TP/SL + trailing + cooldown fix"
    }


def get_tickers():
    try:
        r = requests.get(f"{BASE_URL}/api/v1/contract/ticker", timeout=10)
        return r.json().get("data", [])
    except Exception as e:
        log(f"Ticker hata: {e}")
        return []


def get_price(symbol):
    for t in get_tickers():
        if t.get("symbol") == symbol:
            for key in ["lastPrice", "last", "fairPrice", "indexPrice"]:
                if key in t:
                    try:
                        return float(t[key])
                    except:
                        pass
    return None


def get_top_symbols():
    data = get_tickers()

    def volume_value(x):
        for key in ["amount24", "amount", "volume24", "volume"]:
            try:
                return float(x.get(key, 0))
            except:
                continue
        return 0

    items = [x for x in data if "USDT" in x.get("symbol", "")]
    items = sorted(items, key=volume_value, reverse=True)
    return [x["symbol"] for x in items[:SETTINGS["top_scan"]]]


def get_klines(symbol):
    url = f"{BASE_URL}/api/v1/contract/kline/{symbol}"
    params = {"interval": "Min5", "limit": 80}

    r = requests.get(url, params=params, timeout=10)
    data = r.json().get("data", {})

    closes = list(map(float, data.get("close", [])[-60:]))
    highs = list(map(float, data.get("high", [])[-60:]))
    lows = list(map(float, data.get("low", [])[-60:]))
    vols = list(map(float, data.get("vol", data.get("volume", []))[-60:]))

    return closes, highs, lows, vols


def sma(values, length):
    if len(values) < length:
        return None
    return sum(values[-length:]) / length


def calc_indicators(closes, highs, lows, vols):
    signals = []

    ema9 = sma(closes, 9)
    ema21 = sma(closes, 21)
    ema50 = sma(closes, 50)
    avg20 = sma(closes, 20)

    signals.append(1 if ema9 > ema21 else -1)
    signals.append(1 if closes[-1] > ema50 else -1)
    signals.append(1 if closes[-1] > avg20 else -1)

    momentum = closes[-1] - closes[-10]
    signals.append(1 if momentum > 0 else -1)

    roc = (closes[-1] - closes[-5]) / closes[-5]
    signals.append(1 if roc > 0 else -1)

    lowest14 = min(lows[-14:])
    highest14 = max(highs[-14:])
    stoch = (closes[-1] - lowest14) / (highest14 - lowest14 + 1e-9)
    signals.append(1 if stoch < 0.25 else (-1 if stoch > 0.75 else 0))

    gains = []
    losses = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))

    avg_gain = sum(gains[-14:]) / 14
    avg_loss = sum(losses[-14:]) / 14 if sum(losses[-14:]) != 0 else 1
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    signals.append(1 if rsi < 35 else (-1 if rsi > 65 else 0))

    macd = ema9 - ema21
    signals.append(1 if macd > 0 else -1)

    avg_vol = sum(vols[-20:]) / 20 if len(vols) >= 20 else 0
    volume_signal = 1 if len(vols) >= 20 and vols[-1] > avg_vol * 1.15 else 0
    signals.append(volume_signal)

    tenkan = (max(highs[-9:]) + min(lows[-9:])) / 2
    kijun = (max(highs[-26:]) + min(lows[-26:])) / 2
    signals.append(1 if tenkan > kijun else -1)

    signals.append(1 if closes[-1] > ema21 else -1)
    signals.append(1 if closes[-1] > avg20 else -1)
    signals.append(1 if closes[-1] > closes[-2] else -1)

    return signals, rsi, volume_signal


def get_signal_detail(symbol):
    try:
        closes, highs, lows, vols = get_klines(symbol)

        if len(closes) < 50 or len(highs) < 50 or len(lows) < 50:
            return {
                "symbol": symbol,
                "signal": "BEKLE",
                "score": 0,
                "reason": "Yetersiz mum"
            }

        signals, rsi, volume_signal = calc_indicators(closes, highs, lows, vols)
        score = sum(signals)

        if score >= 6 or (score >= 4 and volume_signal == 1):
            signal = "LONG"
        elif score <= -6 or (score <= -4 and volume_signal == 1):
            signal = "SHORT"
        else:
            signal = "BEKLE"

        return {
            "symbol": symbol,
            "signal": signal,
            "score": score,
            "rsi": round(rsi, 2),
            "volume_ok": bool(volume_signal)
        }

    except Exception as e:
        return {
            "symbol": symbol,
            "signal": "BEKLE",
            "score": 0,
            "error": str(e)
        }


def can_open_side(side):
    if not SETTINGS["balance_filter"]:
        return True

    same_side = len([p for p in POSITIONS if p["side"] == side])
    return same_side < SETTINGS["max_same_side"]


def is_in_cooldown(symbol):
    return time.time() < COOLDOWN.get(symbol, 0)


def open_trade(symbol, side):
    global BALANCE

    if len(POSITIONS) >= SETTINGS["max_positions"]:
        return False

    if any(p["symbol"] == symbol for p in POSITIONS):
        return False

    if is_in_cooldown(symbol):
        log(f"Cooldown: {symbol}")
        return False

    if not can_open_side(side):
        log(f"Denge filtresi: {side} fazla")
        return False

    price = get_price(symbol)
    if not price:
        log(f"Fiyat alınamadı: {symbol}")
        return False

    margin = SETTINGS["margin"]
    leverage = SETTINGS["leverage"]

    if BALANCE < margin:
        log("Bakiye yetersiz")
        return False

    qty = (margin * leverage) / price
    BALANCE -= margin

    POSITIONS.append({
        "symbol": symbol,
        "side": side,
        "entry": price,
        "last": price,
        "qty": qty,
        "margin": margin,
        "leverage": leverage,
        "pnl": 0.0,
        "change_percent": 0.0,
        "best_percent": 0.0,
        "trailing_active": False,
        "tp_percent": SETTINGS["tp_percent"],
        "sl_percent": SETTINGS["sl_percent"],
        "opened_at": time.time()
    })

    log(f"DEMO {side} açıldı: {symbol} | Margin ${margin} | {leverage}x")
    return True


def close_trade(pos, reason):
    global BALANCE, REALIZED_PNL, WIN, LOSS

    if pos not in POSITIONS:
        return

    price = get_price(pos["symbol"]) or pos["last"]

    if pos["side"] == "LONG":
        pnl = (price - pos["entry"]) * pos["qty"]
    else:
        pnl = (pos["entry"] - price) * pos["qty"]

    BALANCE += pos["margin"] + pnl
    REALIZED_PNL += pnl

    if pnl >= 0:
        WIN += 1
    else:
        LOSS += 1

    closed = pos.copy()
    closed["close"] = price
    closed["pnl"] = pnl
    closed["reason"] = reason
    closed["closed_at"] = time.time()

    CLOSED.insert(0, closed)
    POSITIONS.remove(pos)

    COOLDOWN[pos["symbol"]] = time.time() + SETTINGS["cooldown_sec"]

    log(f"{reason}: {pos['symbol']} kapandı | PnL ${round(pnl, 4)}")


def update_positions():
    for p in POSITIONS[:]:
        if p not in POSITIONS:
            continue

        price = get_price(p["symbol"])
        if not price:
            continue

        p["last"] = price

        if p["side"] == "LONG":
            pnl = (price - p["entry"]) * p["qty"]
            change_percent = ((price - p["entry"]) / p["entry"]) * 100 * p["leverage"]
        else:
            pnl = (p["entry"] - price) * p["qty"]
            change_percent = ((p["entry"] - price) / p["entry"]) * 100 * p["leverage"]

        p["pnl"] = pnl
        p["change_percent"] = round(change_percent, 4)

        if change_percent > p["best_percent"]:
            p["best_percent"] = change_percent

        if change_percent >= SETTINGS["trailing_start_percent"]:
            p["trailing_active"] = True

        close_reason = None

        if change_percent >= SETTINGS["tp_percent"]:
            close_reason = "TP"
        elif change_percent <= -SETTINGS["sl_percent"]:
            close_reason = "SL"
        elif p["trailing_active"] and change_percent <= p["best_percent"] - SETTINGS["trailing_gap_percent"]:
            close_reason = "TRAILING"

        if close_reason:
            close_trade(p, close_reason)


def bot_loop():
    global BOT_RUNNING

    log("Bot başladı")

    while BOT_RUNNING:
        try:
            update_positions()
            symbols = get_top_symbols()

            for symbol in symbols:
                if len(POSITIONS) >= SETTINGS["max_positions"]:
                    break

                detail = get_signal_detail(symbol)
                signal = detail["signal"]

                if signal in ["LONG", "SHORT"]:
                    open_trade(symbol, signal)

            time.sleep(15)

        except Exception as e:
            log(f"Bot hata: {e}")
            time.sleep(5)

    log("Bot durdu")


@app.get("/start")
def start():
    global BOT_RUNNING

    if BOT_RUNNING:
        return {"status": "already_running"}

    BOT_RUNNING = True
    threading.Thread(target=bot_loop, daemon=True).start()
    return {"status": "started"}


@app.get("/stop")
def stop():
    global BOT_RUNNING
    BOT_RUNNING = False
    return {"status": "stopped"}


@app.get("/positions")
def positions():
    update_positions()
    return {"count": len(POSITIONS), "positions": POSITIONS}


@app.get("/balance")
def balance():
    update_positions()
    open_pnl = sum(p.get("pnl", 0) for p in POSITIONS)

    return {
        "balance": round(BALANCE, 4),
        "open_pnl": round(open_pnl, 4),
        "equity": round(BALANCE + open_pnl, 4),
        "open_positions": len(POSITIONS)
    }


@app.get("/report")
def report():
    update_positions()

    open_pnl = sum(p.get("pnl", 0) for p in POSITIONS)
    total_closed = WIN + LOSS
    winrate = (WIN / total_closed * 100) if total_closed else 0

    long_count = len([p for p in POSITIONS if p["side"] == "LONG"])
    short_count = len([p for p in POSITIONS if p["side"] == "SHORT"])

    return {
        "balance": round(BALANCE, 4),
        "open_pnl": round(open_pnl, 4),
        "equity": round(BALANCE + open_pnl, 4),
        "realized_pnl": round(REALIZED_PNL, 4),
        "positions": len(POSITIONS),
        "long_positions": long_count,
        "short_positions": short_count,
        "closed_positions": total_closed,
        "win": WIN,
        "loss": LOSS,
        "winrate": round(winrate, 2),
        "logs": LOGS[:30],
        "closed": CLOSED[:20]
    }


@app.get("/scan")
def scan():
    results = []
    symbols = get_top_symbols()

    for symbol in symbols:
        results.append(get_signal_detail(symbol))

    return {
        "status": "ok",
        "count": len(results),
        "results": results
    }


@app.get("/force_open")
def force_open(symbol: str = "BTC_USDT", side: str = "LONG"):
    ok = open_trade(symbol, side.upper())

    return {
        "status": "opened" if ok else "failed",
        "symbol": symbol,
        "side": side.upper()
    }


@app.get("/settings")
def settings():
    return SETTINGS

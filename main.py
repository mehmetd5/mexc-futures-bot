from fastapi import FastAPI
import requests, time, threading

app = FastAPI()

BASE_URL = "https://contract.mexc.com"

BOT_RUNNING = False
BALANCE = 1000.0
REALIZED_PNL = 0.0
POSITIONS = []
LOGS = []

SETTINGS = {
    "max_positions": 3,
    "margin": 5.0,
    "leverage": 10,
    "tp_percent": 3.0,
    "sl_percent": 1.5,
    "top_scan": 20
}


def log(msg):
    LOGS.insert(0, time.strftime("%H:%M:%S") + " " + msg)
    if len(LOGS) > 80:
        LOGS.pop()


@app.get("/")
def home():
    return {"status": "ok", "bot": "V2 13 indicator aktif"}


def get_tickers():
    r = requests.get(f"{BASE_URL}/api/v1/contract/ticker", timeout=10)
    return r.json().get("data", [])


def get_price(symbol):
    for t in get_tickers():
        if t.get("symbol") == symbol:
            for k in ["lastPrice", "last", "fairPrice", "indexPrice"]:
                if k in t:
                    return float(t[k])
    return None


def get_top_symbols():
    data = get_tickers()

    def vol(x):
        for k in ["amount24", "amount", "volume24", "volume"]:
            try:
                return float(x.get(k, 0))
            except:
                return 0
        return 0

    items = [x for x in data if "USDT" in x.get("symbol", "")]
    items = sorted(items, key=vol, reverse=True)
    return [x["symbol"] for x in items[:SETTINGS["top_scan"]]]


def get_klines(symbol):
    url = f"{BASE_URL}/api/v1/contract/kline/{symbol}"
    params = {"interval": "Min5", "limit": 80}
    r = requests.get(url, params=params, timeout=10)
    data = r.json().get("data", {})

    closes = list(map(float, data.get("close", [])[-60:]))
    vols = list(map(float, data.get("vol", data.get("volume", []))[-60:]))

    return closes, vols


def calc_indicators(closes, vols):
    signals = []

    ema9 = sum(closes[-9:]) / 9
    ema21 = sum(closes[-21:]) / 21
    signals.append(1 if ema9 > ema21 else -1)

    ema50 = sum(closes[-50:]) / 50
    signals.append(1 if closes[-1] > ema50 else -1)

    avg20 = sum(closes[-20:]) / 20
    signals.append(1 if closes[-1] > avg20 else -1)

    momentum = closes[-1] - closes[-10]
    signals.append(1 if momentum > 0 else -1)

    roc = (closes[-1] - closes[-5]) / closes[-5]
    signals.append(1 if roc > 0 else -1)

    lowest = min(closes[-14:])
    highest = max(closes[-14:])
    stoch = (closes[-1] - lowest) / (highest - lowest + 1e-6)
    signals.append(1 if stoch < 0.25 else (-1 if stoch > 0.75 else 0))

    gains = [max(closes[i] - closes[i - 1], 0) for i in range(1, len(closes))]
    losses = [max(closes[i - 1] - closes[i], 0) for i in range(1, len(closes))]
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

    tenkan = (max(closes[-9:]) + min(closes[-9:])) / 2
    kijun = (max(closes[-26:]) + min(closes[-26:])) / 2
    signals.append(1 if tenkan > kijun else -1)

    signals.append(1 if closes[-1] > ema21 else -1)

    bb_mid = avg20
    signals.append(1 if closes[-1] > bb_mid else -1)

    candle = 1 if closes[-1] > closes[-2] else -1
    signals.append(candle)

    return signals, rsi, volume_signal


def get_signal_detail(symbol):
    try:
        closes, vols = get_klines(symbol)

        if len(closes) < 50:
            return {
                "symbol": symbol,
                "signal": "BEKLE",
                "score": 0,
                "reason": "Yetersiz mum"
            }

        signals, rsi, volume_signal = calc_indicators(closes, vols)
        score = sum(signals)

        if score >= 6 and volume_signal == 1:
            signal = "LONG"
        elif score <= -6 and volume_signal == 1:
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


def get_signal(symbol):
    return get_signal_detail(symbol)["signal"]


def open_trade(symbol, side):
    global BALANCE

    if len(POSITIONS) >= SETTINGS["max_positions"]:
        return False

    if any(p["symbol"] == symbol for p in POSITIONS):
        return False

    price = get_price(symbol)
    if not price:
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
        "tp_percent": SETTINGS["tp_percent"],
        "sl_percent": SETTINGS["sl_percent"],
        "opened_at": time.time()
    })

    log(f"DEMO {side} açıldı: {symbol} | Margin ${margin} | {leverage}x")
    return True


def update_positions():
    for p in POSITIONS:
        price = get_price(p["symbol"])
        if not price:
            continue

        p["last"] = price

        if p["side"] == "LONG":
            p["pnl"] = (price - p["entry"]) * p["qty"]
        else:
            p["pnl"] = (p["entry"] - price) * p["qty"]


def bot_loop():
    global BOT_RUNNING

    log("Bot başladı")

    while BOT_RUNNING:
        try:
            update_positions()

            symbols = get_top_symbols()

            for s in symbols:
                if len(POSITIONS) >= SETTINGS["max_positions"]:
                    break

                detail = get_signal_detail(s)
                signal = detail["signal"]

                if signal in ["LONG", "SHORT"]:
                    open_trade(s, signal)

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
    return {
        "balance": round(BALANCE, 4),
        "open_pnl": round(open_pnl, 4),
        "equity": round(BALANCE + open_pnl, 4),
        "positions": len(POSITIONS),
        "logs": LOGS[:30]
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

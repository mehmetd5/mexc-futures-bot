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
    "margin": 5,
    "leverage": 10,
    "tp_percent": 3,
    "sl_percent": 1.5,
    "top_scan": 20
}

# ---------------- LOG ----------------
def log(msg):
    LOGS.insert(0, msg)
    if len(LOGS) > 50:
        LOGS.pop()

# ---------------- API ----------------
@app.get("/")
def home():
    return {"status": "ok", "bot": "V2 13 indicator aktif"}

@app.get("/start")
def start():
    global BOT_RUNNING
    BOT_RUNNING = True
    threading.Thread(target=bot_loop, daemon=True).start()
    return {"status": "started"}

@app.get("/stop")
def stop():
    global BOT_RUNNING
    BOT_RUNNING = False
    return {"status": "stopped"}

@app.get("/positions")
def get_positions():
    return {"count": len(POSITIONS), "positions": POSITIONS}

@app.get("/balance")
def balance():
    open_pnl = sum(p["pnl"] for p in POSITIONS)
    return {
        "balance": BALANCE,
        "open_pnl": open_pnl,
        "equity": BALANCE + open_pnl
    }

@app.get("/report")
def report():
    return {
        "balance": BALANCE,
        "positions": len(POSITIONS),
        "logs": LOGS[:20]
    }

# ---------------- DATA ----------------
def get_tickers():
    return requests.get(f"{BASE_URL}/api/v1/contract/ticker").json()["data"]

def get_price(symbol):
    for t in get_tickers():
        if t["symbol"] == symbol:
            return float(t["lastPrice"])
    return None

def get_top_symbols():
    data = get_tickers()
    sorted_data = sorted(data, key=lambda x: float(x["amount"]), reverse=True)
    return [x["symbol"] for x in sorted_data if "USDT" in x["symbol"]][:SETTINGS["top_scan"]]

def get_klines(symbol):
    url = f"{BASE_URL}/api/v1/contract/kline/{symbol}?interval=Min5&limit=60"
    data = requests.get(url).json()["data"]

    closes = list(map(float, data["close"]))
    vols = list(map(float, data.get("vol", data.get("volume", []))))

    return closes, vols

# ---------------- 13 INDICATOR ----------------
def calc_indicators(closes, vols):
    signals = []

    ema9 = sum(closes[-9:]) / 9
    ema21 = sum(closes[-21:]) / 21
    signals.append(1 if ema9 > ema21 else -1)

    avg = sum(closes[-20:]) / 20
    signals.append(1 if closes[-1] > avg else -1)

    momentum = closes[-1] - closes[-10]
    signals.append(1 if momentum > 0 else -1)

    roc = (closes[-1] - closes[-5]) / closes[-5]
    signals.append(1 if roc > 0 else -1)

    lowest = min(closes[-14:])
    highest = max(closes[-14:])
    stoch = (closes[-1] - lowest) / (highest - lowest + 1e-6)
    signals.append(1 if stoch < 0.2 else (-1 if stoch > 0.8 else 0))

    gains = [max(closes[i]-closes[i-1], 0) for i in range(1,len(closes))]
    losses = [max(closes[i-1]-closes[i], 0) for i in range(1,len(closes))]
    avg_gain = sum(gains[-14:]) / 14
    avg_loss = sum(losses[-14:]) / 14 if sum(losses[-14:]) != 0 else 1
    rs = avg_gain / avg_loss
    rsi = 100 - (100/(1+rs))
    signals.append(1 if rsi < 35 else (-1 if rsi > 65 else 0))

    avg_vol = sum(vols[-20:]) / 20 if len(vols)>=20 else 0
    signals.append(1 if vols[-1] > avg_vol*1.2 else 0)

    high9 = max(closes[-9:])
    low9 = min(closes[-9:])
    tenkan = (high9 + low9)/2

    high26 = max(closes[-26:])
    low26 = min(closes[-26:])
    kijun = (high26 + low26)/2

    signals.append(1 if tenkan > kijun else -1)

    return signals

# ---------------- SIGNAL ----------------
def get_signal(symbol):
    closes, vols = get_klines(symbol)

    if len(closes) < 30:
        return "BEKLE"

    signals = calc_indicators(closes, vols)
    score = sum(signals)

    if score >= 5:
        return "LONG"
    elif score <= -5:
        return "SHORT"
    else:
        return "BEKLE"

# ---------------- TRADE ----------------
def open_trade(symbol, side):
    global BALANCE

    if len(POSITIONS) >= SETTINGS["max_positions"]:
        return

    price = get_price(symbol)
    qty = (SETTINGS["margin"] * SETTINGS["leverage"]) / price

    BALANCE -= SETTINGS["margin"]

    POSITIONS.append({
        "symbol": symbol,
        "side": side,
        "entry": price,
        "qty": qty,
        "pnl": 0
    })

    log(f"{side} açıldı: {symbol}")

def update_positions():
    for p in POSITIONS:
        price = get_price(p["symbol"])
        if not price:
            continue

        if p["side"] == "LONG":
            p["pnl"] = (price - p["entry"]) * p["qty"]
        else:
            p["pnl"] = (p["entry"] - price) * p["qty"]

# ---------------- BOT ----------------
def bot_loop():
    global BOT_RUNNING

    while BOT_RUNNING:
        try:
            update_positions()

            symbols = get_top_symbols()

            for s in symbols:
                if len(POSITIONS) >= SETTINGS["max_positions"]:
                    break

                signal = get_signal(s)

                if signal in ["LONG", "SHORT"]:
                    open_trade(s, signal)

            time.sleep(15)

        except:
            time.sleep(5)
@app.get("/scan")
def scan():
    results = []

    for symbol in SYMBOLS:
        try:
            candles = get_candles(symbol)
            signal = generate_signal(candles)

            results.append({
                "symbol": symbol,
                "signal": signal
            })

        except Exception as e:
            results.append({
                "symbol": symbol,
                "error": str(e)
            })

    return results

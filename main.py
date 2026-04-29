from fastapi import FastAPI
import requests, time, threading

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
    "max_same_side": 2,
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
    return {"status": "ok", "bot": "V3 13 indicator + TP/SL + trailing + cooldown"}


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
    signals.append(1 if rsi < 35 else

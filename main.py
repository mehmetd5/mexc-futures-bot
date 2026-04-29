from fastapi import FastAPI
import requests, time, threading, os, hmac, hashlib, json

app = FastAPI()

BASE_URL = "https://contract.mexc.com"

MEXC_KEY = os.getenv("MEXC_KEY")
MEXC_SECRET = os.getenv("MEXC_SECRET")

LIVE_TRADING = os.getenv("LIVE_TRADING", "false").lower() == "true"

MARGIN = float(os.getenv("MARGIN", 2))
LEVERAGE = int(os.getenv("LEVERAGE", 3))
MAX_POSITIONS = int(os.getenv("MAX_POSITIONS", 4))

BOT_RUNNING = False

POSITIONS = []
LOGS = []

# ---------------- SIGN ----------------
def sign(query):
    return hmac.new(
        MEXC_SECRET.encode(),
        query.encode(),
        hashlib.sha256
    ).hexdigest()

# ---------------- GET PRICE ----------------
def get_price(symbol):
    url = f"{BASE_URL}/api/v1/contract/ticker"
    r = requests.get(url).json()
    for x in r["data"]:
        if x["symbol"] == symbol:
            return float(x["lastPrice"])
    return None

# ---------------- ORDER ----------------
def place_order(symbol, side):

    price = get_price(symbol)
    if not price:
        return False

    qty = round((MARGIN * LEVERAGE) / price, 4)

    if not LIVE_TRADING:
        LOGS.append(f"PAPER {side} {symbol}")
        POSITIONS.append({"symbol": symbol, "side": side})
        return True

    timestamp = str(int(time.time() * 1000))

    body = {
        "symbol": symbol,
        "price": price,
        "vol": qty,
        "side": 1 if side == "LONG" else 3,
        "type": 1,
        "openType": 1,
        "leverage": LEVERAGE
    }

    query = json.dumps(body)
    signature = sign(query)

    headers = {
        "ApiKey": MEXC_KEY,
        "Request-Time": timestamp,
        "Signature": signature,
        "Content-Type": "application/json"
    }

    url = f"{BASE_URL}/api/v1/private/order/submit"

    r = requests.post(url, headers=headers, data=query)

    LOGS.append(f"REAL {side} {symbol} -> {r.text}")

    return True

# ---------------- SIGNAL ----------------
def get_signal():
    coins = ["BTC_USDT","ETH_USDT","SOL_USDT","XRP_USDT"]

    results = []

    for c in coins:
        rsi = 50  # basit demo

        if rsi > 55:
            results.append((c, "SHORT"))
        elif rsi < 45:
            results.append((c, "LONG"))

    return results

# ---------------- BOT LOOP ----------------
def bot_loop():
    global BOT_RUNNING

    while BOT_RUNNING:

        signals = get_signal()

        if len(POSITIONS) < MAX_POSITIONS:
            for s in signals:
                if len(POSITIONS) >= MAX_POSITIONS:
                    break

                place_order(s[0], s[1])

        time.sleep(20)

# ---------------- API ----------------

@app.get("/")
def home():
    return {"status": "ok"}

@app.get("/start")
def start():
    global BOT_RUNNING
    if BOT_RUNNING:
        return {"status": "already_running"}

    BOT_RUNNING = True
    threading.Thread(target=bot_loop).start()

    return {"status": "started"}

@app.get("/stop")
def stop():
    global BOT_RUNNING
    BOT_RUNNING = False
    return {"status": "stopped"}

@app.get("/positions")
def positions():
    return POSITIONS

@app.get("/logs")
def logs():
    return LOGS

@app.get("/api_test")
def api_test():
    return {
        "api_key_loaded": bool(MEXC_KEY),
        "secret_loaded": bool(MEXC_SECRET),
        "live": LIVE_TRADING
}

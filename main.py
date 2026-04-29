from fastapi import FastAPI
import requests, time, threading

app = FastAPI()

BASE_URL = "https://contract.mexc.com"

BOT_RUNNING = False
BALANCE = 1000.0
POSITIONS = []
LOGS = []

def log(msg):
    LOGS.insert(0, time.strftime("%H:%M:%S") + " " + msg)

@app.get("/")
def home():
    return {"status": "ok", "bot": "V3 çalışıyor"}

def get_price(symbol):
    try:
        r = requests.get(f"{BASE_URL}/api/v1/contract/ticker")
        data = r.json()["data"]
        for t in data:
            if t["symbol"] == symbol:
                return float(t["lastPrice"])
    except:
        return None

def open_trade(symbol, side):
    global BALANCE

    if len(POSITIONS) >= 3:
        return

    price = get_price(symbol)
    if not price:
        return

    margin = 5
    leverage = 10
    qty = (margin * leverage) / price

    POSITIONS.append({
        "symbol": symbol,
        "side": side,
        "entry": price,
        "qty": qty
    })

    BALANCE -= margin
    log(f"{side} açıldı: {symbol}")

def bot_loop():
    global BOT_RUNNING

    symbols = ["BTC_USDT", "ETH_USDT", "DOGE_USDT"]

    while BOT_RUNNING:
        try:
            for s in symbols:
                if len(POSITIONS) < 3:
                    open_trade(s, "LONG")
            time.sleep(10)
        except:
            time.sleep(5)

@app.get("/start")
def start():
    global BOT_RUNNING

    if BOT_RUNNING:
        return {"status": "running"}

    BOT_RUNNING = True
    threading.Thread(target=bot_loop).start()

    return {"status": "started"}

@app.get("/positions")
def positions():
    return POSITIONS

@app.get("/balance")
def balance():
    return {"balance": BALANCE}

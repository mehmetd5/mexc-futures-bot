from fastapi import FastAPI
import requests, time, threading

app = FastAPI()

BASE_URL = "https://contract.mexc.com"

BOT_RUNNING = False
BALANCE = 1000.0
POSITIONS = []

SETTINGS = {
    "max_positions": 2,
    "leverage": 5,
    "tp": 0.02,
    "sl": 0.01
}

# --- ANA SAYFA ---
@app.get("/")
def home():
    return {"status": "ok", "message": "MEXC Futures Bot Aktif"}

# --- BOT BAŞLAT ---
@app.get("/start")
def start():
    global BOT_RUNNING
    BOT_RUNNING = True
    threading.Thread(target=bot_loop).start()
    return {"status": "Bot başlatıldı"}

# --- BOT DURDUR ---
@app.get("/stop")
def stop():
    global BOT_RUNNING
    BOT_RUNNING = False
    return {"status": "Bot durduruldu"}

# --- POZİSYONLAR ---
@app.get("/positions")
def get_positions():
    return {
        "count": len(POSITIONS),
        "positions": POSITIONS
    }

# --- BALANCE ---
@app.get("/balance")
def balance():
    return {
        "balance": BALANCE,
        "open_positions": len(POSITIONS)
    }

# --- HACİM TOP COIN ---
def get_top_symbols():
    url = f"{BASE_URL}/api/v1/contract/ticker"
    data = requests.get(url).json()["data"]

    sorted_list = sorted(
        data,
        key=lambda x: float(x["amount"]),
        reverse=True
    )

    return [x["symbol"] for x in sorted_list[:5]]

# --- BASİT SİNYAL ---
def get_signal(symbol):
    url = f"{BASE_URL}/api/v1/contract/kline/{symbol}?interval=Min5&limit=20"
    data = requests.get(url).json()["data"]

    closes = [float(x["close"]) for x in data]

    avg = sum(closes) / len(closes)
    last = closes[-1]

    if last > avg:
        return "LONG"
    elif last < avg:
        return "SHORT"
    return None

# --- POZİSYON AÇ ---
def open_position(symbol, direction):
    if len(POSITIONS) >= SETTINGS["max_positions"]:
        return

    price = requests.get(f"{BASE_URL}/api/v1/contract/ticker").json()["data"][0]["lastPrice"]

    pos = {
        "symbol": symbol,
        "side": direction,
        "entry": float(price),
        "tp": float(price) * (1 + SETTINGS["tp"] if direction == "LONG" else 1 - SETTINGS["tp"]),
        "sl": float(price) * (1 - SETTINGS["sl"] if direction == "LONG" else 1 + SETTINGS["sl"])
    }

    POSITIONS.append(pos)

# --- BOT LOOP ---
def bot_loop():
    global BOT_RUNNING

    while BOT_RUNNING:
        try:
            symbols = get_top_symbols()

            for s in symbols:
                signal = get_signal(s)

                if signal:
                    open_position(s, signal)

            time.sleep(10)

        except:
            time.sleep(5)

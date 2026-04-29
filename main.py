from fastapi import FastAPI
import requests
import time
import threading

app = FastAPI()

BOT_RUNNING = False

SETTINGS = {
    "max_positions": 2,
    "leverage": 5,
    "tp": 0.02,
    "sl": 0.01
}

OPEN_POSITIONS = []
BASE_URL = "https://contract.mexc.com"


@app.get("/")
def home():
    return {
        "status": "ok",
        "message": "MEXC Futures Bot Backend aktif"
    }


def get_top_volume_symbols():
    url = f"{BASE_URL}/api/v1/contract/ticker"
    r = requests.get(url, timeout=10)
    data = r.json()

    items = data.get("data", [])

    sorted_list = sorted(
        items,
        key=lambda x: float(x.get("amount", 0)),
        reverse=True
    )

    return [
        x["symbol"]
        for x in sorted_list
        if "USDT" in x.get("symbol", "")
    ][:10]


def get_signal(symbol):
    try:
        url = f"{BASE_URL}/api/v1/contract/kline/{symbol}"
        params = {
            "interval": "Min5",
            "limit": 50
        }

        r = requests.get(url, params=params, timeout=10)
        data = r.json().get("data", {})

        closes = list(map(float, data.get("close", [])[-20:]))

        if len(closes) < 20:
            return None

        avg = sum(closes) / len(closes)

        if closes[-1] > avg:
            return "LONG"
        elif closes[-1] < avg:
            return "SHORT"
        else:
            return "BEKLE"

    except Exception:
        return None


def bot_loop():
    global BOT_RUNNING

    while BOT_RUNNING:
        try:
            symbols = get_top_volume_symbols()

            for symbol in symbols:
                if len(OPEN_POSITIONS) >= SETTINGS["max_positions"]:
                    break

                already_open = any(
                    p["symbol"] == symbol for p in OPEN_POSITIONS
                )

                if already_open:
                    continue

                signal = get_signal(symbol)

                if signal in ["LONG", "SHORT"]:
                    OPEN_POSITIONS.append({
                        "symbol": symbol,
                        "side": signal,
                        "leverage": SETTINGS["leverage"],
                        "entry_time": time.time()
                    })

                time.sleep(1)

            time.sleep(10)

        except Exception:
            time.sleep(5)


@app.get("/start")
def start():
    global BOT_RUNNING

    if BOT_RUNNING:
        return {"status": "already_running"}

    BOT_RUNNING = True

    thread = threading.Thread(
        target=bot_loop,
        daemon=True
    )
    thread.start()

    return {"status": "started"}


@app.get("/stop")
def stop():
    global BOT_RUNNING
    BOT_RUNNING = False
    return {"status": "stopped"}


@app.get("/positions")
def positions():
    return {
        "count": len(OPEN_POSITIONS),
        "positions": OPEN_POSITIONS
    }


@app.get("/settings")
def settings():
    return SETTINGS


@app.get("/scan")
def scan():
    symbols = get_top_volume_symbols()
    return {
        "status": "ok",
        "symbols": symbols
    }


@app.get("/signal")
def signal(symbol: str = "BTC_USDT"):
    result = get_signal(symbol)
    return {
        "symbol": symbol,
        "signal": result
    }

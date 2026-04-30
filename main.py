from fastapi import FastAPI
import requests
import time
import os
import hmac
import hashlib
import json

app = FastAPI()

BASE_URL = "https://contract.mexc.com"

MEXC_KEY = os.getenv("MEXC_KEY", "")
MEXC_SECRET = os.getenv("MEXC_SECRET", "")
LIVE_TRADING = os.getenv("LIVE_TRADING", "false").lower() == "true"

MARGIN = float(os.getenv("MARGIN", "1.5"))
LEVERAGE = int(os.getenv("LEVERAGE", "3"))

LOGS = []
ORDER_LOCK = False


def log(msg):
    LOGS.insert(0, time.strftime("%H:%M:%S") + " " + str(msg))
    if len(LOGS) > 50:
        LOGS.pop()


# 🔥 DOĞRU SIGN
def sign(timestamp, body_text):
    return hmac.new(
        MEXC_SECRET.encode(),
        (timestamp + body_text).encode(),
        hashlib.sha256
    ).hexdigest()


def headers(body_text):
    timestamp = str(int(time.time() * 1000))
    return {
        "ApiKey": MEXC_KEY,
        "Request-Time": timestamp,
        "Signature": sign(timestamp, body_text),
        "Content-Type": "application/json"
    }


def get_price(symbol):
    r = requests.get(f"{BASE_URL}/api/v1/contract/ticker").json()
    for x in r.get("data", []):
        if x["symbol"] == symbol:
            return float(x["lastPrice"])
    return None


def calc_qty(symbol):
    price = get_price(symbol)
    if not price:
        return None

    qty = (MARGIN * LEVERAGE) / price

    if symbol == "BTC_USDT":
        return round(qty, 4)
    elif symbol == "ETH_USDT":
        return round(qty, 3)
    else:
        return round(qty, 2)


def create_order(symbol, side):
    qty = calc_qty(symbol)
    if not qty:
        return {"error": "qty hesaplanamadı"}

    mexc_side = 1 if side == "LONG" else 3

    body = {
        "symbol": symbol,
        "price": 0,
        "vol": qty,
        "side": mexc_side,
        "type": 5,
        "openType": 1,
        "leverage": LEVERAGE
    }

    body_text = json.dumps(body, separators=(",", ":"))
    h = headers(body_text)

    url = f"{BASE_URL}/api/v1/private/order/create"
    r = requests.post(url, headers=h, data=body_text)

    try:
        result = r.json()
    except:
        result = {"http_status": r.status_code, "text": r.text}

    log(f"REAL {side} {symbol} qty={qty} -> {result}")
    return result


@app.get("/")
def home():
    return {
        "status": "ok",
        "live": LIVE_TRADING
    }


@app.get("/api_test")
def api_test():
    return {
        "api_key_loaded": bool(MEXC_KEY),
        "secret_loaded": bool(MEXC_SECRET),
        "live": LIVE_TRADING
    }


@app.get("/price")
def price(symbol: str = "BTC_USDT"):
    return {
        "symbol": symbol,
        "price": get_price(symbol),
        "qty": calc_qty(symbol)
    }


@app.get("/real_test_once")
def real_test(symbol: str = "BTC_USDT", side: str = "LONG", confirm: str = "false"):
    global ORDER_LOCK

    if confirm != "true":
        return {"status": "confirm gerekli"}

    if not LIVE_TRADING:
        return {"status": "LIVE kapalı"}

    if ORDER_LOCK:
        return {"status": "zaten denendi"}

    ORDER_LOCK = True
    return create_order(symbol, side)


@app.get("/logs")
def logs():
    return LOGS


@app.get("/stop")
def stop():
    return {"status": "stopped"}

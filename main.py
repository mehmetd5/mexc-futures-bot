from fastapi import FastAPI
import requests, time, os, hmac, hashlib, json

app = FastAPI()

BASE_URL = "https://contract.mexc.com"

MEXC_KEY = os.getenv("MEXC_KEY", "")
MEXC_SECRET = os.getenv("MEXC_SECRET", "")
LIVE_TRADING = os.getenv("LIVE_TRADING", "false").lower() == "true"

MARGIN = float(os.getenv("MARGIN", "1.5"))
LEVERAGE = int(os.getenv("LEVERAGE", "3"))

LOGS = []
LOCK = False


def log(x):
    LOGS.insert(0, time.strftime("%H:%M:%S") + " " + str(x))
    if len(LOGS) > 30:
        LOGS.pop()


# 🔑 SIGN
def sign(param, timestamp):
    text = MEXC_KEY + timestamp + param
    return hmac.new(
        MEXC_SECRET.encode(),
        text.encode(),
        hashlib.sha256
    ).hexdigest()


def headers(param):
    timestamp = str(int(time.time() * 1000))
    return {
        "ApiKey": MEXC_KEY,
        "Request-Time": timestamp,
        "Signature": sign(param, timestamp),
        "Content-Type": "application/json"
    }


# 🌍 PUBLIC
def get_price(symbol):
    r = requests.get(BASE_URL + "/api/v1/contract/ticker").json()
    for x in r["data"]:
        if x["symbol"] == symbol:
            return float(x["lastPrice"])
    return None


# 🔒 PRIVATE GET
def private_get(path):
    param = ""
    r = requests.get(BASE_URL + path, headers=headers(param))
    try:
        return r.json()
    except:
        return {"error": r.text}


# 🔒 PRIVATE POST
def private_post(path, body):
    param = json.dumps(body, separators=(",", ":"))
    r = requests.post(BASE_URL + path, headers=headers(param), data=param)
    try:
        return r.json()
    except:
        return {"error": r.text}


def calc_qty(symbol):
    price = get_price(symbol)
    if not price:
        return None
    qty = (MARGIN * LEVERAGE) / price
    return round(qty, 3)


# ---------------- API ----------------

@app.get("/")
def home():
    return {"status": "ok"}


@app.get("/api_test")
def api_test():
    return {
        "key": bool(MEXC_KEY),
        "secret": bool(MEXC_SECRET),
        "live": LIVE_TRADING
    }


@app.get("/account")
def account():
    return private_get("/api/v1/private/account/assets")


@app.get("/price")
def price(symbol: str = "BTC_USDT"):
    return {
        "price": get_price(symbol),
        "qty": calc_qty(symbol)
    }


@app.get("/real_test_once")
def real_test_once(symbol: str = "BTC_USDT", side: str = "LONG", confirm: str = "false"):
    global LOCK

    if confirm != "true":
        return {"error": "confirm=true gerekli"}

    if not LIVE_TRADING:
        return {"error": "LIVE kapalı"}

    if LOCK:
        return {"error": "zaten çalıştı"}

    qty = calc_qty(symbol)
    if not qty:
        return {"error": "qty yok"}

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

    LOCK = True

    result = private_post("/api/v1/private/order/create", body)

    log(result)

    return result


@app.get("/logs")
def logs():
    return LOGS

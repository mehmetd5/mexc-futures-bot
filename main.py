from fastapi import FastAPI
import requests, time, os, hmac, hashlib, json

app = FastAPI()

BASE_URL = "https://contract.mexc.com"

MEXC_KEY = os.getenv("MEXC_KEY", "")
MEXC_SECRET = os.getenv("MEXC_SECRET", "")
LIVE_TRADING = os.getenv("LIVE_TRADING", "false").lower() == "true"

SYMBOL = "XRP_USDT"
MARGIN = float(os.getenv("MARGIN", "1.5"))
LEVERAGE = int(os.getenv("LEVERAGE", "3"))

LOGS = []
LOCK = False


def log(x):
    LOGS.insert(0, time.strftime("%H:%M:%S") + " " + str(x))
    if len(LOGS) > 30:
        LOGS.pop()


def sign(param_string, timestamp):
    target = MEXC_KEY + timestamp + param_string
    return hmac.new(
        MEXC_SECRET.encode("utf-8"),
        target.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()


def make_headers(param_string):
    timestamp = str(int(time.time() * 1000))
    return {
        "ApiKey": MEXC_KEY,
        "Request-Time": timestamp,
        "Signature": sign(param_string, timestamp),
        "Content-Type": "application/json",
        "Recv-Window": "30000"
    }


def public_get(path):
    r = requests.get(BASE_URL + path, timeout=10)
    try:
        return r.json()
    except Exception:
        return {"http_status": r.status_code, "text": r.text}


def private_get(path):
    param_string = ""
    r = requests.get(
        BASE_URL + path,
        headers=make_headers(param_string),
        timeout=10
    )
    try:
        return r.json()
    except Exception:
        return {"http_status": r.status_code, "text": r.text}


def private_post(path, body):
    body_text = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
    r = requests.post(
        BASE_URL + path,
        headers=make_headers(body_text),
        data=body_text,
        timeout=10
    )
    try:
        return r.json()
    except Exception:
        return {"http_status": r.status_code, "text": r.text}


def get_price():
    data = public_get("/api/v1/contract/ticker")
    for x in data.get("data", []):
        if x.get("symbol") == SYMBOL:
            return float(x.get("lastPrice") or x.get("last") or x.get("fairPrice"))
    return None


def calc_qty():
    price = get_price()
    if not price:
        return None

    qty = (MARGIN * LEVERAGE) / price

    # XRP minimum 1 adet dediğin için
    return max(round(qty, 0), 1)


@app.get("/")
def home():
    return {
        "status": "ok",
        "bot": "V5 XRP SAFE TEST",
        "symbol": SYMBOL,
        "live": LIVE_TRADING,
        "margin": MARGIN,
        "leverage": LEVERAGE
    }


@app.get("/api_test")
def api_test():
    return {
        "api_key_loaded": bool(MEXC_KEY),
        "secret_loaded": bool(MEXC_SECRET),
        "live": LIVE_TRADING
    }


@app.get("/account")
def account():
    return private_get("/api/v1/private/account/assets")


@app.get("/price")
def price():
    return {
        "symbol": SYMBOL,
        "price": get_price(),
        "qty": calc_qty()
    }


@app.get("/real_test_once")
def real_test_once(confirm: str = "false"):
    global LOCK

    if confirm.lower() != "true":
        return {"status": "blocked", "message": "confirm=true gerekli"}

    if not LIVE_TRADING:
        return {"status": "blocked", "message": "LIVE_TRADING false"}

    if LOCK:
        return {"status": "blocked", "message": "Bu deployda test zaten denendi"}

    qty = calc_qty()
    if not qty:
        return {"success": False, "error": "qty hesaplanamadı"}

    body = {
        "symbol": SYMBOL,
        "price": 0,
        "vol": qty,
        "side": 1,       # 1 = open long
        "type": 5,       # market order
        "openType": 1,
        "leverage": LEVERAGE
    }

    LOCK = True
    result = private_post("/api/v1/private/order/create", body)

    log({
        "symbol": SYMBOL,
        "side": "LONG",
        "qty": qty,
        "result": result
    })

    return result


@app.get("/logs")
def logs():
    return LOGS


@app.get("/stop")
def stop():
    return {"status": "stopped", "message": "Otomatik bot yok"}

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
ORDER_LOCK = False


def add_log(msg):
    LOGS.insert(0, time.strftime("%H:%M:%S") + " " + msg)
    if len(LOGS) > 50:
        LOGS.pop()


def sign_post(body_text, timestamp):
    target = MEXC_KEY + timestamp + body_text
    return hmac.new(
        MEXC_SECRET.encode("utf-8"),
        target.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()


def headers(body_text):
    timestamp = str(int(time.time() * 1000))
    return {
        "ApiKey": MEXC_KEY,
        "Request-Time": timestamp,
        "Signature": sign_post(body_text, timestamp),
        "Content-Type": "application/json",
        "Recv-Window": "5000",
        "Language": "English"
    }


def get_price(symbol):
    r = requests.get(f"{BASE_URL}/api/v1/contract/ticker", timeout=10)
    data = r.json().get("data", [])
    for x in data:
        if x.get("symbol") == symbol:
            return float(x.get("lastPrice") or x.get("last") or x.get("fairPrice"))
    return None


def qty_from_margin(symbol):
    price = get_price(symbol)
    if not price:
        return None

    raw_qty = (MARGIN * LEVERAGE) / price

    if symbol in ["BTC_USDT"]:
        return round(raw_qty, 4)
    if symbol in ["ETH_USDT"]:
        return round(raw_qty, 3)

    return round(raw_qty, 2)


def create_market_order(symbol, side):
    qty = qty_from_margin(symbol)
    if not qty or qty <= 0:
        return {"success": False, "error": "qty hesaplanamadı"}

    # MEXC Futures side:
    # 1 = open long, 3 = open short
    mexc_side = 1 if side.upper() == "LONG" else 3

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
    r = requests.post(url, headers=h, data=body_text, timeout=10)

    try:
        result = r.json()
    except Exception:
        result = {"http_status": r.status_code, "text": r.text}

    add_log(f"REAL {side.upper()} {symbol} qty={qty} -> {result}")
    return result


@app.get("/")
def home():
    return {
        "status": "ok",
        "bot": "V4.2 SAFE REAL TEST",
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


@app.get("/price")
def price(symbol: str = "BTC_USDT"):
    return {"symbol": symbol, "price": get_price(symbol)}


@app.get("/real_test_once")
def real_test_once(symbol: str = "BTC_USDT", side: str = "LONG", confirm: str = "false"):
    global ORDER_LOCK

    if confirm.lower() != "true":
        return {
            "status": "blocked",
            "message": "Gerçek emir için confirm=true yazmalısın"
        }

    if not LIVE_TRADING:
        return {"status": "blocked", "message": "LIVE_TRADING false"}

    if ORDER_LOCK:
        return {"status": "blocked", "message": "Bu deployda test emri zaten denendi"}

    ORDER_LOCK = True
    result = create_market_order(symbol, side)
    return result


@app.get("/logs")
def logs():
    return LOGS


@app.get("/stop")
def stop():
    return {"status": "stopped", "message": "Bu güvenli sürümde otomatik bot yok; sadece real_test_once var."}

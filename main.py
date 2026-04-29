from fastapi import FastAPI
import requests, time, threading

app = FastAPI()

BASE_URL = "https://contract.mexc.com"

BOT_RUNNING = False
BALANCE = 1000.0
REALIZED_PNL = 0.0
POSITIONS = []
CLOSED = []
LOGS = []

SETTINGS = {
    "max_positions": 3,
    "margin": 5.0,
    "leverage": 10,
    "tp_percent": 3.0,
    "sl_percent": 1.5,
    "top_scan": 20
}


def log(msg):
    LOGS.insert(0, time.strftime("%H:%M:%S") + " " + msg)
    if len(LOGS) > 100:
        LOGS.pop()


@app.get("/")
def home():
    return {
        "status": "ok",
        "message": "MEXC Futures Paper Bot aktif"
    }


def get_tickers():
    url = f"{BASE_URL}/api/v1/contract/ticker"
    r = requests.get(url, timeout=10)
    return r.json().get("data", [])


def get_price(symbol):
    data = get_tickers()
    for x in data:
        if x.get("symbol") == symbol:
            for key in ["lastPrice", "last", "fairPrice", "indexPrice"]:
                if key in x:
                    return float(x[key])
    return None


def get_top_symbols():
    data = get_tickers()

    def vol(x):
        for key in ["amount24", "amount", "volume24", "volume"]:
            try:
                return float(x.get(key, 0))
            except:
                return 0
        return 0

    usdt = [x for x in data if "USDT" in x.get("symbol", "")]
    usdt = sorted(usdt, key=vol, reverse=True)
    return [x["symbol"] for x in usdt[:SETTINGS["top_scan"]]]


def get_klines(symbol):
    url = f"{BASE_URL}/api/v1/contract/kline/{symbol}"
    params = {
        "interval": "Min5",
        "limit": 60
    }

    r = requests.get(url, params=params, timeout=10)
    data = r.json().get("data", {})

    closes = list(map(float, data.get("close", [])[-50:]))
    vols = list(map(float, data.get("vol", data.get("volume", []))[-50:]))

    return closes, vols


def get_signal(symbol):
    try:
        closes, vols = get_klines(symbol)

        if len(closes) < 30:
            return "BEKLE"

        last = closes[-1]
        ema_fast = sum(closes[-7:]) / 7
        ema_slow = sum(closes[-25:]) / 25

        volume_ok = True
        if len(vols) >= 20:
            avg_vol = sum(vols[-20:]) / 20
            volume_ok = vols[-1] >= avg_vol * 1.05

        if last > ema_fast > ema_slow and volume_ok:
            return "LONG"

        if last < ema_fast < ema_slow and volume_ok:
            return "SHORT"

        return "BEKLE"

    except Exception as e:
        log(f"Sinyal hata {symbol}: {e}")
        return "BEKLE"


def open_position(symbol, side):
    global BALANCE

    if len(POSITIONS) >= SETTINGS["max_positions"]:
        return False

    if any(p["symbol"] == symbol for p in POSITIONS):
        return False

    price = get_price(symbol)
    if not price:
        log(f"{symbol} fiyat alınamadı")
        return False

    margin = SETTINGS["margin"]
    leverage = SETTINGS["leverage"]

    if BALANCE < margin:
        log("Bakiye yetersiz")
        return False

    qty = (margin * leverage) / price

    BALANCE -= margin

    POSITIONS.append({
        "symbol": symbol,
        "side": side,
        "entry": price,
        "last": price,
        "qty": qty,
        "margin": margin,
        "leverage": leverage,
        "pnl": 0.0,
        "tp_percent": SETTINGS["tp_percent"],
        "sl_percent": SETTINGS["sl_percent"],
        "opened_at": time.time()
    })

    log(f"DEMO {side} açıldı: {symbol} | Margin ${margin} | {leverage}x")
    return True


def close_position(pos, reason):
    global BALANCE, REALIZED_PNL

    price = get_price(pos["symbol"]) or pos["last"]

    if pos["side"] == "LONG":
        pnl = (price - pos["entry"]) * pos["qty"]
    else:
        pnl = (pos["entry"] - price) * pos["qty"]

    BALANCE += pos["margin"] + pnl
    REALIZED_PNL += pnl

    closed = pos.copy()
    closed["close"] = price
    closed["pnl"] = pnl
    closed["reason"] = reason
    closed["closed_at"] = time.time()

    CLOSED.insert(0, closed)
    POSITIONS.remove(pos)

    log(f"{reason}: {pos['symbol']} kapandı | PnL ${round(pnl, 4)}")


def update_positions():
    for pos in POSITIONS[:]:
        price = get_price(pos["symbol"])
        if not price:
            continue

        pos["last"] = price

        if pos["side"] == "LONG":
            pnl = (price - pos["entry"]) * pos["qty"]
            change_percent = ((price - pos["entry"]) / pos["entry"]) * 100 * pos["leverage"]
        else:
            pnl = (pos["entry"] - price) * pos["qty"]
            change_percent = ((pos["entry"] - price) / pos["entry"]) * 100 * pos["leverage"]

        pos["pnl"] = pnl

        if change_percent >= pos["tp_percent"]:
            close_position(pos, "TP")

        elif change_percent <= -pos["sl_percent"]:
            close_position(pos, "SL")


def bot_loop():
    global BOT_RUNNING

    log("Bot başladı")

    while BOT_RUNNING:
        try:
            update_positions()

            if len(POSITIONS) < SETTINGS["max_positions"]:
                symbols = get_top_symbols()

                for symbol in symbols:
                    if len(POSITIONS) >= SETTINGS["max_positions"]:
                        break

                    if any(p["symbol"] == symbol for p in POSITIONS):
                        continue

                    signal = get_signal(symbol)

                    if signal in ["LONG", "SHORT"]:
                        open_position(symbol, signal)
                        time.sleep(1)

            time.sleep(15)

        except Exception as e:
            log(f"Bot hata: {e}")
            time.sleep(10)

    log("Bot durdu")


@app.get("/start")
def start():
    global BOT_RUNNING

    if BOT_RUNNING:
        return {"status": "already_running"}

    BOT_RUNNING = True
    threading.Thread(target=bot_loop, daemon=True).start()

    return {"status": "started"}


@app.get("/stop")
def stop():
    global BOT_RUNNING
    BOT_RUNNING = False
    return {"status": "stopped"}


@app.get("/positions")
def positions():
    update_positions()
    return {
        "count": len(POSITIONS),
        "positions": POSITIONS
    }


@app.get("/balance")
def balance():
    open_pnl = sum(p.get("pnl", 0) for p in POSITIONS)
    return {
        "balance": round(BALANCE, 4),
        "open_pnl": round(open_pnl, 4),
        "equity": round(BALANCE + open_pnl, 4),
        "open_positions": len(POSITIONS)
    }


@app.get("/scan")
def scan():
    symbols = get_top_symbols()
    results = []

    for s in symbols[:20]:
        results.append({
            "symbol": s,
            "signal": get_signal(s)
        })

    return {
        "status": "ok",
        "results": results
    }


@app.get("/force_open")
def force_open(symbol: str = "BTC_USDT", side: str = "LONG"):
    ok = open_position(symbol, side.upper())
    return {
        "status": "opened" if ok else "failed",
        "symbol": symbol,
        "side": side.upper()
    }


@app.get("/report")
def report():
    update_positions()

    open_pnl = sum(p.get("pnl", 0) for p in POSITIONS)
    total_closed = len(CLOSED)
    wins = len([x for x in CLOSED if x.get("pnl", 0) >= 0])
    losses = len([x for x in CLOSED if x.get("pnl", 0) < 0])
    winrate = (wins / total_closed * 100) if total_closed else 0

    return {
        "balance": round(BALANCE, 4),
        "open_pnl": round(open_pnl, 4),
        "equity": round(BALANCE + open_pnl, 4),
        "realized_pnl": round(REALIZED_PNL, 4),
        "open_positions": len(POSITIONS),
        "closed_positions": total_closed,
        "win": wins,
        "loss": losses,
        "winrate": round(winrate, 2),
        "logs": LOGS[:30],
        "closed": CLOSED[:20]
    }


@app.get("/settings")
def settings():
    return SETTINGS

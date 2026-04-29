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

# --- HACİM FİLTRELİ COIN LİSTESİ ---
def get_top_volume_symbols():
    url = f"{BASE_URL}/api/v1/contract/ticker"
    r = requests.get(url)
    data = r.json()

    sorted_list = sorted(
        data["data"],
        key=lambda x: float(x["amount"]),
        reverse=True
    )

    return [x["symbol"] for x in sorted_list[:10]]

# --- BASİT SİNYAL ---
def get_signal(symbol):
    try:
        url = f"{BASE_URL}/api/v1/contract/kline/{symbol}?interval=Min5"
        r = requests.get(url)
        data = r.json()["data"]

        closes = list(map(float, data["close"][-20:]))

        avg

# حقوق حمو @x_O_M_X تيم FYR
import json
import time
import asyncio
import aiohttp
import requests
import warnings
import threading
import os
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, jsonify, request
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

warnings.filterwarnings("ignore")

SECRET_KEY = b"Yg&tc%DEuh6%Zc^8"
SECRET_IV = b"6oyZDr22E3ychjM%"
TOKEN_API = "https://ff-jwt-gen-api.lovable.app/api/public/token"
TOKEN_TTL = 6 * 3600
ACCOUNTS_FILE = "accs.txt"
PORT = int(os.environ.get("PORT", 8008))


def encrypt_payload(raw_bytes):
    cipher = AES.new(SECRET_KEY, AES.MODE_CBC, SECRET_IV)
    return cipher.encrypt(pad(raw_bytes, AES.block_size))


def encode_varint(value):
    value = int(value)
    buffer = bytearray()
    while True:
        piece = value & 0x7F
        value >>= 7
        if value:
            piece |= 0x80
        buffer.append(piece)
        if not value:
            break
    return buffer.hex()


def load_accounts(path=ACCOUNTS_FILE):
    accounts = []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if ":" not in line:
                    continue
                uid, pw = line.split(":", 1)
                uid, pw = uid.strip(), pw.strip()
                if uid and pw:
                    accounts.append({"uid": uid, "pw": pw})
        print(f"[+] {len(accounts)} accounts loaded")
    except FileNotFoundError:
        print(f"[!] {path} not found")
    return accounts


ACCOUNTS = load_accounts()
TOKEN_CACHE = {}
TOKEN_LOCK = threading.Lock()
READY = threading.Event()


def request_token(uid, password):
    r = requests.get(TOKEN_API, params={"uid": uid, "password": password}, timeout=15, verify=False)
    if r.status_code != 200:
        raise RuntimeError(f"http {r.status_code}")
    data = r.json()
    token = data.get("token") or data.get("access_token")
    if not token:
        raise RuntimeError("no token")
    return token.strip()


def _fetch_one(account):
    try:
        token = request_token(account["uid"], account["pw"])
        with TOKEN_LOCK:
            TOKEN_CACHE[account["uid"]] = {"token": token, "ts": time.time()}
        print(f"[+] {account['uid']} -> ok")
        return True
    except Exception as exc:
        print(f"[!] {account['uid']} -> {exc}")
        return False


def preload_worker():
    print("[*] Starting preload...")
    with ThreadPoolExecutor(max_workers=10) as pool:
        list(pool.map(_fetch_one, ACCOUNTS))
    READY.set()


def start_preload():
    threading.Thread(target=preload_worker, daemon=True).start()


def get_live_tokens():
    with TOKEN_LOCK:
        now = time.time()
        return [item["token"] for item in TOKEN_CACHE.values() if now - item["ts"] < TOKEN_TTL]


async def send_visit(session, token, payload):
    endpoint = "https://clientbp.ppmainecoonghj.com/GetPlayerPersonalShow"
    headers = {
        "ReleaseVersion": "OB55",
        "X-GA": "v1 1",
        "Authorization": f"Bearer {token}",
        "Host": "clientbp.ppmainecoonghj.com",
        "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
        "Connection": "Keep-Alive",
        "X-Unity-Version": "2018.4.11f1",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    try:
        async with session.post(endpoint, headers=headers, data=payload, ssl=False, timeout=10) as r:
            await r.read()
    except Exception:
        pass


async def dispatch_requests(tokens, player_id, total):
    if not tokens:
        return
    connector = aiohttp.TCPConnector(limit=50)
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        raw_packet = "08" + encode_varint(player_id) + "1801"
        encrypted = bytes.fromhex(encrypt_payload(bytes.fromhex(raw_packet)).hex())
        chunk_size = 50
        for start in range(0, total, chunk_size):
            stop = min(start + chunk_size, total)
            jobs = []
            for position in range(start, stop):
                token = tokens[position % len(tokens)]
                jobs.append(asyncio.create_task(send_visit(session, token, encrypted)))
            await asyncio.gather(*jobs)
            await asyncio.sleep(0.05)


app = Flask(__name__)


@app.route("/", methods=["GET"])
def home():
    with TOKEN_LOCK:
        count = len(TOKEN_CACHE)
    return jsonify({
        "status": "online",
        "service": "HAMO Visit API",
        "ready": READY.is_set(),
        "cached_tokens": count,
        "total_accounts": len(ACCOUNTS),
    }), 200


@app.route("/<int:player_id>", methods=["GET"])
def visit_endpoint(player_id):
    amount = int(request.args.get("count", 100))
    tokens = get_live_tokens()
    if not tokens:
        return jsonify({"status": "error", "msg": "tokens not ready"}), 503
    asyncio.run(dispatch_requests(tokens, player_id, amount))
    return jsonify({
        "status": "success",
        "msg": f"Request Sent To ID : {player_id}",
        "ID": player_id,
        "Request Sent": amount,
        "Tokens Used": len(tokens),
    }), 200


@app.route("/refresh", methods=["GET"])
def refresh_endpoint():
    with TOKEN_LOCK:
        TOKEN_CACHE.clear()
    READY.clear()
    start_preload()
    return jsonify({"status": "success", "msg": "preload started"}), 200


@app.route("/status", methods=["GET"])
def status_endpoint():
    with TOKEN_LOCK:
        count = len(TOKEN_CACHE)
    return jsonify({
        "ready": READY.is_set(),
        "cached_tokens": count,
        "total_accounts": len(ACCOUNTS),
    }), 200


start_preload()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)

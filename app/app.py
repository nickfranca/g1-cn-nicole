"""
Sistema de mensagens distribuído.

Cada instância (app1, app2, app3) expõe uma API REST na porta 5000.
Ao receber uma mensagem em POST /send, a instância:
  1. grava a mensagem no seu próprio arquivo de log no volume compartilhado;
  2. replica a mensagem para as outras instâncias (POST /replicate);
  3. confere, no volume compartilhado, se a mensagem aparece no log de cada par.
"""

import fcntl
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests
from flask import Flask, jsonify, render_template, request

INSTANCE_NAME = os.getenv("INSTANCE_NAME", "app")
PEERS = [p.strip() for p in os.getenv("PEERS", "").split(",") if p.strip()]
PEER_PORT = int(os.getenv("PEER_PORT", "5000"))
DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "3"))
REPLICATION_RETRIES = int(os.getenv("REPLICATION_RETRIES", "3"))

DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = DATA_DIR / f"{INSTANCE_NAME}.log"

logging.basicConfig(
    level=logging.INFO,
    format=f"%(asctime)s [{INSTANCE_NAME}] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

app = Flask(__name__)

def log_path(instance: str) -> Path:
    return DATA_DIR / f"{instance}.log"


def read_messages(instance: str = INSTANCE_NAME) -> list[dict]:
    path = log_path(instance)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        try:
            return [json.loads(line) for line in f if line.strip()]
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def store_message(msg: dict) -> bool:
    """Grava a mensagem no log desta instância. Retorna False se já existia."""
    with LOG_FILE.open("a+", encoding="utf-8") as f:
        # Lock exclusivo: evita escrita concorrente entre workers/threads.
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.seek(0)
            if any(json.loads(line)["id"] == msg["id"] for line in f if line.strip()):
                return False  # idempotência: não duplica mensagens
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
            return True
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)



def replicate_to_peer(peer: str, msg: dict) -> dict:
    url = f"http://{peer}:{PEER_PORT}/replicate"
    last_error = None
    for attempt in range(1, REPLICATION_RETRIES + 1):
        try:
            resp = requests.post(url, json=msg, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return {"peer": peer, "status": "ok", "attempts": attempt}
        except requests.RequestException as exc:
            last_error = str(exc)
            log.warning("Falha ao replicar para %s (tentativa %d): %s", peer, attempt, exc)
    return {"peer": peer, "status": "error", "attempts": REPLICATION_RETRIES, "error": last_error}


def verify_replication(msg_id: str) -> dict:
    """Confere, direto no volume compartilhado, em quais logs a mensagem está."""
    instances = [INSTANCE_NAME, *PEERS]
    found = {
        inst: any(m["id"] == msg_id for m in read_messages(inst)) for inst in instances
    }
    return {"id": msg_id, "replicated": all(found.values()), "instances": found}


@app.post("/send")
def send():
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not str(body.get("message", "")).strip():
        return jsonify(error='JSON inválido. Formato esperado: {"message": "texto"}'), 400

    msg = {
        "id": str(uuid.uuid4()),
        "message": str(body["message"]),
        "origin": INSTANCE_NAME,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    store_message(msg)
    log.info("Mensagem %s recebida e armazenada", msg["id"])

    replication = [replicate_to_peer(peer, msg) for peer in PEERS]
    verification = verify_replication(msg["id"])

    status = 201 if verification["replicated"] else 207
    return jsonify(data=msg, replication=replication, verification=verification), status


@app.post("/replicate")
def replicate():
    """Endpoint interno: recebe a cópia de outra instância e NÃO reencaminha (evita loop)."""
    msg = request.get_json(silent=True)
    if not isinstance(msg, dict) or not {"id", "message", "origin", "timestamp"} <= msg.keys():
        return jsonify(error="mensagem de replicação inválida"), 400

    stored = store_message(msg)
    log.info("Réplica %s vinda de %s %s", msg["id"], msg["origin"],
             "armazenada" if stored else "já existia")
    return jsonify(status="stored" if stored else "duplicate", instance=INSTANCE_NAME), 200


@app.get("/messages")
def messages():
    msgs = read_messages()
    return jsonify(instance=INSTANCE_NAME, count=len(msgs), messages=msgs)


@app.get("/verify/<msg_id>")
def verify(msg_id: str):
    result = verify_replication(msg_id)
    return jsonify(result), 200 if result["replicated"] else 404


@app.get("/")
def index():
    """Página HTML simples para enviar e ver as mensagens pelo navegador."""
    return render_template("index.html", instance=INSTANCE_NAME)


@app.get("/api")
def api_index():
    return jsonify(
        instance=INSTANCE_NAME,
        endpoints={
            "POST /send": 'envia uma mensagem. Corpo: {"message": "texto"}',
            "GET /messages": "lista as mensagens armazenadas nesta instância",
            "GET /verify/<id>": "verifica se a mensagem foi replicada em todas as instâncias",
            "GET /health": "status da instância",
        },
    )


@app.get("/health")
def health():
    return jsonify(status="ok", instance=INSTANCE_NAME, peers=PEERS)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

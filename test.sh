#!/usr/bin/env bash
# Script de teste do sistema de mensagens distribuído.
# Uso: ./test.sh            (sobe os containers, testa e mantém rodando)
#      ./test.sh --down     (ao final, derruba os containers)

set -euo pipefail

PORTS=(5001 5002 5003)
PASS=0
FAIL=0

green() { printf '\033[32m%s\033[0m\n' "$*"; }
red()   { printf '\033[31m%s\033[0m\n' "$*"; }
info()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }

check() {
  local desc=$1; shift
  if "$@"; then green "  [OK]   $desc"; PASS=$((PASS + 1))
  else          red   "  [FALHA] $desc"; FAIL=$((FAIL + 1)); fi
}

# Compatível com "docker compose" (v2) e "docker-compose" (v1)
if docker compose version >/dev/null 2>&1; then COMPOSE="docker compose"; else COMPOSE="docker-compose"; fi

wait_healthy() {
  for port in "${PORTS[@]}"; do
    for _ in $(seq 1 30); do
      curl -fs "http://localhost:$port/health" >/dev/null 2>&1 && break
      sleep 1
    done
    curl -fs "http://localhost:$port/health" >/dev/null || { red "Instância na porta $port não respondeu"; exit 1; }
  done
}

info "Subindo os 3 containers"
$COMPOSE up -d --build
wait_healthy
green "  app1, app2 e app3 estão no ar"

# ---------------------------------------------------------------------------
info "Teste 1: enviar mensagem para app1 (porta 5001)"
MSG="hello-$(date +%s)"
RESP=$(curl -s -X POST -H "Content-Type: application/json" \
  -d "{\"message\":\"$MSG\"}" http://localhost:5001/send)
echo "  Resposta: $RESP"
MSG_ID=$(echo "$RESP" | python3 -c 'import sys, json; print(json.load(sys.stdin)["data"]["id"])')
check "app1 respondeu com o id da mensagem ($MSG_ID)" test -n "$MSG_ID"

# ---------------------------------------------------------------------------
info "Teste 2: a mensagem deve aparecer em GET /messages de todas as instâncias"
for port in "${PORTS[@]}"; do
  check "localhost:$port/messages contém '$MSG'" \
    bash -c "curl -s http://localhost:$port/messages | grep -q '$MSG_ID'"
done

# ---------------------------------------------------------------------------
info "Teste 3: verificação de replicação (GET /verify/<id>)"
for port in "${PORTS[@]}"; do
  check "localhost:$port confirma replicação em app1, app2 e app3" \
    bash -c "curl -fs http://localhost:$port/verify/$MSG_ID | grep -q '\"replicated\":true'"
done

# ---------------------------------------------------------------------------
info "Teste 4: cada container possui seu próprio arquivo de log no volume compartilhado"
docker exec app1 ls -l /data
for inst in app1 app2 app3; do
  check "/data/$inst.log existe e contém a mensagem" \
    docker exec app1 grep -q "$MSG_ID" "/data/$inst.log"
done

# ---------------------------------------------------------------------------
info "Teste 5: envio a partir de outra instância (app3 -> app1, app2)"
RESP=$(curl -s -X POST -H "Content-Type: application/json" \
  -d '{"message":"mensagem enviada pelo app3"}' http://localhost:5003/send)
ID2=$(echo "$RESP" | python3 -c 'import sys, json; print(json.load(sys.stdin)["data"]["id"])')
check "app1 recebeu a mensagem do app3" bash -c "curl -s http://localhost:5001/messages | grep -q '$ID2'"
check "app2 recebeu a mensagem do app3" bash -c "curl -s http://localhost:5002/messages | grep -q '$ID2'"

# ---------------------------------------------------------------------------
info "Teste 6: requisição inválida deve retornar 400"
CODE=$(curl -s -o /dev/null -w '%{http_code}' -X POST -H "Content-Type: application/json" \
  -d '{"texto":"sem campo message"}' http://localhost:5001/send)
check "POST /send sem 'message' retorna 400 (recebido: $CODE)" test "$CODE" = "400"

# ---------------------------------------------------------------------------
info "Teste 7: persistência — reiniciar os containers não apaga as mensagens"
$COMPOSE restart >/dev/null
wait_healthy
for port in "${PORTS[@]}"; do
  check "localhost:$port ainda tem a mensagem após restart" \
    bash -c "curl -s http://localhost:$port/messages | grep -q '$MSG_ID'"
done

# ---------------------------------------------------------------------------
info "Resultado: $PASS teste(s) OK, $FAIL falha(s)"

if [[ "${1:-}" == "--down" ]]; then
  $COMPOSE down
fi

[[ $FAIL -eq 0 ]]

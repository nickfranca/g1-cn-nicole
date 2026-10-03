# Guia de estudo: `app.py` e `index.html`

Este guia explica, parte por parte, os dois arquivos de código do projeto:

- [`app/app.py`](app/app.py): o **back-end**. É a API em Python/Flask que roda dentro de cada container.
- [`app/templates/index.html`](app/templates/index.html): o **front-end**. É a página que aparece no navegador.

O código está explicado na ordem em que aparece nos arquivos. Os números de linha batem com a versão atual.

---

## Visão geral: como as peças se encaixam

```
 Navegador (localhost:5001)
        │  1. GET /            → recebe o index.html
        │  2. GET /messages    → a cada 2s, busca a lista de mensagens
        │  3. POST /send       → quando você clica em "Enviar"
        ▼
 ┌──────────────┐  4. POST /replicate   ┌──────────────┐
 │    app1      │ ────────────────────► │    app2      │
 │  (app.py)    │ ────────────────┐     └──────┬───────┘
 └──────┬───────┘                 │            │
        │                         ▼            │
        │                  ┌──────────────┐    │
        │                  │    app3      │    │
        │                  └──────┬───────┘    │
        ▼                         ▼            ▼
   /data/app1.log          /data/app3.log  /data/app2.log
   └────────────── volume compartilhado "messages-data" ─────────────┘
```

Cada container roda **o mesmo** `app.py`. O que muda entre eles são as variáveis de ambiente (`INSTANCE_NAME` e `PEERS`), definidas no `docker-compose.yml`.

---

# Parte 1: `app.py`

## 1.1 Docstring (linhas 1-9)

```python
"""
Sistema de mensagens distribuído.
...
"""
```

Um texto entre três aspas (`"""`) no topo do arquivo é uma **docstring**: um comentário que documenta o módulo. O Python não executa nada aqui.

Para comentários de uma linha, o Python usa `#`.

---

## 1.2 Imports (linhas 11-20)

`import` traz código de outros módulos, como o `import`/`require` do JavaScript.

```python
import fcntl
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests
from flask import Flask, jsonify, render_template, request
```

- `import x` importa o módulo inteiro. Você usa com o prefixo: `json.loads(...)`.
- `from x import y` importa só um item. Você usa direto: `Path(...)`.

| Módulo | Vem de onde | Para que é usado aqui |
|---|---|---|
| `fcntl` | Python padrão | Trava o arquivo (lock) enquanto ele é lido ou escrito |
| `json` | Python padrão | Converte entre texto JSON e dicionário Python |
| `logging` | Python padrão | Escreve mensagens de log no terminal (aparecem no `docker logs`) |
| `os` | Python padrão | Lê variáveis de ambiente e força a gravação no disco |
| `uuid` | Python padrão | Gera IDs únicos para as mensagens |
| `datetime` | Python padrão | Gera a data e hora da mensagem |
| `pathlib.Path` | Python padrão | Monta caminhos de arquivo (`/data/app1.log`) |
| `requests` | `requirements.txt` | Faz requisições HTTP para os outros containers |
| `flask` | `requirements.txt` | Cria a API e serve a página HTML |

Do Flask, o arquivo usa quatro coisas:
- `Flask` cria a aplicação.
- `jsonify` transforma dados Python numa resposta HTTP em JSON.
- `render_template` lê um arquivo da pasta `templates/` e devolve como HTML.
- `request` dá acesso à requisição que chegou (corpo, cabeçalhos etc.).

---

## 1.3 Configuração (linhas 22-27)

```python
INSTANCE_NAME = os.getenv("INSTANCE_NAME", "app")
PEERS = [p.strip() for p in os.getenv("PEERS", "").split(",") if p.strip()]
PEER_PORT = int(os.getenv("PEER_PORT", "5000"))
DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "3"))
REPLICATION_RETRIES = int(os.getenv("REPLICATION_RETRIES", "3"))
```

**Nomes em MAIÚSCULAS:** em Python, essa é a convenção para **constantes**, valores que não mudam durante a execução. A linguagem não obriga nada, é só um combinado entre programadores.

**`os.getenv("NOME", "padrão")`** lê uma variável de ambiente. Se ela não existir, usa o segundo valor.

| Variável | Valor no app1 | Por quê |
|---|---|---|
| `INSTANCE_NAME` | `"app1"` | Definido no `environment:` do compose |
| `PEERS` | `["app2", "app3"]` | Veio de `"app2,app3"` no compose |
| `PEER_PORT` | `5000` | Valor padrão (porta interna dos containers) |
| `DATA_DIR` | `Path("/data")` | Definido no `ENV` do Dockerfile |
| `REQUEST_TIMEOUT` | `3.0` | Padrão: espera no máximo 3 segundos por resposta |
| `REPLICATION_RETRIES` | `3` | Padrão: tenta replicar até 3 vezes |

**Conversão de tipos:** variáveis de ambiente são **sempre texto**. Por isso o código usa:
- `int("5000")`, que dá `5000` (número inteiro)
- `float("3")`, que dá `3.0` (número decimal)
- `Path("/data")`, que dá um objeto de caminho

### A linha do `PEERS` (list comprehension)

```python
PEERS = [p.strip() for p in os.getenv("PEERS", "").split(",") if p.strip()]
```

Isto é uma **list comprehension**, um `for` que monta uma lista numa linha só. Lendo de dentro para fora, no app1:

1. `os.getenv("PEERS", "")` dá `"app2,app3"`
2. `.split(",")` divide o texto em cada vírgula: `["app2", "app3"]`
3. `for p in ...` passa por cada item
4. `if p.strip()` mantém só os itens que não ficam vazios
5. `p.strip()` (no começo) é o que entra na lista final, sem espaços nas pontas

O mesmo código "do jeito longo":

```python
PEERS = []
for p in os.getenv("PEERS", "").split(","):
    if p.strip():
        PEERS.append(p.strip())
```

O `if` serve para o caso de `PEERS` estar vazio: `"".split(",")` dá `[""]`, e sem o filtro teríamos uma lista com um texto vazio.

**Formato geral:** `[O_QUE_COLOCAR for ITEM in LISTA if CONDIÇÃO]`

---

## 1.4 Preparação (linhas 29-38)

```python
DATA_DIR.mkdir(parents=True, exist_ok=True)
```
Cria a pasta `/data` se ela não existir.
- `parents=True` cria também as pastas "pai" se faltarem.
- `exist_ok=True` não dá erro se a pasta já existir.

Repare na forma `nome=valor`: são **argumentos nomeados**. Eles deixam claro o que cada valor significa.

```python
LOG_FILE = DATA_DIR / f"{INSTANCE_NAME}.log"
```
- `f"..."` é uma **f-string**: o que está entre `{}` é trocado pelo valor da variável. `f"{INSTANCE_NAME}.log"` vira `"app1.log"`. (No JavaScript seria `` `${INSTANCE_NAME}.log` ``.)
- A `/` entre um `Path` e um texto **junta caminhos**. `Path("/data") / "app1.log"` vira `/data/app1.log`. Não é divisão: o `Path` redefine o que a `/` faz.

```python
logging.basicConfig(
    level=logging.INFO,
    format=f"%(asctime)s [{INSTANCE_NAME}] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)
```
Configura o formato dos logs. Uma linha de log fica assim:
```
2026-10-03 12:20:12,548 [app1] INFO Mensagem 5c99... recebida e armazenada
```
- `level=logging.INFO` mostra mensagens de nível INFO para cima (INFO, WARNING, ERROR).
- `%(asctime)s` e as outras são marcadores que o `logging` preenche: data, nível e texto.
- `log` é o objeto usado no resto do código: `log.info(...)`, `log.warning(...)`.

```python
app = Flask(__name__)
```
Cria a aplicação web. `__name__` é uma variável especial do Python com o nome do módulo atual. O Flask usa isso para achar a pasta `templates/` ao lado do arquivo.

---

## 1.5 Como as mensagens ficam salvas

Antes das funções, vale ver o formato do arquivo. Cada container tem o próprio arquivo (`/data/app1.log`, `/data/app2.log`, `/data/app3.log`), com **uma mensagem por linha**, cada linha em JSON (formato *JSON Lines*):

```
{"id": "5c997c17-...", "message": "hello", "origin": "app1", "timestamp": "2026-10-03T12:20:12+00:00"}
{"id": "a1b2c3d4-...", "message": "oi", "origin": "app3", "timestamp": "2026-10-03T12:25:40+00:00"}
```

| Campo | Significado |
|---|---|
| `id` | Identificador único, gerado com UUID |
| `message` | O texto enviado |
| `origin` | Container que recebeu a mensagem primeiro |
| `timestamp` | Data e hora (UTC) em que ela foi recebida |

Em Python, cada linha dessas vira um **dicionário** (`dict`), que é o equivalente ao objeto do JavaScript:

```python
msg = {"id": "5c99...", "message": "hello", "origin": "app1"}
msg["message"]   # → "hello"
```

---

## 1.6 Funções de arquivo (linhas 40-70)

### Como se define uma função

```python
def log_path(instance: str) -> Path:
    return DATA_DIR / f"{instance}.log"
```
- `def` define uma função.
- `instance: str` diz que o parâmetro deve ser um texto. É uma **type hint** (dica de tipo): o Python não obriga, ela só documenta e ajuda o editor.
- `-> Path` diz que a função retorna um `Path`.
- **A indentação (os espaços no começo da linha) define o bloco.** O Python não usa `{ }`. Tudo que está mais para dentro depois do `:` faz parte da função.

`log_path("app2")` devolve `/data/app2.log`.

### `read_messages` lê todas as mensagens de um log (linhas 44-53)

```python
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
```

Linha a linha:

- `instance: str = INSTANCE_NAME` é um **valor padrão**. `read_messages()` sem argumento lê o log do próprio container. `read_messages("app2")` lê o do app2.
- `-> list[dict]` indica que a função retorna uma lista de dicionários.
- `if not path.exists(): return []`: se o arquivo ainda não existe (nenhuma mensagem foi enviada), retorna uma lista vazia.
- **`with ... as f:`** abre o arquivo e guarda na variável `f`. O `with` garante que o arquivo **feche sozinho** no fim do bloco, mesmo se acontecer um erro.
  - `"r"` é o modo leitura (*read*).
  - `encoding="utf-8"` faz acentos funcionarem.
- `fcntl.flock(f, fcntl.LOCK_SH)` trava o arquivo em modo **compartilhado** (*shared*): vários podem ler ao mesmo tempo, mas ninguém escreve enquanto alguém lê.
- **`try: ... finally: ...`**: o bloco `finally` **sempre** roda, com ou sem erro no `try`. Aqui ele garante que o arquivo seja destravado (`LOCK_UN`, *unlock*).
- `[json.loads(line) for line in f if line.strip()]` é outra list comprehension:
  - `for line in f` percorre o arquivo linha por linha
  - `if line.strip()` pula linhas em branco
  - `json.loads(line)` converte o texto JSON em dicionário (*loads* = "load string")

### `store_message` grava uma mensagem (linhas 56-70)

```python
def store_message(msg: dict) -> bool:
    """Grava a mensagem no log desta instância. Retorna False se já existia."""
    with LOG_FILE.open("a+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.seek(0)
            if any(json.loads(line)["id"] == msg["id"] for line in f if line.strip()):
                return False
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
            return True
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
```

- `-> bool` indica que a função retorna `True` ou `False`. Em Python, os dois começam com letra maiúscula.
- `"a+"` abre para **escrita no final** (*append*) e também para leitura. Se o arquivo não existir, ele é criado.
- `LOCK_EX` é a trava **exclusiva**: enquanto ela está ativa, ninguém mais lê nem escreve. Sem ela, duas requisições ao mesmo tempo poderiam misturar as linhas. O Gunicorn roda 2 processos com 4 threads cada, então isso pode acontecer de verdade.
- `f.seek(0)` volta o "cursor" do arquivo para o começo. No modo `"a+"` ele começa no final, e precisamos ler desde o início.
- **`any(...)`** retorna `True` se **pelo menos um** item for verdadeiro. Aqui a pergunta é: alguma linha já tem esse `id`?
  - Se sim, `return False` e a função não grava de novo. Isso se chama **idempotência**: receber a mesma mensagem duas vezes tem o mesmo efeito que receber uma.
- `json.dumps(msg)` faz o caminho inverso do `loads`: converte o dicionário em texto JSON (*dumps* = "dump string").
  - `ensure_ascii=False` grava "não" em vez de `"não"`.
  - `+ "\n"` adiciona a quebra de linha.
- `f.flush()` esvazia o buffer do Python. `os.fsync(...)` pede ao sistema operacional para gravar no disco **agora**. Isso garante que outro container que leia o arquivo logo em seguida já veja a mensagem.

---

## 1.7 Comunicação entre containers (linhas 74-94)

### `replicate_to_peer` manda a mensagem para outro container

```python
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
```

- `url` vira, por exemplo, `http://app2:5000/replicate`. O nome `app2` funciona como endereço porque o Docker tem um **DNS interno** na rede bridge: o nome do serviço do compose aponta para o IP do container.
- `None` é o "nada" do Python, como o `null` de outras linguagens.
- **`range(1, 4)`** gera 1, 2 e 3. O último número **não** entra.
- `requests.post(url, json=msg, timeout=3)`:
  - faz um POST HTTP
  - `json=msg` converte o dicionário em JSON e já põe o cabeçalho `Content-Type: application/json`
  - `timeout=3` desiste se não houver resposta em 3 segundos
- `resp.raise_for_status()`: se o status HTTP for de erro (4xx ou 5xx), **lança uma exceção**. Sem isso, um erro 500 contaria como sucesso.
- **`try: ... except ... as exc:`** é o `try/catch` do Python. Se algo der errado no `try`, o código pula para o `except`, e `exc` guarda o erro.
  - `requests.RequestException` pega qualquer erro de rede: container desligado, timeout, status de erro.
- Fluxo do `for`:
  - deu certo, `return` sai da função na hora
  - deu erro, registra o aviso e o `for` vai para a próxima tentativa
  - acabaram as tentativas, sai do `for` e chega no último `return`, com status `"error"`
- `log.warning("... %s ... %d", peer, attempt)` usa marcadores: `%s` é trocado por texto e `%d` por número.

### `verify_replication` confere se a mensagem chegou em todos

```python
def verify_replication(msg_id: str) -> dict:
    """Confere, direto no volume compartilhado, em quais logs a mensagem está."""
    instances = [INSTANCE_NAME, *PEERS]
    found = {
        inst: any(m["id"] == msg_id for m in read_messages(inst)) for inst in instances
    }
    return {"id": msg_id, "replicated": all(found.values()), "instances": found}
```

- `[INSTANCE_NAME, *PEERS]`: o `*` **espalha** a lista dentro da outra, como o `...` do JavaScript. No app1 o resultado é `["app1", "app2", "app3"]`.
- `found = {chave: valor for item in lista}` é uma **dict comprehension**, igual à list comprehension, só que monta um dicionário.
  - Para cada container (`inst`), ela lê o log **dele** direto no volume compartilhado e pergunta se **alguma** mensagem tem esse id.
  - Resultado: `{"app1": True, "app2": True, "app3": True}`.
- **`all(...)`** retorna `True` só se **todos** forem verdadeiros. É o contrário do `any`, que precisa de só um.
- `found.values()` pega só os valores do dicionário: `[True, True, True]`.

A verificação funciona porque todos os containers montam o **mesmo volume** em `/data`. O app1 consegue abrir o `/data/app2.log` como se fosse um arquivo dele.

---

## 1.8 Endpoints (linhas 97-165)

### O que é o `@` (decorator)

```python
@app.post("/send")
def send():
    ...
```

O `@` é um **decorator**. Ele "embrulha" a função de baixo. Aqui ele registra a função no Flask: **"quando chegar um POST em `/send`, execute `send()`"**.

- `@app.get(...)` serve para requisições GET.
- `@app.post(...)` serve para requisições POST.

O que a função **retorna** vira a resposta HTTP:
- `return jsonify(...)` responde com JSON e status 200 (o padrão).
- `return jsonify(...), 400` responde com JSON e status 400. Em Python, dá para retornar dois valores separados por vírgula (isso é uma **tupla**).

### `POST /send`, o fluxo principal (linhas 97-116)

```python
@app.post("/send")
def send():
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not str(body.get("message", "")).strip():
        return jsonify(error='JSON inválido. Formato esperado: {"message": "texto"}'), 400
```

**Passo 1, ler e validar:**
- `request.get_json(silent=True)` lê o corpo da requisição como JSON. Com `silent=True`, se o JSON for inválido ele devolve `None` em vez de quebrar.
- `isinstance(body, dict)` verifica se o corpo é um dicionário (um objeto JSON `{...}`). Se alguém mandar `[1,2]` ou `"oi"`, é rejeitado.
- `body.get("message", "")` pega o campo `message`. Se ele não existir, devolve `""` em vez de dar erro (diferente de `body["message"]`, que daria erro).
- `str(...).strip()` converte para texto e tira os espaços. Se sobrar vazio, a mensagem é inválida.
- `not`, `or` e `and`: o Python usa palavras no lugar de `!`, `||` e `&&`.
- Se falhar, responde **400 Bad Request**.

```python
    msg = {
        "id": str(uuid.uuid4()),
        "message": str(body["message"]),
        "origin": INSTANCE_NAME,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
```

**Passo 2, montar a mensagem completa:**
- `uuid.uuid4()` gera um ID aleatório, praticamente impossível de repetir, como `5c997c17-d617-43c8-ae51-9244561b38d6`.
- `datetime.now(timezone.utc).isoformat()` dá a data e hora atual em UTC no formato padrão ISO: `2026-10-03T12:20:12.548595+00:00`.

```python
    store_message(msg)
    log.info("Mensagem %s recebida e armazenada", msg["id"])
```

**Passo 3, gravar no log deste container.**

```python
    replication = [replicate_to_peer(peer, msg) for peer in PEERS]
```

**Passo 4, enviar a mensagem para os outros containers.** É uma list comprehension que chama `replicate_to_peer` para cada par e junta os resultados numa lista:

```python
[{"peer": "app2", "status": "ok", "attempts": 1},
 {"peer": "app3", "status": "ok", "attempts": 1}]
```

```python
    verification = verify_replication(msg["id"])
```

**Passo 5, conferir nos 3 logs se a mensagem foi gravada.**

```python
    status = 201 if verification["replicated"] else 207
    return jsonify(data=msg, replication=replication, verification=verification), status
```

**Passo 6, responder:**
- `X if CONDIÇÃO else Y` é o **if ternário** do Python. Em JavaScript seria `CONDIÇÃO ? X : Y`.
- **201 Created** quer dizer que a mensagem foi criada e replicada em todos os containers.
- **207 Multi-Status** quer dizer que a mensagem foi gravada aqui, mas algum container não confirmou.
- `jsonify(data=..., replication=...)`: os argumentos nomeados viram as chaves do JSON de resposta.

### `POST /replicate` recebe a cópia (linhas 119-129)

```python
@app.post("/replicate")
def replicate():
    msg = request.get_json(silent=True)
    if not isinstance(msg, dict) or not {"id", "message", "origin", "timestamp"} <= msg.keys():
        return jsonify(error="mensagem de replicação inválida"), 400

    stored = store_message(msg)
    log.info(...)
    return jsonify(status="stored" if stored else "duplicate", instance=INSTANCE_NAME), 200
```

Este endpoint é **interno**: quem chama é outro container, não o usuário.

- `{"id", "message", "origin", "timestamp"}`: chaves `{}` com valores soltos (sem `:`) formam um **set** (conjunto), não um dicionário.
- `<=` entre conjuntos significa "está contido em". A pergunta é se a mensagem tem **todos** esses campos.
- Ele **só grava e não reenvia** para ninguém. Se reenviasse, o app2 mandaria de volta para o app1, que mandaria para o app2... e os containers ficariam num **loop infinito**.
- A mensagem chega já pronta, com o mesmo `id` e o mesmo `timestamp` da original. Por isso é a mesma mensagem nos 3 logs.

### `GET /messages` lista as mensagens (linhas 132-135)

```python
@app.get("/messages")
def messages():
    msgs = read_messages()
    return jsonify(instance=INSTANCE_NAME, count=len(msgs), messages=msgs)
```

- `read_messages()` sem argumento lê o log **deste** container.
- `len(msgs)` é o tamanho da lista, como o `.length` do JavaScript.

### `GET /verify/<msg_id>` verifica a replicação (linhas 138-141)

```python
@app.get("/verify/<msg_id>")
def verify(msg_id: str):
    result = verify_replication(msg_id)
    return jsonify(result), 200 if result["replicated"] else 404
```

- `<msg_id>` na rota é um **parâmetro de URL**. Em `/verify/abc123`, o Flask chama `verify(msg_id="abc123")`.
- A resposta é **200** se a mensagem está nos 3 containers e **404** se falta em algum.

### `GET /` serve a página HTML (linhas 144-147)

```python
@app.get("/")
def index():
    return render_template("index.html", instance=INSTANCE_NAME)
```

- `render_template` procura o arquivo em `templates/index.html`. A pasta **tem** que se chamar `templates`, porque é onde o Flask procura.
- `instance=INSTANCE_NAME` passa uma variável para o HTML. Lá dentro, `{{ instance }}` é trocado por `app1` (ou `app2`, `app3`). Isso é feito pelo **Jinja2**, o motor de templates que vem junto com o Flask.

### `GET /api` e `GET /health` (linhas 150-165)

Os dois só devolvem informações fixas:
- `/api` lista os endpoints disponíveis.
- `/health` diz "estou vivo". O `HEALTHCHECK` do Dockerfile chama essa rota a cada 10 segundos para saber se o container está saudável.

---

## 1.9 O final do arquivo (linhas 168-169)

```python
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
```

- Quando você executa `python app.py` diretamente, `__name__` vale `"__main__"` e o bloco roda.
- Quando o arquivo é **importado** por outro programa, o bloco **não** roda.
- No Docker, quem sobe a aplicação é o **Gunicorn** (`CMD [..., "app:app"]` no Dockerfile, que quer dizer "arquivo `app.py`, variável `app`"). Então esse bloco não é usado no Docker. Ele fica no arquivo para testar sem Docker.
- `host="0.0.0.0"` aceita conexões de qualquer endereço. Com `localhost`, só aceitaria conexões de dentro do próprio container.

---

## 1.10 Resumo da sintaxe Python usada

| Python | Equivalente em JavaScript | Exemplo no código |
|---|---|---|
| `def f(x):` | `function f(x) {` | `def send():` |
| indentação | `{ }` | todo bloco |
| `None` | `null` | `last_error = None` |
| `True` / `False` | `true` / `false` | `return True` |
| `and` / `or` / `not` | `&&` / `\|\|` / `!` | `if not isinstance(...)` |
| `f"{x}"` | `` `${x}` `` | `f"{INSTANCE_NAME}.log"` |
| `{"a": 1}` (dict) | `{a: 1}` (objeto) | `msg = {...}` |
| `[1, 2]` (list) | `[1, 2]` (array) | `PEERS` |
| `{"a", "b"}` (set) | `new Set(["a","b"])` | campos do `/replicate` |
| `[x for x in lista]` | `lista.map(x => x)` | `PEERS = [...]` |
| `[x for x in lista if c]` | `lista.filter(...).map(...)` | `read_messages` |
| `*lista` | `...lista` | `[INSTANCE_NAME, *PEERS]` |
| `X if c else Y` | `c ? X : Y` | `201 if ... else 207` |
| `try/except` | `try/catch` | `replicate_to_peer` |
| `try/finally` | `try/finally` | destravar o arquivo |
| `with open(...) as f:` | (não tem igual) | abre e fecha o arquivo sozinho |
| `len(x)` | `x.length` | `len(msgs)` |
| `any(...)` / `all(...)` | `.some()` / `.every()` | idempotência e verificação |
| `@decorator` | (não tem igual nativo) | `@app.post("/send")` |
| `x: str` / `-> bool` | TypeScript `x: string` | type hints |

---

# Parte 2: `index.html`

A página tem duas partes: o **HTML**, que é a estrutura que aparece na tela, e o **JavaScript** dentro de `<script>`, que é o comportamento. Não tem CSS.

## 2.1 Cabeçalho (linhas 1-6)

```html
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <title>{{ instance }} - Mensagens</title>
</head>
```

- `<!doctype html>` avisa ao navegador que a página é HTML5 moderno.
- `lang="pt-br"` diz que o idioma é português. Leitores de tela e o tradutor do navegador usam isso.
- `<meta charset="utf-8">` faz os acentos aparecerem certo.
- `<title>` é o texto da **aba** do navegador.
- **`{{ instance }}` não é HTML.** É marcação do **Jinja2**. Antes de mandar a página, o Flask troca isso pelo valor passado no `render_template`. O navegador recebe `<title>app1 - Mensagens</title>`. Por isso cada aba mostra o nome do próprio container.

## 2.2 Título e links (linhas 8-14)

```html
<h1>Instância: {{ instance }}</h1>
<p>
  Abra as outras instâncias em outras abas para ver a replicação:
  <a href="http://localhost:5001">app1 (5001)</a> |
  <a href="http://localhost:5002">app2 (5002)</a> |
  <a href="http://localhost:5003">app3 (5003)</a>
</p>
```

- `<h1>` é o título principal.
- `<p>` é um parágrafo.
- `<a href="...">` é um link. Aqui ele leva para cada container usando as portas do **host** (5001, 5002, 5003), porque quem acessa é o navegador, fora do Docker.

## 2.3 Formulário de envio (linhas 16-21)

```html
<h2>Enviar mensagem</h2>
<form id="form">
  <input id="texto" placeholder="Digite a mensagem" size="40" required>
  <button type="submit">Enviar</button>
</form>
<pre id="resultado"></pre>
```

- `<form>` agrupa o campo e o botão. Apertar Enter ou clicar no botão dispara o evento `submit`.
- **`id="..."`** é um nome único que o JavaScript usa para encontrar o elemento.
- `<input>` é o campo de texto.
  - `placeholder` é o texto cinza que aparece quando o campo está vazio.
  - `size="40"` é a largura, em caracteres.
  - `required` faz o navegador não deixar enviar o campo vazio.
- `<button type="submit">` é o botão que envia o formulário.
- `<pre id="resultado">` começa vazio. Depois do envio, o JavaScript coloca a resposta do servidor aqui. `<pre>` mantém quebras de linha e espaços, então o JSON aparece formatado.

## 2.4 Tabela de mensagens (linhas 23-30)

```html
<h2>Mensagens armazenadas em {{ instance }} (<span id="total">0</span>)</h2>
<p><small>Atualiza sozinho a cada 2 segundos.</small></p>
<table border="1" cellpadding="4">
  <thead>
    <tr><th>Horário</th><th>Origem</th><th>Mensagem</th><th>ID</th></tr>
  </thead>
  <tbody id="lista"></tbody>
</table>
```

- `<span id="total">` é um pedaço de texto que o JavaScript atualiza com a quantidade de mensagens.
- `<small>` deixa o texto menor.
- `<table>` é a tabela.
  - `border="1"` desenha as bordas e `cellpadding="4"` dá um espaçamento interno. São atributos antigos do HTML, usados aqui para não precisar de CSS.
  - `<thead>` é o cabeçalho, `<tr>` é uma linha (*table row*) e `<th>` é uma célula de título (*table header*).
  - `<tbody id="lista">` começa **vazio**. O JavaScript preenche esse corpo com uma linha para cada mensagem.

## 2.5 JavaScript (linhas 32-69)

### Carregar as mensagens: `carregarMensagens()`

```javascript
async function carregarMensagens() {
  const resp = await fetch("/messages");
  const dados = await resp.json();
  document.getElementById("total").textContent = dados.count;
```

- **`async function`** declara uma função **assíncrona**, que pode esperar operações demoradas (como a rede) sem travar a página.
- **`await`** espera a operação terminar antes de seguir para a próxima linha. Só funciona dentro de uma função `async`.
- **`fetch("/messages")`** faz uma requisição GET para `/messages`.
  - O endereço não tem `http://localhost:5001` porque um **caminho relativo** vai para o mesmo servidor que entregou a página. Na aba do app2, a requisição vai para o app2.
- `resp.json()` lê o corpo da resposta e converte o JSON em objeto JavaScript. Depois dessa linha, `dados` é algo como:
  ```javascript
  { instance: "app1", count: 2, messages: [ {...}, {...} ] }
  ```
- `document.getElementById("total")` encontra o elemento com `id="total"`. `.textContent = dados.count` troca o texto dele pelo número de mensagens.

```javascript
  const lista = document.getElementById("lista");
  lista.innerHTML = "";
```

- Encontra o `<tbody>` e apaga o conteúdo dele (`innerHTML = ""`). A tabela é redesenhada do zero a cada atualização.

```javascript
  for (const m of dados.messages.slice().reverse()) {
```

- `for (const m of lista)` passa por cada item da lista. `m` é uma mensagem.
- `.reverse()` inverte a ordem para as **mais recentes aparecerem primeiro**.
- `.slice()` cria uma **cópia** antes de inverter, porque o `.reverse()` altera a lista original. Neste caso não faria diferença, mas é um bom hábito.

```javascript
    const tr = document.createElement("tr");
    for (const valor of [new Date(m.timestamp).toLocaleString(), m.origin, m.message, m.id]) {
      const td = document.createElement("td");
      td.textContent = valor;
      tr.appendChild(td);
    }
    lista.appendChild(tr);
  }
}
```

Para cada mensagem:

1. `document.createElement("tr")` cria uma linha nova da tabela (ainda fora da página).
2. Monta uma lista com os 4 valores das colunas:
   - `new Date(m.timestamp).toLocaleString()` converte a data ISO (`2026-10-03T12:20:12+00:00`) para o formato e o fuso do seu computador (`03/10/2026, 09:20:12`).
   - `m.origin`, `m.message` e `m.id` vêm direto da mensagem.
3. Para cada valor, cria uma célula `<td>`, coloca o texto e prende a célula na linha com `appendChild`.
4. Prende a linha pronta no `<tbody>`. Aí ela aparece na tela.

**Por que `textContent` e não `innerHTML`?** O `textContent` trata o valor como **texto puro**. Se alguém enviar a mensagem `<script>alert('hack')</script>`, ela aparece escrita na tela e não é executada. Com `innerHTML`, o navegador interpretaria isso como HTML, e qualquer pessoa conseguiria rodar código na página dos outros. Esse ataque se chama **XSS** (*Cross-Site Scripting*).

### Enviar mensagem: evento do formulário

```javascript
document.getElementById("form").addEventListener("submit", async (e) => {
  e.preventDefault();
```

- `addEventListener("submit", função)`: "quando o formulário for enviado, rode esta função".
- `async (e) => { ... }` é uma **arrow function** (forma curta de escrever uma função), assíncrona. `e` é o **evento**, com informações sobre o que aconteceu.
- **`e.preventDefault()`** cancela o comportamento padrão. Por padrão, enviar um formulário **recarrega a página inteira**. A gente quer enviar por JavaScript sem recarregar.

```javascript
  const campo = document.getElementById("texto");
  const resp = await fetch("/send", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: campo.value }),
  });
```

É o mesmo que o `curl` da prova faz, só que pelo navegador:

| `fetch` | `curl` equivalente |
|---|---|
| `method: "POST"` | `-X POST` |
| `headers: { "Content-Type": "application/json" }` | `-H "Content-Type: application/json"` |
| `body: JSON.stringify({ message: ... })` | `-d '{"message":"..."}'` |

- `campo.value` é o texto digitado no `<input>`.
- `JSON.stringify(...)` converte o objeto JavaScript em texto JSON. É o equivalente do `json.dumps` do Python.
- O cabeçalho `Content-Type` é **obrigatório**. Sem ele, o `request.get_json()` do Flask não reconhece o corpo como JSON e devolve `None`, e o servidor responde 400.

```javascript
  const dados = await resp.json();
  document.getElementById("resultado").textContent =
    "Status HTTP: " + resp.status + "\n" + JSON.stringify(dados, null, 2);
  campo.value = "";
  carregarMensagens();
});
```

- Lê a resposta do servidor e mostra no `<pre id="resultado">`:
  - `resp.status` é o código HTTP (201, 207 ou 400).
  - `JSON.stringify(dados, null, 2)` converte em texto **com indentação de 2 espaços**, para ficar legível. O `null` é um parâmetro que a gente não usa.
- `campo.value = ""` limpa o campo para a próxima mensagem.
- `carregarMensagens()` atualiza a tabela na hora, sem esperar os 2 segundos.

### Início e atualização automática

```javascript
carregarMensagens();
setInterval(carregarMensagens, 2000);
```

- A primeira linha carrega as mensagens assim que a página abre.
- **`setInterval(função, ms)`** chama a função **repetidamente** a cada X milissegundos. 2000 ms são 2 segundos. É isso que faz a mensagem enviada pelo app1 aparecer sozinha na aba do app2.
- Repare que é `carregarMensagens`, **sem parênteses**. Estamos passando a função para o `setInterval` chamar depois. Com parênteses, ela seria chamada uma vez agora, e o `setInterval` receberia o resultado dela.

### Por que cada aba mostra só o próprio container?

A página do app1 (porta 5001) não consegue chamar `http://localhost:5002/messages` direto. O navegador bloqueia por segurança, porque portas diferentes contam como **sites diferentes**. Essa regra se chama **CORS** (*Cross-Origin Resource Sharing*). Por isso o jeito de ver a replicação é abrir as 3 abas, uma para cada container.

---

# Parte 3: o caminho completo de uma mensagem

Você digita **"oi"** na aba do **app1** (`localhost:5001`) e clica em Enviar:

1. **Navegador** (`index.html`): `e.preventDefault()` impede o recarregamento, e o `fetch` faz um `POST /send` com `{"message": "oi"}`.
2. **Docker**: a porta 5001 do seu PC é redirecionada para a porta 5000 do container app1.
3. **app1** (`send()`):
   1. Valida o JSON.
   2. Cria a mensagem com `id`, `origin: "app1"` e `timestamp`.
   3. `store_message` grava uma linha nova em `/data/app1.log`.
   4. `replicate_to_peer("app2", msg)` faz `POST http://app2:5000/replicate`.
4. **app2** (`replicate()`): valida e grava em `/data/app2.log`. **Não reenvia.** Responde 200.
5. **app1** recebe o 200 do app2 e faz o mesmo com o **app3**, que grava em `/data/app3.log`.
6. **app1** (`verify_replication`): lê os 3 arquivos no volume compartilhado e confirma que o `id` está nos três.
7. **app1** responde **201** com `data`, `replication` e `verification`.
8. **Navegador**: mostra a resposta no `<pre>`, limpa o campo e atualiza a tabela.
9. **Abas do app2 e do app3**: em até 2 segundos, o `setInterval` chama `GET /messages`, e cada container lê o **próprio** log, onde o "oi" já está. A mensagem aparece na tabela.

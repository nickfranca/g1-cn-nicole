# Sistema de Mensagens Distribuído com Docker

Avaliação G1 de Computação em Nuvem. São três containers da mesma aplicação Python/Flask (`app1`, `app2` e `app3`). Eles trocam mensagens entre si e gravam tudo em um volume Docker compartilhado.

## Arquitetura

```
                 localhost:5001      localhost:5002      localhost:5003
                       │                   │                   │
              ┌────────▼───────┐  ┌────────▼───────┐  ┌────────▼───────┐
              │      app1      │  │      app2      │  │      app3      │
              │   Flask :5000  │◄─►   Flask :5000  │◄─►   Flask :5000  │
              └────────┬───────┘  └────────┬───────┘  └────────┬───────┘
                       │    rede bridge "messaging-net"        │
                       └───────────────────┼───────────────────┘
                                           ▼
                           volume "messages-data" → /data
                           ├── app1.log
                           ├── app2.log
                           └── app3.log
```

**Fluxo de uma mensagem enviada para `app1`:**

1. `POST /send` chega ao `app1`, que cria um `id` (UUID), registra `origin` e `timestamp` e grava a mensagem em `/data/app1.log`.
2. O `app1` envia uma cópia para `http://app2:5000/replicate` e outra para `http://app3:5000/replicate`. Os nomes de serviço do Compose funcionam como hostnames dentro da rede bridge. Se um envio falhar, ele é repetido até 3 vezes.
3. Cada par grava a cópia no próprio log. O endpoint `/replicate` não reencaminha a mensagem, o que evita loop infinito. Ele também ignora mensagens com `id` repetido.
4. O `app1` lê os três arquivos de log no volume compartilhado para conferir se a mensagem foi replicada. O resultado vem no campo `verification` da resposta.

## Estrutura do projeto

```
.
├── app/
│   ├── app.py             # Código principal (API Flask)
│   ├── requirements.txt   # Dependências (flask, requests, gunicorn)
│   ├── Dockerfile         # Imagem da aplicação
│   ├── templates/
│   │   └── index.html     # Interface web simples
│   └── .dockerignore
├── docker-compose.yml     # 3 instâncias + volume + rede bridge
├── test.sh                # Script de teste automatizado
└── README.md
```

## Pré-requisitos

- Docker 20+ com Docker Compose (`docker compose` ou `docker-compose`)
- `curl` e `python3` no host. São usados só pelo `test.sh`.

## Como executar

```bash
# Subir os 3 containers (faz o build da imagem na primeira vez)
docker compose up -d --build        # ou: docker-compose up -d --build

# Ver o status (a coluna STATUS deve mostrar "healthy")
docker compose ps

# Acompanhar os logs das três instâncias
docker compose logs -f
```

| Instância | URL no host             | Hostname na rede interna |
|-----------|-------------------------|--------------------------|
| app1      | http://localhost:5001   | `app1:5000`              |
| app2      | http://localhost:5002   | `app2:5000`              |
| app3      | http://localhost:5003   | `app3:5000`              |

## Interface web

Abra http://localhost:5001, http://localhost:5002 e http://localhost:5003 em abas diferentes. Envie uma mensagem por uma delas e ela aparece nas outras em até 2 segundos, que é o intervalo de atualização da página.

## Endpoints

| Método | Rota             | Descrição |
|--------|------------------|-----------|
| POST   | `/send`          | Recebe `{"message": "..."}`, grava localmente, replica para os pares e verifica a replicação. Retorna `201`, ou `207` se algum par não confirmou. Corpo inválido retorna `400`. |
| GET    | `/messages`      | Retorna todas as mensagens armazenadas no log desta instância. |
| GET    | `/verify/<id>`   | Diz em quais logs do volume compartilhado a mensagem aparece. Retorna `200` se está nos três e `404` caso contrário. |
| POST   | `/replicate`     | Uso interno: recebe a cópia enviada por outra instância. |
| GET    | `/health`        | Health check usado pelo Docker. |
| GET    | `/`              | Página HTML para enviar e ver as mensagens pelo navegador. |
| GET    | `/api`           | Lista os endpoints disponíveis (JSON). |

> Pelo navegador só é possível testar as rotas `GET`, como `http://localhost:5001/messages`. O navegador não consegue mandar o `POST /send`. Para isso, use o `curl` ou uma ferramenta como Postman ou Insomnia.

### Exemplo de uso

```bash
# 1. Enviar uma mensagem para o app1
curl -X POST -H "Content-Type: application/json" \
     -d '{"message":"hello"}' http://localhost:5001/send
```

```json
{
  "data": {
    "id": "5c997c17-d617-43c8-ae51-9244561b38d6",
    "message": "hello",
    "origin": "app1",
    "timestamp": "2026-10-03T12:20:12.548595+00:00"
  },
  "replication": [
    {"peer": "app2", "status": "ok", "attempts": 1},
    {"peer": "app3", "status": "ok", "attempts": 1}
  ],
  "verification": {
    "id": "5c997c17-d617-43c8-ae51-9244561b38d6",
    "instances": {"app1": true, "app2": true, "app3": true},
    "replicated": true
  }
}
```

```bash
# 2. Ler as mensagens pelo app2. A mensagem enviada ao app1 aparece aqui.
curl http://localhost:5002/messages

# 3. Verificar a replicação de uma mensagem específica
curl http://localhost:5003/verify/5c997c17-d617-43c8-ae51-9244561b38d6

# 4. Ver os arquivos de log no volume compartilhado
docker exec app1 ls -l /data
docker exec app1 cat /data/app2.log
```

## Testes automatizados

```bash
chmod +x test.sh
./test.sh            # sobe o ambiente, roda os testes e deixa os containers no ar
./test.sh --down     # mesma coisa, mas derruba os containers no final
```

O script verifica:

1. O envio de uma mensagem para o `app1`.
2. Se a mensagem aparece em `GET /messages` nas três instâncias.
3. Se `GET /verify/<id>` confirma a replicação em todas elas.
4. Se cada container tem seu próprio arquivo `/data/appN.log` no volume compartilhado.
5. Se uma mensagem enviada pelo `app3` chega ao `app1` e ao `app2`.
6. Se uma requisição inválida recebe `400`.
7. Se as mensagens continuam lá depois de `docker compose restart`.

## Boas práticas de Docker adotadas

- **Imagem enxuta:** usa `python:3.12-slim`, com `pip --no-cache-dir` e só as dependências necessárias, todas com versão fixa.
- **Cache de camadas:** o `requirements.txt` é copiado e instalado antes do código, então mudar o `app.py` não reinstala as dependências.
- **Usuário sem root:** a aplicação roda como `appuser`.
- **`.dockerignore`:** deixa arquivos desnecessários fora do contexto de build.
- **Servidor de produção:** usa Gunicorn, com 2 workers e 4 threads, em vez do servidor de desenvolvimento do Flask.
- **HEALTHCHECK:** o Docker consulta `/health` para monitorar cada container.
- **Configuração por variáveis de ambiente:** `INSTANCE_NAME`, `PEERS` e `DATA_DIR`. A mesma imagem atende as três instâncias.
- **Compose sem repetição:** um *YAML anchor* (`x-app`) guarda a configuração comum aos três serviços.
- **`restart: unless-stopped`:** os containers voltam sozinhos se caírem.
- **Escrita segura no volume:** `fcntl.flock` impede escrita simultânea em um mesmo log, e o `id` de cada mensagem garante que ela não seja gravada duas vezes.

## Persistência

As mensagens ficam no volume nomeado `messages-data`, que sobrevive a `docker compose down` e `restart`. Para apagar tudo:

```bash
docker compose down -v
```

Cada linha dos arquivos `appN.log` é um JSON, no formato *JSON Lines*.

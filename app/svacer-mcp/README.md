# Svacer MCP Server

MCP-сервер поверх публичного REST API [Svacer](https://svacer.ispras.ru). 8 инструментов, 2 транспорта (STDIO и Streamable HTTP), [FastMCP](https://github.com/modelcontextprotocol/python-sdk) под капотом.

Подробная документация размещена на [wiki](https://svacer.ispras.ru/mediawiki/index.php?title=Help:13-alpha_MCP).

## Dev quick start

```bash
git clone https://gitlab.ispras.ru/svacer-public/svacer-mcp.git && cd svacer-mcp
python3 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -e .

cp .env.example .env  # SVACER_URL, SVACER_LOGIN, SVACER_PASSWORD

# STDIO
svacer-mcp

# Streamable HTTP, порт 8002 на хосте
docker compose up --build
```

## Архитектура

```
svacer_mcp/
├── server.py        # FastMCP + lifespan, регистрация 8 тулов
├── tools/           # по одному файлу на тул, JSON schema из аннотаций
├── api_client.py    # httpx-обёртка над /api/public/*, retry on 401
├── auth.py          # JWT, авто-refresh при истечении и 401
├── config.py        # Pydantic Settings, env vars с префиксом SVACER_
├── exceptions.py    # SvacerError → Auth / API / Config / Validation
└── utils/filters.py # FilterBuilder: фильтры маркеров → base64 JSON
```

## Тесты

Тестовые зависимости лежат в extra `[dev]` (`pytest`, `pytest-asyncio`, `respx`, `pytest-httpserver`):

```bash
pip install -e ".[dev]"             # один раз

pytest tests/ -v                    # всё (system скипаются без env)
pytest tests/unit/ -v               # быстрые, без MCP
pytest tests/integration/           # MCP in-memory + httpx mock
```

Тесты против живого стенда лежат в `tests/system/` и прибиты к `svacer-demo.ispras.ru`. Запускаются отдельно — без `SVACER_URL/LOGIN/PASSWORD` в окружении вся подсессия скипается, поэтому в обычном прогоне и в CI они не мешают.

```bash
export SVACER_URL=https://svacer-demo.ispras.ru SVACER_LOGIN=admin SVACER_PASSWORD=admin
pytest tests/ -m system -v
```

Hardcoded UUID/имена живут в `tests/system/_demo.py`. Если стенд переедет или снэпшоты прокрутят — пересними значения скриптом `python -m tests.system._discover` и подставь в `_demo.py`.

Отладка тулов через MCP Inspector: `./run_inspector.sh` (нужен Node.js).

## Разработка

- Новый тул: файл в `tools/`, метод в `api_client.py`, регистрация в `server.py`, тесты в `tests/unit/` и `tests/integration/`.
- Описания тулов и `SERVER_INSTRUCTIONS` лежат в `tools/descriptions.py`.

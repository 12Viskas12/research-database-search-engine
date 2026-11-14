# Research Database Search Engine

![Python](https://img.shields.io/badge/Python-3.12-8b5cf6?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110-8b5cf6?style=flat-square&logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-8b5cf6?style=flat-square&logo=postgresql&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-8b5cf6?style=flat-square&logo=docker&logoColor=white)

Upload CSV, XLSX or XML files and search through them from a web page, a REST API or a Telegram bot.

## Features

- Upload `.csv`, `.xlsx` and `.xml` files
- Automatic cleaning: HTML tags, duplicates, empty rows and columns, column names
- Background processing with a progress bar
- Full-text search with a partial match fallback
- Web interface, REST API and Telegram bot

## Stack

| Part | Tool |
| --- | --- |
| API and web | FastAPI, Jinja2 |
| Database | PostgreSQL |
| Queue | Redis, arq |
| Bot | aiogram |
| Cleaning | pandas |
| Run | Docker Compose |

## Quick start

```bash
git clone https://github.com/12Viskas12/research-database-search-engine.git
cd research-database-search-engine
echo "BOT_TOKEN=your_bot_token" > .env
docker compose up --build
```

Open [localhost:8000](http://localhost:8000). API docs are at `/docs`.

## Configuration

Settings are read from `.env`.

| Variable | Default | Description |
| --- | --- | --- |
| `BOT_TOKEN` | none | Telegram bot token |
| `DATABASE_URL` | `postgresql://postgres:postgres@db:5432/search` | PostgreSQL connection |
| `REDIS_URL` | `redis://redis:6379` | Redis connection |
| `UPLOAD_DIR` | `/data/uploads` | Where uploaded files are stored |

## API

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/api/files` | Upload a file |
| `GET` | `/api/files` | List files with status and progress |
| `GET` | `/api/files/{id}` | Get one file |
| `GET` | `/api/search?q=text&limit=20&offset=0` | Search records |

Example:

```bash
curl -F "file=@data.csv" localhost:8000/api/files
curl "localhost:8000/api/search?q=Kyiv"
```

## Telegram bot

Send any text to the bot and it replies with the five best matches.

## How it works

1. The file is saved and a job is added to the Redis queue.
2. The worker reads the file with a parser and cleans the rows.
3. Records are written to PostgreSQL in batches.
4. Search runs on a `tsvector` index.

## Project structure

```
app/
  core/        settings, Redis
  db/          connection pool, schema
  parsers/     csv, xlsx, xml
  routers/     files, search, pages
  services/    cleaner, ingestion, search
  static/      css, js
  templates/   html
bot/           Telegram bot
workers/       background tasks
```

## License

See [LICENSE](LICENSE).

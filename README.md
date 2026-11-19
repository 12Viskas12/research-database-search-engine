# Research Database Search Engine

![Python](https://img.shields.io/badge/Python-3.12-8b5cf6?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110-8b5cf6?style=flat-square&logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-8b5cf6?style=flat-square&logo=postgresql&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-8b5cf6?style=flat-square&logo=docker&logoColor=white)

Upload data files and search through them from a web page, a REST API or a Telegram bot.

## Formats

| Type | Extensions |
| --- | --- |
| Tables | `csv` `tsv` `xlsx` `xlsm` `xls` `ods` |
| Structured | `json` `jsonl` `ndjson` `xml` `sql` |
| Documents | `pdf` `docx` `html` `htm` |
| Text | `txt` `log` `md` `dat` and any other text file |

SQL dumps are read from `INSERT` and `COPY` statements.

## Features

- Upload files in many formats, the type is detected automatically
- Automatic cleaning: HTML tags, duplicates, empty rows and columns, column names
- Background processing with a progress bar
- Full-text search that tolerates typos, word beginnings and partial data
- Filters by file and by field, "Show more" paging, per-user search history
- Compression of single files or all files merged into one, search keeps working
- Auto compression of old files
- Accounts with roles, VIP expiry, password change and an audit log
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
docker compose up --build
```

Open [localhost:8000](http://localhost:8000). The first start creates an admin and prints the login in the logs:

```bash
docker compose logs app | grep ADMIN
```

The bot is optional. To run it, put `BOT_TOKEN` into `.env` and start with the `bot` profile:

```bash
docker compose --profile bot up --build
```

See `.env.example` for all settings.

## Configuration

Settings are read from `.env`.

| Variable | Default | Description |
| --- | --- | --- |
| `BOT_TOKEN` | none | Telegram bot token, the bot is disabled without it |
| `SITE_URL` | `http://localhost:8000` | Link the bot sends with the token |
| `ADMIN_USERNAME` | `admin` | First admin login |
| `ADMIN_PASSWORD` | random | First admin password, printed in the logs if empty |
| `QUOTA_USER` | `5` | Searches per day for the user role |
| `QUOTA_VIP` | `50` | Searches per day for the vip role |
| `DATABASE_URL` | `postgresql://postgres:postgres@db:5432/search` | PostgreSQL connection |
| `REDIS_URL` | `redis://redis:6379` | Redis connection |
| `UPLOAD_DIR` | `/data/uploads` | Where uploaded files are stored |

## Search

Stages, the first one with results wins:

1. All words match exactly.
2. Every word matches exactly, by prefix or with a typo (one or two edits).
3. The whole query is found as a substring, digits included.
4. For queries with 3 or more words, at least half of the words match (name and surname without a phone, for example).

Filters:

- Pick a file in the list above the results.
- Search one field with `city:Kyiv` or `name:"Ivan Petrenko"`. Several fields can be combined with free text.

"Show more" loads the next page of the same search and does not use the daily limit. The word list for typos is built during upload. After an upgrade it is built automatically, or press "Update search words" in the Files tab.

## Accounts

Registration works only with a token.

1. A person sends `/request` to the Telegram bot.
2. The admin approves the request on the site as user or vip.
3. The bot sends the token to the person.
4. The person registers on the site with the token.

Without the bot the admin creates tokens directly in the Tokens tab.

| Role | Searches per day | Access |
| --- | --- | --- |
| user | 5 | search |
| vip | 50 | search |
| admin | unlimited | search, files, compression, requests, tokens, users |

The limit resets at 00:00 UTC. Each search and each "I'm feeling lucky" counts. Searches get a rank title: Новичок, Следопыт, Сыщик, Детектив, Шерлок.

VIP can have a term (7, 30, 90, 365 days or forever) set on a token, on a request or on a user. When it ends the account becomes a normal user.

Every user can change the password in the Profile tab, other sessions are closed. The admin can reset any password in the Users tab. Failed logins are limited in Redis: 8 per login and address, 40 per address in 10 minutes.

The History tab shows the last searches of the account, including the ones from the bot. The Log tab (admin) lists logins, role changes, uploads, compression and other actions with filters.

## API

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/api/auth/register` | Register with a token |
| `POST` | `/api/auth/login` | Log in |
| `POST` | `/api/auth/logout` | Log out |
| `GET` | `/api/auth/me` | Profile, quota and rank |
| `GET` | `/api/search?q=text&limit=20&offset=0&files=1,2&search_id=5` | Search records |
| `GET` | `/api/sources` | Files available for the filter |
| `GET` | `/api/history` | Search history |
| `DELETE` | `/api/history` | Clear search history |
| `POST` | `/api/auth/password` | Change the password |
| `POST` | `/api/auth/tg-code` | Code for linking Telegram |
| `DELETE` | `/api/auth/tg` | Unlink Telegram |
| `GET` | `/api/lucky` | Random record |
| `POST` | `/api/files` | Upload a file, admin |
| `GET` | `/api/files` | List files with status and progress, admin |
| `GET` | `/api/files/{id}` | Get one file, admin |
| `POST` | `/api/compress/files/{id}/pack?method=bz2` | Compress one file |
| `POST` | `/api/compress/files/{id}/unpack` | Restore a compressed file |
| `POST` | `/api/compress/merge` | Merge files into one compressed file |
| `POST` | `/api/compress/reclaim` | Free disk space after compression |
| `GET` | `/api/compress/stats` | Sizes before and after |

Admin only: `/api/files`, `/api/compress/*` and `/api/admin/*` (requests, invites, users, password reset, audit, settings).

Example:

```bash
curl -c jar -H "Content-Type: application/json" -d '{"username":"admin","password":"..."}' localhost:8000/api/auth/login
curl -b jar -F "file=@data.csv" localhost:8000/api/files
curl -b jar "localhost:8000/api/search?q=Kyiv"
```

## Compression

Rows are packed into blocks of 2000 and compressed with `bz2`, `zlib` or `lzma`. Every block has a small Bloom filter of its words, so search skips blocks that cannot match and unpacks only the rest. Results come from live and compressed files together.

```bash
curl -b jar -X POST "localhost:8000/api/compress/files/1/pack?method=bz2"
curl -b jar -X POST localhost:8000/api/compress/merge -H "Content-Type: application/json" -d '{"name": "all"}'
curl -b jar -X POST localhost:8000/api/compress/reclaim
```

Auto compression is set in the Files tab: right after upload or after a number of days. The worker checks every 10 minutes.

Merge replaces the source files with one file, each row keeps its `source_file`. Disk space is returned after `reclaim`, which briefly locks the tables.

## Telegram bot

| Command | Action |
| --- | --- |
| `/request text` | Ask for access |
| `/status` | Check the request or the account |
| `/link CODE` | Link the account, the code is in the Profile tab |
| `/id` | Show your Telegram ID |
| any text | Search, the five best matches |

Search in the bot uses the same account and the same daily limit as the site.

Admins with a linked Telegram get every new request in the bot with buttons: user, VIP 30 days, VIP forever, reject. The token goes to the requester right after.

## How it works

1. The file is saved and a job is added to the Redis queue.
2. The worker reads the file with a parser and cleans the rows.
3. Records are written to PostgreSQL in batches.
4. Search runs on a `tsvector` index with a trigram word list for typos.

## Project structure

```
app/
  core/        settings, Redis
  db/          connection pool, schema
  parsers/     one parser per format
  routers/     files, search, pages
  services/    cleaner, ingestion, search
  static/      css, js
  templates/   html
bot/           Telegram bot
workers/       background tasks
```

## License

See [LICENSE](LICENSE).

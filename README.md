# PMO System

## Run with Docker

Requires Docker and Docker Compose.

```bash
cp .env.example .env
```

Set `PMO_SECRET_KEY` in `.env` to a random secret. Generate one with
`python3 -c 'import secrets; print(secrets.token_hex(32))'`.

```bash
docker compose up -d --build
```

Open http://localhost:8000. API documentation is at http://localhost:8000/docs.
Set `PMO_PORT` in `.env` to use a different host port.

The first startup creates sample data and an administrator account:

- Email: `rana@opex.com.sa`
- Password: `Pmo@2026`

The application is bound to localhost. Change the seeded credentials before
making it available to other users.

```bash
docker compose ps
docker compose logs -f app
docker compose down
```

SQLite data is stored in the `pmo_data` Docker volume and survives container
rebuilds and `docker compose down`. `docker compose down -v` deletes that data.

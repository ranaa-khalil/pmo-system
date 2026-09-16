# PMO System — Deployment Guide

## Prerequisites

- Docker Engine 24+ and Docker Compose v2
- A domain name pointing to the server (e.g. `pmo-system.obelion.ai`)
- Resend API key (free at https://resend.com) for password reset emails
- (Optional) GitHub token for GitHub board sync
- (Optional) AI API key for AI assistant features

## Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/ranaa-khalil/pmo-system.git
cd pmo-system
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set the following critical values:

| Variable | Required | Example |
|----------|----------|---------|
| `PMO_SECRET_KEY` | YES | Run `python -c "import secrets; print(secrets.token_hex(32))"` |
| `PMO_POSTGRES_PASSWORD` | YES | A strong random password |
| `PMO_APP_URL` | YES | `https://pmo-system.obelion.ai` |
| `PMO_RESEND_API_KEY` | YES | `re_xxxxxxxx` from resend.com |
| `INFRA_ENCRYPTION_KEY` | YES | Run `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `PMO_ENV` | YES | `production` |
| `PMO_DEBUG` | YES | `false` |

Leave other variables empty if you don't need GitHub sync or AI features.

### 3. Start the services

```bash
docker compose up -d
```

This starts:
- **PostgreSQL 16** (with persistent volume `pgdata`)
- **PMO System app** (gunicorn + uvicorn, port 8000)

The app auto-seeds the database on first launch (creates OPEX tenant, admin user, demo data).

### 4. Verify

```bash
# Check health
curl http://localhost:8000/health
# Expected: {"status":"healthy","app":"PMO System"}

# Check logs
docker compose logs -f app
```

### 5. Set up reverse proxy (nginx + SSL)

Put nginx in front of the app for HTTPS:

```nginx
server {
    listen 80;
    server_name pmo-system.obelion.ai;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name pmo-system.obelion.ai;

    ssl_certificate /etc/letsencrypt/live/pmo-system.obelion.ai/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/pmo-system.obelion.ai/privkey.pem;

    client_max_body_size 10M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Use Let's Encrypt for free SSL certificates:
```bash
sudo certbot --nginx -d pmo-system.obelion.ai
```

### 6. First login

Open `https://pmo-system.obelion.ai` in your browser.

**Super Admin (manages all tenants):**
- Email: `admin@pmosystem.app`
- Password: `Pmo@2026`

**Tenant Admin (OPEX tenant):**
- Email: `rana@opex.com.sa`
- Password: `Pmo@2026`

⚠️ **Change both passwords immediately after first login.**

## Post-Deploy Checklist

- [ ] Change super admin password (login → Settings)
- [ ] Change tenant admin password
- [ ] Verify `PMO_APP_URL` matches your domain (password reset links depend on it)
- [ ] Test forgot password flow (enter email → check inbox → reset password)
- [ ] Verify Resend is sending emails (check Resend dashboard)
- [ ] If using a custom domain for email, verify it in Resend dashboard and update `PMO_EMAIL_FROM`
- [ ] Configure firewall: only expose ports 80/443, keep 5432 (PostgreSQL) internal
- [ ] Set up daily database backups: `docker exec pmo-db pg_dump -U pmo pmo_system | gzip > backup_$(date +%F).sql.gz`
- [ ] Review the app is running in production mode (Swagger docs at `/docs` should be disabled)
- [ ] Set up log rotation for Docker logs

## Useful Commands

```bash
# View logs
docker compose logs -f app
docker compose logs -f db

# Restart app
docker compose restart app

# Rebuild after code update
docker compose up -d --build

# Stop everything
docker compose down

# Stop and delete data (CAREFUL!)
docker compose down -v

# Manual database backup
docker exec pmo-system-db-1 pg_dump -U pmo pmo_system > backup.sql

# Restore from backup
cat backup.sql | docker exec -i pmo-system-db-1 psql -U pmo pmo_system

# Re-seed database (destroys existing data)
docker compose exec app python -m app.seed
```

## Demo Data

The seed script creates:

| Item | Count |
|------|-------|
| Tenant (OPEX) | 1 |
| Super admin | 1 |
| Tenant admin | 1 |
| Clients | 2 (NITC/PNU, GO Telecom) |
| Projects | 2 (PNU Cloud, CloudGate Platform) |
| Backlog items | 6 |
| KPIs | 5 |
| Milestones | 5 |
| Releases | 1 (with approval chain) |
| RACI roles | 12 |

## Architecture

```
Internet → nginx (443) → Docker app (8000) → PostgreSQL (5432)
                              ↓
                        Resend API (email)
```

## Troubleshooting

**App won't start:** Check `docker compose logs app` for errors. Most common: database not ready, missing env vars.

**Database connection refused:** Ensure `PMO_POSTGRES_PASSWORD` in `.env` matches. The db container takes a few seconds to initialize.

**Emails not sending:** Check `PMO_RESEND_API_KEY` is set. On Resend free tier, `PMO_EMAIL_FROM` must be `onboarding@resend.dev` unless you've verified your domain.

**Forgot password shows "Set New Password" form directly:** This means email sending failed and the system fell back to returning a token. Check Resend API key and logs.

**403 on API calls:** CORS is restricted to `PMO_APP_URL` in production. Make sure the domain in `.env` matches what users access.

## Security Notes

- `PMO_SECRET_KEY` is used for JWT signing — if compromised, all tokens are invalid. Keep it secret.
- `INFRA_ENCRYPTION_KEY` encrypts stored infrastructure secrets — if lost, encrypted secrets cannot be decrypted.
- The database stores bcrypt password hashes — passwords are never stored in plain text.
- Swagger API docs (`/docs`, `/redoc`) are disabled in production mode.
- Rate limiting: 500 req/min (Free), 2000 (Team), 5000 (Business), 10000 (Enterprise).

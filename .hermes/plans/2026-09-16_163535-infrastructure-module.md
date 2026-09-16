# Infrastructure Management Module — Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Add an Infrastructure Management module to the Obelion PMO platform focused on Assets and Secrets, with supporting Environments, Services, and Database registries, plus audit logging.

**Architecture:** New `infrastructure` router group + new models following the existing tenant-scoped pattern (`tenant_id` on every table, multi-tenant isolation via `current_tenant`). Secrets encrypted at rest using Fernet symmetric encryption with a tenant-scoped master key. All secret views/edits/deletes logged to an audit table. UI added as a new sidebar section "Infrastructure" with sub-routes for Assets, Secrets, Environments, Services, and Databases.

**Tech Stack:** FastAPI + SQLAlchemy + PostgreSQL (existing), cryptography (Fernet) for secret encryption, Jinja2 + Tailwind + Alpine.js (existing frontend).

**Source BRD:** `/Users/rainbow/Downloads/Obelion_Infrastructure_Module_BRD.md`

---

## Scope

### In scope (Phase 1 — this plan)
- **Environments** — dev, staging, prod, etc. (assets and secrets link to these)
- **Secrets Management** — encrypted storage, masked display, temporary reveal, versioning, rotation, expiration alerts, access audit
- **Asset Registry** — servers, VPS, GPU clusters, databases, domains, APIs, certificates, services (with owner, team, project, environment)
- **Services Registry** — third-party and internal services with linked secrets
- **Database Registry** — database instances with linked secrets
- **Audit Logging** — all create/update/delete/view/rotate actions on assets and secrets

### Deferred to Phase 2 (per BRD Section 18)
- Domains & SSL Certificate management (can be added later as asset sub-types)
- Deployment Management
- Cost Management
- Infrastructure Automation / Secret Injection / CI-CD Integration
- Dependency Graph Visualization
- Notifications (secret expiration, SSL expiration) — will be stubbed but not wired

---

## Current System Context

The PMO System is a multi-tenant SaaS:
- **Stack:** FastAPI + Jinja2 + Tailwind + Alpine.js + PostgreSQL
- **Pattern:** Every model has `tenant_id` for isolation. Routers use `get_current_tenant` dependency.
- **Auth:** JWT via `get_current_user`. Two-layer RBAC: system role (super_admin, account_manager, project_manager, member) + tenant role (owner, admin, member).
- **Frontend:** Single `app/templates/index.html` (~9300 lines). Alpine.js `pmoApp()` component with route-based navigation. `api()` method does `fetch('/api' + url)`.
- **Models:** `app/models/` — each model is a single file, registered in `app/models/__init__.py`.
- **Routers:** `app/routers/` — each router is a single file, registered in `app/main.py` via `app.include_router()`.
- **Services:** `app/services/` — business logic (usage_service, auth, notifications, etc.).
- **DB:** PostgreSQL, tables created via `Base.metadata.create_all(engine)` at startup.

---

## Proposed Approach

### Data Model

```
environments
├── id, tenant_id, name, type (enum), url, description, owner_id, status, created_at

secrets
├── id, tenant_id, name, category (enum), environment_id (FK),
│   encrypted_value (Text), description, owner_id,
│   status (active/rotated/expired), expires_at,
│   version (Integer, starts at 1), created_at, updated_at

secret_versions
├── id, secret_id (FK), version (Integer), encrypted_value (Text),
│   created_by (FK users), created_at

secret_access_log
├── id, secret_id (FK), user_id (FK), action (view/reveal/create/update/delete/rotate),
│   timestamp, ip_address

assets
├── id, tenant_id, name, asset_type (enum), environment_id (FK),
│   project_id (FK, nullable), owner_id (FK users), team (String),
│   status (active/maintenance/decommissioned), metadata (JSON/Text),
│   cost_monthly (Float, nullable), created_at, updated_at

services
├── id, tenant_id, name, service_type (enum), environment_id (FK),
│   owner_id (FK users), status, documentation_url,
│   linked_secret_ids (JSON array of secret IDs), created_at, updated_at

databases
├── id, tenant_id, name, db_type (enum), host, port, environment_id (FK),
│   owner_id (FK users), backup_policy (String),
│   linked_secret_ids (JSON array), created_at, updated_at
```

### Encryption Strategy

- Use `cryptography.fernet.Fernet` for symmetric encryption of secret values.
- A single master key stored in environment variable `INFRA_ENCRYPTION_KEY` (generated once, 32-byte url-safe base64).
- Each secret value is encrypted with Fernet using this key before storage.
- Decryption only happens in-memory during "reveal" — never stored decrypted.
- Masked display shows `••••••••` by default. Reveal returns the decrypted value via a dedicated endpoint that logs the access.

### UI Structure

New sidebar section "Infrastructure" with sub-routes:
- `infrastructure` — Overview dashboard (counts, recent activity, expiring secrets)
- `infra-assets` — Asset Registry (table + add/edit modal)
- `infra-secrets` — Secrets Management (table + add/edit modal, reveal button, version history)
- `infra-environments` — Environments (table + inline add)
- `infra-services` — Services Registry (table + add/edit modal)
- `infra-databases` — Database Registry (table + add/edit modal)

Access: visible to owner, admin, and account_manager roles. Developers/project_managers can view but not edit. Members cannot access.

---

## Task Breakdown

### Task 1: Install cryptography dependency

**Objective:** Add the `cryptography` package for Fernet encryption.

**Files:**
- Modify: `requirements.txt`

**Steps:**
1. Add `cryptography>=41.0.0` to `requirements.txt`
2. Run: `pip install cryptography`
3. Verify: `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key())"`

**Commit:** `chore: add cryptography dependency for secret encryption`

---

### Task 2: Create encryption service

**Objective:** Centralized encrypt/decrypt utility for secret values.

**Files:**
- Create: `app/services/encryption.py`

**Implementation:**

```python
"""Encryption service for infrastructure secrets using Fernet symmetric encryption."""
import os
from cryptography.fernet import Fernet

# Master key from environment — generate once with Fernet.generate_key()
# Store in .env or environment variable
_MASTER_KEY = os.getenv("INFRA_ENCRYPTION_KEY", "")

if not _MASTER_KEY:
    # Fallback: generate a persistent key and warn
    _MASTER_KEY = Fernet.generate_key().decode()
    import warnings
    warnings.warn("INFRA_ENCRYPTION_KEY not set — using ephemeral key. Secrets will be unreadable after restart.")

_fernet = Fernet(_MASTER_KEY.encode() if isinstance(_MASTER_KEY, str) else _MASTER_KEY)


def encrypt_value(plaintext: str) -> str:
    """Encrypt a plaintext string, return base64 ciphertext string."""
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str) -> str:
    """Decrypt a base64 ciphertext string, return plaintext."""
    return _fernet.decrypt(ciphertext.encode()).decode()


def mask_value(value: str, visible_chars: int = 0) -> str:
    """Return a masked version of a value."""
    if not value:
        return ""
    if visible_chars <= 0:
        return "•" * 12
    if len(value) <= visible_chars:
        return "•" * len(value)
    return value[:visible_chars] + "•" * (len(value) - visible_chars)
```

**Verify:**
```bash
python3 -c "
from app.services.encryption import encrypt_value, decrypt_value
ct = encrypt_value('my-secret-password')
print(f'Encrypted: {ct}')
print(f'Decrypted: {decrypt_value(ct)}')
assert decrypt_value(ct) == 'my-secret-password'
"
```

**Commit:** `feat: add encryption service for secrets`

---

### Task 3: Create Environment model

**Objective:** Model for tracking environments (dev, staging, prod, etc.).

**Files:**
- Create: `app/models/infrastructure.py` (single file for all infra models)
- Modify: `app/models/__init__.py` (register new models)

**Implementation:**

```python
"""Infrastructure models — environments, secrets, assets, services, databases."""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, Float, Text
from sqlalchemy.sql import func
from app.database import Base


class Environment(Base):
    """An infrastructure environment (dev, staging, prod, etc.)."""
    __tablename__ = "infra_environments"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=True, index=True)
    name = Column(String(255), nullable=False)
    type = Column(String(50), nullable=False)  # local, dev, qa, uat, staging, production
    url = Column(String(500), nullable=True)
    description = Column(Text, nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(50), default="active")  # active, inactive
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def to_dict(self):
        return {
            "id": self.id, "name": self.name, "type": self.type,
            "url": self.url, "description": self.description,
            "owner_id": self.owner_id, "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
```

**Commit:** `feat: add Environment model for infrastructure`

---

### Task 4: Create Secret, SecretVersion, SecretAccessLog models

**Objective:** Models for encrypted secrets with versioning and access audit.

**Files:**
- Modify: `app/models/infrastructure.py` (add to same file)

**Implementation:**

```python
class Secret(Base):
    """An encrypted secret (database password, API key, etc.)."""
    __tablename__ = "infra_secrets"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=True, index=True)
    name = Column(String(255), nullable=False)
    category = Column(String(50), nullable=False)
    # database, authentication, ai_providers, email, storage, payments, monitoring, custom
    environment_id = Column(Integer, ForeignKey("infra_environments.id", ondelete="SET NULL"), nullable=True)
    encrypted_value = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(50), default="active")  # active, rotated, expired
    expires_at = Column(DateTime(timezone=True), nullable=True)
    version = Column(Integer, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def to_dict(self, include_value=False):
        d = {
            "id": self.id, "name": self.name, "category": self.category,
            "environment_id": self.environment_id,
            "description": self.description, "owner_id": self.owner_id,
            "status": self.status, "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "version": self.version,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        d["value"] = "••••••••" if not include_value else None  # never send encrypted_value
        return d


class SecretVersion(Base):
    """Version history for a secret (for rollback)."""
    __tablename__ = "infra_secret_versions"

    id = Column(Integer, primary_key=True, index=True)
    secret_id = Column(Integer, ForeignKey("infra_secrets.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False)
    encrypted_value = Column(Text, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SecretAccessLog(Base):
    """Audit log for all secret access (view, reveal, create, update, delete, rotate)."""
    __tablename__ = "infra_secret_access_logs"

    id = Column(Integer, primary_key=True, index=True)
    secret_id = Column(Integer, ForeignKey("infra_secrets.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action = Column(String(50), nullable=False)  # view, reveal, create, update, delete, rotate
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ip_address = Column(String(50), nullable=True)
```

**Commit:** `feat: add Secret, SecretVersion, SecretAccessLog models`

---

### Task 5: Create Asset, Service, Database models

**Objective:** Models for the asset registry, services, and databases.

**Files:**
- Modify: `app/models/infrastructure.py` (add to same file)

**Implementation:**

```python
class Asset(Base):
    """An infrastructure asset (server, VPS, GPU cluster, domain, API, certificate, etc.)."""
    __tablename__ = "infra_assets"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=True, index=True)
    name = Column(String(255), nullable=False)
    asset_type = Column(String(50), nullable=False)
    # server, vps, gpu_cluster, database, domain, api, certificate, service, other
    environment_id = Column(Integer, ForeignKey("infra_environments.id", ondelete="SET NULL"), nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    team = Column(String(255), nullable=True)
    status = Column(String(50), default="active")  # active, maintenance, decommissioned
    metadata_json = Column(Text, nullable=True)  # JSON: host, IP, specs, etc.
    cost_monthly = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def to_dict(self):
        import json
        return {
            "id": self.id, "name": self.name, "asset_type": self.asset_type,
            "environment_id": self.environment_id, "project_id": self.project_id,
            "owner_id": self.owner_id, "team": self.team, "status": self.status,
            "metadata": json.loads(self.metadata_json) if self.metadata_json else {},
            "cost_monthly": self.cost_monthly,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class InfraService(Base):
    """A third-party or internal service (OpenAI, Anthropic, Redis, etc.)."""
    __tablename__ = "infra_services"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=True, index=True)
    name = Column(String(255), nullable=False)
    service_type = Column(String(50), nullable=False)  # ai, database, cache, storage, email, payments, monitoring, internal
    environment_id = Column(Integer, ForeignKey("infra_environments.id", ondelete="SET NULL"), nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(50), default="active")
    documentation_url = Column(String(500), nullable=True)
    linked_secret_ids = Column(Text, nullable=True)  # JSON array of secret IDs
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def to_dict(self):
        import json
        return {
            "id": self.id, "name": self.name, "service_type": self.service_type,
            "environment_id": self.environment_id, "owner_id": self.owner_id,
            "status": self.status, "documentation_url": self.documentation_url,
            "linked_secret_ids": json.loads(self.linked_secret_ids) if self.linked_secret_ids else [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class InfraDatabase(Base):
    """A database instance (PostgreSQL, MySQL, MongoDB, Redis, Supabase)."""
    __tablename__ = "infra_databases"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=True, index=True)
    name = Column(String(255), nullable=False)
    db_type = Column(String(50), nullable=False)  # postgresql, mysql, mongodb, redis, supabase
    host = Column(String(500), nullable=True)
    port = Column(Integer, nullable=True)
    environment_id = Column(Integer, ForeignKey("infra_environments.id", ondelete="SET NULL"), nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    backup_policy = Column(String(255), nullable=True)  # e.g., "daily, 7-day retention"
    linked_secret_ids = Column(Text, nullable=True)  # JSON array of secret IDs
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def to_dict(self):
        import json
        return {
            "id": self.id, "name": self.name, "db_type": self.db_type,
            "host": self.host, "port": self.port,
            "environment_id": self.environment_id, "owner_id": self.owner_id,
            "backup_policy": self.backup_policy,
            "linked_secret_ids": json.loads(self.linked_secret_ids) if self.linked_secret_ids else [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
```

**Commit:** `feat: add Asset, InfraService, InfraDatabase models`

---

### Task 6: Register models and run migration

**Objective:** Ensure all new models are registered so `metadata.create_all` creates the tables.

**Files:**
- Modify: `app/models/__init__.py`

**Steps:**
1. Add `from app.models.infrastructure import Environment, Secret, SecretVersion, SecretAccessLog, Asset, InfraService, InfraDatabase` to `__init__.py`
2. Restart the server — `Base.metadata.create_all(engine)` will create all 7 new tables
3. Verify: `psql -c "\dt infra_*"` — should show 7 tables

**Commit:** `feat: register infrastructure models, create tables`

---

### Task 7: Create infrastructure router — Environments CRUD

**Objective:** REST endpoints for environment management.

**Files:**
- Create: `app/routers/infrastructure.py`

**Endpoints:**
- `GET /projects/{project_id}/infra/environments` — list environments (for current tenant)
- `POST /projects/{project_id}/infra/environments` — create environment
- `PUT /infra/environments/{id}` — update environment
- `DELETE /infra/environments/{id}` — delete environment

**Notes:**
- All endpoints use `get_current_tenant` for tenant isolation
- All use `get_current_user` for auth
- Create/update requires owner/admin role
- Standard pattern matching existing routers (e.g., `clients.py`)

**Commit:** `feat: add environments CRUD endpoints`

---

### Task 8: Create infrastructure router — Secrets CRUD + Reveal + Rotate

**Objective:** REST endpoints for secret management with encryption, reveal, and rotation.

**Files:**
- Modify: `app/routers/infrastructure.py`

**Endpoints:**
- `GET /projects/{project_id}/infra/secrets` — list secrets (masked values, never encrypted_value)
- `POST /projects/{project_id}/infra/secrets` — create secret (encrypt value, create version 1, log access)
- `PUT /infra/secrets/{id}` — update secret (encrypt new value, increment version, log access)
- `DELETE /infra/secrets/{id}` — delete secret (log access)
- `GET /infra/secrets/{id}/reveal` — reveal decrypted value (log access with action="reveal")
- `POST /infra/secrets/{id}/rotate` — rotate secret (save old version, create new version, log access)
- `GET /infra/secrets/{id}/versions` — list version history
- `POST /infra/secrets/{id}/rollback` — rollback to a previous version (log access)
- `GET /infra/secrets/{id}/audit` — get access log for a secret

**Security controls:**
- Reveal endpoint returns decrypted value in response, never stores it
- Every access to `/reveal`, `/rotate`, `/rollback` is logged with user_id, action, timestamp
- List endpoint returns `••••••••` for all values — no decryption on list
- Only owner/admin can create/update/delete/rotate
- project_manager/member can view (masked) but not reveal
- Only owner/admin can reveal

**Commit:** `feat: add secrets CRUD with encryption, reveal, rotation, audit`

---

### Task 9: Create infrastructure router — Assets CRUD

**Objective:** REST endpoints for asset registry.

**Files:**
- Modify: `app/routers/infrastructure.py`

**Endpoints:**
- `GET /projects/{project_id}/infra/assets` — list assets
- `POST /projects/{project_id}/infra/assets` — create asset
- `PUT /infra/assets/{id}` — update asset
- `DELETE /infra/assets/{id}` — delete asset

**Commit:** `feat: add assets CRUD endpoints`

---

### Task 10: Create infrastructure router — Services + Databases CRUD

**Objective:** REST endpoints for services and databases registries.

**Files:**
- Modify: `app/routers/infrastructure.py`

**Endpoints:**
- `GET/POST /projects/{project_id}/infra/services` — list/create services
- `PUT/DELETE /infra/services/{id}` — update/delete services
- `GET/POST /projects/{project_id}/infra/databases` — list/create databases
- `PUT/DELETE /infra/databases/{id}` — update/delete databases

**Commit:** `feat: add services and databases CRUD endpoints`

---

### Task 11: Create infrastructure overview dashboard endpoint

**Objective:** Single endpoint returning counts and summary data for the infra dashboard.

**Files:**
- Modify: `app/routers/infrastructure.py`

**Endpoint:**
- `GET /projects/{project_id}/infra/overview` — returns:
  - environment_count, secret_count, asset_count, service_count, database_count
  - expiring_secrets (secrets with expires_at within 30 days)
  - recent_activity (last 10 secret access logs)
  - assets_by_type, secrets_by_category (for charts/distribution)

**Commit:** `feat: add infrastructure overview dashboard endpoint`

---

### Task 12: Register router in main.py

**Objective:** Wire the infrastructure router into the FastAPI app.

**Files:**
- Modify: `app/main.py`

**Steps:**
1. Add `from app.routers import infrastructure` to imports
2. Add `app.include_router(infrastructure.router)` after the other routers

**Commit:** `feat: register infrastructure router`

---

### Task 13: Add infrastructure nav items to frontend

**Objective:** Add "Infrastructure" section to the sidebar navigation.

**Files:**
- Modify: `app/templates/index.html`

**Changes:**
1. Add nav items after the existing project nav items:
   ```javascript
   { id: 'infrastructure', label: 'Infrastructure', group: 'project', icon: 'server' },
   ```
   Sub-items (shown when infrastructure is active):
   ```javascript
   { id: 'infra-assets', label: 'Assets', group: 'infra', icon: 'box' },
   { id: 'infra-secrets', label: 'Secrets', group: 'infra', icon: 'key' },
   { id: 'infra-environments', label: 'Environments', group: 'infra', icon: 'globe' },
   { id: 'infra-services', label: 'Services', group: 'infra', icon: 'cloud' },
   { id: 'infra-databases', label: 'Databases', group: 'infra', icon: 'database' },
   ```

2. Add route handling in `navigate()` for infrastructure routes
3. Add data properties: `infraEnvironments`, `infraSecrets`, `infraAssets`, `infraServices`, `infraDatabases`, `infraOverview`
4. Add `loadInfrastructure()` method that calls the overview endpoint + loads all sub-lists
5. Call `loadInfrastructure()` in `openProject()` alongside the existing `loadReleases()`, `loadBacklog()`, etc.

**Commit:** `feat: add infrastructure sidebar navigation`

---

### Task 14: Build infrastructure overview dashboard UI

**Objective:** Dashboard page with summary cards and recent activity.

**Files:**
- Modify: `app/templates/index.html`

**Content:**
- 5 stat cards: Environments, Secrets, Assets, Services, Databases (with counts)
- "Expiring Secrets" alert card (shows secrets expiring within 30 days, yellow/red)
- "Recent Activity" feed (last 10 audit log entries: who did what when)
- Distribution mini-charts: assets by type, secrets by category

**Commit:** `feat: add infrastructure overview dashboard UI`

---

### Task 15: Build Environments UI

**Objective:** Environments table with inline add (button-first pattern).

**Files:**
- Modify: `app/templates/index.html`

**Content:**
- Table: Name, Type (badge), URL, Owner, Status, Actions (edit, delete)
- Add button + toggle form (button-first pattern): Name, Type (select), URL, Description, Owner, Status
- Edit inline in same modal

**Commit:** `feat: add environments management UI`

---

### Task 16: Build Secrets UI

**Objective:** Secrets table with add/edit modal, masked values, reveal button, version history.

**Files:**
- Modify: `app/templates/index.html`

**Content:**
- Table: Name, Category (badge), Environment, Status, Version, Expires, Actions
- Add button + toggle form: Name, Category (select), Environment (select), Value (password input), Description, Owner, Expires At
- Edit modal: same fields + "Reveal Value" button (calls reveal endpoint, shows value for 30 seconds, then re-masks)
- "Rotate" button in edit modal (prompts for new value, creates new version)
- "Version History" expandable section showing all versions with timestamp and who created
- "Rollback" button on each version
- "Audit Log" expandable section showing access history
- Category badges with colors: database=blue, authentication=violet, ai_providers=indigo, email=amber, storage=emerald, payments=rose, monitoring=cyan, custom=gray

**Security UI:**
- Value field is type=password in form
- Reveal button shows decrypted value in a monospace box that auto-hides after 30 seconds (setTimeout)
- No copy button (to discourage casual copying) — or a copy button that logs the action

**Commit:** `feat: add secrets management UI with reveal, rotation, version history`

---

### Task 17: Build Assets UI

**Objective:** Asset registry table with add/edit modal.

**Files:**
- Modify: `app/templates/index.html`

**Content:**
- Table: Name, Type (badge), Environment, Project, Owner, Team, Status, Monthly Cost, Actions
- Filter by type, environment, status
- Add button + toggle form: Name, Type (select), Environment (select), Project (select), Owner (select), Team, Status, Metadata (key-value JSON editor or textarea), Monthly Cost
- Asset type badges with icons/colors: server=blue, vps=cyan, gpu_cluster=violet, database=emerald, domain=amber, api=indigo, certificate=rose, service=teal, other=gray

**Commit:** `feat: add asset registry UI`

---

### Task 18: Build Services + Databases UI

**Objective:** Services and databases tables with add/edit modals.

**Files:**
- Modify: `app/templates/index.html`

**Services table:**
- Name, Type (badge), Environment, Owner, Status, Linked Secrets (count), Actions
- Add form: Name, Type (select), Environment (select), Owner, Status, Documentation URL, Linked Secrets (multi-select from secrets list)

**Databases table:**
- Name, Type (badge), Host:Port, Environment, Owner, Backup Policy, Linked Secrets (count), Actions
- Add form: Name, Type (select), Host, Port, Environment (select), Owner, Backup Policy, Linked Secrets (multi-select)

**Commit:** `feat: add services and databases UI`

---

### Task 19: Seed sample data

**Objective:** Add sample infrastructure data for testing.

**Steps:**
1. Create a Python script `scripts/seed_infrastructure.py` that:
   - Creates 3 environments (Development, Staging, Production)
   - Creates 5 secrets (database password, OpenAI API key, Resend API key, Cloudflare API key, JWT secret)
   - Creates 4 assets (API server, database server, GPU cluster, wildcard SSL cert)
   - Creates 3 services (OpenAI, Resend, Cloudflare)
   - Creates 2 databases (PostgreSQL production, Redis cache)
2. Run the seed script
3. Verify all data loads correctly in the UI

**Commit:** `feat: seed sample infrastructure data`

---

### Task 20: Test and verify

**Objective:** End-to-end testing of all infrastructure features.

**Test cases:**
1. Navigate to Infrastructure → Overview — dashboard loads with counts
2. Environments: add, edit, delete an environment
3. Secrets:
   - Create a secret — value is masked in table
   - Reveal a secret — decrypted value shows for 30 seconds
   - Rotate a secret — new version created, old version in history
   - Rollback to previous version — value reverts
   - View audit log — shows all actions (create, reveal, rotate, rollback)
4. Assets: add, edit, delete an asset with metadata
5. Services: add a service, link secrets to it
6. Databases: add a database, link secrets to it
7. Verify tenant isolation — secrets from tenant A not visible to tenant B

**Commit:** `test: verify infrastructure module end-to-end`

---

## File Summary

### New files
| File | Purpose |
|------|---------|
| `app/models/infrastructure.py` | All 7 infra models (Environment, Secret, SecretVersion, SecretAccessLog, Asset, InfraService, InfraDatabase) |
| `app/routers/infrastructure.py` | All infra CRUD endpoints + secrets reveal/rotate/rollback/audit |
| `app/services/encryption.py` | Fernet encrypt/decrypt/mask utilities |
| `scripts/seed_infrastructure.py` | Sample data seeding |

### Modified files
| File | Changes |
|------|---------|
| `requirements.txt` | Add `cryptography` |
| `app/models/__init__.py` | Register 7 new models |
| `app/main.py` | Register infrastructure router |
| `app/templates/index.html` | Nav items, 5 new route views, data properties, methods |

---

## Risks & Tradeoffs

1. **Encryption key management:** Using a single master key from env var is simple but not as secure as per-tenant keys. Phase 2 could add per-tenant key derivation. For now, the key should be set in `.env` and never committed.

2. **Secret reveal in browser:** The decrypted value travels over HTTP to the browser. In production, HTTPS mitigates this. The 30-second auto-hide limits exposure but doesn't prevent screenshots. Audit logging provides traceability.

3. **No RBAC granularity yet:** The BRD defines 5 roles (System Admin, DevOps Engineer, Technical Lead, Developer, Project Manager). The current plan uses existing PMO roles (owner/admin/member). Mapping to infra-specific roles can be added in Phase 2.

4. **Single-file models:** Putting all 7 models in one `infrastructure.py` file keeps it manageable (~200 lines). If it grows, it can be split.

5. **index.html size:** Already ~9300 lines. Adding ~5 new views will add ~800-1000 lines. Still manageable but approaching the limit where splitting the template would be advisable.

---

## Open Questions

1. **Should infrastructure be project-scoped or tenant-scoped?** The BRD mentions "Every asset must have: Owner, Team, Project, Environment" — suggesting project-scoped. But environments and secrets are often shared across projects within a tenant. **Proposed:** Environments and Secrets are tenant-scoped (accessible from any project). Assets, Services, and Databases can optionally link to a project but are also tenant-scoped. The infrastructure section appears at the project level in the sidebar but shows tenant-wide data filtered by the current project context.

2. **Secret categories — should the list be configurable?** The BRD defines 8 categories. For Phase 1, these are hardcoded. Phase 2 could allow tenant admins to add custom categories.

3. **Should we show infrastructure in the main project sidebar or as a separate top-level section?** **Proposed:** Project-level sidebar item, since assets link to projects and it's contextual to the current project.

4. **Rate limiting on reveal endpoint?** The BRD doesn't mention it, but to prevent abuse, the reveal endpoint could be rate-limited (e.g., 10 reveals per minute per user). **Proposed:** Use the existing rate limiter middleware.

---

## Implementation Order

```
Task 1:  cryptography dependency
Task 2:  encryption service
Task 3:  Environment model
Task 4:  Secret + SecretVersion + SecretAccessLog models
Task 5:  Asset + InfraService + InfraDatabase models
Task 6:  Register models + migration
Task 7:  Environments CRUD
Task 8:  Secrets CRUD + reveal + rotate
Task 9:  Assets CRUD
Task 10: Services + Databases CRUD
Task 11: Overview dashboard endpoint
Task 12: Register router
Task 13: Nav items + data properties
Task 14: Overview dashboard UI
Task 15: Environments UI
Task 16: Secrets UI (most complex — reveal, rotate, versions, audit)
Task 17: Assets UI
Task 18: Services + Databases UI
Task 19: Seed sample data
Task 20: Test and verify
```

Backend first (Tasks 1-12), then frontend (Tasks 13-18), then seed + test (Tasks 19-20).

Each task is independently committable. The backend can be tested via curl before the UI is built.

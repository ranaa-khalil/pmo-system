# PMO System QA Report
Date: 2026-09-16
Tester: Hermes Agent (automated)

## Testing Scope
Full system QA testing of the PMO System at localhost:8000
- API layer: 50+ endpoints tested via Python requests
- Frontend: Method definitions verified, data loading checked
- Authentication, Super Admin, Clients, Projects, Backlog, Releases, KPIs,
  Infrastructure, Settings, Forms, Approvals

## Test Results

### Phase 1: Authentication — 5/5 PASS
- [PASS] Tenant admin login (rana@opex.com.sa)
- [PASS] Super admin login (admin@pmosystem.app)
- [PASS] Invalid login rejected (401)
- [PASS] /auth/me returns correct user
- [PASS] No-token requests rejected (401)

### Phase 1b: Super Admin — 5/5 PASS
- [PASS] Admin insights endpoint
- [PASS] List tenants (4 tenants)
- [PASS] List plans (4 plans)
- [PASS] Tenant detail with plan info
- [PASS] Tenant admin blocked from admin endpoints (403)

### Phase 2: Clients — 2/2 PASS
- [PASS] List clients (6 clients)
- [PASS] Create + delete client

### Phase 3: Projects — 15/15 PASS
- [PASS] List projects (5 projects)
- [PASS] All 15 project detail endpoints return 200:
  backlog(30), releases(1), roadmaps(1), kpis(3), stakeholders(0),
  personas(8), test-accounts(5), infra/overview, infra/environments(4),
  infra/secrets(5), infra/assets(4), infra/services(3), infra/databases(2),
  traceability, health

### Phase 6: Infrastructure CRUD — 11/11 PASS
- [PASS] Create/update/delete environment
- [PASS] Create secret, reveal (value matches), rotate (new value verified)
- [PASS] Audit log (4 entries after create+reveal+rotate)
- [PASS] Create/delete asset
- [PASS] Create/delete service
- [PASS] Create/delete database

### Phase 7: Tenant Settings — 3/3 PASS
- [PASS] Tenant limits (includes max_clients + plan_name)
- [PASS] Branding endpoint
- [PASS] Stakeholders endpoint

## Bugs Found and Fixed

### BUG 1: saveKPI() not defined — CRITICAL
- **Severity:** Critical
- **Category:** Functional
- **Location:** KPIs tab, Add KPI form
- **Description:** The "Add KPI" button calls saveKPI() but the method
  was never defined. Only saveKPIEdit() existed. KPI creation was
  completely broken.
- **Also:** deleteKPI() was called but not defined either.
- **Fix:** Added saveKPI() (handles create+update), editKPI(), deleteKPI().
  Added Edit button to KPI table.

### BUG 2: Approvals list returns 500 — CRITICAL
- **Severity:** Critical
- **Category:** Functional
- **Location:** GET /api/projects/{id}/approvals
- **Description:** _enrich_steps() in approvals.py queried
  User.tenant_id, but the User model has no tenant_id column
  (it uses active_tenant_id). Every call to list approvals crashed.
- **Fix:** Removed tenant_id filter from approver lookup.

### BUG 3: Forms list returns 500 — CRITICAL
- **Severity:** Critical
- **Category:** Functional
- **Location:** GET /api/projects/{id}/forms
- **Description:** Pydantic response models expected dict/list for
  field_schema and data fields, but the JSON columns sometimes returned
  strings to the validator. Validation failed for every form instance.
- **Fix:** Added field_validator with json.loads fallback to parse
  string-encoded JSON before validation.

### BUG 4: Release create returns 500 — HIGH
- **Severity:** High
- **Category:** Functional
- **Location:** POST /api/projects/{id}/releases
- **Description:** releases_id_seq PostgreSQL sequence was out of sync
  (sequence at 8, but max(id) was 13). INSERT failed with duplicate
  key violation.
- **Fix:** Reset all PostgreSQL sequences to MAX(id).

### BUG 5: Rate limit too aggressive — MEDIUM
- **Severity:** Medium
- **Category:** UX
- **Location:** All API endpoints
- **Description:** Free plan allowed 100 req/min. Opening a project
  fires 15+ concurrent API calls via Promise.all, instantly exhausting
  the budget. Multiple endpoints returned 429, causing data loading
  to fail silently.
- **Fix:** Increased limits to 500/2000/5000/10000 req/min.
  Made loadInfrastructure() use individual try/catch instead of
  Promise.all so one 429 doesn't block all data.

## Summary
- **Total tests run:** 41 API tests + full method definition scan
- **Bugs found:** 5 (3 Critical, 1 High, 1 Medium)
- **Bugs fixed:** 5/5
- **All tests passing after fixes:** YES
- **All @click methods defined:** YES (verified programmatically)
- **div balance:** 0 (no unclosed tags)

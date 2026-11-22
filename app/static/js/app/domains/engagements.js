// PMO System — app/engagements.js
// Engagements domain of the Alpine pmoApp() store.
// Rethink v2 Phase B3: the engagement account review on client detail — the
// first UI over the shipped engagements API (routers/engagements.py —
// GET /engagements?client_id=, GET /engagements/{id} with the projects
// rollup, GET /projects/{id}/health). Render-only: the consultant's unit of
// work is client → engagement → projects, so opening a client shows every
// engagement, the rollup and per-project health with why — zero search
// fields. Engagement create/edit are later slices; nothing writes here.

export const engagements = {

// ===== Engagements state (Rethink v2 Phase B3) =====
clientEngagements: [],       // GET /api/engagements?client_id= — newest first,
                             // each row hydrated with the detail's projects rollup
engagementsLoading: false,
engagementHealth: {},        // project id → GET /api/projects/{id}/health
                             // (composite + why + gate_aging) — lazy per project card

// Lazy loader: the client-detail view fetches engagements when it first
// shows (x-effect on the view root — never part of the openProject burst).
// One list call scoped to the client (?client_id=), then the projects rollup
// per engagement (it lives on the detail endpoint) and per-project health
// behind it. A client has few engagements, so the fan-out stays small.
async loadClientEngagements() {
    if (!this.selectedClient) return;
    this.engagementsLoading = true;
    try {
        const rows = (await this.api('GET', `/engagements?client_id=${this.selectedClient.id}&per_page=200`)).engagements || [];
        this.clientEngagements = rows;
        // pmo_lead_id renders as a name — the pool loads once (fire-and-forget;
        // loadUsers catches its own failures)
        if (this.users.length === 0) this.loadUsers().catch(() => {});
        // The rollup lives on GET /engagements/{id} — hydrate every card.
        await Promise.all(rows.map(r => this.loadEngagementDetail(r.id)));
    } catch (e) { console.error('loadClientEngagements', e); this.clientEngagements = []; }
    this.engagementsLoading = false;
},

// One engagement's detail: keeps the list row in sync (the sync adds the
// projects rollup) and fetches the health of each wrapped project.
async loadEngagementDetail(id) {
    try {
        const row = await this.api('GET', `/engagements/${id}`);
        const i = this.clientEngagements.findIndex(x => x.id === id);
        if (i !== -1) this.clientEngagements.splice(i, 1, row); else this.clientEngagements.unshift(row);
        await Promise.all((row.projects?.items || []).map(p => this.loadEngagementProjectHealth(p.id)));
    } catch { /* the list row stays — the rollup/health chips stay hidden */ }
},

// Per-project health: one GET /api/projects/{id}/health per wrapped project,
// keyed by id (lazy-once: the same project reuses its payload this session,
// the coverage guard pattern). Failures leave that project's chips hidden.
async loadEngagementProjectHealth(projectId) {
    if (!projectId || this.engagementHealth[projectId]) return;
    try {
        const health = await this.api('GET', `/projects/${projectId}/health`);
        // Spread-replace: a new key assignment stays reactive on the store.
        this.engagementHealth = { ...this.engagementHealth, [projectId]: health };
    } catch { /* chips stay hidden for this project */ }
},

// Chip class maps — literal strings (the css-coverage guard requires literal
// class strings; the house pattern is the mapping table). Lifecycle:
// active = emerald, paused = amber, closed = ink.
engagementStatusChipClass(status) {
    const map = {
        active: 'bg-emerald-50 text-emerald-600',
        paused: 'bg-amber-50 text-amber-600',
        closed: 'bg-ink-100 text-ink-500',
    };
    return map[status] || map.closed;
},

engagementStatusDotClass(status) {
    const map = {
        active: 'bg-emerald-400',
        paused: 'bg-amber-400',
        closed: 'bg-ink-300',
    };
    return map[status] || map.closed;
},

// pmo_lead_id is a user id — map from the users pool, else the id.
engagementLead(leadId) {
    if (!leadId) return '—';
    const u = (this.users || []).find(x => x.id === leadId);
    return u ? u.name : 'User #' + leadId;
},

// Engagement dates are ISO strings — short human date; unparseable values
// render verbatim.
engagementDate(d) {
    if (!d) return '';
    const date = new Date(d);
    if (isNaN(date.getTime())) return d;
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
},

};

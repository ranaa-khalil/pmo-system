// PMO System — app/decisions.js
// Decisions domain of the Alpine pmoApp() store.
// Rethink v2 Phase B1: the first-class UI over the shipped decision-records
// API (routers/decisions.py — POST/GET /decisions, GET/PUT /decisions/{id},
// POST /decisions/{id}/supersede, DELETE). Search hits the server (?q=),
// source/status chips filter the loaded page client-side, and every write
// goes through the same endpoints the API tests prove behave
// (tests/test_routers/test_decisions_api.py).

export const decisions = {

// ===== Decisions state (Rethink v2 Phase B1) =====
decisions: [],
decisionsLoading: false,
decisionsLoaded: false,
decisionSearch: '',
decisionProjectFilter: '',      // '' = all projects (server ?project_id=)
decisionSourceFilter: 'all',    // 'all' | 'manual' | 'gate' | 'ai' — chips-not-tabs
decisionStatusFilter: 'all',    // 'all' | 'active' | 'superseded' — chips-not-tabs
decisionSearchTimer: null,
selectedDecision: null,
decisionDetail: null,
decisionDetailLoading: false,
decisionEdit: false,
decisionEditForm: { title: '', decision: '', rationale: '', alternatives: '' },
decisionNew: false,
decisionNewForm: { title: '', decision: '', rationale: '', alternatives: '', project_id: null, source: 'manual' },
decisionSupersedeOpen: false,
decisionSupersedeForm: { title: '', decision: '', rationale: '' },
decisionPredecessor: null,      // chained_from_id record (lineage)
decisionApproval: null,         // the linked approval request (lineage)

// Source/status chips filter the loaded page client-side — the API has no
// status/source query params; search (q=) and project (project_id=) are
// server-side.
get filteredDecisions() {
    let items = this.decisions;
    if (this.decisionSourceFilter !== 'all') {
        items = items.filter(d => (d.source || 'manual') === this.decisionSourceFilter);
    }
    if (this.decisionStatusFilter !== 'all') {
        items = items.filter(d => (d.status || 'active') === this.decisionStatusFilter);
    }
    return items;
},

get decisionSuccessors() {
    const d = this.decisionDetail || this.selectedDecision;
    if (!d) return [];
    return this.decisions.filter(x => x.chained_from_id === d.id);
},

async loadDecisions() {
    this.decisionsLoading = true;
    try {
        const params = [];
        if (this.decisionSearch.trim()) params.push(`q=${encodeURIComponent(this.decisionSearch.trim())}`);
        if (this.decisionProjectFilter) params.push(`project_id=${this.decisionProjectFilter}`);
        params.push('per_page=200');
        const qs = `?${params.join('&')}`;
        this.decisions = (await this.api('GET', `/decisions${qs}`)).decisions || [];
        this.decisionsLoaded = true;
        // made_by renders as a name — the pool loads once (fire-and-forget;
        // loadUsers catches its own failures)
        if (this.users.length === 0) this.loadUsers().catch(() => {});
    } catch (e) { console.error('loadDecisions', e); this.decisions = []; }
    this.decisionsLoading = false;
},

// Search input (server q= across title/decision/rationale) — debounced.
onDecisionSearchInput() {
    clearTimeout(this.decisionSearchTimer);
    this.decisionSearchTimer = setTimeout(() => this.loadDecisions(), 300);
},

setDecisionProjectFilter(value) {
    this.decisionProjectFilter = value;
    this.loadDecisions();
},

setDecisionSourceFilter(source) { this.decisionSourceFilter = source; },

setDecisionStatusFilter(status) { this.decisionStatusFilter = status; },

clearDecisionFilters() {
    this.decisionSearch = '';
    this.decisionProjectFilter = '';
    this.decisionSourceFilter = 'all';
    this.decisionStatusFilter = 'all';
    this.loadDecisions();
},

// Chip class maps — literal strings (the css-coverage guard requires literal
// class strings; the house pattern is the mapping table: tagChipClass,
// avatarColor, itemTypeColor).
decisionSourceChipClass(source) {
    const map = {
        manual: 'bg-ink-100 text-ink-600',
        gate: 'bg-emerald-50 text-emerald-700',
        ai: 'bg-violet-50 text-violet-700',
    };
    return map[source] || map.manual;
},

decisionStatusChipClass(status) {
    const map = {
        active: 'bg-emerald-50 text-emerald-600',
        superseded: 'bg-amber-50 text-amber-700',
    };
    return map[status] || map.active;
},

// Project name from the already-loaded projects pool (the list rows carry
// project_id only — the name maps client-side).
decisionProjectName(projectId) {
    if (!projectId) return '';
    const p = (this.projects || []).find(x => x.id === projectId);
    return p ? p.name : '';
},

// made_by is a user id — map from the users pool, then the session user,
// then a readable fallback.
decisionMadeBy(userId) {
    if (!userId) return '—';
    const u = (this.users || []).find(x => x.id === userId);
    if (u) return u.name;
    if (this.currentUser && this.currentUser.id === userId) return this.currentUser.name;
    return 'User #' + userId;
},

decisionDate(d) {
    if (!d) return '';
    const date = new Date(d);
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
},

// ===== Drawer (slide-over — the item-drawer pattern) =====
async openDecision(d) {
    this.selectedDecision = d;
    this.decisionDetail = d;
    this.decisionEdit = false;
    this.decisionNew = false;
    this.decisionSupersedeOpen = false;
    this.decisionPredecessor = null;
    this.decisionApproval = null;
    await this.loadDecisionDetail(d.id);
},

async openDecisionById(id) {
    if (!id) return;
    this.decisionEdit = false;
    this.decisionNew = false;
    this.decisionSupersedeOpen = false;
    this.decisionPredecessor = null;
    this.decisionApproval = null;
    this.selectedDecision = { id };
    await this.loadDecisionDetail(id);
    if (!this.decisionDetail || this.decisionDetail.id !== id) this.closeDecision();
},

async loadDecisionDetail(id) {
    this.decisionDetailLoading = true;
    try {
        const row = await this.api('GET', `/decisions/${id}`);
        this.decisionDetail = row;
        // Keep the list row in sync (edits/supersede flow back through here)
        const i = this.decisions.findIndex(x => x.id === row.id);
        if (i !== -1) this.decisions.splice(i, 1, row); else this.decisions.unshift(row);
        // Lineage: the chained predecessor and the linked approval request
        if (row.chained_from_id) {
            const inList = this.decisions.find(x => x.id === row.chained_from_id);
            if (inList) {
                this.decisionPredecessor = inList;
            } else {
                try { this.decisionPredecessor = await this.api('GET', `/decisions/${row.chained_from_id}`); }
                catch { this.decisionPredecessor = null; }
            }
        }
        if (row.approval_request_id) {
            try { this.decisionApproval = await this.api('GET', `/approvals/${row.approval_request_id}`); }
            catch { this.decisionApproval = null; }
        }
    } catch (e) { console.error('loadDecisionDetail', e); }
    this.decisionDetailLoading = false;
},

closeDecision() {
    this.selectedDecision = null;
    this.decisionDetail = null;
    this.decisionEdit = false;
    this.decisionNew = false;
    this.decisionSupersedeOpen = false;
    this.decisionPredecessor = null;
    this.decisionApproval = null;
},

// The linked approval request lives in its project's detail — jump there.
openApprovalProject() {
    const a = this.decisionApproval;
    if (!a || !a.project_id) return;
    const p = (this.projects || []).find(x => x.id === a.project_id);
    if (p) { this.closeDecision(); this.openProject(p); }
},

// The linked backlog item's drawer lives inside the Work view — route there
// first, then open it (openItemRef fetches the item when it is not loaded).
openDecisionItem() {
    const id = this.decisionDetail?.item_id;
    if (!id) return;
    this.closeDecision();
    this.navigate('work');
    this.openItemRef(id);
},

// ===== Create (POST /decisions → 201) =====
startNewDecision() {
    this.selectedDecision = null;
    this.decisionDetail = null;
    this.decisionEdit = false;
    this.decisionNew = true;
    this.decisionSupersedeOpen = false;
    this.decisionPredecessor = null;
    this.decisionApproval = null;
    // Preselect the project filter if one is active
    this.decisionNewForm = {
        title: '', decision: '', rationale: '', alternatives: '',
        project_id: this.decisionProjectFilter ? Number(this.decisionProjectFilter) : null,
        source: 'manual',
    };
},

async createDecision() {
    if (!this.decisionNewForm.title.trim() || !this.decisionNewForm.decision.trim()) return;
    const payload = { ...this.decisionNewForm };
    if (!payload.project_id) delete payload.project_id;
    try {
        const row = await this.api('POST', '/decisions', payload);
        this.decisionNewForm = { title: '', decision: '', rationale: '', alternatives: '', project_id: null, source: 'manual' };
        this.decisionNew = false;
        await this.loadDecisions();
        this.showToast('Decision recorded', 'success');
        this.selectedDecision = row;
        this.decisionDetail = row;
    } catch (e) { this.showToast(e.message || 'Failed to record decision', 'error'); }
},

// ===== Edit (content-only PUT — made_at/made_by are immutable by shape) =====
startDecisionEdit() {
    const d = this.decisionDetail || this.selectedDecision;
    if (!d) return;
    this.decisionEditForm = {
        title: d.title || '',
        decision: d.decision || '',
        rationale: d.rationale || '',
        alternatives: d.alternatives || '',
    };
    this.decisionEdit = true;
},

async saveDecisionEdit() {
    const d = this.decisionDetail || this.selectedDecision;
    if (!d || !this.decisionEditForm.title.trim() || !this.decisionEditForm.decision.trim()) return;
    try {
        const row = await this.api('PUT', `/decisions/${d.id}`, {
            title: this.decisionEditForm.title,
            decision: this.decisionEditForm.decision,
            rationale: this.decisionEditForm.rationale || null,
            alternatives: this.decisionEditForm.alternatives || null,
        });
        this.decisionDetail = row;
        this.decisionEdit = false;
        const i = this.decisions.findIndex(x => x.id === row.id);
        if (i !== -1) this.decisions.splice(i, 1, row);
        this.showToast('Decision updated', 'success');
    } catch (e) { this.showToast(e.message || 'Failed to save decision', 'error'); }
},

// ===== Supersede (POST /decisions/{id}/supersede → 201; the successor
// carries chained_from_id and the old record is marked superseded) =====
startSupersede() {
    const d = this.decisionDetail || this.selectedDecision;
    if (!d) return;
    this.decisionSupersedeForm = { title: `${d.title} (v2)`, decision: '', rationale: '' };
    this.decisionSupersedeOpen = true;
    this.decisionEdit = false;
},

async confirmSupersede() {
    const d = this.decisionDetail || this.selectedDecision;
    if (!d || !this.decisionSupersedeForm.decision.trim()) return;
    try {
        const successor = await this.api('POST', `/decisions/${d.id}/supersede`, {
            title: this.decisionSupersedeForm.title.trim() || d.title,
            decision: this.decisionSupersedeForm.decision,
            rationale: this.decisionSupersedeForm.rationale || null,
        });
        this.decisionSupersedeOpen = false;
        this.decisionSupersedeForm = { title: '', decision: '', rationale: '' };
        await this.loadDecisions();
        this.showToast('Decision superseded — both entries are chained', 'success');
        // Open the successor so the user sees the new link
        this.selectedDecision = successor;
        this.decisionDetail = successor;
        this.decisionPredecessor = this.decisions.find(x => x.id === successor.chained_from_id) || null;
    } catch (e) { this.showToast(e.message || 'Failed to supersede', 'error'); }
},

// ===== Delete (permission-gated — the API 403s without can_manage_project;
// the message is surfaced, nothing else happens) =====
async deleteDecision() {
    const d = this.decisionDetail || this.selectedDecision;
    if (!d) return;
    if (!confirm('Delete this decision? The delete is recorded in the artifact chain.')) return;
    try {
        await this.api('DELETE', `/decisions/${d.id}`);
        this.decisions = this.decisions.filter(x => x.id !== d.id);
        this.closeDecision();
        this.showToast('Decision deleted', 'success');
    } catch (e) { this.showToast(e.message || 'Failed to delete decision', 'error'); }
},

};

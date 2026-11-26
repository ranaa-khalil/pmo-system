// PMO System — app/projects.js
// Projects domain of the Alpine pmoApp() store.
// Fragments are verbatim from the original monolith; pmo-app.js assembles them.

export const projects = {
// ===== Tenant branding =====
tenantBranding: window.__TENANT_BRANDING || null,
settingsTab: 'personal',
tenantBrandingForm: { app_name: '', primary_color: '#7c3aed', logo_url: '', hide_powered_by: false },
tenantLimitsForm: { max_users: 999999, max_projects: 999999, max_clients: 999999 },
usageCurrent: { users: 0, projects: 0 },
loginLoading: false,
showRegister: false,


// ===== Stakeholders state =====
projectStakeholders: [],
personas: [],
testAccounts: [],
envEditMode: false,
envForm: { dev_url: '', uat_url: '', prod_url: '' },
personaModalOpen: false,
editingPersona: null,
testAccountModalOpen: false,
editingTestAccount: null,
projectAssignments: [],  // system users assigned to the project
reqUserSearch: {},  // per-role search text for required role autocomplete
reqUserFocused: null,  // which role's dropdown is open
reqUserResults: [],  // filtered results for required role autocomplete
stakeholderForm: { name: '', email: '', phone: '', company: '', role_name: 'Stakeholder', raci_type: 'I', notes: '' },
editingStakeholderId: null,  // set → the add form edits an existing stakeholder
editAssign: null,  // { id, role, name } → required-role change-assignee dropdown open


// ===== Roles state =====
roles: [],


// ===== Releases state =====
projectReleases: [],
selectedRelease: null,
releaseForm: { version: '', name: '', description: '', target_date: '', milestone_id: '' },
releaseStatuses: ['Planning', 'In Progress', 'Testing', 'UAT', 'Pre-Release', 'Released', 'Post-Release', 'Cancelled'],


// ===== User management state =====
users: [],
userForm: { name: '', email: '', password: '', system_role: 'member' },
assignmentForm: { user_id: '', role_id: '', project_id: '' },
amForm: { client_id: '', user_id: '' },
pmForm: { project_id: '', user_id: '' },


// ===== Roles =====
async loadRoles() {
    try {
        this.roles = await this.api('GET', '/roles');
        // Update raciRoles from DB
        this.raciRoles = this.roles.map(r => r.name);
    } catch { this.roles = []; }
},


// ===== Stakeholders =====
async loadStakeholders() {
    try {
        this.projectStakeholders = await this.api('GET', `/projects/${this.selectedProject.id}/stakeholders`);
        try { this.projectAssignments = await this.api('GET', `/projects/${this.selectedProject.id}/assignments`); } catch(e) { this.projectAssignments = []; }
    } catch { this.projectStakeholders = []; }
},

async saveStakeholder() {
    try {
        const editing = !!this.editingStakeholderId;
        if (editing) {
            await this.api('PUT', `/stakeholders/${this.editingStakeholderId}`, this.stakeholderForm);
        } else {
            await this.api('POST', `/projects/${this.selectedProject.id}/stakeholders`, this.stakeholderForm);
        }
        this.stakeholderForm = { name: '', email: '', phone: '', company: '', role_name: 'Stakeholder', raci_type: 'I', notes: '' };
        this.editingStakeholderId = null;
        this.showStakeholderForm = false;
        await this.loadStakeholders();
        this.showToast(editing ? 'Stakeholder updated' : 'Stakeholder added', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

startEditStakeholder(s) {
    // Edit inline in the same add form (view → edit on one surface)
    this.editingStakeholderId = s.id;
    this.stakeholderForm = {
        name: s.name || '', email: s.email || '', phone: s.phone || '',
        company: s.company || '', role_name: s.role_name || 'Stakeholder',
        raci_type: s.raci_type || 'I', notes: s.notes || '',
    };
    this.showStakeholderForm = true;
},

cancelEditStakeholder() {
    this.editingStakeholderId = null;
    this.stakeholderForm = { name: '', email: '', phone: '', company: '', role_name: 'Stakeholder', raci_type: 'I', notes: '' };
    this.showStakeholderForm = false;
},

async updateAssignmentRole(assignmentId, roleId) {
    // Team-member chip: change the RACI role in place
    if (!roleId) return;
    try {
        await this.api('PUT', `/assignments/${assignmentId}`, { role_id: parseInt(roleId) });
        await this.loadStakeholders();
        this.showToast('Role updated', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

openEditAssign(a) {
    // Required-role card: open change-assignee dropdown seeded with the current assignee.
    // Template passes { id, role, name } — read role from a.role (fall back to role_name).
    const role = a.role || a.role_name;
    const asg = (this.projectAssignments || []).find(x => x.id === a.id);
    this.editAssign = { id: a.id, role, name: a.name, user_id: asg ? asg.user_id : null };
    this.reqUserSearch[role] = '';
    this.filterReqUsers(role);
    // Open the panel immediately — don't wait for the input's @focus
    this.reqUserFocused = role;
},

async changeAssignee(a, userId) {
    // Required-role card: swap the assigned user, keep the role
    if (!userId) return;
    this.editAssign = null;
    try {
        await this.api('PUT', `/assignments/${a.id}`, { user_id: parseInt(userId) });
        this.projectAssignments = await this.api('GET', `/projects/${this.selectedProject.id}/assignments`);
        this.showToast('Assignee updated', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

async deleteStakeholder(id) {
    try {
        await this.api('DELETE', `/stakeholders/${id}`);
        await this.loadStakeholders();
        this.showToast('Stakeholder removed', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

raciColor(type) {
    return {
        'R': 'bg-blue-100 text-blue-700',
        'A': 'bg-emerald-100 text-emerald-700',
        'C': 'bg-amber-100 text-amber-700',
        'I': 'bg-ink-100 text-ink-500',
    }[type] || 'bg-ink-100 text-ink-500';
},


// ===== Releases =====
async loadReleases() {
    try {
        this.projectReleases = await this.api('GET', `/projects/${this.selectedProject.id}/releases`);
    } catch { this.projectReleases = []; }
    // The drift banner reads the radar — a fresh release list refreshes it
    // while the Releases tab is showing (advance/save call loadReleases).
    if (this.route === 'project-detail' && this.projectTab === 'releases') this.loadDriftRadar(true);
},

// ===== Drift Radar (Rethink §3 #3) =====
// Deterministic per-release drift (schedule.py's plan-vs-target compute via
// GET /api/projects/{id}/releases/drift): the Releases tab banner and the
// Today Brief's Drift section read the same payload. The suggested move is
// rules-based — never LLM-authored.
driftRadar: null,           // {records: [{entity_id, drift_days, causing_items, suggested_move, ...}]}
driftRadarLoadedFor: null,  // project id already fetched (lazy-once guard)
driftRadarLoading: false,

async loadDriftRadar(force = false) {
    if (!this.selectedProject) return;
    if (!force && this.driftRadarLoadedFor === this.selectedProject.id) return;
    this.driftRadarLoading = true;
    try {
        this.driftRadar = await this.api('GET', `/projects/${this.selectedProject.id}/releases/drift`);
        this.driftRadarLoadedFor = this.selectedProject.id;
    } catch { this.driftRadar = null; }
    finally { this.driftRadarLoading = false; }
},

// The drift record for one release card (or null — no banner).
releaseDrift(releaseId) {
    return (this.driftRadar?.records || []).find(r => r.entity_id === releaseId) || null;
},

// Today Brief Drift section: a drifted release lands in its project at the
// Releases tab (the openOutcomeRecord pattern — open, then set the tab).
async openDriftRelease(row) {
    if (!row || !row.project_id) return;
    await this.openProjectRef(row.project_id, row.project_name);
    this.projectTab = 'releases';
},


// ===== Project KPI coverage (Rethink v2 Phase B2) =====
projectCoverage: null,      // GET /api/projects/{id}/coverage — the overview's lazy fetch
coverageLoadedFor: null,    // project id already fetched (lazy-once guard)
coverageLoading: false,

// ===== Coverage =====
async loadCoverage() {
    // Lazy loader: the overview fetches coverage the first time the tab shows
    // (x-effect on the overview section) — never part of the openProject burst.
    // One project loads it once; re-opening the same project reuses the payload.
    if (!this.selectedProject) return;
    if (this.coverageLoadedFor === this.selectedProject.id) return;
    this.coverageLoading = true;
    try {
        this.projectCoverage = await this.api('GET', `/projects/${this.selectedProject.id}/coverage`);
        this.coverageLoadedFor = this.selectedProject.id;
    } catch { this.projectCoverage = null; }
    finally { this.coverageLoading = false; }
},


// ===== User Management =====
async loadUsers() {
    try {
        this.users = await this.api('GET', '/users');
    } catch { this.users = []; }
},

};

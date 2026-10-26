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
        await this.api('POST', `/projects/${this.selectedProject.id}/stakeholders`, this.stakeholderForm);
        this.stakeholderForm = { name: '', email: '', phone: '', company: '', role_name: 'Stakeholder', raci_type: 'I', notes: '' };
        this.showStakeholderForm = false;
        await this.loadStakeholders();
        this.showToast('Stakeholder added', 'success');
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
},


// ===== User Management =====
async loadUsers() {
    try {
        this.users = await this.api('GET', '/users');
    } catch { this.users = []; }
},

};

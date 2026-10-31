// PMO System — app/tenants.js
// Tenants domain of the Alpine pmoApp() store.
// Fragments are verbatim from the original monolith; pmo-app.js assembles them.

export const tenants = {
// ===== Tenant state =====
currentTenant: null,
tenantEditForm: { name: '' },
tenantMembers: [],
inviteForm: { email: '', role: 'member' },
integrations: {},
integrationForm: { github_token: '', ai_api_key: '', ai_base_url: '', ai_model: '' },
usageMetrics: [],
// P4 automation + lifecycle state
automationRules: [],
automationScan: null,
lifecycleTemplates: [],
lifecycleTypes: [],
lifecycleForm: { project_type: '', name: '', description: '', item_phases: '', release_stages: '', fields_text: '' },
showLifecycleForm: false,


// ===== Super Admin state =====
allTenants: [],
adminInsights: null,
adminTab: 'dashboard',
adminPlans: [],
showCreateTenantForm: false,
showPlanForm: false,
editingPlanId: null,
planForm: { name: '', description: '', max_users: 3, max_projects: 1, max_clients: 5, price_monthly: 0, price_yearly: 0, is_active: true, sort_order: 0 },
selectedTenantDetail: null,
adminAddUserForm: { name: '', email: '', password: '', role: 'member' },
adminResetPasswordForm: { user_id: null, new_password: '' },
adminBrandingForm: { app_name: '', primary_color: '#7c3aed', logo_url: '', hide_powered_by: false },
newTenantForm: { tenant_name: '', owner_name: '', owner_email: '', owner_password: '', plan_id: '' },
newUserForm: { tenant_id: '', name: '', email: '', password: '', role: 'member' },
tenantCreateForm: { name: '', email: '', password: '', role: 'member' },
showAddUserForm: false,
projectHealth: null,


// ===== Tenant management methods =====
async loadTenant() {
    try {
        this.currentTenant = await this.api('GET', '/tenant');
        this.tenantEditForm.name = this.currentTenant.name || '';
        // Populate branding form
        const b = this.currentTenant?.branding || {};
        const logo = this.currentTenant?.logo_url || '';
        this.tenantBrandingForm = {
            app_name: b.app_name || '',
            primary_color: b.primary_color || '#7c3aed',
            logo_url: logo || b.logo_url || '',
            hide_powered_by: b.hide_powered_by || false,
        };
        // Sync tenantBranding so sidebar, login screen, and title update reactively
        this.tenantBranding = {
            app_name: b.app_name || '',
            primary_color: b.primary_color || '#7c3aed',
            logo_url: logo || b.logo_url || '',
            hide_powered_by: b.hide_powered_by || false,
            slug: this.currentTenant?.slug || '',
            name: this.currentTenant?.name || '',
        };
    } catch { this.currentTenant = null; }
},

async saveTenant() {
    try {
        await this.api('PUT', '/tenant', { name: this.tenantEditForm.name });
        await this.loadTenant();
        this.showToast('Tenant name updated', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

async saveTenantBranding() {
    try {
        await this.api('PUT', '/tenant/branding', this.tenantBrandingForm);
        await this.loadTenant();
        this.applyBranding();
        this.showToast('Branding saved', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

async loadTenantLimits() {
    try {
        const data = await this.api('GET', '/tenant/limits');
        this.tenantLimitsForm = {
            max_users: data.limits.max_users >= 999999 ? 999999 : data.limits.max_users,
            max_projects: data.limits.max_projects >= 999999 ? 999999 : data.limits.max_projects,
            max_clients: data.limits.max_clients >= 999999 ? 999999 : data.limits.max_clients,
        };
        this.usageCurrent = { ...data.current, plan_name: data.plan_name };
    } catch { /* ignore */ }
},

async uploadTenantLogo(event) {
    const file = event.target.files[0];
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) {
        this.showToast('Logo file too large (max 2 MB)', 'error');
        return;
    }
    const formData = new FormData();
    formData.append('file', file);
    try {
        const resp = await fetch('/api/tenant/logo', {
            method: 'POST',
            headers: { 'Authorization': 'Bearer ' + this.authToken },
            body: formData,
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.detail || 'Upload failed');
        }
        const data = await resp.json();
        this.tenantBrandingForm.logo_url = data.logo_url;
        await this.loadTenant();
        this.applyBranding();
        this.showToast('Logo uploaded', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

async adminUploadTenantLogo(event, tenantId) {
    const file = event.target.files[0];
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) {
        this.showToast('Logo file too large (max 2 MB)', 'error');
        return;
    }
    const formData = new FormData();
    formData.append('file', file);
    try {
        const resp = await fetch(`/api/admin/tenants/${tenantId}/logo`, {
            method: 'POST',
            headers: { 'Authorization': 'Bearer ' + this.authToken },
            body: formData,
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.detail || 'Upload failed');
        }
        const data = await resp.json();
        this.adminBrandingForm.logo_url = data.logo_url;
        await this.loadTenantDetail(tenantId);
        this.showToast('Logo uploaded', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

async loadMembers() {
    try {
        this.tenantMembers = await this.api('GET', '/tenant/members');
    } catch { this.tenantMembers = []; }
},

async inviteMember() {
    try {
        await this.api('POST', '/tenant/invite', this.inviteForm);
        this.inviteForm = { email: '', role: 'member' };
        await this.loadMembers();
        this.showToast('Invitation sent', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

async removeMember(userId) {
    if (!confirm('Remove this member from the workspace?')) return;
    try {
        await this.api('DELETE', `/api/tenant/members/${userId}`);
        await this.loadMembers();
        this.showToast('Member removed', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

async changeMemberRole(userId, newRole) {
    try {
        await this.api('PUT', `/tenant/members/${userId}?role=${newRole}`);
        await this.loadMembers();
        this.showToast('Role updated', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},


// ===== Super Admin methods =====
async loadAdminInsights() {
    try {
        this.adminInsights = await this.api('GET', '/admin/insights');
        this.allTenants = this.adminInsights?.tenants || [];
    } catch (e) { this.showToast('Failed to load insights', 'error'); }
},

async loadAdminPlans() {
    try {
        this.adminPlans = await this.api('GET', '/admin/plans');
    } catch (e) { this.showToast('Failed to load plans', 'error'); }
},

async createTenant() {
    try {
        await this.api('POST', '/admin/tenants', this.newTenantForm);
        this.newTenantForm = { tenant_name: '', owner_name: '', owner_email: '', owner_password: '', plan_id: '' };
        this.showCreateTenantForm = false;
        await this.loadAdminInsights();
        this.showToast('Tenant created', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

async createUserInTenant() {
    try {
        await this.api('POST', `/api/admin/tenants/${this.newUserForm.tenant_id}/users`, this.newUserForm);
        this.newUserForm = { tenant_id: '', name: '', email: '', password: '', role: 'member' };
        await this.loadAdminInsights();
        this.showToast('User created', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

async assignTenantPlan(tenantId, planId) {
    try {
        await this.api('PUT', `/admin/tenants/${tenantId}/plan`, { plan_id: parseInt(planId) });
        await this.loadAdminInsights();
        this.showToast('Plan assigned', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

async updateTenantStatus(tenantId, status) {
    try {
        await this.api('PUT', `/admin/tenants/${tenantId}/status?status=${status}`);
        await this.loadAdminInsights();
        if (this.selectedTenantDetail?.tenant?.id === tenantId) await this.loadTenantDetail(tenantId);
        this.showToast(`Status updated to ${status}`, 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

// ─── Plan Management ───

resetPlanForm() {
    this.planForm = { name: '', description: '', max_users: 3, max_projects: 1, max_clients: 5, price_monthly: 0, price_yearly: 0, is_active: true, sort_order: 0 };
    this.editingPlanId = null;
},

editPlan(plan) {
    this.editingPlanId = plan.id;
    this.planForm = {
        name: plan.name,
        description: plan.description || '',
        max_users: plan.max_users,
        max_projects: plan.max_projects,
        max_clients: plan.max_clients,
        price_monthly: plan.price_monthly,
        price_yearly: plan.price_yearly,
        is_active: plan.is_active,
        sort_order: plan.sort_order,
    };
    this.showPlanForm = true;
},

async savePlan() {
    try {
        const data = { ...this.planForm };
        // Convert numeric fields
        data.max_users = parseInt(data.max_users) || 999999;
        data.max_projects = parseInt(data.max_projects) || 999999;
        data.max_clients = parseInt(data.max_clients) || 999999;
        data.price_monthly = parseInt(data.price_monthly) || 0;
        data.price_yearly = parseInt(data.price_yearly) || 0;
        data.sort_order = parseInt(data.sort_order) || 0;
        if (this.editingPlanId) {
            await this.api('PUT', `/admin/plans/${this.editingPlanId}`, data);
            this.showToast('Plan updated — limits propagated to tenants', 'success');
        } else {
            await this.api('POST', '/admin/plans', data);
            this.showToast('Plan created', 'success');
        }
        this.showPlanForm = false;
        this.resetPlanForm();
        await this.loadAdminPlans();
        await this.loadAdminInsights();
    } catch (e) { this.showToast(e.message, 'error'); }
},

async deletePlan(planId, planName) {
    if (!confirm(`Delete plan "${planName}"? Tenants on this plan will keep their current limits but become unassigned.`)) return;
    try {
        await this.api('DELETE', `/admin/plans/${planId}`);
        await this.loadAdminPlans();
        await this.loadAdminInsights();
        this.showToast('Plan deleted', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

async loadTenantDetail(tenantId) {
    try {
        this.selectedTenantDetail = await this.api('GET', `/admin/tenants/${tenantId}`);
        // Populate branding form from tenant data
        const b = this.selectedTenantDetail?.tenant?.branding || {};
        const logo = this.selectedTenantDetail?.tenant?.logo_url || '';
        this.adminBrandingForm = {
            app_name: b.app_name || '',
            primary_color: b.primary_color || '#7c3aed',
            logo_url: logo || b.logo_url || '',
            hide_powered_by: b.hide_powered_by || false,
        };
    } catch (e) { this.showToast('Failed to load tenant detail', 'error'); }
},

async adminAddMember(tenantId) {
    try {
        await this.api('POST', `/admin/tenants/${tenantId}/members?name=${encodeURIComponent(this.adminAddUserForm.name)}&email=${encodeURIComponent(this.adminAddUserForm.email)}&password=${encodeURIComponent(this.adminAddUserForm.password)}&role=${this.adminAddUserForm.role}`);
        this.adminAddUserForm = { name: '', email: '', password: '', role: 'member' };
        await this.loadTenantDetail(tenantId);
        await this.loadAdminInsights();
        this.showToast('User added', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

async adminRemoveMember(tenantId, userId) {
    if (!confirm('Remove this user from the tenant?')) return;
    try {
        await this.api('DELETE', `/admin/tenants/${tenantId}/members/${userId}`);
        await this.loadTenantDetail(tenantId);
        await this.loadAdminInsights();
        this.showToast('User removed', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

async adminChangeMemberRole(tenantId, userId, newRole) {
    try {
        await this.api('PUT', `/admin/tenants/${tenantId}/members/${userId}?role=${newRole}`);
        await this.loadTenantDetail(tenantId);
        this.showToast('Role updated', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

async adminResetPassword(tenantId, userId) {
    const pwd = prompt('Enter new password (min 8 characters):');
    if (!pwd || pwd.length < 8) { if (pwd) this.showToast('Password too short', 'error'); return; }
    try {
        await this.api('PUT', `/admin/tenants/${tenantId}/members/${userId}/reset-password?new_password=${encodeURIComponent(pwd)}`);
        this.showToast('Password reset', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

async adminToggleMemberActive(tenantId, userId, currentActive) {
    try {
        await this.api('PUT', `/admin/tenants/${tenantId}/members/${userId}?is_active=${!currentActive}`);
        await this.loadTenantDetail(tenantId);
        this.showToast(`User ${!currentActive ? 'activated' : 'deactivated'}`, 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

async adminUpdateBranding(tenantId) {
    try {
        await this.api('PUT', `/admin/tenants/${tenantId}/branding`, this.adminBrandingForm);
        await this.loadTenantDetail(tenantId);
        this.showToast('Branding updated', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},


// ===== Tenant Admin: User Management =====
async tenantCreateUser() {
    try {
        await this.api('POST', `/tenant/users?name=${encodeURIComponent(this.tenantCreateForm.name)}&email=${encodeURIComponent(this.tenantCreateForm.email)}&password=${encodeURIComponent(this.tenantCreateForm.password)}&role=${this.tenantCreateForm.role}`);
        this.tenantCreateForm = { name: '', email: '', password: '', role: 'member' };
        await this.loadMembers();
        await this.loadUsage();
        this.showToast('User added', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

async tenantResetPassword(userId) {
    const pwd = prompt('Enter new password (min 8 characters):');
    if (!pwd || pwd.length < 8) { if (pwd) this.showToast('Password too short', 'error'); return; }
    try {
        await this.api('PUT', `/tenant/members/${userId}/reset-password?new_password=${encodeURIComponent(pwd)}`);
        this.showToast('Password reset', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

async tenantToggleActive(userId, currentActive) {
    try {
        await this.api('PUT', `/tenant/members/${userId}/toggle-active`);
        await this.loadMembers();
        this.showToast(`User ${!currentActive ? 'activated' : 'deactivated'}`, 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

async loadIntegrations() {
    try {
        this.integrations = await this.api('GET', '/tenant/settings');
    } catch { this.integrations = {}; }
},

async saveIntegrations() {
    try {
        const payload = {};
        if (this.integrationForm.github_token) payload.github_token = this.integrationForm.github_token;
        if (this.integrationForm.ai_api_key) payload.ai_api_key = this.integrationForm.ai_api_key;
        if (this.integrationForm.ai_base_url) payload.ai_base_url = this.integrationForm.ai_base_url;
        if (this.integrationForm.ai_model) payload.ai_model = this.integrationForm.ai_model;
        await this.api('PUT', '/tenant/settings', payload);
        await this.loadIntegrations();
        this.integrationForm = { github_token: '', ai_api_key: '', ai_base_url: '', ai_model: '' };
        this.showToast('Integrations saved', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

async loadUsage() {
    try {
        const data = await this.api('GET', '/tenant/usage');
        const limits = await this.api('GET', '/tenant/usage/history?days=1');
        const current = limits.current || {};
        const lim = limits.limits || {};
        this.usageMetrics = [
            { key: 'users', label: 'Team Members', current: current.users || 0, limit: lim.users || 3 },
            { key: 'projects', label: 'Projects', current: current.projects || 0, limit: lim.projects || 1 },
            { key: 'releases', label: 'Releases', current: current.releases || 0, limit: lim.releases || 999999 },
            { key: 'backlog_items', label: 'Backlog Items', current: current.backlog_items || 0, limit: lim.backlog_items || 999999 },
        ];
    } catch { this.usageMetrics = []; }
},

async createUser() {
    try {
        await this.api('POST', '/users', this.userForm);
        this.userForm = { name: '', email: '', password: '', system_role: 'member' };
        await this.loadUsers();
        this.showToast('User created', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

async deleteUser(id) {
    try {
        await this.api('DELETE', `/users/${id}`);
        await this.loadUsers();
        this.showToast('User deleted', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

async assignRole() {
    try {
        await this.api('POST', `/projects/${this.assignmentForm.project_id}/assignments`, this.assignmentForm);
        this.assignmentForm = { user_id: '', role_id: '', project_id: '' };
        await this.loadUsers();
        this.showToast('RACI role assigned', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

assignableUsers(roleName) {
    // All system users, but exclude those already assigned to THIS role on
    // this project. While a change-assignee dropdown is open for this role,
    // keep the current assignee selectable (swap back to them).
    const editingThis = this.editAssign && this.editAssign.role === roleName;
    const assignedIds = this.projectAssignments
        .filter(a => a.role_name === roleName && (!editingThis || a.id !== this.editAssign.id))
        .map(a => a.user_id);
    return (this.users || []).filter(u => !assignedIds.includes(u.id));
},

filterReqUsers(roleName) {
    const q = (this.reqUserSearch[roleName] || '').toLowerCase().trim();
    const pool = this.assignableUsers(roleName);
    if (!q) {
        this.reqUserResults = pool.slice(0, 10);
    } else {
        this.reqUserResults = pool.filter(u =>
            (u.name || '').toLowerCase().includes(q) ||
            (u.email || '').toLowerCase().includes(q)
        ).slice(0, 10);
    }
},

async assignRequiredRole(roleName, userId) {
    if (!userId || !this.selectedProject) return;
    this.reqUserFocused = null;
    this.reqUserSearch[roleName] = '';
    const role = (this.roles || []).find(r => r.name === roleName);
    if (!role) { this.showToast(`Role '${roleName}' not found`, 'error'); return; }
    try {
        await this.api('POST', `/projects/${this.selectedProject.id}/assignments`, {
            user_id: parseInt(userId),
            role_id: role.id,
            project_id: this.selectedProject.id,
        });
        this.projectAssignments = await this.api('GET', `/projects/${this.selectedProject.id}/assignments`);
        this.showToast(`${roleName} assigned`, 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

async assignAM() {
    try {
        await this.api('PUT', `/clients/${this.amForm.client_id}/account-manager`, { account_manager_id: parseInt(this.amForm.user_id) });
        this.amForm = { client_id: '', user_id: '' };
        await this.loadUsers();
        await this.loadClients();
        this.showToast('Account Manager assigned', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

async assignPM() {
    try {
        await this.api('PUT', `/projects/${this.pmForm.project_id}/project-manager`, { project_manager_id: parseInt(this.pmForm.user_id) });
        this.pmForm = { project_id: '', user_id: '' };
        await this.loadUsers();
        this.showToast('Project Manager assigned', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

async loadClients() {
    try { this.clients = await this.api('GET', '/clients'); }
    catch (e) { this.showToast('Failed to load clients: ' + e.message, 'error'); }
},

getClientName(id) { return this.clients.find(c => c.id === id)?.name || 'Unknown'; },

openClient(client) {
    this.selectedClient = client;
    this.route = 'client-detail';
},

backToClients() {
    this.selectedClient = null;
    this.route = 'clients';
},

openClientModal(client = null) {
    this.editingClient = client ? { ...client } : { name: '', contact_name: '', contact_email: '', description: '' };
    this.clientModalOpen = true;
},

async saveClient() {
    try {
        if (this.editingClient.id) {
            const updated = await this.api('PUT', '/clients/' + this.editingClient.id, this.editingClient);
            this.showToast('Client updated successfully');
            // Update selectedClient if we're on the detail page
            if (this.selectedClient && this.selectedClient.id === this.editingClient.id) {
                this.selectedClient = { ...this.selectedClient, ...updated };
            }
        } else {
            await this.api('POST', '/clients', this.editingClient);
            this.showToast('Client created successfully');
        }
        this.clientModalOpen = false;
        await this.loadClients();
    } catch (e) { this.showToast('Failed: ' + e.message, 'error'); }
},

async deleteClient(client) {
    if (!confirm('Delete "' + client.name + '"? This will also delete related projects.')) return;
    try {
        await this.api('DELETE', '/clients/' + client.id);
        this.showToast('Client deleted');
        await Promise.all([this.loadClients(), this.loadProjects()]);
    } catch (e) { this.showToast('Failed: ' + e.message, 'error'); }
},

async loadProjects() {
    try {
        const url = this.projectFilter ? '/projects?client_id=' + this.projectFilter : '/projects';
        this.projects = await this.api('GET', url);
    } catch (e) { this.showToast('Failed to load projects: ' + e.message, 'error'); }
},

openProjectModal(project = null) {
    this.editingProject = project ? { ...project } : { name: '', client_id: '', status: 'Active', github_repo: '', description: '', version_prefix: '', dev_url: '', uat_url: '', prod_url: '' };
    this.projectModalOpen = true;
},

async saveProject() {
    try {
        if (this.editingProject.id) {
            await this.api('PUT', '/projects/' + this.editingProject.id, this.editingProject);
            this.showToast('Project updated successfully');
        } else {
            await this.api('POST', '/projects', this.editingProject);
            this.showToast('Project created successfully');
        }
        this.projectModalOpen = false;
        await this.loadProjects();
    } catch (e) { this.showToast('Failed: ' + e.message, 'error'); }
},

async deleteProject(project) {
    if (!confirm('Delete "' + project.name + '"?')) return;
    try {
        await this.api('DELETE', '/projects/' + project.id);
        this.showToast('Project deleted');
        await this.loadProjects();
    } catch (e) { this.showToast('Failed: ' + e.message, 'error'); }
},

showToast(message, type = 'success') {
    this.toast = { show: true, message, type };
    setTimeout(() => this.toast.show = false, 3000);
},

// ===== P4 automation methods =====
async loadAutomation() {
    try {
        const data = await this.api('GET', '/ai/automation/rules');
        this.automationRules = data.rules || data || [];
    } catch { this.automationRules = []; }
},

async runAutomationScan() {
    try {
        this.automationScan = await this.api('POST', '/ai/automation/scan', {});
        this.automationScan.scanning = false;
        await this.loadAutomation();
        const n = (this.automationScan.proposals || []).length;
        this.showToast(n ? `Scan found ${n} pattern${n === 1 ? '' : 's'} — review and enable` : 'Scan complete — no repeated patterns yet');
    } catch (e) { this.showToast(e.message, 'error'); }
},

async enableRule(id) {
    try {
        await this.api('POST', `/ai/automation/rules/${id}/enable`, {});
        await this.loadAutomation();
        this.showToast('Rule enabled — it now runs on every scan', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

async disableRule(id) {
    try {
        await this.api('POST', `/ai/automation/rules/${id}/disable`, {});
        await this.loadAutomation();
        this.showToast('Rule disabled', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

async deleteRule(id) {
    if (!confirm('Delete this automation rule?')) return;
    try {
        await this.api('DELETE', `/ai/automation/rules/${id}`);
        await this.loadAutomation();
        this.showToast('Rule deleted');
    } catch (e) { this.showToast(e.message, 'error'); }
},

// ===== P4 lifecycle template builder methods =====
async loadLifecycle() {
    try {
        const data = await this.api('GET', '/lifecycle/templates');
        this.lifecycleTemplates = data.templates || [];
        this.lifecycleTypes = await this.api('GET', '/lifecycle/types');
    } catch { this.lifecycleTemplates = []; this.lifecycleTypes = []; }
},

async saveLifecycleTemplate() {
    const f = this.lifecycleForm;
    try {
        await this.api('POST', '/lifecycle/templates', {
            project_type: f.project_type,
            name: f.name,
            description: f.description || null,
            item_phases: f.item_phases.split(',').map(s => s.trim()).filter(Boolean),
            release_stages: f.release_stages.split(',').map(s => s.trim()).filter(Boolean),
            gate_deliverables: {},
            gate_roles: {},
            fields: [],
        });
        this.showLifecycleForm = false;
        this.lifecycleForm = { project_type: '', name: '', description: '', item_phases: '', release_stages: '', fields_text: '' };
        await this.loadLifecycle();
        this.showToast('Lifecycle template saved — new projects of this type use it', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

async editLifecycleTemplate(t) {
    this.lifecycleForm = {
        project_type: t.project_type,
        name: t.name,
        description: t.description || '',
        item_phases: (t.item_phases || []).join(', '),
        release_stages: (t.release_stages || []).join(', '),
        fields_text: '',
    };
    this.showLifecycleForm = true;
},

async deleteLifecycleTemplate(id) {
    if (!confirm('Remove this template? The project type falls back to the built-in lifecycle.')) return;
    try {
        await this.api('DELETE', `/lifecycle/templates/${id}`);
        await this.loadLifecycle();
        this.showToast('Template removed — built-in lifecycle restored', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

};

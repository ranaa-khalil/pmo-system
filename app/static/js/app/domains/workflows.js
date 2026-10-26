// PMO System — app/workflows.js
// Workflows domain of the Alpine pmoApp() store.
// Fragments are verbatim from the original monolith; pmo-app.js assembles them.

export const workflows = {
// ===== Forms state =====
formTemplates: [],
projectForms: [],
selectedForm: null,
formEditMode: false,


// ===== Risks state (P3 heatmap) =====
projectRisks: [],
selectedRisk: null,
riskEditMode: false,
riskMatrixSeverity: ['Low', 'Medium', 'High', 'Critical'],
riskMatrixProbability: ['Rare', 'Unlikely', 'Medium', 'Likely', 'Almost Certain'],

// ===== Approvals state =====
projectApprovals: [],
selectedApproval: null,
approvalForm: { title: '', description: '', request_type: 'release', steps: [{ role_name: 'Product Owner', step_order: 1 }] },
raciRoles: ['Product Owner', 'Product Manager', 'Business Lead', 'UX Designer', 'Tech Lead', 'Engineering Team', 'QA Lead', 'QA Engineer', 'DevOps Lead', 'DevOps Engineer', 'CX Engineer', 'PMO'],


// ===== Forms =====
async loadForms() {
    try {
        this.formTemplates = await this.api('GET', '/forms/templates');
        this.projectForms = await this.api('GET', `/projects/${this.selectedProject.id}/forms`);
    } catch {
        this.formTemplates = [];
        this.projectForms = [];
    }
},

async createForm(templateId) {
    try {
        await this.api('POST', `/projects/${this.selectedProject.id}/forms`, {
            template_id: templateId,
            project_id: this.selectedProject.id,
        });
        await this.loadForms();
        this.showToast('Form created', 'success');
    } catch (e) {
        this.showToast(e.message, 'error');
    }
},

async openForm(form) {
    this.selectedForm = await this.api('GET', `/forms/${form.id}`);
    this.formEditMode = false;
},

closeForm() {
    this.selectedForm = null;
    this.formEditMode = false;
},

async saveFormData() {
    try {
        this.selectedForm = await this.api('PUT', `/forms/${this.selectedForm.id}`, {
            data: this.selectedForm.data,
        });
        this.formEditMode = false;
        this.showToast('Form saved', 'success');
    } catch (e) {
        this.showToast(e.message, 'error');
    }
},

async submitForm() {
    try {
        this.selectedForm = await this.api('POST', `/forms/${this.selectedForm.id}/submit`);
        await this.loadForms();
        this.showToast('Form submitted', 'success');
    } catch (e) {
        this.showToast(e.message, 'error');
    }
},

async approveForm() {
    try {
        this.selectedForm = await this.api('POST', `/forms/${this.selectedForm.id}/approve`);
        await this.loadForms();
        this.showToast('Form approved', 'success');
    } catch (e) {
        this.showToast(e.message, 'error');
    }
},

async deleteForm(id) {
    try {
        await this.api('DELETE', `/forms/${id}`);
        this.selectedForm = null;
        await this.loadForms();
        this.showToast('Form deleted', 'success');
    } catch (e) {
        this.showToast(e.message, 'error');
    }
},

formStatusColor(status) {
    return {
        'Draft': 'bg-ink-100 text-ink-600',
        'Submitted': 'bg-blue-50 text-blue-700',
        'Approved': 'bg-emerald-50 text-emerald-700',
        'Rejected': 'bg-rose-50 text-rose-700',
    }[status] || 'bg-ink-100 text-ink-600';
},


// ===== Approvals =====
async loadApprovals() {
    try {
        this.projectApprovals = await this.api('GET', `/projects/${this.selectedProject.id}/approvals`);
    } catch {
        this.projectApprovals = [];
    }
},

addApprovalStep() {
    this.approvalForm.steps.push({ role_name: '', step_order: this.approvalForm.steps.length + 1 });
},

removeApprovalStep(idx) {
    this.approvalForm.steps.splice(idx, 1);
    this.approvalForm.steps.forEach((s, i) => s.step_order = i + 1);
},

async saveApproval() {
    try {
        await this.api('POST', `/projects/${this.selectedProject.id}/approvals`, {
            project_id: this.selectedProject.id,
            ...this.approvalForm,
        });
        this.approvalForm = { title: '', description: '', request_type: 'release', steps: [{ role_name: 'Product Owner', step_order: 1 }] };
        await this.loadApprovals();
        this.showToast('Approval request created', 'success');
    } catch (e) {
        this.showToast(e.message, 'error');
    }
},

async openApproval(approval) {
    this.selectedApproval = await this.api('GET', `/approvals/${approval.id}`);
},

closeApproval() {
    this.selectedApproval = null;
},

async approveStep(stepId) {
    try {
        this.selectedApproval = await this.api('POST', `/approvals/${this.selectedApproval.id}/steps/${stepId}/approve`, {});
        await this.loadApprovals();
        this.showToast('Step approved', 'success');
    } catch (e) {
        this.showToast(e.message, 'error');
    }
},

async rejectStep(stepId) {
    try {
        this.selectedApproval = await this.api('POST', `/approvals/${this.selectedApproval.id}/steps/${stepId}/reject`, {});
        await this.loadApprovals();
        this.showToast('Step rejected', 'error');
    } catch (e) {
        this.showToast(e.message, 'error');
    }
},

async deleteApproval(id) {
    try {
        await this.api('DELETE', `/approvals/${id}`);
        this.selectedApproval = null;
        await this.loadApprovals();
        this.showToast('Approval deleted', 'success');
    } catch (e) {
        this.showToast(e.message, 'error');
    }
},

approvalStatusColor(status) {
    return {
        'Pending': 'bg-amber-50 text-amber-700',
        'Approved': 'bg-emerald-50 text-emerald-700',
        'Rejected': 'bg-rose-50 text-rose-700',
        'Skipped': 'bg-ink-100 text-ink-400',
    }[status] || 'bg-ink-100 text-ink-600';
},


// ===== Risk heatmap (P3): severity × probability 5×4 matrix =====
riskLevel(severity, probability) {
    const s = { 'Low': 1, 'Medium': 2, 'High': 3, 'Critical': 5 }[severity] || 0;
    const pr = { 'Rare': 1, 'Unlikely': 2, 'Medium': 3, 'Possible': 3, 'Likely': 4, 'Almost Certain': 5 }[probability] || 0;
    return s * pr;
},

risksInCell(severity, probability) {
    return (this.projectRisks || []).filter(r => r.severity === severity && r.probability === probability && r.status !== 'Closed');
},

riskCellColor(severity, probability) {
    // Standard bands on the 5×5 scale: low ≤4, moderate ≤9, high ≤14, extreme ≥15
    const score = this.riskLevel(severity, probability);
    if (score <= 0) return 'bg-ink-50';
    if (score <= 4) return 'bg-emerald-50 border-emerald-100';
    if (score <= 9) return 'bg-amber-50 border-amber-100';
    if (score <= 14) return 'bg-orange-50 border-orange-100';
    return 'bg-rose-50 border-rose-100';
},

riskScoreColor(risk) {
    const score = typeof risk.score === 'number' ? risk.score : this.riskLevel(risk.severity, risk.probability);
    if (score <= 4) return 'bg-emerald-100 text-emerald-700';
    if (score <= 9) return 'bg-amber-100 text-amber-700';
    if (score <= 14) return 'bg-orange-100 text-orange-700';
    return 'bg-rose-100 text-rose-700';
},

riskStatusColor(status) {
    return {
        'Open': 'bg-rose-50 text-rose-700',
        'Mitigating': 'bg-amber-50 text-amber-700',
        'Closed': 'bg-emerald-50 text-emerald-700',
    }[status] || 'bg-ink-100 text-ink-600';
},

async loadRisks() {
    try {
        this.projectRisks = await this.api('GET', `/projects/${this.selectedProject.id}/risks`);
    } catch { this.projectRisks = []; }
},

openRisk(risk) {
    // View modal with inline edit in the same panel (edit → inline within modal)
    this.selectedRisk = { ...risk };
    this.riskEditMode = false;
},

closeRisk() {
    this.selectedRisk = null;
    this.riskEditMode = false;
},

async saveRisk() {
    try {
        const updated = await this.api('PUT', `/risks/${this.selectedRisk.id}`, {
            status: this.selectedRisk.status,
            severity: this.selectedRisk.severity,
            probability: this.selectedRisk.probability,
            mitigation: this.selectedRisk.mitigation,
        });
        Object.assign(this.selectedRisk, updated);
        await this.loadRisks();
        this.riskEditMode = false;
        this.showToast('Risk updated', 'success');
    } catch (e) {
        this.showToast(e.message, 'error');
    }
},


// ===== Personas & Environments =====
async loadPersonas() {
    try {
        this.personas = await this.api('GET', `/projects/${this.selectedProject.id}/personas`);
    } catch { this.personas = []; }
},

async loadTestAccounts() {
    try {
        this.testAccounts = await this.api('GET', `/projects/${this.selectedProject.id}/test-accounts`);
    } catch { this.testAccounts = []; }
},

initEnvForm() {
    this.envForm = {
        dev_url: this.selectedProject?.dev_url || '',
        uat_url: this.selectedProject?.uat_url || '',
        prod_url: this.selectedProject?.prod_url || '',
    };
},

async saveEnvUrls() {
    try {
        const updated = await this.api('PUT', '/projects/' + this.selectedProject.id, this.envForm);
        this.selectedProject = { ...this.selectedProject, ...updated };
        // Also update in projects array
        const idx = this.projects.findIndex(p => p.id === this.selectedProject.id);
        if (idx >= 0) this.projects[idx] = { ...this.projects[idx], ...updated };
        this.envEditMode = false;
        this.showToast('Environment URLs saved');
    } catch (e) { this.showToast('Failed: ' + e.message, 'error'); }
},

openPersonaModal(persona = null) {
    this.editingPersona = persona ? { ...persona } : { name: '', role: '', description: '', goals: '', pain_points: '' };
    this.personaModalOpen = true;
},

async savePersona() {
    try {
        if (this.editingPersona.id) {
            await this.api('PUT', `/projects/${this.selectedProject.id}/personas/${this.editingPersona.id}`, this.editingPersona);
            this.showToast('Persona updated');
        } else {
            await this.api('POST', `/projects/${this.selectedProject.id}/personas`, { ...this.editingPersona, project_id: this.selectedProject.id });
            this.showToast('Persona created');
        }
        this.personaModalOpen = false;
        await this.loadPersonas();
    } catch (e) { this.showToast('Failed: ' + e.message, 'error'); }
},

async deletePersona(persona) {
    if (!confirm('Delete persona "' + persona.name + '"?')) return;
    try {
        await this.api('DELETE', `/projects/${this.selectedProject.id}/personas/${persona.id}`);
        this.showToast('Persona deleted');
        await this.loadPersonas();
    } catch (e) { this.showToast('Failed: ' + e.message, 'error'); }
},

openTestAccountModal(account = null) {
    this.editingTestAccount = account ? { ...account } : { environment: 'UAT', username: '', password_hint: '', role: '', notes: '' };
    this.testAccountModalOpen = true;
},

async saveTestAccount() {
    try {
        if (this.editingTestAccount.id) {
            await this.api('PUT', `/projects/${this.selectedProject.id}/test-accounts/${this.editingTestAccount.id}`, this.editingTestAccount);
            this.showToast('Test account updated');
        } else {
            await this.api('POST', `/projects/${this.selectedProject.id}/test-accounts`, { ...this.editingTestAccount, project_id: this.selectedProject.id });
            this.showToast('Test account created');
        }
        this.testAccountModalOpen = false;
        await this.loadTestAccounts();
    } catch (e) { this.showToast('Failed: ' + e.message, 'error'); }
},

async deleteTestAccount(account) {
    if (!confirm('Delete test account "' + account.username + '"?')) return;
    try {
        await this.api('DELETE', `/projects/${this.selectedProject.id}/test-accounts/${account.id}`);
        this.showToast('Test account deleted');
        await this.loadTestAccounts();
    } catch (e) { this.showToast('Failed: ' + e.message, 'error'); }
},


// ===== Infrastructure =====
async loadInfrastructure() {
    const pid = this.selectedProject.id;
    // Load each independently so a rate-limit on one doesn't block the others
    try { this.infraOverview = await this.api('GET', `/projects/${pid}/infra/overview`); } catch { this.infraOverview = null; }
    try { this.infraEnvironments = await this.api('GET', `/projects/${pid}/infra/environments`); } catch { this.infraEnvironments = []; }
    try { this.infraSecrets = await this.api('GET', `/projects/${pid}/infra/secrets`); } catch { this.infraSecrets = []; }
    try { this.infraAssets = await this.api('GET', `/projects/${pid}/infra/assets`); } catch { this.infraAssets = []; }
    try { this.infraServices = await this.api('GET', `/projects/${pid}/infra/services`); } catch { this.infraServices = []; }
    try { this.infraDatabases = await this.api('GET', `/projects/${pid}/infra/databases`); } catch { this.infraDatabases = []; }
},

// Environments
async saveInfraEnv() {
    try {
        const data = { ...this.infraEnvForm };
        if (data.environment_id === '') data.environment_id = null;
        if (this.editingInfraEnvId) {
            await this.api('PUT', `/infra/environments/${this.editingInfraEnvId}`, data);
        } else {
            await this.api('POST', `/projects/${this.selectedProject.id}/infra/environments`, data);
        }
        await this.loadInfrastructure();
        this.showInfraEnvForm = false;
        this.editingInfraEnvId = null;
        this.infraEnvForm = { name: '', type: 'development', url: '', description: '', status: 'active' };
        this.showToast('Environment saved', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},
editInfraEnv(e) {
    this.editingInfraEnvId = e.id;
    this.infraEnvForm = { name: e.name, type: e.type, url: e.url || '', description: e.description || '', status: e.status };
    this.showInfraEnvForm = true;
},
async deleteInfraEnv(id) {
    if (!confirm('Delete this environment?')) return;
    try {
        await this.api('DELETE', `/infra/environments/${id}`);
        await this.loadInfrastructure();
        this.showToast('Environment deleted', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

// Secrets
async saveInfraSecret() {
    try {
        const data = { ...this.infraSecretForm };
        if (data.environment_id === '') data.environment_id = null;
        if (data.expires_at === '') data.expires_at = null;
        if (this.editingInfraSecretId) {
            await this.api('PUT', `/infra/secrets/${this.editingInfraSecretId}`, data);
        } else {
            await this.api('POST', `/projects/${this.selectedProject.id}/infra/secrets`, data);
        }
        await this.loadInfrastructure();
        this.showInfraSecretForm = false;
        this.editingInfraSecretId = null;
        this.infraSecretForm = { name: '', category: '', environment_id: '', value: '', description: '', expires_at: '' };
        this.showToast('Secret saved', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},
editInfraSecret(s) {
    this.editingInfraSecretId = s.id;
    this.infraSecretForm = { name: s.name, category: s.category, environment_id: s.environment_id || '', value: '', description: s.description || '', expires_at: s.expires_at ? s.expires_at.split('T')[0] : '' };
    this.showInfraSecretForm = true;
},
async revealSecret(id) {
    try {
        const data = await this.api('GET', `/infra/secrets/${id}/reveal`);
        this.revealedSecrets = { ...this.revealedSecrets, [id]: data.value };
        // Auto-hide after 30 seconds
        setTimeout(() => {
            const rs = { ...this.revealedSecrets };
            delete rs[id];
            this.revealedSecrets = rs;
        }, 30000);
    } catch (e) { this.showToast(e.message, 'error'); }
},
async rotateInfraSecret(s) {
    const newValue = prompt(`Enter new value for "${s.name}":`);
    if (!newValue) return;
    try {
        await this.api('POST', `/infra/secrets/${s.id}/rotate`, { value: newValue });
        await this.loadInfrastructure();
        this.showToast('Secret rotated — new version created', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},
async viewSecretAudit(s) {
    try {
        this.secretAuditData = await this.api('GET', `/infra/secrets/${s.id}/audit`);
    } catch (e) { this.showToast(e.message, 'error'); }
},
async deleteInfraSecret(id) {
    if (!confirm('Delete this secret? This cannot be undone.')) return;
    try {
        await this.api('DELETE', `/infra/secrets/${id}`);
        await this.loadInfrastructure();
        this.showToast('Secret deleted', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

// Assets
async saveInfraAsset() {
    try {
        const data = { ...this.infraAssetForm };
        if (data.environment_id === '') data.environment_id = null;
        if (data.cost_monthly === '') data.cost_monthly = null;
        let metadata = {};
        if (data.metadata_json) { try { metadata = JSON.parse(data.metadata_json); } catch {} }
        data.metadata = metadata;
        delete data.metadata_json;
        if (this.editingInfraAssetId) {
            await this.api('PUT', `/infra/assets/${this.editingInfraAssetId}`, data);
        } else {
            await this.api('POST', `/projects/${this.selectedProject.id}/infra/assets`, data);
        }
        await this.loadInfrastructure();
        this.showInfraAssetForm = false;
        this.editingInfraAssetId = null;
        this.infraAssetForm = { name: '', asset_type: '', environment_id: '', team: '', status: 'active', cost_monthly: '', metadata_json: '' };
        this.showToast('Asset saved', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},
editInfraAsset(a) {
    this.editingInfraAssetId = a.id;
    this.infraAssetForm = { name: a.name, asset_type: a.asset_type, environment_id: a.environment_id || '', team: a.team || '', status: a.status, cost_monthly: a.cost_monthly || '', metadata_json: Object.keys(a.metadata || {}).length ? JSON.stringify(a.metadata, null, 2) : '' };
    this.showInfraAssetForm = true;
},
async deleteInfraAsset(id) {
    if (!confirm('Delete this asset?')) return;
    try {
        await this.api('DELETE', `/infra/assets/${id}`);
        await this.loadInfrastructure();
        this.showToast('Asset deleted', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

// Services
async saveInfraService() {
    try {
        const data = { ...this.infraServiceForm };
        if (data.environment_id === '') data.environment_id = null;
        if (this.editingInfraServiceId) {
            await this.api('PUT', `/infra/services/${this.editingInfraServiceId}`, data);
        } else {
            await this.api('POST', `/projects/${this.selectedProject.id}/infra/services`, data);
        }
        await this.loadInfrastructure();
        this.showInfraServiceForm = false;
        this.editingInfraServiceId = null;
        this.infraServiceForm = { name: '', service_type: 'internal', environment_id: '', documentation_url: '' };
        this.showToast('Service saved', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},
editInfraService(s) {
    this.editingInfraServiceId = s.id;
    this.infraServiceForm = { name: s.name, service_type: s.service_type, environment_id: s.environment_id || '', documentation_url: s.documentation_url || '' };
    this.showInfraServiceForm = true;
},
async deleteInfraService(id) {
    if (!confirm('Delete this service?')) return;
    try {
        await this.api('DELETE', `/infra/services/${id}`);
        await this.loadInfrastructure();
        this.showToast('Service deleted', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

// Databases
async saveInfraDb() {
    try {
        const data = { ...this.infraDbForm };
        if (data.environment_id === '') data.environment_id = null;
        if (data.port === '') data.port = null;
        if (this.editingInfraDbId) {
            await this.api('PUT', `/infra/databases/${this.editingInfraDbId}`, data);
        } else {
            await this.api('POST', `/projects/${this.selectedProject.id}/infra/databases`, data);
        }
        await this.loadInfrastructure();
        this.showInfraDbForm = false;
        this.editingInfraDbId = null;
        this.infraDbForm = { name: '', db_type: 'postgresql', host: '', port: '', environment_id: '', backup_policy: '' };
        this.showToast('Database saved', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},
editInfraDb(d) {
    this.editingInfraDbId = d.id;
    this.infraDbForm = { name: d.name, db_type: d.db_type, host: d.host || '', port: d.port || '', environment_id: d.environment_id || '', backup_policy: d.backup_policy || '' };
    this.showInfraDbForm = true;
},
async deleteInfraDb(id) {
    if (!confirm('Delete this database record?')) return;
    try {
        await this.api('DELETE', `/infra/databases/${id}`);
        await this.loadInfrastructure();
        this.showToast('Database deleted', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

async loadTraceability() {
    try {
        this.traceability = await this.api('GET', `/projects/${this.selectedProject.id}/traceability`);
    } catch { this.traceability = null; }
},

kpiProgress(kpi) {
    if (!kpi || !kpi.target_value || !kpi.current_value) return 0;
    try {
        const target = parseFloat(kpi.target_value);
        const current = parseFloat(kpi.current_value);
        if (isNaN(target) || isNaN(current) || target === 0) return 0;
        return Math.min(100, Math.round((current / target) * 100));
    } catch { return 0; }
},

kpiDisplayValue(kpi, field) {
    // Returns "20%" if unit is %, or "50 users" if unit is users
    const val = kpi[field];
    if (!val) return '—';
    const unit = kpi.unit || '';
    if (unit === '%') return val + '%';
    return val + (unit ? ' ' + unit : '');
},

async saveRelease() {
    try {
        await this.api('POST', `/projects/${this.selectedProject.id}/releases`, this.releaseForm);
        this.releaseForm = { version: '', name: '', description: '', target_date: '', milestone_id: '' };
        this.showReleaseForm = false;
        await this.loadReleases();
        this.showToast('Release created', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

async openRelease(release) {
    try {
        this.selectedRelease = await this.api('GET', `/releases/${release.id}`);
        this.sharedWith = null;
        this.releaseItemSearch = '';
        this.showReleaseItemSearch = false;
    } catch (e) { this.showToast(e.message, 'error'); }
},

closeRelease() { this.selectedRelease = null; },

async addBacklogToRelease(releaseId, backlogItemId) {
    try {
        await this.api('POST', `/releases/${releaseId}/items/${backlogItemId}`);
        await this.openRelease({ id: releaseId });
        this.showToast('Item added to release', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

async removeItemFromRelease(releaseId, backlogItemId) {
    try {
        await this.api('DELETE', `/releases/${releaseId}/items/${backlogItemId}`);
        await this.openRelease({ id: releaseId });
        this.showToast('Item removed', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

async generateNotes(releaseId) {
    try {
        const result = await this.api('POST', `/releases/${releaseId}/generate-notes`);
        await this.openRelease({ id: releaseId });
        this.showToast('Release notes generated from template', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

downloadNotes(releaseId) {
    const token = localStorage.getItem('pmo_token') || '';
    window.open(`/api/releases/${releaseId}/download-notes?token=${token}`, '_blank');
},

downloadSignoffPdf(releaseId) {
    const token = localStorage.getItem('pmo_token') || '';
    window.open(`/api/releases/${releaseId}/signoff-pdf?token=${token}`, '_blank');
},

viewSignoffPdf(releaseId) {
    const token = localStorage.getItem('pmo_token') || '';
    this.pdfViewerUrl = `/api/releases/${releaseId}/signoff-pdf?token=${token}&view=1`;
},

async shareNotes(releaseId) {
    try {
        this.sharedWith = await this.api('POST', `/releases/${releaseId}/share`);
        this.showToast(`Shared with ${this.sharedWith.shared_with.length} stakeholder(s)`, 'success');
    } catch(e) { this.showToast(e.message, 'error'); }
},

async advanceRelease(releaseId) {
    try {
        const result = await this.api('POST', `/releases/${releaseId}/advance`);
        await this.openRelease({ id: releaseId });
        await this.loadReleases();

        if (result.approval_status === 'created') {
            this.showToast(`Approval routed to ${result.pending_role} for ${result.target_phase}`, 'info');
        } else if (result.approval_status === 'pending') {
            this.showToast(`Still pending approval from ${result.pending_role}`, 'info');
        } else if (result.approval_status === 'approved') {
            let msg = `Advanced to ${result.status}`;
            if (result.next_pending_role) {
                msg += ` — next approval routed to ${result.next_pending_role}`;
            }
            this.showToast(msg, 'success');
        } else if (result.approval_status === 'rejected') {
            this.showToast(`Advancement rejected: ${result.message}`, 'error');
        } else {
            this.showToast(`Advanced to ${result.status}`, 'success');
        }
    } catch (e) { this.showToast(e.message, 'error'); }
},

async approveReleaseStep(approvalId, stepId) {
    try {
        await this.api('POST', `/approvals/${approvalId}/steps/${stepId}/approve`, { comment: 'Approved via PMO system' });
        if (this.selectedRelease) {
            await this.openRelease({ id: this.selectedRelease.id });
        }
        await this.loadReleases();
        await this.loadApprovals();
        this.showToast('Approval granted — release advanced', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

async deleteRelease(id) {
    try {
        await this.api('DELETE', `/releases/${id}`);
        this.selectedRelease = null;
        await this.loadReleases();
        this.showToast('Release deleted', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

getReleasePhaseIndex(status) {
    const phases = ['Planning', 'In Progress', 'Testing', 'UAT', 'Pre-Release', 'Released', 'Post-Release'];
    return phases.indexOf(status);
},

releaseStatusColor(status) {
    return {
        'Planning': 'bg-ink-100 text-ink-600',
        'In Progress': 'bg-blue-50 text-blue-700',
        'Testing': 'bg-amber-50 text-amber-700',
        'UAT': 'bg-violet-50 text-violet-700',
        'Pre-Release': 'bg-orange-50 text-orange-700',
        'Released': 'bg-emerald-50 text-emerald-700',
        'Post-Release': 'bg-teal-50 text-teal-700',
        'Cancelled': 'bg-rose-50 text-rose-700',
    }[status] || 'bg-ink-100 text-ink-600';
},

};

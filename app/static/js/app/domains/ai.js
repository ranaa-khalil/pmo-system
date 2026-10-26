// PMO System — app/ai.js
// Ai domain of the Alpine pmoApp() store.
// Fragments are verbatim from the original monolith; pmo-app.js assembles them.

export const ai = {
// ===== AI assistant state =====
aiConfigured: false,
aiLoading: false,
aiModalOpen: false,
aiModalTitle: '',
aiModalContent: null,
aiModalType: '',  // 'vision', 'features', 'fill'
aiConfigForm: { api_key: '', base_url: 'https://api.openai.com/v1', model: 'gpt-4o-mini', _msg: '', _ok: false },
aiSuggestionStatus: {},  // {epic_0: 'pending', feature_0: 'approved', ...}


// ===== AI assistant methods =====
async checkAIStatus() {
    try {
        const data = await this.api('GET', '/ai/status');
        this.aiConfigured = data.configured;
        if (data.base_url) this.aiConfigForm.base_url = data.base_url;
        if (data.model) this.aiConfigForm.model = data.model;
    } catch (e) { this.aiConfigured = false; }
},

async aiSuggestVision() {
    if (!this.aiConfigured) {
        this.showToast('AI is not configured. Set API key in Settings.', 'error');
        return;
    }
    this.aiLoading = true;
    this.aiModalType = 'vision';
    this.aiModalTitle = '✨ AI Vision Analysis';
    this.aiModalOpen = true;
    this.aiModalContent = null;
    try {
        this.aiModalContent = await this.api('POST', '/ai/suggest-vision', {
            project_id: this.selectedProject.id
        });
    } catch (e) {
        this.aiModalContent = { error: e?.message || 'Failed to get AI suggestion' };
    }
    this.aiLoading = false;
},

async aiSuggestFeatures() {
    if (!this.aiConfigured) {
        this.showToast('AI is not configured. Set API key in Settings.', 'error');
        return;
    }
    this.aiLoading = true;
    this.aiModalType = 'features';
    this.aiModalTitle = '✨ AI Feature Suggestions';
    this.aiModalOpen = true;
    this.aiModalContent = null;
    this.aiSuggestionStatus = {};
    try {
        this.aiModalContent = await this.api('POST', '/ai/suggest-features', {
            project_id: this.selectedProject.id
        });
        // Initialize all as pending
        const epics = this.aiModalContent.suggested_epics || [];
        const features = this.aiModalContent.suggested_features || [];
        epics.forEach((_, i) => { this.aiSuggestionStatus['epic_' + i] = 'pending'; });
        features.forEach((_, i) => { this.aiSuggestionStatus['feature_' + i] = 'pending'; });
    } catch (e) {
        this.aiModalContent = { error: e?.message || 'Failed to get AI suggestion' };
    }
    this.aiLoading = false;
},

async aiFillField(itemId, fieldName, context = '') {
    if (!this.aiConfigured) {
        this.showToast('AI is not configured. Set API key in Settings.', 'error');
        return;
    }
    this.aiLoading = true;
    this.aiModalType = 'fill';
    this.aiModalTitle = `✨ AI Fill: ${fieldName}`;
    this.aiModalOpen = true;
    this.aiModalContent = null;
    this._aiFillItemId = itemId;
    this._aiFillFieldName = fieldName;
    try {
        this.aiModalContent = await this.api('POST', '/ai/fill-field', {
            item_id: itemId,
            field_name: fieldName,
            field_context: context,
        });
    } catch (e) {
        this.aiModalContent = { error: e?.message || 'Failed to get AI suggestion' };
    }
    this.aiLoading = false;
},

approveAISuggestion() {
    if (this.aiModalType === 'vision' && this.aiModalContent?.improved_vision) {
        this.visionForm.statement = this.aiModalContent.improved_vision;
        if (this.aiModalContent.suggested_objectives?.length) {
            this.visionForm.strategic_objectives = this.aiModalContent.suggested_objectives.join('\n');
        }
        this.saveVision();
        this.showToast('Vision updated with AI suggestion', 'success');
    } else if (this.aiModalType === 'fill' && this.aiModalContent) {
        const fieldName = this._aiFillFieldName;
        const value = this.aiModalContent[fieldName];
        if (value && this.viewingBacklogItem) {
            this.viewingBacklogItem[fieldName] = value;
            // Also update edit form if open
            if (this.editingBacklogId) {
                this.backlogEditForm[fieldName] = value;
            }
            this.showToast(`${fieldName} filled with AI suggestion`, 'success');
        }
    }
    this.aiModalOpen = false;
},

declineAISuggestion() {
    this.aiModalOpen = false;
    this.showToast('AI suggestion declined', 'info');
},

async approveFeatureSuggestion(idx, type) {
    // type = 'epic' or 'feature'
    const key = type + '_' + idx;
    const list = type === 'epic' ? 'suggested_epics' : 'suggested_features';
    const item = this.aiModalContent?.[list]?.[idx];
    if (!item) return;

    // If approving a feature, auto-create its parent epic first (if it's a suggested epic not yet created)
    if (type === 'feature' && item.epic) {
        const epics = this.aiModalContent?.suggested_epics || [];
        const epicIdx = epics.findIndex(e => e.title === item.epic);
        if (epicIdx !== -1) {
            const epicKey = 'epic_' + epicIdx;
            const epicStatus = this.aiSuggestionStatus[epicKey];
            // If epic hasn't been approved yet (pending or not started), create it first
            if (!epicStatus || epicStatus === 'pending') {
                // Mark as adding while we create it
                this.aiSuggestionStatus[epicKey] = 'adding';
                try {
                    const epicItem = epics[epicIdx];
                    await this.api('POST', `/projects/${this.selectedProject.id}/backlog`, {
                        project_id: this.selectedProject.id,
                        title: epicItem.title,
                        description: epicItem.description || '',
                        item_type: 'Epic',
                        epic: epicItem.title,
                        priority: 'Medium',
                        primary_actor: '',
                        story_points: null,
                        acceptance_criteria: '',
                        target_release: '',
                    });
                    this.aiSuggestionStatus[epicKey] = 'approved';
                    this.showToast(`Epic "${epicItem.title}" auto-created`, 'success');
                } catch (e) {
                    // Epic creation failed — continue with feature anyway, it'll still reference the epic name
                    this.aiSuggestionStatus[epicKey] = 'error';
                }
            }
        }
    }

    this.aiSuggestionStatus[key] = 'adding';
    try {
        const payload = {
            project_id: this.selectedProject.id,
            title: item.title,
            description: item.description || '',
            priority: item.priority || 'Medium',
            primary_actor: item.primary_actor || '',
            story_points: item.story_points || null,
            acceptance_criteria: item.acceptance_criteria || '',
            target_release: item.target_release || '',
        };
        if (type === 'epic') {
            payload.item_type = 'Epic';
            payload.epic = item.title;
            // Epics only have title + description
            payload.priority = 'Medium';
            payload.primary_actor = '';
            payload.story_points = null;
            payload.acceptance_criteria = '';
            payload.target_release = '';
        } else {
            payload.item_type = item.item_type || 'Feature';
            payload.epic = item.epic || '';
        }
        await this.api('POST', `/projects/${this.selectedProject.id}/backlog`, payload);
        this.aiSuggestionStatus[key] = 'approved';
        this.showToast(`${type === 'epic' ? 'Epic' : 'Feature'} "${item.title}" added to backlog`, 'success');
        await this.loadBacklog();
    } catch (e) {
        this.aiSuggestionStatus[key] = 'error';
        this.showToast(`Failed to add: ${e.message}`, 'error');
    }
},

declineFeatureSuggestion(idx, type) {
    const key = type + '_' + idx;
    this.aiSuggestionStatus[key] = 'declined';
},

approveAllFeatureSuggestions() {
    const epics = this.aiModalContent?.suggested_epics || [];
    const features = this.aiModalContent?.suggested_features || [];
    epics.forEach((_, idx) => {
        if (this.aiSuggestionStatus['epic_' + idx] === 'pending' || !this.aiSuggestionStatus['epic_' + idx]) {
            this.approveFeatureSuggestion(idx, 'epic');
        }
    });
    features.forEach((_, idx) => {
        if (this.aiSuggestionStatus['feature_' + idx] === 'pending' || !this.aiSuggestionStatus['feature_' + idx]) {
            this.approveFeatureSuggestion(idx, 'feature');
        }
    });
},

async saveAIConfig() {
    try {
        const data = await this.api('PUT', '/ai/config', {
            api_key: this.aiConfigForm.api_key,
            base_url: this.aiConfigForm.base_url,
            model: this.aiConfigForm.model,
        });
        this.aiConfigured = data.configured;
        this.aiConfigForm._msg = data.message || 'Configuration saved.';
        this.aiConfigForm._ok = true;
        this.aiConfigForm.api_key = ''; // Clear for security
        this.showToast('AI configuration saved', 'success');
    } catch (e) {
        this.aiConfigForm._msg = e?.message || 'Failed to save configuration';
        this.aiConfigForm._ok = false;
    }
},

async testAIConfig() {
    this.aiLoading = true;
    try {
        // Try a simple vision suggestion as a test
        if (this.projects.length > 0) {
            const data = await this.api('POST', '/ai/suggest-vision', {
                project_id: this.projects[0].id
            });
            if (data.error) throw new Error(data.error);
            this.aiConfigForm._msg = '✅ AI is working! Test successful.';
            this.aiConfigForm._ok = true;
        } else {
            this.aiConfigForm._msg = 'Create a project first to test AI.';
            this.aiConfigForm._ok = false;
        }
    } catch (e) {
        this.aiConfigForm._msg = '❌ ' + (e?.message || 'Test failed');
        this.aiConfigForm._ok = false;
    }
    this.aiLoading = false;
},

// Chart.js instances
chartInstances: {},

destroyCharts() {
    Object.values(this.chartInstances).forEach(c => { try { c.destroy(); } catch {} });
    this.chartInstances = {};
},

renderCharts() {
    this.destroyCharts();
    if (!this.dashStats) { console.log('[PMO] renderCharts: no dashStats, skipping'); return; }
    if (typeof Chart === 'undefined') {
        console.error('[PMO] Chart.js is not loaded — charts will not render');
        this.dashChartError = 'Chart.js library not loaded';
        return;
    }
    const ds = this.dashStats;
    this.dashChartError = null;

    // Common Chart.js defaults
    Chart.defaults.font.family = "'Inter', sans-serif";
    Chart.defaults.font.size = 11;
    Chart.defaults.color = '#94a3b8';

    // 1. Backlog by Phase — horizontal bar
    try {
        const phaseEl = document.getElementById('chartBacklogPhase');
        console.log('[PMO] chartBacklogPhase element:', phaseEl, 'size:', phaseEl ? `${phaseEl.offsetWidth}x${phaseEl.offsetHeight}` : 'N/A');
        if (phaseEl) {
            const phases = Object.keys(ds.phase_distribution || {});
            const counts = Object.values(ds.phase_distribution || {});
            const phaseColors = phases.map((p, i) => {
                const palette = ['#6366f1', '#8b5cf6', '#a855f7', '#3b82f6', '#7c3aed', '#10b981', '#f59e0b', '#ef4444'];
                return palette[i % palette.length];
            });
            this.chartInstances.phase = new Chart(phaseEl, {
                type: 'bar',
                data: { labels: phases.length ? phases : ['No data'], datasets: [{ data: counts.length ? counts : [0], backgroundColor: phaseColors, borderRadius: 6, barThickness: 18 }] },
                options: {
                    indexAxis: 'y',
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false }, tooltip: { backgroundColor: '#1e293b', padding: 8, cornerRadius: 8, titleFont: { size: 11 }, bodyFont: { size: 11 } } },
                    scales: { x: { display: false, beginAtZero: true }, y: { grid: { display: false }, ticks: { font: { size: 10 } } } },
                },
            });
            console.log('[PMO] Backlog chart created:', !!this.chartInstances.phase);
        }
    } catch (e) {
        console.error('[PMO] Backlog chart error:', e);
        this.dashChartError = `Bar chart: ${e.message}`;
    }

    // 2. Release Cycle — doughnut
    try {
        const releaseEl = document.getElementById('chartReleaseCycle');
        console.log('[PMO] chartReleaseCycle element:', releaseEl, 'size:', releaseEl ? `${releaseEl.offsetWidth}x${releaseEl.offsetHeight}` : 'N/A');
        if (releaseEl) {
            const rLabels = Object.keys(ds.release_status_distribution || {});
            const rValues = Object.values(ds.release_status_distribution || {});
            const rColors = { 'Planning': '#6366f1', 'In Progress': '#8b5cf6', 'Testing': '#a855f7', 'UAT': '#3b82f6', 'Pre-Release': '#7c3aed', 'Released': '#10b981', 'Post-Release': '#f59e0b', 'Cancelled': '#ef4444' };
            const colors = rLabels.map(l => rColors[l] || '#94a3b8');
            if (!rLabels.length) { rLabels.push('No releases'); rValues.push(1); colors.push('#e2e8f0'); }
            this.chartInstances.release = new Chart(releaseEl, {
                type: 'doughnut',
                data: { labels: rLabels, datasets: [{ data: rValues, backgroundColor: colors, borderWidth: 0, hoverOffset: 6 }] },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    cutout: '65%',
                    plugins: { legend: { position: 'bottom', labels: { boxWidth: 8, boxHeight: 8, padding: 8, font: { size: 9 } } }, tooltip: { backgroundColor: '#1e293b', padding: 8, cornerRadius: 8 } },
                },
            });
            console.log('[PMO] Release chart created:', !!this.chartInstances.release);
        }
    } catch (e) {
        console.error('[PMO] Release chart error:', e);
        this.dashChartError = `Doughnut: ${e.message}`;
    }

    // 3. Priority Mix — doughnut
    try {
        const prioEl = document.getElementById('chartPriority');
        console.log('[PMO] chartPriority element:', prioEl, 'size:', prioEl ? `${prioEl.offsetWidth}x${prioEl.offsetHeight}` : 'N/A');
        if (prioEl) {
            const pLabels = Object.keys(ds.priority_distribution || {});
            const pValues = Object.values(ds.priority_distribution || {});
            const prioColors = { 'Critical': '#ef4444', 'High': '#f59e0b', 'Medium': '#6366f1', 'Low': '#94a3b8' };
            const pColors = pLabels.map(l => prioColors[l] || '#94a3b8');
            if (!pLabels.length) { pLabels.push('No items'); pValues.push(1); pColors.push('#e2e8f0'); }
            this.chartInstances.priority = new Chart(prioEl, {
                type: 'doughnut',
                data: { labels: pLabels, datasets: [{ data: pValues, backgroundColor: pColors, borderWidth: 0, hoverOffset: 6 }] },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    cutout: '65%',
                    plugins: { legend: { position: 'bottom', labels: { boxWidth: 8, boxHeight: 8, padding: 8, font: { size: 9 } } }, tooltip: { backgroundColor: '#1e293b', padding: 8, cornerRadius: 8 } },
                },
            });
            console.log('[PMO] Priority chart created:', !!this.chartInstances.priority);
        }
    } catch (e) {
        console.error('[PMO] Priority chart error:', e);
        this.dashChartError = `Priority: ${e.message}`;
    }
},

kpiProgressPct(kpi) {
    return this.kpiProgress(kpi);
},

};

// PMO System — app/backlog.js
// Backlog domain of the Alpine pmoApp() store.
// Fragments are verbatim from the original monolith; pmo-app.js assembles them.

export const backlog = {
// ===== Backlog state =====
backlogItems: [],
backlogFormMode: 'feature',  // 'feature' or 'epic'
backlogSearch: '',  // search query for backlog items
boardGroupBy: '',  // list grouping: '' = epic, or type | priority | assignee | phase
    projectViews: [],  // saved views for this project
    viewsLoading: false,
    savingView: false,
    viewSaveName: '',
    activeViewName: '',
releaseItemSearch: '',  // search query for adding backlog items to release
showReleaseItemSearch: false,
// Infrastructure module
infraSubTab: 'overview',
infraOverview: null,
infraEnvironments: [],
infraSecrets: [],
infraAssets: [],
infraServices: [],
infraDatabases: [],
revealedSecrets: {},
secretAuditData: null,
showInfraEnvForm: false,
editingInfraEnvId: null,
infraEnvForm: { name: '', type: 'development', url: '', description: '', status: 'active' },
showInfraSecretForm: false,
editingInfraSecretId: null,
infraSecretForm: { name: '', category: '', environment_id: '', value: '', description: '', expires_at: '' },
showInfraAssetForm: false,
editingInfraAssetId: null,
infraAssetForm: { name: '', asset_type: '', environment_id: '', team: '', status: 'active', cost_monthly: '', metadata_json: '' },
showInfraServiceForm: false,
editingInfraServiceId: null,
infraServiceForm: { name: '', service_type: 'internal', environment_id: '', documentation_url: '' },
showInfraDbForm: false,
editingInfraDbId: null,
infraDbForm: { name: '', db_type: 'postgresql', host: '', port: '', environment_id: '', backup_policy: '' },
phaseFilter: null,  // filter backlog by phase
get phaseCounts() {
    const counts = {};
    for (const item of this.backlogItems) {
        counts[item.current_phase] = (counts[item.current_phase] || 0) + 1;
    }
    return counts;
},
get filteredBacklogItems() {
    if (!this.phaseFilter) return this.backlogItems;
    if (this.phaseFilter === 'In Release') {
        return this.backlogItems.filter(i =>
            ['UAT', 'Pre-Release'].includes(i.current_phase)
        );
    }
    if (this.phaseFilter === 'Released') {
        return this.backlogItems.filter(i =>
            ['Release', 'Post-Release', 'Retrospective'].includes(i.current_phase) || i.status === 'Done'
        );
    }
    return this.backlogItems.filter(i => i.current_phase === this.phaseFilter);
},
get releaseFilterCounts() {
    const inRelease = this.backlogItems.filter(i =>
        ['UAT', 'Pre-Release'].includes(i.current_phase)
    ).length;
    const released = this.backlogItems.filter(i =>
        ['Release', 'Post-Release', 'Retrospective'].includes(i.current_phase) || i.status === 'Done'
    ).length;
    return { inRelease, released };
},
get requiredRoles() {
    // The 6 gate-keeper roles required by the Release Process V-cycle
    // Aligned to RACI Matrix v2.3
    const defs = [
        {role: 'Product Manager', gate: 'Prepares release notes, UAT gate, PIV', icon: '📋'},
        {role: 'Product Owner', gate: 'Planning gate — requirements sign-off', icon: '🎯'},
        {role: 'Tech Lead', gate: 'In Progress gate — code readiness', icon: '⚙️'},
        {role: 'QA Lead', gate: 'Testing gate — SIT sign-off', icon: '🔬'},
        {role: 'DevOps Lead', gate: 'Pre-Release + Released gates — deployment', icon: '🚀'},
        {role: 'UX Designer', gate: 'UX sign-off gate (if UX required)', icon: '🎨'},
    ];
    // Also check stakeholders (external people assigned with these roles)
    const stakeholderRoles = this.projectStakeholders.map(s => s.role_name);
    return defs.map(d => {
        const assignment = this.projectAssignments.find(a => a.role_name === d.role);
        const stakeholder = this.projectStakeholders.find(s => s.role_name === d.role);
        const assignedName = assignment ? assignment.user_name : (stakeholder ? stakeholder.name : null);
        return {...d, assigned: !!assignedName, assignedName};
    });
},
get requiredRolesAssigned() {
    return this.requiredRoles.filter(r => r.assigned).length;
},
collapsedEpics: [],
expandedEpicDesc: {},  // epic name → true for expanded description
backlogForm: { title: '', description: '', priority: 'Medium', kpi_id: '', epic: '', item_type: 'Feature', primary_actor: '', story_points: null, target_release: '', dependencies: '', depends_on: [] },
availableDeps: [],  // backlog items available to select as dependencies
// GitHub Board integration
githubBoardConfig: { repo: '', project_node_id: '', project_title: '', project_url: '', default_labels: 'from-pmo', auto_export: false, export_trigger_phase: 'Development', issue_title_prefix: '', include_acceptance_criteria: true, include_dependencies: true },
githubProjects: [],  // available GitHub Project V2 boards
githubLoadingProjects: false,
githubBoardUrlInput: '',  // input for pasting a board URL
githubResolvingBoard: false,  // resolving board URL in progress
githubSyncStatus: null,  // sync status for current project
itemSubitems: [],  // sub-items of the drawer item
itemBacklinks: [],  // items whose description references this one (#N)
    subitemRollup: { total: 0, done: 0, pct: 0 },
    newSubitemTitle: '',
    githubSyncingTags: false,  // two-way tag ↔ label sync in progress
githubExportResult: null,  // last export result
githubImportResult: null,  // last import result
githubImporting: false,  // import in progress
editingBacklogId: null,  // track which backlog item is being edited
viewingBacklogItem: null,  // backlog item being viewed in detail modal
suggestedVersion: null,  // auto-suggested next SemVer version
sharedWith: null,  // result of sharing release notes
pdfViewerUrl: null,  // URL for PDF viewer modal
depSearch: '',  // search text for dependency autocomplete
depSearchFocused: false,
filteredDeps: [],  // filtered results for dependency autocomplete
epicForm: { name: '', description: '' },
// Full 9-phase process (for reference)
phases: ['Requirements', 'Design', 'Development', 'Testing', 'UAT', 'Pre-Release', 'Release', 'Post-Release', 'Retrospective'],
// Item-level phases (features/bugs advance through these only)
itemPhases: ['Requirements', 'Design', 'Development', 'Testing', 'Ready for UAT'],
backlogView: 'list',  // 'list' | 'board' — board is the Kanban by phase
backlogBoardColumns: [],  // [{ phase, items }] built by buildBacklogBoard
dragItem: null,  // { id, fromPhase } while dragging a board card
dragOverPhase: null,  // phase the dragged card is hovering over
dropIndex: null,  // 'before' | 'after' — insert gap while dragging over a card
quickAddPhase: null,  // phase whose quick-add input is open
quickAddTitle: '',  // quick-add input text
quickAddSaving: false,
// Release-level phases (the release as a whole goes through these)
releasePhases: ['UAT', 'Pre-Release', 'Release', 'Post-Release', 'Retrospective'],


// ===== Backlog computed: epic list + grouped items =====
get epicOptions() {
    const epics = new Set();
    for (const item of this.backlogItems) {
        if (item.epic && item.epic !== '—') epics.add(item.epic);
    }
    return Array.from(epics).sort();
},
get milestoneOptions() {
    // Get milestones for the selected project in task form
    if (!this.taskForm.project_id) return [];
    const proj = this.projects.find(p => p.id === this.taskForm.project_id);
    if (!proj || !proj._roadmaps) return [];
    const milestones = [];
    for (const r of proj._roadmaps) {
        if (r.milestones) {
            for (const m of r.milestones) {
                milestones.push({ id: m.id, title: m.title });
            }
        }
    }
    return milestones;
},

get aiGroupedSuggestions() {
    // Group AI features under their epics
    const epics = this.aiModalContent?.suggested_epics || [];
    const features = this.aiModalContent?.suggested_features || [];
    const groups = [];

    // For each suggested epic, find its features
    for (let i = 0; i < epics.length; i++) {
        const epic = epics[i];
        const epicFeatures = [];
        for (let j = 0; j < features.length; j++) {
            if (features[j].epic === epic.title) {
                epicFeatures.push({ ...features[j], _origIdx: j });
            }
        }
        groups.push({ epic, epicIdx: i, features: epicFeatures });
    }

    // Features whose epic is NOT a suggested epic (existing epics)
    const suggestedEpicTitles = epics.map(e => e.title);
    const orphanFeatures = [];
    for (let j = 0; j < features.length; j++) {
        if (!suggestedEpicTitles.includes(features[j].epic)) {
            orphanFeatures.push({ ...features[j], _origIdx: j });
        }
    }
    if (orphanFeatures.length > 0) {
        groups.push({ epic: null, epicIdx: -1, features: orphanFeatures });
    }

    return groups;
},

get backlogGrouped() {
    if (!this.boardGroupBy || this.boardGroupBy === 'epic') return this.backlogByEpic;
    let items = this.phaseFilter ? this.filteredBacklogItems : this.backlogItems;
    if (this.backlogSearch && this.backlogSearch.trim()) {
        const q = this.backlogSearch.trim().toLowerCase();
        items = items.filter(i =>
            (i.title || '').toLowerCase().includes(q) ||
            (i.description || '').toLowerCase().includes(q) ||
            (i.epic || '').toLowerCase().includes(q) ||
            (i.acceptance_criteria || '').toLowerCase().includes(q) ||
            (i.primary_actor || '').toLowerCase().includes(q) ||
            (i.item_type || '').toLowerCase().includes(q)
        );
    }
    const field = this.boardGroupBy;
    const groups = {};
    for (const i of items) {
        let key;
        if (field === 'assignee') key = i.assigned_to_name || 'Unassigned';
        else key = i[field] || 'None';
        (groups[key] = groups[key] || []).push(i);
    }
    return Object.keys(groups).sort().map(k => ({ key: k, label: k, items: groups[k] }));
},

get backlogByEpic() {
    let items = this.phaseFilter ? this.filteredBacklogItems : this.backlogItems;
    // Apply search filter
    if (this.backlogSearch && this.backlogSearch.trim()) {
        const q = this.backlogSearch.trim().toLowerCase();
        items = items.filter(i =>
            (i.title || '').toLowerCase().includes(q) ||
            (i.description || '').toLowerCase().includes(q) ||
            (i.epic || '').toLowerCase().includes(q) ||
            (i.acceptance_criteria || '').toLowerCase().includes(q) ||
            (i.primary_actor || '').toLowerCase().includes(q) ||
            (i.item_type || '').toLowerCase().includes(q)
        );
    }
    const epicItems = items.filter(i => i.item_type === 'Epic');
    const featureItems = items.filter(i => i.item_type !== 'Epic');
    const groups = {};

    // First, create groups from existing epic items
    for (const e of epicItems) {
        groups[e.epic || e.title] = { epicItem: e, items: [] };
    }
    // Group features by their epic field
    for (const item of featureItems) {
        const epicName = item.epic && item.epic !== '—' ? item.epic : 'Uncategorized';
        if (!groups[epicName]) groups[epicName] = { epicItem: null, items: [] };
        groups[epicName].items.push(item);
    }
    // Return as array, with Uncategorized last
    const entries = Object.entries(groups).map(([epic, data]) => ({ epic, ...data }));
    entries.sort((a, b) => {
        if (a.epic === 'Uncategorized') return 1;
        if (b.epic === 'Uncategorized') return -1;
        return a.epic.localeCompare(b.epic);
    });
    return entries;
},

// Avatar colors based on name
avatarColor(name) {
    const colors = [
        'bg-gradient-to-br from-rose-400 to-pink-500',
        'bg-gradient-to-br from-blue-400 to-indigo-500',
        'bg-gradient-to-br from-emerald-400 to-teal-500',
        'bg-gradient-to-br from-amber-400 to-orange-500',
        'bg-gradient-to-br from-violet-400 to-purple-500',
        'bg-gradient-to-br from-cyan-400 to-blue-500',
    ];
    const hash = name.charCodeAt(0) % colors.length;
    return colors[hash];
},

renderMarkdown(text) {
    if (!text) return '';
    const autolinkRefs = (html) => html.replace(/#(\d+)/g, '<a data-item-id="$1" class="item-ref cursor-pointer font-medium text-brand-600 hover:text-brand-700 hover:underline" title="Open item #$1">#$1</a>');
    try {
        if (typeof marked !== 'undefined') {
            marked.setOptions({ breaks: true, gfm: true });
            return autolinkRefs('<div class="md-content">' + marked.parse(text) + '</div>');
        }
    } catch(e) {}
    // Fallback: convert newlines to <br>
    return autolinkRefs('<div class="md-content">' + text.replace(/\n/g, '<br>') + '</div>');
},

async openItemRef(id) {
    // Open a #N reference — fetch the item if it is not already loaded
    const known = (this.backlogItems || []).find(i => i.id === Number(id));
    if (known) { this.viewBacklogItem(known); return; }
    try {
        const item = await this.api('GET', `/backlog/${id}`);
        if (item) this.viewBacklogItem(item);
    } catch { /* deleted or foreign item — no-op */ }
},

async loadBacklinks(itemId) {
    if (!itemId) return;
    try {
        this.itemBacklinks = await this.api('GET', `/backlog/${itemId}/backlinks`);
    } catch { this.itemBacklinks = []; }
},

applyBranding() {
    const b = this.tenantBranding;
    if (!b) return;
    if (b.primary_color) {
        const hex = b.primary_color;
        const r = parseInt(hex.slice(1,3), 16);
        const g = parseInt(hex.slice(3,5), 16);
        const bl = parseInt(hex.slice(5,7), 16);
        document.documentElement.style.setProperty('--brand-r', r);
        document.documentElement.style.setProperty('--brand-g', g);
        document.documentElement.style.setProperty('--brand-b', bl);
        document.documentElement.style.setProperty('--brand-color', hex);
    }
    if (b.app_name) {
        document.title = b.app_name + ' — PMO System';
    }
},

resetBranding() {
    // Clear tenant branding — restore PMO System defaults
    this.tenantBranding = null;
    document.documentElement.style.removeProperty('--brand-r');
    document.documentElement.style.removeProperty('--brand-g');
    document.documentElement.style.removeProperty('--brand-b');
    document.documentElement.style.removeProperty('--brand-color');
    document.title = 'PMO System';
},

async init() {
    // Check for reset token in URL (from email link)
    const urlParams = new URLSearchParams(window.location.search);
    const resetToken = urlParams.get('reset_token');
    if (resetToken) {
        this.forgotPasswordToken = resetToken;
        // Auto-open the reset form so the user can set a new password
        this.showForgotPassword = true;
        this.forgotPasswordStep = 'reset';
        // Clean the URL
        window.history.replaceState({}, document.title, window.location.pathname);
    }

    // Load tenant branding from subdomain (if not already injected by server)
    if (!this.tenantBranding) {
        try {
            this.tenantBranding = await this.api('GET', '/branding');
            this.applyBranding();
        } catch { /* root domain — no branding */ }
    } else {
        this.applyBranding();
    }

    // Check for stored token
    const token = localStorage.getItem('pmo_token');
    if (token) {
        this.authToken = token;
        try {
            const user = await this.api('GET', '/auth/me');
            this.currentUser = user;
            this.isLoggedIn = true;
        } catch {
            localStorage.removeItem('pmo_token');
            this.authToken = null;
        }
    }
    if (this.isLoggedIn) {
        if (this.isSuperAdmin) {
            // Super admin: load admin dashboard, skip tenant data
            this.resetBranding();  // Super admin: no tenant branding
            this.route = 'admin-dashboard';
            await this.loadAdminInsights();
            await this.loadAdminPlans();
        } else {
            // Tenant user: load tenant branding + workspace data
            await this.loadTenant();  // Load branding for sidebar/logo
            this.applyBranding();  // Apply CSS variables + title
            await Promise.all([this.loadClients(), this.loadProjects(), this.loadDashboard(), this.loadRoles(), this.loadUsers(), this.loadNotifications(), this.loadActivity(), this.checkAIStatus()]);
            // Poll notifications every 30 seconds
            setInterval(() => this.loadNotifications(), 30000);
        }
    }
    // Sliding session: refresh the token before the 8h expiry (at 6h mark),
    // then keep it fresh every 30 minutes of activity.
    const REFRESH_MS = 30 * 60 * 1000;
    setInterval(async () => {
        if (!this.isLoggedIn || document.hidden) return;  // only active tabs
        try {
            const res = await this.api('POST', '/auth/refresh');
            if (res && res.access_token) {
                this.authToken = res.access_token;
                localStorage.setItem('pmo_token', res.access_token);
            }
        } catch { /* 401 handled by api() — logs the user out */ }
    }, REFRESH_MS);

    setInterval(() => {
        this.currentTime = new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
    }, 60000);
},


// ===== Backlog =====
async loadBacklog() {
    try {
        this.backlogItems = await this.api('GET', `/projects/${this.selectedProject.id}/backlog`);
        this.loadAvailableDeps(this.selectedProject.id, this.editingBacklogId || 0);
    } catch {
        this.backlogItems = [];
    }
},

async saveBacklogItem(saveAndNew = false) {
    try {
        if (this.backlogFormMode === 'epic') {
            // Create an epic as a BacklogItem with item_type='Epic'
            const epicName = this.epicForm.name.trim();
            if (!epicName) { this.showToast('Epic name is required', 'error'); return; }
            await this.api('POST', `/projects/${this.selectedProject.id}/backlog`, {
                project_id: this.selectedProject.id,
                title: epicName,
                description: this.epicForm.description || '',
                item_type: 'Epic',
                epic: epicName,
                priority: 'Medium',
                current_phase: 'Requirements',
                status: 'Draft',
            });
            this.epicForm = { name: '', description: '' };
            await this.loadBacklog();
            if (saveAndNew) {
                this.showToast('Epic saved — add another', 'success');
            } else {
                this.backlogFormMode = 'feature';
                this.showBacklogForm = false;
                this.showToast('Epic added', 'success');
            }
        } else {
            // Feature / Story mode
            const pendingDeps = [...(this.backlogForm.depends_on || [])];
            const created = await this.api('POST', `/projects/${this.selectedProject.id}/backlog`, {
                project_id: this.selectedProject.id,
                title: this.backlogForm.title,
                description: this.backlogForm.description,
                priority: this.backlogForm.priority,
                kpi_id: this.backlogForm.kpi_id || null,
                epic: this.backlogForm.epic,
                item_type: this.backlogForm.item_type,
                primary_actor: this.backlogForm.primary_actor,
                story_points: this.backlogForm.story_points || null,
                target_release: this.backlogForm.target_release,
                acceptance_criteria: this.backlogForm.acceptance_criteria,
                dependencies: this.backlogForm.dependencies,
            });
            // Add any pending dependencies collected during creation
            for (const dep of pendingDeps) {
                try {
                    await this.api('POST', `/backlog/${created.id}/dependencies`, { depends_on_id: dep.id });
                } catch(e) { /* skip if fails */ }
            }
            this.editingBacklogId = created.id;
            this.loadAvailableDeps(this.selectedProject.id, created.id);
            const savedEpic = this.backlogForm.epic;
            await this.loadBacklog();
            if (saveAndNew) {
                // Keep epic + actor for rapid entry, clear the rest
                this.backlogForm = {
                    title: '', description: '', priority: this.backlogForm.priority,
                    kpi_id: this.backlogForm.kpi_id, epic: savedEpic,
                    item_type: this.backlogForm.item_type, primary_actor: this.backlogForm.primary_actor,
                    story_points: null, target_release: this.backlogForm.target_release,
                    dependencies: '', depends_on: [],
                };
                this.showToast('Item saved — add another', 'success');
            } else {
                this.backlogForm = { title: '', description: '', priority: 'Medium', kpi_id: '', epic: '', item_type: 'Feature', primary_actor: '', story_points: null, target_release: '', dependencies: '', depends_on: [] };
                this.showBacklogForm = false;
                this.showToast('Backlog item added — manage dependencies below', 'success');
            }
        }
    } catch (e) {
        this.showToast(e.message, 'error');
    }
},

addFeatureToEpic(epicName) {
    this.backlogFormMode = 'feature';
    this.backlogForm.epic = epicName;
    this.backlogForm.item_type = 'Feature';
    // Scroll to form
    this.$nextTick(() => {
        const form = document.getElementById('backlog-form');
        if (form) form.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
},

toggleEpic(epicName) {
    const idx = this.collapsedEpics.indexOf(epicName);
    if (idx >= 0) {
        this.collapsedEpics.splice(idx, 1);
    } else {
        this.collapsedEpics.push(epicName);
    }
},

toggleEpicDesc(epicName) {
    this.expandedEpicDesc[epicName] = !this.expandedEpicDesc[epicName];
},

async sendBackToDev(id) {
    try {
        await this.api('POST', `/backlog/${id}/send-back`);
        await this.loadBacklog();
        if (this.viewingBacklogItem) {
            this.viewingBacklogItem = this.backlogItems.find(i => i.id === id);
        }
        this.showToast('Sent back to Development', 'info');
    } catch (e) {
        this.showToast(e.message, 'error');
    }
},

async advanceBacklogItem(id) {
    try {
        await this.api('POST', `/backlog/${id}/advance`);
        await this.loadBacklog();
        this.showToast('Phase advanced', 'success');
    } catch (e) {
        this.showToast(e.message, 'error');
    }
},

// ─── Board view (Kanban by phase) ───
buildBacklogBoard() {
    // One column per item-level phase; items grouped by current_phase.
    // Epic-type items are not on the board (they're groupings, not work).
    const pool = this.backlogItems.filter(i => i.item_type !== 'Epic');
    this.backlogBoardColumns = this.itemPhases.map(phase => ({
        phase,
        items: pool.filter(i => (i.current_phase || '') === phase).sort((a, b) => this.boardItemCompare(a, b)),
    }));
    // Stragglers in phases outside the template (legacy values) go to the last column's tail
    const known = new Set(this.itemPhases);
    const stragglers = pool.filter(i => !known.has(i.current_phase || ''));
    if (stragglers.length) {
        this.backlogBoardColumns[this.backlogBoardColumns.length - 1].items.push(...stragglers);
    }
},
boardCount(phase) {
    const col = (this.backlogBoardColumns || []).find(c => c.phase === phase);
    return col ? col.items.length : 0;
},
// Lane sort: manual board_order first (lower = higher), never-ordered cards
// by created_at ascending (oldest at top, newest at bottom of the tail).
boardItemCompare(a, b) {
    const ao = a.board_order, bo = b.board_order;
    if (ao != null && bo != null) return ao - bo;
    if (ao != null) return -1;
    if (bo != null) return 1;
    return String(a.created_at || '').localeCompare(String(b.created_at || ''));
},
dragStart(item, fromPhase) {
    this.dragItem = { id: item.id, fromPhase };
},
dragEnd() {
    this.dragItem = null;
    this.dragOverPhase = null;
    this.dropIndex = null;
},
allowDrop(phase) {
    this.dragOverPhase = phase;
},
cardDragOver(item, colPhase, ev) {
    // Compute the insert gap: above or below the hovered card
    if (!this.dragItem) return;
    const rect = ev.currentTarget.getBoundingClientRect();
    this.dropIndex = (ev.clientY - rect.top) < rect.height / 2 ? 'before' : 'after';
    this.dragOverPhase = colPhase;
},
cardDrop(item, colPhase, ev) {
    // Drop on a card = insert at its gap (same lane) or phase change (cross-lane)
    if (!this.dragItem) return;
    const movedId = this.dragItem.id;
    if (this.dragItem.fromPhase !== colPhase) { this.reorderCard(movedId, colPhase, null, null); return; }
    if (item.id === movedId) { this.dragEnd(); return; }  // dropped on itself — no-op
    if (this.dropIndex === 'before') this.reorderCard(movedId, colPhase, item.id, null);
    else this.reorderCard(movedId, colPhase, null, item.id);
},
async reorderCard(movedId, colPhase, beforeId, afterId) {
    // Cross-lane drops (phase change) delegate to dropToPhase
    if (this.dragItem && this.dragItem.fromPhase !== colPhase) {
        const phase = colPhase;
        this.dropIndex = null;
        await this.dropToPhase(phase);
        return;
    }
    this.dragEnd();
    if (!movedId || !this.selectedProject) return;
    const col = (this.backlogBoardColumns || []).find(c => c.phase === colPhase);
    if (!col) return;
    const ids = col.items.map(i => i.id).filter(id => id !== movedId);
    let idx;
    if (beforeId != null) idx = ids.indexOf(beforeId);
    else if (afterId != null) idx = ids.indexOf(afterId) + 1;
    else idx = ids.length;
    if (idx < 0) idx = ids.length;
    ids.splice(idx, 0, movedId);
    // Persist the full lane order as per-lane counters
    const payload = ids.map((id, pos) => ({ id, board_order: pos }));
    try {
        await this.api('PUT', '/backlog/board-order', { order: payload });
        await this.loadBacklog();
        this.buildBacklogBoard();
    } catch (e) { this.showToast(e.message, 'error'); }
},
async dropToPhase(phase) {
    if (!this.dragItem || !this.selectedProject) { this.dragEnd(); return; }
    const { id, fromPhase } = this.dragItem;
    this.dragEnd();
    if (phase === fromPhase) return;
    // Release-level items are managed by the release workflow — don't drag them
    if (this.releasePhases.includes(phase) || this.releasePhases.includes(fromPhase)) {
        this.showToast('Release stages are managed by the release workflow', 'info');
        return;
    }
    try {
        await this.api('PUT', `/backlog/${id}`, { current_phase: phase });
        // Optimistic refresh: rebuild the board from fresh data
        await this.loadBacklog();
        this.buildBacklogBoard();
        if (phase === 'Development') this.showToast('Moved to Development — syncing to GitHub', 'success');
        else this.showToast(`Moved to ${phase}`, 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},
openBoard() {
    this.backlogView = 'board';
    this.buildBacklogBoard();
},
// ─── Quick-add on the board ───
toggleQuickAdd(phase) {
    if (this.quickAddPhase === phase) {
        this.quickAddPhase = null;
        this.quickAddTitle = '';
    } else {
        this.quickAddPhase = phase;
        this.quickAddTitle = '';
        this.$nextTick(() => {
            const el = document.getElementById('quick-add-' + CSS.escape(phase));
            if (el) el.focus();
        });
    }
},
parseQuickAdd(raw) {
    // Smart parse: "!1..4" or "!(low|medium|high|critical)" prefix sets priority,
    // "#N" sets story points, "3x" at start also sets points. The rest is the title.
    let title = raw.trim();
    let priority = null;
    let points = null;
    const pmap = { '1': 'Low', '2': 'Medium', '3': 'High', '4': 'Critical' };
    const pm = title.match(/^!(?:([1-4])|(low|medium|high|critical|crit))\s+/i);
    if (pm) {
        priority = pm[1] ? pmap[pm[1]] : (pm[2].toLowerCase() === 'crit' ? 'Critical' : pm[2][0].toUpperCase() + pm[2].slice(1).toLowerCase());
        title = title.slice(pm[0].length);
    }
    const sm = title.match(/^(\d{1,2})x\s+/i) || title.match(/\s#(\d{1,2})$/);
    if (sm) {
        points = parseInt(sm[1], 10);
        title = (title.slice(0, sm.index) + title.slice(sm.index + sm[0].length)).trim();
    }
    return { title, priority, points };
},
async quickAdd(phase) {
    if (this.quickAddSaving) return;
    const parsed = this.parseQuickAdd(this.quickAddTitle);
    if (!parsed.title) { this.showToast('Type a title first', 'info'); return; }
    if (this.releasePhases.includes(phase)) {
        this.showToast('Release stages are managed by the release workflow', 'info');
        return;
    }
    this.quickAddSaving = true;
    try {
        await this.api('POST', `/projects/${this.selectedProject.id}/backlog`, {
            project_id: this.selectedProject.id,
            title: parsed.title,
            item_type: 'Feature',
            current_phase: phase,
            priority: parsed.priority || 'Medium',
            story_points: parsed.points,
        });
        this.quickAddTitle = '';  // keep the input open for rapid entry
        await this.loadBacklog();
        this.buildBacklogBoard();
        this.showToast('Added to ' + phase, 'success');
    } catch (e) {
        this.showToast(e.message, 'error');
    } finally {
        this.quickAddSaving = false;
    }
},

async deleteBacklogItem(id) {
    try {
        await this.api('DELETE', `/backlog/${id}`);
        await this.loadBacklog();
        this.showToast('Item deleted', 'success');
    } catch (e) {
        this.showToast(e.message, 'error');
    }
},

// ─── GitHub Board integration ───
async loadGithubBoardConfig(projectId) {
    if (!projectId) return;
    try {
        this.githubBoardConfig = await this.api('GET', `/projects/${projectId}/github-config`);
    } catch (e) {
        // Config doesn't exist yet — use defaults
        this.githubBoardConfig = { repo: '', project_node_id: '', project_title: '', project_url: '', default_labels: 'from-pmo', auto_export: false, export_trigger_phase: 'Development', issue_title_prefix: '', include_acceptance_criteria: true, include_dependencies: true };
    }
},

async loadGithubSyncStatus(projectId) {
    if (!projectId) return;
    try {
        this.githubSyncStatus = await this.api('GET', `/projects/${projectId}/github/sync-status`);
    } catch (e) {
        this.githubSyncStatus = null;
    }
},

async loadGithubProjects() {
    const projectId = this.selectedProject?.id;
    if (!projectId) return;
    this.githubLoadingProjects = true;
    try {
        this.githubProjects = await this.api('GET', `/projects/${projectId}/github/projects`);
        if (this.githubProjects.length === 0) {
            this.showToast('No GitHub Project V2 boards found. Make sure the token has "project" scope.', 'info');
        }
    } catch (e) {
        this.showToast(e.message || 'Failed to load GitHub projects', 'error');
        this.githubProjects = [];
    } finally {
        this.githubLoadingProjects = false;
    }
},

onGithubProjectSelected() {
    // Update project_title and project_url when a project is selected
    const selected = this.githubProjects.find(p => p.id === this.githubBoardConfig.project_node_id);
    this.githubBoardConfig.project_title = selected ? selected.title : '';
    this.githubBoardConfig.project_url = selected ? selected.url : '';
},

async resolveBoardUrl() {
    const projectId = this.selectedProject?.id;
    if (!projectId || !this.githubBoardUrlInput) return;
    this.githubResolvingBoard = true;
    try {
        const result = await this.api('POST', `/projects/${projectId}/github/resolve-board`, { url: this.githubBoardUrlInput });
        this.githubBoardConfig.project_node_id = result.id;
        this.githubBoardConfig.project_title = result.title;
        this.githubBoardConfig.project_url = result.url;
        this.githubBoardUrlInput = '';
        this.showToast(`Connected to board: ${result.title}`, 'success');
    } catch (e) {
        this.showToast(e.message || 'Could not resolve board URL. Make sure the URL is correct and the token has "project" scope.', 'error');
    } finally {
        this.githubResolvingBoard = false;
    }
},

async saveGithubBoardConfig() {
    const projectId = this.selectedProject?.id;
    if (!projectId) return;
    try {
        this.githubBoardConfig = await this.api('PUT', `/projects/${projectId}/github-config`, this.githubBoardConfig);
        this.showToast('GitHub board configuration saved', 'success');
        await this.loadGithubSyncStatus(projectId);
    } catch (e) {
        this.showToast(e.message || 'Failed to save configuration', 'error');
    }
},

async exportToGithub(itemIds) {
    const projectId = this.selectedProject?.id;
    if (!projectId) return;
    try {
        this.githubExportResult = await this.api('POST', `/projects/${projectId}/github/export`, { item_ids: itemIds || [] });
        const r = this.githubExportResult;
        if (r.exported > 0) {
            this.showToast(`Exported ${r.exported} item(s) to GitHub`, 'success');
        } else if (r.skipped > 0 && r.exported === 0) {
            this.showToast(`All ${r.skipped} item(s) already synced`, 'info');
        } else if (r.failed > 0) {
            this.showToast(`Export failed for ${r.failed} item(s)`, 'error');
        } else {
            this.showToast('No items to export', 'info');
        }
        await this.loadBacklog();
        await this.loadGithubSyncStatus(projectId);
    } catch (e) {
        this.showToast(e.message || 'Export failed', 'error');
    }
},

async importFromGithub() {
    const projectId = this.selectedProject?.id;
    if (!projectId) return;
    this.githubImporting = true;
    try {
        this.githubImportResult = await this.api('POST', `/projects/${projectId}/github/import`);
        const r = this.githubImportResult;
        if (r.updated > 0) {
            this.showToast(`Synced from GitHub: ${r.updated} item(s) updated, ${r.closed_count} closed`, 'success');
        } else if (r.failed > 0 && r.updated === 0) {
            this.showToast(`Sync failed for ${r.failed} item(s)`, 'error');
        } else {
            this.showToast(`All ${r.unchanged} item(s) up to date`, 'info');
        }
        await this.loadBacklog();
        await this.loadGithubSyncStatus(projectId);
    } catch (e) {
        this.showToast(e.message || 'Import failed', 'error');
    } finally {
        this.githubImporting = false;
    }
},

// ─── Backlog dependency management ───
async loadAvailableDeps(projectId, excludeId) {
    if (!projectId) return;
    try {
        this.availableDeps = await this.api('GET', `/projects/${projectId}/backlog/available-dependencies/${excludeId || 0}`);
        // Also remove any already-selected pending deps from available list
        if (this.backlogForm.depends_on) {
            const selectedIds = this.backlogForm.depends_on.map(d => d.id);
            this.availableDeps = this.availableDeps.filter(a => !selectedIds.includes(a.id));
        }
    } catch(e) { this.availableDeps = []; }
},

async addDependency(event) {
    const targetId = parseInt(event.target.value);
    if (!targetId) return;
    event.target.value = '';
    // For new items (not yet saved), collect pending deps locally
    if (!this.editingBacklogId) {
        if (!this.backlogForm.depends_on) this.backlogForm.depends_on = [];
        const exists = this.backlogForm.depends_on.find(d => d.id === targetId);
        if (exists) { this.showToast('Already added', 'error'); return; }
        // Find the item from backlogItems to get its info
        const item = this.backlogItems.find(i => i.id === targetId);
        if (item) {
            this.backlogForm.depends_on.push({ id: item.id, title: item.title, current_phase: item.current_phase, status: item.status });
            // Update available deps (remove the one just added)
            this.availableDeps = this.availableDeps.filter(a => a.id !== targetId);
            this.showToast('Dependency added (will link on save)', 'success');
        }
        return;
    }
    // For existing items, add via API
    try {
        const updated = await this.api('POST', `/backlog/${this.editingBacklogId}/dependencies`, { depends_on_id: targetId });
        const idx = this.backlogItems.findIndex(i => i.id === this.editingBacklogId);
        if (idx >= 0) this.backlogItems[idx] = updated;
        this.backlogForm.depends_on = updated.depends_on || [];
        this.loadAvailableDeps(this.selectedProject.id, this.editingBacklogId);
        this.showToast('Dependency added', 'success');
    } catch(e) { this.showToast(e.message || 'Failed to add dependency', 'error'); }
},

async removeDependency(depId) {
    // For new items, remove from local pending list
    if (!this.editingBacklogId) {
        this.backlogForm.depends_on = (this.backlogForm.depends_on || []).filter(d => d.id !== depId);
        // Add back to available deps
        const item = this.backlogItems.find(i => i.id === depId);
        if (item) this.availableDeps.push(item);
        return;
    }
    // For existing items, remove via API
    try {
        const updated = await this.api('DELETE', `/backlog/${this.editingBacklogId}/dependencies/${depId}`);
        const idx = this.backlogItems.findIndex(i => i.id === this.editingBacklogId);
        if (idx >= 0) this.backlogItems[idx] = updated;
        this.backlogForm.depends_on = updated.depends_on || [];
        this.loadAvailableDeps(this.selectedProject.id, this.editingBacklogId);
        this.showToast('Dependency removed', 'success');
    } catch(e) { this.showToast(e.message || 'Failed to remove dependency', 'error'); }
},

editBacklogDeps(item) {
    this.editingBacklogId = item.id;
    this.backlogForm.depends_on = item.depends_on || [];
    this.loadAvailableDeps(this.selectedProject.id, item.id);
    // Scroll to the dependency selector
    this.$nextTick(() => {
        const form = document.getElementById('backlog-form');
        if (form) form.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
},

viewBacklogItem(item) {
    this.backlogEditMode = false;
    this.viewingBacklogItem = item;
    this.viewingProof = null;
    this.itemProofs = [];
    this.itemSubitems = [];
    this.subitemRollup = { total: 0, done: 0, pct: 0 };
    this.newSubitemTitle = '';
    if (item && item.id) {
        this.loadProofs(item.id);
        this.loadSubitems(item.id);
        this.loadBacklinks(item.id);
    }
},


async loadSubitems(itemId) {
    if (!itemId) return;
    try {
        const tree = await this.api('GET', `/backlog/${itemId}/tree`);
        this.itemSubitems = tree.children || [];
        this.subitemRollup = tree.rollup || { total: 0, done: 0, pct: 0 };
    } catch { this.itemSubitems = []; this.subitemRollup = { total: 0, done: 0, pct: 0 }; }
},

async addSubitem() {
    const title = (this.newSubitemTitle || '').trim();
    if (!title || !this.viewingBacklogItem) return;
    try {
        await this.api('POST', `/projects/${this.viewingBacklogItem.project_id}/backlog`, {
            project_id: this.viewingBacklogItem.project_id,
            title: title,
            parent_item_id: this.viewingBacklogItem.id,
        });
        this.newSubitemTitle = '';
        await this.loadSubitems(this.viewingBacklogItem.id);
        this.toast('Sub-item added', 'success');
    } catch(e) { this.toast(e.message || 'Could not add sub-item', 'error'); }
},


async loadViews() {
    if (!this.selectedProject) return;
    this.viewsLoading = true;
    try {
        this.projectViews = await this.api('GET', `/projects/${this.selectedProject.id}/views`);
    } catch { this.projectViews = []; }
    finally { this.viewsLoading = false; }
},

async saveCurrentView() {
    const name = (this.viewSaveName || '').trim();
    if (!name || !this.selectedProject) { this.toast('Give the view a name first', 'error'); return; }
    this.savingView = true;
    try {
        await this.api('POST', `/projects/${this.selectedProject.id}/views`, {
            name: name,
            filters: { search: this.backlogSearch || '', phase: this.phaseFilter || '', view: this.backlogView || 'list', group_by: this.boardGroupBy || '' },
            shared: true,
        });
        this.viewSaveName = '';
        await this.loadViews();
        this.toast('View saved', 'success');
    } catch(e) { this.toast(e.message || 'Could not save view', 'error'); }
    finally { this.savingView = false; }
},

applyView(v) {
    const f = v.filters || {};
    this.backlogSearch = f.search || '';
    this.phaseFilter = f.phase || null;
    this.boardGroupBy = f.group_by || '';
    if (f.view) this.backlogView = f.view;
    this.activeViewName = v.name;
    this.toast('View applied: ' + v.name, 'success');
},

clearActiveView() {
    this.backlogSearch = '';
    this.phaseFilter = null;
    this.boardGroupBy = '';
    this.activeViewName = '';
},

async syncTagsToGithub() {
    if (!this.selectedProject) return;
    this.githubSyncingTags = true;
    try {
        const result = await this.api('POST', `/projects/${this.selectedProject.id}/github/sync-tags`);
        const pushed = (result.pushed || []).length, pulled = (result.pulled || []).length;
        this.toast(`Tag sync: ${pushed} pushed, ${pulled} pulled`, 'success');
    } catch(e) { this.toast(e.message || 'Tag sync failed', 'error'); }
    finally { this.githubSyncingTags = false; }
},

async loadNextVersion(bump = 'minor') {
    if (!this.selectedProject) return;
    try {
        const result = await this.api('GET', `/projects/${this.selectedProject.id}/releases/next-version?bump=${bump}`);
        this.suggestedVersion = result.version;
    } catch(e) { this.suggestedVersion = null; }
},

filterDeps() {
    const q = (this.depSearch || '').toLowerCase().trim();
    if (!q) {
        this.filteredDeps = this.availableDeps.slice(0, 10);
    } else {
        this.filteredDeps = this.availableDeps.filter(d => {
            return ('#' + d.id).includes(q) ||
                   (d.title || '').toLowerCase().includes(q) ||
                   (d.current_phase || '').toLowerCase().includes(q);
        }).slice(0, 10);
    }
},

selectDepFromSearch(avail) {
    // Simulate the addDependency flow
    this.depSearch = '';
    this.depSearchFocused = false;
    // Reuse the addDependency logic
    if (!this.editingBacklogId) {
        // New item — collect pending dep locally
        if (!this.backlogForm.depends_on) this.backlogForm.depends_on = [];
        const exists = this.backlogForm.depends_on.find(d => d.id === avail.id);
        if (!exists) {
            this.backlogForm.depends_on.push({ id: avail.id, title: avail.title, current_phase: avail.current_phase, status: avail.status });
            this.availableDeps = this.availableDeps.filter(a => a.id !== avail.id);
            this.showToast('Dependency added (will link on save)', 'success');
        }
    } else {
        // Existing item — add via API
        this.api('POST', `/backlog/${this.editingBacklogId}/dependencies`, { depends_on_id: avail.id })
            .then(updated => {
                const idx = this.backlogItems.findIndex(i => i.id === this.editingBacklogId);
                if (idx >= 0) this.backlogItems[idx] = updated;
                this.backlogForm.depends_on = updated.depends_on || [];
                this.loadAvailableDeps(this.selectedProject.id, this.editingBacklogId);
                this.showToast('Dependency added', 'success');
            })
            .catch(e => this.showToast(e.message || 'Failed', 'error'));
    }
    this.filterDeps();
},

togglePhaseFilter(phase) {
    this.phaseFilter = this.phaseFilter === phase ? null : phase;
},

cancelEditBacklog() {
    this.backlogForm = { title: '', description: '', priority: 'Medium', kpi_id: '', epic: '', item_type: 'Feature', primary_actor: '', story_points: null, target_release: '', dependencies: '', depends_on: [] };
    this.editingBacklogId = null;
    this.loadAvailableDeps(this.selectedProject.id, 0);
},

editBacklogItem(item) {
    this.backlogEditMode = true;
    this.backlogEditForm = {
        id: item.id,
        title: item.title || '',
        description: item.description || '',
        priority: item.priority || 'Medium',
        item_type: item.item_type || 'Feature',
        primary_actor: item.primary_actor || '',
        story_points: item.story_points ?? null,
        target_release: item.target_release || '',
        acceptance_criteria: item.acceptance_criteria || '',
    };
},

async saveBacklogEdit() {
    if (!this.backlogEditForm.title?.trim()) return;
    try {
        const updated = await this.api('PUT', `/backlog/${this.backlogEditForm.id}`, this.backlogEditForm);
        this.viewingBacklogItem = updated;
        this.backlogEditMode = false;
        await this.loadBacklog();
        this.showToast('Backlog item updated', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

async saveBacklogItemEdit() {
    if (!this.editingBacklogId) return;
    try {
        const updated = await this.api('PUT', `/backlog/${this.editingBacklogId}`, {
            title: this.backlogForm.title,
            description: this.backlogForm.description,
            priority: this.backlogForm.priority,
            kpi_id: this.backlogForm.kpi_id || null,
            epic: this.backlogForm.epic,
            item_type: this.backlogForm.item_type,
            primary_actor: this.backlogForm.primary_actor,
            story_points: this.backlogForm.story_points || null,
            target_release: this.backlogForm.target_release,
            acceptance_criteria: this.backlogForm.acceptance_criteria,
            dependencies: this.backlogForm.dependencies,
        });
        // Update the item in the list
        const idx = this.backlogItems.findIndex(i => i.id === this.editingBacklogId);
        if (idx >= 0) this.backlogItems[idx] = updated;
        this.showToast('Backlog item updated', 'success');
        // Reset form
        this.backlogForm = { title: '', description: '', priority: 'Medium', kpi_id: '', epic: '', item_type: 'Feature', primary_actor: '', story_points: null, target_release: '', dependencies: '', depends_on: [] };
        this.editingBacklogId = null;
    } catch(e) { this.showToast(e.message || 'Failed to update', 'error'); }
},

phaseIndex(phase) {
    return this.phases.indexOf(phase);
},

priorityColor(priority) {
    return {
        'Critical': 'bg-rose-50 text-rose-700',
        'High': 'bg-amber-50 text-amber-700',
        'Medium': 'bg-blue-50 text-blue-700',
        'Low': 'bg-ink-100 text-ink-600',
    }[priority] || 'bg-ink-100 text-ink-600';
},

};

// PMO System — app/planning.js
// Planning domain of the Alpine pmoApp() store.
// Fragments are verbatim from the original monolith; pmo-app.js assembles them.

export const planning = {
// ===== Today + Work (R1 spine) =====
today: null,
todayLoading: false,
workItems: [],
workFilter: 'all',
workSearch: '',
workProjectFilter: '',
workLoading: false,
selectedWorkItem: null,
workDetail: null,
workDetailLoading: false,

get workFiltered() {
    let items = this.workItems;
    if (this.workProjectFilter) items = items.filter(i => String(i.project_id) === String(this.workProjectFilter));
    if (this.workSearch.trim()) {
        const q = this.workSearch.trim().toLowerCase();
        items = items.filter(i => (i.title || '').toLowerCase().includes(q) || (i.project || '').toLowerCase().includes(q));
    }
    return items;
},

async loadToday() {
    this.todayLoading = true;
    try {
        this.today = await this.api('GET', '/today');
    } catch { this.today = null; }
    this.todayLoading = false;
},

async loadWork() {
    this.workLoading = true;
    try {
        const qs = this.workFilter && this.workFilter !== 'all' ? `?filter=${this.workFilter}` : '';
        this.workItems = (await this.api('GET', `/work${qs}`)).items || [];
    } catch { this.workItems = []; }
    this.workLoading = false;
},

setWorkFilter(f) {
    this.workFilter = f;
    this.loadWork();
},

async openWorkItem(item) {
    this.selectedWorkItem = item;
    this.workDetail = null;
    this.workDetailLoading = true;
    try {
        const [brief, itemRow] = await Promise.all([
            this.api('GET', `/projects/${item.project_id}/brief`).catch(() => null),
            this.api('GET', `/backlog/${item.id}`).catch(() => null),
        ]);
        this.workDetail = { brief, item: itemRow };
    } catch { this.workDetail = { brief: null, item: null }; }
    this.workDetailLoading = false;
},

closeWorkItem() {
    this.selectedWorkItem = null;
    this.workDetail = null;
},

// Today row → Work detail drawer (approvals open the legacy project page for now)
openWorkItemFromToday(row) {
    if (row.kind === 'approval') {
        this.navigate('projects');
        return;
    }
    this.navigate('work');
    this.openWorkItem({ id: row.ref_id, title: row.title, project: row.project, project_id: row.project_id, phase: '', status: row.kind === 'blocked' ? 'Blocked' : 'In Progress', priority: '', blocked: row.kind === 'blocked', overdue: row.kind === 'overdue' });
},

// Open the legacy project detail by id (used from the Work drawer)
async openProjectById(projectId) {
    let project = (this.projects || []).find(p => String(p.id) === String(projectId));
    if (!project) {
        try { project = await this.api('GET', `/projects/${projectId}`); } catch { return; }
    }
    if (project) await this.openProject(project);
},

// ===== Project detail state =====
selectedProject: null,
selectedClient: null,
projectTab: 'overview',
vision: null,
kpis: [],
roadmaps: [],
brdCoverage: null,
visionForm: { statement: '', strategic_objectives: '' },
kpiForm: { name: '', target_value: '', current_value: '', unit: '', category: '', vision_objective: '' },
roadmapForm: { title: '', start_date: '', end_date: '' },
showRoadmapForm: false,
showBacklogForm: false,
showKpiForm: false,
showReleaseForm: false,
showStakeholderForm: false,
milestoneForm: { title: '', target_date: '', status: 'On Track' },
activeRoadmapId: null,


// ===== Milestone & KPI view/edit state =====
selectedMilestone: null,
selectedKPI: null,
editingMilestoneId: null,
editingKPIId: null,
milestoneEditMode: false,
kpiEditMode: false,
backlogEditMode: false,
backlogEditForm: {},


// ===== Traceability state =====
traceability: null,


// ===== Role helpers =====
get isSuperAdmin() { return this.currentUser?.system_role === 'super_admin'; },
get isAccountManager() { return this.currentUser?.system_role === 'account_manager' || this.isSuperAdmin; },
get isProjectManager() { return this.currentUser?.system_role === 'project_manager' || this.isAccountManager; },
get canManageUsers() { return this.currentUser?.tenant_role === 'owner' || this.currentUser?.tenant_role === 'admin'; },
get canManageClients() { return this.canManageUsers; },
get canAssignAM() { return this.canManageUsers; },
get canAssignPM() { return this.canManageUsers; },
get canAssignRoles() { return this.canManageUsers; },

allowedRoles() {
    if (this.isSuperAdmin) return ['member', 'project_manager', 'account_manager', 'super_admin'];
    if (this.isAccountManager) return ['member', 'project_manager', 'account_manager'];
    if (this.isProjectManager) return ['member'];
    return [];
},


// ===== Timeline state =====
timelineZoom: 1,
monthWidth: 80,  // base px per month at zoom=1

navItems: [
    { id: 'admin-dashboard', label: 'Dashboard', group: 'admin', icon: '<svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z"/></svg>' },
    { id: 'admin-tenants', label: 'Tenants', group: 'admin', icon: '<svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"/></svg>' },
    { id: 'admin-plans', label: 'Plans', group: 'admin', icon: '<svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>' },
    { id: 'today', label: 'Today', group: 'workspace', icon: '<svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>' },
    { id: 'work', label: 'Work', group: 'workspace', icon: '<svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"/></svg>' },
    { id: 'dashboard', label: 'Dashboard', group: 'consultant', icon: '<svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z"/></svg>' },
    { id: 'clients', label: 'Clients', group: 'consultant', icon: '<svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z"/></svg>' },
    { id: 'projects', label: 'Projects', group: 'consultant', icon: '<svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2H5a2 2 0 00-2-2z"/></svg>' },
    { id: 'tasks', label: 'My Tasks', group: 'consultant', icon: '<svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"/></svg>' },
    { id: 'roadmap', label: 'Roadmaps', group: 'planning', icon: '<svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7"/></svg>' },
    { id: 'docs', label: 'Documentation', group: 'planning', icon: '<svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"/></svg>' },
    { id: 'settings', label: 'Settings', group: 'planning', icon: '<svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/><path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/></svg>' },
],

consultantView: localStorage.getItem('consultantView') !== '0',

toggleConsultantView() {
    this.consultantView = !this.consultantView;
    localStorage.setItem('consultantView', this.consultantView ? '1' : '0');
    if (!this.consultantView && ['dashboard', 'clients', 'projects', 'tasks', 'project-detail', 'client-detail', 'roadmap'].includes(this.route)) {
        this.route = 'today';
    }
},

get visibleNavItems() {
    if (this.isSuperAdmin) return this.navItems.filter(i => i.group === 'admin');
    const groups = this.consultantView ? ['workspace', 'consultant', 'planning'] : ['workspace', 'planning'];
    return this.navItems.filter(i => groups.includes(i.group));
},

get pageTitle() {
    return { today: 'Today', work: 'Work', dashboard: 'Dashboard', clients: 'Clients', 'client-detail': 'Client Detail', projects: 'Projects', 'project-detail': 'Project Detail', tasks: 'My Tasks', roadmap: 'Roadmaps', docs: 'Documentation', settings: 'Settings' }[this.route] || '';
},
get stats() {
    const ds = this.dashStats || {};
    return [
        { label: 'Total Clients', value: ds.clients ?? this.clients.length, route: 'clients', icon: '<svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"/></svg>', bg: 'bg-brand-50', color: 'text-brand-600', glow: 'bg-brand-300', trend: 'New', trendColor: 'text-emerald-600' },
        { label: 'Active Projects', value: ds.projects ?? this.projects.length, route: 'projects', icon: '<svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2H5a2 2 0 00-2-2z"/></svg>', bg: 'bg-emerald-50', color: 'text-emerald-600', glow: 'bg-emerald-300' },
        { label: 'Backlog Items', value: ds.backlog_items ?? 0, route: 'projects', icon: '<svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"/></svg>', bg: 'bg-amber-50', color: 'text-amber-600', glow: 'bg-amber-300' },
        { label: 'Pending Approvals', value: ds.pending_approvals ?? 0, route: 'projects', icon: '<svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"/></svg>', bg: 'bg-rose-50', color: 'text-rose-600', glow: 'bg-rose-300' },
    ];
},


// ===== Timeline computed properties =====
get timelineRange() {
    let minDate = null, maxDate = null;
    for (const p of this.projects) {
        for (const rm of (p._roadmaps || [])) {
            if (rm.start_date) { const d = new Date(rm.start_date); if (!minDate || d < minDate) minDate = d; }
            if (rm.end_date) { const d = new Date(rm.end_date); if (!maxDate || d > maxDate) maxDate = d; }
            for (const ms of (rm.milestones || [])) {
                if (ms.target_date) { const d = new Date(ms.target_date); if (!minDate || d < minDate) minDate = d; if (!maxDate || d > maxDate) maxDate = d; }
            }
        }
    }
    // Always center on today — 3 months before, 9 months after minimum
    const now = new Date();
    const minPad = new Date(now.getFullYear(), now.getMonth() - 3, 1);
    const maxPad = new Date(now.getFullYear(), now.getMonth() + 9, 1);
    if (!minDate || minDate > minPad) minDate = minPad;
    if (!maxDate || maxDate < maxPad) maxDate = maxPad;
    minDate = new Date(minDate); minDate.setDate(1); minDate.setMonth(minDate.getMonth() - 1);
    maxDate = new Date(maxDate); maxDate.setMonth(maxDate.getMonth() + 2);
    return { min: minDate, max: maxDate };
},

get timelineMonths() {
    const { min, max } = this.timelineRange;
    const months = [];
    const cur = new Date(min.getFullYear(), min.getMonth(), 1);
    const monthNames = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    while (cur <= max) {
        const q = Math.floor(cur.getMonth() / 3) + 1;
        months.push({
            key: cur.getFullYear() + '-' + cur.getMonth(),
            label: monthNames[cur.getMonth()],
            year: cur.getFullYear().toString(),
            isQuarter: cur.getMonth() % 3 === 0,
            quarter: 'Q' + q,
            date: new Date(cur),
        });
        cur.setMonth(cur.getMonth() + 1);
    }
    return months;
},

get timelineTotalWidth() {
    return this.timelineMonths.length * this.monthWidth;
},

get timelineDateRange() {
    const { min, max } = this.timelineRange;
    const fmt = (d) => d.toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
    return fmt(min) + ' → ' + fmt(max);
},

get todayOffset() {
    const { min } = this.timelineRange;
    const now = new Date();
    const monthsDiff = (now.getFullYear() - min.getFullYear()) * 12 + (now.getMonth() - min.getMonth());
    const dayInMonth = now.getDate() / 30;
    return (monthsDiff + dayInMonth) * this.monthWidth;
},

timelineDateToPx(dateStr) {
    if (!dateStr) return 0;
    const { min } = this.timelineRange;
    const d = new Date(dateStr);
    const monthsDiff = (d.getFullYear() - min.getFullYear()) * 12 + (d.getMonth() - min.getMonth());
    const dayInMonth = d.getDate() / 30;
    return (monthsDiff + dayInMonth) * this.monthWidth;
},

roadmapLeftPx(rm) {
    return this.timelineDateToPx(rm.start_date);
},

roadmapWidthPx(rm) {
    const left = this.timelineDateToPx(rm.start_date);
    const right = this.timelineDateToPx(rm.end_date);
    return Math.max(right - left, 40);
},

milestoneLeftPx(ms) {
    return this.timelineDateToPx(ms.target_date);
},


// ===== Project-level timeline (uses this.roadmaps) =====
get projectTimelineRange() {
    let minDate = null, maxDate = null;
    for (const rm of (this.roadmaps || [])) {
        if (rm.start_date) { const d = new Date(rm.start_date); if (!minDate || d < minDate) minDate = d; }
        if (rm.end_date) { const d = new Date(rm.end_date); if (!maxDate || d > maxDate) maxDate = d; }
        for (const ms of (rm.milestones || [])) {
            if (ms.target_date) { const d = new Date(ms.target_date); if (!minDate || d < minDate) minDate = d; if (!maxDate || d > maxDate) maxDate = d; }
        }
    }
    // Always center on today — 3 months before, 9 months after minimum
    const now = new Date();
    const minPad = new Date(now.getFullYear(), now.getMonth() - 3, 1);
    const maxPad = new Date(now.getFullYear(), now.getMonth() + 9, 1);
    if (!minDate || minDate > minPad) minDate = minPad;
    if (!maxDate || maxDate < maxPad) maxDate = maxPad;
    minDate = new Date(minDate); minDate.setDate(1); minDate.setMonth(minDate.getMonth() - 1);
    maxDate = new Date(maxDate); maxDate.setMonth(maxDate.getMonth() + 2);
    return { min: minDate, max: maxDate };
},

get projectTimelineMonths() {
    const { min, max } = this.projectTimelineRange;
    const months = [];
    const cur = new Date(min.getFullYear(), min.getMonth(), 1);
    const monthNames = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    while (cur <= max) {
        months.push({
            key: 'p-' + cur.getFullYear() + '-' + cur.getMonth(),
            label: monthNames[cur.getMonth()],
            year: cur.getFullYear().toString(),
            isQuarter: cur.getMonth() % 3 === 0,
        });
        cur.setMonth(cur.getMonth() + 1);
    }
    return months;
},

get projectTimelineTotalWidth() {
    return this.projectTimelineMonths.length * this.monthWidth;
},

get projectTodayOffset() {
    const { min } = this.projectTimelineRange;
    const now = new Date();
    const monthsDiff = (now.getFullYear() - min.getFullYear()) * 12 + (now.getMonth() - min.getMonth());
    const dayInMonth = now.getDate() / 30;
    return (monthsDiff + dayInMonth) * this.monthWidth;
},

projectDateToPx(dateStr) {
    if (!dateStr) return 0;
    const { min } = this.projectTimelineRange;
    const d = new Date(dateStr);
    const monthsDiff = (d.getFullYear() - min.getFullYear()) * 12 + (d.getMonth() - min.getMonth());
    const dayInMonth = d.getDate() / 30;
    return (monthsDiff + dayInMonth) * this.monthWidth;
},

projectRoadmapLeftPx(rm) { return this.projectDateToPx(rm.start_date); },
projectRoadmapWidthPx(rm) {
    return Math.max(this.projectDateToPx(rm.end_date) - this.projectDateToPx(rm.start_date), 40);
},
projectMilestoneLeftPx(ms) { return this.projectDateToPx(ms.target_date); },

async api(method, url, body) {
    const opts = {
        method,
        headers: { 'Content-Type': 'application/json' },
    };
    if (this.authToken) {
        opts.headers['Authorization'] = 'Bearer ' + this.authToken;
    }
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch('/api' + url, opts);
    if (res.status === 401) {
        // Session expired — clear token and redirect to login
        localStorage.removeItem('pmo_token');
        this.authToken = null;
        this.currentUser = null;
        this.isLoggedIn = false;
        this.loginError = 'Your session has expired. Please log in again.';
        throw new Error('Session expired — please log in again');
    }
    if (res.status === 204) return null;
    // Try to parse as JSON, fall back to text for non-JSON error responses
    const text = await res.text();
    let data;
    try { data = JSON.parse(text); } catch (e) {
        if (!res.ok) throw new Error(text || `Server error (${res.status})`);
        throw new Error(`Unexpected response format: ${text.slice(0, 100)}`);
    }
    if (!res.ok) throw new Error(data.detail || data.message || `API error (${res.status})`);
    return data;
},


// ===== Project detail =====
async openProject(project) {
    this.selectedProject = project;
    this.route = 'project-detail';
    this.projectTab = 'overview';
    this.initEnvForm();
    await Promise.all([this.loadVision(), this.loadKPIs(), this.loadRoadmaps(), this.loadBacklog(), this.loadForms(), this.loadApprovals(), this.loadRisks(), this.loadStakeholders(), this.loadReleases(), this.loadTraceability(), this.loadPersonas(), this.loadTestAccounts(), this.loadProjectHealth(project.id), this.loadGithubBoardConfig(project.id), this.loadGithubSyncStatus(project.id), this.loadInfrastructure(), this.loadBrdCoverage(project.id)]);
},

async loadBrdCoverage(projectId) {
    try {
        this.brdCoverage = await this.api('GET', `/projects/${projectId}/brd-coverage`);
    } catch { this.brdCoverage = null; }
},

backToProjects() {
    this.selectedProject = null;
    this.route = 'projects';
},

async loadVision() {
    try {
        this.vision = await this.api('GET', `/projects/${this.selectedProject.id}/vision`);
    } catch {
        this.vision = null;
    }
},

async saveVision() {
    try {
        if (this.vision) {
            await this.api('PUT', `/projects/${this.selectedProject.id}/vision`, this.visionForm);
            this.vision = await this.api('GET', `/projects/${this.selectedProject.id}/vision`);
        } else {
            await this.api('POST', `/projects/${this.selectedProject.id}/vision`, {
                project_id: this.selectedProject.id,
                ...this.visionForm,
            });
            this.vision = await this.api('GET', `/projects/${this.selectedProject.id}/vision`);
        }
        this.visionForm = { statement: '', strategic_objectives: '' };
        this.showToast('Vision saved', 'success');
    } catch (e) {
        this.showToast(e.message, 'error');
    }
},

editVision() {
    this.visionForm = {
        statement: this.vision.statement || '',
        strategic_objectives: this.vision.strategic_objectives || '',
    };
},

async loadKPIs() {
    try {
        this.kpis = await this.api('GET', `/projects/${this.selectedProject.id}/kpis`);
    } catch {
        this.kpis = [];
    }
},

async saveKpi() {
    try {
        await this.api('POST', `/projects/${this.selectedProject.id}/kpis`, {
            project_id: this.selectedProject.id,
            ...this.kpiForm,
        });
        this.kpiForm = { name: '', target_value: '', current_value: '', unit: '', category: '', vision_objective: '' };
        await this.loadKPIs();
        this.showToast('KPI added', 'success');
    } catch (e) {
        this.showToast(e.message, 'error');
    }
},

async deleteKpi(id) {
    try {
        await this.api('DELETE', `/kpis/${id}`);
        await this.loadKPIs();
        this.showToast('KPI deleted', 'success');
    } catch (e) {
        this.showToast(e.message, 'error');
    }
},

async loadRoadmaps() {
    try {
        this.roadmaps = await this.api('GET', `/projects/${this.selectedProject.id}/roadmaps`);
    } catch {
        this.roadmaps = [];
    }
},

async saveRoadmap() {
    try {
        await this.api('POST', `/projects/${this.selectedProject.id}/roadmaps`, {
            project_id: this.selectedProject.id,
            ...this.roadmapForm,
        });
        this.roadmapForm = { title: '', start_date: '', end_date: '' };
        this.showRoadmapForm = false;
        await this.loadRoadmaps();
        this.showToast('Roadmap created', 'success');
    } catch (e) {
        this.showToast(e.message, 'error');
    }
},

async deleteRoadmap(id) {
    try {
        await this.api('DELETE', `/roadmaps/${id}`);
        await this.loadRoadmaps();
        this.showToast('Roadmap deleted', 'success');
    } catch (e) {
        this.showToast(e.message, 'error');
    }
},

async saveMilestone(roadmapId) {
    try {
        await this.api('POST', `/roadmaps/${roadmapId}/milestones`, {
            roadmap_id: roadmapId,
            ...this.milestoneForm,
        });
        this.milestoneForm = { title: '', target_date: '', status: 'On Track' };
        await this.loadRoadmaps();
        this.showToast('Milestone added', 'success');
    } catch (e) {
        this.showToast(e.message, 'error');
    }
},

async deleteMilestone(id) {
    try {
        await this.api('DELETE', `/milestones/${id}`);
        await this.loadRoadmaps();
        this.showToast('Milestone deleted', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

async viewMilestone(id) {
    this.milestoneEditMode = false;
    try {
        this.selectedMilestone = await this.api('GET', `/milestones/${id}/detail`);
    } catch (e) { this.showToast(e.message, 'error'); }
},

startMilestoneEdit() {
    if (!this.selectedMilestone) return;
    const ms = this.selectedMilestone;
    this.milestoneForm = { title: ms.title, target_date: ms.target_date || '', status: ms.status || 'On Track', description: ms.description || '' };
    this.milestoneEditMode = true;
},

async saveMilestoneEdit() {
    if (!this.selectedMilestone || !this.milestoneForm.title.trim()) return;
    try {
        await this.api('PUT', `/milestones/${this.selectedMilestone.id}`, this.milestoneForm);
        // Reload the detail
        this.selectedMilestone = await this.api('GET', `/milestones/${this.selectedMilestone.id}/detail`);
        this.milestoneEditMode = false;
        await this.loadRoadmaps();
        this.showToast('Milestone updated', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

async viewKPI(id) {
    this.kpiEditMode = false;
    try {
        this.selectedKPI = await this.api('GET', `/kpis/${id}/detail`);
    } catch (e) { this.showToast(e.message, 'error'); }
},

startKPIEdit() {
    if (!this.selectedKPI) return;
    const k = this.selectedKPI;
    this.kpiForm = { name: k.name, category: k.category || '', target_value: k.target_value || '', current_value: k.current_value || '', unit: k.unit || '', vision_objective: k.vision_objective || '' };
    this.kpiEditMode = true;
},

async saveKPIEdit() {
    if (!this.selectedKPI || !this.kpiForm.name.trim()) return;
    try {
        await this.api('PUT', `/kpis/${this.selectedKPI.id}`, this.kpiForm);
        this.selectedKPI = await this.api('GET', `/kpis/${this.selectedKPI.id}/detail`);
        this.kpiEditMode = false;
        await this.loadKPIs();
        this.showToast('KPI updated', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

async saveKPI() {
    if (!this.kpiForm.name.trim()) return;
    try {
        const data = { ...this.kpiForm };
        if (this.editingKPIId) {
            await this.api('PUT', `/kpis/${this.editingKPIId}`, data);
            this.showToast('KPI updated', 'success');
        } else {
            data.project_id = this.selectedProject.id;
            await this.api('POST', `/projects/${this.selectedProject.id}/kpis`, data);
            this.showToast('KPI created', 'success');
        }
        this.showKpiForm = false;
        this.editingKPIId = null;
        this.kpiForm = { name: '', target_value: '', current_value: '', unit: '', category: '', vision_objective: '' };
        await this.loadKPIs();
    } catch (e) { this.showToast(e.message, 'error'); }
},

editKPI(kpi) {
    this.editingKPIId = kpi.id;
    this.kpiForm = {
        name: kpi.name || '',
        target_value: kpi.target_value != null ? String(kpi.target_value) : '',
        current_value: kpi.current_value != null ? String(kpi.current_value) : '',
        unit: kpi.unit || '',
        category: kpi.category || '',
        vision_objective: kpi.vision_objective || ''
    };
    this.showKpiForm = true;
},

async deleteKPI(id) {
    if (!confirm('Delete this KPI?')) return;
    try {
        await this.api('DELETE', `/kpis/${id}`);
        await this.loadKPIs();
        this.showToast('KPI deleted', 'success');
    } catch (e) { this.showToast(e.message, 'error'); }
},

milestoneStatusColor(status) {
    return {
        'On Track': 'bg-emerald-50 text-emerald-700',
        'At Risk': 'bg-amber-50 text-amber-700',
        'Delayed': 'bg-rose-50 text-rose-700',
        'Completed': 'bg-ink-100 text-ink-600',
    }[status] || 'bg-ink-100 text-ink-600';
},

};

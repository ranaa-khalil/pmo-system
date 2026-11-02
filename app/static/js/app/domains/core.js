// PMO System — app/core.js
// Core domain of the Alpine pmoApp() store.
// Fragments are verbatim from the original monolith; pmo-app.js assembles them.

export const core = {
// ===== Auth state =====
isLoggedIn: false,
authToken: null,
currentUser: null,
loginForm: { email: '', password: '' },
showPassword: false,
registerForm: { full_name: '', email: '', password: '', tenant_name: '' },
loginError: '',


// ===== App state =====
route: 'today',
clients: [],
projects: [],
projectFilter: '',
clientModalOpen: false,
projectModalOpen: false,
editingClient: {},
editingProject: { name: '', client_id: '', description: '', status: 'Active', health: '', budget_hours: '', budget_amount: '', github_repo: '', version_prefix: '' },
toast: { show: false, message: '', type: 'success' },
currentTime: new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false }),


// ===== ⌘K command palette =====
paletteOpen: false,
paletteQuery: '',
paletteSelected: 0,
_paletteBound: false,

// ===== Per-user UI preferences =====
// Dashboard widget layout: ordered visible-widget keys (per-user via /me/preferences)
DASH_WIDGET_KEYS: ['stats', 'briefing', 'charts', 'projects', 'kpis', 'mytasks', 'activity', 'workload'],
dashWidgets: ['stats', 'briefing', 'charts', 'projects', 'kpis', 'mytasks', 'activity', 'workload'],
widgetPickerOpen: false,
draggingWidget: null,


// ===== Notification state =====
notifications: [],
unreadCount: 0,
notifPanelOpen: false,
activityFeed: [],
activityLoading: false,


// ===== Dashboard stats =====
dashStats: null,
dashLoading: false,
dashError: null,
dashChartError: null,


// ===== Greeting methods =====
greetingPrefix() {
    const h = new Date().getHours();
    if (h < 12) return 'Good morning';
    if (h < 17) return 'Good afternoon';
    if (h < 21) return 'Good evening';
    return 'Working late';
},

greetingMessage() {
    const h = new Date().getHours();
    const msgs = {
        morning: [
            "Fresh day, fresh wins — let's make it count.",
            "Every release brings you closer to the vision. Let's move.",
            "Your projects are waiting. Let's ship something great today.",
        ],
        afternoon: [
            "Halfway through — keep the momentum going.",
            "Approvals are moving, releases are rolling. Stay on track.",
            "The best releases happen when you stay focused. Keep going.",
        ],
        evening: [
            "Wrapping up strong — review what moved today.",
            "End the day with clarity. Check your pending approvals.",
        ],
        late: [
            "Burning the midnight oil — don't forget to rest too.",
        ],
    };
    let pool;
    if (h < 12) pool = msgs.morning;
    else if (h < 17) pool = msgs.afternoon;
    else if (h < 21) pool = msgs.evening;
    else pool = msgs.late;
    return pool[Math.floor(Math.random() * pool.length)];
},

async loadDashboard() {
    this.dashLoading = true;
    this.dashError = null;
    try {
        this.dashStats = await this.api('GET', '/dashboard');
        this.dashLoading = false;
        // setTimeout ensures Alpine.js has processed all x-show updates
        // and the canvas is visible before Chart.js initializes
        setTimeout(() => this.renderCharts(), 150);
    } catch (e) {
        this.dashStats = null;
        this.dashLoading = false;
        this.dashError = e?.message || 'Failed to load dashboard data';
        console.error('Dashboard load error:', e);
    }
},


// ===== Notification & Activity methods =====
async loadNotifications() {
    try {
        const data = await this.api('GET', '/notifications');
        this.notifications = data.notifications || [];
        this.unreadCount = data.unread_count || 0;
    } catch (e) { /* silent fail */ }
},

async loadActivity() {
    this.activityLoading = true;
    try {
        this.activityFeed = await this.api('GET', '/activity?limit=15');
    } catch (e) {
        console.error('Failed to load activity:', e);
    } finally {
        this.activityLoading = false;
    }
},

// ===== Team workload (workload strip widget) =====
workload: [],
workloadLoading: false,
async loadWorkload() {
    this.workloadLoading = true;
    try {
        this.workload = await this.api('GET', '/workload');
    } catch { this.workload = []; }
    this.workloadLoading = false;
},

toggleNotifPanel() {
    this.notifPanelOpen = !this.notifPanelOpen;
},

async markNotifRead(notif) {
    if (notif.read) return;
    try {
        await this.api('PUT', `/notifications/${notif.id}/read`);
        notif.read = true;
        this.unreadCount = Math.max(0, this.unreadCount - 1);
    } catch (e) { /* silent fail */ }
},

async markAllNotifsRead() {
    try {
        await this.api('PUT', '/notifications/read-all');
        this.notifications.forEach(n => n.read = true);
        this.unreadCount = 0;
    } catch (e) { /* silent fail */ }
},

async deleteNotif(notif) {
    try {
        await this.api('DELETE', `/notifications/${notif.id}`);
        this.notifications = this.notifications.filter(n => n.id !== notif.id);
        if (!notif.read) this.unreadCount = Math.max(0, this.unreadCount - 1);
    } catch (e) { /* silent fail */ }
},

notifIcon(type) {
    const icons = {
        approval_request: '📋', approval_approved: '✅', approval_rejected: '❌',
        task_due: '⏰', task_overdue: '⚠️', release_advanced: '🚀',
        item_sent_back: '↩️', phase_changed: '📊',
    };
    return icons[type] || '🔔';
},

notifColor(type) {
    const colors = {
        approval_request: 'bg-blue-50 text-blue-600',
        approval_approved: 'bg-emerald-50 text-emerald-600',
        approval_rejected: 'bg-rose-50 text-rose-600',
        task_due: 'bg-amber-50 text-amber-600',
        task_overdue: 'bg-rose-50 text-rose-600',
        release_advanced: 'bg-violet-50 text-violet-600',
        item_sent_back: 'bg-orange-50 text-orange-600',
    };
    return colors[type] || 'bg-ink-100 text-ink-600';
},

formatTimeAgo(dateStr) {
    if (!dateStr) return '';
    const date = new Date(dateStr);
    const now = new Date();
    const diff = Math.floor((now - date) / 1000);
    if (diff < 60) return 'just now';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    if (diff < 604800) return Math.floor(diff / 86400) + 'd ago';
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
},

activityIcon(action) {
    const icons = {
        created: '✨', updated: '✏️', deleted: '🗑️', advanced: '➡️',
        approved: '✅', rejected: '❌', assigned: '👤', sent_back: '↩️',
        signed_off: '📝',
    };
    return icons[action] || '•';
},

activityColor(action) {
    const colors = {
        created: 'text-emerald-500', updated: 'text-blue-500',
        deleted: 'text-rose-500', advanced: 'text-violet-500',
        approved: 'text-emerald-500', rejected: 'text-rose-500',
        assigned: 'text-amber-500', sent_back: 'text-orange-500',
    };
    return colors[action] || 'text-ink-400';
},

async loadProjectHealth(projectId) {
    try {
        this.projectHealth = await this.api('GET', `/projects/${projectId}/health`);
    } catch (e) {
        this.projectHealth = null;
    }
},

healthColor(score) {
    if (score >= 80) return 'text-emerald-600 bg-emerald-50';
    if (score >= 60) return 'text-amber-600 bg-amber-50';
    if (score >= 40) return 'text-orange-600 bg-orange-50';
    return 'text-rose-600 bg-rose-50';
},

healthBarColor(score) {
    if (score >= 80) return 'bg-emerald-500';
    if (score >= 60) return 'bg-amber-500';
    if (score >= 40) return 'bg-orange-500';
    return 'bg-rose-500';
},

exportBacklog(projectId) {
    const token = localStorage.getItem('pmo_token');
    window.open(`/api/export/backlog/${projectId}?token=${token}`, '_blank');
},

exportTasks() {
    const token = localStorage.getItem('pmo_token');
    window.open(`/api/export/tasks?token=${token}`, '_blank');
},

exportKPIs(projectId) {
    const token = localStorage.getItem('pmo_token');
    window.open(`/api/export/kpis/${projectId}?token=${token}`, '_blank');
},


// ===== Auth =====
async login() {
    this.loginLoading = true;
    this.loginError = '';
    try {
        const res = await fetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(this.loginForm),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Login failed');
        this.authToken = data.access_token;
        localStorage.setItem('pmo_token', this.authToken);
        const user = await this.api('GET', '/auth/me');
        this.currentUser = user;
        this.isLoggedIn = true;
        this.loginForm = { email: '', password: '' };
        if (user.system_role === 'super_admin') {
            this.resetBranding();  // Super admin: no tenant branding
            this.route = 'admin-dashboard';
            await this.loadAdminInsights();
            await this.loadAdminPlans();
        } else {
            this.route = 'today';
            await this.loadTenant();  // Load tenant branding for sidebar/logo
            this.applyBranding();  // Apply CSS variables + title
            this.initPaletteShortcuts();  // Global ⌘K/Ctrl+K
            await Promise.all([this.loadClients(), this.loadProjects(), this.loadToday(), this.loadRoles(), this.loadNotifications(), this.loadActivity(), this.checkAIStatus(), this.loadPreferences()]);
            // Fire-and-forget: the daily briefing card generates after the shell loads
            this.generateBriefing();
            setInterval(() => this.loadNotifications(), 30000);
        }
    } catch (e) {
        this.loginError = e.message;
    } finally {
        this.loginLoading = false;
    }
},

useUrlResetToken() {
    this.forgotPasswordStep = 'reset';
    this.showForgotPassword = true;
    this.hasResetTokenFromUrl = false;
},

async requestPasswordReset() {
    this.forgotPasswordLoading = true;
    this.forgotPasswordError = '';
    try {
        const res = await fetch('/api/auth/forgot-password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email: this.forgotPasswordEmail }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed to send reset email');
        // Always show "check your email" — never auto-open the reset form
        this.forgotPasswordStep = 'email_sent';
    } catch (e) {
        this.forgotPasswordError = e.message;
    } finally {
        this.forgotPasswordLoading = false;
    }
},

async confirmPasswordReset() {
    this.forgotPasswordError = '';
    if (this.forgotPasswordNewPassword.length < 8) {
        this.forgotPasswordError = 'Password must be at least 8 characters';
        return;
    }
    if (this.forgotPasswordNewPassword !== this.forgotPasswordConfirmPassword) {
        this.forgotPasswordError = 'Passwords do not match';
        return;
    }
    this.forgotPasswordLoading = true;
    try {
        const res = await fetch('/api/auth/reset-password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                token: this.forgotPasswordToken,
                new_password: this.forgotPasswordNewPassword,
            }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed to reset password');
        this.forgotPasswordStep = 'success';
    } catch (e) {
        this.forgotPasswordError = e.message;
    } finally {
        this.forgotPasswordLoading = false;
    }
},

async register() {
    this.loginError = '';
    try {
        const res = await fetch('/api/auth/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: this.registerForm.full_name,
                email: this.registerForm.email,
                password: this.registerForm.password,
                tenant_name: this.registerForm.tenant_name,
            }),
        });
        if (!res.ok) {
            const data = await res.json();
            throw new Error(data.detail || 'Registration failed');
        }
        // Auto-login after register
        this.loginForm.email = this.registerForm.email;
        this.loginForm.password = this.registerForm.password;
        this.registerForm = { full_name: '', email: '', password: '', tenant_name: '' };
        this.showRegister = false;
        await this.login();
    } catch (e) {
        this.loginError = e.message;
    }
},

logout() {
    localStorage.removeItem('pmo_token');
    this.authToken = null;
    this.currentUser = null;
    this.isLoggedIn = false;
    this.route = 'dashboard';
    this.resetBranding();
},

navigate(route) {
    if (this.route === 'dashboard' && route !== 'dashboard') { this.destroyCharts(); }
    this.route = route;
    if (route === 'roadmap') {
        this.loadAllRoadmaps().then(() => {
            this.$nextTick(() => {
                const el = this.$refs.roadmapScroll;
                if (el) {
                    const todayX = 280 + this.todayOffset * this.timelineZoom;
                    el.scrollLeft = Math.max(0, todayX - el.clientWidth / 2);
                }
            });
        });
        // Item Gantt: default to the first project
        if (!this.ganttProjectId && this.projects.length) {
            this.ganttProjectId = this.projects[0].id;
        }
        if (this.ganttProjectId) this.loadGantt();
    }
    if (route === 'dashboard') { setTimeout(() => this.renderCharts(), 150); this.refreshTaskSummary(); this.loadWorkload(); }
    if (route === 'tasks') { this.loadTasks(); }
    if (route === 'today') { this.loadToday(); }
    if (route === 'work') { this.loadWork(); }
    if (route === 'settings') { this.loadItemTypes(); }
    if (route === 'projects' || route === 'project-detail') { this.loadItemTypes(); }
    if (route === 'settings') { this.loadTenant(); this.loadMembers(); this.loadIntegrations(); this.loadTenantLimits(); this.loadAutomation(); this.loadLifecycle(); }
    if (route === 'admin-dashboard' || route === 'admin-tenants' || route === 'admin-plans') { this.loadAdminInsights(); this.loadAdminPlans(); }
},

async loadAllRoadmaps() {
    for (const p of this.projects) {
        try {
            p._roadmaps = await this.api('GET', `/projects/${p.id}/roadmaps`);
        } catch { p._roadmaps = []; }
    }
},


// ===== ⌘K palette methods =====
initPaletteShortcuts() {
    if (this._paletteBound) return;
    this._paletteBound = true;
    window.addEventListener('keydown', (e) => {
        if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
            e.preventDefault();
            this.togglePalette();
        } else if (e.key === 'Escape' && this.paletteOpen) {
            this.closePalette();
        }
    });
},
togglePalette() { this.paletteOpen ? this.closePalette() : this.openPalette(); },
openPalette() {
    this.paletteQuery = '';
    this.paletteSelected = 0;
    this.paletteOpen = true;
    // Tasks may not be loaded yet — fetch in the background
    if (this.tasks.length === 0 && this.isLoggedIn) this.loadTasks();
    this.$nextTick(() => {
        const el = document.getElementById('palette-input');
        if (el) el.focus();
    });
},
closePalette() { this.paletteOpen = false; },
get paletteResults() {
    const q = (this.paletteQuery || '').trim().toLowerCase();
    const results = [];
    const views = [
        { type: 'view', label: 'Today', route: 'today', icon: '📅', sub: 'View' },
        { type: 'view', label: 'Work', route: 'work', icon: '🗂️', sub: 'View' },
        { type: 'view', label: 'Roadmap', route: 'roadmap', icon: '🛣️', sub: 'View' },
        { type: 'view', label: 'Dashboard', route: 'dashboard', icon: '📊', sub: 'View' },
        { type: 'view', label: 'Clients', route: 'clients', icon: '🏢', sub: 'View' },
        { type: 'view', label: 'Projects', route: 'projects', icon: '📁', sub: 'View' },
        { type: 'view', label: 'My Tasks', route: 'tasks', icon: '✅', sub: 'View' },
        { type: 'view', label: 'Settings', route: 'settings', icon: '⚙️', sub: 'View' },
    ];
    for (const v of views) {
        if (!q || v.label.toLowerCase().includes(q)) results.push(v);
    }
    for (const p of this.projects) {
        if (!q || p.name.toLowerCase().includes(q)) results.push({ type: 'project', label: p.name, icon: '📁', sub: 'Project' });
    }
    for (const c of this.clients) {
        if (!q || c.name.toLowerCase().includes(q)) results.push({ type: 'client', label: c.name, icon: '🏢', sub: 'Client' });
    }
    for (const t of this.tasks) {
        if (!q || (t.title || '').toLowerCase().includes(q)) results.push({ type: 'task', label: t.title, task: t, icon: '✅', sub: 'Task' });
    }
    return results.slice(0, 12);
},
paletteHandleKey(e) {
    if (e.key === 'ArrowDown') {
        e.preventDefault();
        this.paletteSelected = Math.min(this.paletteSelected + 1, this.paletteResults.length - 1);
    } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        this.paletteSelected = Math.max(this.paletteSelected - 1, 0);
    } else if (e.key === 'Enter') {
        e.preventDefault();
        const r = this.paletteResults[this.paletteSelected];
        if (r) this.paletteGo(r);
    }
},
paletteGo(result) {
    this.closePalette();
    if (result.type === 'view') { this.navigate(result.route); }
    else if (result.type === 'project') { this.navigate('projects'); }
    else if (result.type === 'client') { this.navigate('clients'); }
    else if (result.type === 'task') { this.navigate('tasks'); this.openTaskModal(result.task); }
},


// ===== Preferences & dashboard widget layout =====
async loadPreferences() {
    try {
        const prefs = await this.api('GET', '/me/preferences');
        if (prefs.task_view_mode && ['list', 'board', 'calendar'].includes(prefs.task_view_mode)) {
            this.taskViewMode = prefs.task_view_mode;
        }
        if (Array.isArray(prefs.dashboard_widgets) && prefs.dashboard_widgets.length) {
            const valid = prefs.dashboard_widgets.filter(k => this.DASH_WIDGET_KEYS.includes(k));
            if (valid.length) this.dashWidgets = valid;
        }
    } catch { /* defaults are fine */ }
},
dashWidgetVisible(key) { return this.dashWidgets.includes(key); },
dashWidgetOrder(key) { const i = this.dashWidgets.indexOf(key); return i === -1 ? 99 : i; },
dashWidgetLabel(key) {
    const labels = {
        stats: 'Stat cards', briefing: 'Daily briefing', charts: 'Charts',
        projects: 'Project health', kpis: 'KPI progress', mytasks: 'My Tasks', activity: 'Activity feed',
        workload: 'Team workload',
    };
    return labels[key] || key;
},
toggleDashWidget(key) {
    if (this.dashWidgets.includes(key)) {
        if (this.dashWidgets.length <= 1) { this.showToast('At least one widget must stay visible', 'error'); return; }
        this.dashWidgets = this.dashWidgets.filter(k => k !== key);
    } else {
        this.dashWidgets = [...this.dashWidgets, key];
    }
    this.persistDashWidgets();
},
persistDashWidgets() {
    this.api('PUT', '/me/preferences', { key: 'dashboard_widgets', value: this.dashWidgets }).catch(() => {});
},
onWidgetDrop(targetKey) {
    const from = this.dashWidgets.indexOf(this.draggingWidget);
    const to = this.dashWidgets.indexOf(targetKey);
    this.draggingWidget = null;
    if (from === -1 || to === -1 || from === to) return;
    const next = [...this.dashWidgets];
    next.splice(to, 0, next.splice(from, 1)[0]);
    this.dashWidgets = next;
    this.persistDashWidgets();
},


// ===== Share links (public read-only views) =====
showShareModal: false,
shareLinks: [],
shareForm: { scope: 'dashboard', project_id: null, password: '', expires_in_days: 30 },
async openShareModal(scope = 'dashboard') {
    this.shareForm = { scope, project_id: null, password: '', expires_in_days: 30 };
    this.showShareModal = true;
    await this.loadShareLinks();
},
async loadShareLinks() {
    try { this.shareLinks = await this.api('GET', '/share-links'); } catch { this.shareLinks = []; }
},
async createShareLink() {
    try {
        const link = await this.api('POST', '/share-links', {
            scope: this.shareForm.scope,
            project_id: this.shareForm.scope === 'project' ? this.shareForm.project_id : null,
            password: this.shareForm.password || null,
            expires_in_days: this.shareForm.expires_in_days || 30,
        });
        this.shareForm.password = '';
        await this.loadShareLinks();
        this.copyShareLink(link);
    } catch (e) { this.showToast(e.message || 'Failed to create link', 'error'); }
},
async revokeShareLink(link) {
    try {
        await this.api('DELETE', `/share-links/${link.id}`);
        await this.loadShareLinks();
        this.showToast('Link revoked', 'success');
    } catch (e) { this.showToast('Failed to revoke', 'error'); }
},
copyShareLink(link) {
    const url = window.location.origin + link.url;
    navigator.clipboard.writeText(url).then(
        () => this.showToast('Share link copied', 'success'),
        () => window.prompt('Copy this share link:', url),
    );
},

};

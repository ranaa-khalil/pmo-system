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
route: 'dashboard',
clients: [],
projects: [],
projectFilter: '',
clientModalOpen: false,
projectModalOpen: false,
editingClient: {},
editingProject: { name: '', client_id: '', description: '', status: 'Active', github_repo: '', version_prefix: '' },
toast: { show: false, message: '', type: 'success' },
currentTime: new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false }),


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
            this.route = 'dashboard';
            await this.loadTenant();  // Load tenant branding for sidebar/logo
            this.applyBranding();  // Apply CSS variables + title
            await Promise.all([this.loadClients(), this.loadProjects(), this.loadDashboard(), this.loadRoles(), this.loadNotifications(), this.loadActivity(), this.checkAIStatus()]);
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
    }
    if (route === 'dashboard') { setTimeout(() => this.renderCharts(), 150); this.refreshTaskSummary(); }
    if (route === 'tasks') { this.loadTasks(); }
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

};

// PMO System — domains/portal.js
// Client portal (P4): PM-side management (enable/disable, passcode shown once)
// + the client-facing portal session (separate scoped token, read-only).

export const portal = {
// ===== Portal management (PM side) =====
portalSetupFor: null,       // client being set up
portalSetupBusy: false,
portalSetupError: '',
portalPasscodeShown: null,  // {clientName, email, passcode} — shown ONCE
portalStatusCache: {},      // client_id -> {portal_enabled: bool}

// ===== Client portal session (client side) =====
portalMode: false,          // true = portal view active (replaces the SPA shell)
portalSession: null,        // {id, name}
portalLoginForm: { email: '', passcode: '' },
portalLoginBusy: false,
portalLoginError: '',
portalData: null,           // {projects, releases, milestones}
portalLoading: false,
portalError: '',

portalStatus(clientId) {
    return (this.portalStatusCache || {})[clientId] || null;
},

async togglePortalSetup(c) {
    if (this.portalSetupFor && this.portalSetupFor.id === c.id) {
        this.portalSetupFor = null;
        return;
    }
    this.portalSetupFor = { ...c };
    this.portalSetupError = '';
    this.portalPasscodeShown = null;
    // Fetch current portal status
    try {
        const st = await this.api('GET', `/clients/${c.id}/portal`);
        this.portalStatusCache = { ...this.portalStatusCache, [c.id]: st };
    } catch (e) { /* status unknown — buttons still work */ }
},

async enablePortal() {
    if (!this.portalSetupFor || this.portalSetupBusy) return;
    this.portalSetupBusy = true;
    this.portalSetupError = '';
    try {
        const data = await this.api('POST', `/clients/${this.portalSetupFor.id}/portal`, {});
        this.portalPasscodeShown = {
            clientName: this.portalSetupFor.name,
            email: this.portalSetupFor.contact_email,
            passcode: data.passcode,
        };
        this.portalStatusCache = { ...this.portalStatusCache, [this.portalSetupFor.id]: { portal_enabled: true } };
    } catch (e) {
        this.portalSetupError = e.message || 'Failed to enable portal';
    } finally {
        this.portalSetupBusy = false;
    }
},

async disablePortal(c) {
    if (this.portalSetupBusy) return;
    this.portalSetupBusy = true;
    this.portalSetupError = '';
    try {
        await this.api('DELETE', `/clients/${c.id}/portal`);
        this.portalStatusCache = { ...this.portalStatusCache, [c.id]: { portal_enabled: false } };
        this.portalSetupFor = null;
        this.toast = { show: true, message: `Portal disabled for ${c.name}`, type: 'success' };
        setTimeout(() => { this.toast.show = false; }, 3000);
    } catch (e) {
        this.portalSetupError = e.message || 'Failed to disable portal';
    } finally {
        this.portalSetupBusy = false;
    }
},

copyPortalPasscode() {
    if (!this.portalPasscodeShown) return;
    navigator.clipboard?.writeText(this.portalPasscodeShown.passcode).catch(() => {});
},

// ===== Portal session (client side) =====
async portalLogin() {
    this.portalLoginBusy = true;
    this.portalLoginError = '';
    try {
        const res = await fetch('/api/portal/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(this.portalLoginForm),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Invalid email or passcode');
        this.portalSession = data.client;
        localStorage.setItem('pmo_portal_token', data.access_token);
        this.portalMode = true;
        this.portalLoginForm = { email: '', passcode: '' };
        await this.loadPortalOverview();
    } catch (e) {
        this.portalLoginError = e.message;
    } finally {
        this.portalLoginBusy = false;
    }
},

async loadPortalOverview() {
    this.portalLoading = true;
    this.portalError = '';
    try {
        const token = localStorage.getItem('pmo_portal_token');
        const res = await fetch('/api/portal/overview', {
            headers: { 'Authorization': `Bearer ${token}` },
        });
        if (res.status === 401) { this.portalLogout(); return; }
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed to load portal data');
        this.portalData = data;
        if (data.client) this.portalSession = data.client;
    } catch (e) {
        this.portalError = e.message || 'Failed to load portal data';
    } finally {
        this.portalLoading = false;
    }
},

portalLogout() {
    localStorage.removeItem('pmo_portal_token');
    this.portalSession = null;
    this.portalData = null;
    this.portalMode = false;
},

portalStatusColor(status) {
    if (status === 'Active') return 'bg-emerald-50 text-emerald-600';
    if (status === 'On Hold') return 'bg-amber-50 text-amber-600';
    if (status === 'Released') return 'bg-emerald-50 text-emerald-600';
    return 'bg-ink-100 text-ink-500';
},

portalPhasePct(release) {
    // V-cycle progress: map release status to % of the 7-phase cycle
    const order = ['Planning', 'In Progress', 'Testing', 'UAT', 'Pre-Release', 'Released', 'Post-Release'];
    const idx = order.indexOf(release.status);
    if (idx < 0) return 0;
    return Math.round(((idx + 1) / order.length) * 100);
},
};

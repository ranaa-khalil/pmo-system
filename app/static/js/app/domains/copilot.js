// PMO System — copilot.js
// Copilot domain of the Alpine pmoApp() store.
// State + methods for the PMO Copilot drawer: grounded chat, action
// proposals (draft → confirm/reject), and ongoing intake capture.
// All calls go through the store's `api()` helper (auth headers included).

export const copilot = {
// ===== Copilot state =====
copilotOpen: false,
copilotMessages: [],        // [{role: 'user'|'assistant', text, sources, proposal_id, ops}]
copilotInput: '',
copilotBusy: false,
copilotPendingProposal: null,  // {proposal_id, operations}


// ===== Copilot methods =====
toggleCopilot() {
    this.copilotOpen = !this.copilotOpen;
    if (this.copilotOpen && this.copilotMessages.length === 0) {
        this.copilotMessages.push({
            role: 'assistant',
            text: 'Ask me anything about your projects — overdue work, aging items, pending approvals, or releases at risk. I read your data and cite sources.',
        });
    }
},

async copilotAsk(text) {
    const question = (text || this.copilotInput || '').trim();
    if (!question || this.copilotBusy) return;
    this.copilotInput = '';
    this.copilotMessages.push({ role: 'user', text: question });
    this.copilotBusy = true;
    this.copilotScroll();
    try {
        const data = await this.api('POST', '/ai/copilot/chat', {
            question,
            project_id: this.selectedProject ? this.selectedProject.id : null,
        });
        this.copilotMessages.push({
            role: 'assistant',
            text: data.answer,
            sources: data.sources || [],
        });
    } catch (e) {
        this.copilotMessages.push({
            role: 'assistant',
            text: e?.message || 'Copilot request failed.',
            error: true,
        });
    }
    this.copilotBusy = false;
    this.copilotScroll();
},

async copilotPropose(intent) {
    if (this.copilotBusy) return;
    this.copilotBusy = true;
    this.copilotMessages.push({ role: 'user', text: intent });
    this.copilotScroll();
    try {
        const data = await this.api('POST', '/ai/copilot/propose', {
            intent,
            project_id: this.selectedProject ? this.selectedProject.id : null,
        });
        this.copilotPendingProposal = {
            proposal_id: data.proposal_id,
            operations: data.operations || [],
        };
        this.copilotMessages.push({
            role: 'assistant',
            text: data.operations.length
                ? 'I drafted the operations below. Nothing is executed until you confirm.'
                : 'This is out of scope for now — I can advance items, assign users, draft risks, or escalate approvals.',
            proposal_id: data.proposal_id,
            ops: data.operations || [],
        });
    } catch (e) {
        this.copilotMessages.push({ role: 'assistant', text: e?.message || 'Proposal failed.', error: true });
    }
    this.copilotBusy = false;
    this.copilotScroll();
},

async copilotConfirm() {
    if (!this.copilotPendingProposal) return;
    const { proposal_id } = this.copilotPendingProposal;
    this.copilotPendingProposal = null;
    this.copilotBusy = true;
    try {
        const data = await this.api('POST', `/ai/copilot/proposals/${proposal_id}/confirm`, {});
        const ok = (data.executed || []).length;
        const bad = (data.failed || []).length;
        this.copilotMessages.push({
            role: 'assistant',
            text: `Done — ${ok} operation${ok === 1 ? '' : 's'} executed${bad ? `, ${bad} failed` : ''}.`,
        });
        // Refresh the dashboard so the executed writes are visible
        this.loadDashboard();
    } catch (e) {
        this.copilotMessages.push({ role: 'assistant', text: e?.message || 'Confirm failed.', error: true });
    }
    this.copilotBusy = false;
    this.copilotScroll();
},

async copilotReject() {
    if (!this.copilotPendingProposal) return;
    const { proposal_id } = this.copilotPendingProposal;
    this.copilotPendingProposal = null;
    try {
        await this.api('POST', `/ai/copilot/proposals/${proposal_id}/reject`, {});
        this.copilotMessages.push({ role: 'assistant', text: 'Proposal discarded — nothing was executed.' });
    } catch (e) {
        this.copilotMessages.push({ role: 'assistant', text: e?.message || 'Reject failed.', error: true });
    }
    this.copilotScroll();
},

copilotScroll() {
    this.$nextTick(() => {
        const el = document.getElementById('copilot-messages');
        if (el) el.scrollTop = el.scrollHeight;
    });
},

copilotSubmit() {
    const q = this.copilotInput.trim();
    if (!q) return;
    // Intents phrased as commands go to the proposal flow; questions to chat
    if (/^(move|assign|draft|escalate|create)\b/i.test(q)) {
        this.copilotPropose(q);
        this.copilotInput = '';
    } else {
        this.copilotAsk(q);
    }
},
};

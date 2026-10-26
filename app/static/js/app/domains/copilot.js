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
copilotTab: 'chat',         // 'chat' | 'intake'

// ===== Intake state =====
intakeKickoff: '',
intakeProjectType: 'software',
intakeBusy: false,
intakeDraft: null,          // {summary, epics, personas, kpis, assumptions, draft_id}
intakeApplying: false,
intakeResult: null,         // {features_created, personas_created, kpis_created}
backlogVerdict: null,       // feature verdict chip: {verdict, epic, confidence, reasoning, sibling_duplicates}

// ===== Daily briefing state =====
briefingSummary: '',
briefingVerdict: '',
briefingRisks: [],
briefingLoading: false,
briefingGeneratedAt: null,


// ===== Copilot methods =====
// Structured chat answer rendering: escape HTML, then convert the copilot's
// concise markdown (bold, bullets, numbered lists, line breaks) to HTML.
renderChatMarkdown(text) {
    if (!text) return '';
    const esc = String(text)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    const lines = esc.split(/\r?\n/);
    let html = '', inList = false, listType = 'ul';
    const closeList = () => { if (inList) { html += `</${listType}>`; inList = false; } };
    for (const raw of lines) {
        const line = raw.trimEnd();
        const bullet = line.match(/^\s*[-*]\s+(.*)$/);
        const numbered = line.match(/^\s*\d+\.\s+(.*)$/);
        if (bullet) {
            if (!inList || listType !== 'ul') { closeList(); html += '<ul>'; inList = true; listType = 'ul'; }
            html += `<li>${bullet[1]}</li>`;
        } else if (numbered) {
            if (!inList || listType !== 'ol') { closeList(); html += '<ol>'; inList = true; listType = 'ol'; }
            html += `<li>${numbered[1]}</li>`;
        } else if (line.trim() === '') {
            closeList();
        } else {
            closeList();
            html += `<p>${line}</p>`;
        }
    }
    closeList();
    // Inline markdown: **bold** last (after list parsing)
    return html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
},

toggleCopilot() {
    this.copilotOpen = !this.copilotOpen;
    if (this.copilotOpen && this.copilotMessages.length === 0) {
        const scope = this.selectedProject
            ? `I'm scoped to ${this.selectedProject.name} — the project you have open.`
            : "I cover all your assigned projects. Open a project to scope me to it.";
        this.copilotMessages.push({
            role: 'assistant',
            text: `Ask me anything about your projects — overdue work, aging items, pending approvals, or releases at risk. I read your data and cite sources. ${scope}`,
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

// ===== Daily briefing (exec verdict shape, computed from live data) =====
// Parse the copilot's structured briefing answer into sections:
// "**Verdict: ...**", "**Overdue tasks (3):**\n- item", "**At-risk releases (2):**"
// — no regex-on-prose chips, no truncation.
parseBriefing(answer) {
    const text = String(answer || '').trim();
    const sections = {};   // lowercase section title → [items] or string
    let current = null;
    for (const raw of text.split(/\r?\n/)) {
        const line = raw.trim();
        if (!line) continue;
        // Header: "**Verdict: Needs attention** — rest" or "**Overdue tasks:**"
        // The colon may sit inside OR outside the bold — split on it after capture.
        const header = line.match(/^\*\*(.+?)\*\*\s*—?\s*(.*)$/);
        if (header) {
            let title = header[1].trim();
            const rest = header[2].trim();
            // "**Verdict: Needs attention**" — colon inside the bold: the part
            // before the colon is the section title, after it is the content
            if (title.includes(':')) {
                const [before, ...after] = title.split(':');
                title = before.trim();
                const inline = after.join(':').trim();
                if (inline && !rest) sections[title.toLowerCase()] = [inline];
                else if (inline) sections[title.toLowerCase()] = [inline, ...(rest ? [rest] : [])];
                else sections[title.toLowerCase()] = [];
            } else {
                sections[title.replace(/:$/, '').toLowerCase()] = rest ? [rest] : [];
            }
            current = title.toLowerCase();
            continue;
        }
        if (current) {
            const bullet = line.match(/^[-*]\s+(.*)$/) || line.match(/^\d+\.\s+(.*)$/);
            if (bullet) sections[current].push(bullet[1]);
            else if (Array.isArray(sections[current]) && sections[current].length === 0) sections[current] = [line];
            else sections[current] = (sections[current] || []) ;
        }
    }
    return { text, sections };
},

async generateBriefing() {
    if (this.briefingLoading) return;
    this.briefingLoading = true;
    try {
        // Ask the copilot in briefing mode — grounded in the same data spine
        const data = await this.api('POST', '/ai/copilot/chat', {
            question: 'Give me my daily briefing: overall verdict (on track / needs attention), overdue tasks, pending gate approvals, and at-risk releases. Be brief.',
            project_id: this.selectedProject ? this.selectedProject.id : null,
        });
        const { text, sections } = this.parseBriefing(data.answer || '');
        // Full answer, never truncated — the card renders it as markdown
        this.briefingSummary = text;
        // Verdict: from the parsed Verdict section, not string sniffing
        const verdictRaw = (sections['verdict'] || [])[0] || '';
        this.briefingVerdict = /needs attention|at risk/i.test(verdictRaw) ? 'needs attention' : 'on track';
        // Risk chips: the bullet items of the at-risk section (real items, not regex fragments)
        const riskItems = sections['at-risk releases'] || sections['risks'] || sections['at risk'] || [];
        this.briefingRisks = riskItems
            .map(r => String(r).replace(/\*\*/g, '').split(/[:—-]/)[0].trim())
            .filter(Boolean).slice(0, 3);
        this.briefingGeneratedAt = new Date().toISOString();
    } catch (e) {
        this.briefingSummary = e?.message || 'Briefing unavailable — check AI configuration in Settings.';
        this.briefingVerdict = '';
        this.briefingRisks = [];
    }
    this.briefingLoading = false;
},

// ===== Conversational intake (structure → review → Apply) =====
// Open the copilot intake tab from a core flow (new project / backlog).
openCopilotIntake() {
    this.copilotOpen = true;
    this.copilotTab = 'intake';
},

// Feature verdict (exists / fits an epic / new) — debounced fetch as the PM
// types the title; the chip renders above the form and fits_epic pre-fills
// the epic selector. Manual form is never gated: saving stays possible.
async checkBacklogVerdict() {
    const title = (this.backlogForm?.title || '').trim();
    if (title.length <= 2 || !this.selectedProject) { this.backlogVerdict = null; return; }
    clearTimeout(this._verdictTimer);
    this._verdictTimer = setTimeout(async () => {
        try {
            const data = await this.api('POST', '/ai/intake/verdict', {
                title,
                description: this.backlogForm.description || '',
                project_id: this.selectedProject.id,
            });
            // Ignore stale responses (title changed while the request ran)
            if ((this.backlogForm?.title || '').trim() !== title) return;
            this.backlogVerdict = data;
            // fits_epic → pre-fill the epic selector (PM can adjust)
            if (data.verdict === 'fits_epic' && data.epic && !this.backlogForm.epic) {
                this.backlogForm.epic = data.epic;
            }
        } catch (e) {
            this.backlogVerdict = null;  // verdict is assistive only — never blocks
        }
    }, 900);
},

async intakeStructure() {
    const kickoff = (this.intakeKickoff || '').trim();
    if (!kickoff || this.intakeBusy) return;
    this.intakeBusy = true;
    this.intakeDraft = null;
    this.intakeResult = null;
    try {
        const data = await this.api('POST', '/ai/intake/structure', {
            kickoff,
            project_id: this.selectedProject ? this.selectedProject.id : null,
            project_name: this.selectedProject ? this.selectedProject.name : '',
        });
        this.intakeDraft = data;
    } catch (e) {
        this.showToast(e?.message || 'Intake structuring failed.', 'error');
    }
    this.intakeBusy = false;
},

async intakeApply() {
    if (!this.intakeDraft || this.intakeApplying) return;
    this.intakeApplying = true;
    try {
        const data = await this.api('POST', '/ai/intake/apply', {
            draft: this.intakeDraft,
            project_id: this.selectedProject ? this.selectedProject.id : null,
        });
        this.intakeResult = data;
        this.showToast(`Intake applied: ${data.features_created} features, ${data.personas_created} personas, ${data.kpis_created} KPIs.`, 'success');
        // Refresh backlog + releases so the created records are visible
        this.loadBacklog();
        this.loadReleases();
    } catch (e) {
        this.showToast(e?.message || 'Intake apply failed.', 'error');
    }
    this.intakeApplying = false;
},
};

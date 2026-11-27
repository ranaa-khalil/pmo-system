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
copilotStreaming: false,    // phase 3: tokens are streaming into the live bubble
copilotPendingProposal: null,  // {proposal_id, operations}
intakeKickoffOpen: false,  // Rethink MVP #4: kickoff paste card open in the ONE Ask surface

// ===== Intake state =====
intakeKickoff: '',
intakeProjectType: 'software',
intakeBusy: false,
intakeDraft: null,          // {summary, epics, personas, kpis, assumptions, draft_id}
intakeApplying: false,
intakeResult: null,         // {features_created, personas_created, kpis_created}
backlogVerdict: null,       // feature verdict chip: {verdict, epic, confidence, reasoning, sibling_duplicates}

// ===== Interview state (P2.1) =====
interviewSession: null,     // {session_id, question, progress, answers_so_far, done}
interviewFlow: 'project',
interviewBusy: false,
interviewDraft: null,       // assembled draft (same shape as intake draft)
interviewFinished: false,
interviewApplying: false,
interviewResult: null,
interviewApprovals: [],     // open approvals for the escalation flow picker
interviewEscalationApprovalId: '',

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

// Quick action chip: labeled capability → asked as a plain chat message
copilotQuickAsk(text) {
    this.copilotOpen = true;
    this.copilotAsk(text);
},

// Scope greeting — seeded once, on open and after a new topic
seedCopilotGreeting() {
    if (this.copilotMessages.length > 0) return;
    const scope = this.selectedProject
        ? `I'm scoped to **${this.selectedProject.name}** — the project you have open. I know its backlog, epics, risks, approvals, and releases, and I'll cite record ids.`
        : "I cover all your assigned projects. Open a project to scope me to it — then I know that project's backlog, risks, approvals, and releases specifically.";
    this.copilotMessages.push({
        role: 'assistant',
        text: `Hi — I'm your AI PMO officer. **Tell me what's happening** and I'll structure it, or ask me anything: overdue work, waiting approvals, aging items. I read your data and cite sources. ${scope}`,
    });
},

toggleCopilot() {
    this.copilotOpen = !this.copilotOpen;
    if (this.copilotOpen && this.copilotMessages.length === 0) {
        this.seedCopilotGreeting();
    }
},

// New topic: clear the conversation, keep scope greeting.
// One open path only — toggling twice visibly closed and reopened the drawer.
copilotNewTopic() {
    this.copilotMessages = [];
    this.copilotPendingProposal = null;
    // Rethink MVP #4: clear every in-panel surface so the capability
    // fallback row is reachable again (one Ask surface, no tabs).
    this.intakeKickoffOpen = false;
    this.intakeKickoff = '';
    this.intakeDraft = null;
    this.intakeResult = null;
    this.interviewSession = null;
    this.interviewDraft = null;
    this.interviewFinished = false;
    this.interviewResult = null;
    this.copilotInput = '';
    if (!this.copilotOpen) {
        this.toggleCopilot();
    } else {
        this.seedCopilotGreeting();
    }
},

// Rethink MVP #4: capability fallback stays reachable in-panel while no
// session/draft/result is open — kickoff + guided flows, one Ask surface.
get showCopilotCapabilities() {
    return !this.intakeKickoffOpen && !this.intakeDraft && !this.intakeResult
        && !this.interviewSession && !this.interviewDraft && !this.interviewResult;
},

copilotStartProjectKickoff() {
    this.copilotOpen = true;
    this.copilotMessages.push({ role: 'user', text: 'Start a project kickoff' });
    this.copilotMessages.push({
        role: 'assistant',
        text: 'Paste your kickoff notes in the card below — a paragraph, meeting notes, or a doc. I\'ll structure them into epics, features, personas, and KPIs; you review and Apply. Or just tell me about the project here and I\'ll ask for what\'s missing.',
    });
    this.intakeKickoffOpen = true;
},

copilotStartFeatureIntake() {
    this.copilotOpen = true;
    this.interviewStart('feature', this.selectedProject ? this.selectedProject.id : null);
},

copilotStartRiskIntake() {
    this.copilotOpen = true;
    this.interviewStart('risk', this.selectedProject ? this.selectedProject.id : null);
},

copilotStartReleaseIntake() {
    this.copilotOpen = true;
    if (!this.selectedProject) {
        this.copilotMessages.push({ role: 'user', text: 'Plan a release' });
        this.copilotMessages.push({
            role: 'assistant',
            text: 'Happy to — open a project first (releases belong to a project), then tap **Plan a release** again. Or tell me here what should ship and I\'ll remember it.',
        });
        return;
    }
    this.interviewStart('release', this.selectedProject.id);
},

// Point-of-work launcher (Rethink final slice): the approval detail's
// "Escalate with AI" button starts the escalation interview with THIS
// approval pre-selected in the picker. The drawer's fallback list stays for
// everything else; the engine + endpoints are unchanged.
copilotStartEscalationIntake() {
    const approval = this.selectedApproval;
    this._interviewPresetApprovalId = approval?.id || null;
    this.copilotOpen = true;
    this.interviewStart('escalation', approval?.project_id ?? (this.selectedProject ? this.selectedProject.id : null));
},

async copilotAsk(text) {
    const question = (text || this.copilotInput || '').trim();
    if (!question || this.copilotBusy) return;
    this.copilotInput = '';
    this.copilotMessages.push({ role: 'user', text: question });
    const history = this.copilotMessages.slice(-8).map(m => ({ role: m.role, text: m.text }));
    this.copilotBusy = true;
    this.copilotScroll();
    // Phase 3: the streaming bubble — pushed up-front so the answer renders
    // into it as tokens arrive. Mutations go through the store (Alpine's
    // reactivity tracks proxy reads, not raw-object writes).
    this.copilotMessages.push({ role: 'assistant', text: '', streaming: true, sources: [], references: [] });
    this.copilotStreaming = true;
    try {
        await this._copilotStreamAsk(question, history);
    } catch (e) {
        // Degrade to the existing non-streaming call on ANY stream failure —
        // the proven contract renders the answer (or the error) as today.
        try {
            const data = await this.api('POST', '/ai/copilot/chat', {
                question,
                project_id: this.selectedProject ? this.selectedProject.id : null,
                history,
            });
            const m = this._copilotLastMessage();
            if (m) {
                m.streaming = false;
                m.text = data.answer;
                m.sources = data.sources || [];
                m.references = data.references || [];
            }
        } catch (e2) {
            const m = this._copilotLastMessage();
            if (m) {
                m.streaming = false;
                m.text = e2?.message || 'PMO Copilot request failed.';
                m.error = true;
            }
        }
    }
    this.copilotBusy = false;
    this.copilotStreaming = false;
    this.copilotScroll();
},

_copilotLastMessage() {
    return this.copilotMessages.length ? this.copilotMessages[this.copilotMessages.length - 1] : null;
},

// SSE over fetch + ReadableStream (NOT the browser's native SSE client — the
// POST body carries the question). Token events append into the live bubble; a tool event
// resets the partial to the tool status; the terminal event (final |
// degraded) replaces the text and renders the references/badges — the same
// finish as the non-streaming contract.
async _copilotStreamAsk(question, history) {
    const opts = {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            question,
            project_id: this.selectedProject ? this.selectedProject.id : null,
            history,
        }),
    };
    if (this.authToken) opts.headers['Authorization'] = 'Bearer ' + this.authToken;
    const res = await fetch('/api/ai/copilot/chat/stream', opts);
    if (res.status === 401) {
        localStorage.removeItem('pmo_token');
        this.authToken = null;
        this.currentUser = null;
        this.isLoggedIn = false;
        this.loginError = 'Your session has expired. Please log in again.';
        throw new Error('Session expired — please log in again');
    }
    if (!res.ok) {
        let detail = `API error (${res.status})`;
        try { const j = await res.json(); detail = j.detail || j.message || detail; } catch (_) { /* non-JSON body */ }
        throw new Error(detail);
    }
    const ctype = (res.headers.get('content-type') || '').toLowerCase();
    if (!ctype.includes('text/event-stream')) {
        // Fast-path short-circuit: plain 200 JSON — the non-streaming contract.
        const data = await res.json();
        const m = this._copilotLastMessage();
        if (m) {
            m.streaming = false;
            m.text = data.answer;
            m.sources = data.sources || [];
            m.references = data.references || [];
        }
        this.copilotScroll();
        return;
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let sep;
        while ((sep = buf.indexOf('\n\n')) !== -1) {
            const block = buf.slice(0, sep);
            buf = buf.slice(sep + 2);
            const ev = this._parseSSE(block);
            if (!ev) continue;
            const m = this._copilotLastMessage();
            if (!m) return;
            if (ev.event === 'token') {
                m.text += (ev.data && ev.data.delta) || '';
                this.copilotScroll();
            } else if (ev.event === 'tool') {
                m.text = '';
                m.toolStatus = ev.data && ev.data.tool ? `checked ${ev.data.tool}` : '';
                this.copilotScroll();
            } else if (ev.event === 'final' || ev.event === 'degraded') {
                m.streaming = false;
                m.text = (ev.data && ev.data.answer) || m.text;
                m.degraded = !!(ev.data && ev.data.degraded);
                m.sources = (ev.data && ev.data.sources) || [];
                m.references = (ev.data && ev.data.references) || [];
                this.copilotScroll();
                return;
            } else if (ev.event === 'error') {
                throw new Error((ev.data && ev.data.detail) || 'stream failed');
            }
        }
    }
    // The stream ended without a terminal event — a broken half answer is
    // never rendered: throw so the caller degrades to the non-streaming call.
    throw new Error('stream ended without a final answer');
},

_parseSSE(block) {
    let event = 'message', data = '';
    for (const line of block.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim();
        else if (line.startsWith('data:')) data += line.slice(5).trimStart();
    }
    if (!data) return null;
    try { return { event, data: JSON.parse(data) }; } catch (e) { return null; }
},

// Clickable reference chips (Rethink MVP #2): a validated citation lands at
// the record — the openNotification pattern (route match, then project path
// with the right tab), closing the drawer first so the record is visible.
async openReference(ref) {
    if (!ref) return;
    const url = (ref.url || '').trim();
    if (!url) return;
    this.copilotOpen = false;
    const route = url.replace(/^\/+/, '');
    // Route-level links (/tasks) navigate directly
    if (this.navItems && this.navItems.some(i => i.id === route)) { this.navigate(route); return; }
    // Project paths: /projects/<id>[/tab] → open the project at the tab
    const projectMatch = route.match(/^projects\/(\d+)(?:\/([a-z-]+))?$/);
    if (projectMatch) {
        const projectId = parseInt(projectMatch[1], 10);
        const tab = projectMatch[2] || '';
        const project = (this.projects || []).find(p => p.id === projectId);
        if (project) {
            await this.openProject(project);
        } else {
            await this.selectProjectById(projectId);
        }
        const tabMap = { backlog: 'backlog', approvals: 'approvals', releases: 'releases', risks: 'risks', kpis: 'kpis', docs: 'docs' };
        if (tab && tabMap[tab]) this.projectTab = tabMap[tab];
        return;
    }
    // Fallback: a bare route id
    if (this.navItems && this.navItems.some(i => i.id === route.split('/')[0])) {
        this.navigate(route.split('/')[0]);
    }
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

// Back: undo the last interview answer and re-ask it. On the first question
// (nothing to undo server-side), Back ends the interview and returns to the
// capability chips — "choose another" without nuking the conversation.
async interviewBack() {
    if (!this.interviewSession || this.interviewBusy) return;
    this.interviewBusy = true;
    this.copilotScroll();
    // Remove the marker + trailing assistant messages for the last question
    while (this.copilotMessages.length && this.copilotMessages[this.copilotMessages.length - 1].meta) {
        this.copilotMessages.pop();
    }
    try {
        const data = await this.api('POST', `/ai/interview/${this.interviewSession.session_id}/back`, {});
        // Server state wins: back moves the question pointer and progress,
        // so merge fresh data AFTER the stale session copy.
        this.interviewSession = { ...this.interviewSession, ...data };
        const chipHint = data.question.choices ? ` Options: ${data.question.choices.join(' · ')}.` : '';
        this.copilotMessages.push({
            role: 'assistant',
            text: `Went back — let's redo this one.${chipHint}\n\n${data.question.prompt}`,
        });
    } catch (e) {
        if (e?.message === 'nothing_to_undo') {
            // Nothing to undo → this was question 1: end the interview and
            // return to the guided options list so the user can pick another.
            this.interviewSession = null;
            this.interviewDraft = null;
            this.interviewFinished = false;
            this.copilotMessages.push({
                role: 'assistant',
                text: 'No problem — choose another guided option below, or just tell me what you need.',
            });
        } else {
            this.showToast(e?.message || 'Back failed.', 'error');
        }
    }
    this.interviewBusy = false;
    this.copilotScroll();
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


async selectProjectById(projectId) {
    if (!projectId) return;
    try {
        const projects = await this.api('GET', '/projects');
        const project = (Array.isArray(projects) ? projects : []).find(p => p.id === projectId);
        if (project) await this.openProject(project);
    } catch (e) { /* non-fatal */ }
},

// ===== Conversational intake (structure → review → Apply) =====
// Open the kickoff paste card inside the ONE Ask surface
// (Rethink MVP #4: no intake tab — the card is a message-type panel).
openCopilotIntake() {
    this.copilotOpen = true;
    this.intakeKickoffOpen = true;
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

// AI-outcome tags: click a created-record tag → land in the project at the
// right tab (features → Backlog, KPIs → KPIs, personas → Env & Personas,
// risk → Backlog, release → Releases, escalation → Approvals).
async openOutcomeRecord(kind) {
    const r = this.intakeResult || this.interviewResult;
    if (!r || !r.project_id) return;
    try {
        const projects = await this.api('GET', '/projects');
        const project = (Array.isArray(projects) ? projects : []).find(p => p.id === r.project_id);
        if (!project) return;
        this.copilotOpen = false;
        await this.openProject(project);
        if (kind === 'kpi') this.projectTab = 'kpis';
        else if (kind === 'persona') this.projectTab = 'env';
        else if (kind === 'release') this.projectTab = 'releases';
        else if (kind === 'escalation') this.projectTab = 'approvals';
        else this.projectTab = 'backlog';
    } catch (e) { /* non-fatal */ }
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

// ===== Interview engine (guided Q&A — P2.1) =====
// The AI PM asks 4-8 questions one at a time; the human answers (text, chip,
// or accept-default). State persists server-side (AiInteraction kind=interview),
// so closing the drawer and coming back resumes mid-interview. Apply remains
// the only write — the finished draft feeds the existing intake pipeline.
async interviewStart(flow, projectId) {
    if (this.interviewBusy) return;
    this.interviewBusy = true;
    this.copilotOpen = true;
    this.intakeKickoffOpen = false;
    this.interviewDraft = null;
    this.interviewFinished = false;
    try {
        const data = await this.api('POST', `/ai/interview/${flow}/start`, {
            flow, project_id: projectId ?? (this.selectedProject ? this.selectedProject.id : null),
        });
        this.interviewSession = data;
        this.interviewFlow = flow;
        this.copilotMessages.push({
            role: 'assistant',
            text: `**${data.title}** — I'll ask a few short questions. Tap a chip, type your answer, or hit "Use default" to accept mine. Skip anything and I'll fill it in.\n\n${data.question.prompt}`,
        });
    } catch (e) {
        this.showToast(e?.message || 'Interview failed to start.', 'error');
    }
    this.interviewBusy = false;
    this.copilotScroll();
},

async interviewAnswer(value, skipped = false) {
    if (!this.interviewSession || this.interviewBusy) return;
    const q = this.interviewSession.question;
    const shown = skipped ? '(skipped — using default)' : value;
    this.copilotMessages.push({ role: 'user', text: shown || '(default)' });
    this.copilotMessages.push({ role: 'assistant', text: `__Q:${q.id}`, meta: true, questionId: q.id });
    this.interviewBusy = true;
    this.copilotScroll();
    const path = skipped ? 'skip' : 'answer';
    try {
        const data = await this.api('POST', `/ai/interview/${this.interviewSession.session_id}/${path}`, {
            question_id: q.id, answer: value || '',
        });
        if (data.error) {
            this.showToast(data.error, 'error');
        } else if (data.done) {
            this.interviewSession = { ...this.interviewSession, done: true };
            this.copilotMessages.push({
                role: 'assistant',
                text: 'That\'s everything I need. Assembling the draft for your review…',
            });
            this.interviewBusy = false;
            await this.interviewFinish();
        } else {
            this.interviewSession = data;
            const chipHint = data.question.choices ? ` Options: ${data.question.choices.join(' · ')}.` : '';
            const defaultHint = data.question.default && !data.question.required
                ? ` (default: "${data.question.default}")` : '';
            this.copilotMessages.push({
                role: 'assistant',
                text: `${data.question.prompt}${chipHint}${defaultHint}`,
            });
        }
    } catch (e) {
        this.showToast(e?.message || 'Interview answer failed.', 'error');
    }
    this.interviewBusy = false;
    this.copilotScroll();
},

async interviewFinish() {
    if (!this.interviewSession || this.interviewBusy) return;
    this.interviewBusy = true;
    try {
        const data = await this.api('POST', `/ai/interview/${this.interviewSession.session_id}/finish`, {});
        this.interviewDraft = data.draft;
        this.interviewFinished = true;
        if (data.flow === 'project') {
            const d = data.draft;
            const featCount = (d.epics || []).reduce((n, e) => n + (e.features || []).length, 0);
            this.copilotMessages.push({
                role: 'assistant',
                text: `Here's the structured draft: **${(d.summary || '').slice(0, 200)}**\n\n- ${(d.epics || []).length} epics / ${featCount} features\n- ${(d.personas || []).length} personas\n- ${(d.kpis || []).length} KPIs\n\nReview it in the panel — edit inline if needed, then **Apply** to create the records. Nothing is created until you do.`,
            });
        } else if (data.flow === 'escalation') {
            // Load the project's open approvals for the picker (read-only);
            // a point-of-work launch pre-selects the approval it came from.
            this.interviewEscalationApprovalId = this._interviewPresetApprovalId ? String(this._interviewPresetApprovalId) : '';
            this._interviewPresetApprovalId = null;
            try {
                const pid = data.draft.project_id ?? (this.selectedProject ? this.selectedProject.id : null);
                if (pid) {
                    const approvals = await this.api('GET', `/projects/${pid}/approvals`);
                    this.interviewApprovals = (approvals || []).filter(a => (a.status || 'pending') !== 'approved');
                } else {
                    this.interviewApprovals = [];
                }
            } catch (_) { this.interviewApprovals = []; }
            this.copilotMessages.push({
                role: 'assistant',
                text: 'Escalation note drafted. Pick the approval to escalate in the panel, review the note, then **Apply** to append it. Nothing changes until you do.',
            });
        } else if (data.flow === 'risk') {
            this.copilotMessages.push({
                role: 'assistant',
                text: 'Risk drafted — severity × probability score is computed at Apply. Review it in the panel, then **Apply** to add it to the register.',
            });
        } else if (data.flow === 'release') {
            this.copilotMessages.push({
                role: 'assistant',
                text: `Release draft ready: **${data.draft.version || '—'}**. Review it in the panel, then **Apply** to create the release.`,
            });
        } else {
            this.copilotMessages.push({
                role: 'assistant',
                text: 'Draft assembled — review it in the panel below.',
            });
        }
    } catch (e) {
        this.showToast(e?.message || 'Interview assembly failed.', 'error');
    }
    this.interviewBusy = false;
    this.copilotScroll();
},

async interviewApply() {
    if (!this.interviewDraft || this.interviewApplying) return;
    this.interviewApplying = true;
    try {
        if (this.interviewFlow === 'feature') {
            // Feature intake → pre-fill the backlog form (the real write path);
            // the PM reviews and saves from the form like any manual entry.
            if (!this.selectedProject) {
                this.showToast('Open a project first — feature intake pre-fills its backlog form.', 'error');
                this.interviewApplying = false;
                return;
            }
            const d = this.interviewDraft || {};
            this.backlogForm = {
                ...this.backlogForm,
                title: d.title || this.backlogForm.title,
                description: d.acceptance_criteria || this.backlogForm.description,
                priority: d.priority || 'Medium',
                target_release: d.target_release || '',
                dependencies: (d.dependencies && d.dependencies !== 'none') ? d.dependencies : '',
            };
            this.interviewSession = null;
            this.interviewDraft = null;
            this.interviewFinished = false;
            this.copilotOpen = false;
            this.showBacklogForm = true;
            this.showToast('Feature answers pre-filled in the backlog form — review and save.', 'success');
        } else if (this.interviewFlow === 'project') {
            // From scratch: create the project shell first, then apply into it.
            let targetProjectId = this.selectedProject ? this.selectedProject.id : null;
            if (!targetProjectId) {
                const d = this.interviewDraft || {};
                const created = await this.api('POST', '/projects', {
                    name: (d.summary || 'New project').slice(0, 120),
                    client_id: this.clients && this.clients.length ? this.clients[0].id : null,
                    description: d.summary || '',
                    project_type: (d.interview_answers && d.interview_answers.project_type) || 'software',
                    status: 'Active',
                });
                targetProjectId = created.id;
                await this.loadProjects();
                const shell = (this.projects || []).find(pr => pr.id === targetProjectId);
                if (shell) { this.selectedProject = shell; }
                this.showToast('Project created — applying the structured records into it.', 'success');
            }
            // Apply into the (new or open) project — the only write path
            const data = await this.api('POST', '/ai/intake/apply', {
                draft: this.interviewDraft,
                project_id: targetProjectId,
            });
            this.interviewResult = data;
            this.showToast(`Applied: ${data.features_created} features, ${data.personas_created} personas, ${data.kpis_created} KPIs.`, 'success');
            this.loadBacklog();
            this.loadReleases();
            // Land the PM in the new project with the records visible
            if (this.selectedProject && this.selectedProject.id === targetProjectId) {
                await this.openProject(this.selectedProject);
            }
        } else {
            // risk / release / escalation: the interview apply endpoint
            const edits = this.interviewFlow === 'escalation'
                ? { approval_id: parseInt(this.interviewEscalationApprovalId, 10) || null }
                : undefined;
            const data = await this.api('POST', `/ai/interview/${this.interviewSession.session_id}/apply`, edits ? { edits } : {});
            const label = data.applied === 'risk' ? `Risk #${data.risk_id} (score ${data.score})`
                : data.applied === 'release' ? `Release ${data.version}`
                : `Approval #${data.approval_id} escalated`;
            this.interviewResult = { applied: data.applied, label, project_id: data.project_id };
            this.showToast(`Applied: ${label}.`, 'success');
            if (data.applied === 'risk') this.loadBacklog();
            if (data.applied === 'release') this.loadReleases();
            if (data.applied === 'escalation') this.loadApprovals && this.loadApprovals();
        }
    } catch (e) {
        this.showToast(e?.message || 'Apply failed.', 'error');
    }
    this.interviewApplying = false;
},
};

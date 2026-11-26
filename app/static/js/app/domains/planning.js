// PMO System — app/planning.js
// Planning domain of the Alpine pmoApp() store.
// Fragments are verbatim from the original monolith; pmo-app.js assembles them.

export const planning = {
// ===== Today + Work (R1 spine) =====
today: null,
todayLoading: false,
todayNarrative: '',         // Rethink MVP #3: 3-sentence AI brief over the deterministic card
todayNarrativeLoading: false,
todayNarrativeDegraded: false,
workItems: [],
workFilter: 'all',
workTagFilter: null,  // cross-tagging filter (tag id or null)
workSearch: '',
workProjectFilter: '',
workLoading: false,
selectedWorkItem: null,
workDetail: null,
workDetailLoading: false,
workViewMode: 'board',  // 'board' | 'timeline' | 'list' — the ONE Work view chips
workGroupBy: 'phase',  // 'phase' | 'epic' | 'assignee' | 'type' — changes what a drag means
workTagsOpen: false,  // Tags ▾ dropdown (filter row)
workGroupByOpen: false,  // Group-by ▾ dropdown (filter row)

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
    // ONE AI narrative call (Rethink MVP #3): 3 sentences over the
    // deterministic needs-you aggregate, fired wherever the card renders.
    this.loadTodayNarrative();
},

// The narrative is additive — the deterministic card (verdict + needs-you
// rows) stands alone whenever the LLM is down, unconfigured or over quota
// (degraded=true). The LLM never blocks the card: a failed call just leaves
// it empty.
async loadTodayNarrative() {
    if (this.todayNarrativeLoading) return;
    this.todayNarrativeLoading = true;
    try {
        const data = await this.api('POST', '/ai/today-brief/narrative');
        this.todayNarrative = data.narrative || '';
        this.todayNarrativeDegraded = !!data.degraded;
    } catch {
        this.todayNarrative = '';
        this.todayNarrativeDegraded = true;
    }
    this.todayNarrativeLoading = false;
},

async loadWork() {
    this.workLoading = true;
    try {
        const params = [];
        if (this.workFilter && this.workFilter !== 'all') params.push(`filter=${this.workFilter}`);
        if (this.workTagFilter) params.push(`tag_id=${this.workTagFilter}`);
        const qs = params.length ? `?${params.join('&')}` : '';
        this.workItems = ((await this.api('GET', `/work${qs}`)).items || []).map(i => ({ ...i, current_phase: i.current_phase ?? i.phase }));
    } catch { this.workItems = []; }
    this.workLoading = false;
    // Tag chips for the cross-tagging filter (load once)
    if (this.tagPool.length === 0) this.loadTagPool();
    // The board re-lanes from fresh data (optimistic moves call loadWork too)
    if (this.workViewMode === 'board') this.buildWorkBoard();
},

setWorkFilter(f) {
    this.workFilter = f;
    this.loadWork();
    // Persisted state (survives reload) — pattern: setTaskViewMode
    this.api('PUT', '/me/preferences', { key: 'work_filter', value: f }).catch(() => {});
},

setWorkTagFilter(tagId) {
    this.workTagFilter = this.workTagFilter === tagId ? null : tagId;
    this.loadWork();
},

setWorkProjectFilter(value) {
    this.workProjectFilter = value;
    this.api('PUT', '/me/preferences', { key: 'work_project_filter', value: value }).catch(() => {});
    if (this.workViewMode === 'timeline') this.syncWorkGantt();
},

setWorkViewMode(mode) {
    this.workViewMode = mode;
    this.api('PUT', '/me/preferences', { key: 'work_view_mode', value: mode }).catch(() => {});
    if (mode === 'timeline') this.syncWorkGantt();
    if (mode === 'board') this.buildWorkBoard();
},

setWorkGroupBy(groupBy) {
    this.workGroupBy = groupBy;
    this.api('PUT', '/me/preferences', { key: 'work_group_by', value: groupBy }).catch(() => {});
    this.buildWorkBoard();
},

// Timeline is filter-first per project: the gantt follows the Work project select
syncWorkGantt() {
    const want = this.workProjectFilter ? Number(this.workProjectFilter) : null;
    if (want === null) {
        if (this.ganttProjectId !== null) { this.ganttProjectId = null; this.ganttData = null; }
        return;
    }
    if (this.ganttProjectId !== want || !this.ganttData || this.ganttData.project_id !== want) {
        this.ganttProjectId = want;
        this.loadGantt();
    }
},

// Empty-state next action for the projectless timeline: focus + flash the select
workPickProject() {
    const el = document.getElementById('work-project-select');
    if (!el) return;
    el.focus();
    el.classList.add('ring-2', 'ring-brand-300');
    setTimeout(() => el.classList.remove('ring-2', 'ring-brand-300'), 2000);
},

// + New item — opens the drawer in new-item mode (capture box + form fallback)
newWorkItem() {
    this.openWorkItemNew();
},

// ===== ItemType vocabulary (tenant-scoped) =====
itemTypes: [],
itemTypesLoading: false,
itemTypeForm: { key: '', label: '', color: 'blue' },
async loadItemTypes() {
    this.itemTypesLoading = true;
    try {
        this.itemTypes = await this.api('GET', '/item-types');
    } catch { this.itemTypes = []; }
    this.itemTypesLoading = false;
},
itemTypeColor(key) {
    const classes = {
        blue: 'bg-blue-50 text-blue-600', rose: 'bg-rose-50 text-rose-600',
        amber: 'bg-amber-50 text-amber-600', violet: 'bg-violet-50 text-violet-600',
        ink: 'bg-ink-100 text-ink-500', emerald: 'bg-emerald-50 text-emerald-600',
        indigo: 'bg-indigo-50 text-indigo-600',
    };
    const t = (this.itemTypes || []).find(x => x.key === key);
    return (t && classes[t.color]) || 'bg-ink-100 text-ink-500';
},
async saveItemType() {
    if (!this.itemTypeForm.key.trim() || !this.itemTypeForm.label.trim()) {
        this.showToast('Key and label are required', 'error'); return;
    }
    try {
        await this.api('POST', '/item-types', {
            key: this.itemTypeForm.key.trim(),
            label: this.itemTypeForm.label.trim(),
            color: this.itemTypeForm.color || 'blue',
        });
        this.itemTypeForm = { key: '', label: '', color: 'blue' };
        await this.loadItemTypes();
        this.showToast('Item type added', 'success');
    } catch (e) { this.showToast(e.message || 'Failed to add type', 'error'); }
},
async toggleItemType(t) {
    try {
        await this.api('PUT', `/item-types/${t.id}`, { is_active: !t.is_active });
        await this.loadItemTypes();
    } catch (e) { this.showToast('Failed to update type', 'error'); }
},
async deleteItemType(t) {
    try {
        await this.api('DELETE', `/item-types/${t.id}`);
        await this.loadItemTypes();
    } catch (e) { this.showToast(e.message || 'Failed to delete type', 'error'); }
},

// ===== Item proofing (versioned deliverables) =====
itemProofs: [],
itemProofsLoading: false,
proofForm: { title: '', file_url: '', file: null },
proofMode: 'file',
viewingProof: null,
async loadProofs(itemId) {
    this.itemProofsLoading = true;
    try {
        this.itemProofs = await this.api('GET', `/backlog/${itemId}/proofs`);
    } catch { this.itemProofs = []; }
    this.itemProofsLoading = false;
},
async uploadProof() {
    const item = this.selectedWorkItem ?? this.viewingBacklogItem;
    if (!item) return;
    if (!this.proofForm.title.trim()) { this.showToast('Give the proof a title', 'error'); return; }
    if (this.proofMode === 'file') {
        if (!this.proofForm.file) { this.showToast('Choose a file to upload', 'error'); return; }
        const fd = new FormData();
        fd.append('title', this.proofForm.title.trim());
        fd.append('file', this.proofForm.file);
        try {
            await this.api('POST', `/backlog/${item.id}/proofs`, fd);
            this.proofForm = { title: '', file_url: '', file: null };
            await this.loadProofs(item.id);
            this.showToast('Attachment uploaded — pending review', 'success');
        } catch (e) { this.showToast(e.message || 'Failed to upload attachment', 'error'); }
    } else {
        if (!this.proofForm.file_url.trim()) { this.showToast('Paste a link to the deliverable', 'error'); return; }
        try {
            const body = new URLSearchParams();
            body.set('title', this.proofForm.title.trim());
            body.set('file_url', this.proofForm.file_url.trim());
            await this.api('POST', `/backlog/${item.id}/proofs`, body.toString(), 'application/x-www-form-urlencoded');
            this.proofForm = { title: '', file_url: '', file: null };
            await this.loadProofs(item.id);
            this.showToast('Link proof uploaded — pending review', 'success');
        } catch (e) { this.showToast(e.message || 'Failed to upload proof', 'error'); }
    }
},
onProofFileChosen(event) {
    const file = event.target.files && event.target.files[0];
    this.proofForm.file = file || null;
},
viewProof(proof) {
    const src = proof.file_path || proof.file_url;
    if (!src) { this.showToast('This proof has no attachment', 'error'); return; }
    this.viewingProof = { ...proof, src };
},
closeProof() { this.viewingProof = null; },
isImageSrc(src) {
    return /\.(png|jpe?g|webp|gif)$/i.test(src || '');
},
async decideProof(proof, decision) {
    try {
        const comment = decision === 'Changes Requested'
            ? window.prompt('What needs to change?', '') : null;
        if (decision === 'Changes Requested' && comment === null) return;
        await this.api('POST', `/proofs/${proof.id}/decide`, { decision, comment });
        await this.loadProofs(proof.item_id);
        this.showToast(decision === 'Approved' ? 'Proof approved' : 'Changes requested', 'success');
    } catch (e) { this.showToast(e.message || 'Failed to record decision', 'error'); }
},

// ===== Item Gantt (project-level, day grid) =====
ganttProjectId: null,
ganttData: null,
ganttLoading: false,
ganttDragging: null,
async loadGantt() {
    if (!this.ganttProjectId) return;
    this.ganttLoading = true;
    try { this.ganttData = await this.api('GET', `/projects/${this.ganttProjectId}/gantt`); }
    catch { this.ganttData = null; }
    this.ganttLoading = false;
},
ganttDayList() {
    if (!this.ganttData || !this.ganttData.start || !this.ganttData.end) return [];
    const start = new Date(this.ganttData.start + 'T00:00:00');
    const end = new Date(this.ganttData.end + 'T00:00:00');
    const days = [];
    const now = new Date();
    const todayIso = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
    for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
        const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
        days.push({ iso, day: d.getDate(), isWeekend: d.getDay() === 0 || d.getDay() === 6, isToday: iso === todayIso });
    }
    return days;
},
ganttDayIndex(iso) {
    if (!this.ganttData || !this.ganttData.start) return 0;
    return Math.round((new Date(iso + 'T00:00:00') - new Date(this.ganttData.start + 'T00:00:00')) / 86400000);
},
// Release targets (Timeline P1): the project's releases are the commitment
// layer on the item Gantt — each target renders as a key-date line. Targets
// outside the day window stay on the drift chip (the line can't be placed).
ganttReleaseLines() {
    if (!this.ganttData || !this.ganttData.releases || !this.ganttData.start) return [];
    const days = this.ganttDayList().length;
    const lines = [];
    for (const r of this.ganttData.releases) {
        if (!r.target_date) continue;
        const t = new Date(r.target_date + 'T00:00:00');
        if (isNaN(t.getTime())) continue;
        const idx = Math.round((t - new Date(this.ganttData.start + 'T00:00:00')) / 86400000);
        if (idx < 0 || idx >= days) continue;
        lines.push({ id: r.id, version: r.version, status: r.status, day_index: idx });
    }
    return lines;
},
// Drift chip (Timeline P1): the plan runs past a release target — the
// backend's window-end vs target comparison (the PNU contradiction).
ganttDrift() {
    return (this.ganttData && this.ganttData.drift) || null;
},
// Actuals (Timeline P2): baseline-vs-actual — the actual bar overlays the
// planned bar once the advance machine has stamped actual dates. An open
// item (no actual end yet) runs its actual bar to the window edge; bars
// clamp to the visible day grid.
ganttActualBar(it) {
    if (!it.actual_start_date || !this.ganttData || !this.ganttData.start) return null;
    const days = this.ganttDayList().length;
    if (!days) return null;
    const left = Math.max(this.ganttDayIndex(it.actual_start_date), 0);
    const endIso = it.actual_end_date || this.ganttData.end;
    const right = Math.min(this.ganttDayIndex(endIso), days - 1);
    const width = right - left + 1;
    if (width <= 0) return null;
    return { left: left * 28 + 1, width: Math.max(width * 28 - 2, 6) };
},
async onGanttDrop(item, dayIso) {
    if (!item || !item.start_date) return;
    const shift = Math.round((new Date(dayIso + 'T00:00:00') - new Date(item.start_date + 'T00:00:00')) / 86400000);
    this.ganttDragging = null;
    if (!shift) return;
    const fmt = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    const start = new Date(item.start_date + 'T00:00:00');
    const end = new Date(item.end_date + 'T00:00:00');
    start.setDate(start.getDate() + shift);
    end.setDate(end.getDate() + shift);
    try {
        await this.api('PUT', `/backlog/${item.id}`, { start_date: fmt(start), end_date: fmt(end) });
        this.showToast(`#${item.id} moved to ${fmt(start)}`, 'success');
        this.loadGantt();
        // Keep the ONE Work view in sync when the move came from its timeline
        if (this.workViewMode === 'timeline') this.loadWork();
    } catch (e) { this.showToast('Failed to move item', 'error'); }
},

async openWorkItem(item) {
    this.selectedWorkItem = item;
    this.workDetail = null;
    this.workItemNew = false;
    this.workItemEdit = false;
    this.workItemMoveOpen = false;
    this.workTagPickerOpen = false;
    this.workAssigneeOpen = false;
    this.workItemCommentForm = '';
    try {
        const [brief, itemRow, comments, proofs, subitems] = await Promise.all([
            this.api('GET', `/projects/${item.project_id}/brief`).catch(() => null),
            this.api('GET', `/backlog/${item.id}`).catch(() => null),
            this.api('GET', `/backlog/${item.id}/comments`).catch(() => []),
            this.api('GET', `/backlog/${item.id}/proofs`).catch(() => []),
            this.api('GET', `/backlog/${item.id}/subitems`).catch(() => []),
        ]);
        this.workDetail = { brief, item: itemRow };
        this.workItemComments = comments || [];
        this.workItemProofs = proofs || [];
        this.workItemSubitems = subitems || [];
        // The fresh row's tags are the drawer's tags (the payload's tags[] is a fallback)
        if (itemRow && itemRow.tags) this.selectedWorkItem.tags = itemRow.tags;
    } catch { this.workDetail = { brief: null, item: null }; }
    this.workDetailLoading = false;
},

closeWorkItem() {
    this.selectedWorkItem = null;
    this.workDetail = null;
    this.workItemNew = false;
    this.workItemEdit = false;
    this.workItemMoveOpen = false;
    this.workTagPickerOpen = false;
    this.workAssigneeOpen = false;
    this.workItemComments = [];
    this.workItemProofs = [];
    this.workItemSubitems = [];
    this.workItemCommentForm = '';
},

// ===== Item drawer write layer (Slice 3b — the ONE drawer everywhere) =====
// Drawer-not-modal (rule 6), optimistic (rule 8), inline edit (rule 4).
workItemNew: false,          // drawer is in + New item mode
workItemEdit: false,         // view ↔ edit swap
workItemEditForm: {},
workItemMoveOpen: false,     // the phase chip's move menu
workTagPickerOpen: false,
workTagName: '',
workTagColor: 'indigo',
workAssigneeOpen: false,
workItemComments: [],
workItemCommentForm: '',
workItemProofs: [],
workItemSubitems: [],
newItemForm: { project_id: null, title: '', description: '', priority: 'Medium', item_type: 'Feature' },

// The drawer's + New item: capture box + the form fallback (visible path)
openWorkItemNew() {
    this.workItemNew = true;
    this.workItemEdit = false;
    this.workItemMoveOpen = false;
    this.workTagPickerOpen = false;
    this.workAssigneeOpen = false;
    const pre = this.workProjectFilter ? Number(this.workProjectFilter)
        : (this.projects && this.projects[0] ? this.projects[0].id : null);
    this.newItemForm = { project_id: pre, title: '', description: '', priority: 'Medium', item_type: 'Feature' };
    // A truthy placeholder opens the drawer; the new-item template renders
    this.selectedWorkItem = { id: 'new', title: 'New item', project: '', project_id: pre };
},

// Fresh values win (a stale row keeps the drawer honest after a move)
workItemDescription() {
    const it = this.workDetail && this.workDetail.item;
    return (it && it.description) || this.selectedWorkItem?.description || '';
},
workItemAcceptance() {
    const it = this.workDetail && this.workDetail.item;
    return (it && it.acceptance_criteria) || this.selectedWorkItem?.acceptance_criteria || '';
},
workCurrentPhase() {
    const it = this.workDetail && this.workDetail.item;
    return (it && it.current_phase) || this.selectedWorkItem?.phase || 'Requirements';
},
workStepperFill(idx) {
    const phases = this.itemPhases || [];
    const cur = phases.indexOf(this.workCurrentPhase());
    if (idx < cur) return 'bg-brand-500';
    if (idx === cur) return 'bg-white border-2 border-accent-600 shadow-sm';
    return 'bg-ink-200';
},
workAdvanceLabel() {
    const phases = this.itemPhases || [];
    const idx = phases.indexOf(this.workCurrentPhase());
    if (idx < 0 || idx >= phases.length - 1) return 'Advance';
    return `Move to ${phases[idx + 1]} →`;
},
workAdvanceAllowed() {
    const phases = this.itemPhases || [];
    const idx = phases.indexOf(this.workCurrentPhase());
    return idx >= 0 && idx < phases.length - 1;
},

// Phase moves share the modal footer's endpoints (advance/send-back) — one
// verb vocabulary everywhere. Drag = group-by on the board (3a); this is
// the explicit move for every other surface.
async moveWorkItemTo(phase) {
    if (!this.selectedWorkItem || phase === this.workCurrentPhase()) { this.workItemMoveOpen = false; return; }
    const id = this.selectedWorkItem.id;
    if (phase === 'Requirements') {
        this.workItemMoveOpen = false;
        await this.sendBackWorkItem(id);
        return;
    }
    this.workItemMoveOpen = false;
    // Optimistic: the drawer reflects the move before the round-trip lands
    const from = this.workCurrentPhase();
    const steps = (this.itemPhases || []).indexOf(phase) - (this.itemPhases || []).indexOf(from);
    if (this.workDetail && this.workDetail.item) this.workDetail.item.current_phase = phase;
    if (this.selectedWorkItem) this.selectedWorkItem.phase = phase;
    try {
        for (let i = 0; i < Math.abs(steps); i++) {
            await this.api('POST', `/backlog/${id}/${steps > 0 ? 'advance' : 'send-back'}`);
        }
        this.showToast(`#${id} → ${phase}`, 'success');
        this.loadWork();
    } catch (e) {
        // Roll back the optimistic state
        if (this.workDetail && this.workDetail.item) this.workDetail.item.current_phase = from;
        if (this.selectedWorkItem) this.selectedWorkItem.phase = from;
        this.showToast(e.message || 'Move failed', 'error');
    }
},
async advanceWorkItem(id) {
    const from = this.workCurrentPhase();
    const phases = this.itemPhases || [];
    const next = phases[phases.indexOf(from) + 1];
    if (this.workDetail && this.workDetail.item) this.workDetail.item.current_phase = next;
    if (this.selectedWorkItem) this.selectedWorkItem.phase = next;
    try {
        await this.api('POST', `/backlog/${id}/advance`);
        this.showToast('Phase advanced: ' + from + ' → ' + next, 'success');
        this.loadWork();
    } catch (e) {
        if (this.workDetail && this.workDetail.item) this.workDetail.item.current_phase = from;
        if (this.selectedWorkItem) this.selectedWorkItem.phase = from;
        this.showToast(e.message || 'Move failed', 'error');
    }
},
async sendBackWorkItem(id) {
    const from = this.workCurrentPhase();
    if (this.workDetail && this.workDetail.item) this.workDetail.item.current_phase = 'Requirements';
    if (this.selectedWorkItem) this.selectedWorkItem.phase = 'Requirements';
    try {
        await this.api('POST', `/backlog/${id}/send-back`);
        this.showToast('↩ Sent back to Requirements', 'info');
        this.loadWork();
    } catch (e) {
        if (this.workDetail && this.workDetail.item) this.workDetail.item.current_phase = from;
        if (this.selectedWorkItem) this.selectedWorkItem.phase = from;
        this.showToast(e.message || 'Send-back failed', 'error');
    }
},

// Edit: swaps inline in place (rule 4) — same surface, no navigation
startWorkItemEdit() {
    const it = (this.workDetail && this.workDetail.item) || this.selectedWorkItem || {};
    this.workItemEditForm = {
        title: it.title || '',
        description: this.workItemDescription(),
        acceptance_criteria: this.workItemAcceptance(),
        priority: it.priority || 'Medium',
        item_type: it.item_type || '',
        story_points: it.story_points ?? '',
        target_release: it.target_release || '',
        epic: it.epic || '',
    };
    this.workItemEdit = true;
},
async saveWorkItemEdit() {
    const id = this.selectedWorkItem && this.selectedWorkItem.id;
    if (!id || !this.workItemEditForm.title.trim()) return;
    const body = {
        title: this.workItemEditForm.title.trim(),
        description: this.workItemEditForm.description || '',
        acceptance_criteria: this.workItemEditForm.acceptance_criteria || '',
        priority: this.workItemEditForm.priority,
        item_type: this.workItemEditForm.item_type || null,
        story_points: this.workItemEditForm.story_points === '' ? null : Number(this.workItemEditForm.story_points),
        target_release: this.workItemEditForm.target_release || null,
        epic: this.workItemEditForm.epic || null,
    };
    try {
        const fresh = await this.api('PUT', `/backlog/${id}`, body);
        if (this.workDetail && this.workDetail.item) this.workDetail.item = { ...this.workDetail.item, ...fresh };
        if (this.selectedWorkItem) {
            this.selectedWorkItem.title = fresh.title;
            this.selectedWorkItem.priority = fresh.priority;
            this.selectedWorkItem.item_type = fresh.item_type;
        }
        this.workItemEdit = false;
        this.showToast('Item updated', 'success');
        this.loadWork();
    } catch (e) {
        this.showToast(e.message || 'Could not save changes', 'error');
    }
},

// The drawer's form fallback: POST /projects/{id}/backlog (create, 3 steps:
// open drawer → form → Add). Confirmed items land in the Requirements lane.
async saveNewItem() {
    const f = this.newItemForm;
    if (!f.title.trim() || !f.project_id) return;
    try {
        const created = await this.api('POST', `/projects/${f.project_id}/backlog`, {
            project_id: Number(f.project_id),
            title: f.title.trim(),
            description: f.description || '',
            priority: f.priority,
            item_type: f.item_type || null,
        });
        this.showToast(`#${created.id} added to Requirements`, 'success');
        this.closeWorkItem();
        this.loadWork();
    } catch (e) {
        this.showToast(e.message || 'Could not add the item', 'error');
    }
},

// Tags — the SAME picker as modals/task.html, re-hosted in the drawer
async attachWorkItemTag(tag) {
    const id = this.selectedWorkItem && this.selectedWorkItem.id;
    if (!id) return;
    try {
        await this.api('POST', `/backlog/${id}/tags`, { tag_id: tag.id });
        this.workTagPickerOpen = false;
        const fresh = await this.api('GET', `/backlog/${id}`);
        if (this.workDetail && this.workDetail.item) this.workDetail.item = fresh;
        if (this.selectedWorkItem) this.selectedWorkItem.tags = fresh.tags || [];
        this.showToast(`Tagged #${tag.name}`, 'success');
        this.loadWork();
    } catch (e) {
        this.showToast(e.message || 'Could not attach the tag', 'error');
    }
},
async detachWorkItemTag(tag) {
    const id = this.selectedWorkItem && this.selectedWorkItem.id;
    if (!id) return;
    try {
        await this.api('DELETE', `/backlog/${id}/tags/${tag.id}`);
        const fresh = await this.api('GET', `/backlog/${id}`);
        if (this.workDetail && this.workDetail.item) this.workDetail.item = fresh;
        if (this.selectedWorkItem) this.selectedWorkItem.tags = fresh.tags || [];
        this.showToast(`Removed #${tag.name}`, 'info');
        this.loadWork();
    } catch (e) {
        this.showToast(e.message || 'Could not remove the tag', 'error');
    }
},
async createWorkTagInline() {
    if (!this.workTagName.trim()) return;
    try {
        const tag = await this.api('POST', '/tags', { name: this.workTagName.trim(), color: this.workTagColor });
        this.workTagName = '';
        const pool = this.tagPool || [];
        if (!pool.find(t => t.id === tag.id)) pool.push(tag);
        await this.attachWorkItemTag(tag);
    } catch (e) {
        this.showToast(e.message || 'Could not create the tag', 'error');
    }
},

// Assignee — the same toggle picker (single assignee on backlog items)
async setWorkItemAssignee(userId) {
    const id = this.selectedWorkItem && this.selectedWorkItem.id;
    if (!id) return;
    const prev = this.selectedWorkItem.assigned_to;
    const user = (this.users || []).find(u => u.id === userId) || null;
    // Optimistic (rule 8)
    this.selectedWorkItem.assigned_to = userId;
    this.selectedWorkItem.assigned_to_name = user ? user.name : '';
    this.workAssigneeOpen = false;
    try {
        await this.api('PUT', `/backlog/${id}`, { assigned_to: userId });
        this.showToast(user ? `Assigned to ${user.name}` : 'Unassigned', 'success');
        this.loadWork();
    } catch (e) {
        this.selectedWorkItem.assigned_to = prev;
        this.showToast(e.message || 'Could not update the assignee', 'error');
    }
},

// Comment thread — append-only, input pinned at the bottom, Enter posts
async postWorkItemComment() {
    const id = this.selectedWorkItem && this.selectedWorkItem.id;
    const body = (this.workItemCommentForm || '').trim();
    if (!id || !body) return;
    try {
        const c = await this.api('POST', `/backlog/${id}/comments`, { body });
        this.workItemComments.push(c);
        this.workItemCommentForm = '';
        this.showToast('Comment posted', 'success');
    } catch (e) {
        this.showToast(e.message || 'Could not post the comment', 'error');
    }
},

// Today row → Work detail drawer. Approval rows open the approval detail modal
// (approve/reject/guest links in one panel) — the ONE approvals inbox is
// actionable in place (Rethink v2 Phase E: the legacy "open the project page"
// hack is gone; the Approvals tab folded into this inbox).
openWorkItemFromToday(row) {
    if (row.kind === 'approval') {
        this.openApproval({ id: row.ref_id });
        return;
    }
    this.workReturnTo = { kind: 'route', route: 'today', name: 'Today' };
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
// Set by the first in-app openProject — flags the #/p/ hash as navigation-
// authored (stale) rather than a boot deep link.
_projectVisited: false,
// The cockpit is the DEFAULT landing (Rethink v2 Phase D2) — the deep-admin's
// first stop. Rethink v2 Phase E: deep admin shrinks 14 → 9 — the Overview,
// Vision, Backlog, Time and Approvals tabs folded away (Backlog and Time
// deep-link into the ONE Work view, Approvals into the ONE approvals inbox,
// Vision into Plan depth). NOTHING is deleted as data.
projectTab: 'cockpit',
    // Rethink v2 Phase D2 — project cockpit state: ?tab= URL state + lazy loaders.
    // projectTabLoaders: tab → the datasets its FIRST show loads (the tabLoaded
    // pattern; loadTime/C2's rail/B2's coverage were the reference). openProject
    // keeps only the cockpit's needs — the other tabs load lazily on first show.
    projectTabLoaders: {
        cockpit: ['coverage', 'today', 'activity'],
        kpis: ['kpis', 'traceability'],
        roadmap: ['roadmaps'],
        backlog: ['backlogRail'],
        docs: ['releases', 'vision'],
        risks: ['risks'],
        releases: ['releases'],
        stakeholders: ['stakeholders'],
        infrastructure: ['infrastructure'],
        github: ['githubConfig', 'githubSync'],
        env: ['personas', 'testAccounts'],
    },
    projectTabLoaded: {},      // one lazy-once flag per dataset (reversible per loader)
    projectLoadedFor: null,    // project id whose flags are valid (reset on switch)
    projectNarrative: null,    // per-project last-activity fallback (the cockpit's line)
    narrativeLoadedFor: null,  // project id already fetched for the narrative
    _projectTabWatchersBound: false,
    // Time tracking (Q1) — manual hours log + timesheet lock
    timeEntries: [],
    timeSummary: [],
    timeDate: new Date().toISOString().slice(0, 10),
    timeHours: '',
    timeNote: '',
    timeItem: '',
    timeUser: '',
    timeLoading: false,
    timeSaving: false,

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
    { id: 'decisions', label: 'Decisions', group: 'workspace', icon: '<svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M10.125 2.25h-4.5c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125v-9M10.125 2.25h.375a9 9 0 019 9v.375M10.125 2.25A3.375 3.375 0 0113.5 5.625v1.5c0 .621.504 1.125 1.125 1.125h1.5a3.375 3.375 0 013.375 3.375M9 15l2.25 2.25L15 12"/></svg>' },
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

get pageTitle() {
    return { today: 'Today', work: 'Work', decisions: 'Decisions', dashboard: 'Dashboard', clients: 'Clients', 'client-detail': 'Client Detail', projects: 'Projects', 'project-detail': 'Project Detail', tasks: 'My Tasks', roadmap: 'Roadmaps', docs: 'Documentation', settings: 'Settings' }[this.route] || '';
},
get stats() {
    const ds = this.dashStats || {};
    return [
        { label: 'Total Clients', value: ds.clients ?? this.clients.length, route: 'clients', icon: '<svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"/></svg>', bg: 'bg-brand-50', color: 'text-brand-600', glow: 'bg-brand-300', trend: 'New', trendColor: 'text-emerald-600' },
        { label: 'Active Projects', value: ds.projects ?? this.projects.length, route: 'projects', icon: '<svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2H5a2 2 0 00-2-2z"/></svg>', bg: 'bg-emerald-50', color: 'text-emerald-600', glow: 'bg-emerald-300' },
        { label: 'Backlog Items', value: ds.backlog_items ?? 0, route: 'work', icon: '<svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"/></svg>', bg: 'bg-amber-50', color: 'text-amber-600', glow: 'bg-amber-300' },
        { label: 'Pending Approvals', value: ds.pending_approvals ?? 0, route: 'today', icon: '<svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"/></svg>', bg: 'bg-rose-50', color: 'text-rose-600', glow: 'bg-rose-300' },
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

async api(method, url, body, contentType) {
    const opts = { method, headers: {} };
    if (body instanceof FormData) {
        opts.body = body;  // browser sets the multipart boundary
    } else {
        opts.headers['Content-Type'] = contentType || 'application/json';
        if (body !== undefined && body !== null) {
            opts.body = typeof body === 'string' ? body : JSON.stringify(body);
        }
    }
    if (this.authToken) {
        opts.headers['Authorization'] = 'Bearer ' + this.authToken;
    }
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
// Open a project from a row reference (Work items, Today rows, the
// dashboard's progress list): the FULL project object when it's in the
// loaded list, else a minimal one — openProject's loaders fill the rest.
// A name-only fallback matches the loaded projects by title.
openProjectRef(projectId, name) {
    const pid = Number(projectId);
    const full = (pid && this.projects.find(p => Number(p.id) === pid))
        || this.projects.find(p => name && p.name === name);
    if (full) return this.openProject(full);
    if (pid) return this.openProject({id: pid, name: name || 'Project', client_id: null});
},
async openProject(project) {
    this.selectedProject = project;
    this.route = 'project-detail';
    this.bindProjectTabWatchers();
    // An in-app open authors the #/p/{id}/{tab} hash — tryProjectDeepLink
    // must never treat it as a fresh deep link afterwards.
    this._projectVisited = true;
    // Lazy flags are per project — a different project starts fresh
    if (this.projectLoadedFor !== String(project.id)) {
        this.projectTabLoaded = {};
        this.projectLoadedFor = String(project.id);
        this.projectNarrative = null;
        this.narrativeLoadedFor = null;
    }
    // ?tab= in the URL wins; else this project's last-visited tab; else the cockpit
    this.projectTab = this.readProjectTabFromUrl(project.id) || this.lastProjectTab(project.id) || 'cockpit';
    this.syncProjectTabUrl();
    this.persistProjectTab(project.id, this.projectTab);
    this.initEnvForm();
    // The cockpit is the landing — load ONLY its needs (the other 9 deep-admin
    // tabs load lazily on first show via ensureProjectTabData). Burst: 17
    // loaders → 5. Flags first so the root x-effect never double-fires these
    // datasets. loadApprovals/loadBacklog stay: the verdict bar's gates count,
    // the needs-you rows and the Work card count read them.
    this.projectTabLoaded.health = true;
    this.projectTabLoaded.releases = true;
    this.projectTabLoaded.approvals = true;
    this.projectTabLoaded.risks = true;
    this.projectTabLoaded.backlog = true;
    await Promise.all([
        this.loadProjectHealth(project.id),
        this.loadReleases(),
        this.loadApprovals(),
        this.loadRisks(),
        this.loadBacklog(),
    ]);
},

// ===== Project cockpit (Rethink v2 Phase D2) =====

// Root x-effect on the project-detail section: loads each tab's datasets the
// FIRST time it shows (whatever set projectTab — tab buttons, the cockpit's
// cards, copilot jumps, pasted #/p/{id}/{tab} links), and honors a shared
// deep link after login. Flags make every call after the first a no-op.
projectRouteEffect() {
    if (this.route === 'project-detail' && this.selectedProject) {
        this.ensureProjectTabData(this.projectTab);
        return;
    }
    this.tryProjectDeepLink();
},

// Boot deep-link: a shared #/p/{id}/{tab} opens that project + tab once the
// user is logged in and the projects list exists. The hash is consumed FIRST
// so a failed open can't re-fire the effect on every reactive change.
tryProjectDeepLink() {
    if (!this.isLoggedIn || this.route === 'project-detail') return;
    const m = (window.location.hash || '').match(/^#\/p\/(\d+)\/([a-z-]+)$/);
    if (!m || !this.isValidProjectTab(m[2])) return;
    // STALE-HASH GUARD (the "clicks do nothing" bug): a #/p/{id}/{tab} hash
    // left by in-app navigation must NEVER re-deep-link — projectRouteEffect
    // re-fires this on every route change, so without this guard every
    // navigation away from a project (sidebar, client rows, dashboard cards)
    // bounces straight back into the last project. Only a hash present before
    // the first in-app project open (pasted/bookmarked link at boot) is a real
    // deep link; mid-session links stay covered by the hashchange listener.
    if (this._projectVisited) { this.consumeProjectHash(); return; }
    if (!(this.projects || []).length) return;
    const projectId = m[1];
    const tab = m[2];
    this.consumeProjectHash();
    this.openProjectById(projectId).then(() => {
        if (this.selectedProject && String(this.selectedProject.id) === projectId) this.setProjectTab(tab);
    });
},

// #/p/{id}/{tab} — the project page's state in the URL (survives
// refresh/share/back-forward). A query param was the alternative; the hash
// needs no server route changes.
readProjectTabFromUrl(projectId) {
    const m = (window.location.hash || '').match(/^#\/p\/(\d+)\/([a-z-]+)$/);
    if (m && m[1] === String(projectId) && this.isValidProjectTab(m[2])) return m[2];
    return null;
},

syncProjectTabUrl() {
    if (!this.selectedProject) return;
    const hash = '#/p/' + this.selectedProject.id + '/' + this.projectTab;
    if (window.location.hash !== hash) {
        window.history.replaceState({}, document.title, window.location.pathname + window.location.search + hash);
    }
},

consumeProjectHash() {
    if ((window.location.hash || '').startsWith('#/p/')) {
        window.history.replaceState({}, document.title, window.location.pathname + window.location.search);
    }
},

// Tab switches by anything but the tabs row (cockpit cards, needs-you rows,
// the deep link) go through here so the URL/state stay consistent.
setProjectTab(tab) {
    if (!this.isValidProjectTab(tab)) return;
    this.projectTab = tab;
},

isValidProjectTab(tab) {
    return !!tab && !!this.projectTabLoaders[tab];
},

// Last-visited tab persisted per project (localStorage) — the fallback when
// the URL carries no ?tab=.
lastProjectTab(projectId) {
    try {
        const map = JSON.parse(localStorage.getItem('pmo_project_tabs') || '{}');
        return this.isValidProjectTab(map[String(projectId)]) ? map[String(projectId)] : null;
    } catch { return null; }
},

persistProjectTab(projectId, tab) {
    if (!this.isValidProjectTab(tab)) return;
    try {
        const map = JSON.parse(localStorage.getItem('pmo_project_tabs') || '{}');
        map[String(projectId)] = tab;
        localStorage.setItem('pmo_project_tabs', JSON.stringify(map));
    } catch { /* storage unavailable (private mode) — state stays in the URL */ }
},

// Bind ONCE per session: any projectTab change (tabs, chips, copilot, deep
// link) syncs the URL + last-visited; hashchange covers back/forward and
// pasted links. replaceState keeps one history entry per project open.
bindProjectTabWatchers() {
    if (this._projectTabWatchersBound) return;
    this._projectTabWatchersBound = true;
    this.$watch('projectTab', (tab) => {
        if (this.route !== 'project-detail' || !this.selectedProject) return;
        // Removed tabs (Rethink v2 Phase E: overview/vision/backlog/time/approvals)
        // degrade gracefully to the cockpit — including direct assignments from
        // the copilot's jump table, which bypasses setProjectTab's guard.
        if (!this.isValidProjectTab(tab)) { this.projectTab = 'cockpit'; return; }
        this.syncProjectTabUrl();
        this.persistProjectTab(this.selectedProject.id, tab);
    });
    window.addEventListener('hashchange', () => {
        const m = (window.location.hash || '').match(/^#\/p\/(\d+)\/([a-z-]+)$/);
        if (!m || !this.isValidProjectTab(m[2])) return;
        if (this.selectedProject && String(this.selectedProject.id) === m[1]) {
            if (this.projectTab !== m[2]) this.projectTab = m[2];
        } else {
            this.openProjectById(m[1]);
        }
    });
},

// The lazy loaders: fire each dataset the first time its tab shows. One flag
// per dataset — reversible per loader, the same endpoints and payloads as the
// old openProject burst, only the timing changes.
ensureProjectTabData(tab) {
    if (this.route !== 'project-detail' || !this.selectedProject) return;
    if (this.projectLoadedFor !== String(this.selectedProject.id)) {
        this.projectTabLoaded = {};
        this.projectLoadedFor = String(this.selectedProject.id);
    }
    for (const ds of (this.projectTabLoaders[tab] || [])) {
        if (this.projectTabLoaded[ds]) continue;
        this.projectTabLoaded[ds] = true;
        this.runProjectTabLoader(ds);
    }
},

runProjectTabLoader(ds) {
    switch (ds) {
        case 'health': this.loadProjectHealth(this.selectedProject.id); break;
        case 'releases': this.loadReleases(); break;
        case 'approvals': this.loadApprovals(); break;
        case 'risks': this.loadRisks(); break;
        case 'backlog': this.loadBacklog(); break;
        case 'backlogRail': this.loadBacklogRail(this.selectedProject.id); break;
        case 'coverage': this.loadCoverage(); break;
        case 'today': if (!this.today && !this.todayLoading) this.loadToday(); break;
        case 'activity': this.loadProjectNarrative(); break;
        case 'traceability': this.loadTraceability(); break;
        case 'stakeholders': this.loadStakeholders(); break;
        case 'vision': this.loadVision(); break;
        case 'kpis': this.loadKPIs(); break;
        case 'roadmaps': this.loadRoadmaps(); break;
        case 'time': this.loadTime(); break;
        case 'brdCoverage': this.loadBrdCoverage(this.selectedProject.id); break;
        case 'githubConfig': this.loadGithubBoardConfig(this.selectedProject.id); break;
        case 'githubSync': this.loadGithubSyncStatus(this.selectedProject.id); break;
        case 'personas': this.loadPersonas(); break;
        case 'testAccounts': this.loadTestAccounts(); break;
        case 'infrastructure': this.loadInfrastructure(); break;
    }
},

// Verdict bar (cockpit): the why chips flattened from the health payload —
// B2's rendering, one compact row instead of the deep-admin card.
get projectVerdictChips() {
    const h = this.projectHealth;
    if (!h) return [];
    const chips = [];
    const add = (list, warn) => {
        for (const c of (list || [])) { if (c) chips.push({ label: c, warn: !!warn }); }
    };
    add(h.why?.schedule, false);
    add(h.why?.approvals, (h.pending_approvals || 0) > 0);
    add(h.why?.tasks, (h.overdue_tasks || 0) > 0);
    add(h.why?.kpis, (h.kpis_below_target || 0) > 0);
    return chips;
},

// Verdict bar counts — each one a button into its surface.
get projectPendingGates() {
    return (this.projectApprovals || []).filter(a => (a.status || 'Pending') === 'Pending');
},

get projectNextRelease() {
    const rels = this.projectReleases || [];
    const upcoming = rels
        .filter(r => r.status !== 'Released')
        .sort((a, b) => String(a.target_date || '9999-12-31').localeCompare(String(b.target_date || '9999-12-31')));
    return upcoming[0] || rels[0] || null;
},

get projectOpenRaidCount() {
    return (this.projectRisks || []).filter(r => (r.status || '') !== 'Closed').length;
},

// Risk & Decisions card: RAID from the loaded payload; decisions count only
// when the Decisions panel's payload is already loaded (its route fetches on
// show — never a duplicate store here).
get projectRiskDecisionCount() {
    let n = this.projectOpenRaidCount;
    if (this.decisionsLoaded) {
        const pid = String(this.selectedProject?.id ?? '');
        n += (this.decisions || []).filter(d => String(d.project_id) === pid && (d.status || 'active') !== 'superseded').length;
    }
    return n;
},

// What needs you: the /today needs-you aggregate (server-computed "waiting on
// you", project-scoped) + aging High/Critical risks from the RAID payload.
// today is loaded at login; on a token-restore boot the cockpit's 'today'
// dataset fetches it once.
get projectNeedsYou() {
    if (!this.selectedProject) return [];
    const pid = String(this.selectedProject.id);
    const rows = (this.today?.needs_you || []).filter(r => String(r.project_id) === pid);
    const aging = (this.projectRisks || [])
        .filter(r => (r.status || '') !== 'Closed' && (r.severity === 'High' || r.severity === 'Critical'))
        .sort((a, b) => String(a.created_at || '').localeCompare(String(b.created_at || '')));
    for (const r of aging) {
        rows.push({
            kind: 'risk',
            ref_id: r.id,
            title: r.title,
            why: r.severity + ' severity · aging',
            project_id: r.project_id,
            project: '',
        });
    }
    return rows;
},

// Each needs-you row opens its surface in 1 click: gates → the approval detail
// (approve/reject in one panel — the Approvals tab folded into the ONE approvals
// inbox, Rethink v2 Phase E), risks → the RAID tab, items → the item drawer (the
// ONE Work view's drawer fallback when the backlog row isn't loaded — never a
// re-hosted board).
openCockpitRow(row) {
    if (!row) return;
    if (row.kind === 'approval') { this.openApproval({ id: row.ref_id }); return; }
    if (row.kind === 'risk') { this.setProjectTab('risks'); return; }
    const known = (this.backlogItems || []).find(i => String(i.id) === String(row.ref_id));
    if (known) { this.viewBacklogItem(known); return; }
    this.navigate('work');
    this.openWorkItem({ id: row.ref_id, title: row.title, project: row.project, project_id: row.project_id, phase: '', status: row.kind === 'blocked' ? 'Blocked' : 'In Progress', priority: '', blocked: row.kind === 'blocked', overdue: row.kind === 'overdue' });
},

// Work action card: the ONE Work view pre-filtered to this project (the house
// setWorkProjectFilter pattern — never a re-hosted backlog).
    workReturnTo: null,  // {projectId, tab, name} — set when a project deep-links into Work; the header's back chip consumes it

openWorkWithProject() {
    if (!this.selectedProject) return;
    // Record the origin — the Work header's back chip returns here (before this
    // the intake redirect stranded the user on Work with no way back)
    this.workReturnTo = { kind: 'project', projectId: this.selectedProject.id, tab: this.projectTab || 'backlog', name: this.selectedProject.name };
    this.setWorkProjectFilter(String(this.selectedProject.id));
    this.navigate('work');
},
// The Work header's back chip: return to the origin that deep-linked in —
// a project tab, or the Today route (Today-row → Work detail drawer).
backToProject() {
    const r = this.workReturnTo;
    this.workReturnTo = null;
    if (!r) return;
    if (r.kind === 'route') { this.navigate(r.route || 'today'); return; }
    this.openProjectById(r.projectId);
    if (r.tab && this.isValidProjectTab(r.tab)) this.setProjectTab(r.tab);
},

// Time deep-link (Rethink v2 Phase E): the project's time view is the ONE Work
// view's timeline, pre-filtered to this project — the Work action card's
// "Timeline view" chip, where the legacy Time tab's deep-link lands.
openWorkTimeline() {
    if (!this.selectedProject) return;
    this.workReturnTo = { kind: 'project', projectId: this.selectedProject.id, tab: this.projectTab || 'cockpit', name: this.selectedProject.name };
    this.setWorkProjectFilter(String(this.selectedProject.id));
    this.setWorkViewMode('timeline');
    this.navigate('work');
},

// Approvals deep-link (Rethink v2 Phase E): the ONE approvals inbox is Today's
// needs-you queue — the gate approvals waiting on you across projects, each row
// opening the approval detail (approve/reject/guest links in one panel). The
// legacy Approvals tab folded into it; no second approvals surface was built.
openApprovalInbox() {
    this.navigate('today');
},

// Decisions panel: the route exists; the server filters ?project_id=
openDecisionsPanel() {
    if (!this.selectedProject) return;
    this.decisionProjectFilter = String(this.selectedProject.id);
    this.navigate('decisions');
},

// Narrative line: the project's latest activity, read from the login
// bootstrap's activity feed (zero extra requests); a quiet project fetches
// its own last entry once.
get projectLastActivity() {
    if (!this.selectedProject) return null;
    const pid = String(this.selectedProject.id);
    const rows = (this.activityFeed || []).filter(a => String(a.project_id) === pid);
    if (rows.length) return rows[0];
    return this.projectNarrative;
},

async loadProjectNarrative() {
    if (!this.selectedProject) return;
    if (this.narrativeLoadedFor === String(this.selectedProject.id)) return;
    this.narrativeLoadedFor = String(this.selectedProject.id);
    if ((this.activityFeed || []).some(a => String(a.project_id) === String(this.selectedProject.id))) return;
    try {
        const rows = await this.api('GET', `/activity?project_id=${this.selectedProject.id}&limit=1`);
        this.projectNarrative = (rows && rows[0]) || null;
    } catch { this.projectNarrative = null; }
},

backToProjects() {
    this.selectedProject = null;
    this.route = 'projects';
    this.consumeProjectHash();  // a stale #/p/{id}/{tab} must not re-deep-link
},

async loadBrdCoverage(projectId) {
    try {
        this.brdCoverage = await this.api('GET', `/projects/${projectId}/brd-coverage`);
    } catch { this.brdCoverage = null; }
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

async loadTime() {
    if (!this.selectedProject) return;
    this.timeLoading = true;
    try {
        this.timeEntries = await this.api('GET', `/projects/${this.selectedProject.id}/time-entries`);
        this.timeSummary = await this.api('GET', `/projects/${this.selectedProject.id}/time-summary`);
    } catch { /* keep previous */ }
    finally { this.timeLoading = false; }
},

async logTime() {
    const h = parseFloat(this.timeHours);
    if (!h || h <= 0) { this.showToast('Enter hours first', 'error'); return; }
    if (!this.selectedProject) return;
    this.timeSaving = true;
    try {
        await this.api('POST', `/projects/${this.selectedProject.id}/time-entries`, {
            entry_date: this.timeDate || new Date().toISOString().slice(0, 10),
            hours: h,
            note: this.timeNote || null,
            item_id: this.timeItem ? Number(this.timeItem) : null,
            user_id: this.timeUser ? Number(this.timeUser) : null,
        });
        this.timeHours = ''; this.timeNote = '';
        await this.loadTime();
        this.showToast('Hours logged', 'success');
    } catch(e) { this.showToast(e.message || 'Could not log hours', 'error'); }
    finally { this.timeSaving = false; }
},

async deleteTimeEntry(id) {
    try {
        await this.api('DELETE', `/time-entries/${id}`);
        await this.loadTime();
        this.showToast('Entry removed', 'success');
    } catch(e) { this.showToast(e.message || 'Could not remove entry', 'error'); }
},

async lockWeek(userId, userName) {
    if (!this.selectedProject) return;
    const monday = new Date();
    monday.setDate(monday.getDate() - ((monday.getDay() + 6) % 7));
    const ws = monday.toISOString().slice(0, 10);
    try {
        await this.api('POST', `/projects/${this.selectedProject.id}/timesheets/lock`, { user_id: userId, week_start: ws });
        this.showToast('Week locked for ' + (userName || 'user'), 'success');
    } catch(e) { this.showToast(e.message || 'Could not lock week', 'error'); }
},

};

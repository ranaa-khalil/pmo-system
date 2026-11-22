// PMO System — capture_box.js
// The capture box (§7 #3): one line → the ONE collapsed intake call → the
// amber Confirm bar with per-item drafts + dedupe ("Already captured as #12 —
// merge?") → Confirm/Dismiss. Per-instance Alpine component (registered as
// Alpine.data('captureBox')) — the partial lives once in
// templates/components/capture_box.html and is included from the Work header,
// Today, the drawer's + New item, and the FAB launcher.
//
// Every request rides the root store's api() (auth + error handling in one
// place). Confirm is the human tap that lands the checked items in the
// Requirements lane — POST /api/ai/intake runs the chain, nothing writes
// before /api/ai/intake/confirm; Dismiss records the rejection and writes
// nothing.
const ROOT_SELECTOR = '[x-data="pmoRoot"]';

export function captureBox(boxId = 'capture') {
    return {
        boxId,
        notes: '',
        destination: 'work_item',
        submitting: false,
        confirming: false,
        result: null,
        checked: {},
        parkProjectId: '',

        store() {
            const root = document.querySelector(ROOT_SELECTOR);
            return root && window.Alpine ? window.Alpine.$data(root) : null;
        },

        checkedCount() {
            return Object.values(this.checked).filter(Boolean).length;
        },

        confirmDisabled() {
            if (this.confirming || !this.checkedCount()) return true;
            // Parking-lot drafts need a filed project before they land
            if (this.result && this.result.parking_lot && !this.parkProjectId) return true;
            return false;
        },

        async submit() {
            const text = this.notes.trim();
            if (!text || this.submitting) return;
            const store = this.store();
            if (!store) return;
            this.submitting = true;
            try {
                const body = { notes: text, source: 'capture box', destination: this.destination };
                // The Work project filter is the capture's target project
                const filter = store.workProjectFilter ? Number(store.workProjectFilter) : null;
                if (filter) body.project_id = filter;
                this.result = await store.api('POST', '/ai/intake', body);
                this.checked = {};
                for (const it of (this.result.items || [])) this.checked[it.key] = true;
                if (this.result.project_id) this.parkProjectId = String(this.result.project_id);
                this.notes = '';
            } catch (e) {
                store.showToast(e.message || 'Capture failed', 'error');
            }
            this.submitting = false;
        },

        async confirm() {
            if (this.confirmDisabled() || !this.result) return;
            const store = this.store();
            if (!store) return;
            this.confirming = true;
            try {
                const body = {
                    draft_id: this.result.draft_id,
                    keys: Object.keys(this.checked).filter(k => this.checked[k]),
                    destination: this.destination,
                };
                // The confirm inherits the intake's project; an explicit pick
                // only matters for parking-lot lines (a PM filing them).
                if (this.result.project_id) body.project_id = this.result.project_id;
                else if (this.parkProjectId) body.project_id = Number(this.parkProjectId);
                const res = await store.api('POST', '/ai/intake/confirm', body);
                const n = res.confirmed || 0;
                store.showToast(
                    n ? `Captured — ${n} item(s) landed in Requirements` : 'Nothing new — already captured',
                    'success',
                );
                this.reset();
                store.loadWork();
                if (typeof store.loadToday === 'function') store.loadToday();
            } catch (e) {
                store.showToast(e.message || 'Could not confirm the capture', 'error');
            }
            this.confirming = false;
        },

        async dismiss() {
            if (!this.result || this.confirming) return;
            const store = this.store();
            const draftId = this.result.draft_id;
            this.reset();
            if (store && draftId) {
                try { await store.api('POST', '/ai/intake/dismiss', { draft_id: draftId }); }
                catch { /* the ledger write is best-effort — the bar is already gone */ }
            }
        },

        // The manual path, always visible: open the drawer's + New item in
        // edit mode (the form fallback — interaction rule 7). The drawer
        // lives in the Work view — navigate there first (the
        // openWorkItemFromToday pattern) when the capture ran elsewhere.
        skipToForm() {
            const store = this.store();
            this.reset();
            if (store && typeof store.openWorkItemNew === 'function') {
                if (store.route !== 'work' && typeof store.navigate === 'function') store.navigate('work');
                store.openWorkItemNew();
            }
        },

        reset() {
            this.result = null;
            this.checked = {};
            this.notes = '';
            this.submitting = false;
            this.confirming = false;
        },
    };
}
window.captureBox = captureBox;

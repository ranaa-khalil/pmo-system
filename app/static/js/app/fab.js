// PMO System — fab.js
// Floating Action Button (Quick Add Task) — its own Alpine component.
// State/methods verbatim from the original monolith's inline x-data object.
export const fab = {
    pos: { x: window.innerWidth - 80, y: window.innerHeight - 120 },
    dragging: false,
    moved: false,
    startX: 0, startY: 0,
    offsetX: 0, offsetY: 0,
    showPopup: false,
    quickTitle: '',
    init() {
        try {
            const saved = JSON.parse(localStorage.getItem('fab_pos'));
            if (saved && saved.x > 0 && saved.x < window.innerWidth - 40 && saved.y > 0 && saved.y < window.innerHeight - 40) {
                this.pos = saved;
            }
        } catch {}
    },
    startDrag(e) {
        const touch = e.touches ? e.touches[0] : e;
        this.dragging = true;
        this.moved = false;
        this.startX = touch.clientX;
        this.startY = touch.clientY;
        this.offsetX = touch.clientX - this.pos.x;
        this.offsetY = touch.clientY - this.pos.y;
    },
    onDrag(e) {
        if (!this.dragging) return;
        e.preventDefault();
        const touch = e.touches ? e.touches[0] : e;
        const nx = touch.clientX - this.offsetX;
        const ny = touch.clientY - this.offsetY;
        if (Math.abs(touch.clientX - this.startX) > 4 || Math.abs(touch.clientY - this.startY) > 4) this.moved = true;
        this.pos.x = Math.max(8, Math.min(window.innerWidth - 56, nx));
        this.pos.y = Math.max(8, Math.min(window.innerHeight - 56, ny));
    },
    endDrag() {
        if (!this.dragging) return;
        this.dragging = false;
        if (!this.moved) {
            this.showPopup = !this.showPopup;
        }
        try { localStorage.setItem('fab_pos', JSON.stringify(this.pos)); } catch {}
    },
    submitQuick() {
        if (!this.quickTitle.trim()) return;
        this.$dispatch('quick-add-task', { title: this.quickTitle });
        this.quickTitle = '';
        this.showPopup = false;
    }
};
window.fabComponent = fab;

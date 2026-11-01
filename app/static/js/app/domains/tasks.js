// PMO System — app/tasks.js
// Tasks domain of the Alpine pmoApp() store.
// Fragments are verbatim from the original monolith; pmo-app.js assembles them.

export const tasks = {
// ===== Forgot password =====
showForgotPassword: false,
forgotPasswordStep: 'request',  // 'request' | 'email_sent' | 'reset' | 'success'
hasResetTokenFromUrl: false,
forgotPasswordEmail: '',
forgotPasswordToken: '',
forgotPasswordNewPassword: '',
forgotPasswordConfirmPassword: '',
forgotPasswordError: '',
forgotPasswordLoading: false,
showResetPassword: false,


// ===== Tasks state =====
tasks: [],
tasksLoading: false,
taskSummary: {},
taskFilter: 'all',
taskDateFilter: null,  // ISO date string or null
showTaskModal: false,
editingTask: null,
taskForm: { title: '', description: '', project_id: null, milestone_id: null, due_date: '', priority: 'Medium', status: 'Pending', reminder_days: 3 },


// ===== Tasks (personal to-dos) =====
get filteredTasks() {
    // Start with status filter
    let result;
    if (this.taskFilter === 'all') result = this.tasks;
    else if (this.taskFilter === 'overdue') result = this.tasks.filter(t => t.status !== 'Completed' && t.status !== 'Cancelled' && t.due_date && new Date(t.due_date) < new Date(new Date().toDateString()));
    else if (this.taskFilter === 'pending') result = this.tasks.filter(t => t.status === 'Pending');
    else if (this.taskFilter === 'in_progress') result = this.tasks.filter(t => t.status === 'In Progress');
    else if (this.taskFilter === 'completed') result = this.tasks.filter(t => t.status === 'Completed');
    else result = this.tasks;
    // Apply date filter on top if set
    if (this.taskDateFilter) {
        result = result.filter(t => t.due_date && t.due_date.slice(0, 10) === this.taskDateFilter);
    }
    return result;
},
todayISO() {
    const d = new Date();
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
},
setTodayFilter() {
    const today = this.todayISO();
    this.taskDateFilter = this.taskDateFilter === today ? null : today;
},
get todayTaskCount() {
    const today = this.todayISO();
    return this.tasks.filter(t => t.due_date && t.due_date.slice(0, 10) === today && t.status !== 'Completed' && t.status !== 'Cancelled').length;
},
async loadTasks() {
    this.tasksLoading = true;
    try {
        this.tasks = await this.api('GET', '/tasks');
        this.taskSummary = await this.api('GET', '/tasks/summary');
        // Load roadmaps for milestone dropdown if not already loaded
        if (this.projects.length > 0 && !this.projects[0]._roadmaps) {
            await this.loadAllRoadmaps();
        }
    } catch (e) { console.error('loadTasks', e); }
    this.tasksLoading = false;
},
async refreshTaskSummary() {
    try { this.taskSummary = await this.api('GET', '/tasks/summary'); } catch {}
},
openTaskModal(task = null) {
    this.editingTask = task;
    if (task) {
        this.taskForm = { title: task.title, description: task.description || '', project_id: task.project_id, milestone_id: task.milestone_id, due_date: task.due_date || '', priority: task.priority, status: task.status, reminder_days: task.reminder_days };
    } else {
        this.taskForm = { title: '', description: '', project_id: null, milestone_id: null, due_date: '', priority: 'Medium', status: 'Pending', reminder_days: 3 };
    }
    this.showTagPicker = false;
    if (task) {
        this.loadSubtasks(task.id);
        const t = this.tasks.find(x => x.id === task.id);
        this.taskTags = t && t.tags ? [...t.tags] : [];
        this.loadTagPool();
    } else {
        this.subtasks = []; this.subtaskTotal = 0; this.subtaskDone = 0;
        this.taskTags = [];
    }
    this.showTaskModal = true;
},
async quickAddTask(title) {
    try {
        await this.api('POST', '/tasks', { title, priority: 'Medium', status: 'Pending', reminder_days: 3 });
        this.showToast('Task added: ' + title);
        await this.loadTasks();
        this.refreshTaskSummary();
    } catch (e) { this.showToast('Failed: ' + e.message, 'error'); }
},
closeTaskModal() {
    this.showTaskModal = false;
    this.editingTask = null;
},
async saveTask() {
    if (!this.taskForm.title.trim()) return;
    const payload = { ...this.taskForm };
    if (!payload.due_date) delete payload.due_date;
    if (!payload.project_id) delete payload.project_id;
    if (!payload.milestone_id) delete payload.milestone_id;
    try {
        if (this.editingTask) {
            await this.api('PUT', `/tasks/${this.editingTask.id}`, payload);
        } else {
            await this.api('POST', '/tasks', payload);
        }
        this.closeTaskModal();
        await this.loadTasks();
    } catch (e) { alert('Error saving task: ' + (e.message || e)); }
},
async toggleTaskStatus(task) {
    const newStatus = task.status === 'Completed' ? 'Pending' : (task.status === 'Pending' ? 'In Progress' : 'Completed');
    try {
        await this.api('PUT', `/tasks/${task.id}`, { status: newStatus });
        task.status = newStatus;
        this.refreshTaskSummary();
    } catch (e) { console.error('toggleTaskStatus', e); }
},
async deleteTask(taskId) {
    if (!confirm('Delete this task?')) return;
    try {
        await this.api('DELETE', `/tasks/${taskId}`);
        this.tasks = this.tasks.filter(t => t.id !== taskId);
        this.refreshTaskSummary();
    } catch (e) { alert('Error deleting task: ' + (e.message || e)); }
},
isOverdue(task) {
    return task.due_date && task.status !== 'Completed' && new Date(task.due_date) < new Date(new Date().toDateString());
},
isDueSoon(task) {
    if (!task.due_date || task.status === 'Completed') return false;
    const due = new Date(task.due_date);
    const today = new Date(new Date().toDateString());
    const diff = (due - today) / (1000 * 60 * 60 * 24);
    return diff >= 0 && diff <= (task.reminder_days || 3);
},
formatDate(d) {
    if (!d) return '';
    const date = new Date(d);
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
},

// ===== View mode (List | Board | Calendar) =====
taskViewMode: 'list',  // 'list' | 'board' | 'calendar'
draggingTask: null,  // board drag source
setTaskViewMode(mode) {
    this.taskViewMode = mode;
    this.api('PUT', '/me/preferences', { key: 'task_view_mode', value: mode }).catch(() => {});
},

// ===== Board (Consultant view) =====
get taskBoardColumns() {
    const cols = [
        { status: 'Pending', label: 'Pending', tasks: [] },
        { status: 'In Progress', label: 'In Progress', tasks: [] },
        { status: 'Completed', label: 'Completed', tasks: [] },
    ];
    for (const t of this.filteredTasks) {
        const col = cols.find(c => c.status === t.status);
        (col || cols[0]).tasks.push(t);
    }
    return cols;
},
async onTaskDrop(task, status) {
    if (!task || task.status === status) return;
    const old = task.status;
    task.status = status;  // optimistic
    try {
        await this.api('PUT', `/tasks/${task.id}`, { status });
        this.refreshTaskSummary();
    } catch (e) {
        task.status = old;
        this.showToast('Failed to move task', 'error');
    }
},

// ===== Calendar (Consultant view) =====
taskCalCursor: new Date(),
get taskCalendarLabel() {
    return this.taskCalCursor.toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
},
get taskCalendarWeeks() {
    const y = this.taskCalCursor.getFullYear();
    const m = this.taskCalCursor.getMonth();
    const first = new Date(y, m, 1);
    const start = new Date(first);
    start.setDate(1 - first.getDay());  // back to Sunday
    const weeks = [];
    const todayIso = this.todayISO();
    for (let w = 0; w < 6; w++) {
        const days = [];
        for (let d = 0; d < 7; d++) {
            const dt = new Date(start);
            dt.setDate(start.getDate() + w * 7 + d);
            const iso = `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`;
            days.push({
                iso,
                day: dt.getDate(),
                inMonth: dt.getMonth() === m,
                isToday: iso === todayIso,
                tasks: this.tasks.filter(t => t.due_date && t.due_date.slice(0, 10) === iso),
            });
        }
        weeks.push(days);
    }
    return weeks;
},
taskCalPrev() { const c = new Date(this.taskCalCursor); c.setMonth(c.getMonth() - 1); this.taskCalCursor = c; },
taskCalNext() { const c = new Date(this.taskCalCursor); c.setMonth(c.getMonth() + 1); this.taskCalCursor = c; },
taskCalToday() { this.taskCalCursor = new Date(); },
onCalDayClick(day) {
    if (!day.tasks.length) return;
    this.taskDateFilter = this.taskDateFilter === day.iso ? null : day.iso;
    this.taskViewMode = 'list';
},

// ===== Subtasks (checklists) =====
subtasks: [],
subtaskTotal: 0,
subtaskDone: 0,
subtaskForm: '',
subtasksLoading: false,
async loadSubtasks(taskId) {
    this.subtasks = []; this.subtaskTotal = 0; this.subtaskDone = 0; this.subtaskForm = '';
    if (!taskId) return;
    this.subtasksLoading = true;
    try {
        const data = await this.api('GET', `/tasks/${taskId}/subtasks`);
        this.subtasks = data.subtasks;
        this.subtaskTotal = data.total;
        this.subtaskDone = data.done;
    } catch (e) { console.error('loadSubtasks', e); }
    this.subtasksLoading = false;
},
async addSubtask() {
    const title = (this.subtaskForm || '').trim();
    if (!title || !this.editingTask) return;
    try {
        await this.api('POST', '/tasks', { title, parent_task_id: this.editingTask.id, status: 'Pending', priority: 'Medium', reminder_days: 3 });
        this.subtaskForm = '';
        await this.loadSubtasks(this.editingTask.id);
        await this.loadTasks();
    } catch (e) { this.showToast('Failed to add step', 'error'); }
},
async toggleSubtask(sub) {
    const newStatus = sub.status === 'Completed' ? 'Pending' : 'Completed';
    try {
        await this.api('PUT', `/tasks/${sub.id}`, { status: newStatus });
        sub.status = newStatus;
        this.subtaskDone = this.subtasks.filter(s => s.status === 'Completed').length;
        this.refreshTaskSummary();
    } catch (e) { console.error('toggleSubtask', e); }
},
async deleteSubtask(sub) {
    try {
        await this.api('DELETE', `/tasks/${sub.id}`);
        this.subtasks = this.subtasks.filter(s => s.id !== sub.id);
        this.subtaskTotal = this.subtasks.length;
        this.subtaskDone = this.subtasks.filter(s => s.status === 'Completed').length;
    } catch (e) { this.showToast('Failed to remove step', 'error'); }
},

// ===== Tags (cross-tagging pool) =====
tagPool: [],
tagPoolLoading: false,
taskTags: [],
showTagPicker: false,
newTagName: '',
newTagColor: 'indigo',
async loadTagPool() {
    this.tagPoolLoading = true;
    try { this.tagPool = await this.api('GET', '/tags'); } catch (e) { console.error('loadTagPool', e); }
    this.tagPoolLoading = false;
},
tagChipClass(color) {
    const map = {
        indigo: 'bg-indigo-50 text-indigo-700 border-indigo-200',
        violet: 'bg-violet-50 text-violet-700 border-violet-200',
        blue: 'bg-blue-50 text-blue-700 border-blue-200',
        emerald: 'bg-emerald-50 text-emerald-700 border-emerald-200',
        amber: 'bg-amber-50 text-amber-700 border-amber-200',
        rose: 'bg-rose-50 text-rose-700 border-rose-200',
        slate: 'bg-slate-100 text-slate-600 border-slate-200',
    };
    return map[color] || map.indigo;
},
tagDotClass(color) {
    const map = {
        indigo: 'bg-indigo-400',
        violet: 'bg-violet-400',
        blue: 'bg-blue-400',
        emerald: 'bg-emerald-400',
        amber: 'bg-amber-400',
        rose: 'bg-rose-400',
        slate: 'bg-slate-400',
    };
    return map[color] || map.indigo;
},
async attachTagToTask(tag) {
    if (!this.editingTask) return;
    try {
        await this.api('POST', `/tasks/${this.editingTask.id}/tags`, { tag_id: tag.id });
        this.taskTags.push(tag);
        this.showTagPicker = false;
    } catch (e) { this.showToast('Failed to attach tag', 'error'); }
},
async detachTagFromTask(tag) {
    if (!this.editingTask) return;
    try {
        await this.api('DELETE', `/tasks/${this.editingTask.id}/tags/${tag.id}`);
        this.taskTags = this.taskTags.filter(t => t.id !== tag.id);
    } catch (e) { this.showToast('Failed to remove tag', 'error'); }
},
async createTagInline() {
    const name = (this.newTagName || '').trim();
    if (!name) return;
    try {
        const tag = await this.api('POST', '/tags', { name, color: this.newTagColor });
        this.tagPool.push(tag);
        this.newTagName = '';
        this.newTagColor = 'indigo';
        await this.attachTagToTask(tag);
    } catch (e) { this.showToast(e.message || 'Failed to create tag', 'error'); }
},

};

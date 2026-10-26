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

};

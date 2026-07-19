/**
 * scheduler-batch.js - AI Proposed Tasks Management logic
 * Handles: Table rendering, Individual edit/delete, Batch processing
 */

class BatchProcessor {
    constructor() {
        this.proposedTasks = [];
        this.selectedIds = new Set();
        this.searchTerm = '';
        this.init();
    }

    init() {
        document.addEventListener('DOMContentLoaded', () => {
            this.refreshTable();
            this.setupListeners();
        });
    }

    setupListeners() {
        // Select all checkbox
        const selectAll = document.getElementById('selectAllTasks');
        if (selectAll) {
            selectAll.addEventListener('change', (e) => {
                const checkboxes = document.querySelectorAll('.task-checkbox');
                checkboxes.forEach(cb => {
                    cb.checked = e.target.checked;
                    const id = parseInt(cb.getAttribute('data-id'));
                    if (e.target.checked) this.selectedIds.add(id);
                    else this.selectedIds.delete(id);
                });
                this.updateBatchGroupVisibility();
            });
        }

        // Save job button
        document.getElementById('btn-save-job')?.addEventListener('click', () => this.saveJob());

        // Delete job trigger button (opens reason container)
        document.getElementById('btn-delete-job-trigger')?.addEventListener('click', () => {
            const reasonContainer = document.getElementById('deletion-reason-container');
            if (reasonContainer.style.display === 'none') {
                reasonContainer.style.display = 'block';
                document.getElementById('btn-delete-job-trigger').innerText = 'Confirm Delete';
                document.getElementById('btn-delete-job-trigger').classList.remove('aot-pill-btn-danger');
                document.getElementById('btn-delete-job-trigger').classList.add('btn-danger'); // More prominent
            } else {
                this.deleteJob();
            }
        });
    }

    handleSearch(term) {
        this.searchTerm = term.toLowerCase();
        this.renderTable();
    }

    async refreshTable() {
        const body = document.getElementById('proposed-tasks-body');
        if (!body) return;

        try {
            const response = await fetch('/api/scheduler/jobs/proposed');
            this.proposedTasks = await response.json();
            this.renderTable();
        } catch (error) {
            console.error('Failed to refresh proposed tasks:', error);
            body.innerHTML = '<tr><td colspan="6" class="text-center py-4 text-danger">Error loading tasks.</td></tr>';
        }
    }

    renderTable() {
        const body = document.getElementById('proposed-tasks-body');
        if (!body) return;

        const filteredTasks = this.proposedTasks.filter(job => {
            if (!this.searchTerm) return true;
            return (
                job.action_type.toLowerCase().includes(this.searchTerm) ||
                job.target_id.toLowerCase().includes(this.searchTerm) ||
                (job.reasoning && job.reasoning.toLowerCase().includes(this.searchTerm))
            );
        });

        if (filteredTasks.length === 0) {
            body.innerHTML = `<tr><td colspan="6" class="text-center py-5 text-muted">${this.searchTerm ? 'No matching tasks found.' : 'No proposed tasks found.'}</td></tr>`;
            return;
        }

        body.innerHTML = '';
        filteredTasks.forEach(job => {
            const row = document.createElement('tr');
                row.innerHTML = `
                    <td style="padding-left: 1.5rem;">
                        <div class="custom-control custom-checkbox">
                            <input type="checkbox" class="custom-control-input task-checkbox" id="check-${job.id}" data-id="${job.id}">
                            <label class="custom-control-label" for="check-${job.id}"></label>
                        </div>
                    </td>
                    <td><span class="badge badge-info">${job.action_type.toUpperCase()}</span></td>
                    <td><code>${job.target_id}</code></td>
                    <td>${new Date(job.schedule_time).toLocaleString()}</td>
                    <td><span class="badge badge-secondary">${job.state}</span></td>
                    <td class="text-right px-3 whitespace-nowrap">
                        <div class="btn-group btn-group-sm">
                            <button class="btn btn-outline-primary" title="Edit" onclick="window.batchProcessor.openEditModal(${job.id})">
                                <i class="fa fa-edit"></i>
                            </button>
                            <button class="btn btn-outline-success" title="Approve" onclick="window.batchProcessor.handleSingleAction(${job.id}, 'approve')">
                                <i class="fa fa-check"></i>
                            </button>
                            <button class="btn btn-outline-warning" title="Reject" onclick="window.batchProcessor.handleSingleAction(${job.id}, 'reject')">
                                <i class="fa fa-times"></i>
                            </button>
                            <button class="btn btn-outline-danger" title="Delete" onclick="window.batchProcessor.openEditModal(${job.id}, true)">
                                <i class="fa fa-trash"></i>
                            </button>
                        </div>
                    </td>
                `;
                
                // Add change listener to checkbox
                const cb = row.querySelector('.task-checkbox');
                cb.addEventListener('change', (e) => {
                    const id = parseInt(e.target.getAttribute('data-id'));
                    if (e.target.checked) this.selectedIds.add(id);
                    else this.selectedIds.delete(id);
                    this.updateBatchGroupVisibility();
                });

                body.appendChild(row);
        });
    }

    updateBatchGroupVisibility() {
        const group = document.getElementById('batch-action-group');
        if (group) {
            group.style.display = this.selectedIds.size > 0 ? 'flex' : 'none';
        }
    }

    openEditModal(jobId, directDelete = false) {
        const job = this.proposedTasks.find(j => j.id === jobId);
        if (!job) return;

        document.getElementById('edit-job-id').value = job.id;
        document.getElementById('edit-job-action').value = job.action_type;
        document.getElementById('edit-job-target').value = job.target_id;
        document.getElementById('edit-job-time').value = job.schedule_time.slice(0, 16);
        document.getElementById('edit-job-reasoning').value = job.reasoning || '';
        
        // Deletion specific setup
        const delBtn = document.getElementById('btn-delete-job-trigger');
        const reasonContainer = document.getElementById('deletion-reason-container');
        
        if (directDelete) {
            reasonContainer.style.display = 'block';
            delBtn.innerText = 'Confirm Delete';
            delBtn.classList.remove('aot-pill-btn-danger');
            delBtn.classList.add('btn-danger');
        } else {
            delBtn.innerText = 'Delete Task';
            delBtn.classList.remove('btn-danger');
            delBtn.classList.add('aot-pill-btn-danger');
            reasonContainer.style.display = 'none';
        }

        $('#jobEditModal').modal('show');
    }

    async saveJob() {
        const id = document.getElementById('edit-job-id').value;
        const data = {
            action_type: document.getElementById('edit-job-action').value,
            target_id: document.getElementById('edit-job-target').value,
            schedule_time: document.getElementById('edit-job-time').value
        };

        try {
            const response = await fetch(`/api/scheduler/job/${id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });

            if (response.ok) {
                $('#jobEditModal').modal('hide');
                this.refreshTable();
                if (window.aotGantt) window.aotGantt.refresh();
            } else {
                alert('Failed to save changes.');
            }
        } catch (error) {
            console.error('Save failed:', error);
        }
    }

    async deleteJob() {
        const id = document.getElementById('edit-job-id').value;
        const reason = document.getElementById('edit-job-delete-reason').value;

        if (!reason) {
            alert('Please provide a reason for deletion.');
            return;
        }

        try {
            const response = await fetch(`/api/scheduler/job/${id}`, {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ reason: reason })
            });

            if (response.ok) {
                $('#jobEditModal').modal('hide');
                this.refreshTable();
                if (window.aotGantt) window.aotGantt.refresh();
            } else {
                alert('Failed to delete job.');
            }
        } catch (error) {
            console.error('Delete failed:', error);
        }
    }

    async handleSingleAction(id, action) {
        try {
            const response = await fetch('/api/scheduler/jobs/batch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    job_ids: [id],
                    action: action
                })
            });

            if (response.ok) {
                this.refreshTable();
                if (window.aotGantt) window.aotGantt.refresh();
            } else {
                alert(`Failed to ${action} job.`);
            }
        } catch (error) {
            console.error(`${action} failed:`, error);
        }
    }

    async handleBatch(action) {
        if (this.selectedIds.size === 0) return;

        let reason = '';
        if (action === 'delete') {
            reason = prompt('Please provide a reason for global deletion:');
            if (reason === null) return; // Cancelled
        }

        try {
            const response = await fetch('/api/scheduler/jobs/batch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    job_ids: Array.from(this.selectedIds),
                    action: action,
                    reason: reason
                })
            });

            if (response.ok) {
                this.selectedIds.clear();
                this.refreshTable();
                if (window.aotGantt) window.aotGantt.refresh();
            } else {
                alert(`Batch ${action} failed.`);
            }
        } catch (error) {
            console.error('Batch action failed:', error);
        }
    }
}

window.batchProcessor = new BatchProcessor();

/**
 * AoT AI Gantt Component
 * Handles hierarchical visualization and manipulation of AI tasks.
 */
class AoTAIGantt {
    constructor(macroContainerId, microContainerId) {
        this.macroContainer = document.getElementById(macroContainerId);
        this.microContainer = document.getElementById(microContainerId);
        
        this.macroTimeline = null;
        this.microTimeline = null;
        
        // DataSets
        this.items = new vis.DataSet(); // Micro Detailed
        this.macroItems = new vis.DataSet(); // Macro Milestones
        this.groups = new vis.DataSet();
        this.macroGroups = new vis.DataSet();
        
        this.isSyncing = false; // Infinite loop protection
        
        this.commonOptions = {
            stack: true,
            selectable: true,
            editable: { add: false, updateTime: true, updateGroup: true, remove: false },
            verticalScroll: true,
            zoomKey: 'ctrlKey',
            orientation: 'top',
            tooltip: { followMouse: true, overflowMethod: 'cap' }
        };

        this.microOptions = {
            ...this.commonOptions,
            groupTemplate: (group) => this.renderGroupTemplate(group),
            onMove: (item, callback) => {
                // When drag completes, save to backend and refresh parent bars
                this.handleItemTimeUpdate(item).then(() => callback(item));
            },
            snap: null
        };

        this.macroOptions = {
            ...this.commonOptions,
            selectable: true,
            editable: false,
            zoomable: false, // Macro view zoom is handled via Micro or fixed buttons
            height: '100%'
        };

        this.selectedTaskId = null;
        this.selectedGroupId = null;
        this.globalControls = $('#gantt-global-controls');
        this.modal = $('#taskEditModal');
        this.form = $('#taskEditForm');
        this.btnSave = $('#btn-save-task');
        this.btnDelete = $('#btn-delete-task');
    }

    renderGroupTemplate(group) {
        const container = document.createElement('div');
        container.className = 'gantt-group-container';

        const depth = group.depth || 0;
        container.style.paddingLeft = `${depth * 18}px`;

        // Hierarchy icon
        if (group.isParentGroup) {
            container.classList.add('gantt-group-root');
            const icon = document.createElement('span');
            icon.textContent = '📁 ';
            icon.style.marginRight = '4px';
            container.appendChild(icon);
        } else if (depth > 0) {
            const icon = document.createElement('span');
            icon.textContent = '└ ';
            icon.style.color = '#aaa';
            icon.style.marginRight = '2px';
            container.appendChild(icon);
        }

        const label = document.createElement('span');
        label.className = group.isParentGroup ? 'gantt-group-parent' : (depth > 0 ? 'gantt-group-child' : '');
        label.innerText = group.content;
        label.style.cursor = 'pointer';
        label.title = window._('Click to edit');

        // Single click -> open edit modal
        label.onclick = (e) => {
            e.stopPropagation();
            this.handleTaskSelection(group.id);
        };

        // Double click -> inline rename
        label.ondblclick = (e) => {
            e.stopPropagation();
            this.enterInlineEdit(group.id, label);
        };
        
        container.appendChild(label);
        return container;
    }

    async init() {
        if (!this.macroContainer || !this.microContainer) return;

        this.macroTimeline = new vis.Timeline(this.macroContainer, this.macroItems, this.macroGroups, this.macroOptions);
        this.microTimeline = new vis.Timeline(this.microContainer, this.items, this.groups, this.microOptions);
        
        // --- Sync Logic (Macro <-> Micro) ---
        
        // 1. Macro Click -> Jump Micro
        this.macroTimeline.on('select', (properties) => {
            if (properties.items.length > 0) {
                const item = this.macroItems.get(properties.items[0]);
                if (item && item.start && item.end) {
                    this.isSyncing = true;
                    this.microTimeline.setWindow(item.start, item.end, { animation: true }, () => {
                        this.isSyncing = false;
                    });
                }
            }
        });

        // 2. Micro Range Change -> Macro Highlight (Silent Sync)
        this.microTimeline.on('rangechanged', (properties) => {
            if (this.isSyncing) return;
            
            this.updateMacroHighlight(properties.start, properties.end);
            this.handleZoomAggregation(properties.start, properties.end);
        });

        // Note: Drag updates are handled by onMove in microOptions

        // Bar click only tracks selection (no modal - avoids conflict with drag/resize)
        this.microTimeline.on('select', (properties) => {
            if (properties.items && properties.items.length > 0) {
                this.selectedTaskId = properties.items[0];
            } else {
                this.selectedTaskId = null;
            }
        });

        // Right-click Context Menu for Proposed Tasks
        this.microTimeline.on('contextmenu', (props) => {
            props.event.preventDefault();
            const itemId = this.microTimeline.getEventProperties(props.event).item;
            if (!itemId) return;
            const item = this.items.get(itemId);
            if (!item || !item._raw) return;
            
            if (item._raw.status === 'PROPOSED') {
                this.showContextMenu(props.event, item._raw.id);
            }
        });

        // Control Bindings
        $('#btn-global-up').on('click', () => this.handleMoveUp(this.selectedGroupId || this.selectedTaskId));
        $('#btn-global-down').on('click', () => this.handleMoveDown(this.selectedGroupId || this.selectedTaskId));
        $('#btn-global-indent').on('click', () => this.handleIndent(this.selectedGroupId || this.selectedTaskId));
        $('#btn-global-outdent').on('click', () => this.handleOutdent(this.selectedGroupId || this.selectedTaskId));
        $('.btn-scale').on('click', (e) => {
            const unit = $(e.target).data('unit');
            this.setGanttScale(unit);
            $('.btn-scale').removeClass('active');
            $(e.target).addClass('active');
        });
        $('#btn-gantt-today').on('click', () => this.moveToToday());
        $('#btn-refresh-gantt').on('click', () => this.refresh());
        $('#btn-add-task').on('click', () => this.openAddTaskModal());
        $('#btn-toggle-macro').on('click', () => $('#ai-gantt-macro-container').toggleClass('active'));

        // Modal Save & Delete Bindings
        this.btnSave.on('click', () => this.saveTask());
        this.btnDelete.on('click', () => this.deleteTask());

        await this.refresh();
    }

    updateMacroHighlight(start, end) {
        // Use a background item in Macro to show Micro's current view
        const indicatorId = 'micro_view_indicator';
        if (this.macroItems.get(indicatorId)) {
            this.macroItems.update({ id: indicatorId, start: start, end: end });
        } else {
            this.macroItems.add({
                id: indicatorId,
                type: 'background',
                start: start,
                end: end,
                className: 'macro-indicator'
            });
        }
    }

    handleZoomAggregation(start, end) {
        const diffDays = (new Date(end) - new Date(start)) / (1000 * 3600 * 24);
        const modeBadge = $('#view-mode-badge');
        
        if (diffDays > 30) {
            modeBadge.text('Monthly Aggregation');
            // Logic to swap setItems with aggregated data (placeholder)
        } else if (diffDays > 7) {
            modeBadge.text('Weekly View');
        } else {
            modeBadge.text('Daily Detailed');
        }
    }

    setGanttScale(unit) {
        if (!this.microTimeline) return;
        const center = new Date();
        let start, end;
        const dayMs = 24 * 60 * 60 * 1000;

        switch (unit) {
            case 'day': start = center.getTime() - dayMs/2; end = center.getTime() + dayMs/2; break;
            case 'week': start = center.getTime() - (7*dayMs)/2; end = center.getTime() + (7*dayMs)/2; break;
            case 'month': start = center.getTime() - (30*dayMs)/2; end = center.getTime() + (30*dayMs)/2; break;
            case 'year': start = center.getTime() - (365*dayMs)/2; end = center.getTime() + (365*dayMs)/2; break;
            default: return;
        }
        this.isSyncing = true;
        this.microTimeline.setWindow(start, end, { animation: true }, () => {
            this.isSyncing = false;
        });
    }

    moveToToday() {
        if (!this.microTimeline) return;
        this.microTimeline.moveTo(new Date());
    }



    async refresh() {
        try {
            const response = await fetch('/api/v1/ai/tasks');
            const data = await response.json();
            
            this.items.clear();
            this.groups.clear();
            this.macroItems.clear();
            this.macroGroups.clear();

            this.macroGroups.add({ id: 'macro_milestones', content: 'Strategic Milestones', className: 'gantt-group-header' });

            const groups = [];
            const items = [];
            const processedGroups = new Set();

            // Build lookup maps for O(1) access (performance optimization)
            const generalTasks = data.filter(t => t.layer === 'general');
            const taskMap = new Map();       // id -> task object
            const childrenMap = new Map();   // parent_id -> [child task objects]
            const childMap = {};             // parent_id -> [child_ids] (for nestedGroups)
            generalTasks.forEach(t => {
                taskMap.set(t.id, t);
                if (t.parent_id) {
                    if (!childMap[t.parent_id]) childMap[t.parent_id] = [];
                    childMap[t.parent_id].push(t.id);
                    if (!childrenMap.has(t.parent_id)) childrenMap.set(t.parent_id, []);
                    childrenMap.get(t.parent_id).push(t);
                }
            });

            data.forEach(task => {
                if (task.type === 'milestone') {
                    if (task.start) {
                        this.macroItems.add({
                            id: task.id,
                            group: 'macro_milestones',
                            content: task.content,
                            start: task.start,
                            end: task.end,
                            className: 'vis-item-milestone'
                        });
                    }
                }
                
                if (task.layer === 'general') {
                    const isProposed = task.status === 'PROPOSED';
                    const isParent = !!childMap[task.id];
                    const isChild = !!task.parent_id;
                    const depth = this._getDepth(task.id, taskMap);
                    
                    if (!processedGroups.has(task.id)) {
                        const groupDef = {
                            id: task.id,
                            content: task.content,
                            layer: 'general',
                            type: task.type,
                            depth: depth,
                            isParentGroup: isParent,
                            className: isParent ? 'gantt-row-parent' : (isChild ? 'gantt-row-child' : ''),
                            isRoot: !task.parent_id
                        };

                        // Use nestedGroups for parent tasks
                        if (isParent) {
                            groupDef.nestedGroups = childMap[task.id];
                            groupDef.showNested = true;
                        }

                        groups.push(groupDef);
                        processedGroups.add(task.id);
                    }

                    const statusLabelsDesktop = {
                        'in_progress': window._('In progress'), 'completed': window._('Completed'),
                        'pending': window._('Pending'), 'failed': window._('Failed'), 'PROPOSED': window._('AI suggestion')
                    };
                    const statusText = statusLabelsDesktop[task.status] || task.status;
                    const parentInfo = task.parent_id ? `<br>${window._('Parent')}: ${this._findTaskTitle(task.parent_id, taskMap)}` : '';

                    if (isParent) {
                        // --- PARENT: Summary bar with duration from children ---
                        const childRange = this._getChildRange(task.id, childrenMap);
                        const summaryStart = childRange.start || task.start;
                        const summaryEnd = childRange.end || task.end;
                        const childCount = (childMap[task.id] || []).length;
                        const tooltipHtml = `<b>📁 ${task.content}</b><br>${window._('Subtasks')}: ${childCount}<br>${window._('Status')}: ${statusText}<br>${window._('Duration')}: ${window._('auto-calculated from subtasks')}<br>${window._('Click to edit')}`;

                        if (summaryStart) {
                            items.push({
                                id: task.id,
                                group: task.id,
                                content: `◆ ${task.content}`,
                                start: summaryStart,
                                end: summaryEnd,
                                className: 'gantt-summary-bar',
                                title: tooltipHtml,
                                _raw: task
                            });
                        }
                    } else {
                        // --- CHILD or STANDALONE: Normal task bar ---
                        const tooltipHtml = `<b>${task.content}</b><br>${window._('Status')}: ${statusText}${parentInfo}<br>${window._('Click to edit')}`;

                        if (task.start) {
                            items.push({
                                id: task.id,
                                group: task.id,
                                content: isProposed ? `✨ ${task.content}` : task.content,
                                start: task.start,
                                end: task.end,
                                className: `task-status-${task.status} ${isProposed ? 'ai-proposed-item' : ''}`,
                                title: tooltipHtml,
                                _raw: task
                            });
                        }
                    }
                }
            });

            this.groups.add(groups);
            this.items.add(items);

            // Mobile Card List rendering
            this.renderMobileCards(data);
        } catch (e) {
            console.error("Gantt refresh failed", e);
        }
    }

    _getDepth(taskId, taskMap) {
        let depth = 0;
        let current = taskMap.get(taskId);
        while (current && current.parent_id) {
            depth++;
            current = taskMap.get(current.parent_id);
            if (depth > 10) break;
        }
        return depth;
    }

    _findTaskTitle(taskId, taskMap) {
        const t = taskMap.get(taskId);
        return t ? t.content : '';
    }

    _getChildRange(parentId, childrenMap) {
        const children = childrenMap.get(parentId);
        if (!children || children.length === 0) return { start: null, end: null };

        let minStart = null;
        let maxEnd = null;

        children.forEach(child => {
            if (child.start) {
                const s = new Date(child.start);
                if (!minStart || s < minStart) minStart = s;
            }
            if (child.end) {
                const e = new Date(child.end);
                if (!maxEnd || e > maxEnd) maxEnd = e;
            }
            // Recurse into grandchildren
            const grandRange = this._getChildRange(child.id, childrenMap);
            if (grandRange.start) {
                const gs = new Date(grandRange.start);
                if (!minStart || gs < minStart) minStart = gs;
            }
            if (grandRange.end) {
                const ge = new Date(grandRange.end);
                if (!maxEnd || ge > maxEnd) maxEnd = ge;
            }
        });

        return {
            start: minStart ? minStart.toISOString() : null,
            end: maxEnd ? maxEnd.toISOString() : null
        };
    }

    renderMobileCards(tasks) {
        const container = document.getElementById('mobile-task-list');
        if (!container) return;

        const generalTasks = tasks.filter(t => t.layer === 'general');
        if (generalTasks.length === 0) {
            container.innerHTML = '<div class="mobile-empty-state">' + window._('No tasks registered.') + '<br>' + window._('Add one with the Add Task button at the top.') + '</div>';
            return;
        }

        // Store for click handler
        this._mobileTaskData = generalTasks;

        const statusLabels = {
            'in_progress': window._('In progress'),
            'completed': window._('Completed'),
            'pending': window._('Pending'),
            'failed': window._('Failed'),
            'PROPOSED': window._('AI suggestion')
        };

        const formatDate = (d) => {
            if (!d) return '';
            const date = new Date(d);
            return `${date.getMonth()+1}/${date.getDate()}`;
        };

        container.innerHTML = generalTasks.map(task => {
            const status = task.status || 'pending';
            const label = statusLabels[status] || status;
            const dateRange = (task.start && task.end) 
                ? `${formatDate(task.start)} ~ ${formatDate(task.end)}`
                : '';
            const isProposed = status === 'PROPOSED';

            return `
                <div class="mobile-task-card status-${status}" data-task-id="${task.id}">
                    <div class="task-title">${isProposed ? '✨ ' : ''}${task.content}</div>
                    <div class="task-meta">${dateRange}</div>
                    <span class="task-status-badge badge-${status}">${label}</span>
                </div>
            `;
        }).join('');

        // Tap to edit - directly populate modal from raw data
        container.querySelectorAll('.mobile-task-card').forEach(card => {
            card.addEventListener('click', () => {
                const taskId = card.dataset.taskId;
                const task = this._mobileTaskData.find(t => String(t.id) === String(taskId));
                if (!task) return;

                $('#edit-task-id').val(task.id);
                $('#edit-task-title').val(task.content);
                $('#edit-task-desc').val(task.description || '');
                $('#edit-task-status').val(task.status);
                $('#edit-task-type').val(task.type || 'task');

                if (task.start) $('#edit-task-start').val(this.formatDateForInput(task.start));
                if (task.end) $('#edit-task-end').val(this.formatDateForInput(task.end));

                $('#taskModalLabel').text('Edit Task');
                this.btnDelete.show();
                this.modal.modal('show');
            });
        });
    }

    // ===== Context Menu Handlers (AI Proposals) =====
    showContextMenu(event, taskId) {
        // Remove existing menu if any
        $('#ai-gantt-context-menu').remove();
        
        // Ensure menu stays within window bounds
        let x = event.pageX;
        let y = event.pageY;
        
        const menuHtml = `
            <div id="ai-gantt-context-menu" class="dropdown-menu show" style="position: absolute; left: ${x}px; top: ${y}px; z-index: var(--aot-z-dropdown); border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.15);">
                <a class="dropdown-item text-success" href="#" onclick="window.aotGantt.handleApproveTask('${taskId}'); return false;" style="font-weight: 500; padding: 10px 20px;">
                    <i class="fa fa-check mr-2"></i> ${window._('Approve suggestion')}
                </a>
                <div class="dropdown-divider"></div>
                <a class="dropdown-item text-danger" href="#" onclick="window.aotGantt.handleRejectTask('${taskId}'); return false;" style="font-weight: 500; padding: 10px 20px;">
                    <i class="fa fa-times mr-2"></i> ${window._('Reject suggestion')}
                </a>
            </div>
        `;
        $('body').append(menuHtml);
        
        // Remove on click outside
        setTimeout(() => {
            $(document).one('click', function() {
                $('#ai-gantt-context-menu').remove();
            });
        }, 50);
    }

    async handleApproveTask(taskId) {
        if (!confirm(window._('Approve the AI-suggested schedule and add it to the calendar?'))) return;
        try {
            const response = await fetch('/api/v1/ai/task/approve', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ task_id: taskId })
            });
            if (response.ok) {
                window.showToast?.(window._('AI-suggested schedule approved.'), 'success');
                this.refresh();
            } else {
                const err = await response.json();
                window.showToast?.(err.message || window._('Approval failed'), 'error');
            }
        } catch (e) {
            console.error(e);
            window.showToast?.(window._('Network error'), 'error');
        }
    }

    async handleRejectTask(taskId) {
        if (!confirm(window._('Reject and delete this suggestion?'))) return;
        try {
            const response = await fetch('/api/v1/ai/task/reject', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ task_id: taskId })
            });
            if (response.ok) {
                window.showToast?.(window._('Suggestion rejected and deleted.'), 'success');
                this.refresh();
            } else {
                const err = await response.json();
                window.showToast?.(err.message || window._('Rejection failed'), 'error');
            }
        } catch (e) {
            console.error(e);
            window.showToast?.(window._('Network error'), 'error');
        }
    }

    // ===== Hierarchy Control Handlers =====
    async handleIndent(taskId) {
        const item = this.items.get(taskId);
        if (!item || !item._raw) return;
        
        const parentId = item._raw.parent_id;
        const siblings = this.items.get().filter(i => i._raw && i._raw.parent_id === parentId && i._raw.layer === 'general');
        
        const myIdx = siblings.findIndex(s => s.id === taskId);
        if (myIdx > 0) {
            const newParentId = siblings[myIdx - 1].id;
            await this.updateTaskParent(taskId, newParentId);
        } else {
            window.showToast?.(window._('No parent task to indent under'), 'info');
        }
    }

    async handleOutdent(taskId) {
        const item = this.items.get(taskId);
        if (!item || !item._raw) return;
        
        const parentId = item._raw.parent_id;
        if (!parentId) {
            window.showToast?.(window._('Already a top-level task'), 'info');
            return;
        }

        const parentTask = this.items.get(parentId);
        const newParentId = parentTask ? parentTask._raw.parent_id : null;
        await this.updateTaskParent(taskId, newParentId);
    }

    async handleMoveUp(taskId) {
        if (!taskId) return;
        await this.updateTaskOrder(taskId, 'up');
    }

    async handleMoveDown(taskId) {
        if (!taskId) return;
        await this.updateTaskOrder(taskId, 'down');
    }

    async updateTaskOrder(taskId, direction) {
        const response = await fetch('/api/v1/ai/task/reorder', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ task_id: taskId, direction: direction })
        });
        if (response.ok) {
            window.showToast?.(window._('Order updated'), 'success');
            this.refresh();
        } else {
            const err = await response.json();
            window.showToast?.(err.message || window._('Update failed'), 'error');
        }
    }

    async updateTaskParent(taskId, parentId) {
        const response = await fetch('/api/v1/ai/task/reorder', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ task_id: taskId, parent_id: parentId })
        });
        if (response.ok) {
            window.showToast?.(window._('Hierarchy updated'), 'success');
            this.refresh();
        } else {
            const err = await response.json();
            window.showToast?.(err.message || window._('Update failed'), 'error');
        }
    }

    enterInlineEdit(taskId, labelElement) {
        const currentName = labelElement.innerText;
        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'gantt-inline-editor';
        input.value = currentName;
        
        const parent = labelElement.parentNode;
        parent.replaceChild(input, labelElement);
        input.focus();
        input.select();

        const save = async () => {
            const newName = input.value.trim();
            if (newName && newName !== currentName) {
                const response = await fetch('/api/v1/ai/task/update', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ task_id: taskId, title: newName })
                });
                if (response.ok) {
                    window.showToast?.(window._('Name updated'), 'success');
                    this.refresh();
                } else {
                    window.showToast?.(window._('Update failed'), 'error');
                    parent.replaceChild(labelElement, input);
                }
            } else {
                parent.replaceChild(labelElement, input);
            }
        };

        input.onkeydown = (e) => {
            if (e.key === 'Enter') save();
            if (e.key === 'Escape') parent.replaceChild(labelElement, input);
        };
        input.onblur = () => save();
    }

    // ===== Modal Operations =====
    openAddTaskModal() {
        this.form[0].reset();
        $('#edit-task-id').val('');
        $('#taskModalLabel').text('Add New Task');
        this.btnDelete.hide();
        this.populateParentSelect(null);
        this.modal.modal('show');
    }

    handleTaskSelection(taskId) {
        const item = this.items.get(taskId);
        if (!item) return;

        const task = item._raw;
        if (!task || task.layer === 'aot') {
            window.showToast?.('AoT jobs are managed by the AI engine', 'info');
            return;
        }

        $('#edit-task-id').val(task.id);
        $('#edit-task-title').val(task.content);
        $('#edit-task-desc').val(task.description || '');
        $('#edit-task-status').val(task.status);
        $('#edit-task-type').val(task.type || 'task');
        this.populateParentSelect(task.parent_id, task.id);

        if (task.start) $('#edit-task-start').val(this.formatDateForInput(task.start));
        if (task.end) $('#edit-task-end').val(this.formatDateForInput(task.end));

        $('#taskModalLabel').text('Edit Task');
        this.btnDelete.show();
        this.modal.modal('show');
    }

    populateParentSelect(currentParentId, currentTaskId) {
        const select = $('#edit-task-parent');
        select.empty();
        select.append('<option value="">None (Top Level)</option>');
        this.items.get().filter(i => i._raw && i._raw.layer === 'general' && i.id !== currentTaskId).forEach(task => {
            select.append(`<option value="${task.id}" ${task.id === currentParentId ? 'selected' : ''}>${task.content}</option>`);
        });
    }

    async saveTask() {
        const taskId = $('#edit-task-id').val();
        const data = {
            title: $('#edit-task-title').val(),
            description: $('#edit-task-desc').val(),
            status: $('#edit-task-status').val(),
            task_type: $('#edit-task-type').val(),
            parent_id: $('#edit-task-parent').val() || null,
            start_date: $('#edit-task-start').val(),
            end_date: $('#edit-task-end').val()
        };

        const url = taskId ? '/api/v1/ai/task/update' : '/api/v1/ai/task/add';
        if (taskId) data.task_id = taskId;

        const response = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });

        if (response.ok) {
            window.showToast?.('Task saved successfully', 'success');
            this.modal.modal('hide');
            this.refresh();
        } else {
            const err = await response.json();
            window.showToast?.(err.message || 'Error saving task', 'error');
        }
    }

    async deleteTask() {
        const taskId = $('#edit-task-id').val();
        if (!taskId) return;
        if (!confirm('Are you sure you want to delete this task?')) return;

        const response = await fetch(`/api/v1/ai/task/delete/${taskId}`, { method: 'POST' });
        if (response.ok) {
            window.showToast?.('Task deleted', 'success');
            this.modal.modal('hide');
            this.refresh();
        } else {
            window.showToast?.('Failed to delete task', 'error');
        }
    }

    // ===== Utility =====
    formatDateForInput(dateStr) {
        if (!dateStr) return '';
        const d = new Date(dateStr);
        return d.toISOString().slice(0, 16);
    }

    async handleItemTimeUpdate(item) {
        const updateData = {
            task_id: item.id,
            start_date: item.start instanceof Date ? item.start.toISOString() : item.start,
            end_date: item.end instanceof Date ? item.end.toISOString() : item.end
        };

        const response = await fetch('/api/v1/ai/task/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(updateData)
        });

        if (response.ok) {
            window.showToast?.(window._('Schedule updated'), 'success');
            // Refresh to recalculate parent summary bars
            await this.refresh();
        } else {
            window.showToast?.(window._('Update failed'), 'error');
            await this.refresh();
        }
    }
}

// Global initialization (v2.0 Dual Viewport)
window.addEventListener('DOMContentLoaded', () => {
    if (document.getElementById('ai-gantt-micro-container')) {
        window.aotGantt = new AoTAIGantt('ai-gantt-macro-container', 'ai-gantt-micro-container');
        window.aiGantt = window.aotGantt;
        window.aotGantt.init();
    }
});

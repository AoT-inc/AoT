/**
 * MCP Server Management UI Logic
 * Handles server lifecycle (start/stop/restart/config) and tool inspection.
 */

$(document).ready(function() {
    const API_BASE = '/api/v1/mcp';
    const $grid = $('#mcp-server-grid');
    const $toolsContainer = $('#tools-container');

    /**
     * Fetch all MCP servers and render grid
     */
    function loadServers() {
        $grid.html('<div class="col-12 text-center py-5 loading-state"><div class="spinner-border text-primary"></div><p class="mt-3">Updating server status...</p></div>');
        
        fetch(`${API_BASE}/servers`)
            .then(res => res.json())
            .then(data => {
                renderServers(data);
            })
            .catch(err => {
                showToast('Failed to load MCP servers', 'error');
                $grid.html('<div class="col-12 text-center py-5"><i class="fas fa-exclamation-triangle fa-3x text-danger mb-3"></i><p>Connection failed</p></div>');
            });
    }

    /**
     * Render grid of server cards
     */
    function renderServers(servers) {
        if (!servers || servers.length === 0) {
            $grid.html('<div class="col-12 text-center py-5"><p class="text-muted">No MCP servers configured yet.</p></div>');
            return;
        }

        let html = '';
        servers.forEach(server => {
            const isRunning  = server.status === 'running';
            const isCooldown = server.status === 'cooldown';
            const statusClass = isRunning  ? 'status-running'
                              : isCooldown ? 'status-error'
                              : 'status-stopped';
            const statusIcon  = isRunning  ? 'fa-play-circle'
                              : isCooldown ? 'fa-clock'
                              : 'fa-stop-circle';  // v25 BF-05
            
            html += `
            <div class="col-md-6 col-lg-4 mb-4">
                <div class="server-card h-100" data-id="${server.unique_id}">
                    <div class="d-flex justify-content-between align-items-start mb-3">
                        <div class="status-indicator ${statusClass}">
                            <i class="fas ${statusIcon} mr-1"></i> ${server.status}
                        </div>
                        <div class="dropdown">
                            <button class="btn btn-link p-0 text-muted" data-toggle="dropdown">
                                <i class="fas fa-ellipsis-v"></i>
                            </button>
                            <div class="dropdown-menu dropdown-menu-right glass-effect">
                                <a class="dropdown-item btn-edit" href="#" onclick="event.preventDefault();"><i class="fas fa-edit mr-2"></i>Edit</a>
                                <a class="dropdown-item btn-delete text-danger" href="#" onclick="event.preventDefault();"><i class="fas fa-trash-alt mr-2"></i>Delete</a>
                            </div>
                        </div>
                    </div>
                    
                    <h4 class="font-weight-bold mb-2">${server.name}</h4>
                    
                    <div class="mb-3">
                        <div class="server-info-label">Command</div>
                        <div class="server-info-value text-truncate">${server.command}</div>
                    </div>

                    <div class="flex-grow-1"></div>

                    <div class="d-flex justify-content-between align-items-center mt-3 pt-3 border-top border-light">
                        <div class="btn-group">
                            ${isRunning ? `
                                <button class="btn btn-sm btn-premium-secondary btn-restart" title="Restart">
                                    <i class="fas fa-sync-alt"></i>
                                </button>
                                <button class="btn btn-sm btn-premium-secondary btn-stop" title="Stop">
                                    <i class="fas fa-stop"></i>
                                </button>
                            ` : `
                                <button class="btn btn-sm btn-premium-primary btn-start">
                                    <i class="fas fa-play mr-1"></i> Start
                                </button>
                            `}
                        </div>
                        <button class="btn btn-sm btn-outline-info rounded-pill px-3 btn-view-tools">
                            <i class="fas fa-tools mr-1"></i> Tools
                        </button>
                    </div>
                </div>
            </div>`;
        });
        $grid.html(html);
    }

    // --- Actions ---

    $grid.on('click', '.btn-start', function() {
        const id = $(this).closest('.server-card').data('id');
        fetch(`${API_BASE}/servers/${id}/restart`, { method: 'POST' })
            .then(res => res.json())
            .then(res => {
                showToast(res.message, res.status === 'success' ? 'success' : 'error');
                loadServers();
            });
    });

    $grid.on('click', '.btn-stop', function() {
        const id = $(this).closest('.server-card').data('id');
        fetch(`${API_BASE}/servers/${id}/stop`, { method: 'POST' })
            .then(res => res.json())
            .then(res => {
                showToast(res.message, res.status === 'success' ? 'success' : 'error');
                loadServers();
            });
    });  // v25 BF-03

    $grid.on('click', '.btn-restart', function() {
        const id = $(this).closest('.server-card').data('id');
        $(this).find('i').addClass('fa-spin');
        fetch(`${API_BASE}/servers/${id}/restart`, { method: 'POST' })
            .then(res => res.json())
            .then(res => {
                showToast(res.message, res.status === 'success' ? 'success' : 'error');
                loadServers();
            });
    });

    $grid.on('click', '.btn-view-tools', function() {
        const id = $(this).closest('.server-card').data('id');
        $toolsContainer.html('<div class="text-center p-4"><div class="spinner-border text-info"></div></div>');
        $('#modal-view-tools').modal('show');
        
        fetch(`${API_BASE}/servers/${id}/tools`)  // v25 BF-01
            .then(res => res.json())
            .then(data => {
                if (!data || !data.tools) {
                    $toolsContainer.html('<div class="text-center p-4 text-muted">No tools exposed by this server.</div>');
                    return;
                }
                const tools = data.tools;
                if (tools.length === 0) {
                    $toolsContainer.html('<div class="text-center p-4 text-muted">No tools exposed by this server.</div>');
                    return;
                }
                let html = '';
                tools.forEach(tool => {
                    html += `
                    <div class="list-group-item bg-transparent border-0 mb-3 glass-effect p-3">
                        <div class="d-flex w-100 justify-content-between">
                            <h5 class="mb-1 font-weight-bold text-primary">${tool.name}</h5>
                        </div>
                        <p class="mb-1 text-muted small">${tool.description || 'No description provided.'}</p>
                        <hr class="my-2 border-light">
                        <div class="small">
                            <span class="font-weight-bold">Schema:</span>
                            <pre class="bg-dark text-light p-2 rounded mt-1" style="font-size: 0.75rem;">${JSON.stringify(tool.inputSchema, null, 2)}</pre>
                        </div>
                    </div>`;
                });
                $toolsContainer.html(html);
            });
    });

    $('#btn-refresh-all').click(loadServers);

    // --- Modal Logic ---

    $('#btn-save-server').click(function() {
        const formData = {
            name: $('#server-name').val(),
            command: $('#server-command').val(),
            env_json: $('#server-env').val(),
            scope: $('#server-scope').val(),
            is_activated: $('#server-is-activated').prop('checked')  // v25 BF-04
        };
        const id = $('#server-unique-id').val();
        
        const method = id ? 'PUT' : 'POST';  // v25 BF-02
        const url = id ? `${API_BASE}/servers/${id}` : `${API_BASE}/servers`;

        fetch(url, {
            method: method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(formData)
        })
        .then(res => res.json())
        .then(res => {
            if (res.status === 'success') {
                showToast(id ? 'Configuration updated' : 'Server added', 'success');
                $('#modal-add-server').modal('hide');
                loadServers();
            } else {
                showToast(res.message || 'Error saving configuration', 'error');
            }
        });
    });

    // Edit: prefill modal with server data  // v25 BF-04
    $grid.on('click', '.btn-edit', function() {
        const $card = $(this).closest('.server-card');
        const id = $card.data('id');
        const name = $card.find('h4').text().trim();
        const command = $card.find('.server-info-value').first().text().trim();

        $('#server-unique-id').val(id);
        $('#server-name').val(name);
        $('#server-command').val(command);
        $('#server-env').val('');
        $('#server-scope').val('general');
        $('#server-is-activated').prop('checked', false);

        // Fetch full server data for accurate prefill
        fetch(`${API_BASE}/servers`)
            .then(res => res.json())
            .then(servers => {
                const server = servers.find(s => s.unique_id == id);
                if (server) {
                    $('#server-name').val(server.name);
                    $('#server-command').val(server.command);
                    $('#server-env').val(server.env_json || '');
                    $('#server-scope').val(server.scope || 'general');
                    $('#server-is-activated').prop('checked', server.is_activated || false);
                }
            });

        $('#modal-add-server').modal('show');
    });

    // Reset modal on open for "Add"
    $('#btn-add-server').click(function() {
        $('#form-mcp-server')[0].reset();
        $('#server-unique-id').val('');
    });

    // Initial Load
    loadServers();
});

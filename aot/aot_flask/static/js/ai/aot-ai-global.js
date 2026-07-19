/**
 * aot-ai-global.js
 * Global AI Assistant Singleton for AoT
 */

const AoT_AI = (function() {
    let threadId = localStorage.getItem('aot_ai_thread_id') || null;
    let isOpen = false;
    let pageContext = null;
    // True only when pageContext is an EXPLICIT device/modal focus (set via
    // openChat(context) while configuring a device). When false, pageContext is
    // auto-captured and MUST be refreshed every send to reflect the current page
    // — otherwise it sticks to whatever page the chat was first opened on
    // (the "AI always describes the 김제 dashboard" bug).
    let pageContextExplicit = false;
    let currentAbortController = null;

    // Composer state — pending image attachments and judgment-level controls.
    let attachments = [];  // [{ media_type, base64_data, dataUrl, bytes }]
    let currentDepth = localStorage.getItem('aot_ai_depth') || 'fast';        // 'fast' | 'deep'
    let currentAutonomy = localStorage.getItem('aot_ai_autonomy') || 'approve'; // 'advice' | 'approve' | 'auto'
    const MAX_ATTACHMENTS = 3;
    const MAX_ATTACH_BYTES = 5 * 1024 * 1024; // 5MB per image (matches backend cap)
    const MAX_IMAGE_DIM = 1568;               // longest edge after client resize

    function _getCsrfToken() {
        const meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute('content') : '';
    }

    function _init() {
        // console.log("AoT AI: Initializing Global Assistant...");

        _renderUI();
        _bindEvents();

        // REQ-3: Always hydrate from the server on mount so that conversation
        // history is restored even if browser storage was cleared.
        _hydrateFromServer();
    }

    /**
     * REQ-3: Hydrate conversation history from server on every page load.
     * If threadId is cached in localStorage, load that thread.
     * Otherwise fetch the user's thread list and restore the most recent one.
     */
    async function _hydrateFromServer() {
        if (threadId) {
            // Thread ID is cached — load its messages from the server (REQ-3)
            _loadHistory(0, true);
        } else {
            // localStorage was cleared or first visit — recover latest thread from server
            try {
                const resp = await fetch('/api/chat/history');
                if (!resp.ok) return;
                const data = await resp.json();
                if (data.threads && data.threads.length > 0) {
                    threadId = data.threads[0].thread_id;
                    // Repopulate localStorage cache from server data
                    localStorage.setItem('aot_ai_thread_id', threadId);
                    _loadHistory(0, true);
                }
            } catch (err) {
                console.warn("AoT AI: Could not recover thread list from server", err);
            }
        }
    }

    function _renderUI() {
        // Check if UI elements already exist in HTML (from layout_default.html)
        const existingFab = document.getElementById('ai-fab');
        const existingDrawer = document.getElementById('ai-chat-drawer');
        
        if (existingFab && existingDrawer) {
            // console.log("AoT AI: Using existing UI elements from HTML");
            return; // Use existing HTML elements
        }
        
        // Legacy fallback: Create UI if not found (should not happen with new layout)
        console.warn("AoT AI: HTML elements not found, creating dynamically (legacy mode)");
        
        if (!document.getElementById('aot-ai-fab')) {
            // FAB
            const fab = document.createElement('button');
            fab.id = 'aot-ai-fab';
            fab.innerHTML = '<span class="fab-text">AI</span>';
            document.body.appendChild(fab);
        }

        if (!document.getElementById('aot-ai-drawer')) {
            // Drawer
            const drawer = document.createElement('div');
            drawer.id = 'aot-ai-drawer';
            drawer.innerHTML = `
                <div class="ai-drawer-header">
                    <h5>AI Assistant</h5>
                    <button class="ai-close-btn">&times;</button>
                </div>
                <div class="ai-drawer-body" id="ai-messages-container">
                    <div class="ai-msg ai-msg-bot">${window._('Hello! How can I help you? Ask me anything about your AoT system settings or status.')}</div>
                </div>
                <div class="ai-drawer-footer">
                    <div id="ai-context-indicator"></div>
                    <div class="ai-input-group">
                        <textarea id="ai-global-input" placeholder="${window._('Type a message...')}" rows="1"></textarea>
                        <button class="ai-send-btn">
                            <span class="btn-icon">
                                <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>
                            </span>
                        </button>
                    </div>
                </div>
            `;
            document.body.appendChild(drawer);
        }
    }

    function _bindEvents() {
        // Support both old IDs (legacy) and new IDs (from HTML)
        const fab = document.getElementById('ai-fab') || document.getElementById('aot-ai-fab');
        const closeBtn = document.getElementById('ai-close-btn') || document.querySelector('.ai-close-btn');
        const sendBtn = document.getElementById('ai-send-btn') || document.querySelector('.ai-send-btn');
        const input = document.getElementById('ai-chat-input') || document.getElementById('ai-global-input');

        if (!fab || !closeBtn || !sendBtn || !input) {
            console.error("AoT AI: Required UI elements not found", { fab, closeBtn, sendBtn, input });
            return;
        }

        fab.addEventListener('click', () => AoT_AI.toggleChat());
        closeBtn.addEventListener('click', () => AoT_AI.closeChat());

        // Infinite Scroll Listener
        const container = document.getElementById('ai-chat-messages') || document.getElementById('ai-messages-container');
        if (container) {
            container.addEventListener('scroll', () => {
                if (container.scrollTop === 0 && !container.classList.contains('loading-history')) {
                    const currentCount = container.querySelectorAll('.ai-msg').length;
                    _loadHistory(currentCount);
                }
            });
        }

        sendBtn.addEventListener('click', () => _handleSend());
        
        // Handle textarea auto-height and shortcuts
        input.addEventListener('input', function() {
            this.style.height = 'auto';
            this.style.height = (this.scrollHeight) + 'px';
        });

        input.addEventListener('keydown', (e) => {
            // Handle IME composition (prevents double send on Korean/Japanese input)
            if (e.isComposing || e.keyCode === 229) return;

            // Send on Enter (without Shift)
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                _handleSend();
            }
            
            // Legacy support: Send on Cmd/Ctrl + Enter
            if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                e.preventDefault();
                _handleSend();
            }
        });

        // --- Composer extras: mode toggles, attachments, new chat, mobile auto-hide ---
        _initModeToggles();

        const attachBtn = document.getElementById('ai-attach-btn');
        const fileInput = document.getElementById('ai-file-input');
        if (attachBtn && fileInput) {
            attachBtn.addEventListener('click', () => fileInput.click());
            fileInput.addEventListener('change', (e) => {
                _handleFiles(e.target.files);
                fileInput.value = ''; // allow re-selecting the same file
            });
        }

        const newChatBtn = document.getElementById('ai-new-chat-btn');
        if (newChatBtn) newChatBtn.addEventListener('click', () => AoT_AI.newConversation());

        _bindScrollAutoHide(fab);

        // Listen for context-specific triggers from other components
        window.addEventListener('open-ai-chat', (e) => {
            const context = e.detail || {};
            AoT_AI.openChat(context);
        });

        // [FIX] Bootstrap Modal Compatibility: Remove ai-drawer-active when modal opens
        $(document).on('show.bs.modal', '.modal', function() {
            // Store drawer state before modal opens
            const wasDrawerOpen = isOpen;
            if (wasDrawerOpen) {
                $(this).data('aot-drawer-was-open', true);
            }
            // Always remove the class to prevent modal issues (both desktop and mobile)
            document.body.classList.remove('ai-drawer-active');
            
            // [MOBILE FIX] Force remove any inline padding styles
            document.body.style.paddingRight = '';
        });

        // [FIX] Bootstrap Modal Compatibility: Restore ai-drawer-active when modal closes
        $(document).on('hidden.bs.modal', '.modal', function() {
            // Restore drawer state after modal closes (desktop only)
            const wasDrawerOpen = $(this).data('aot-drawer-was-open');
            if (wasDrawerOpen && isOpen && window.innerWidth > 480) {
                document.body.classList.add('ai-drawer-active');
            }
            $(this).removeData('aot-drawer-was-open');
            
            // [MOBILE FIX] Ensure no lingering padding on mobile
            if (window.innerWidth <= 480) {
                document.body.style.paddingRight = '';
            }
        });
    }

    async function _handleSend(overrideText = null, isAuto = false) {
        const input = document.getElementById('ai-chat-input') || document.getElementById('ai-global-input');
        const sendBtn = document.getElementById('ai-send-btn') || document.querySelector('.ai-send-btn');
        
        // Check if we are currently waiting for a response
        if (sendBtn && sendBtn.classList.contains('thinking')) {
            if (currentAbortController) {
                currentAbortController.abort();
                currentAbortController = null;
            }
            sendBtn.classList.remove('thinking');
            return;
        }

        const text = overrideText || input.value.trim();
        // Attachments only ride along with a real user send (not auto/override messages).
        const sendAttachments = overrideText ? [] : attachments.filter(a => a.base64_data);
        if (!text && sendAttachments.length === 0) return;

        // Backend requires a non-empty message; supply a default when sending images alone.
        const effectiveText = text || window._('Please look at the attached image(s).');

        if (!overrideText) {
            input.value = '';
            input.style.height = 'auto'; // Reset height
            _clearAttachments();
        }
        _appendMessage(effectiveText, 'user', [], null, false, sendAttachments);

        // Set busy state
        if (sendBtn) sendBtn.classList.add('thinking');

        // Re-capture the current page every send UNLESS an explicit device/modal
        // focus is active. Capturing only once (the old `if (!pageContext)`) left
        // the context stuck on the first page the chat was opened on.
        if (!pageContextExplicit) {
            pageContext = _capturePageContext();
        }

        currentAbortController = new AbortController();

        // Placeholder message that will be replaced on final response
        const thinkingMsg = document.createElement('div');
        thinkingMsg.className = 'ai-msg ai-msg-bot ai-msg-thinking';
        thinkingMsg.innerText = window._('Thinking...');
        const container = document.getElementById('ai-chat-messages') || document.getElementById('ai-messages-container');
        if (container) { container.appendChild(thinkingMsg); container.scrollTop = container.scrollHeight; }

        try {
            const response = await fetch('/api/v1/ai/portal/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': _getCsrfToken() },
                body: JSON.stringify({
                    message: effectiveText,
                    thread_id: threadId,
                    stream: true,
                    page_context: pageContext || _capturePageContext(),
                    current_dashboard_id: (pageContext ? pageContext.dashboard_id : null) || _capturePageContext().dashboard_id,
                    // Images ride in a top-level key (NOT page_context) so they are never
                    // json.dumps'd into the text prompt. media_type + raw base64 (no data: prefix).
                    attachments: sendAttachments.map(a => ({ media_type: a.media_type, base64_data: a.base64_data })),
                    mode: { depth: currentDepth, autonomy: currentAutonomy }
                }),
                signal: currentAbortController.signal
            });

            if (!response.ok) {
                const errText = await response.text();
                if (thinkingMsg.parentNode) thinkingMsg.remove();
                _appendMessage("Error: HTTP " + response.status, 'bot');
                return;
            }

            // Read SSE stream
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            let finalData = null;

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop();
                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    try {
                        const evt = JSON.parse(line.slice(6));
                        if (evt.status === 'planning') {
                            thinkingMsg.innerText = window._('Analyzing...');
                        } else if (evt.status === 'plan_ready' && evt.insight) {
                            thinkingMsg.innerText = evt.insight.slice(0, 60) + '...';
                        } else if (evt.status === 'success' || evt.status === 'error') {
                            finalData = evt;
                        }
                    } catch (_) {}
                }
            }

            if (thinkingMsg.parentNode) thinkingMsg.remove();

            if (finalData) {
                if (finalData.status === 'success') {
                    threadId = finalData.thread_id;
                    localStorage.setItem('aot_ai_thread_id', threadId);
                    _appendMessage(finalData.message, 'bot', finalData.actions || [], finalData.history_id,
                                   false, null, finalData.ask_user_options || []);
                } else {
                    _appendMessage("Error: " + (finalData.message || window._("An error occurred.")), 'bot');
                }
            } else {
                _appendMessage(window._("No response received. Please try again."), 'bot');
            }

        } catch (err) {
            if (thinkingMsg.parentNode) thinkingMsg.remove();
            if (err.name === 'AbortError') {
                _appendMessage(window._("Request canceled. (stopped by user)"), 'bot');
            } else {
                console.error('[AoT AI] fetch error:', err.name, err.message);
                _appendMessage(window._("A system error occurred. Please try again shortly."), 'bot');
            }
        } finally {
            if (sendBtn) sendBtn.classList.remove('thinking');
            currentAbortController = null;
        }
    }

    function _appendMessage(text, type, actions = [], historyId = null, isPrepend = false, msgAttachments = null, options = []) {
        const container = document.getElementById('ai-chat-messages') || document.getElementById('ai-messages-container');
        const msg = document.createElement('div');
        msg.className = `ai-msg ai-msg-${type}`;
        msg.innerText = text;

        // Render attached images (local send: dataUrl thumbnail) or history chips
        // (metadata only: {media_type} → "[Image]" chip). Placed above the text.
        if (msgAttachments && msgAttachments.length) {
            const attWrap = document.createElement('div');
            attWrap.className = 'ai-msg-attachments';
            msgAttachments.forEach(a => {
                if (a && a.dataUrl) {
                    const im = document.createElement('img');
                    im.src = a.dataUrl;
                    im.alt = '';
                    attWrap.appendChild(im);
                } else {
                    const chip = document.createElement('span');
                    chip.className = 'ai-msg-attach-chip';
                    chip.textContent = window._('Image');
                    attWrap.appendChild(chip);
                }
            });
            msg.insertBefore(attWrap, msg.firstChild);
        }

        // Agent-loop ask_user options: render each as a clickable chip that sends
        // itself as the next message (the answer to the AI's clarifying question).
        // Reuses the existing .ai-action-* styling — no new CSS. Only on bot msgs.
        if (options && options.length > 0 && type !== 'user') {
            const optWrap = document.createElement('div');
            optWrap.className = 'ai-actions-container ai-ask-options';
            options.forEach((opt) => {
                const label = (typeof opt === 'string') ? opt : (opt && (opt.label || opt.value) || '');
                if (!label) return;
                const btn = document.createElement('button');
                btn.className = 'ai-action-btn';
                btn.textContent = label;
                btn.addEventListener('click', () => {
                    // Disable all sibling option buttons once one is chosen.
                    optWrap.querySelectorAll('.ai-action-btn').forEach(b => { b.disabled = true; });
                    btn.classList.add('ai-action-btn-all');
                    _handleSend(label);
                });
                optWrap.appendChild(btn);
            });
            if (optWrap.children.length) msg.appendChild(optWrap);
        }

        if (actions && actions.length > 0 && historyId) {
            const actionsContainer = document.createElement('div');
            actionsContainer.className = 'ai-actions-container';

            // Renders one Approve & Execute button per action. Used for a single
            // action directly, and lazily for the "approve individually" path so a
            // long device list doesn't force the user to scroll a wall of buttons.
            const _renderIndividual = () => {
                actions.forEach((action, index) => {
                    const actionCard = document.createElement('div');
                    actionCard.className = 'ai-action-card';
                    actionCard.innerHTML = `
                        <div class="ai-action-info">
                            <div class="ai-action-desc">${action.description || action.display_summary || action.tool_name || 'Approve Action'}</div>
                            <button class="ai-action-btn" data-history-id="${historyId}" data-index="${index}">${window._('Approve & Execute')}</button>
                        </div>`;
                    actionsContainer.appendChild(actionCard);
                    const btn = actionCard.querySelector('.ai-action-btn');
                    btn.addEventListener('click', () => _executeAction(btn, historyId, index));
                });
            };

            if (actions.length > 1) {
                // Multiple devices: show only two compact choices up front — approve
                // ALL at once, or switch to per-device approval (which then reveals the
                // individual buttons). Keeps the proposal to two lines regardless of
                // device count (10 or 100).
                const choice = document.createElement('div');
                choice.className = 'ai-action-card ai-action-choice';
                choice.innerHTML = `
                    <div class="ai-action-info">
                        <button class="ai-action-btn ai-action-btn-all" data-history-id="${historyId}">${window._('Approve & Execute All')} (${actions.length})</button>
                        <button class="ai-action-btn ai-action-btn-individual">${window._('Approve individually')}</button>
                    </div>`;
                actionsContainer.appendChild(choice);
                choice.querySelector('.ai-action-btn-all')
                    .addEventListener('click', (e) => _executeAllActions(e.currentTarget, historyId, actions.length, actionsContainer));
                choice.querySelector('.ai-action-btn-individual')
                    .addEventListener('click', () => { choice.remove(); _renderIndividual(); });
            } else {
                _renderIndividual();
            }
            msg.appendChild(actionsContainer);
        }

        if (isPrepend) {
            const oldHeight = container.scrollHeight;
            container.prepend(msg);
            // Maintain scroll position after prepend
            container.scrollTop = container.scrollHeight - oldHeight;
        } else {
            container.appendChild(msg);
            container.scrollTop = container.scrollHeight;
        }
    }

    async function _loadHistory(offset, isInitial = false) {
        const container = document.getElementById('ai-chat-messages') || document.getElementById('ai-messages-container');
        if (!container || !threadId) return;

        container.classList.add('loading-history');
        try {
            const response = await fetch(`/api/chat/history?thread_id=${threadId}&offset=${offset}&limit=10`);
            const data = await response.json();

            if (data.history && data.history.length > 0) {
                // Return history is in chronological order, so we process it backwards to prepend correctly
                // No, the backend reversed it to be chronological for the batch.
                // So we prepend from the end of the batch to the beginning of the batch?
                // Actually, if we prepend in order: 1, 2, 3 -> result is 3, 2, 1 at top.
                // So we should prepend in REVERSE order of the batch.
                const batch = data.history;
                for (let i = batch.length - 1; i >= 0; i--) {
                    const item = batch[i];
                    _appendMessage(item.content, item.message_type === 'user' ? 'user' : 'bot', item.actions, item.id, true, item.attachments);
                }
                // On the FIRST hydration, the prepend-anchor logic (meant to keep the
                // viewport stable during scroll-up paging) leaves the scroll mid-thread.
                // The user expects the newest message — jump to the bottom instead.
                if (isInitial) _scrollToBottom(container);
            }
        } catch (err) {
            console.error("AoT AI: Failed to load history", err);
        } finally {
            container.classList.remove('loading-history');
        }
    }

    // Jump the messages pane to the newest message. rAF-deferred so it runs after
    // layout (and once more, to settle image thumbnails that change row heights).
    function _scrollToBottom(container) {
        const el = container || document.getElementById('ai-chat-messages') || document.getElementById('ai-messages-container');
        if (!el) return;
        const jump = () => { el.scrollTop = el.scrollHeight; };
        jump();
        requestAnimationFrame(() => { jump(); requestAnimationFrame(jump); });
    }

    async function _executeAction(button, historyId, index) {
        const originalText = button.innerText;
        button.innerText = 'Executing...';
        button.disabled = true;

        try {
            const response = await fetch('/api/v1/ai/portal/chat/action', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': _getCsrfToken() },
                body: JSON.stringify({
                    history_id: historyId,
                    action_index: index
                })
            });

            const data = await response.json();
            if (data.status === 'success') {
                button.innerText = window._('Executed');
                const status = document.createElement('div');
                status.className = 'ai-action-status';
                // data.result may be an object (execution dict) — extract a readable
                // field instead of stringifying to "[object Object]".
                let _rt = data.result;
                if (_rt && typeof _rt === 'object') {
                    _rt = _rt.message || _rt.display_summary || _rt.summary || null;
                }
                status.innerText = '✓ ' + (_rt || window._('Done'));
                button.parentNode.appendChild(status);
            } else {
                button.innerText = 'Failed';
                button.disabled = false;
                const errorMsg = data.message || data.error || "Unknown error";
                alert("Action failed: " + errorMsg);
            }
        } catch (err) {
            button.innerText = 'Error';
            button.disabled = false;
            console.error("Action execution error:", err);
        }
    }

    // Batch approval — execute ALL proposed actions of one message in a single
    // request, and mark every per-action button as executed. Avoids N clicks.
    async function _executeAllActions(button, historyId, count, actionsContainer) {
        button.innerText = window._('Executing...');
        button.disabled = true;
        try {
            const response = await fetch('/api/v1/ai/portal/chat/action', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': _getCsrfToken() },
                body: JSON.stringify({ history_id: historyId, action_index: 'all' })
            });
            const data = await response.json();
            if (data.status === 'success') {
                const results = Array.isArray(data.results) ? data.results : [];
                button.innerText = window._('Executed');
                // Reflect on each individual button.
                actionsContainer.querySelectorAll('.ai-action-btn:not(.ai-action-btn-all)').forEach((b, i) => {
                    const ok = !results[i] || results[i].status === 'success';
                    b.innerText = ok ? window._('Executed') : 'Failed';
                    b.disabled = ok;
                });
                const status = document.createElement('div');
                status.className = 'ai-action-status';
                const okc = results.filter(r => !r || r.status === 'success').length || count;
                status.innerText = '✓ ' + window._('Done') + ' (' + okc + '/' + count + ')';
                button.parentNode.appendChild(status);
            } else {
                button.innerText = 'Failed';
                button.disabled = false;
                alert("Action failed: " + (data.message || data.error || "Unknown error"));
            }
        } catch (err) {
            button.innerText = 'Error';
            button.disabled = false;
            console.error("Batch action execution error:", err);
        }
    }

    function _capturePageContext() {
        const context = {
            url: window.location.href,
            title: document.title,
            timestamp: new Date().toISOString(),
            dashboard_id: null,
            active_modal: null,
            widget_snapshots: []
        };

        // 1. Detect Dashboard ID from URL path or query
        const pathParts = window.location.pathname.split('/');
        if (pathParts.includes('dashboard')) {
            const idx = pathParts.indexOf('dashboard');
            if (pathParts[idx + 1]) context.dashboard_id = pathParts[idx + 1];
        }
        if (!context.dashboard_id) context.dashboard_id = _getQueryParam('dashboard_id');

        // 2. Detect Active Modal (Bootstrap)
        const activeModal = document.querySelector('.modal.show');
        if (activeModal) {
            // Attempt to find device info from the modal content
            const idInput = activeModal.querySelector('input[name="unique_id"], input[name="input_id"], input[name="output_id"], input[name="function_id"]');
            const nameInput = activeModal.querySelector('input.input-device-name, input[name="name"]');
            
            if (idInput) {
                context.active_modal = {
                    targetId: idInput.value,
                    name: nameInput ? nameInput.value : 'Unknown Device',
                    // Inference type from input name/form action
                    targetType: _inferTypeFromModal(activeModal)
                };
            }
        }

        // 3. Widget DOM Snapshot — extract visible data from dashboard widgets
        try {
            const widgets = document.querySelectorAll('.grid-stack-item');
            widgets.forEach(w => {
                // Title: AoT widgets standardize on .aot-w-title (21+ widget types)
                // and .widget-title-bar; the generic .widget-title etc. are kept
                // as fallbacks. CSS class selectors match whole tokens, so
                // .widget-title does NOT match class "widget-title-bar" — the
                // aot-w-title / widget-title-bar entries are what actually hit.
                const titleEl = w.querySelector('.aot-w-title, .widget-title-bar, .widget-title, .panel-title, .card-header, [data-widget-title]');
                if (!titleEl) return;

                const title = titleEl.textContent.trim();
                if (!title) return;

                const snap = { title: title, values: [] };

                // Collect displayed values. AoT widgets render live values into
                // .aot-w-value / .widget-measurement-value (populated by JS at
                // runtime); the generic classes below are fallbacks. data-ai-value
                // is the reliable opt-in any widget can add for AI visibility.
                const valueSelectors = [
                    '.aot-w-value',
                    '.widget-measurement-value',
                    '[data-ai-value]',
                    '.widget-value',
                    '.gauge-value',
                    '.measurement-value',
                    '.live-value',
                    '.current-value'
                ];
                
                valueSelectors.forEach(sel => {
                    w.querySelectorAll(sel).forEach(v => {
                        const txt = v.textContent.trim();
                        if (txt && txt !== '--' && txt !== 'N/A') {
                            // Try to include label if available
                            const label = v.getAttribute('data-ai-label') || 
                                         v.closest('[data-ai-label]')?.getAttribute('data-ai-label') || '';
                            snap.values.push(label ? `${label}: ${txt}` : txt);
                        }
                    });
                });

                // Only include if there's meaningful data
                if (snap.values.length > 0) {
                    context.widget_snapshots.push(snap);
                }
            });
        } catch(e) {
            // Silently fail — DOM scraping is best-effort
        }

        // 3.5 Map viewport — the site/zone the user is currently looking at on a
        // dashboard map widget. Lets a vague control command with no location
        // ("밸브 다 열어줘") be scoped to the on-screen location, so the AI can ask
        // "'1포장' '1-1'에 배치된 밸브를 열까요?". The backend resolves lat/lng → zone
        // by spatial containment. Reads the already-global map instance registry;
        // picks the first VISIBLE map.
        try {
            const insts = window.AoTWidgetInstances || {};
            for (const id in insts) {
                const m = insts[id] && insts[id].map;
                if (!m || typeof m.getCenter !== 'function') continue;
                let el = null;
                try { el = m.getContainer ? m.getContainer() : document.getElementById('aot-map-' + id); }
                catch (e) { el = null; }
                if (el && el.offsetParent === null) continue;  // hidden widget
                const c = m.getCenter();
                if (c && (c.lat !== undefined) && (c.lng !== undefined)) {
                    context.map_context = {
                        lat: c.lat, lng: c.lng,
                        zoom: (typeof m.getZoom === 'function') ? m.getZoom() : null
                    };
                    break;
                }
            }
        } catch (e) {
            // best-effort — no map on this page
        }

        // 4. Page semantic structure — heading / tabs / section titles. Gives the
        // AI a sense of WHAT THIS PAGE DOES (esp. non-dashboard pages like the AI
        // settings page), so "이 페이지에서 뭘 할 수 있어?" is answered from the
        // actual UI rather than a generic system description. Excludes the AI
        // drawer's own chrome.
        context.page_structure = _capturePageStructure();

        // 5. Multi-site scope — widgets tied to one facility (e.g. AoT_facility)
        // tag their container with data-ai-facility-id (see AoT_facility.py body
        // HTML). If this dashboard shows exactly one distinct facility, forward
        // it so server-side knowledge search / advice stays within that site.
        // A dashboard mixing more than one facility is ambiguous — omit rather
        // than guess wrong. See .local/plans/phase6_knowledge_digest_design.md
        // (multi-site addendum).
        try {
            const facilityIds = new Set();
            document.querySelectorAll('[data-ai-facility-id]').forEach(el => {
                const fid = el.getAttribute('data-ai-facility-id');
                if (fid) facilityIds.add(fid);
            });
            if (facilityIds.size === 1) {
                context.facility_id = facilityIds.values().next().value;
            }
        } catch(e) {
            // Silently fail — DOM scraping is best-effort
        }

        return context;
    }

    function _capturePageStructure() {
        const struct = { heading: '', tabs: [], sections: [] };
        try {
            const drawer = document.getElementById('ai-chat-drawer');
            const inDrawer = (el) => drawer && drawer.contains(el);

            // Main heading: first non-empty page heading outside the AI drawer.
            const headingEl = Array.from(document.querySelectorAll('.page-title, h1, h2, h3'))
                .find(el => !inDrawer(el) && el.textContent.trim());
            if (headingEl) struct.heading = headingEl.textContent.trim().replace(/\s+/g, ' ').slice(0, 80);

            // Tab labels (nav-tabs / nav-pills) — the page's main sections.
            document.querySelectorAll('.nav-tabs .nav-link, .nav-pills .nav-link').forEach(t => {
                if (inDrawer(t) || struct.tabs.length >= 12) return;
                const txt = t.textContent.trim().replace(/\s+/g, ' ');
                if (txt && !struct.tabs.includes(txt)) struct.tabs.push(txt);
            });

            // Section/card titles.
            document.querySelectorAll('.card-header, .card-title').forEach(s => {
                if (inDrawer(s) || struct.sections.length >= 12) return;
                const txt = s.textContent.trim().replace(/\s+/g, ' ');
                if (txt && txt.length <= 60 && !struct.sections.includes(txt)) struct.sections.push(txt);
            });
        } catch(e) {
            // best-effort
        }
        return struct;
    }

    function _inferTypeFromModal(modal) {
        const form = modal.querySelector('form');
        if (!form) return 'unknown';
        const action = form.getAttribute('action') || '';
        if (action.includes('input')) return 'input';
        if (action.includes('output')) return 'output';
        if (action.includes('function')) return 'function';
        if (action.includes('pid')) return 'pid';
        return 'device';
    }

    function _getQueryParam(name) {
        const urlParams = new URLSearchParams(window.location.search);
        return urlParams.get(name);
    }

    // --- Composer: mode toggles ---

    function _initModeToggles() {
        const applyActive = (groupId, value) => {
            const group = document.getElementById(groupId);
            if (!group) return;
            group.querySelectorAll('.ai-mode-seg').forEach(seg => {
                seg.classList.toggle('is-active', seg.dataset.value === value);
            });
        };
        applyActive('ai-depth-toggle', currentDepth);
        applyActive('ai-autonomy-toggle', currentAutonomy);

        document.querySelectorAll('.ai-mode-group').forEach(group => {
            group.addEventListener('click', (e) => {
                const seg = e.target.closest('.ai-mode-seg');
                if (!seg || !group.contains(seg)) return;
                const mode = group.dataset.mode;
                const value = seg.dataset.value;
                group.querySelectorAll('.ai-mode-seg').forEach(s => s.classList.toggle('is-active', s === seg));
                if (mode === 'depth') { currentDepth = value; localStorage.setItem('aot_ai_depth', value); }
                else if (mode === 'autonomy') { currentAutonomy = value; localStorage.setItem('aot_ai_autonomy', value); }
            });
        });
    }

    // --- Composer: image attachments ---

    function _handleFiles(fileList) {
        const files = Array.from(fileList || []).filter(f => /^image\/(png|jpe?g|webp|gif)$/i.test(f.type));
        for (const file of files) {
            if (attachments.length >= MAX_ATTACHMENTS) {
                alert(window._('You can attach up to %(n)s images.').replace('%(n)s', MAX_ATTACHMENTS));
                break;
            }
            _addAttachment(file);
        }
    }

    function _addAttachment(file) {
        const slot = { media_type: '', base64_data: '', dataUrl: '', bytes: 0 };
        attachments.push(slot);       // show a loading placeholder immediately
        _renderAttachments();
        _resizeImage(file, (result) => {
            const idx = attachments.indexOf(slot);
            if (!result || result.bytes > MAX_ATTACH_BYTES) {
                if (idx >= 0) attachments.splice(idx, 1);
                _renderAttachments();
                if (result && result.bytes > MAX_ATTACH_BYTES) alert(window._('Image is too large (max 5MB).'));
                return;
            }
            slot.media_type = result.media_type;
            slot.base64_data = result.base64_data;
            slot.dataUrl = result.dataUrl;
            slot.bytes = result.bytes;
            _renderAttachments();
        });
    }

    // Draw the image to a canvas capped at MAX_IMAGE_DIM and export compressed
    // base64. Strips the "data:...;base64," prefix so the provider gets raw base64.
    function _resizeImage(file, cb) {
        const reader = new FileReader();
        reader.onload = () => {
            const img = new Image();
            img.onload = () => {
                let width = img.naturalWidth || img.width;
                let height = img.naturalHeight || img.height;
                const scale = Math.min(1, MAX_IMAGE_DIM / Math.max(width, height));
                width = Math.max(1, Math.round(width * scale));
                height = Math.max(1, Math.round(height * scale));
                const canvas = document.createElement('canvas');
                canvas.width = width;
                canvas.height = height;
                const ctx = canvas.getContext('2d');
                ctx.drawImage(img, 0, 0, width, height);
                // PNG/GIF (transparency/flat art) → png; photos → jpeg for size.
                const outType = /png|gif/i.test(file.type) ? 'image/png' : 'image/jpeg';
                let dataUrl;
                try { dataUrl = canvas.toDataURL(outType, 0.85); }
                catch (e) { dataUrl = reader.result; }
                const comma = dataUrl.indexOf(',');
                const base64 = comma >= 0 ? dataUrl.slice(comma + 1) : dataUrl;
                const bytes = Math.round(base64.length * 3 / 4);
                cb({ media_type: outType, base64_data: base64, dataUrl: dataUrl, bytes: bytes });
            };
            img.onerror = () => cb(null);
            img.src = reader.result;
        };
        reader.onerror = () => cb(null);
        reader.readAsDataURL(file);
    }

    function _renderAttachments() {
        const box = document.getElementById('ai-attachments');
        if (!box) return;
        box.innerHTML = '';
        if (!attachments.length) { box.hidden = true; return; }
        box.hidden = false;
        attachments.forEach((a) => {
            const thumb = document.createElement('div');
            thumb.className = 'ai-attach-thumb' + (a.dataUrl ? '' : ' is-loading');
            if (a.dataUrl) {
                const im = document.createElement('img');
                im.src = a.dataUrl;
                im.alt = '';
                thumb.appendChild(im);
            } else {
                thumb.textContent = '…';
            }
            const rm = document.createElement('button');
            rm.className = 'ai-attach-remove';
            rm.type = 'button';
            rm.setAttribute('aria-label', window._('Remove'));
            rm.innerHTML = '&times;';
            rm.addEventListener('click', () => {
                const i = attachments.indexOf(a);
                if (i >= 0) attachments.splice(i, 1);
                _renderAttachments();
            });
            thumb.appendChild(rm);
            box.appendChild(thumb);
        });
    }

    function _clearAttachments() {
        attachments = [];
        _renderAttachments();
    }

    // --- Hide the bottom-center launcher while scrolling DOWN, reveal on scroll
    //     UP (direction-following). Slides straight down (see .ai-fab--tucked). ---

    function _bindScrollAutoHide(fab) {
        if (!fab) return;
        let lastY = window.scrollY || 0;
        let ticking = false;
        window.addEventListener('scroll', () => {
            if (ticking) return;
            ticking = true;
            requestAnimationFrame(() => {
                ticking = false;
                // While the chat is open the FAB is already hidden — keep it settled.
                if (isOpen) { lastY = window.scrollY || 0; return; }
                const y = window.scrollY || 0;
                if (y <= 60) {
                    fab.classList.remove('ai-fab--tucked');           // always show near the top
                } else if (y > lastY + 6) {
                    fab.classList.add('ai-fab--tucked');              // scrolling down → slide down out
                } else if (y < lastY - 6) {
                    fab.classList.remove('ai-fab--tucked');           // scrolling up → slide back up
                }
                lastY = y;
            });
        }, { passive: true });
    }

    // --- Public Methods ---

    return {
        init: _init,
        toggleChat: function() {
            isOpen ? this.closeChat() : this.openChat();
        },
        openChat: function(context = null) {
            const drawer = document.getElementById('ai-chat-drawer') || document.getElementById('aot-ai-drawer');
            const fab = document.getElementById('ai-fab') || document.getElementById('aot-ai-fab');
            if (!drawer) {
                console.error("AoT AI: Drawer element not found");
                return;
            }
            drawer.classList.add('active');
            if (fab) fab.classList.add('hidden');
            isOpen = true;

            // Always reveal the newest message when opening (the drawer may have
            // been rendered while hidden, leaving the scroll un-pinned).
            _scrollToBottom();

            // Side-by-side layout for desktop
            if (window.innerWidth > 480) {
                document.body.classList.add('ai-drawer-active');
                // [Fix] Trigger Global Resize after the body padding CSS transition
                // completes (0.4s), so Highcharts/gauge widgets reflow to their
                // final narrowed width instead of getting stuck mid-animation.
                setTimeout(() => window.dispatchEvent(new Event('resize')), 450);
            }

            if (context) {
                pageContext = { ..._capturePageContext(), ...context };
                pageContextExplicit = true;  // device/modal focus — keep it, don't auto-refresh
                const indicator = document.getElementById('ai-context-indicator');
                if (indicator) {
                    indicator.innerHTML = `<div class="ai-context-chip">Context: ${context.name || 'Device'} Setting</div>`;
                }

                // Automatically send the initial question. Callers may provide their
                // own opening message via context.autoMessage (e.g., the map widget's
                // AI-advisory modal); default remains the device-settings advice ask.
                const adviceMsg = context.autoMessage ||
                    `${window._('Please analyze the')} '${context.name}' (${context.targetType}) ${window._('device currently being configured and give me advice on its settings.')}`;
                _handleSend(adviceMsg, true); // silent send to avoid double user bubble if preferred, but let's make it visible so user knows what's happening
            } else {
                pageContext = null;
                pageContextExplicit = false;  // no explicit focus → auto-capture per send
                const indicator = document.getElementById('ai-context-indicator');
                if (indicator) indicator.innerHTML = '';
            }
        },
        closeChat: function() {
            const drawer = document.getElementById('ai-chat-drawer') || document.getElementById('aot-ai-drawer');
            const fab = document.getElementById('ai-fab') || document.getElementById('aot-ai-fab');
            if (drawer) drawer.classList.remove('active');
            if (fab) fab.classList.remove('hidden');
            isOpen = false;

            // [FIX] Always remove side-by-side layout class
            document.body.classList.remove('ai-drawer-active');

            // [FIX] Force remove any lingering padding from body (both desktop and mobile)
            document.body.style.paddingRight = '';

            // [MOBILE FIX] Remove modal-open class if it exists (Bootstrap leftover)
            document.body.classList.remove('modal-open');

            // [Fix] Trigger Global Resize after the body padding CSS transition
            // completes (0.4s), so Highcharts/gauge widgets reflow back to their
            // full width instead of staying stuck at the drawer-narrowed size.
            setTimeout(() => window.dispatchEvent(new Event('resize')), 450);
        },
        newConversation: function() {
            // Start a fresh thread: clear the cached thread id, wipe the messages
            // pane, and drop any pending attachments. Server history is untouched.
            threadId = null;
            localStorage.removeItem('aot_ai_thread_id');
            const container = document.getElementById('ai-chat-messages') || document.getElementById('ai-messages-container');
            if (container) container.innerHTML = '';
            _clearAttachments();
        }
    };
})();

// Auto-initialize on DOM load
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => AoT_AI.init());
} else {
    AoT_AI.init();
}

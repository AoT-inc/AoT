/**
 * Tab Management Functions
 * Provides functionality for creating, renaming, duplicating, and deleting tabs
 */

/**
 * Create a new tab for a page type
 * @param {string} pageType - Type of page ('input', 'output', 'function', 'dashboard')
 */
function createNewTab(pageType) {
    console.log('[createNewTab] Creating new tab for page type:', pageType);
    
    fetch('/tab/create', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCSRFToken()
        },
        body: JSON.stringify({ page_type: pageType })
    })
    .then(response => {
        console.log('[createNewTab] Response status:', response.status);
        return response.json();
    })
    .then(data => {
        console.log('[createNewTab] Response data:', data);
        if (data.success) {
            showToast('Tab created successfully', 'success');
            console.log('[createNewTab] Redirecting to:', data.redirect_url);
            window.location.href = data.redirect_url;
        } else {
            showToast(data.message || 'Failed to create tab', 'error');
        }
    })
    .catch(err => {
        console.error('[createNewTab] Create tab failed:', err);
        showToast('Failed to create tab', 'error');
    });
}

/**
 * Open tab settings modal
 * @param {string} tabId - Tab unique_id
 */
function openTabSettings(tabId, tabName, itemLength) {
    // Fallback: derive from DOM if args not supplied (templates use data-id)
    if (tabName === undefined || tabName === null) {
        const tabElement = document.querySelector(`[data-id="${tabId}"]`);
        tabName = tabElement ? tabElement.textContent.trim() : '';
    }

    // Set modal values
    document.getElementById('tab-settings-tab-id').value = tabId;
    document.getElementById('tab-settings-name').value = tabName;

    // Get page description (you may want to pass this from the template)
    const pageDescriptions = {
        'input': 'Input devices collect data from sensors and external sources.',
        'output': 'Output devices control physical hardware like relays, motors, and valves.',
        'function': 'Functions automate tasks and control system behavior.',
        'dashboard': 'Dashboards display real-time data and system status.'
    };

    // Get page type from current URL
    const path = window.location.pathname;
    let pageType = 'dashboard';
    if (path.includes('/input')) pageType = 'input';
    else if (path.includes('/output')) pageType = 'output';
    else if (path.includes('/function')) pageType = 'function';

    document.getElementById('tab-settings-description').textContent =
        pageDescriptions[pageType] || '';

    // Check if this is the last tab (disable delete button)
    const tabCount = (typeof itemLength === 'number' && itemLength > 0)
        ? itemLength
        : document.querySelectorAll('[data-id]').length;
    const deleteBtn = document.getElementById('delete-tab-btn');
    if (deleteBtn) {
        deleteBtn.disabled = tabCount <= 1;
        if (tabCount <= 1) {
            deleteBtn.title = 'Cannot delete the last tab';
        } else {
            deleteBtn.title = '';
        }
    }

    // Show modal (Bootstrap 4 / jQuery API)
    if (document.getElementById('tabSettingsModal')) {
        $('#tabSettingsModal').modal('show');
    }
}

/**
 * Rename a tab
 */
function renameTab() {
    const tabId = document.getElementById('tab-settings-tab-id').value;
    const newName = document.getElementById('tab-settings-name').value.trim();

    if (!newName) {
        showToast('Tab name cannot be empty', 'error');
        return;
    }

    fetch('/tab/rename', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCSRFToken()
        },
        body: JSON.stringify({
            tab_id: tabId,
            name: newName
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showToast('Tab renamed successfully', 'success');
            // Close modal (Bootstrap 4 / jQuery API)
            $('#tabSettingsModal').modal('hide');
            // Reload page to show new name
            setTimeout(() => location.reload(), 500);
        } else {
            showToast(data.message || 'Failed to rename tab', 'error');
        }
    })
    .catch(err => {
        console.error('Rename tab failed:', err);
        showToast('Failed to rename tab', 'error');
    });
}

/**
 * Duplicate a tab and all its entries
 */
function duplicateTab() {
    const tabId = document.getElementById('tab-settings-tab-id').value;

    if (!confirm('Duplicate this tab and all its entries? Duplicated entries will be set to inactive.')) {
        return;
    }

    fetch('/tab/duplicate', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCSRFToken()
        },
        body: JSON.stringify({ tab_id: tabId })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showToast('Tab duplicated successfully', 'success');
            // Redirect to new tab
            window.location.href = data.redirect_url;
        } else {
            showToast(data.message || 'Failed to duplicate tab', 'error');
        }
    })
    .catch(err => {
        console.error('Duplicate tab failed:', err);
        showToast('Failed to duplicate tab', 'error');
    });
}

/**
 * Delete a tab
 */
function deleteTab() {
    const tabId = document.getElementById('tab-settings-tab-id').value;

    if (!confirm('Delete this tab and all its entries? This cannot be undone.')) {
        return;
    }

    fetch(`/tab/${tabId}`, {
        method: 'DELETE',
        headers: {
            'X-CSRFToken': getCSRFToken()
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showToast('Tab deleted successfully', 'success');
            // Redirect to another tab
            if (data.redirect_url) {
                window.location.href = data.redirect_url;
            } else {
                location.reload();
            }
        } else {
            showToast(data.message || 'Failed to delete tab', 'error');
        }
    })
    .catch(err => {
        console.error('Delete tab failed:', err);
        showToast('Failed to delete tab', 'error');
    });
}

/**
 * Get CSRF token from meta tag or form input
 * @returns {string} CSRF token
 */
function getCSRFToken() {
    // Try meta tag first
    const metaTag = document.querySelector('meta[name="csrf-token"]');
    if (metaTag) {
        return metaTag.getAttribute('content');
    }

    // Try form input
    const inputTag = document.querySelector('input[name="csrf_token"]');
    if (inputTag) {
        return inputTag.value;
    }

    // Fallback to empty string
    console.warn('CSRF token not found');
    return '';
}

/**
 * Show toast notification
 * @param {string} message - Message to display
 * @param {string} type - Type of message ('success', 'error', 'info', 'warning')
 */
function showToast(message, type) {
    // Delegate to window.showToast if available (respects AoTGlobalSettings hide flags)
    if (typeof window.showToast === 'function' && window.showToast !== showToast) {
        window.showToast(message, type);
        return;
    }

    // Fallback: respect AoTGlobalSettings directly
    const settings = window.AoTGlobalSettings || {};
    if (type === 'success' && settings.hide_success) return;
    if (type === 'info' && settings.hide_info) return;
    if ((type === 'warning' || type === 'error') && settings.hide_warning) return;

    if (typeof toastr !== 'undefined') {
        toastr.options = {
            "closeButton": true,
            "debug": false,
            "newestOnTop": true,
            "progressBar": true,
            "positionClass": "toast-top-right",
            "preventDuplicates": false,
            "onclick": null,
            "showDuration": "300",
            "hideDuration": "1000",
            "timeOut": "5000",
            "extendedTimeOut": "1000",
            "showEasing": "swing",
            "hideEasing": "linear",
            "showMethod": "fadeIn",
            "hideMethod": "fadeOut"
        };

        switch(type) {
            case 'success':
                toastr.success(message);
                break;
            case 'error':
                toastr.error(message);
                break;
            case 'warning':
                toastr.warning(message);
                break;
            case 'info':
                toastr.info(message);
                break;
            default:
                toastr.info(message);
        }
    } else {
        console.log(`[${type.toUpperCase()}] ${message}`);
    }
}

/**
 * API Key Manager - Intelligent Matching & Injection
 * 
 * This script handles auto-detection of API key fields on settings pages,
 * fetches available keys from the manager, matches them intelligently,
 * and provides a selection UI.
 */

(function($) {
    'use strict';

    const API_KEYS_ENDPOINT = '/api/api_keys';
    let availableKeys = [];

    // Initialize
    async function init() {
        console.log("API Key Manager: Initializing...");
        try {
            const response = await fetch(API_KEYS_ENDPOINT);
            availableKeys = await response.json();
            console.log(`API Key Manager: Found ${availableKeys.length} keys in manager.`);
            
            // Always scan to show UI presence even if no keys yet
            scanForFields();
        } catch (error) {
            console.error("API Key Manager: Failed to fetch API keys.", error);
        }
    }

    // Scan for fields that likely require an API key or Token
    function scanForFields() {
        // Look for inputs with keywords in name/id, but skip the manager page itself
        if (window.location.pathname.includes('/settings/api_key')) return;

        const authKeywords = ['api_key', 'token', 'secret', 'access_key', 'auth_key', 'client_id', 'client_secret'];
        
        $('input[type="text"], input[type="password"], textarea').each(function() {
            const $input = $(this);
            if ($input.data('api-key-managed')) return;

            const id = ($input.attr('id') || '').toLowerCase();
            const name = ($input.attr('name') || '').toLowerCase();
            const placeholder = ($input.attr('placeholder') || '').toLowerCase();

            const isAuthField = authKeywords.some(kw => 
                id.includes(kw) || name.includes(kw) || placeholder.includes(kw)
            );

            if (isAuthField) {
                console.log(`API Key Manager: Matched field - id: ${id}, name: ${name}`);
                attachManagerUI($input);
            }
        });
    }

    // Attach "Select from Manager" UI to a field
    function attachManagerUI($input) {
        if ($input.data('api-key-managed')) return;
        $input.data('api-key-managed', true);

        // Create container and button
        const $wrapper = $('<div class="api-key-input-wrapper" style="position:relative; display: flex; align-items: center;"></div>');
        $input.wrap($wrapper);
        
        const $btn = $('<button type="button" class="btn btn-sm btn-outline-secondary" title="Select from API Key Manager" style="margin-left: 5px; height: 32px; padding: 0 8px;">' +
                       '<i class="fas fa-key"></i></button>');
        
        $input.after($btn);

        // Intelligent Matching logic for this field
        const matches = getIntelligentMatches($input);
        
        // If high confidence match exists and field is empty, auto-inject or suggest
        if (matches.length > 0 && !$input.val()) {
            // Priority 1: Exact provider match
            const bestMatch = matches[0];
            if (bestMatch.score >= 100) {
                $input.val(bestMatch.key.key);
                $input.trigger('change');
                showInjectionNotice($input, bestMatch.key.name);
            }
        }

        // Show selection menu on click
        $btn.on('click', function(e) {
            e.preventDefault();
            showSelectionMenu($input, $btn, matches);
        });
    }

    // Intelligent Matching Logic
    function getIntelligentMatches($input) {
        const results = [];
        const id = ($input.attr('id') || '').toLowerCase();
        const name = ($input.attr('name') || '').toLowerCase();
        
        // Try to determine the provider from the context (e.g., input device name)
        // In AoT, often it's prefix of the ID or found in a nearby hidden field
        let contextProvider = '';
        const $form = $input.closest('form');
        
        // Common AoT pattern: device/output type is in a hidden field or page title
        contextProvider = $form.find('input[name="device"], input[name="output_type"], input[name="action_type"]').val() || '';
        if (!contextProvider) {
            // Fallback: search page title or breadcrumbs
            contextProvider = $('.sidebar-heading').text() || '';
        }

        availableKeys.forEach(key => {
            let score = 0;
            const keyProvider = (key.provider || '').toLowerCase();
            const keyName = (key.name || '').toLowerCase();
            const keyTags = (key.tag || '').toLowerCase();
            const keyDesc = (key.description || '').toLowerCase();

            // Match Priority 1: Provider Match
            if (contextProvider && keyProvider && contextProvider.toLowerCase().includes(keyProvider)) {
                score += 100;
            }

            // Match Priority 2: Keyword Match
            const keywords = [contextProvider, id, name].join(' ').toLowerCase();
            if (keywords) {
                if (keyName && keywords.includes(keyName)) score += 50;
                if (keyTags && keyTags.split(',').some(t => keywords.includes(t.trim().toLowerCase()))) score += 40;
                if (keyProvider && keywords.includes(keyProvider)) score += 30;
                if (keyDesc && keywords.split(' ').some(w => w.length > 3 && keyDesc.includes(w))) score += 10;
            }

            if (score > 0) {
                results.push({ key, score });
            } else if (availableKeys.length < 20) {
                 // Include all if few keys, with score 0
                 results.push({ key, score: 0 });
            }
        });

        return results.sort((a, b) => b.score - a.score);
    }

    function showSelectionMenu($input, $btn, matches) {
        // Remove existing menus
        $('.api-key-selection-menu').remove();

        const $menu = $('<div class="api-key-selection-menu list-group" style="position:absolute; z-index:9999; width: 250px; box-shadow: 0 4px 8px rgba(0,0,0,0.2); border: 1px solid #ccc; max-height: 300px; overflow-y: auto; background: white;"></div>');
        
        if (matches.length === 0 && availableKeys.length === 0) {
            $menu.append('<div class="list-group-item disabled">No keys found in manager</div>');
        } else {
            const keysToShow = matches.length > 0 ? matches : availableKeys.map(k => ({key: k, score: 0}));
            
            keysToShow.forEach(m => {
                const $item = $('<a href="#" class="list-group-item list-group-item-action d-flex justify-content-between align-items-center" style="padding: 8px 12px; font-size: 0.9em;">' +
                                '<div><strong>' + m.key.name + '</strong><br/><small class="text-muted">' + (m.key.provider || 'Generic') + '</small></div>' +
                                (m.score >= 100 ? '<span class="badge badge-success">Match</span>' : '') +
                                '</a>');
                
                $item.on('click', function(e) {
                    e.preventDefault();
                    $input.val(m.key.key);
                    $input.trigger('change');
                    $menu.remove();
                    if (typeof window.showToast !== 'undefined') {
                        window.showToast(`Injected: ${m.key.name}`, 'success');
                    } else if (typeof toastr !== 'undefined') {
                        toastr['success'](`Injected: ${m.key.name}`);
                    }
                });
                $menu.append($item);
            });
        }

        $('body').append($menu);
        
        // Position menu near button
        const offset = $btn.offset();
        $menu.css({
            top: offset.top + $btn.outerHeight(),
            left: offset.left - $menu.outerWidth() + $btn.outerWidth()
        });

        // Close on outside click
        $(document).on('mousedown.api-key-menu', function(e) {
            if (!$(e.target).closest('.api-key-selection-menu, ' + $btn.selector).length) {
                $menu.remove();
                $(document).off('mousedown.api-key-menu');
            }
        });
    }

    function showInjectionNotice($input, name) {
        // Subtle hint that we auto-filled
        $input.css('border-color', '#28a745');
        setTimeout(() => {
            $input.css('border-color', '');
        }, 2000);
        console.log(`API Key Inspector: Auto-injected match "${name}"`);
    }

    // Run on document ready
    $(function() {
        init();
        
        // Watch for dynamic content (e.g., adding rows, opening modals)
        const observer = new MutationObserver(function(mutations) {
            // Use a small debounce to avoid excessive scanning during heavy DOM changes
            if (this.scanTimeout) clearTimeout(this.scanTimeout);
            this.scanTimeout = setTimeout(() => {
                scanForFields();
            }, 100);
        });
        
        console.log("API Key Manager: Starting MutationObserver on document.body");
        observer.observe(document.body, { childList: true, subtree: true });
    });

})(jQuery);

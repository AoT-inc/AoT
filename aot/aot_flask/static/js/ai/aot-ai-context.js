/**
 * AoT AI Context Manager Module
 * Handles AJAX form submission and DOM updates for the context injection UI.
 */
const AoTAIContext = {

    /**
     * Submit a context action (add, confirm, reject, delete, mod).
     * @param {HTMLElement} button - The clicked button element
     * @param {string} action - Action type: record_add, record_confirm, record_reject, record_delete, record_mod
     * @param {number|null} recordId - Record ID (null for add action)
     */
    submitContextAction: function (button, action, recordId) {
        let formData;
        let $form;

        if (action === 'record_add') {
            $form = $('#context_add_form');
        } else if (recordId) {
            $form = $('#form_record_' + recordId);
        } else {
            $form = $(button).closest('form');
        }

        if (!$form.length) {
            if (window.showToast) window.showToast('Error: form not found', 'error');
            return false;
        }

        // Get CSRF token
        var csrfToken = $form.find('input[name="csrf_token"]').val();
        if (!csrfToken) {
            csrfToken = $('meta[name="csrf-token"]').attr('content');
        }

        $.ajax({
            type: "POST",
            url: '/ai/context/submit',
            headers: {"X-CSRFToken": csrfToken},
            data: $form.serialize() + '&' + action + '=1',
            success: function (data) {
                var msgs = data.data.messages;

                // Display messages using existing AoT toast pattern
                if (msgs.error && msgs.error.length) {
                    if (window.showToast) window.showToast('Error: ' + msgs.error.join(", "), 'error');
                }
                if (msgs.warning && msgs.warning.length) {
                    if (window.showToast) window.showToast(msgs.warning.join(", "), 'warning');
                }
                if (msgs.success && msgs.success.length) {
                    if (window.showToast) window.showToast(msgs.success.join(", "), 'success');
                }
                if (msgs.info && msgs.info.length) {
                    if (window.showToast) window.showToast(msgs.info.join(", "), 'info');
                }

                var actionType = data.data.action;
                var targetId = data.data.record_id;

                // DOM updates based on action
                if (actionType === 'record_add') {
                    // Reload to show new record
                    location.reload();

                } else if (actionType === 'record_confirm' || actionType === 'record_mod') {
                    // Update badge to confirmed (green)
                    var $badge = $('#badge_' + targetId);
                    $badge.removeClass('badge-system_generated badge-pending')
                          .addClass('badge-user_confirmed')
                          .text(window._('Confirmed'));
                    // Hide confirm/reject buttons
                    var $card = $('#record_card_' + targetId);
                    $card.find('.btn-success, .btn-warning').hide();

                } else if (actionType === 'record_reject') {
                    // Update badge to pending (yellow)
                    var $badge = $('#badge_' + targetId);
                    $badge.removeClass('badge-system_generated badge-user_confirmed')
                          .addClass('badge-pending')
                          .text(window._('Review needed'));

                } else if (actionType === 'record_delete') {
                    // Remove the record card from DOM
                    $('#record_card_' + targetId).fadeOut(300, function () {
                        $(this).remove();
                    });
                }
            },
            error: function (xhr) {
                if (window.showToast) window.showToast('Server Error: ' + xhr.statusText, 'error');
            }
        });

        return false;
    },

    /**
     * Update the raw_input label/placeholder based on source_type selection.
     * @param {string} sourceType - Selected source type value
     */
    updateSourceTypeLabel: function (sourceType) {
        var $label = $('#raw_input_label');
        var $input = $('#raw_input');

        if (sourceType === 'manual') {
            $label.text(window._('Enter value'));
            $input.attr('placeholder', window._('e.g. 25.5'));
        } else if (sourceType === 'free_text') {
            $label.text(window._('Note/Description'));
            $input.attr('placeholder', window._('e.g. setpoint based on morning temperature'));
        } else if (sourceType === 'url') {
            $label.text(window._('External URL'));
            $input.attr('placeholder', window._('e.g. https://api.weather.kr/...'));
        }
    },

    /**
     * Initialize event bindings on DOMContentLoaded.
     */
    init: function () {
        var self = this;

        // Bind source_type dropdown change
        $('#source_type').on('change', function () {
            self.updateSourceTypeLabel($(this).val());
        });

        // Set initial label
        var initialType = $('#source_type').val();
        if (initialType) {
            self.updateSourceTypeLabel(initialType);
        }
    }
};

// Auto-initialize on DOM ready
$(document).ready(function () {
    AoTAIContext.init();
});

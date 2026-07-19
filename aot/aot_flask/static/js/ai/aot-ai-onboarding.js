/**
 * AoT Onboarding Flow — Multi-step wizard controller
 * Namespace: AoT_Onboarding
 * Dependencies: none (vanilla JS)
 */
var AoT_Onboarding = (function() {
    'use strict';

    var facilityId = null;
    var currentStep = 1;
    var totalSteps = 4;

    /**
     * Initialize onboarding flow for a facility.
     * Checks backend status and shows the appropriate step.
     * @param {string|number} fId - Facility ID
     */
    function init(fId) {
        facilityId = fId;
        if (!facilityId) return;

        var container = document.getElementById('ai-onboarding-flow');
        if (!container) return;

        // Bind param chip click handlers
        var chips = document.querySelectorAll('.ob-param-chip');
        chips.forEach(function(chip) {
            chip.addEventListener('click', function() {
                this.classList.toggle('selected');
            });
        });

        // Check current onboarding status
        fetch('/ai/facility/' + facilityId + '/onboard/status')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.status === 'completed') {
                    // Already completed — don't show onboarding
                    container.style.display = 'none';
                    return;
                }
                if (data.status === 'contract_acknowledged') {
                    // Jump to completion step
                    goToStep(4);
                    container.style.display = 'block';
                    return;
                }
                if (data.status === 'not_started') {
                    // Start onboarding session on backend
                    fetch('/ai/facility/' + facilityId + '/onboard/start', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': _getCSRF()
                        }
                    });
                }
                goToStep(1);
                container.style.display = 'block';
            })
            .catch(function(err) {
                console.error('Onboarding status check failed:', err);
            });
    }

    /**
     * Navigate to a specific step.
     * @param {number} step - Step number (1-4)
     */
    function goToStep(step) {
        currentStep = step;
        var steps = document.querySelectorAll('.ob-step');
        steps.forEach(function(s) {
            s.classList.remove('active');
        });
        var target = document.querySelector('.ob-step[data-ob-step="' + step + '"]');
        if (target) target.classList.add('active');

        // Update progress dots
        var dots = document.querySelectorAll('.ob-dot');
        dots.forEach(function(d) {
            var dotStep = parseInt(d.getAttribute('data-dot'));
            d.classList.toggle('active', dotStep <= step);
        });
    }

    /**
     * Advance to the next step with validation.
     */
    function nextStep() {
        if (currentStep === 2) {
            // Validate questionnaire before proceeding
            var facilityType = document.getElementById('ob-facility-type');
            if (facilityType && !facilityType.value) {
                _showError('Please select a facility type.');
                return;
            }
            var experience = document.getElementById('ob-experience');
            if (experience && !experience.value) {
                _showError('Please select your operating experience.');
                return;
            }
        }
        _hideError();
        if (currentStep < totalSteps) {
            goToStep(currentStep + 1);
        }
    }

    /**
     * Go back to the previous step.
     */
    function prevStep() {
        _hideError();
        if (currentStep > 1) {
            goToStep(currentStep - 1);
        }
    }

    /**
     * Submit questionnaire and contract acknowledgement to backend.
     */
    function submitQuestionnaire() {
        var checkbox = document.getElementById('ob-agree-checkbox');
        if (!checkbox || !checkbox.checked) {
            _showError('You must agree to the terms before proceeding.');
            return;
        }

        var facilityType = document.getElementById('ob-facility-type').value;
        var experience = document.getElementById('ob-experience').value;
        var params = [];
        document.querySelectorAll('.ob-param-chip.selected').forEach(function(chip) {
            params.push(chip.getAttribute('data-param'));
        });

        var body = {
            questionnaire: {
                facility_type: facilityType,
                operator_experience: experience,
                critical_parameters: params
            }
        };

        fetch('/ai/facility/' + facilityId + '/onboard/acknowledge', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': _getCSRF()
            },
            body: JSON.stringify(body)
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.status === 'success' || data.status === 'acknowledged') {
                goToStep(4);
            } else {
                _showError(data.message || data.error || 'An error occurred. Please try again.');
            }
        })
        .catch(function(err) {
            console.error('Onboarding acknowledge failed:', err);
            _showError('Connection error. Please try again.');
        });
    }

    /**
     * Complete onboarding — hide flow and hand off to learning dashboard.
     */
    function complete() {
        var container = document.getElementById('ai-onboarding-flow');
        if (container) container.style.display = 'none';
        // Trigger learning dashboard if available
        if (typeof AoT_LearningDashboard !== 'undefined') {
            AoT_LearningDashboard.init(facilityId);
        }
    }

    // -- Private helpers --

    function _getCSRF() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute('content') : '';
    }

    function _showError(msg) {
        var el = document.getElementById('ob-error-msg');
        if (el) {
            el.textContent = msg;
            el.style.display = 'block';
        }
    }

    function _hideError() {
        var el = document.getElementById('ob-error-msg');
        if (el) el.style.display = 'none';
    }

    // Public API
    return {
        init: init,
        nextStep: nextStep,
        prevStep: prevStep,
        submitQuestionnaire: submitQuestionnaire,
        complete: complete
    };
})();

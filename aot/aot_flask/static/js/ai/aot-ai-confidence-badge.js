var AoT_ConfidenceBadge = (function() {
    'use strict';

    var BADGE_CONFIG = {
        HIGH:   { cls: 'cb-high',   icon: '✓', label: 'High Confidence' },
        MEDIUM: { cls: 'cb-medium', icon: '~', label: 'Medium Confidence' },
        LOW:    { cls: 'cb-low',    icon: '!', label: 'Low Confidence' }
    };

    function create(confidenceLevel, reasoningTrace) {
        var config = BADGE_CONFIG[(confidenceLevel || '').toUpperCase()] || BADGE_CONFIG.LOW;
        var trace = reasoningTrace || {};

        var wrapper = document.createElement('div');
        wrapper.className = 'cb-wrapper';

        // Badge
        var badge = document.createElement('span');
        badge.className = 'cb-badge ' + config.cls;
        badge.textContent = config.icon + ' ' + config.label;
        badge.addEventListener('click', function(e) {
            e.stopPropagation();
            var detail = wrapper.querySelector('.cb-detail');
            if (detail) {
                detail.style.display = detail.style.display === 'none' ? 'block' : 'none';
            }
        });
        wrapper.appendChild(badge);

        // Detail panel
        var detail = document.createElement('div');
        detail.className = 'cb-detail';
        detail.style.display = 'none';

        // Reasoning
        if (trace.confidence_reasoning) {
            var reasoning = document.createElement('p');
            reasoning.className = 'cb-reasoning';
            reasoning.textContent = trace.confidence_reasoning;
            detail.appendChild(reasoning);
        }

        // Sources
        if (trace.based_on && trace.based_on.length > 0) {
            var sourcesList = document.createElement('ul');
            sourcesList.className = 'cb-sources';
            trace.based_on.forEach(function(src) {
                var li = document.createElement('li');
                li.textContent = (src.source || 'unknown') + ' (' + (src.state || 'unknown') + ', ' + (src.confidence || 'unknown') + ')';
                sourcesList.appendChild(li);
            });
            detail.appendChild(sourcesList);
        }

        // Would increase if
        if (trace.confidence_would_increase_if) {
            var improve = document.createElement('p');
            improve.className = 'cb-improve';
            improve.textContent = trace.confidence_would_increase_if;
            detail.appendChild(improve);
        }

        wrapper.appendChild(detail);
        return wrapper;
    }

    function createFromAction(actionDict) {
        if (!actionDict || !actionDict.reasoning_trace) {
            return null;
        }
        var trace = actionDict.reasoning_trace;
        var level = trace.confidence_overall || 'LOW';
        return create(level, trace);
    }

    return {
        create: create,
        createFromAction: createFromAction
    };
})();

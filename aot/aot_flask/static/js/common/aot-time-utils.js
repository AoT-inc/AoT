/**
 * AoT Time Utilities (aot-time-utils.js)
 * Provides server-synchronized time and flexible duration formatting/parsing.
 * Supports: ss, mm:ss, hh:mm:ss
 */
(function (window) {
    'use strict';

    const AoTTime = {
        serverOffsetMs: 0,

        /**
         * Update the server-client time offset based on response headers.
         */
        sync: function (dateHeader) {
            if (!dateHeader) return;
            try {
                const srvMs = Date.parse(dateHeader);
                if (!isNaN(srvMs)) {
                    const off = srvMs - Date.now();
                    if (Math.abs(off) <= 120000) {
                        this.serverOffsetMs = off;
                    }
                }
            } catch (e) {
                console.warn('[AoTTime] Sync failed', e);
            }
        },

        /**
         * Get current Server Time (estimated).
         */
        now: function () {
            return Date.now() + this.serverOffsetMs;
        },

        /**
         * Format total seconds into HH:MM:SS
         */
        formatDuration: function (totalSeconds) {
            if (totalSeconds < 0 || isNaN(totalSeconds)) totalSeconds = 0;
            const h = Math.floor(totalSeconds / 3600);
            const m = Math.floor((totalSeconds % 3600) / 60);
            const s = Math.floor(totalSeconds % 60);
            const pad = (n) => (n < 10 ? '0' + n : n);
            return `${pad(h)}:${pad(m)}:${pad(s)}`;
        },

        /**
         * Flexible Parsing: ss, mm:ss, hh:mm:ss -> totalSeconds
         */
        parseFlexible: function (input) {
            if (input === null || input === undefined) return 0;
            let s_val = String(input).trim();
            if (!s_val) return 0;

            // Remove non-numeric/colon characters
            s_val = s_val.replace(/[^0-9:.]/g, '');
            const parts = s_val.split(':');
            let total = 0;

            try {
                if (parts.length === 1) {
                    // Pure seconds
                    total = Math.floor(parseFloat(parts[0]) || 0);
                } else if (parts.length === 2) {
                    // MM:SS
                    const m = Math.floor(parseFloat(parts[0]) || 0);
                    const s = Math.floor(parseFloat(parts[1]) || 0);
                    total = m * 60 + s;
                } else if (parts.length >= 3) {
                    // HH:MM:SS
                    const h = Math.floor(parseFloat(parts[0]) || 0);
                    const m = Math.floor(parseFloat(parts[1]) || 0);
                    const s = Math.floor(parseFloat(parts[2]) || 0);
                    total = h * 3600 + m * 60 + s;
                }
            } catch (e) {
                console.warn('[AoTTime] Parse failed for: ' + input, e);
                return 0;
            }
            return total;
        },

        /**
         * Auto-attach blur listener to inputs
         */
        attachToInput: function (element) {
            const self = this;
            if (!element) return;

            // Avoid duplicate attachment
            if (element.dataset.aotTimeAttached) return;
            element.dataset.aotTimeAttached = "true";

            element.addEventListener('blur', function () {
                const val = element.value;
                if (!val) return;

                const totalSeconds = self.parseFlexible(val);
                const formatted = self.formatDuration(totalSeconds);

                // If it's a 'time' type input, it might need HH:mm or HH:mm:ss
                if (element.type === 'time') {
                    // Standard time input usually accepts HH:mm or HH:mm:ss
                    // If we have seconds, HH:mm:ss is best.
                    element.value = formatted;
                } else {
                    element.value = formatted;
                }

                // Trigger change event just in case
                element.dispatchEvent(new Event('change', { bubbles: true }));
            });

            // Optional: suggest numeric keyboard on mobile
            if (element.type === 'text' && !element.getAttribute('inputmode')) {
                element.setAttribute('inputmode', 'numeric');
            }
        },

        /**
         * Scan page and attach to relevant inputs
         */
        autoAttach: function () {
            const self = this;
            // 1. Explicit class
            document.querySelectorAll('.aot-time-input').forEach(el => self.attachToInput(el));

            // 2. Heuristic search (inputs with seconds/duration/period in labels/placeholders)
            // This is broader but helps "immediate response" without changing every template
            const keywords = ['sec', 'period', 'duration', 'delay', 'HH:MM'];
            document.querySelectorAll('input[type="text"], input[type="number"]').forEach(el => {
                const placeholder = (el.placeholder || "").toLowerCase();
                const name = (el.name || "").toLowerCase();
                const id = (el.id || "").toLowerCase();

                const matches = keywords.some(k =>
                    placeholder.includes(k.toLowerCase()) ||
                    name.includes(k.toLowerCase()) ||
                    id.includes(k.toLowerCase())
                );

                if (matches) {
                    self.attachToInput(el);
                }
            });
        }
    };

    window.AoTTime = AoTTime;

    // Auto-init on DOMContentLoaded
    document.addEventListener('DOMContentLoaded', function () {
        AoTTime.autoAttach();
    });

})(window);

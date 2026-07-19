/**
 * aot-stopwatch-manager.js
 * Centralized runtime (stopwatch) management system
 */

(function() {
    // console.log("[AoT Runtime] Stopwatch Manager Initializing...");

    const registry = {}; // { "deviceId::channel": { startMs, elements: Set, isActive } }
    let globalTimer = null;

    /**
     * HH:MM:SS format conversion routine
     */
    function formatDuration(ms) {
        if (ms < 0) return "---";
        let totalSec = Math.floor(ms / 1000);
        let h = Math.floor(totalSec / 3600);
        let m = Math.floor((totalSec % 3600) / 60);
        let s = totalSec % 60;
        return [h, m, s].map(v => v.toString().padStart(2, '0')).join(':');
    }

    /**
     * Current time including server-time correction (AoT_map compatible)
     */
    function getNowMs() {
        // If window.tm_nowServerMs exists and is a function outside this closure, call it
        if (typeof window.tm_nowServerMs === 'function' && window.tm_nowServerMs !== getNowMs) {
            try {
                return window.tm_nowServerMs();
            } catch (e) {
                return Date.now();
            }
        }
        return Date.now();
    }

    const Manager = {
        /**
         * Register a stopwatch
         * @param {string} deviceId "unique_id"
         * @param {number|string} channel
         * @param {boolean} isActive whether the device is active
         * @param {number|null} initialStartEpoch Epoch in seconds (Optional)
         * @param {HTMLElement} element DOM element to update
         * @param {number} syncThresholdMs (Optional) sync tolerance (default 7000)
         * @param {boolean} isUserAction (Optional) explicit user action (True: allow forced state change, False: keep existing state if Active)
         */
        register: function(deviceId, channel, isActive, initialStartEpoch, element, syncThresholdMs, isUserAction) {
            const key = `${deviceId}::${channel}`;
            // Default threshold: 7000ms if not provided
            const threshold = syncThresholdMs || 7000;
            
            if (!registry[key]) {
                let cleanId = deviceId;
                let cleanChannel = channel;
                if (typeof deviceId === 'string' && deviceId.indexOf('::') !== -1) {
                    const parts = deviceId.split('::');
                    cleanId = parts[0];
                    if (!channel || channel === 0 || channel === '0') cleanChannel = parts[1];
                }

                // If startEpoch is supplied use it; otherwise keep startMs=null until
                // the first sync() returns a real value from the server.
                // Do NOT fall back to Date.now() — that produces a misleading "00:00:XX"
                // for devices that have been running for hours.
                const initStartMs = initialStartEpoch ? initialStartEpoch * 1000 : null;

                registry[key] = {
                    deviceId: cleanId,
                    channel: cleanChannel,
                    startMs: initStartMs,
                    elements: new Set(),
                    isActive: !!isActive,
                    lastSync: 0,
                    forceOffUntil: 0,
                    syncThreshold: threshold,
                    localFallback: false
                };
                if (isActive) this.sync(key);
            } else {
                const entry = registry[key];
                
                // Update threshold if provided
                // [Fix] Use dynamic threshold (User Setting or 2s default) for force-off buffer
                const offBuffer = entry.syncThreshold ? (entry.syncThreshold / 2) : 2000;
                
                // [Fix] If trying to set Inactive (FALSE)
                if (!isActive) {
                    if (entry.isActive) {
                        // Conflict: Currently Active, but Registering as Inactive.
                        if (isUserAction) {
                            // User clicked STOP. Honor it.
                            entry.isActive = false;
                            entry.forceOffUntil = Date.now() + offBuffer;
                        } else {
                            // System/UI Event (e.g. popup open with stale state).
                            
                            // [Fix] Ghost Timer Prevention
                            // If the timer is "Young" (< 10s), this OFF signal might be a stale poll from right before start. Ignore it.
                            // If the timer is "Old" (> 10s), this OFF signal is likely real (we missed the stop event, or it stopped remotely). Trust it.
                            const runDuration = Date.now() - (entry.startMs || 0);
                            const safetyWindow = entry.syncThreshold ? (entry.syncThreshold + 3000) : 10000;

                            if (runDuration < safetyWindow) {
                                // Ignore stale inactive state
                            } else {
                                entry.isActive = false;
                                if (element) {
                                     if (element.tagName === 'INPUT') element.value = "00:00:00";
                                     else element.textContent = "00:00:00";
                                }
                            }
                        }
                    } else {
                        // Already inactive. Just ensure it stays inactive.
                        entry.isActive = false;
                        if (element) {
                             if (element.tagName === 'INPUT') element.value = "00:00:00";
                             else element.textContent = "00:00:00";
                        }
                    }
                } else {
                    // Trying to set Active (TRUE)
                    // (Logic for zombie prevention matches previous flow)
                    // [Fix] If trying to set ACTIVE but we are FORCED OFF, ignore it!
                    if (entry.forceOffUntil && Date.now() < entry.forceOffUntil) {
                         if (initialStartEpoch || isUserAction) {
                            // User explicitly toggled ON. Allow it.
                            entry.forceOffUntil = 0;
                            entry.isActive = true;
                        } else {
                            if (element) {
                                entry.elements.add(element);
                                // Don't show time yet if forced off, show 00:00:00
                                if (element.tagName === 'INPUT') element.value = "00:00:00";
                                else element.textContent = "00:00:00";
                            }
                            return key; 
                        }
                    } else {
                        entry.isActive = true;
                    }
                }

                if (initialStartEpoch) {
                    const newStartMs = initialStartEpoch * 1000;
                    // [Fix] Use dynamic threshold
                    if (!entry.startMs || Math.abs(entry.startMs - newStartMs) > entry.syncThreshold) {
                        entry.startMs = newStartMs;
                    }
                }
            }

            if (element) {
                registry[key].elements.add(element);
                this.updateElement(key, element);
            }

            this.startGlobalTimer();
            return key;
        },

        unregister: function(key, element) {
            if (registry[key]) {
                registry[key].elements.delete(element);
                if (registry[key].elements.size === 0) {
                    // Keep the data for backend integration even when no UI observes it (deletion logic can be added if needed)
                }
            }
        },

        updateElement: function(key, el) {
            const entry = registry[key];
            if (!entry) return;

            // Inactive → reset to zero
            if (!entry.isActive) {
                if (el.tagName === 'INPUT') el.value = "00:00:00";
                else el.textContent = "00:00:00";
                return;
            }

            // Active but startMs not yet known (waiting for first sync)
            if (entry.startMs === null) {
                if (el.tagName === 'INPUT') el.value = "---";
                else el.textContent = "---";
                return;
            }

            // Calculate duration
            const now = getNowMs();
            const diff = Math.max(0, now - entry.startMs);
            const text = formatDuration(diff);

            if (el.tagName === 'INPUT') el.value = text;
            else el.textContent = text;
        },

        sync: function(key) {
            const entry = registry[key];
            if (!entry) return;

            // [Fix] Ignore sync if forced off locally recently
            if (entry.forceOffUntil && Date.now() < entry.forceOffUntil) {
                // console.debug(`[AoT Runtime] Skipping sync for ${key} (Force Off Active)`);
                return;
            }

            // [Fix] Remove hardcoded 5s throttle. Use dynamic throttle.
            // Allow sync request if half of the cycle has passed, or if it's the first sync.
            const throttleMs = entry.syncThreshold ? (entry.syncThreshold / 2) : 2000;
            const now = Date.now();
            if (entry.lastSync && (now - entry.lastSync < throttleMs)) return;
            entry.lastSync = now;

            const url = `/output_started_at_public/${entry.deviceId}/${entry.channel}`;
            fetch(url)
                .then(res => {
                    if (res.status === 204) {
                        // No server data — if we have a local fallback startMs, keep counting
                        entry.localFallback = false; // stop retrying aggressively
                        throw new Error("No data");
                    }
                    return res.json();
                })
                .then(data => {
                    // [Fix] Stale Response Protection
                    // If the user stopped the timer (isActive=false) while this fetch was in-flight,
                    // COMPLETELY IGNORE the result. Do not update startMs, do not revive.
                    if (!entry.isActive) return;

                    let srvStartMs = null;
                    if (data.started_at_epoch !== undefined && data.started_at_epoch !== null) {
                        srvStartMs = data.started_at_epoch * 1000;
                    } else if (data.started_at_ms !== undefined && data.started_at_ms !== null) {
                         srvStartMs = data.started_at_ms;
                    } else if (data.point_ts_epoch !== undefined && data.point_ts_epoch !== null) {
                         srvStartMs = data.point_ts_epoch * 1000;
                    }

                    // [Sanity Check] Ignore timestamps older than 2020 (1577836800000)
                    // This prevents 0 (1970) or garbage data from resetting the timer.
                    if (srvStartMs !== null && srvStartMs < 1577836800000) {
                        srvStartMs = null;
                    }

                    if (srvStartMs) {
                         // Valid server time received
                         const threshold = entry.syncThreshold || 7000;

                        if (!entry.startMs || Math.abs(entry.startMs - srvStartMs) > threshold) {
                            entry.startMs = srvStartMs;
                            // Immediately refresh all elements
                            entry.elements.forEach(el => this.updateElement(key, el));
                        }
                    } 
                    // If srvStartMs is null (didn't pass check or no data), 
                    // WE DO NOTHING. We keep the local startMs ticking.
                })
                .catch(err => {
                    // console.debug(`[AoT Runtime] Sync Failed (${key}):`, err.message);
                });
        },

        tick: function() {
            const keys = Object.keys(registry);
            if (keys.length === 0) return;

            keys.forEach(key => {
                const entry = registry[key];
                // (tick debug removed)
                entry.elements.forEach(el => {
                    // Check whether it still exists in the DOM
                    const inDom = document.body.contains(el);
                    if (inDom) {
                        this.updateElement(key, el);
                    } else {
                        entry.elements.delete(el);
                    }
                });

                // [Fix] Use dynamic polling interval based on user option (syncThreshold)
                const pollInterval = entry.syncThreshold || 5000; 
                if (entry.elements.size > 0 && (Date.now() - entry.lastSync > pollInterval)) {
                    this.sync(key);
                }
            });
        },

        startGlobalTimer: function() {
            if (globalTimer) return;
            // console.log("[AoT Runtime] Starting Global Stopwatch Timer");
            globalTimer = setInterval(() => this.tick(), 1000);
        }
    };

    window.AoTStopwatchManager = Manager;

    // Expose the global timer auto-correction utility (for widget compatibility)
    // but assign getNowMs so it does not point to itself
    if (typeof window.tm_nowServerMs !== 'function') {
        window.tm_nowServerMs = getNowMs;
    }

})();

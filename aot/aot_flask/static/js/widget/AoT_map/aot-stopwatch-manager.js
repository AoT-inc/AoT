/**
 * aot-stopwatch-manager.js
 * 중앙 집중형 가동 시간(Stopwatch) 관리 시스템
 */

(function() {
    // console.log("[AoT Runtime] Stopwatch Manager Initializing...");

    const registry = {}; // { "deviceId::channel": { startMs, elements: Set, isActive } }
    let globalTimer = null;

    /**
     * HH:MM:SS 포맷 변환 루틴
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
     * 서버 시간 보정을 포함한 현재 시각 (AoT_map 호환)
     */
    function getNowMs() {
        // 전역변수에 tm_nowServerMs가 있고, 그것이 이 클로저 외부의 함수라면 호출
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
         * 스톱워치 등록
         * @param {string} deviceId "unique_id"
         * @param {number|string} channel 
         * @param {boolean} isActive 장치 활성 여부
         * @param {number|null} initialStartEpoch 초 단위 Epoch (Optional)
         * @param {HTMLElement} element 업데이트할 DOM 요소
         * @param {number} syncThresholdMs (Optional) 동기화 허용 오차 (기본값 7000)
         * @param {boolean} isUserAction (Optional) 사용자 명시적 조작 여부 (True: 상태 강제 변경 허용, False: 기존 상태가 Active면 유지)
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

                // [Fix] Initial Registration force-off check not usually needed but safe
                registry[key] = {
                    deviceId: cleanId,
                    channel: cleanChannel,
                    startMs: initialStartEpoch ? initialStartEpoch * 1000 : 0,
                    elements: new Set(),
                    isActive: !!isActive,
                    lastSync: 0,
                    forceOffUntil: 0, // [Fix] Timestamp to ignore server "active" status
                    syncThreshold: threshold // [Fix] Store dynamic threshold
                };
                console.log(`[AoT Runtime] Registered: ${key}, active=${isActive}, thresh=${threshold}`, registry[key]);
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
                    // 관찰하는 UI가 없어도 백엔드 연동을 위해 데이터는 유지 (필요시 삭제 로직 추가 가능)
                }
            }
        },

        updateElement: function(key, el) {
            const entry = registry[key];
            if (!entry) return;

            // [Fix] If inactive, force display to 00:00:00 and do not calculate duration
            if (!entry.isActive) {
                if (el.tagName === 'INPUT') el.value = "00:00:00";
                else el.textContent = "00:00:00";
                return;
            }

            // Active State Logic
            if (!entry.startMs) {
                // Active but no start time yet (waiting for sync or just started)
                // Show 00:00:00 until confirmed
                if (el.tagName === 'INPUT') el.value = "00:00:00";
                else el.textContent = "00:00:00";
                // 활성 상태인데 시작 시간이 없으면 동기화 재시도
                this.sync(key);
                return;
            }

            // Calculate duration
            const now = getNowMs();
            // Ensure we don't show negative time if server time lags slightly or startMs is future
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
                    if (res.status === 204) throw new Error("No data");
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
                            console.log(`[AoT Runtime] Sync Success (${key}): Rebased from ${entry.startMs} to ${srvStartMs} (diff > ${threshold})`);
                            entry.startMs = srvStartMs;
                            // 즉시 모든 엘리먼트 갱신
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
                entry.elements.forEach(el => {
                    // DOM에 존재하는지 확인
                    if (document.body.contains(el)) {
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

    // 전역 타이머 자동 보정 유틸리티 노출 (위젯 호환용)
    // 단, 자기 자신을 가리키지 않도록 getNowMs를 할당
    if (typeof window.tm_nowServerMs !== 'function') {
        window.tm_nowServerMs = getNowMs;
    }

})();

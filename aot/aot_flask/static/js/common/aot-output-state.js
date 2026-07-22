/**
 * aot-output-state.js — shared classifier for the Output state protocol.
 *
 * Backend output_state() returns one of:
 *   'on' | 'off' | 'pending' | 'fault' | <number> (PWM duty) | true/false/null.
 *
 * Widgets historically each re-interpreted this string, drifting apart (a map
 * popup showed 'fault' as OFF; timers counted from dispatch; sequences ignored
 * the device entirely). This single classifier keeps every widget consistent.
 *
 * Semantics (confirmation-based / "honest"):
 *   - on      : device-confirmed ON. Runtime counts (from confirmed-on).
 *   - off     : device-confirmed OFF.
 *   - pending : command sent, awaiting the device (bounded by the command
 *               timeout). Transient — resolves to on/off/fault. No runtime yet.
 *   - fault   : unconfirmed / offline. Distinct "no response" state — NOT a fake
 *               off, NOT an infinite wait. No runtime.
 */
(function (root) {
  var CLASS = {
    on:      'active-background',
    off:     'inactive-background',
    pending: 'hold-background',
    fault:   'pause-background'
  };

  function classify(raw) {
    if (raw === 'pending') {
      return { kind: 'pending', isOn: false, isPending: true, isFault: false,
               isOffline: false, countsRuntime: false, cssClass: CLASS.pending };
    }
    if (raw === 'fault') {
      return { kind: 'fault', isOn: false, isPending: false, isFault: true,
               isOffline: true, countsRuntime: false, cssClass: CLASS.fault };
    }
    if (raw === 'on' || raw === true) {
      return { kind: 'on', isOn: true, isPending: false, isFault: false,
               isOffline: false, countsRuntime: true, cssClass: CLASS.on };
    }
    if (typeof raw === 'number') {
      var on = raw > 0;
      return { kind: on ? 'on' : 'off', isOn: on, isPending: false, isFault: false,
               isOffline: false, countsRuntime: on, value: raw,
               cssClass: on ? CLASS.on : CLASS.off };
    }
    // 'off', false, null, undefined, or anything unrecognized
    return { kind: 'off', isOn: false, isPending: false, isFault: false,
             isOffline: false, countsRuntime: false, cssClass: CLASS.off };
  }

  // labels: optional {on,off,pending,fault} overrides (for i18n at call site).
  function label(raw, labels) {
    labels = labels || {};
    var c = classify(raw);
    if (c.kind === 'pending') return labels.pending || 'Confirming';
    if (c.kind === 'fault')   return labels.fault   || 'No response';
    if (c.kind === 'on')      return labels.on      || 'Active';
    return labels.off || 'Inactive';
  }

  root.AoTOutputState = { classify: classify, label: label };
})(typeof window !== 'undefined' ? window : this);

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
    // 2026-08-04: 'pause-background' 에서 분리. 그 클래스는 "사용자가 멈춤"
    // (PID 일시정지 등)에도 쓰여, 고장과 정상 운영이 같은 색으로 보였다.
    // 이 상수만 바꾸면 cssClass 를 쓰는 소비처는 전부 따라온다 — 다만
    // classList.remove(...) 목록에 'fault-background' 를 넣어 주지 않은 곳은
    // 빨강이 그대로 눌어붙으므로 소비처마다 확인이 필요하다.
    fault:   'fault-background'
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

  // classifyComm(active, commFault) — for entities whose backend status is a
  // plain {active, comm_fault} pair rather than the on/off/pending/fault
  // output_state() protocol above (currently: Input, via /inputstate — see
  // io_link_health_infra_plan.md). 'pending' has no meaning here: comm_fault
  // is derived from InputController.comm_is_fault(), which is synchronous
  // (stale-check or listener-connected check), never an in-flight command.
  function classifyComm(active, commFault) {
    if (!active) {
      return { kind: 'off', isOn: false, isPending: false, isFault: false,
               isOffline: false, countsRuntime: false, cssClass: CLASS.off };
    }
    if (commFault) {
      return { kind: 'fault', isOn: false, isPending: false, isFault: true,
               isOffline: true, countsRuntime: false, cssClass: CLASS.fault };
    }
    return { kind: 'on', isOn: true, isPending: false, isFault: false,
             isOffline: false, countsRuntime: true, cssClass: CLASS.on };
  }

  // aggregate(rawStates) — collapse a list of raw output_state() values (e.g.
  // every channel on one Output device, or every step of a Trigger Sequence)
  // into a single device/card-level classification. Precedence: any fault
  // wins over any pending, which wins over any on, which wins over off/empty.
  // Used for card-level summaries where the underlying UI already shows each
  // channel/step individually (this is the "at a glance" rollup, not a
  // replacement for the per-channel detail).
  function aggregate(rawStates) {
    var sawFault = false, sawPending = false, sawOn = false, any = false;
    (rawStates || []).forEach(function (raw) {
      if (raw === null || raw === undefined) return;
      any = true;
      var c = classify(raw);
      if (c.isFault) sawFault = true;
      else if (c.isPending) sawPending = true;
      else if (c.isOn) sawOn = true;
    });
    if (!any) {
      return { kind: 'off', isOn: false, isPending: false, isFault: false,
               isOffline: false, countsRuntime: false, cssClass: CLASS.off };
    }
    if (sawFault) {
      return { kind: 'fault', isOn: false, isPending: false, isFault: true,
               isOffline: true, countsRuntime: false, cssClass: CLASS.fault };
    }
    if (sawPending) {
      return { kind: 'pending', isOn: false, isPending: true, isFault: false,
               isOffline: false, countsRuntime: false, cssClass: CLASS.pending };
    }
    return { kind: sawOn ? 'on' : 'off', isOn: sawOn, isPending: false, isFault: false,
             isOffline: false, countsRuntime: sawOn, cssClass: sawOn ? CLASS.on : CLASS.off };
  }

  // paintNameWarning(el, on) — highlight a device-name label when its device is
  // comm-fault (no response).
  //
  // Uses the DANGER tint, not the warning tint, even though the function is
  // named ...Warning (kept for its callers). The warning pair is exposed in
  // settings/custom_ui as "Unverified Running Tint" — it belongs to
  // paintUnverifiedRunning() below, and users set it with that meaning in mind.
  // Borrowing it here made one knob carry two unrelated states, and on a real
  // install (김제, 2026-08-04) that read as: --aot-tint-warning-fg #4F4F4F grey,
  // --aot-tint-warning-bg #B8DBC7 GREEN — an unreachable device highlighted in
  // green, i.e. the opposite of the intent. "No response" is a failure, so it
  // takes the danger pair, whose settings label matches how it is used.
  //
  // MAP POPUPS ONLY. The Input/Output/Function list cards deliberately do NOT
  // use this: there the card background already carries the offline state, and
  // running both meant one fact showed up as two tints that appeared and
  // disappeared independently (turning a device on cleared the name tint while
  // the row gained one), which read as two unrelated problems. A map popup has
  // no card background to fall back on, so it keeps the name highlight.
  //
  // Deliberately inline style + setProperty(..., 'important'), NOT a CSS class:
  // name elements carry their own `background: transparent !important`
  // (aot-entry-ui.css), which a class-based override ties with on specificity
  // and then loses to by stylesheet load order. An inline !important always
  // wins the cascade over any external rule, important or not.
  function paintNameWarning(el, on) {
    if (!el) return;
    if (on) {
      el.style.setProperty('background-color', 'var(--aot-tint-danger-bg)', 'important');
      el.style.setProperty('color', 'var(--aot-tint-danger-fg)', 'important');
    } else {
      el.style.removeProperty('background-color');
      el.style.removeProperty('color');
    }
  }

  // paintUnverifiedRunning(el, unverified) — mark a device that is RUNNING but
  // whose state nothing can confirm (comm_capable() === false: a fire-and-forget
  // control signal with no ACK, readback or heartbeat path).
  //
  // Only while running, not always: most outputs in a deployment are of this
  // kind, so tinting them permanently would make the warning colour meaningless.
  // An unverifiable device sitting idle is unremarkable; an unverifiable device
  // reported as ON is the case actually worth flagging, because "supposedly
  // open" and "actually open" are indistinguishable there.
  //
  // This one KEEPS the warning tint: settings/custom_ui labels that pair
  // "Unverified Running Tint", so this is the state the user actually had in
  // mind when picking it. comm-fault moved to danger (paintNameWarning above).
  //
  // Inline !important for the same cascade reason as paintNameWarning() above.
  function paintUnverifiedRunning(el, unverified) {
    if (!el) return;
    if (unverified) {
      el.style.setProperty('background-color', 'var(--aot-tint-warning-bg)', 'important');
    } else {
      el.style.removeProperty('background-color');
    }
  }

  root.AoTOutputState = { classify: classify, label: label, classifyComm: classifyComm,
                          aggregate: aggregate, paintNameWarning: paintNameWarning,
                          paintUnverifiedRunning: paintUnverifiedRunning };
})(typeof window !== 'undefined' ? window : this);

/**
 * Calendar dashboard widget glue (aot/widgets/widget_calendar.py).
 * One FullCalendar instance per widget card; events come from
 * /api/v1/scheduler/calendar_events (aot/utils/calendar_event_providers.py).
 *
 * Clicking an event goes straight to the edit modal when the viewer can edit
 * (options.canEdit, from Jinja's permission_edit_settings) AND the row itself
 * allows it (per-event rowEditable/rowDeletable — some rows are locked
 * regardless of permission, e.g. an already-fired device command) — no
 * intermediate "Edit" button, matching how a normal calendar app's click
 * behaves. Anything else (view-only viewer, or a row that's deletable but
 * not editable) falls back to a small read-only popover with a deep link to
 * /scheduler (and a Delete button in the deletable-but-not-editable case).
 *
 * Dragging an event to a new day/time reschedules it (PUT with just
 * date/time); dragging its bottom edge resizes it (PUT with just
 * duration_minutes, computed from the new end - start). Both revert on
 * failure via FullCalendar's info.revert(). eventAllow gates both
 * interactions on the same per-event rowEditable flag as the click-to-edit
 * path above.
 *
 * Both paths call the *same* PUT/DELETE /api/v1/scheduler/jobs/<id>
 * endpoints scheduler.html's own per-job modal uses — this widget is a
 * second presentation of that one backend contract, not a parallel mutation
 * path. CSRF is handled for free by the global fetch() patch in
 * layout_default.html.
 */
(function () {
  'use strict';

  var POPOVER_ID = 'aot-calendar-widget-popover';

  function closePopover() {
    var el = document.getElementById(POPOVER_ID);
    if (el) el.parentNode.removeChild(el);
    document.removeEventListener('click', onOutsideClick, true);
    document.removeEventListener('keydown', onEscape, true);
  }

  function onOutsideClick(e) {
    var el = document.getElementById(POPOVER_ID);
    if (el && !el.contains(e.target)) closePopover();
  }

  function onEscape(e) {
    if (e.key === 'Escape') closePopover();
  }

  function fieldRow(label, value) {
    if (!value) return '';
    var row = document.createElement('div');
    row.className = 'aot-cal-popover-row';
    var l = document.createElement('span');
    l.className = 'aot-cal-popover-label';
    l.textContent = label;
    var v = document.createElement('span');
    v.className = 'aot-cal-popover-value';
    v.textContent = value;
    row.appendChild(l);
    row.appendChild(v);
    return row;
  }

  function actionButton(label, cssClass, onClick) {
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn aot-pill-btn ' + cssClass + ' aot-cal-popover-action';
    btn.textContent = label;
    btn.addEventListener('click', onClick);
    return btn;
  }

  function toDatetimeLocalValue(date) {
    var pad = function (n) { return (n < 10 ? '0' : '') + n; };
    return date.getFullYear() + '-' + pad(date.getMonth() + 1) + '-' + pad(date.getDate()) +
      'T' + pad(date.getHours()) + ':' + pad(date.getMinutes());
  }

  function showPopover(jsEvent, fcEvent, ctx) {
    closePopover();

    var props = fcEvent.extendedProps || {};
    var i18n = ctx.i18n;
    var pop = document.createElement('div');
    pop.id = POPOVER_ID;
    pop.className = 'aot-cal-popover';

    var title = document.createElement('div');
    title.className = 'aot-cal-popover-title';
    title.textContent = fcEvent.title;
    pop.appendChild(title);

    var body = document.createElement('div');
    body.className = 'aot-cal-popover-body';
    [
      fieldRow(i18n.start, fcEvent.start ? fcEvent.start.toLocaleString() : ''),
      fieldRow(i18n.location, props.location),
      fieldRow(i18n.worker, props.worker),
      fieldRow(i18n.state, props.state)
    ].forEach(function (row) {
      if (row) body.appendChild(row);
    });
    pop.appendChild(body);

    // Editable rows never reach this popover — eventClick sends them straight
    // to the edit modal instead. This only covers deletable-but-not-editable
    // rows (still worth a quick Delete) and fully read-only rows.
    if (ctx.canEdit && props.rowDeletable) {
      var actions = document.createElement('div');
      actions.className = 'aot-cal-popover-actions';
      actions.appendChild(actionButton(i18n.deleteLabel, 'aot-pill-btn-danger', function () {
        ctx.onDelete(fcEvent);
      }));
      pop.appendChild(actions);
    }

    var link = document.createElement('a');
    link.href = props.deepLink || '/scheduler';
    link.className = 'btn aot-pill-btn aot-pill-btn-primary aot-cal-popover-link';
    link.textContent = i18n.openScheduler;
    pop.appendChild(link);

    document.body.appendChild(pop);

    var rect = jsEvent.target.closest('.fc-event') ? jsEvent.target.closest('.fc-event').getBoundingClientRect() : jsEvent.target.getBoundingClientRect();
    var popRect = pop.getBoundingClientRect();
    var top = window.scrollY + rect.bottom + 6;
    var left = window.scrollX + Math.min(rect.left, window.innerWidth - popRect.width - 12);
    if (left < 8) left = 8;
    pop.style.top = top + 'px';
    pop.style.left = left + 'px';

    setTimeout(function () {
      document.addEventListener('click', onOutsideClick, true);
      document.addEventListener('keydown', onEscape, true);
    }, 0);
  }

  function pickInitialView(defaultView, containerEl) {
    var width = window.innerWidth;
    if (width < 768) return 'listWeek';
    if (width < 992) return 'timeGridWeek';
    if (containerEl && containerEl.getBoundingClientRect().width < 420) return 'listWeek';
    return defaultView;
  }

  function attachResponsiveSwitch(calendar, defaultView, containerEl) {
    var lastView = null;
    function apply() {
      var next = pickInitialView(defaultView, containerEl);
      if (next !== lastView) {
        calendar.changeView(next);
        lastView = next;
      }
      calendar.updateSize();
    }
    window.addEventListener('resize', apply);
    apply();
  }

  function putSchedule(jobId, payload, i18n, onSuccess, onError) {
    fetch('/api/v1/scheduler/jobs/' + jobId, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
      .then(function (r) { return r.json().then(function (body) { return { ok: r.ok, body: body }; }); })
      .then(function (res) {
        if (!res.ok) throw new Error((res.body && res.body.error) || i18n.saveFailed);
        onSuccess();
      })
      .catch(function (err) {
        alert(err.message || i18n.saveFailed);
        onError();
      });
  }

  function saveTime(jobId, date, i18n, onSuccess, onError) {
    var parts = toDatetimeLocalValue(date).split('T');
    putSchedule(jobId, { date: parts[0], time: parts[1] }, i18n, onSuccess, onError);
  }

  function saveDuration(jobId, start, end, i18n, onSuccess, onError) {
    var minutes = Math.round((end - start) / 60000);
    putSchedule(jobId, { duration_minutes: minutes }, i18n, onSuccess, onError);
  }

  function performDelete(jobId, i18n, onSuccess) {
    var reason = prompt(i18n.deletePrompt);
    if (reason === null) return;
    fetch('/api/v1/scheduler/jobs/' + jobId, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason: reason })
    })
      .then(function (r) { return r.json().then(function (body) { return { ok: r.ok, body: body }; }); })
      .then(function (res) {
        if (!res.ok) throw new Error((res.body && res.body.error) || i18n.deleteFailed);
        onSuccess();
      })
      .catch(function (err) { alert(err.message || i18n.deleteFailed); });
  }

  function setupEditModal(uniqueId, calendar, i18n) {
    var modalEl = document.getElementById('calendar-edit-modal-' + uniqueId);
    if (!modalEl) return { canEdit: false };

    var locationInput = document.getElementById('calendar-edit-location-' + uniqueId);
    var contentInput = document.getElementById('calendar-edit-content-' + uniqueId);
    var workerInput = document.getElementById('calendar-edit-worker-' + uniqueId);
    var timeInput = document.getElementById('calendar-edit-time-' + uniqueId);
    var saveBtn = document.getElementById('calendar-edit-save-' + uniqueId);
    var deleteBtn = document.getElementById('calendar-edit-delete-' + uniqueId);
    var mapWrapEl = document.getElementById('calendar-edit-map-wrap-' + uniqueId);
    var mapContainerEl = document.getElementById('calendar-edit-map-' + uniqueId);

    // Lazy create-on-shown / destroy-on-hidden, same lifecycle as
    // map_option_macros.html's render_device_map() — avoids exhausting the
    // browser's WebGL context cap since this modal is reused across every
    // job clicked, not one map per job.
    var mapInstance = null;
    var isShown = false;
    var pendingCoords = null;

    function destroyMap() {
      if (mapInstance) {
        try { mapInstance.remove(); } catch (e) { /* silent */ }
        mapInstance = null;
      }
    }

    function initMap(lat, lng) {
      destroyMap();
      if (typeof maplibregl === 'undefined' || !mapContainerEl) return;
      mapInstance = new maplibregl.Map({
        container: mapContainerEl,
        style: {
          version: 8,
          sources: {
            'osm-base': {
              type: 'raster',
              tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
              tileSize: 256,
              attribution: '© OpenStreetMap'
            }
          },
          layers: [{ id: 'osm-base', type: 'raster', source: 'osm-base' }]
        },
        center: [lng, lat],
        zoom: 15,
        attributionControl: false
      });
      mapInstance.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
      new maplibregl.Marker().setLngLat([lng, lat]).addTo(mapInstance);
    }

    if (mapWrapEl) {
      window.$(modalEl).on('shown.bs.modal', function () {
        isShown = true;
        if (pendingCoords) {
          mapWrapEl.classList.remove('d-none');
          initMap(pendingCoords.lat, pendingCoords.lng);
        }
      });
      window.$(modalEl).on('hidden.bs.modal', function () {
        isShown = false;
        pendingCoords = null;
        destroyMap();
        mapWrapEl.classList.add('d-none');
      });
    }

    function openFor(fcEvent) {
      var props = fcEvent.extendedProps || {};
      var jobId = props.jobId;
      modalEl.dataset.jobId = jobId;
      locationInput.value = props.location || '';
      contentInput.value = props.content || '';
      workerInput.value = props.worker || '';
      timeInput.value = fcEvent.start ? toDatetimeLocalValue(fcEvent.start) : '';

      pendingCoords = null;
      if (mapWrapEl) {
        mapWrapEl.classList.add('d-none');
        fetch('/api/v1/scheduler/jobs/' + jobId + '/location')
          .then(function (r) { return r.json(); })
          .then(function (loc) {
            // Stale response guard: user may have clicked a different event
            // before this resolved.
            if (loc && loc.lat != null && loc.lng != null && String(modalEl.dataset.jobId) === String(jobId)) {
              pendingCoords = loc;
              if (isShown) {
                mapWrapEl.classList.remove('d-none');
                initMap(loc.lat, loc.lng);
              }
            }
          })
          .catch(function () { /* no location resolved — leave map hidden, not fatal */ });
      }

      window.$(modalEl).modal('show');
    }

    saveBtn.addEventListener('click', function () {
      var jobId = modalEl.dataset.jobId;
      var dt = timeInput.value;
      var parts = dt.split('T');
      fetch('/api/v1/scheduler/jobs/' + jobId, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          date: parts[0] || null,
          time: parts[1] || null,
          content: contentInput.value,
          worker: workerInput.value,
          target_name: locationInput.value
        })
      })
        .then(function (r) { return r.json().then(function (body) { return { ok: r.ok, body: body }; }); })
        .then(function (res) {
          if (!res.ok) throw new Error((res.body && res.body.error) || i18n.saveFailed);
          window.$(modalEl).modal('hide');
          calendar.refetchEvents();
        })
        .catch(function (err) { alert(err.message || i18n.saveFailed); });
    });

    deleteBtn.addEventListener('click', function () {
      performDelete(modalEl.dataset.jobId, i18n, function () {
        window.$(modalEl).modal('hide');
        calendar.refetchEvents();
      });
    });

    return { canEdit: true, openFor: openFor };
  }

  window.aotCalendarWidgetInit = function (uniqueId, options) {
    var containerEl = document.getElementById('calendar-widget-' + uniqueId);
    if (!containerEl || typeof FullCalendar === 'undefined') return;
    containerEl.innerHTML = '';

    var i18n = {
      start: options.i18nStart,
      location: options.i18nLocation,
      worker: options.i18nWorker,
      state: options.i18nState,
      openScheduler: options.i18nOpenScheduler,
      deleteLabel: options.i18nDelete,
      deletePrompt: options.i18nDeletePrompt,
      saveFailed: options.i18nSaveFailed,
      deleteFailed: options.i18nDeleteFailed
    };

    var calendar = new FullCalendar.Calendar(containerEl, {
      initialView: options.defaultView,
      headerToolbar: { left: 'prev,next today', center: 'title', right: 'dayGridMonth,timeGridWeek,listWeek' },
      height: '100%',
      locale: options.locale,
      displayEventTime: false,
      views: {
        listWeek: { duration: { days: options.daysAheadList } }
      },
      events: function (fetchInfo, successCallback, failureCallback) {
        var params = new URLSearchParams({
          start: fetchInfo.startStr,
          end: fetchInfo.endStr,
          sources: options.includeSchedule ? 'schedule' : '',
          limit: 500
        });
        fetch('/api/v1/scheduler/calendar_events?' + params.toString())
          .then(function (r) { return r.json(); })
          .then(successCallback)
          .catch(failureCallback);
      },
      eventClassNames: function (arg) {
        return ['aot-cal-event', 'aot-cal-event--' + (arg.event.extendedProps.colorHint || 'chart-2')];
      },
      eventDidMount: function (info) {
        if (info.event.extendedProps.state) info.el.dataset.state = info.event.extendedProps.state;
      },
      eventClick: function (info) {
        info.jsEvent.preventDefault();
        var props = info.event.extendedProps || {};
        if (options.canEdit && props.rowEditable && editModal.canEdit) {
          editModal.openFor(info.event);
          return;
        }
        showPopover(info.jsEvent, info.event, {
          i18n: i18n,
          canEdit: !!options.canEdit,
          onDelete: function (fcEvent) {
            performDelete(fcEvent.extendedProps.jobId, i18n, function () {
              closePopover();
              calendar.refetchEvents();
            });
          }
        });
      },
      editable: !!options.canEdit,
      eventAllow: function (dropInfo, draggedEvent) {
        return !!(draggedEvent.extendedProps && draggedEvent.extendedProps.rowEditable);
      },
      eventDrop: function (info) {
        saveTime(info.event.extendedProps.jobId, info.event.start, i18n, function () {
          calendar.refetchEvents();
        }, function () {
          info.revert();
        });
      },
      eventResize: function (info) {
        saveDuration(info.event.extendedProps.jobId, info.event.start, info.event.end, i18n, function () {
          calendar.refetchEvents();
        }, function () {
          info.revert();
        });
      }
    });
    calendar.render();
    attachResponsiveSwitch(calendar, options.defaultView, containerEl);

    var editModal = options.canEdit ? setupEditModal(uniqueId, calendar, i18n) : { canEdit: false };

    if (options.refreshSeconds > 0) {
      setInterval(function () { calendar.refetchEvents(); }, options.refreshSeconds * 1000);
    }
  };
})();

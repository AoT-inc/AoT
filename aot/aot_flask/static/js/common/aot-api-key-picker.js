/*
 * AoT API Key Picker — resolves a stored key's plaintext value on demand.
 *
 * The picker UI used to render every stored API key's plaintext straight
 * into the page (option value / onclick attribute), so anyone who could
 * view the page's HTML got every key regardless of which one they needed.
 * This fetches only the single key the user actually selects, from a
 * permission-checked endpoint (/api/api_key/<unique_id>), instead.
 */
(function ($) {
  'use strict';

  if (window.AoTApiKeyPicker) return;

  function t(key) { return (typeof window._ === 'function') ? window._(key) : key; }

  function resolve(uniqueId) {
    return fetch('/api/api_key/' + encodeURIComponent(uniqueId), {credentials: 'same-origin'})
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data && data.status === 'success') return data.key;
        throw new Error((data && data.message) || 'Failed to resolve API key');
      });
  }

  function reportError(err) {
    console.error('AoTApiKeyPicker:', err);
    var msg = t('Could not load the API key.');
    if (typeof window.showToast !== 'undefined') {
      window.showToast(msg, 'error');
    } else if (typeof toastr !== 'undefined') {
      toastr['error'](msg);
    }
  }

  /*
   * The value arrives asynchronously now, so the field is held readonly until
   * it lands. Without that, selecting a key and immediately hitting Save could
   * submit the form before the fetch resolved — a race the old synchronous
   * (but plaintext-leaking) version could not hit.
   */
  function injectInto($target, uniqueId) {
    if (!$target || !$target.length || !uniqueId) return;
    var placeholders = $target.map(function () { return this.placeholder || ''; }).get();
    $target.prop('readonly', true).attr('placeholder', t('Loading…'));

    function restore() {
      $target.prop('readonly', false).each(function (i) {
        this.placeholder = placeholders[i];
      });
    }

    resolve(uniqueId).then(function (key) {
      restore();
      $target.val(key).trigger('change');
    }).catch(function (err) {
      restore();
      reportError(err);
    });
  }

  window.AoTApiKeyPicker = {
    // Bound to the <select onchange> in pages/form_options/api_key_macro.html
    handleSelectChange: function (selectEl, manageUrl) {
      var $select = $(selectEl);
      var val = $select.val();
      if (val === '__MANAGE_API_KEYS__') {
        window.location.href = manageUrl;
      } else if (val) {
        var $group = $select.closest('.aot-api-key-group');
        var $target = $group.find('input, textarea').not('.bootstrap-select input, .bootstrap-select textarea');
        injectInto($target, val);
      }
      $select.selectpicker('val', '');
    }
  };

  // Delegated click handler for the dropdown-item pickers in
  // Custom_Options.html / geo_input_option.html (data-api-key-ref="<unique_id>").
  $(document).on('click', 'a.dropdown-item[data-api-key-ref]', function (e) {
    e.preventDefault();
    var uniqueId = $(this).data('api-key-ref');
    var $target = $(this).closest('.aot-api-key-group').find('input');
    injectInto($target, uniqueId);
  });

})(jQuery);

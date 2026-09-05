/* AoT bundle: page-model-assets — built from 1 sources. Do not edit; edit sources and rebuild (tools/bundle.mjs). */
(function(n){"use strict";let p={},a=null;function f(e){p=e||{}}function y(e){a=e;let t=document.getElementById("aot-asset-lib-modal");t||(t=_()),u(t,!0),h(t.querySelector("#aot-lib-grid"),t.querySelector("#aot-lib-search"))}function m(){const e=document.getElementById("aot-asset-lib-modal");e&&u(e,!1)}function u(e,t){n.jQuery&&n.jQuery.fn&&n.jQuery.fn.modal?n.jQuery(e).modal(t?"show":"hide"):(e.classList.toggle("show",t),e.style.display=t?"block":"none")}function _(){const e=i=>n._?n._(i):i,t=document.createElement("div");return t.id="aot-asset-lib-modal",t.className="modal fade aot-option-modal",t.tabIndex=-1,t.setAttribute("role","dialog"),t.innerHTML=`
      <div class="modal-dialog modal-dialog-centered" role="document">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">${e("3D Asset Library")}</h5>
            <button type="button" class="close" data-dismiss="modal" aria-label="${e("Close")}">
              <span aria-hidden="true">&times;</span>
            </button>
          </div>
          <div class="modal-body">
            <input class="aot-lib-search" id="aot-lib-search" type="text" placeholder="${e("Search by name\u2026")}">
            <div class="aot-lib-grid" id="aot-lib-grid"></div>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn btn-sm btn-outline-secondary" data-dismiss="modal">${e("Close")}</button>
          </div>
        </div>
      </div>
    `,document.body.appendChild(t),t}let s=[];function h(e,t){e.innerHTML='<div style="color:var(--aot-color-text-secondary);text-align:center;padding:2rem;grid-column:1/-1">'+(n._?n._("Loading\u2026"):"Loading\u2026")+"</div>",fetch("/api/geo/model_assets").then(i=>i.json()).then(function(i){s=i,v(e,i),t&&(t.oninput=function(){const o=t.value.toLowerCase();v(e,o?s.filter(d=>d.name.toLowerCase().includes(o)):s)})}).catch(function(){e.innerHTML='<div style="color:var(--aot-color-danger);grid-column:1/-1;text-align:center;padding:1rem">'+(n._?n._("Failed to load"):"Failed to load")+"</div>"})}function v(e,t){if(e.innerHTML="",!t.length){e.innerHTML='<div style="color:var(--aot-color-text-secondary);text-align:center;padding:2rem;grid-column:1/-1">'+(n._?n._("No assets registered."):"No assets registered.")+"</div>";return}t.forEach(function(i){const o=document.createElement("div");o.className="aot-lib-card";const d=document.createElement("div");if(d.className="aot-lib-thumb",i.preview_png&&i.preview_status==="ok"){const r=document.createElement("img");r.src="/static/"+i.preview_png,r.alt=i.name,d.appendChild(r)}else d.innerHTML='<span style="font-size:var(--aot-fs-value)">\u{1F4E6}</span>';const c=document.createElement("div");c.className="aot-lib-name",c.textContent=i.name;const l=document.createElement("div");l.className="aot-lib-kind",l.textContent={primitive:n._?n._("Primitive"):"Primitive",extruded_polygon:n._?n._("Extruded"):"Extruded",imported_gltf:"GLTF"}[i.kind]||i.kind,o.append(d,c,l),o.addEventListener("click",function(){m(),a&&a(i)}),e.appendChild(o)})}n.AoTAssetLibrary={init:f,openModal:y,closeModal:m}})(window);

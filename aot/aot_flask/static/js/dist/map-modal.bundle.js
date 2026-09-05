/* AoT bundle: map-modal — built from 3 sources. Do not edit; edit sources and rebuild (tools/bundle.mjs). */
(function(){const c=`
    .searchbar {
      font-size: 14px;
      font-family: Arial, sans-serif;
      color: #202124;
      display: flex;
      z-index: 3;
      height: 44px;
      background: #fff;
      border: 1px solid #dfe1e5;
      box-shadow: none;
      border-radius: 24px;
      margin: 0 auto;
      width: 100%;
      max-width: 100%; /* Match overlay max-width */
    }

    .searchbar:hover {
      box-shadow: 0 1px 6px rgba(32, 33, 36, 0.28);
      border-color: transparent;
    }

    .searchbar-wrapper {
      flex: 1;
      display: flex;
      align-items: center;
      padding: 5px 8px 0 14px;
    }

    .searchbar-left {
      font-size: 14px;
      font-family: Arial, sans-serif;
      color: #202124;
      display: flex;
      align-items: center;
      padding-right: 13px;
      margin-top: -5px;
    }

    .search-icon-wrapper {
      display: flex;
      align-items: center;
      justify-content: center;
    }

    .search-icon {
      margin-top: 3px;
      color: #9aa0a6;
      height: 20px;
      line-height: 20px;
      width: 20px;
    }

    .searchbar-icon {
      display: inline-block;
      fill: currentColor;
      height: 24px;
      line-height: 24px;
      position: relative;
      width: 24px;
    }

    .searchbar-center {
      display: flex;
      flex: 1;
      flex-wrap: wrap;
    }

    .searchbar-input-spacer {
      color: transparent;
      flex: 100%;
      white-space: pre;
      height: 34px;
      font-size: 16px;
    }

    .searchbar-input {
      background-color: transparent;
      border: none;
      margin: 0;
      padding: 0;
      color: rgba(0, 0, 0, 0.87);
      word-wrap: break-word;
      outline: none;
      display: flex;
      flex: 100%;
      margin-top: -37px;
      height: 34px;
      font-size: 16px;
      max-width: 100%;
      width: 100%;
    }

    .searchbar-right {
      display: flex;
      flex: 0 0 auto;
      margin-top: -5px;
      align-items: center;
      flex-direction: row;
      padding-right: 8px;
    }

    .voice-search {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 32px;
      height: 32px;
      cursor: pointer;
      border-radius: 50%;
      transition: transform 0.2s ease, opacity 0.2s ease, background-color 0.2s ease;
    }

    .voice-search svg {
      width: 24px;
      height: 24px;
    }

    .voice-search:hover {
      background-color: rgba(66, 133, 244, 0.08);
      transform: scale(1.05);
    }

    .voice-search.disabled {
      opacity: 0.4;
      cursor: not-allowed;
    }

    .voice-search.active {
      animation: pulse 1.2s infinite;
    }

    @keyframes pulse {
      0% {
        transform: scale(1);
      }
      50% {
        transform: scale(1.08);
      }
      100% {
        transform: scale(1);
      }
    }
    `,u=document.createElement("template");u.innerHTML=`
    <style>
      ${c}

      :host {
        display: block;
        position: relative;
        width: 100%;
        max-width: 100%;
      }
      .searchbar-container {
        display: flex;
        justify-content: center;
        width: 100%;
      }
      .searchbar {
        width: 100%;
      }
      .results {
        position: absolute;
        top: calc(100% + 6px);
        left: 0;
        right: 0;
        z-index: var(--aot-z-dropdown);
        background: #fff;
        border: 1px solid rgba(0,0,0,.125);
        border-radius: .25rem;
        box-shadow: 0 .5rem 1rem rgba(0,0,0,.15);
        display: none;
        max-height: 200px;
        overflow-y: auto;
      }
      .results.show {
        display: block;
      }
      .list-group-item {
        position: relative;
        display: block;
        padding: .75rem 1.25rem;
        background-color: #fff;
        border: 1px solid rgba(0,0,0,.125);
        cursor: pointer;
      }
      .list-group-item:hover {
        background-color: #f8f9fa;
      }
    </style>
    <div class="searchbar-container">
      <div class="searchbar">
        <div class="searchbar-wrapper">
          <div class="searchbar-left">
            <div class="search-icon-wrapper">
              <span class="search-icon searchbar-icon">
                <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true">
                  <path d="M15.5 14h-.79l-.28-.27A6.471 6.471 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"></path>
                </svg>
              </span>
            </div>
          </div>
          <div class="searchbar-center">
            <div class="searchbar-input-spacer" aria-hidden="true"></div>
            <input type="text" class="searchbar-input" id="input" maxlength="2048" autocapitalize="off" autocomplete="off" title="\uC8FC\uC18C \uAC80\uC0C9" role="combobox" placeholder="\uC8FC\uC18C\uB97C \uC785\uB825\uD558\uC138\uC694.">
          </div>
          <div class="searchbar-right">
            <span class="voice-search" id="clear-btn" role="button" tabindex="0" aria-label="\uC0AD\uC81C">
              <svg viewBox="0 0 24 24" width="24" height="24">
                <path fill="#5f6368" d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"></path>
              </svg>
            </span>
          </div>
        </div>
      </div>
    </div>
    <div class="results list-group" id="results"></div>
  `;class o extends HTMLElement{constructor(){super(),this.attachShadow({mode:"open"}),this.shadowRoot.appendChild(u.content.cloneNode(!0)),this._debounceTimer=null,this._lastQuery=""}connectedCallback(){if(this.inputEl=this.shadowRoot.getElementById("input"),this.resultsEl=this.shadowRoot.getElementById("results"),this.clearBtn=this.shadowRoot.getElementById("clear-btn"),this.hasAttribute("placeholder")&&(this.inputEl.placeholder=this.getAttribute("placeholder")),this.inputEl.addEventListener("input",()=>{this._updateClearButton(),this._scheduleSearch()}),this.inputEl.addEventListener("keydown",t=>{t.key==="Enter"&&(t.preventDefault(),this._scheduleSearch({immediate:!0}))}),this.clearBtn){const t=e=>{e.preventDefault(),this.inputEl.value="",this.inputEl.focus(),this._updateClearButton(),this.resultsEl.innerHTML="",this.resultsEl.classList.remove("show"),this._lastQuery=""};this.clearBtn.addEventListener("click",t),this.clearBtn.addEventListener("keydown",e=>{(e.key==="Enter"||e.key===" ")&&t(e)})}this._updateClearButton()}_updateClearButton(){this.clearBtn&&(this.inputEl.value&&this.inputEl.value.trim().length>0?this.clearBtn.style.visibility="visible":this.clearBtn.style.visibility="hidden")}_scheduleSearch(t={}){const e=t.immediate;clearTimeout(this._debounceTimer),e?this.search({force:!0}):this._debounceTimer=setTimeout(()=>this.search(),800)}setLayerId(t){this.currentLayerId=t}showToast(t,e="info"){window.showToast?window.showToast(t,e):console.log(`[AoTMapSearch] ${e}: ${t}`)}search(t={}){const e=this.inputEl.value.trim();if(!e){this.resultsEl.classList.remove("show"),this.resultsEl.innerHTML="",this._lastQuery="";return}if(e===this._lastQuery&&this.resultsEl.hasChildNodes()){this.resultsEl.classList.add("show");return}this._lastQuery=e;let i=this.currentLayerId;window.AOT_GEO_CONFIG&&window.AOT_GEO_CONFIG.search_provider&&(i=window.AOT_GEO_CONFIG.search_provider);const n={layer_id:i||null,query:e,type:"place"};window.AoTAPIManager?window.AoTAPIManager.request("/api/geo/search",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(n)}).then(a=>{a.ok?this.renderResults(a.results):(console.warn("Search API Error:",a.message),this.showToast(a.message||"Search Failed","error"))}).catch(a=>{console.error("[Search] Request Error:",a),this.showToast(_("Search service unavailable"),"error")}):fetch("/api/geo/search",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(n)}).then(a=>a.json()).then(a=>{a.ok?this.renderResults(a.results):(console.warn("Search API Error:",a.message),this.showToast(a.message||"Search Failed","error"))}).catch(a=>{console.error("Search failed",a),this.showToast("Network or parsing error occurred.","error")})}renderResults(t){if(this.resultsEl.innerHTML="",!t||!t.length){this.resultsEl.classList.remove("show");return}t.forEach(e=>{const i=document.createElement("div");i.className="list-group-item list-group-item-action",i.textContent=e.name||e.address||"Unknown Location",i.addEventListener("click",()=>{this.selectLocation(e)}),this.resultsEl.appendChild(i)}),this.resultsEl.classList.add("show")}selectLocation(t){this.resultsEl.innerHTML="",this.resultsEl.classList.remove("show");const e=t.name||t.address||"";this.inputEl.value=e,this._lastQuery=e;const i=parseFloat(t.lat??t.latitude),n=parseFloat(t.lng??t.lon??t.longitude);if(isNaN(i)||isNaN(n)){console.error("[AoTSearch] invalid coordinates in item:",JSON.stringify(t)),this.showToast("\uC88C\uD45C \uC815\uBCF4\uAC00 \uC5C6\uB294 \uACB0\uACFC\uC785\uB2C8\uB2E4.","warning");return}this.dispatchEvent(new CustomEvent("location-selected",{detail:{lat:i,lng:n,name:e},bubbles:!0,composed:!0}))}}customElements.get("aot-map-search-fixed")||customElements.define("aot-map-search-fixed",o)})(),(function(){if(window.AoTMapSearchController)return;class c{constructor(o,r,t=null){this.map=o,this.searchComp=document.getElementById(r.searchId),this.toggleBtn=document.getElementById(r.toggleBtnId),this.overlay=document.getElementById(r.overlayId),this.inputLatId=r.inputLatId,this.inputLngId=r.inputLngId,this.marker=t,this.init()}init(){this.toggleBtn&&this.overlay&&this.toggleBtn.addEventListener("click",()=>{this.toggle()}),this.searchComp&&(this.searchComp.addEventListener("location-selected",o=>this.onLocationSelected(o)),this.map.on("baselayerchange",o=>{const r=o.layer;r&&r.aot_base_id?this.searchComp.setLayerId(r.aot_base_id):r&&r.aot_id?this.searchComp.setLayerId(r.aot_id):this.searchComp.setLayerId(null)}),this.map.eachLayer(o=>{o.aot_base_id&&(o.options&&!o.options.role||o.options.role==="base")&&this.searchComp.setLayerId(o.aot_base_id)}))}toggle(){if(this.overlay.classList.contains("d-none")){if(this.overlay.classList.remove("d-none"),this.overlay.style.display="flex",this.toggleBtn&&this.toggleBtn.classList.add("text-primary"),this.searchComp&&this.searchComp.shadowRoot){const o=this.searchComp.shadowRoot.getElementById("input");o&&setTimeout(()=>o.focus(),50)}}else this.overlay.classList.add("d-none"),this.overlay.style.display="",this.toggleBtn&&this.toggleBtn.classList.remove("text-primary")}onLocationSelected(o){const{lat:r,lng:t,name:e}=o.detail||{};if(isNaN(r)||isNaN(t)||r==null||t==null){console.error("[SearchController] invalid coordinates:",o.detail);return}const i=this.map._originalMap||null,n=!!i;if(n?i.flyTo({center:[t,r],zoom:16,duration:1}):this.map.flyTo([r,t],16),this.marker)this.marker.setLatLng([r,t]),this.marker.getPopup()?this.marker.setPopupContent(e):this.marker.bindPopup(e),this.marker.openPopup();else if(n&&window.maplibregl){const a=new maplibregl.Popup({closeOnClick:!0,offset:[0,-6]}).setLngLat([t,r]).setHTML('<div style="font-size:13px;max-width:220px;">'+e+"</div>").addTo(i);setTimeout(()=>{try{a.remove()}catch{}},4e3)}if(this.inputLatId&&this.inputLngId){const a=document.getElementById(this.inputLatId),s=document.getElementById(this.inputLngId);a&&(a.value=r),s&&(s.value=t)}this.toggle()}}window.AoTMapSearchController=c})(),(function(){if(window.AoTMapModalController)return;var c="https://demotiles.maplibre.org/style.json";function u(r){var t=document.createElement("div");return t.className="aot-map-label-marker",t.innerHTML='<div class="label-box" style="background:white;padding:4px 10px;border-radius:20px;border:2px solid #3366ff;box-shadow:0 2px 6px rgba(0,0,0,0.3);white-space:nowrap;width:max-content;font-weight:600;color:#333;font-size:13px;cursor:move;">'+(r||"Device")+"</div>",t}class o{constructor(t){this.options=t||{},this.mapId=this.options.mapId,this.uniqueId=this.options.uniqueId,this.latId=this.options.latId,this.lngId=this.options.lngId,this.initLat=this.options.initLat,this.initLng=this.options.initLng,this.zoom=this.options.zoom,this.formId=this.options.formId,this.mapConfigId=this.options.mapConfigId,this.map=null,this.marker=null,this.draw=null,this._init()}_init(){const t=window.AOT_GEO_CONFIG||{},e=parseFloat(t.default_lat)||37.5665,i=parseFloat(t.default_lng)||126.978,n=parseFloat(t.zoom)||13,a=parseInt(t.max_zoom)||22,s=(t.layers||[]).filter(function(d){return d.type==="vector"}),l=s.length>0&&s[0].url?s[0].url:c,h=$("#"+this.mapId);if(!h.length||h.hasClass("aot-map-init-done"))return;h.addClass("aot-map-init-done"),o._instances=o._instances||{};const b=o._instances[this.mapId];if(b&&b!==this)try{typeof b.destroy=="function"&&b.destroy()}catch{}o._instances[this.mapId]=this,this.uniqueId||(this.uniqueId=h.data("unique-id")),this.latId||(this.latId=h.data("lat-id")),this.lngId||(this.lngId=h.data("lng-id")),this.formId||(this.formId=h.data("form-id")),!this.options.type&&h.data("type")&&(this.options.type=h.data("type")),this.mapConfigId||(this.mapConfigId=h.data("map-config-id"));const w=(d,g)=>{if(d==="null"||d===null||d===void 0)return g;const p=parseFloat(d);return isNaN(p)?g:p};let m=this.initLat===void 0?w(h.data("init-lat"),e):this.initLat,f=this.initLng===void 0?w(h.data("init-lng"),i):this.initLng,L=this.zoom===void 0?w(h.data("zoom"),n):this.zoom;(m===null||isNaN(m))&&(m=e),(f===null||isNaN(f))&&(f=i);const x=L||n;if(typeof maplibregl>"u"){console.error("[AoTMapModal] maplibre-gl not loaded");return}try{this.map=new maplibregl.Map({container:this.mapId,style:l,center:[f,m],zoom:x,maxZoom:a,doubleClickZoom:!1,attributionControl:!1})}catch(d){console.error("[AoTMapModal] Map create failed:",d);return}if(l!==c){const d=g=>{const p=g&&g.error,y=p&&p.status||0,I=p&&p.url||"";if((I===l||I.indexOf("style.json")!==-1)&&(y===401||y===403||y===404||y>=500)){console.warn("[AoTMapModal] Base style failed to load (HTTP "+y+"), falling back to demotiles:",l),this.map.off("error",d);try{this.map.setStyle(c)}catch{}}};this.map.on("error",d),this.map.once("load",()=>{this.map.off("error",d)})}try{this.map.addControl(new maplibregl.AttributionControl({compact:!0}),"bottom-right")}catch{}requestAnimationFrame(()=>{try{this.map.resize()}catch{}});const E=this._getDeviceName()||"Device",v=u(E);this.marker=new maplibregl.Marker({element:v,draggable:!0,anchor:"center"}).setLngLat([f,m]).addTo(this.map),this._attachLabelDblClick(v),this._bindMapEvents(),this._bindZoomEvents(),this._bindSearch(),this._bindLabelSync(),this._bindModalEvents(),this._bindCenterTool()}_initDrawControl(){if(!(!window.AoTMapLibreDraw||typeof window.AoTMapLibreDraw.create!="function"))try{this.draw=window.AoTMapLibreDraw.create(this.map,{displayControlsDefault:!1,controls:{polygon:!0,line_string:!0,point:!1,trash:!0}}),this.draw&&typeof this.draw.init=="function"&&Promise.resolve(this.draw.init({autoLoadDraw:!0})).then(()=>{typeof this.draw.on=="function"&&(this.draw.on("draw.create",()=>this._saveShapes()),this.draw.on("draw.update",()=>this._saveShapes()),this.draw.on("draw.delete",()=>this._saveShapes()))})}catch(t){console.warn("[AoTMapModal] Draw init failed:",t)}}_loadShapes(t){try{const e=JSON.parse(t);Array.isArray(e)&&this.draw&&e.forEach(i=>{try{this.draw.add(i)}catch{}})}catch{}}_renderGeoJSON(t){!Array.isArray(t)||!this.draw||t.forEach(e=>{try{this.draw.add(e)}catch{}})}_saveShapes(){if(!this.uniqueId)return;const t=this.draw&&typeof this.draw.getAll=="function"?this.draw.getAll():{features:[]},e=t&&t.features||[],i=JSON.stringify(e);let s=$("#"+this.mapId).closest(".modal-content, .grid-stack-item-content, form").find('input[name="drawing_shapes"]');s.length||(s=$("#input-drawing-shapes-"+this.uniqueId)),s.length&&s.val(i).trigger("change"),this.mapConfigId&&$.ajax({url:"/api/geo/overlays",method:"POST",contentType:"application/json",data:JSON.stringify({map_uuid:this.mapConfigId,type:"device",device_id:this.uniqueId,features:e})})}_loadShapesFromAPI(){!this.uniqueId||!this.mapConfigId||$.ajax({url:"/api/geo/overlays",method:"GET",data:{map_uuid:this.mapConfigId,type:"device",device_id:this.uniqueId},success:t=>{t&&t.features&&this._renderGeoJSON(t.features)}})}_getDeviceName(){let t=null;if(this.formId){const e=$("#"+this.formId);t=e.find(".input-device-name"),t.length||(t=e.find('input[name="device_name"]')),t.length||(t=e.find('input[name="name"]'))}if((!t||!t.length)&&this.mapId){const i=$("#"+this.mapId).closest(".modal-content, .grid-stack-item-content, form");i.length&&(t=i.find(".input-device-name"),t.length||(t=i.find('input[name="device_name"]')),t.length||(t=i.find('input[name="name"]')))}return t&&t.length?t.val():null}_bindMapEvents(){const t=this;this.marker.on("dragend",function(){const e=t.marker.getLngLat();t._updateInputs(e.lat,e.lng)}),this.map.on("click",function(e){if(t.draw&&t.draw.draw&&typeof t.draw.draw.getMode=="function")try{const i=t.draw.draw.getMode();if(i&&i!=="simple_select"&&i!=="static")return}catch{}t.marker.setLngLat([e.lngLat.lng,e.lngLat.lat]),t._updateInputs(e.lngLat.lat,e.lngLat.lng)}),this.map.on("dblclick",function(e){t.marker.setLngLat([e.lngLat.lng,e.lngLat.lat]),t._updateInputs(e.lngLat.lat,e.lngLat.lng),t.map.panTo([e.lngLat.lng,e.lngLat.lat])})}_updateInputs(t,e){if(this.latId){const a=$("#"+this.latId);a.length&&a.val(t.toFixed(6)).trigger("change")}if(this.lngId){const a=$("#"+this.lngId);a.length&&a.val(e.toFixed(6)).trigger("change")}const n=$("#"+this.mapId).closest(".modal-content, .grid-stack-item-content, form, .card-body");n.length&&(n.find('input[name="latitude"], input[name$="latitude"]').not("#"+this.latId).val(t.toFixed(6)).trigger("change"),n.find('input[name="longitude"], input[name$="longitude"]').not("#"+this.lngId).val(e.toFixed(6)).trigger("change")),this._updateKmaGrid(t,e),this._saveLocation(t,e)}_updateKmaGrid(t,e){if(!this.mapId)return;const n=$("#"+this.mapId).closest(".modal-content, .grid-stack-item-content, form, .card-body");if(!n.length)return;const a=n.find('input[name="nx"], input[name$="nx"], input[name*="[nx]"]'),s=n.find('input[name="ny"], input[name$="ny"], input[name*="[ny]"]');(a.length||s.length)&&$.ajax({url:"/api/tools/kma_lookup",method:"POST",contentType:"application/json",data:JSON.stringify({lat:t,lon:e}),success:l=>{l&&l.ok&&(a.length&&a.val(l.nx).trigger("change"),s.length&&s.val(l.ny).trigger("change"))}})}_saveLocation(t,e){!this.uniqueId||!this.options.type||$.ajax({url:"/api/geo/device/location",method:"POST",contentType:"application/json",data:JSON.stringify({unique_id:this.uniqueId,type:this.options.type,lat:t,lng:e})})}_bindZoomEvents(){const t=$("#btn-zoom-in-"+this.uniqueId),e=$("#btn-zoom-out-"+this.uniqueId);t.length&&t.on("click",()=>this.map.zoomIn()),e.length&&e.on("click",()=>this.map.zoomOut())}_bindCenterTool(){const t=$("#btn-center-label-"+this.uniqueId);t.length&&t.on("click",()=>{const e=this.map.getCenter();this.marker.setLngLat([e.lng,e.lat]),this._updateInputs(e.lat,e.lng)})}_bindSearch(){if(!window.AoTMapSearchController)return;const t=this.map,e={_originalMap:t,on:(a,s)=>t.on(a,s),eachLayer:()=>{},flyTo:a=>t.flyTo(a)},i=this,n={setLatLng:a=>{const s=Array.isArray(a)?a[0]:a.lat,l=Array.isArray(a)?a[1]:a.lng;i.marker.setLngLat([l,s]),i._updateInputs(s,l)},getPopup:()=>i.marker.getPopup?i.marker.getPopup():null,setPopupContent:a=>{const s=i.marker.getPopup?i.marker.getPopup():null;s&&s.setHTML(a)},bindPopup:a=>{typeof i.marker.setPopup=="function"&&i.marker.setPopup(new maplibregl.Popup({offset:12}).setHTML(a))},openPopup:()=>{typeof i.marker.togglePopup=="function"&&i.marker.togglePopup()}};try{new AoTMapSearchController(e,{searchId:"search-comp-"+this.uniqueId,toggleBtnId:"btn-search-"+this.uniqueId,overlayId:"search-overlay-"+this.uniqueId,inputLatId:this.latId,inputLngId:this.lngId},n)}catch(a){console.warn("[AoTMapModal] Search bind failed:",a)}}_attachLabelDblClick(t){const e=this;t.addEventListener("dblclick",function(i){i.stopPropagation();const n=e._findNameInput();if(!n||!n.length)return;const a=n.val(),s=prompt(window._?window._("Edit label name:"):"Edit label name:",a);s!==null&&n.val(s).trigger("change")})}_findNameInput(){let t=null;if(this.formId){const e=$("#"+this.formId);t=e.find(".input-device-name"),t.length||(t=e.find('input[name="device_name"]')),t.length||(t=e.find('input[name="name"]'))}if((!t||!t.length)&&this.mapId){const i=$("#"+this.mapId).closest(".modal-content, .grid-stack-item-content, form");i.length&&(t=i.find(".input-device-name"),t.length||(t=i.find('input[name="device_name"]')),t.length||(t=i.find('input[name="name"]')))}return t}_bindLabelSync(){const t=this._findNameInput();if(!t||!t.length)return;const e=()=>{if(!this.marker)return;const i=this.marker.getElement();if(!i)return;const n=t.val()||"Device",a=i.querySelector(".label-box");a?a.textContent=n:i.innerHTML=u(n).innerHTML};this._$labelInput=t,t.off("keyup.aotlabel change.aotlabel").on("keyup.aotlabel change.aotlabel",e),e()}_bindModalEvents(){const t=this,e=$("#"+this.mapId).closest(".modal"),i=document.getElementById(this.mapId),n=()=>{t.map&&requestAnimationFrame(()=>{try{t.map.resize(),t.marker&&t.map.panTo(t.marker.getLngLat())}catch{}})};e.length&&(e.on("shown.bs.modal.aotmap",n),e.hasClass("show")&&n()),i&&window.ResizeObserver&&(this.resizeObserver=new ResizeObserver(a=>{for(let s=0;s<a.length;s++){const l=a[s].contentRect;l.width>0&&l.height>0&&requestAnimationFrame(()=>{try{t.map&&t.map.resize()}catch{}})}}),this.resizeObserver.observe(i))}destroy(){try{this.resizeObserver&&this.resizeObserver.disconnect()}catch{}this.resizeObserver=null;const t=$("#"+this.mapId),e=t.closest(".modal");if(e.length)try{e.off(".aotmap")}catch{}try{this._$labelInput&&this._$labelInput.off("keyup.aotlabel change.aotlabel")}catch{}this._$labelInput=null;try{this.marker&&typeof this.marker.remove=="function"&&this.marker.remove()}catch{}this.marker=null;try{this.draw&&typeof this.draw.destroy=="function"&&this.draw.destroy()}catch{}this.draw=null;try{this.map&&typeof this.map.remove=="function"&&this.map.remove()}catch{}this.map=null;try{o._instances&&o._instances[this.mapId]===this&&delete o._instances[this.mapId]}catch{}t.removeClass("aot-map-init-done")}static initAll(){$(".map-container").not(".aot-map-init-done").each(function(){const t=$(this);if(t.closest(".modal").length)return;const e=t.attr("id");e&&new o({mapId:e})})}}window.AoTMapModalController=o})();

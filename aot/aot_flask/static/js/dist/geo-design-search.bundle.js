/* AoT bundle: geo-design-search — built from 2 sources. Do not edit; edit sources and rebuild (tools/bundle.mjs). */
(function(){const n=`
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
    `,l=document.createElement("template");l.innerHTML=`
    <style>
      ${n}

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
  `;class r extends HTMLElement{constructor(){super(),this.attachShadow({mode:"open"}),this.shadowRoot.appendChild(l.content.cloneNode(!0)),this._debounceTimer=null,this._lastQuery=""}connectedCallback(){if(this.inputEl=this.shadowRoot.getElementById("input"),this.resultsEl=this.shadowRoot.getElementById("results"),this.clearBtn=this.shadowRoot.getElementById("clear-btn"),this.hasAttribute("placeholder")&&(this.inputEl.placeholder=this.getAttribute("placeholder")),this.inputEl.addEventListener("input",()=>{this._updateClearButton(),this._scheduleSearch()}),this.inputEl.addEventListener("keydown",e=>{e.key==="Enter"&&(e.preventDefault(),this._scheduleSearch({immediate:!0}))}),this.clearBtn){const e=t=>{t.preventDefault(),this.inputEl.value="",this.inputEl.focus(),this._updateClearButton(),this.resultsEl.innerHTML="",this.resultsEl.classList.remove("show"),this._lastQuery=""};this.clearBtn.addEventListener("click",e),this.clearBtn.addEventListener("keydown",t=>{(t.key==="Enter"||t.key===" ")&&e(t)})}this._updateClearButton()}_updateClearButton(){this.clearBtn&&(this.inputEl.value&&this.inputEl.value.trim().length>0?this.clearBtn.style.visibility="visible":this.clearBtn.style.visibility="hidden")}_scheduleSearch(e={}){const t=e.immediate;clearTimeout(this._debounceTimer),t?this.search({force:!0}):this._debounceTimer=setTimeout(()=>this.search(),800)}setLayerId(e){this.currentLayerId=e}showToast(e,t="info"){window.showToast?window.showToast(e,t):console.log(`[AoTMapSearch] ${t}: ${e}`)}search(e={}){const t=this.inputEl.value.trim();if(!t){this.resultsEl.classList.remove("show"),this.resultsEl.innerHTML="",this._lastQuery="";return}if(t===this._lastQuery&&this.resultsEl.hasChildNodes()){this.resultsEl.classList.add("show");return}this._lastQuery=t;let a=this.currentLayerId;window.AOT_GEO_CONFIG&&window.AOT_GEO_CONFIG.search_provider&&(a=window.AOT_GEO_CONFIG.search_provider);const o={layer_id:a||null,query:t,type:"place"};window.AoTAPIManager?window.AoTAPIManager.request("/api/geo/search",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(o)}).then(i=>{i.ok?this.renderResults(i.results):(console.warn("Search API Error:",i.message),this.showToast(i.message||"Search Failed","error"))}).catch(i=>{console.error("[Search] Request Error:",i),this.showToast(_("Search service unavailable"),"error")}):fetch("/api/geo/search",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(o)}).then(i=>i.json()).then(i=>{i.ok?this.renderResults(i.results):(console.warn("Search API Error:",i.message),this.showToast(i.message||"Search Failed","error"))}).catch(i=>{console.error("Search failed",i),this.showToast("Network or parsing error occurred.","error")})}renderResults(e){if(this.resultsEl.innerHTML="",!e||!e.length){this.resultsEl.classList.remove("show");return}e.forEach(t=>{const a=document.createElement("div");a.className="list-group-item list-group-item-action",a.textContent=t.name||t.address||"Unknown Location",a.addEventListener("click",()=>{this.selectLocation(t)}),this.resultsEl.appendChild(a)}),this.resultsEl.classList.add("show")}selectLocation(e){this.resultsEl.innerHTML="",this.resultsEl.classList.remove("show");const t=e.name||e.address||"";this.inputEl.value=t,this._lastQuery=t;const a=parseFloat(e.lat??e.latitude),o=parseFloat(e.lng??e.lon??e.longitude);if(isNaN(a)||isNaN(o)){console.error("[AoTSearch] invalid coordinates in item:",JSON.stringify(e)),this.showToast("\uC88C\uD45C \uC815\uBCF4\uAC00 \uC5C6\uB294 \uACB0\uACFC\uC785\uB2C8\uB2E4.","warning");return}this.dispatchEvent(new CustomEvent("location-selected",{detail:{lat:a,lng:o,name:t},bubbles:!0,composed:!0}))}}customElements.get("aot-map-search-fixed")||customElements.define("aot-map-search-fixed",r)})(),(function(){if(window.AoTMapSearchController)return;class n{constructor(r,s,e=null){this.map=r,this.searchComp=document.getElementById(s.searchId),this.toggleBtn=document.getElementById(s.toggleBtnId),this.overlay=document.getElementById(s.overlayId),this.inputLatId=s.inputLatId,this.inputLngId=s.inputLngId,this.marker=e,this.init()}init(){this.toggleBtn&&this.overlay&&this.toggleBtn.addEventListener("click",()=>{this.toggle()}),this.searchComp&&(this.searchComp.addEventListener("location-selected",r=>this.onLocationSelected(r)),this.map.on("baselayerchange",r=>{const s=r.layer;s&&s.aot_base_id?this.searchComp.setLayerId(s.aot_base_id):s&&s.aot_id?this.searchComp.setLayerId(s.aot_id):this.searchComp.setLayerId(null)}),this.map.eachLayer(r=>{r.aot_base_id&&(r.options&&!r.options.role||r.options.role==="base")&&this.searchComp.setLayerId(r.aot_base_id)}))}toggle(){if(this.overlay.classList.contains("d-none")){if(this.overlay.classList.remove("d-none"),this.overlay.style.display="flex",this.toggleBtn&&this.toggleBtn.classList.add("text-primary"),this.searchComp&&this.searchComp.shadowRoot){const r=this.searchComp.shadowRoot.getElementById("input");r&&setTimeout(()=>r.focus(),50)}}else this.overlay.classList.add("d-none"),this.overlay.style.display="",this.toggleBtn&&this.toggleBtn.classList.remove("text-primary")}onLocationSelected(r){const{lat:s,lng:e,name:t}=r.detail||{};if(isNaN(s)||isNaN(e)||s==null||e==null){console.error("[SearchController] invalid coordinates:",r.detail);return}const a=this.map._originalMap||null,o=!!a;if(o?a.flyTo({center:[e,s],zoom:16,duration:1}):this.map.flyTo([s,e],16),this.marker)this.marker.setLatLng([s,e]),this.marker.getPopup()?this.marker.setPopupContent(t):this.marker.bindPopup(t),this.marker.openPopup();else if(o&&window.maplibregl){const i=new maplibregl.Popup({closeOnClick:!0,offset:[0,-6]}).setLngLat([e,s]).setHTML('<div style="font-size:13px;max-width:220px;">'+t+"</div>").addTo(a);setTimeout(()=>{try{i.remove()}catch{}},4e3)}if(this.inputLatId&&this.inputLngId){const i=document.getElementById(this.inputLatId),h=document.getElementById(this.inputLngId);i&&(i.value=s),h&&(h.value=e)}this.toggle()}}window.AoTMapSearchController=n})();

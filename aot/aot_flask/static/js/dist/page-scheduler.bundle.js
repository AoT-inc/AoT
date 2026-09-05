/* AoT bundle: page-scheduler — built from 2 sources. Do not edit; edit sources and rebuild (tools/bundle.mjs). */
class DeviceTimeline{constructor(e){this.container=document.getElementById(e),this.container&&(this.timeline=null,this.init())}async init(){try{const e=await this.fetchData();if(e.error){console.error("Failed to fetch timeline data:",e.message);return}this.render(e)}catch(e){console.error("Error initializing DeviceTimeline:",e)}}async fetchData(){return await(await fetch("/api/scheduler/device_timeline?hours=24")).json()}render(e){const t={groupOrder:(n,i)=>n.content.localeCompare(i.content),editable:!1,margin:{item:10,axis:5},orientation:"top",zoomMin:36e5,zoomMax:6048e5,tooltip:{followMouse:!0,overflowMethod:"cap"},template:n=>`
          <div class="timeline-item-content ${n.id.split("_")[0]}-content">
            ${n.content}
          </div>
        `};this.container.innerHTML="",this.timeline=new vis.Timeline(this.container,new vis.DataSet(e.items),new vis.DataSet(e.groups),t),this.timeline.on("select",n=>{n.items.length>0&&this.showItemDetails(n.items[0])})}showItemDetails(e){const t=this.timeline.itemsData.get(e);console.log("Selected item:",t),window.showToast&&window.showToast(`Selected: ${t.content} (${t.start} to ${t.end||"N/A"})`,"info")}refresh(){this.init()}}document.addEventListener("DOMContentLoaded",()=>{document.getElementById("device-timeline-container")&&window.innerWidth>768&&(window.deviceTimeline=new DeviceTimeline("device-timeline-container"))});class DeviceTimelineMobile{constructor(e){this.container=document.getElementById(e),this.container&&this.init()}async init(){try{const e=await this.fetchData();if(e.error){console.error("Failed to fetch mobile timeline data:",e.message);return}this.renderMobileCards(e)}catch(e){console.error("Error initializing DeviceTimelineMobile:",e)}}async fetchData(){const e=await fetch("/api/scheduler/device_timeline?hours=24");if(!e.ok)throw new Error("Failed to fetch timeline data");return await e.json()}renderMobileCards(e){const t=new Map;e.groups.forEach(i=>{t.set(i.id,{id:i.id,name:i.content,className:i.className,items:[]})}),e.items.forEach(i=>{t.has(i.group)&&t.get(i.group).items.push(i)});const n=Array.from(t.entries()).map(([i,s])=>{const c=s.items.length,l=s.items.filter(a=>a.className.includes("scheduled")).length,r=s.items.filter(a=>a.className.includes("completed")).length;return`
        <div class="mobile-device-card ${s.className}" data-device-id="${i}">
          <div class="card-header">
            <span class="device-name">${s.name}</span>
            <span class="badge badge-info">${c} events</span>
          </div>
          <div class="card-body">
            <div class="stats">
              <span class="stat-item">
                <i class="fas fa-clock"></i> Scheduled: ${l}
              </span>
              <span class="stat-item">
                <i class="fas fa-check"></i> Runtime: ${r}
              </span>
            </div>
            <button class="btn btn-sm btn-outline-primary mt-2" 
                    onclick="if(window.deviceTimelineMobile) window.deviceTimelineMobile.showDeviceDetails('${i}')">
              View Details
            </button>
          </div>
        </div>
      `}).join("");this.container.innerHTML=n||'<div class="empty-state">No devices found.</div>'}showDeviceDetails(e){console.log("Showing details for device:",e),window.showToast&&window.showToast(`Device details: ${e}`,"info")}refresh(){this.init()}}document.addEventListener("DOMContentLoaded",()=>{document.getElementById("mobile-device-list")&&window.innerWidth<=768&&(window.deviceTimelineMobile=new DeviceTimelineMobile("mobile-device-list"))});let resizeTimer;window.addEventListener("resize",()=>{clearTimeout(resizeTimer),resizeTimer=setTimeout(()=>{const o=document.getElementById("device-timeline-container"),e=document.getElementById("mobile-device-list");window.innerWidth<=768?e&&!window.deviceTimelineMobile&&(window.deviceTimelineMobile=new DeviceTimelineMobile("mobile-device-list")):o&&!window.deviceTimeline&&(window.deviceTimeline=new DeviceTimeline("device-timeline-container"))},500)});

/**
 * DeviceTimelineMobile - Mobile-friendly card list view for device scheduler
 */
class DeviceTimelineMobile {
  constructor(containerId) {
    this.container = document.getElementById(containerId);
    if (!this.container) return;
    this.init();
  }
  
  async init() {
    try {
      const data = await this.fetchData();
      if (data.error) {
        console.error('Failed to fetch mobile timeline data:', data.message);
        return;
      }
      this.renderMobileCards(data);
    } catch (error) {
      console.error('Error initializing DeviceTimelineMobile:', error);
    }
  }
  
  async fetchData() {
    const response = await fetch('/api/scheduler/device_timeline?hours=24');
    if (!response.ok) {
      throw new Error('Failed to fetch timeline data');
    }
    return await response.json();
  }
  
  renderMobileCards(data) {
    // Group items by device
    const deviceMap = new Map();
    
    data.groups.forEach(group => {
      deviceMap.set(group.id, {
        id: group.id,
        name: group.content,
        className: group.className,
        items: []
      });
    });
    
    data.items.forEach(item => {
      if (deviceMap.has(item.group)) {
        deviceMap.get(item.group).items.push(item);
      }
    });
    
    // Generate cards HTML
    const cardsHtml = Array.from(deviceMap.entries()).map(([deviceId, device]) => {
      const itemCount = device.items.length;
      const scheduledCount = device.items.filter(i => i.className.includes('scheduled')).length;
      const completedCount = device.items.filter(i => i.className.includes('completed')).length;
      
      return `
        <div class="mobile-device-card ${device.className}" data-device-id="${deviceId}">
          <div class="card-header">
            <span class="device-name">${device.name}</span>
            <span class="badge badge-info">${itemCount} events</span>
          </div>
          <div class="card-body">
            <div class="stats">
              <span class="stat-item">
                <i class="fas fa-clock"></i> Scheduled: ${scheduledCount}
              </span>
              <span class="stat-item">
                <i class="fas fa-check"></i> Runtime: ${completedCount}
              </span>
            </div>
            <button class="btn btn-sm btn-outline-primary mt-2" 
                    onclick="if(window.deviceTimelineMobile) window.deviceTimelineMobile.showDeviceDetails('${deviceId}')">
              View Details
            </button>
          </div>
        </div>
      `;
    }).join('');
    
    this.container.innerHTML = cardsHtml || '<div class="empty-state">No devices found.</div>';
  }
  
  showDeviceDetails(deviceId) {
    console.log('Showing details for device:', deviceId);
    // Future: Show detailed modal for the device
    if (window.showToast) {
        window.showToast(`Device details: ${deviceId}`, 'info');
    }
  }
  
  refresh() {
    this.init();
  }
}

// Global initialization
document.addEventListener('DOMContentLoaded', () => {
    if (document.getElementById('mobile-device-list') && window.innerWidth <= 768) {
        window.deviceTimelineMobile = new DeviceTimelineMobile('mobile-device-list');
    }
});

// Resizing logic with debounce
let resizeTimer;
window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
        const desktopContainer = document.getElementById('device-timeline-container');
        const mobileContainer = document.getElementById('mobile-device-list');
        
        if (window.innerWidth <= 768) {
            if (mobileContainer && !window.deviceTimelineMobile) {
                window.deviceTimelineMobile = new DeviceTimelineMobile('mobile-device-list');
            }
        } else {
            if (desktopContainer && !window.deviceTimeline) {
                window.deviceTimeline = new DeviceTimeline('device-timeline-container');
            }
        }
    }, 500);
});

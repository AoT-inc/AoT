/**
 * DeviceTimeline - Desktop visualization for device-centric scheduler
 * Uses vis-timeline library
 */
class DeviceTimeline {
  constructor(containerId) {
    this.container = document.getElementById(containerId);
    if (!this.container) return;
    this.timeline = null;
    this.init();
  }
  
  async init() {
    try {
      const data = await this.fetchData();
      if (data.error) {
        console.error('Failed to fetch timeline data:', data.message);
        return;
      }
      this.render(data);
    } catch (error) {
      console.error('Error initializing DeviceTimeline:', error);
    }
  }
  
  async fetchData() {
    const response = await fetch('/api/scheduler/device_timeline?hours=24');
    return await response.json();
  }
  
  render(data) {
    const options = {
      groupOrder: (a, b) => {
        // Sort by content (device name)
        return a.content.localeCompare(b.content);
      },
      editable: false,
      margin: { item: 10, axis: 5 },
      orientation: 'top',
      zoomMin: 1000 * 60 * 60,  // 1 hour
      zoomMax: 1000 * 60 * 60 * 24 * 7,  // 1 week
      
      // Tooltip settings
      tooltip: {
        followMouse: true,
        overflowMethod: 'cap'
      },
      
      // Template for items
      template: (item) => {
        const type = item.id.split('_')[0]; // schedule or runtime
        return `
          <div class="timeline-item-content ${type}-content">
            ${item.content}
          </div>
        `;
      }
    };
    
    // Clear container if needed
    this.container.innerHTML = '';
    
    this.timeline = new vis.Timeline(
      this.container,
      new vis.DataSet(data.items),
      new vis.DataSet(data.groups),
      options
    );
    
    // Selection event
    this.timeline.on('select', (properties) => {
      if (properties.items.length > 0) {
        this.showItemDetails(properties.items[0]);
      }
    });
  }
  
  showItemDetails(itemId) {
    const item = this.timeline.itemsData.get(itemId);
    console.log('Selected item:', item);
    // Future: Show detailed modal
    if (window.showToast) {
        window.showToast(`Selected: ${item.content} (${item.start} to ${item.end || 'N/A'})`, 'info');
    }
  }
  
  refresh() {
    this.init();
  }
}

// Global initialization
document.addEventListener('DOMContentLoaded', () => {
    if (document.getElementById('device-timeline-container') && window.innerWidth > 768) {
        window.deviceTimeline = new DeviceTimeline('device-timeline-container');
    }
});

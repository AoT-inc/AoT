/**
 * AoT Learning Progress Dashboard Module
 * Manages facility AI learning phase visualization and feedback tracking
 */

var AoT_LearningDashboard = (function() {
  'use strict';

  // Private variables
  var currentData = null;
  var facilityId = null;

  /**
   * Format relative time (e.g., "2 hours ago", "3 days ago")
   */
  function formatRelativeTime(isoDateString) {
    try {
      var date = new Date(isoDateString);
      var now = new Date();
      var secondsDiff = Math.floor((now - date) / 1000);

      if (secondsDiff < 60) return 'just now';
      if (secondsDiff < 3600) {
        var mins = Math.floor(secondsDiff / 60);
        return mins + (mins === 1 ? ' min' : ' mins') + ' ago';
      }
      if (secondsDiff < 86400) {
        var hrs = Math.floor(secondsDiff / 3600);
        return hrs + (hrs === 1 ? ' hour' : ' hours') + ' ago';
      }
      var days = Math.floor(secondsDiff / 86400);
      return days + (days === 1 ? ' day' : ' days') + ' ago';
    } catch (e) {
      return 'unknown';
    }
  }

  /**
   * Get color class for progress bar based on confirmation percentage
   */
  function getProgressColorClass(confirmed, total) {
    if (total === 0) return 'bg-secondary';
    var percentage = (confirmed / total) * 100;
    if (percentage >= 80) return 'bg-success';
    if (percentage >= 50) return 'bg-info';
    if (percentage >= 25) return 'bg-warning';
    return 'bg-danger';
  }

  /**
   * Render phase badge (Learning or Calibrated)
   */
  function renderPhaseBadge(data) {
    var badgeHtml = '';
    if (data.learning_phase_active) {
      badgeHtml = '<div class="ld-phase-badge ld-phase-learning">' +
        'Learning (' + (data.days_since_onboarding || 0) + ' days)' +
        '</div>';
    } else {
      badgeHtml = '<div class="ld-phase-badge ld-phase-complete">' +
        'Calibrated' +
        '</div>';
    }
    document.getElementById('ld-phase-badge').innerHTML = badgeHtml;
  }

  /**
   * Render category progress bars
   */
  function renderProgressBars(data) {
    var container = document.getElementById('ld-progress-bars');
    var html = '';

    if (data.confirmations_by_category && Object.keys(data.confirmations_by_category).length > 0) {
      for (var category in data.confirmations_by_category) {
        if (data.confirmations_by_category.hasOwnProperty(category)) {
          var stats = data.confirmations_by_category[category];
          var confirmed = stats.confirmed || 0;
          var total = stats.total || 0;
          var percentage = total > 0 ? Math.round((confirmed / total) * 100) : 0;
          var colorClass = getProgressColorClass(confirmed, total);

          html += '<div class="ld-category-row">' +
            '<div class="ld-category-label">' + category.replace(/_/g, ' ') +
            ' <small class="text-muted">(' + confirmed + '/' + total + ')</small></div>' +
            '<div class="progress" style="height: 20px;">' +
            '<div class="progress-bar ' + colorClass + '" role="progressbar" ' +
            'style="width: ' + percentage + '%;" ' +
            'aria-valuenow="' + percentage + '" aria-valuemin="0" aria-valuemax="100">' +
            percentage + '%' +
            '</div>' +
            '</div>' +
            '</div>';
        }
      }
    } else {
      html = '<div class="text-muted small">No feedback data available</div>';
    }

    container.innerHTML = html;
  }

  /**
   * Render feedback summary
   */
  function renderFeedbackSummary(data) {
    var container = document.getElementById('ld-feedback-summary');
    var html = '';

    var lastFeedbackText = 'Never';
    if (data.last_feedback_at) {
      lastFeedbackText = formatRelativeTime(data.last_feedback_at);
    }

    html = '<div class="small">' +
      '<strong>Total Feedback:</strong> ' + (data.feedback_count_total || 0) + ' | ' +
      '<strong>Last:</strong> ' + lastFeedbackText +
      '</div>';

    container.innerHTML = html;
  }

  /**
   * Render next recommended feedback
   */
  function renderNextFeedback(data) {
    var container = document.getElementById('ld-next-feedback');

    if (data.next_most_valuable_feedback && data.next_most_valuable_feedback.parameter_name) {
      var paramName = data.next_most_valuable_feedback.parameter_name.replace(/_/g, ' ');
      var html = '<div class="ld-next-feedback">' +
        '<small class="text-muted">Next Recommended:</small> ' +
        '<strong>' + paramName + '</strong>' +
        '</div>';
      container.innerHTML = html;
      container.style.display = 'block';
    } else {
      container.style.display = 'none';
    }
  }

  /**
   * Render stalled alert
   */
  function renderStalledAlert(data) {
    var container = document.getElementById('ld-stalled-alert');

    if (data.stalled && data.stalled_since_days !== null) {
      var html = '<div class="ld-stalled-alert">' +
        '<small class="text-warning"><strong>No recent feedback</strong> for ' +
        data.stalled_since_days + ' days. ' +
        'Consider providing new observations.</small>' +
        '</div>';
      container.innerHTML = html;
      container.style.display = 'block';
    } else {
      container.style.display = 'none';
    }
  }

  /**
   * Public API: Initialize dashboard for a facility
   */
  function init(fid) {
    facilityId = fid;
    var dashboard = document.getElementById('ai-learning-dashboard');
    if (!dashboard) {
      console.warn('AoT_LearningDashboard: Container #ai-learning-dashboard not found');
      return;
    }

    fetch('/ai/facility/' + facilityId + '/learning-progress')
      .then(function(response) {
        if (!response.ok) {
          throw new Error('HTTP ' + response.status);
        }
        return response.json();
      })
      .then(function(data) {
        currentData = data;
        render(data);
        dashboard.style.display = 'block';
      })
      .catch(function(error) {
        console.error('AoT_LearningDashboard: Failed to load data', error);
        dashboard.innerHTML = '<div class="alert alert-danger" role="alert">Failed to load learning progress.</div>';
        dashboard.style.display = 'block';
      });
  }

  /**
   * Public API: Render dashboard with data
   */
  function render(data) {
    if (!data) return;
    currentData = data;

    renderPhaseBadge(data);
    renderProgressBars(data);
    renderFeedbackSummary(data);
    renderNextFeedback(data);
    renderStalledAlert(data);
  }

  /**
   * Public API: Refresh dashboard data
   */
  function refresh() {
    if (!facilityId) {
      console.warn('AoT_LearningDashboard: No facility ID set');
      return;
    }
    init(facilityId);
  }

  // Public interface
  return {
    init: init,
    render: render,
    refresh: refresh
  };
})();

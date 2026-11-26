/**
 * static/js/dashboard.js — Dashboard page logic
 *
 * Loads live metrics from /api/dashboard/metrics and
 * renders Chart.js charts from /api/dashboard/trends.
 */

let tempChart   = null;
let humidChart  = null;
let statusChart = null;
let deviceChart = null;

const CHART_DEFAULTS = {
  plugins: { legend: { labels: { color: '#8b949e', font: { size: 11 } } } },
  scales: {
    x: { ticks: { color: '#6e7681', maxTicksLimit: 8 }, grid: { color: '#21262d' } },
    y: { ticks: { color: '#6e7681' }, grid: { color: '#21262d' } }
  }
};

async function loadMetrics() {
  try {
    const r = await apiGet('/api/dashboard/metrics');

    document.getElementById('m-total').textContent   = r.total_records;
    document.getElementById('m-recent').textContent  = r.recent_records_24h;
    document.getElementById('m-searches').textContent = r.total_searches;
    document.getElementById('m-cloud').textContent   = r.cloud_records;
    document.getElementById('m-users').textContent   = r.total_users;
    document.getElementById('m-sim-count').textContent = r.simulator_readings;
    document.getElementById('m-sim-status').textContent = r.simulator_running ? '🟢 Running' : '⚫ Idle';

    // Update storage mode badge on dashboard
    const badge = document.getElementById('storage-mode-badge');
    if (badge) {
      badge.className = `badge badge-${r.storage_mode === 'supabase' ? 'cloud' : 'local'}`;
      badge.textContent = r.storage_mode.toUpperCase();
    }

    const sysStorage = document.getElementById('sys-storage');
    if (sysStorage) {
      sysStorage.textContent = r.storage_mode === 'local'
        ? '📁 Local filesystem'
        : '☁️ Supabase Storage';
    }

  } catch(e) {
    console.error('Metrics load error:', e);
  }
}

async function loadTrends() {
  try {
    const r = await apiGet('/api/dashboard/trends');
    renderTempChart(r.chart_data);
    renderHumidChart(r.chart_data);
    renderStatusChart(r.status_counts);
    renderDeviceChart(r.device_counts);
  } catch(e) {
    console.error('Trends load error:', e);
  }
}

function getLabels(data) {
  return data.map(d => {
    try { return new Date(d.timestamp).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}); }
    catch(_) { return '—'; }
  });
}

function renderTempChart(data) {
  const ctx = document.getElementById('chart-temp');
  if (!ctx) return;
  if (tempChart) tempChart.destroy();
  if (!data.length) return;
  tempChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: getLabels(data),
      datasets: [{
        label: 'Temperature (°C)',
        data: data.map(d => d.temperature),
        borderColor: '#58a6ff',
        backgroundColor: 'rgba(88,166,255,0.08)',
        tension: 0.3, fill: true, pointRadius: 2,
      }]
    },
    options: { ...CHART_DEFAULTS, responsive: true, maintainAspectRatio: false }
  });
}

function renderHumidChart(data) {
  const ctx = document.getElementById('chart-humid');
  if (!ctx) return;
  if (humidChart) humidChart.destroy();
  if (!data.length) return;
  humidChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: getLabels(data),
      datasets: [{
        label: 'Humidity (%)',
        data: data.map(d => d.humidity),
        borderColor: '#3fb950',
        backgroundColor: 'rgba(63,185,80,0.08)',
        tension: 0.3, fill: true, pointRadius: 2,
      }]
    },
    options: { ...CHART_DEFAULTS, responsive: true, maintainAspectRatio: false }
  });
}

function renderStatusChart(counts) {
  const ctx = document.getElementById('chart-status');
  if (!ctx) return;
  if (statusChart) statusChart.destroy();
  statusChart = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: ['NORMAL', 'WARNING', 'CRITICAL'],
      datasets: [{
        data: [counts.NORMAL || 0, counts.WARNING || 0, counts.CRITICAL || 0],
        backgroundColor: ['rgba(63,185,80,0.7)', 'rgba(210,153,34,0.7)', 'rgba(248,81,73,0.7)'],
        borderColor: ['#3fb950', '#d29922', '#f85149'],
        borderWidth: 1,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { color: '#8b949e', font: { size: 11 } } } }
    }
  });
}

function renderDeviceChart(counts) {
  const ctx = document.getElementById('chart-devices');
  if (!ctx) return;
  if (deviceChart) deviceChart.destroy();
  const labels = Object.keys(counts);
  const values = Object.values(counts);
  deviceChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: 'Readings',
        data: values,
        backgroundColor: 'rgba(88,166,255,0.5)',
        borderColor: '#58a6ff',
        borderWidth: 1,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: '#6e7681' }, grid: { color: '#21262d' } },
        y: { ticks: { color: '#6e7681' }, grid: { color: '#21262d' } }
      }
    }
  });
}

// Auto-refresh every 30 seconds
document.addEventListener('DOMContentLoaded', function() {
  loadMetrics();
  loadTrends();
  setInterval(() => { loadMetrics(); loadTrends(); }, 30000);
});

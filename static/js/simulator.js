/**
 * static/js/simulator.js — Sensor monitoring page
 *
 * Controls: start/stop simulator, generate single reading, refresh table.
 */

let simRunning = false;
let pollInterval = null;

async function startSimulator() {
  const interval = parseInt(document.getElementById('sim-interval').value) || 5;
  const device   = document.getElementById('sim-device').value;
  try {
    const r = await apiPost('/api/simulator/start', { interval, device_id: device || null });
    simRunning = true;
    updateSimUI(true, r.interval);
    showToast(`Simulator started (${r.interval}s interval)`, 'success');
    startPoll();
  } catch(e) {
    showToast(e.message, 'error');
  }
}

async function stopSimulator() {
  try {
    const r = await apiPost('/api/simulator/stop', {});
    simRunning = false;
    updateSimUI(false);
    showToast(`Simulator stopped. Total readings: ${r.readings_generated}`, 'info');
    stopPoll();
  } catch(e) {
    showToast(e.message, 'error');
  }
}

async function generateOne() {
  const device = document.getElementById('sim-device').value;
  try {
    const r = await apiPost('/api/simulator/generate', { device_id: device || null, ingest: true });
    showToast(`Generated reading for ${r.reading.device_id}`, 'success');
    refreshReadings();
  } catch(e) {
    showToast(e.message, 'error');
  }
}

async function refreshReadings() {
  const tbody = document.getElementById('readings-table');
  try {
    const r = await apiGet('/api/records?per_page=20');
    if (!r.records.length) {
      tbody.innerHTML = '<tr><td colspan="7"><div class="empty-state"><div class="empty-icon">📡</div><h3>No readings yet</h3><p>Start the simulator or click "Generate Single Reading".</p></div></td></tr>';
      return;
    }

    // Fetch decrypted records for display
    const rows = [];
    for (const rec of r.records.slice(0, 20)) {
      try {
        const detail = await apiGet(`/api/records/${rec.id}`);
        const d = detail.record;
        rows.push(`
          <tr>
            <td class="mono" title="${rec.id}">${rec.id.substring(0,12)}…</td>
            <td>${d.device_id || rec.device_id}</td>
            <td>${d.location || '—'}</td>
            <td>${d.temperature != null ? d.temperature.toFixed(2) : '—'}</td>
            <td>${d.humidity != null ? d.humidity.toFixed(2) : '—'}</td>
            <td>${statusBadge(d.status || 'NORMAL')}</td>
            <td style="color:var(--text-muted)">${new Date(d.timestamp || rec.created_at).toLocaleString()}</td>
          </tr>
        `);
      } catch(_) {
        rows.push(`<tr><td colspan="7" style="color:var(--text-muted)">Record ${rec.id.substring(0,8)}… (decrypt error)</td></tr>`);
      }
    }
    tbody.innerHTML = rows.join('');
  } catch(e) {
    tbody.innerHTML = `<tr><td colspan="7"><div class="alert alert-error">${e.message}</div></td></tr>`;
  }
}

function updateSimUI(running, interval) {
  const badge  = document.getElementById('sim-status-badge');
  const info   = document.getElementById('sim-info');
  const startBtn = document.getElementById('btn-start');
  const stopBtn  = document.getElementById('btn-stop');

  if (running) {
    badge.className   = 'badge badge-normal';
    badge.textContent = 'RUNNING';
    startBtn.disabled = true;
    stopBtn.disabled  = false;
    info.textContent  = `Simulator running — generating a reading every ${interval}s and encrypting to storage.`;
  } else {
    badge.className   = 'badge badge-local';
    badge.textContent = 'IDLE';
    startBtn.disabled = false;
    stopBtn.disabled  = true;
    info.textContent  = 'Simulator idle.';
  }
}

function startPoll() {
  if (pollInterval) return;
  pollInterval = setInterval(refreshReadings, 6000);
}

function stopPoll() {
  if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
}

async function checkSimStatus() {
  try {
    const r = await apiGet('/api/simulator/status');
    simRunning = r.running;
    updateSimUI(r.running, r.interval);
  } catch(_) {}
}

document.addEventListener('DOMContentLoaded', function() {
  checkSimStatus();
  refreshReadings();
});

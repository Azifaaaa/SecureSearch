/**
 * static/js/search.js — Search page logic
 */

function showTab(tab) {
  ['exact', 'range', 'combined'].forEach(t => {
    document.getElementById(`panel-${t}`).style.display = t === tab ? '' : 'none';
    document.getElementById(`tab-${t}`).style.borderBottom =
      t === tab ? '2px solid var(--accent-cyan)' : 'none';
  });
}

function toggleValue2() {
  const op = document.getElementById('range-op').value;
  document.getElementById('value2-group').style.display = op === 'between' ? '' : 'none';
}

function renderResults(containerId, data) {
  const div = document.getElementById(containerId);
  if (!data.results || !data.results.length) {
    div.innerHTML = `
      <div class="card mt-16">
        <div class="card-body">
          <div class="empty-state">
            <div class="empty-icon">🔍</div>
            <h3>No results found</h3>
            <p>Candidates checked: ${data.candidate_count || 0}</p>
          </div>
        </div>
      </div>`;
    return;
  }

  const rows = data.results.map(r => `
    <tr>
      <td class="mono">${r.record_id.substring(0,12)}…</td>
      <td>${r.device_id || '—'}</td>
      <td>${r.location || '—'}</td>
      <td>${r.temperature != null ? r.temperature.toFixed(2) : '—'}</td>
      <td>${r.humidity != null ? r.humidity.toFixed(2) : '—'}</td>
      <td>${statusBadge(r.status || 'NORMAL')}</td>
      <td style="color:var(--text-muted)">${r.timestamp ? new Date(r.timestamp).toLocaleString() : '—'}</td>
      <td><span class="badge badge-ok">✓</span></td>
    </tr>
  `).join('');

  const workflowHtml = data.workflow
    ? `<ol class="workflow-steps" style="margin-bottom:12px">${data.workflow.map(w=>`<li>${w}</li>`).join('')}</ol>`
    : '';

  div.innerHTML = `
    <div class="card mt-16">
      <div class="card-header">
        <div class="card-title">Results: ${data.result_count} match${data.result_count !== 1 ? 'es' : ''}</div>
        <span style="font-size:12px;color:var(--text-muted)">Candidates: ${data.candidate_count || data.result_count}</span>
      </div>
      <div class="card-body">
        ${workflowHtml}
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>Record ID</th><th>Device</th><th>Location</th><th>Temp °C</th><th>Humidity %</th><th>Status</th><th>Timestamp</th><th>Integrity</th></tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </div>`;
}

async function runExactSearch() {
  const field = document.getElementById('exact-field').value;
  const value = document.getElementById('exact-value').value.trim();
  if (!value) return showToast('Enter a search value', 'error');

  const div = document.getElementById('exact-results');
  div.innerHTML = '<div class="loading-state"><div class="spinner"></div> Searching…</div>';

  try {
    const r = await apiPost('/api/search/exact', { field, value });
    showToast(`Found ${r.result_count} result(s)`, r.result_count > 0 ? 'success' : 'info');
    renderResults('exact-results', r);
  } catch(e) {
    div.innerHTML = `<div class="alert alert-error">${e.message}</div>`;
  }
}

async function runRangeSearch() {
  const sensor   = document.getElementById('range-sensor').value;
  const operator = document.getElementById('range-op').value;
  const value    = parseFloat(document.getElementById('range-value').value);
  if (isNaN(value)) return showToast('Enter a numeric value', 'error');

  const body = { sensor, operator, value };
  if (operator === 'between') {
    const v2 = parseFloat(document.getElementById('range-value2').value);
    if (isNaN(v2)) return showToast('Enter a second value for Between', 'error');
    body.value2 = v2;
  }

  const div = document.getElementById('range-results');
  div.innerHTML = '<div class="loading-state"><div class="spinner"></div> Searching…</div>';

  try {
    const r = await apiPost('/api/search/range', body);
    showToast(`Found ${r.result_count} result(s)`, r.result_count > 0 ? 'success' : 'info');
    renderResults('range-results', r);
  } catch(e) {
    div.innerHTML = `<div class="alert alert-error">${e.message}</div>`;
  }
}

async function runCombinedSearch() {
  const combField  = document.getElementById('comb-field').value;
  const combValue  = document.getElementById('comb-value').value.trim();
  const combSensor = document.getElementById('comb-sensor').value;
  const combOp     = document.getElementById('comb-op').value;
  const combRValue = document.getElementById('comb-rvalue').value;

  const body = {};
  if (combField && combValue)  body.exact = { field: combField, value: combValue };
  if (combSensor && combRValue) body.range = { sensor: combSensor, operator: combOp, value: parseFloat(combRValue) };

  if (!body.exact && !body.range) return showToast('Provide at least one filter', 'error');

  const div = document.getElementById('combined-results');
  div.innerHTML = '<div class="loading-state"><div class="spinner"></div> Searching…</div>';

  try {
    const r = await apiPost('/api/search/combined', body);
    showToast(`Found ${r.result_count} result(s)`, r.result_count > 0 ? 'success' : 'info');
    renderResults('combined-results', r);
  } catch(e) {
    div.innerHTML = `<div class="alert alert-error">${e.message}</div>`;
  }
}

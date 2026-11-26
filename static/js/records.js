/**
 * static/js/records.js — Encrypted records page
 */

let currentPage = 1;

async function loadRecords(page = 1) {
  currentPage = page;
  const tbody = document.getElementById('records-table');
  const countEl = document.getElementById('records-count');
  tbody.innerHTML = '<tr><td colspan="7" class="loading-state"><div class="spinner"></div></td></tr>';

  try {
    const r = await apiGet(`/api/records?page=${page}&per_page=20`);
    if (countEl) countEl.textContent = `${r.total} total records`;

    if (!r.records.length) {
      tbody.innerHTML = '<tr><td colspan="7"><div class="empty-state"><div class="empty-icon">🗄️</div><h3>No encrypted records yet</h3><p>Start the simulator or import the dataset.</p></div></td></tr>';
      return;
    }

    tbody.innerHTML = r.records.map(rec => `
      <tr>
        <td class="mono" title="${rec.id}">${rec.id.substring(0,20)}…</td>
        <td>${rec.device_id}</td>
        <td><span class="badge badge-cloud">AES-256-GCM</span></td>
        <td>v${rec.encryption_version}</td>
        <td><span class="badge ${rec.storage_backend === 'local' ? 'badge-local' : 'badge-cloud'}">${rec.storage_backend}</span></td>
        <td style="color:var(--text-muted)">${new Date(rec.created_at).toLocaleString()}</td>
        <td>
          <button class="btn btn-ghost btn-sm" onclick="inspectRecord('${rec.id}')">🔍 Inspect</button>
          <button class="btn btn-ghost btn-sm" onclick="verifyFromTable('${rec.id}')">✅ Verify</button>
        </td>
      </tr>
    `).join('');

    renderPagination('records-pagination', r.page, r.pages, loadRecords);
  } catch(e) {
    tbody.innerHTML = `<tr><td colspan="7"><div class="alert alert-error">${e.message}</div></td></tr>`;
  }
}

async function inspectRecord(recordId) {
  const modal = document.getElementById('inspect-modal');
  const content = document.getElementById('inspect-content');
  modal.style.display = 'flex';
  content.innerHTML = '<div class="loading-state"><div class="spinner"></div></div>';

  try {
    const r = await apiGet(`/api/records/${recordId}`);
    const d = r.record;
    content.innerHTML = `
      <div style="margin-bottom:12px">
        <span class="badge badge-cloud" style="font-size:12px">AES-256-GCM</span>
        <span style="font-size:12px;color:var(--text-muted);margin-left:8px">v${r.encryption_version}</span>
      </div>
      <table style="margin-bottom:16px">
        <tbody>
          <tr><td style="color:var(--text-muted);width:120px">Record ID</td><td class="mono" style="font-size:11px">${recordId}</td></tr>
          <tr><td style="color:var(--text-muted)">Storage</td><td><span class="badge badge-${r.storage_backend === 'local' ? 'local' : 'cloud'}">${r.storage_backend}</span></td></tr>
          <tr><td style="color:var(--text-muted)">Created</td><td>${new Date(r.created_at).toLocaleString()}</td></tr>
        </tbody>
      </table>
      <h4 style="color:var(--accent-cyan);font-size:12px;margin-bottom:8px">DECRYPTED RECORD (authorized user only)</h4>
      <div class="code-block">${JSON.stringify(d, null, 2)}</div>
      <div class="alert alert-info" style="margin-top:12px;font-size:12px">
        ℹ️ This plaintext was decrypted on the server using the AES-256-GCM key. The browser received only the decrypted values — no key material was sent.
      </div>
    `;
  } catch(e) {
    content.innerHTML = `<div class="alert alert-error">${e.message}</div>`;
  }
}

async function verifyFromTable(recordId) {
  try {
    const r = await apiGet(`/api/records/${recordId}/verify`);
    const i = r.integrity;
    showToast(
      i.overall ? `✅ Record ${recordId.substring(0,8)}… integrity OK` : `❌ INTEGRITY FAIL: ${i.detail}`,
      i.overall ? 'success' : 'error',
      5000
    );
  } catch(e) {
    showToast(e.message, 'error');
  }
}

function closeInspect() {
  document.getElementById('inspect-modal').style.display = 'none';
}

// Close modal on backdrop click
document.getElementById('inspect-modal')?.addEventListener('click', function(e) {
  if (e.target === this) closeInspect();
});

document.addEventListener('DOMContentLoaded', () => loadRecords(1));

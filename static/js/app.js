/**
 * static/js/app.js — Shared utilities for all pages
 *
 * Provides:
 *   - apiGet / apiPost wrappers
 *   - Toast notification system
 *   - Auth check on page load
 *   - Active nav highlighting
 *   - Storage mode badge update
 *   - Pagination renderer
 *   - Logout helper
 */

// ── API helpers ──────────────────────────────────────────────────────────────

async function apiGet(url) {
  const resp = await fetch(url, { credentials: 'same-origin' });
  if (resp.status === 401) {
    window.location.href = '/login';
    throw new Error('Not authenticated');
  }
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);
  return data;
}

async function apiPost(url, body) {
  const resp = await fetch(url, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (resp.status === 401) {
    window.location.href = '/login';
    throw new Error('Not authenticated');
  }
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);
  return data;
}

// ── Toast notifications ──────────────────────────────────────────────────────

function showToast(message, type = 'info', duration = 3500) {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  const icons = { success: '✅', error: '❌', info: 'ℹ️' };
  toast.innerHTML = `<span>${icons[type] || 'ℹ️'}</span><span>${message}</span>`;
  container.appendChild(toast);
  setTimeout(() => { toast.remove(); }, duration);
}

// ── Logout ───────────────────────────────────────────────────────────────────

async function logout() {
  try {
    await apiPost('/api/auth/logout', {});
  } catch(e) { /* ignore */ }
  window.location.href = '/login';
}

// ── Active nav item ──────────────────────────────────────────────────────────

function highlightNav() {
  const path = window.location.pathname.replace('/', '') || 'dashboard';
  document.querySelectorAll('.nav-item[data-page]').forEach(el => {
    const page = el.getAttribute('data-page');
    if (path.includes(page)) {
      el.classList.add('active');
    } else {
      el.classList.remove('active');
    }
  });
}

// ── Storage mode badge ───────────────────────────────────────────────────────

async function updateStorageMode() {
  try {
    const r = await apiGet('/api/cloud/status');
    const mode = r.mode || 'local';
    const isCloud = mode === 'cloud';
    const cls   = isCloud ? 'cloud' : 'local';
    const label = isCloud ? 'CLOUD' : 'LOCAL';

    const sidebar = document.getElementById('sidebar-storage-badge');
    if (sidebar) {
      sidebar.className = `storage-badge ${cls}`;
      sidebar.textContent = label;
    }

    const topbar = document.getElementById('topbar-storage');
    if (topbar) {
      topbar.className = `badge badge-${cls}`;
      topbar.textContent = label;
    }
  } catch(e) { /* not critical */ }
}

// ── Current user ─────────────────────────────────────────────────────────────

async function loadUser() {
  try {
    const r = await apiGet('/api/auth/me');
    const el = document.getElementById('topbar-username');
    if (el) el.textContent = r.user.username;
  } catch(e) {
    if (window.location.pathname !== '/login' &&
        window.location.pathname !== '/register') {
      window.location.href = '/login';
    }
  }
}

// ── Pagination renderer ──────────────────────────────────────────────────────

function renderPagination(containerId, currentPage, totalPages, onPageClick) {
  const container = document.getElementById(containerId);
  if (!container) return;
  if (totalPages <= 1) { container.innerHTML = ''; return; }

  let html = '';
  for (let p = 1; p <= totalPages; p++) {
    html += `<button class="page-btn ${p === currentPage ? 'active' : ''}"
      onclick="${onPageClick.name}(${p})">${p}</button>`;
  }
  container.innerHTML = html;
}

// ── Status badge helper ──────────────────────────────────────────────────────

function statusBadge(status) {
  const cls = {
    NORMAL: 'badge-normal', WARNING: 'badge-warning', CRITICAL: 'badge-critical',
    ok: 'badge-ok', error: 'badge-error',
  }[status] || 'badge-local';
  return `<span class="badge ${cls}">${status}</span>`;
}

// ── Init ─────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', function() {
  highlightNav();
  // On non-auth pages, check user and load storage mode
  const path = window.location.pathname;
  if (path !== '/login' && path !== '/register') {
    loadUser();
    updateStorageMode();
  }
});

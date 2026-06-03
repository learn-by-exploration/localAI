'use strict';

// ── State ────────────────────────────────────────────────────────────────────
let state = {
  models: [],
  active: null,
  system: null,
  queue: null,
  currentSnippet: 'curl',
};

// ── SSE live metrics ─────────────────────────────────────────────────────────
let es = null;

function startMetricsStream() {
  if (es) es.close();
  es = new EventSource('/api/metrics/stream');
  es.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      state.system = data.system;
      state.active  = data.model;
      state.queue   = data.queue;
      updateActivePanel();
      updateSystemMetrics();
      updateGatewayStatus('ok');
    } catch (_) {}
  };
  es.onerror = () => updateGatewayStatus('error');
}

// ── Models ───────────────────────────────────────────────────────────────────
async function refreshModels() {
  try {
    const res = await fetch('/api/models');
    const data = await res.json();
    state.models = data.models || [];
    renderModelList();
  } catch (e) {
    console.error('refreshModels', e);
  }
}

function renderModelList() {
  const container = document.getElementById('model-list');
  if (!state.models.length) {
    container.innerHTML = '<div class="loading-text">No models found in registry.</div>';
    return;
  }

  container.innerHTML = state.models.map(m => {
    const isActive = state.active?.model_id === m.id;
    const profileTps = m.profile ? `${m.profile.tokens_per_sec.toFixed(1)} t/s` : '';
    const vramStr = m.vram_required_mb ? `${(m.vram_required_mb / 1024).toFixed(1)}GB VRAM` : '';
    const ctxStr = `${(m.context_length / 1000).toFixed(0)}k ctx`;

    return `
      <div class="model-card ${isActive ? 'is-active' : ''}">
        <div class="mc-name" title="${m.name}">${m.name}</div>
        <div class="mc-meta">
          <span class="badge">${m.runner}</span>
          <span class="badge badge-role">${m.role}</span>
          <span class="badge badge-priority">${m.priority}</span>
        </div>
        <div class="mc-stats">
          ${[ctxStr, vramStr, profileTps].filter(Boolean).join(' · ')}
        </div>
        <div class="mc-actions">
          ${isActive
            ? '<button class="btn btn-xs btn-danger" onclick="stopModel()">Stop</button>'
            : `<button class="btn btn-xs btn-primary" onclick="loadModel('${m.id}')">Load</button>`
          }
          ${isActive
            ? '<button class="btn btn-xs btn-secondary" onclick="profileModel()">Benchmark</button>'
            : ''
          }
        </div>
      </div>
    `;
  }).join('');
}

// ── Active panel ─────────────────────────────────────────────────────────────
function updateActivePanel() {
  const a = state.active;
  if (!a || !a.model_id) {
    document.querySelector('.am-name').textContent = 'No model loaded';
    document.getElementById('am-runner').textContent   = '—';
    document.getElementById('am-role').textContent     = '—';
    document.getElementById('am-priority').textContent = '—';
    document.getElementById('stat-idle').textContent   = '—';
    document.getElementById('stat-ctx').textContent    = '—';
    document.getElementById('btn-stop').disabled = true;
    document.getElementById('btn-profile').disabled = true;
    return;
  }

  document.querySelector('.am-name').textContent        = a.model_name || a.model_id;
  document.getElementById('am-runner').textContent      = a.runner || '—';
  document.getElementById('am-role').textContent        = a.role || '—';
  document.getElementById('am-priority').textContent    = a.priority || '—';
  document.getElementById('stat-ctx').textContent       = a.context_length
    ? `${(a.context_length / 1000).toFixed(0)}k`
    : '—';
  document.getElementById('stat-idle').textContent      = a.idle_seconds != null
    ? formatIdle(a.idle_seconds)
    : '—';
  document.getElementById('btn-stop').disabled    = false;
  document.getElementById('btn-profile').disabled = false;

  // Reload model list to refresh active state
  renderModelList();
}

function updateActiveProfile(profileData) {
  if (!profileData) return;
  document.getElementById('stat-tps').textContent     = `${profileData.tokens_per_sec.toFixed(1)} t/s`;
  document.getElementById('stat-latency').textContent = `${profileData.first_token_latency_ms.toFixed(0)}ms`;
}

// ── System metrics ────────────────────────────────────────────────────────────
function updateSystemMetrics() {
  const s = state.system;
  const q = state.queue;
  if (!s) return;

  setBar('bar-vram', s.vram_percent, `metric-vram`,
    s.vram_used_mb != null
      ? `${s.vram_used_mb}MB / ${s.vram_total_mb || '?'}MB (${s.vram_percent || '?'}%)`
      : 'N/A');

  setBar('bar-ram', s.ram_percent, 'metric-ram',
    `${(s.ram_used_mb / 1024).toFixed(1)}GB / ${(s.ram_total_mb / 1024).toFixed(1)}GB (${s.ram_percent}%)`);

  setBar('bar-cpu', s.cpu_percent, 'metric-cpu', `${s.cpu_percent?.toFixed(1)}%`);

  document.getElementById('metric-gpu-temp').textContent =
    s.gpu_temp != null ? `${s.gpu_temp}°C` : 'N/A';

  if (q) {
    document.getElementById('metric-requests').textContent =
      `${q.active} active${q.queued > 0 ? `, ${q.queued} queued` : ''}`;
    document.getElementById('metric-processed').textContent = q.total_processed;
  }
}

function setBar(barId, percent, labelId, text) {
  const bar = document.getElementById(barId);
  const pct = percent ?? 0;
  bar.style.width = `${Math.min(pct, 100)}%`;
  bar.classList.toggle('warn',   pct > 70 && pct <= 90);
  bar.classList.toggle('danger', pct > 90);
  document.getElementById(labelId).textContent = text;
}

// ── Model actions ─────────────────────────────────────────────────────────────
async function loadModel(modelId) {
  showToast(`Loading ${modelId}…`, 'info');
  try {
    const res = await fetch('/api/models/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model_id: modelId }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Failed');
    showToast(`${modelId} loaded`, 'ok');
    await refreshModels();
  } catch (e) {
    showToast(`Error: ${e.message}`, 'error');
  }
}

async function stopModel() {
  try {
    await fetch('/api/models/stop', { method: 'POST' });
    showToast('Model stopped', 'ok');
    state.active = null;
    updateActivePanel();
    await refreshModels();
  } catch (e) {
    showToast(`Error: ${e.message}`, 'error');
  }
}

async function profileModel() {
  const modelId = state.active?.model_id;
  if (!modelId) return;
  showToast('Benchmarking…', 'info');
  try {
    const res = await fetch(`/api/models/${modelId}/profile`, { method: 'POST' });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    updateActiveProfile(data);
    showToast(`${data.tokens_per_sec.toFixed(1)} tokens/sec`, 'ok');
    await refreshModels();
  } catch (e) {
    showToast(`Benchmark failed: ${e.message}`, 'error');
  }
}

// ── Snippets ──────────────────────────────────────────────────────────────────
const SNIPPETS = {
  curl: `curl http://localhost:8080/v1/chat/completions \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "active",
    "messages": [{"role":"user","content":"Hello!"}],
    "stream": true
  }'`,

  python: `from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key="local"  # not checked
)

response = client.chat.completions.create(
    model="active",
    messages=[{"role": "user", "content": "Hello!"}],
    stream=True,
)

for chunk in response:
    print(chunk.choices[0].delta.content or "", end="", flush=True)`,

  openwebui: `# In Open WebUI settings:
# Admin Panel → Settings → Connections → OpenAI API

Base URL:  http://localhost:8080/v1
API Key:   local

# Then select any model from the gateway in the chat UI.`,

  continue: `# In ~/.continue/config.json:

{
  "models": [
    {
      "title": "Local AI Gateway",
      "provider": "openai",
      "model": "qwen-coder-fast",
      "apiBase": "http://localhost:8080/v1",
      "apiKey": "local"
    }
  ]
}`,
};

function showSnippet(name) {
  state.currentSnippet = name;
  document.querySelectorAll('.snip-tab').forEach(t => {
    t.classList.toggle('active', t.textContent.toLowerCase() === name);
  });
  document.getElementById('snippet-code').textContent = SNIPPETS[name] || '';
}

function copySnippet() {
  navigator.clipboard.writeText(SNIPPETS[state.currentSnippet] || '').then(() => {
    showToast('Copied!', 'ok');
  });
}

// ── Status ────────────────────────────────────────────────────────────────────
function updateGatewayStatus(status) {
  const el = document.getElementById('gateway-status');
  el.className = `status-pill status-${status}`;
  el.textContent = { ok: 'connected', loading: 'connecting…', error: 'offline' }[status];
}

// ── Toast ─────────────────────────────────────────────────────────────────────
let toastTimer = null;

function showToast(msg, type) {
  let toast = document.getElementById('toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'toast';
    toast.style.cssText = `
      position:fixed; bottom:24px; right:24px; padding:10px 18px;
      border-radius:8px; font-size:13px; font-weight:600;
      color:#fff; z-index:999; transition:opacity .3s;
    `;
    document.body.appendChild(toast);
  }
  const colors = { ok: '#43d08a', error: '#f04747', info: '#7c6af5' };
  toast.style.background = colors[type] || colors.info;
  toast.style.opacity = '1';
  toast.textContent = msg;
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.style.opacity = '0'; }, 3000);
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function formatIdle(seconds) {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  return `${Math.floor(seconds / 3600)}h`;
}

// ── Init ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  showSnippet('curl');
  refreshModels();
  startMetricsStream();

  // Refresh model list every 15s
  setInterval(refreshModels, 15000);
});

/* ── State ──────────────────────────────────────────────────────────────── */
let currentCoffeeData = null;
let currentRecommendation = null;
let editingBeanId = null;
let setupEditingId = null;
let cachedSetups = [];

/* ── Helpers ────────────────────────────────────────────────────────────── */
function $(id) { return document.getElementById(id); }

function showPanel(id) {
  ['scan-idle', 'scan-loading', 'scan-results', 'scan-success'].forEach(p => {
    const el = $(p);
    el && el.classList.toggle('hidden', p !== id);
  });
}

let _toastTimer = null;
function showToast(msg, duration = 2800) {
  const t = $('toast');
  t.textContent = msg;
  t.classList.remove('hidden');
  if (_toastTimer) clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => t.classList.add('hidden'), duration);
}

/* ── Tab navigation ─────────────────────────────────────────────────────── */
document.querySelectorAll('.nav-item').forEach(btn => {
  btn.addEventListener('click', () => {
    const tabId = btn.dataset.tab;
    document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(tabId).classList.add('active');
    if (tabId === 'tab-settings') {
      loadSetups();
      loadSettings();
    }
    if (tabId === 'tab-logs') loadLogs();
  });
});

/* ── Scan flow ──────────────────────────────────────────────────────────── */
const installHint = $('install-hint');
const isIos = /iP(ad|hone|od)/.test(navigator.userAgent);
const isStandalone = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone;
if (installHint && (isIos || window.location.protocol !== 'https:') && !isStandalone) {
  installHint.hidden = false;
}

$('file-input').addEventListener('change', async (e) => {
  const file = e.target.files?.[0];
  if (!file) return;
  e.target.value = '';          // reset so same file can be re-selected

  showPanel('scan-loading');

  const form = new FormData();
  form.append('file', file);

  try {
    const res = await fetch('/api/analyze', { method: 'POST', body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Analysis failed');

    currentCoffeeData   = data.coffee_data;
    currentRecommendation = data.recommendation;

    // Coffee card
    $('result-name').textContent    = currentCoffeeData.name    || '—';
    $('result-roaster').textContent = currentCoffeeData.roaster || '—';

    const chipsEl = $('coffee-chips');
    chipsEl.innerHTML = '';
    const chipFields = [
      currentCoffeeData.origin,
      currentCoffeeData.process,
      currentCoffeeData.roast_level,
      currentCoffeeData.roast_date ? `Roasted ${currentCoffeeData.roast_date}` : null,
    ];
    chipFields.forEach(v => {
      if (v && v !== 'Unknown') {
        const span = document.createElement('span');
        span.className = 'chip';
        span.textContent = v;
        chipsEl.appendChild(span);
      }
    });

    $('recommendation-text').textContent = currentRecommendation || '—';

    showPanel('scan-results');
  } catch (err) {
    showPanel('scan-idle');
    showToast('❌ ' + (err.message || 'Something went wrong'));
  }
});

$('btn-scan-again').addEventListener('click', () => {
  currentCoffeeData = null;
  currentRecommendation = null;
  showPanel('scan-idle');
});

$('btn-new-scan').addEventListener('click', () => showPanel('scan-idle'));

/* ── Logs ──────────────────────────────────────────────────────────────── */
$('btn-refresh-logs').addEventListener('click', () => loadLogs());
$('btn-add-log').addEventListener('click', () => openRecordEditor());
$('btn-save-record').addEventListener('click', () => saveRecordFromForm());
$('btn-cancel-record').addEventListener('click', () => closeRecordEditor());
$('setup-select').addEventListener('change', (event) => selectSetup(event.target.value));
$('btn-manage-setups').addEventListener('click', () => openSetupManager());
$('btn-save-setup').addEventListener('click', () => saveSetupFromForm());
$('btn-cancel-setup').addEventListener('click', () => closeSetupManager());

async function loadLogs() {
  const list = $('logs-list');
  list.innerHTML = '<div class="logs-empty">Loading saved beans…</div>';

  try {
    const response = await fetch('/api/logs?limit=20');
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Failed to load beans');

    const entries = data.entries || [];
    if (!entries.length) {
      list.innerHTML = '<div class="logs-empty">No saved beans yet. Scan a bag and save feedback to populate this view.</div>';
      return;
    }

    list.innerHTML = '';
    entries.forEach(entry => {
      const card = document.createElement('article');
      card.className = 'log-card';

      const latest = entry.latest_log;
      const logsCount = Number(entry.logs_count || 0);
      const hasLatest = Boolean(latest);

      const latestHtml = hasLatest
        ? `
          <div class="log-grid">
            <div><span class="log-label">Grind</span><span class="log-value">${escapeHtml(latest.grind_setting)}</span></div>
            <div><span class="log-label">Dose</span><span class="log-value">${escapeHtml(String(latest.dose_g))}g</span></div>
            <div><span class="log-label">Yield</span><span class="log-value">${escapeHtml(String(latest.yield_g))}g</span></div>
            <div><span class="log-label">Time</span><span class="log-value">${escapeHtml(String(latest.time_s))}s</span></div>
          </div>
          <div class="log-foot">
            <span>${escapeHtml(latest.grinder)}</span>
            <span>${escapeHtml(latest.machine)}</span>
            <span>${escapeHtml(new Date(latest.created_at).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }))}</span>
          </div>
          ${latest.tasting_notes ? `<p class="log-notes">${escapeHtml(latest.tasting_notes)}</p>` : ''}
        `
        : '<div class="logs-empty logs-empty-compact">No dial-in log saved yet for this bean.</div>';

      card.innerHTML = `
        <div class="log-card-head">
          <div>
            <h3 class="log-title">${escapeHtml(entry.roaster)} ${escapeHtml(entry.bean_name)}</h3>
            <p class="log-meta">${escapeHtml(entry.origin)} • ${escapeHtml(entry.process)} • ${escapeHtml(entry.roast_level)}</p>
          </div>
          <span class="log-rating">${escapeHtml(String(logsCount))} log${logsCount === 1 ? '' : 's'}</span>
        </div>
        <div class="log-actions">
          <button class="btn btn-sm btn-ghost js-edit-record">Edit</button>
          <button class="btn btn-sm btn-ghost js-delete-record">Delete</button>
        </div>
        ${latestHtml}
      `;
      card.querySelector('.js-edit-record')?.addEventListener('click', () => openRecordEditor(entry));
      card.querySelector('.js-delete-record')?.addEventListener('click', () => deleteRecord(entry));
      list.appendChild(card);
    });
  } catch (err) {
    list.innerHTML = `<div class="logs-empty">${escapeHtml(err.message || 'Could not load beans')}</div>`;
  }
}

function openRecordEditor(entry = null) {
  editingBeanId = entry ? Number(entry.bean_id) : null;
  $('log-editor-title').textContent = editingBeanId ? 'Edit Record' : 'Add Record';

  $('form-roaster').value = entry?.roaster || '';
  $('form-name').value = entry?.bean_name || '';
  $('form-origin').value = entry?.origin || '';
  $('form-process').value = entry?.process || '';
  $('form-roast-level').value = entry?.roast_level || '';
  $('form-grind-setting').value = entry?.latest_log?.grind_setting || '';
  $('form-dose').value = entry?.latest_log?.dose_g ?? '';
  $('form-yield').value = entry?.latest_log?.yield_g ?? '';
  $('form-time').value = entry?.latest_log?.time_s ?? '';
  $('form-rating').value = entry?.latest_log?.rating ?? '';
  $('form-notes').value = entry?.latest_log?.tasting_notes || '';

  $('log-editor-dialog').classList.remove('hidden');
}

function closeRecordEditor() {
  editingBeanId = null;
  $('log-editor-dialog').classList.add('hidden');
}

async function saveRecordFromForm() {
  const payload = {
    roaster: $('form-roaster').value.trim(),
    name: $('form-name').value.trim(),
    origin: $('form-origin').value.trim(),
    process: $('form-process').value.trim(),
    roast_level: $('form-roast-level').value.trim(),
    log: {
      grind_setting: $('form-grind-setting').value.trim() || null,
      dose_g: parseNullableNumber($('form-dose').value),
      yield_g: parseNullableNumber($('form-yield').value),
      time_s: parseNullableInt($('form-time').value),
      rating: parseNullableInt($('form-rating').value),
      tasting_notes: $('form-notes').value.trim() || null,
    },
  };

  if (!payload.roaster || !payload.name || !payload.origin || !payload.process || !payload.roast_level) {
    showToast('Please fill bean details first');
    return;
  }

  try {
    const url = editingBeanId ? `/api/logs/${editingBeanId}` : '/api/logs/manual';
    const method = editingBeanId ? 'PUT' : 'POST';
    const res = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Save failed');

    closeRecordEditor();
    await loadLogs();
    showToast('✅ Record saved');
  } catch (err) {
    showToast('❌ ' + (err.message || 'Could not save record'));
  }
}

async function deleteRecord(entry) {
  const beanId = Number(entry?.bean_id);
  if (!beanId) return;
  if (!window.confirm(`Delete ${entry.roaster} ${entry.bean_name}?`)) return;

  try {
    const res = await fetch(`/api/logs/${beanId}`, { method: 'DELETE' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Delete failed');
    await loadLogs();
    showToast('✅ Record deleted');
  } catch (err) {
    showToast('❌ ' + (err.message || 'Could not delete record'));
  }
}

function parseNullableNumber(value) {
  const v = String(value ?? '').trim();
  if (!v) return null;
  const n = Number.parseFloat(v);
  return Number.isNaN(n) ? null : n;
}

function parseNullableInt(value) {
  const v = String(value ?? '').trim();
  if (!v) return null;
  const n = Number.parseInt(v, 10);
  return Number.isNaN(n) ? null : n;
}

/* ── Feedback: "It worked!" ─────────────────────────────────────────────── */
$('btn-worked').addEventListener('click', () => {
  $('grind-input').value = '';
  $('grind-dialog').classList.remove('hidden');
});

$('btn-save-grind').addEventListener('click', () => saveFeedback($('grind-input').value.trim()));
$('btn-skip-grind').addEventListener('click', () => saveFeedback(null));

async function saveFeedback(actualGrind) {
  $('grind-dialog').classList.add('hidden');
  if (!currentCoffeeData || !currentRecommendation) return;

  try {
    const res = await fetch('/api/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        coffee_data:    currentCoffeeData,
        recommendation: currentRecommendation,
        actual_grind:   actualGrind || null,
        dose_g:         currentCoffeeData.preferred_dose_g ?? null,
      }),
    });
    if (!res.ok) {
      const d = await res.json();
      throw new Error(d.detail || 'Save failed');
    }
    showPanel('scan-success');
  } catch (err) {
    showToast('❌ ' + (err.message || 'Could not save'));
  }
}

/* ── Settings ───────────────────────────────────────────────────────────── */
async function loadSettings() {
  try {
    const [eqRes, setRes] = await Promise.all([
      fetch('/api/equipment'),
      fetch('/api/settings'),
    ]);
    const eq  = await eqRes.json();
    const set = await setRes.json();

    if (eq.grinder) {
      $('grinder-brand').value = eq.grinder.brand || '';
      $('grinder-model').value = eq.grinder.model || '';
    }
    if (eq.machine) {
      $('machine-brand').value = eq.machine.brand || '';
      $('machine-model').value = eq.machine.model || '';
    }
    $('dose-input').value   = set.dose_g            ?? '';
    $('offset-input').value = set.grind_offset_clicks ?? '';
  } catch {
    showToast('⚠️ Could not load settings');
  }
}

async function loadSetups() {
  const select = $('setup-select');
  if (!select) return;

  try {
    const res = await fetch('/api/setups');
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Could not load setups');

    const activeId = Number(data.active_setup_id);
    cachedSetups = Array.isArray(data.setups) ? data.setups : [];

    select.innerHTML = '';
    cachedSetups.forEach(setup => {
      const option = document.createElement('option');
      option.value = String(setup.id);
      option.textContent = setup.name;
      option.selected = Number(setup.id) === activeId;
      select.appendChild(option);
    });

    renderSetupManagerList(activeId);
  } catch (err) {
    showToast('⚠️ ' + (err.message || 'Could not load setups'));
  }
}

function renderSetupManagerList(activeId = null) {
  const list = $('setup-manager-list');
  if (!list) return;

  if (!cachedSetups.length) {
    list.innerHTML = '<div class="logs-empty logs-empty-compact">No setups yet.</div>';
    return;
  }

  list.innerHTML = '';
  cachedSetups.forEach(setup => {
    const item = document.createElement('div');
    item.className = 'setup-item';
    const isActive = activeId !== null ? Number(setup.id) === Number(activeId) : false;
    item.innerHTML = `
      <div class="setup-item-main">
        <div class="setup-item-name">${escapeHtml(setup.name)} ${isActive ? '<span class="setup-active-pill">Active</span>' : ''}</div>
        <div class="setup-item-meta">${escapeHtml(setup.machine.brand)} ${escapeHtml(setup.machine.model)} • ${escapeHtml(setup.grinder.brand)} ${escapeHtml(setup.grinder.model)}</div>
      </div>
      <div class="setup-item-actions">
        <button class="btn btn-sm btn-ghost js-setup-edit">Edit</button>
        <button class="btn btn-sm btn-ghost js-setup-delete">Delete</button>
      </div>
    `;
    item.querySelector('.js-setup-edit')?.addEventListener('click', () => populateSetupForm(setup));
    item.querySelector('.js-setup-delete')?.addEventListener('click', () => deleteSetup(setup));
    list.appendChild(item);
  });
}

async function selectSetup(setupId) {
  const parsed = Number(setupId);
  if (!parsed) return;

  try {
    const res = await fetch('/api/setups/select', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ setup_id: parsed }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Could not switch setup');

    await Promise.all([loadSetups(), loadSettings()]);
    showToast('✅ Setup switched');
  } catch (err) {
    showToast('❌ ' + (err.message || 'Could not switch setup'));
  }
}

function openSetupManager() {
  setupEditingId = null;
  clearSetupForm();
  $('setup-manager-title').textContent = 'Manage Setups';
  $('setup-manager-dialog').classList.remove('hidden');
  const currentActive = Number($('setup-select').value || 0);
  renderSetupManagerList(currentActive || null);
}

function closeSetupManager() {
  $('setup-manager-dialog').classList.add('hidden');
  setupEditingId = null;
}

function clearSetupForm() {
  $('setup-form-name').value = '';
  $('setup-form-grinder-brand').value = '';
  $('setup-form-grinder-model').value = '';
  $('setup-form-machine-brand').value = '';
  $('setup-form-machine-model').value = '';
  $('setup-form-machine-type').value = 'espresso_machine';
}

function populateSetupForm(setup) {
  setupEditingId = Number(setup.id);
  $('setup-manager-title').textContent = `Edit Setup: ${setup.name}`;
  $('setup-form-name').value = setup.name || '';
  $('setup-form-grinder-brand').value = setup.grinder?.brand || '';
  $('setup-form-grinder-model').value = setup.grinder?.model || '';
  $('setup-form-machine-brand').value = setup.machine?.brand || '';
  $('setup-form-machine-model').value = setup.machine?.model || '';
  $('setup-form-machine-type').value = setup.machine?.type || 'espresso_machine';
}

async function saveSetupFromForm() {
  const payload = {
    name: $('setup-form-name').value.trim(),
    grinder_brand: $('setup-form-grinder-brand').value.trim(),
    grinder_model: $('setup-form-grinder-model').value.trim(),
    machine_brand: $('setup-form-machine-brand').value.trim(),
    machine_model: $('setup-form-machine-model').value.trim(),
    machine_type: $('setup-form-machine-type').value.trim() || 'espresso_machine',
  };

  if (!payload.name || !payload.grinder_brand || !payload.grinder_model || !payload.machine_brand || !payload.machine_model) {
    showToast('Please fill all setup fields');
    return;
  }

  try {
    const url = setupEditingId ? `/api/setups/${setupEditingId}` : '/api/setups';
    const method = setupEditingId ? 'PUT' : 'POST';
    const res = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Could not save setup');

    setupEditingId = null;
    clearSetupForm();
    $('setup-manager-title').textContent = 'Manage Setups';
    await Promise.all([loadSetups(), loadSettings()]);
    showToast('✅ Setup saved');
  } catch (err) {
    showToast('❌ ' + (err.message || 'Could not save setup'));
  }
}

async function deleteSetup(setup) {
  if (!setup || !setup.id) return;
  if (!window.confirm(`Delete setup "${setup.name}"?`)) return;

  try {
    const res = await fetch(`/api/setups/${setup.id}`, { method: 'DELETE' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Could not delete setup');

    await Promise.all([loadSetups(), loadSettings()]);
    showToast('✅ Setup deleted');
  } catch (err) {
    showToast('❌ ' + (err.message || 'Could not delete setup'));
  }
}

$('btn-save-grinder').addEventListener('click', async () => {
  const brand = $('grinder-brand').value.trim();
  const model = $('grinder-model').value.trim();
  if (!brand || !model) { showToast('Enter brand and model'); return; }
  await putJson('/api/equipment/grinder', { brand, model }, 'Grinder saved ✓');
});

$('btn-save-machine').addEventListener('click', async () => {
  const brand = $('machine-brand').value.trim();
  const model = $('machine-model').value.trim();
  if (!brand || !model) { showToast('Enter brand and model'); return; }
  await putJson('/api/equipment/machine', { brand, model }, 'Machine saved ✓');
});

$('btn-save-dose').addEventListener('click', async () => {
  const val = parseFloat($('dose-input').value);
  if (!val || val <= 0) { showToast('Enter a valid dose'); return; }
  await putJson('/api/settings/dose', { dose_g: val }, `Dose set to ${val}g ✓`);
});

$('btn-save-offset').addEventListener('click', async () => {
  const raw = $('offset-input').value.trim();
  if (raw === '') { showToast('Enter an offset value'); return; }
  const val = parseFloat(raw);
  if (isNaN(val)) { showToast('Enter a valid number'); return; }
  await putJson('/api/settings/grind-offset', { offset_clicks: val }, `Offset set to ${val > 0 ? '+' : ''}${val} clicks ✓`);
});

async function putJson(url, body, successMsg) {
  try {
    const res = await fetch(url, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const d = await res.json();
      throw new Error(d.detail || 'Update failed');
    }
    showToast('✅ ' + successMsg);
  } catch (err) {
    showToast('❌ ' + (err.message || 'Request failed'));
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

/* ── Service worker registration ────────────────────────────────────────── */
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => {});
  });
}

loadSetups();

/* ── State ──────────────────────────────────────────────────────────────── */
let currentCoffeeData = null;
let currentRecommendation = null;

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
    if (tabId === 'tab-settings') loadSettings();
  });
});

/* ── Scan flow ──────────────────────────────────────────────────────────── */
const installHint = $('install-hint');
if (installHint && window.location.protocol !== 'https:' && window.location.hostname !== 'localhost') {
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

/* ── Service worker registration ────────────────────────────────────────── */
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => {});
  });
}

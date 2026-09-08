/* ── Version ────────────────────────────────────────────────────────────── */
/* The version this bundle was loaded with, read from its own script tag.
   Deliberately self-reported: if a stale index.html is served from the
   service-worker cache, this reports that stale number, which is exactly
   what makes the chip able to answer "did my deploy actually land?". */
const BUNDLE_VERSION = (() => {
  try {
    return Number(new URL(document.currentScript.src).searchParams.get('v')) || null;
  } catch {
    return null;
  }
})();
let serverAssetVersion = null;
let engineVersion = null;

/* ── State ──────────────────────────────────────────────────────────────── */
/* What's on the bench. currentBeanId is set when the coffee exists in the
   library, which is what lets the engine work from the real row. */
let currentBeanId = null;
let currentCoffeeData = null;
let currentRecommendation = null;
// The engine's structured numbers. Read these directly rather than parsing
// them back out of the prose — the prose is an explanation, not a source.
let currentRecipe = null;
let currentRecommendationId = null;
/* The active setup, mirrored into the header chip. */
let activeSetupId = null;
let activeSetupName = '';
let activeSetupMethod = null;
/* Navigation */
let currentTab = 'tab-home';
let editingBeanId = null;
let setupEditingId = null;
let equipmentEditingId = null;
let cachedSetups = [];
let cachedEquipmentLibrary = { grinders: [], machines: [] };

/* ── Helpers ────────────────────────────────────────────────────────────── */
function $(id) { return document.getElementById(id); }

/* Bind a listener only if the element exists. During a deploy a fresh app.js
   can briefly run against a cached older index.html (or the reverse); without
   this an unguarded addEventListener on a missing id throws and takes the
   whole script — and therefore the whole app — down blank. */
function on(id, event, handler) {
  const el = $(id);
  if (el) el.addEventListener(event, handler);
  return el;
}

/* Basket capacity shifts with roast: a dense dark roast packs less mass into the
   same basket than a fluffy light roast. These are the midpoints of the ranges
   that fit the user's basket (dark ~16-17 g, light ~18-19 g). Order matters —
   the more specific "medium-dark" test must come before the bare "dark" test. */
const DOSE_BY_ROAST = [
  { test: /medium[-\s]?dark/i, dose: 17 },
  { test: /dark|french|italian|vienna/i, dose: 16.5 },
  { test: /light|blonde|blond|cinnamon|nordic|scandinav/i, dose: 18.5 },
  { test: /medium/i, dose: 17.5 },
];

function suggestedDoseForRoast(roastLevel, fallback) {
  const text = String(roastLevel || '').trim();
  if (text) {
    for (const rule of DOSE_BY_ROAST) {
      if (rule.test.test(text)) return rule.dose;
    }
  }
  return fallback;
}

function setScanDose(value, { fromRoast = false, roastLevel = '' } = {}) {
  const rounded = Math.round(value * 2) / 2;
  $('scan-dose-input').value = String(rounded);
  if (currentCoffeeData) currentCoffeeData.preferred_dose_g = rounded;
  $('dose-adjust-hint').textContent = fromRoast && roastLevel
    ? `Auto-set to ${rounded} g for a ${String(roastLevel).toLowerCase()} roast. `
      + 'Adjust to what fits your basket, then tap "Update recipe".'
    : 'Adjust to what fits your basket, then tap "Update recipe".';
}

function currentScanDose() {
  const v = parseFloat($('scan-dose-input').value);
  return v > 0 ? v : null;
}

/* Data-driven rather than a hard-coded list, so adding a panel to the markup
   is enough — no parallel array to forget to update. */
function showPanel(id) {
  document.querySelectorAll('.flow-panel').forEach(el => {
    el.classList.toggle('hidden', el.id !== id);
  });
}

/* ── State transitions ──────────────────────────────────────────────────── */
/* Only these three touch the recommendation, so a stale recommendation_id
   cannot survive a recompute or be posted after a shot is logged. */
function setRecommendation(data) {
  currentRecipe = data.recipe || null;
  currentRecommendation = data.recommendation || '';
  currentRecommendationId = data.recommendation_id ?? null;
}

function clearRecommendation() {
  currentRecipe = null;
  currentRecommendation = null;
  currentRecommendationId = null;
}

function clearCoffee() {
  clearRecommendation();
  currentCoffeeData = null;
  currentBeanId = null;
}

/* ── Dialogs ────────────────────────────────────────────────────────────── */
function syncModalScrollLock() {
  const anyOpen = document.querySelector('.dialog-overlay:not(.hidden)') !== null;
  document.body.classList.toggle('modal-open', anyOpen);
}

function openDialog(id) {
  const overlay = $(id);
  if (!overlay) return;
  overlay.classList.remove('hidden');
  const body = overlay.querySelector('.dialog-body');
  if (body) body.scrollTop = 0;
  syncModalScrollLock();
}

function closeDialog(id) {
  const overlay = $(id);
  if (!overlay) return;
  overlay.classList.add('hidden');
  syncModalScrollLock();
}

let _toastTimer = null;
function showToast(msg, duration = 2800) {
  const t = $('toast');
  t.textContent = msg;
  t.classList.remove('hidden');
  if (_toastTimer) clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => t.classList.add('hidden'), duration);
}

function getApiErrorMessage(payload, fallback) {
  if (!payload) return fallback;

  const detail = payload.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;

  if (Array.isArray(detail)) {
    const joined = detail
      .map(item => {
        if (typeof item === 'string') return item;
        if (item && typeof item === 'object') {
          if (typeof item.msg === 'string') return item.msg;
          if (typeof item.message === 'string') return item.message;
        }
        return null;
      })
      .filter(Boolean)
      .join('; ');
    if (joined) return joined;
  }

  if (detail && typeof detail === 'object') {
    if (typeof detail.msg === 'string') return detail.msg;
    if (typeof detail.message === 'string') return detail.message;
  }

  if (typeof payload.message === 'string' && payload.message.trim()) return payload.message;
  return fallback;
}

/* ── Tab navigation ─────────────────────────────────────────────────────── */
const TAB_LOADERS = {
  'tab-home': () => loadRecents(),
  'tab-settings': () => { loadSetups(); loadSettings(); loadEquipmentLibrary(); loadAccount(); },
  'tab-recipe': () => {},
};

/* Switching tabs never touches coffee state — that is the point of keeping
   Recipe in the nav: you can detour to Settings and come back to your shot. */
function showTab(id, { push = true } = {}) {
  document.querySelectorAll('.tab-panel').forEach(p => {
    p.classList.toggle('active', p.id === id);
  });
  document.querySelectorAll('.nav-item').forEach(b => {
    b.classList.toggle('active', b.dataset.tab === id);
  });
  currentTab = id;
  (TAB_LOADERS[id] || (() => {}))();
  // Give the back gesture something to pop; without this it exits the app.
  if (push && history.state?.tab !== id) history.pushState({ tab: id }, '');
}

window.addEventListener('popstate', (e) => {
  showTab(e.state?.tab || 'tab-home', { push: false });
});

/* ── Scan flow ──────────────────────────────────────────────────────────── */
const installHint = $('install-hint');
const isIos = /iP(ad|hone|od)/.test(navigator.userAgent);
const isStandalone = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone;
if (installHint && (isIos || window.location.protocol !== 'https:') && !isStandalone) {
  installHint.hidden = false;
}

/* Fill the coffee card from a profile — shared by both entrances. */
function renderCoffeeCard(profile) {
  if (!profile) return;
  $('result-name').textContent = profile.name || '—';
  $('result-roaster').textContent = profile.roaster || '—';

  const chipsEl = $('coffee-chips');
  if (!chipsEl) return;
  chipsEl.innerHTML = '';
  [
    profile.origin,
    profile.process,
    profile.roast_level,
    profile.roast_date ? `Roasted ${profile.roast_date}` : null,
  ].forEach((v) => {
    if (v && v !== 'Unknown') {
      const span = document.createElement('span');
      span.className = 'chip';
      span.textContent = v;
      chipsEl.appendChild(span);
    }
  });
}

/* The single path every recompute goes through: dose change, setup switch,
   and refreshing after a shot. Sends bean_id when the coffee is in the
   library so the engine works from the real row. */
async function refreshRecommendation({ dose, silent = false } = {}) {
  if (!currentBeanId && !currentCoffeeData) return false;
  const body = currentBeanId
    ? { bean_id: currentBeanId, dose_g: dose ?? null }
    : { coffee_data: currentCoffeeData, dose_g: dose ?? null };

  try {
    const res = await fetch('/api/recommendation', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(getApiErrorMessage(data, 'Could not update recipe'));

    if (data.coffee_data) currentCoffeeData = data.coffee_data;
    renderRecipe(data);
    return true;
  } catch (err) {
    if (!silent) showToast('❌ ' + (err.message || 'Could not update recipe'));
    return false;
  }
}

/* ── Dial-in history ────────────────────────────────────────────────────── */
const BAND_LABELS = { in: 'In the band', long: 'Ran long', fast: 'Ran fast' };
const TASTE_LABELS = {
  very_sour: 'Very sour',
  sour: 'Sour',
  balanced: 'Balanced',
  bitter: 'Bitter',
  very_bitter: 'Very bitter',
};

/* One factual sentence about direction of travel, derived from the shots
   themselves — never invented, and silent when there is nothing to say. */
function historyNote(shots) {
  const measured = shots.filter((s) => s.data_quality === 'measured');
  if (!measured.length) {
    return 'No measured shots yet. Log a grind, a time and how it tasted and '
      + 'the next recommendation is computed from it rather than from theory.';
  }
  if (measured.length === 1) {
    return 'One measured shot so far — the next one is what turns a starting '
      + 'guess into a calibration.';
  }
  const [latest, previous] = measured;
  if (latest.band === 'in') return 'Your last shot landed in the target band.';
  if (latest.band && latest.band === previous.band) {
    const movedRight = latest.delta_clicks !== null
      && ((latest.band === 'long' && latest.delta_clicks > 0)
        || (latest.band === 'fast' && latest.delta_clicks < 0));
    return movedRight
      ? `Two in a row ${latest.band === 'long' ? 'ran long' : 'ran fast'} — `
        + 'the last change went the right way, just not far enough.'
      : `Two in a row ${latest.band === 'long' ? 'ran long' : 'ran fast'}.`;
  }
  return '';
}

function renderHistory(shots) {
  const section = $('dial-in-history');
  const rows = $('history-rows');
  if (!section || !rows) return;

  if (!shots.length) { section.hidden = true; return; }
  section.hidden = false;
  rows.innerHTML = '';

  shots.forEach((shot) => {
    const measured = shot.data_quality === 'measured';
    const row = document.createElement('div');
    row.className = 'history-row' + (measured ? '' : ' is-unmeasured');
    if (shot.band) row.dataset.band = shot.band;

    const when = new Date(shot.created_at).toLocaleDateString([], {
      month: 'short', day: 'numeric',
    });
    const delta = shot.delta_clicks
      ? `<span class="history-delta">${shot.delta_clicks > 0 ? '+' : '−'}${Math.abs(shot.delta_clicks)}</span>`
      : '';
    // A shot with no measurements is shown, not hidden: it is the only place
    // you learn why it did not move the recommendation.
    const verdict = measured
      ? (shot.band
        ? `<span class="chip chip-band">${escapeHtml(BAND_LABELS[shot.band])}</span>`
        : '')
      : '<span class="chip chip-guard">Not measured</span>';

    row.innerHTML = `
      <div class="history-when">
        <span class="log-label">${escapeHtml(when)}</span>
      </div>
      <div class="log-grid history-cells">
        <div><span class="log-label">Grind</span><span class="log-value">${
          shot.grind_clicks ?? '—'}${delta}</span></div>
        <div><span class="log-label">Time</span><span class="log-value">${
          shot.time_s ? escapeHtml(String(shot.time_s)) + ' s' : '—'}</span></div>
        <div><span class="log-label">Taste</span><span class="log-value">${
          shot.taste_axis ? escapeHtml(TASTE_LABELS[shot.taste_axis] || shot.taste_axis) : '—'}</span></div>
      </div>
      <div class="history-verdict">
        ${verdict}
        ${shot.astringent ? '<span class="chip chip-guard">Drying</span>' : ''}
      </div>
    `;
    rows.appendChild(row);
  });

  const note = $('history-note');
  if (note) note.textContent = historyNote(shots);
}

async function loadHistory(beanId) {
  const section = $('dial-in-history');
  if (!beanId) { if (section) section.hidden = true; return; }
  try {
    const res = await fetch(`/api/beans/${beanId}/shots?limit=5`);
    const data = await res.json();
    if (!res.ok) throw new Error('history unavailable');
    renderHistory(data.shots || []);
  } catch {
    if (section) section.hidden = true;   // never block the recipe on this
  }
}

function setLoadingCopy(title, sub) {
  const t = $('loading-text');
  const s = $('loading-sub');
  if (t) t.textContent = title;
  if (s) s.textContent = sub;
}

/* Journey 2: pick up a coffee already in the library. */
async function openBean(entry) {
  clearCoffee();
  currentBeanId = Number(entry.bean_id);
  showTab('tab-recipe');
  setLoadingCopy('Working out your recipe…', 'Using your shots on this bag');
  showPanel('scan-loading');

  const ok = await refreshRecommendation({ dose: null });
  if (!ok) {
    clearCoffee();
    showPanel('recipe-empty');
    showTab('tab-home');
    return;
  }
  renderCoffeeCard(currentCoffeeData);
  setScanDose(Number(currentCoffeeData?.preferred_dose_g) || 16);
  loadHistory(currentBeanId);
  showPanel('recipe-view');
}

/* Journey 1: a bag we have never seen. */
async function analyzeFile(file) {
  clearCoffee();
  showTab('tab-recipe');
  setLoadingCopy('Reading the bag…', 'Then working out a starting recipe');
  showPanel('scan-loading');

  const form = new FormData();
  form.append('file', file);

  try {
    const res = await fetch('/api/analyze', { method: 'POST', body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(getApiErrorMessage(data, 'Analysis failed'));

    currentCoffeeData = data.coffee_data;
    currentBeanId = data.coffee_data?.bean_id ?? null;
    renderCoffeeCard(currentCoffeeData);
    renderRecipe(data);

    // Pre-fill the per-shot dose with a roast-aware guess; the user can override
    // it and hit "Update recipe" to regenerate the recommendation.
    const baseDose = Number(currentCoffeeData.preferred_dose_g) || 16;
    const guessDose = suggestedDoseForRoast(currentCoffeeData.roast_level, baseDose);
    setScanDose(guessDose, {
      fromRoast: guessDose !== baseDose,
      roastLevel: currentCoffeeData.roast_level,
    });

    loadHistory(currentBeanId);
    showPanel('recipe-view');
  } catch (err) {
    clearCoffee();
    showPanel('recipe-empty');
    showTab('tab-home');
    showToast('❌ ' + (err.message || 'Something went wrong'));
  }
}

async function recalcForDose() {
  if (!currentBeanId && !currentCoffeeData) return;
  const dose = currentScanDose();
  if (dose === null) { showToast('Enter a valid dose'); return; }

  const btn = $('btn-recalc');
  const prevLabel = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Updating…';
  try {
    const ok = await refreshRecommendation({ dose });
    if (ok) {
      if (currentCoffeeData) currentCoffeeData.preferred_dose_g = dose;
      $('dose-adjust-hint').textContent = `Recipe updated for ${dose} g.`;
      showToast(`Recipe updated for ${dose} g`);
    }
  } finally {
    btn.disabled = false;
    btn.textContent = prevLabel;
  }
}

/* ── Flow wiring ───────────────────────────────────────────────────────── */
document.querySelectorAll('.nav-item').forEach((btn) => {
  btn.addEventListener('click', () => showTab(btn.dataset.tab));
});

on('file-input', 'change', async (e) => {
  const file = e.target.files?.[0];
  if (!file) return;
  e.target.value = '';          // reset so the same file can be re-selected
  await analyzeFile(file);
});

on('scan-dose-input', 'input', () => {
  const dose = currentScanDose();
  if (currentCoffeeData && dose !== null) currentCoffeeData.preferred_dose_g = dose;
});

on('btn-recalc', 'click', () => recalcForDose());

on('btn-scan-again', 'click', () => {
  clearCoffee();
  showPanel('recipe-empty');
  showTab('tab-home');
});

on('btn-go-home', 'click', () => showTab('tab-home'));

// Straight back to the recipe for another shot on the same coffee.
on('btn-log-another', 'click', () => showPanel('recipe-view'));

on('btn-new-scan', 'click', () => {
  clearCoffee();
  showPanel('recipe-empty');
  showTab('tab-home');
});

/* ── Coffees & settings wiring ─────────────────────────────────────────── */
on('btn-refresh-logs', 'click', () => loadRecents());
on('btn-add-log', 'click', () => openRecordEditor());
on('btn-save-record', 'click', () => saveRecordFromForm());
on('btn-cancel-record', 'click', () => closeRecordEditor());
on('setup-select', 'change', (event) => selectSetup(event.target.value));
on('setup-chip', 'click', () => openSetupSwitch());
on('btn-close-setup-switch', 'click', () => closeDialog('setup-switch-dialog'));
on('btn-switch-manage', 'click', () => {
  closeDialog('setup-switch-dialog');
  showTab('tab-settings');
  openSetupManager();
});
on('btn-manage-setups', 'click', () => openSetupManager());
on('btn-save-setup', 'click', () => saveSetupFromForm());
on('btn-cancel-setup', 'click', () => closeSetupManager());
on('btn-manage-equipment', 'click', () => openEquipmentManager());
on('btn-save-equipment', 'click', () => saveEquipmentFromForm());
on('btn-close-equipment', 'click', () => closeEquipmentManager());
on('btn-cancel-equipment-edit', 'click', () => clearEquipmentForm());

/* Human "3 days ago" for the card foot — precise dates are noise here; what
   matters is whether this is the bag you're working through. */
function relativeDay(iso) {
  if (!iso) return 'never brewed';
  const then = new Date(iso);
  const days = Math.floor((Date.now() - then.getTime()) / 86400000);
  if (days <= 0) return 'brewed today';
  if (days === 1) return 'brewed yesterday';
  if (days < 30) return `brewed ${days} days ago`;
  return `brewed ${then.toLocaleDateString([], { month: 'short', day: 'numeric' })}`;
}

function daysSinceRoast(iso) {
  if (!iso) return null;
  return Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
}

async function loadRecents() {
  const list = $('recent-list');
  if (!list) return;
  list.innerHTML = '<div class="logs-empty">Loading your coffees…</div>';

  try {
    const response = await fetch('/api/logs?limit=20');
    const data = await response.json();
    if (!response.ok) throw new Error(getApiErrorMessage(data, 'Failed to load coffees'));

    const entries = data.entries || [];
    if (!entries.length) {
      list.innerHTML =
        '<div class="logs-empty">No coffees yet. Scan a bag to get started.</div>';
      return;
    }

    list.innerHTML = '';
    entries.forEach((entry) => {
      const card = document.createElement('article');
      card.className = 'log-card is-tappable';
      card.setAttribute('role', 'button');
      card.tabIndex = 0;

      const latest = entry.latest_log;
      const shots = Number(entry.logs_count || 0);
      const rested = daysSinceRoast(entry.roast_date);

      card.innerHTML = `
        ${logMedia(entry.origin, latest ? latest.image_url : null)}
        <div class="log-card-head">
          <div>
            <h3 class="log-title">${escapeHtml(entry.roaster)} ${escapeHtml(entry.bean_name)}</h3>
            <p class="log-meta">${escapeHtml(entry.origin)} • ${escapeHtml(entry.process)} • ${escapeHtml(entry.roast_level)}</p>
          </div>
          <span class="log-rating">${escapeHtml(String(shots))} shot${shots === 1 ? '' : 's'}</span>
        </div>
        <div class="log-foot">
          <span>${escapeHtml(relativeDay(entry.last_brewed_at))}</span>
          ${rested !== null ? `<span>${escapeHtml(String(rested))} days off roast</span>` : ''}
        </div>
        <div class="log-actions">
          <button class="btn btn-sm btn-primary js-open-bean">Dial in</button>
          <button class="btn btn-sm btn-ghost js-edit-record">Edit</button>
          <button class="btn btn-sm btn-ghost js-delete-record">Delete</button>
        </div>
      `;

      const open = () => openBean(entry);
      card.addEventListener('click', open);
      card.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); }
      });
      // Secondary actions must not also open the coffee.
      card.querySelector('.js-open-bean')?.addEventListener('click', (e) => {
        e.stopPropagation();
        open();
      });
      card.querySelector('.js-edit-record')?.addEventListener('click', (e) => {
        e.stopPropagation();
        openRecordEditor(entry);
      });
      card.querySelector('.js-delete-record')?.addEventListener('click', (e) => {
        e.stopPropagation();
        deleteRecord(entry);
      });
      wireLogMedia(card);
      list.appendChild(card);
    });
  } catch (err) {
    list.innerHTML = `<div class="logs-empty">${escapeHtml(err.message || 'Could not load coffees')}</div>`;
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

  openDialog('log-editor-dialog');
}

function closeRecordEditor() {
  editingBeanId = null;
  closeDialog('log-editor-dialog');
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
    if (!res.ok) throw new Error(getApiErrorMessage(data, 'Save failed'));

    closeRecordEditor();
    await loadRecents();
    showToast('Record saved');
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
    if (!res.ok) throw new Error(getApiErrorMessage(data, 'Delete failed'));
    // If the deleted coffee is the one on the bench, take it off.
    if (currentBeanId === beanId) {
      clearCoffee();
      showPanel('recipe-empty');
    }
    await loadRecents();
    showToast('Record deleted');
  } catch (err) {
    showToast('❌ ' + (err.message || 'Could not delete record'));
  }
}

/* ── Origin artwork ─────────────────────────────────────────────────────────
   Coffee-bag photos are kept in the database but not shown in the log list.
   Instead each bean gets a stylised highland scene generated from its origin.
   The drawing is a pure function of the origin string, so the same country
   always renders identically - no fetching, no caching, works offline. */

// Coffee-growing origins -> flag emoji. Regions map to their country so
// "Ethiopia Yirgacheffe" and "Yirgacheffe" both resolve.
const ORIGIN_FLAGS = [
  ['ethiopia', '🇪🇹'], ['yirgacheffe', '🇪🇹'], ['sidamo', '🇪🇹'], ['guji', '🇪🇹'],
  ['kenya', '🇰🇪'], ['tanzania', '🇹🇿'], ['rwanda', '🇷🇼'], ['burundi', '🇧🇮'],
  ['uganda', '🇺🇬'], ['congo', '🇨🇩'], ['malawi', '🇲🇼'], ['zambia', '🇿🇲'],
  ['colombia', '🇨🇴'], ['huila', '🇨🇴'], ['nariño', '🇨🇴'], ['narino', '🇨🇴'],
  ['brazil', '🇧🇷'], ['brasil', '🇧🇷'], ['cerrado', '🇧🇷'], ['mogiana', '🇧🇷'],
  ['peru', '🇵🇪'], ['bolivia', '🇧🇴'], ['ecuador', '🇪🇨'], ['venezuela', '🇻🇪'],
  ['guatemala', '🇬🇹'], ['antigua', '🇬🇹'], ['huehuetenango', '🇬🇹'],
  ['costa rica', '🇨🇷'], ['tarrazu', '🇨🇷'], ['tarrazú', '🇨🇷'],
  ['nicaragua', '🇳🇮'], ['honduras', '🇭🇳'], ['el salvador', '🇸🇻'],
  ['panama', '🇵🇦'], ['panamá', '🇵🇦'], ['mexico', '🇲🇽'], ['méxico', '🇲🇽'],
  ['chiapas', '🇲🇽'], ['jamaica', '🇯🇲'], ['cuba', '🇨🇺'], ['haiti', '🇭🇹'],
  ['dominican', '🇩🇴'], ['indonesia', '🇮🇩'], ['sumatra', '🇮🇩'],
  ['java', '🇮🇩'], ['sulawesi', '🇮🇩'], ['bali', '🇮🇩'], ['flores', '🇮🇩'],
  ['papua', '🇵🇬'], ['new guinea', '🇵🇬'], ['timor', '🇹🇱'],
  ['vietnam', '🇻🇳'], ['viet nam', '🇻🇳'], ['india', '🇮🇳'], ['mysore', '🇮🇳'],
  ['thailand', '🇹🇭'], ['laos', '🇱🇦'], ['china', '🇨🇳'], ['yunnan', '🇨🇳'],
  ['philippines', '🇵🇭'], ['yemen', '🇾🇪'], ['hawaii', '🇺🇸'], ['kona', '🇺🇸'],
];

function flagForOrigin(origin) {
  const text = String(origin || '').toLowerCase();
  for (const [needle, flag] of ORIGIN_FLAGS) {
    if (text.includes(needle)) return flag;
  }
  return '🌍';
}

// FNV-1a: small, stable, and well spread for short strings.
function hashString(value) {
  let h = 2166136261;
  const text = String(value || '').toLowerCase().trim();
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function originArtwork(origin) {
  const label = String(origin || '').trim() || 'Unknown origin';
  const h = hashString(label);

  // A wide viewBox close to the banner's real aspect ratio, so the non-uniform
  // stretch is negligible. The sun is a soft radial glow rather than a hard
  // circle - a glow still reads correctly if it is stretched slightly.
  const W = 400;
  const H = 120;

  // Derive every varying quantity from a different slice of the hash. The sky
  // is confined to a dusk band and desaturated: a full-spectrum hue varied per
  // origin, which is what this used to do, fights the muted palette the rest of
  // the app is built from. The sun stays clay whatever the sky does, and that
  // is what ties every card back to the accent.
  const hue = 186 + (h % 150);
  const hue2 = hue + 10 + ((h >> 9) % 22);
  const sunHue = 26 + ((h >> 7) % 12);
  const sunX = 250 + ((h >> 5) % 110);        // right-hand side
  const sunY = 26 + ((h >> 11) % 16);
  const seed = ((h >> 3) % 1000) / 100;

  // Ridge lines: two sine components so the skyline is irregular, not a wave.
  const ridge = (base, amp, phase) => {
    const y = (x) =>
      base - amp * (0.62 * Math.sin((x / W) * 5.2 + phase) +
                    0.38 * Math.sin((x / W) * 11.3 + phase * 1.9));
    const pts = [];
    for (let x = 0; x <= W; x += 10) pts.push(`${x},${y(x).toFixed(1)}`);
    return `M0,${H} L0,${y(0).toFixed(1)} L${pts.join(' L')} L${W},${H} Z`;
  };

  const uid = `oa${h.toString(36)}`;

  return `
    <div class="origin-art" role="img" aria-label="Illustration for ${escapeHtml(label)}">
      <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
        <defs>
          <linearGradient id="${uid}s" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="hsl(${hue} 26% 26%)"/>
            <stop offset="100%" stop-color="hsl(${hue2} 22% 11%)"/>
          </linearGradient>
          <radialGradient id="${uid}g">
            <stop offset="0%" stop-color="hsl(${sunHue} 62% 70%)" stop-opacity=".85"/>
            <stop offset="45%" stop-color="hsl(${sunHue} 58% 58%)" stop-opacity=".34"/>
            <stop offset="100%" stop-color="hsl(${sunHue} 55% 52%)" stop-opacity="0"/>
          </radialGradient>
        </defs>
        <rect width="${W}" height="${H}" fill="url(#${uid}s)"/>
        <circle cx="${sunX}" cy="${sunY}" r="46" fill="url(#${uid}g)"/>
        <path d="${ridge(70, 26, seed * 1.3)}"       fill="hsl(${hue} 20% 18%)"/>
        <path d="${ridge(88, 21, seed * 2.1 + 2)}"   fill="hsl(${hue} 22% 12%)"/>
        <path d="${ridge(106, 15, seed * 1.7 + 4)}"  fill="hsl(${hue} 24% 7%)"/>
      </svg>
      <div class="origin-art-label">
        <span class="origin-art-flag">${flagForOrigin(label)}</span>
        <span class="origin-art-name">${escapeHtml(label)}</span>
      </div>
    </div>
  `;
}

/* Media strip for a log card: slide 1 is the generated origin scene, slide 2
   the bag photo the user took (when there is one). Swiping is native CSS
   scroll-snap; the dots just mirror and drive the scroll position. */
function logMedia(origin, imageUrl) {
  const slides = [`<div class="log-media-slide">${originArtwork(origin)}</div>`];
  if (imageUrl) {
    slides.push(
      `<div class="log-media-slide">
         <img class="log-photo" src="${escapeHtml(imageUrl)}" alt="Photo of the coffee bag" loading="lazy">
       </div>`
    );
  }

  const dots = slides.length > 1
    ? `<div class="log-media-dots">${slides
        .map((_, i) => `<button class="log-dot${i === 0 ? ' active' : ''}" type="button"
             aria-label="Show image ${i + 1} of ${slides.length}"></button>`)
        .join('')}</div>`
    : '';

  return `<div class="log-media">
            <div class="log-media-track">${slides.join('')}</div>
            ${dots}
          </div>`;
}

/* Full-screen photo viewer. Shows the photo at its own aspect ratio; the
   overlay is a .dialog-overlay so Escape / backdrop-tap / scroll-lock all
   come from the shared dialog handling. */
function openPhotoViewer(src, alt) {
  const img = $('photo-viewer-img');
  img.src = src;
  img.alt = alt || 'Coffee bag photo';
  openDialog('photo-viewer');
}

function closePhotoViewer() {
  closeDialog('photo-viewer');
  // Drop the decoded image so a big JPEG is not held in memory while closed.
  setTimeout(() => {
    if ($('photo-viewer').classList.contains('hidden')) $('photo-viewer-img').removeAttribute('src');
  }, 250);
}

on('btn-close-photo', 'click', () => closePhotoViewer());

function wireLogMedia(card) {
  const photo = card.querySelector('.log-photo');
  if (photo) {
    photo.addEventListener('click', () => openPhotoViewer(photo.src, photo.alt));
  }

  const track = card.querySelector('.log-media-track');
  const dots = [...card.querySelectorAll('.log-dot')];
  if (!track || dots.length < 2) return;

  const currentIndex = () =>
    track.clientWidth ? Math.round(track.scrollLeft / track.clientWidth) : 0;

  const sync = () => {
    const index = currentIndex();
    dots.forEach((dot, i) => dot.classList.toggle('active', i === index));
  };

  let frame = 0;
  track.addEventListener('scroll', () => {
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      sync();
    });
  }, { passive: true });

  dots.forEach((dot, i) => {
    dot.addEventListener('click', () => {
      track.scrollTo({ left: i * track.clientWidth, behavior: 'smooth' });
    });
  });
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

/* ── Rendering the recipe ───────────────────────────────────────────────── */
/* Numbers come from data.recipe as labelled fields; the prose sits underneath
   as explanation. Every clamp the engine applied is shown as a chip rather
   than silently changing what was asked for. */
const GUARDRAIL_LABELS = {
  grind_channeling_floor: 'Held back from finer — channeling',
  grind_hardware_min: 'At your grinder’s finest',
  grind_hardware_max: 'At your grinder’s coarsest',
  grind_snapped_to_step: 'Rounded to a real click',
  dose_basket_capacity: 'Fitted to your basket',
  dose_plausible_range: 'Dose clamped',
  ratio_out_of_band: 'Ratio pulled into range',
  yield_below_dose_rejected: 'Yield looked mis-logged',
  temp_not_controllable: 'Your machine’s temp is fixed',
  temp_machine_range: 'Temp clamped to your machine',
};

function renderRecipe(data) {
  setRecommendation(data);

  const grid = $('recipe-grid');
  grid.innerHTML = '';
  const r = currentRecipe;
  if (r) {
    const fields = [
      ['Grind', r.grind_clicks !== null && r.grind_clicks !== undefined ? r.grind_clicks : '—'],
      ['Dose', r.dose_g != null ? `${r.dose_g} g` : '—'],
      [r.method === 'espresso' ? 'Out' : 'Water',
       (r.yield_g ?? r.water_g) != null ? `${r.yield_g ?? r.water_g} g` : '—'],
      ['Time', r.target_time_s != null ? `${r.target_time_s} s` : '—'],
    ];
    if (r.brew_temp_c != null) fields.push(['Temp', `${r.brew_temp_c} °C`]);
    if (r.preinfusion_s != null) fields.push(['Pre-inf', `${r.preinfusion_s} s`]);
    if (r.pause_s != null) fields.push(['Rest', `${r.pause_s} s`]);
    fields.forEach(([label, value]) => {
      const cell = document.createElement('div');
      cell.className = 'recipe-cell';
      cell.innerHTML = `<span class="recipe-label"></span><span class="recipe-value"></span>`;
      cell.querySelector('.recipe-label').textContent = label;
      cell.querySelector('.recipe-value').textContent = value;
      grid.appendChild(cell);
    });
  }

  const flags = $('recipe-flags');
  flags.innerHTML = '';
  (r?.guardrails_hit || []).forEach((key) => {
    const chip = document.createElement('span');
    chip.className = 'chip chip-guard';
    chip.textContent = GUARDRAIL_LABELS[key] || key;
    flags.appendChild(chip);
  });

  const prose = data.rationale
    ? [data.rationale.headline, data.rationale.why, data.rationale.what_to_watch]
        .filter(Boolean).join('\n\n')
    : currentRecommendation;
  $('recommendation-text').textContent = prose || '—';
  $('recipe-confidence').textContent = data.confidence_label || '';

  // Attribute the numbers to a setup: the same grind means something
  // different on a different grinder.
  const setupLine = $('recipe-setup-line');
  if (setupLine) {
    const method = r?.method ? METHOD_LABELS[r.method] || r.method : '';
    setupLine.textContent = activeSetupName
      ? `for ${activeSetupName}${method ? ` · ${method}` : ''}`
      : '';
  }
}

/* ── Shot wizard ────────────────────────────────────────────────────────── */
/* Three steps, because the middle one wants the whole screen: set up, time
   the shot, then record what came out. Exit is available on every step. */
let wizStep = 1;
let wizTaste = null;
/* Marks captured by the timer, in ms. The pull is t3 -> t4, which is the
   pressurised phase and therefore the shot time the grind law wants. */
let wizMarks = { start: null, pressure: null, pull: null, stop: null };
let wizTicker = null;
/* Last temperature used, so it carries to the next shot rather than being
   retyped. Temperature is a covariate on every comparison, so a blank one
   costs the engine real information. */
let lastBrewTempC = null;

const TIMER_STAGES = {
  idle:     { phase: 'Pre-infusion', prompt: 'Tap anywhere to start' },
  infusing: { phase: 'Pre-infusion', prompt: 'Tap when the gauge starts to move' },
  resting:  { phase: 'Resting',      prompt: 'Tap when you start the pull' },
  pulling:  { phase: 'Pulling',      prompt: 'Tap when you stop the shot' },
  done:     { phase: 'Shot',         prompt: 'Tap Next to record what came out' },
};

function wizTimerStage() {
  return $('timer-surface')?.dataset.stage || 'idle';
}

function secs(from, to) {
  if (from === null || to === null) return null;
  return Math.round(((to - from) / 1000) * 10) / 10;
}

/* Whichever interval is currently running. */
function liveElapsed() {
  const now = performance.now();
  const stage = wizTimerStage();
  if (stage === 'infusing') return secs(wizMarks.start, now);
  if (stage === 'resting') return secs(wizMarks.pressure, now);
  if (stage === 'pulling') return secs(wizMarks.pull, now);
  if (stage === 'done') return secs(wizMarks.pull, wizMarks.stop);
  return 0;
}

function renderTimer() {
  const stage = wizTimerStage();
  const spec = TIMER_STAGES[stage];
  const phase = $('timer-phase');
  const prompt = $('timer-prompt');
  const clock = $('timer-clock');
  if (phase) phase.textContent = spec.phase;
  if (prompt) prompt.textContent = spec.prompt;
  const elapsed = liveElapsed() ?? 0;
  if (clock) clock.textContent = elapsed.toFixed(1);

  // One full turn per minute, like a stopwatch face. 2 * PI * r, r = 108.
  const arc = $('timer-ring-arc');
  if (arc) {
    const CIRCUMFERENCE = 678.58;
    arc.style.strokeDashoffset =
      String(CIRCUMFERENCE * (1 - ((elapsed % 60) / 60)));
  }

  const marks = $('timer-marks');
  if (marks) {
    const pi = secs(wizMarks.start, wizMarks.pressure);
    const pause = secs(wizMarks.pressure, wizMarks.pull);
    const shot = secs(wizMarks.pull, wizMarks.stop);
    marks.innerHTML = [
      pi !== null ? `<span class="chip">Pre-infusion ${pi}s</span>` : '',
      pause !== null ? `<span class="chip">Rest ${pause}s</span>` : '',
      shot !== null ? `<span class="chip chip-band">Shot ${shot}s</span>` : '',
    ].join('');
  }
}

function startTicker() {
  stopTicker();
  wizTicker = setInterval(renderTimer, 100);
}
function stopTicker() {
  if (wizTicker) { clearInterval(wizTicker); wizTicker = null; }
}

function setTimerStage(stage) {
  const surface = $('timer-surface');
  if (surface) surface.dataset.stage = stage;
  if (stage === 'idle' || stage === 'done') stopTicker(); else startTicker();
  renderTimer();
  updateWizardChrome();
}

function advanceTimer() {
  const now = performance.now();
  switch (wizTimerStage()) {
    case 'idle':
      wizMarks = { start: now, pressure: null, pull: null, stop: null };
      setTimerStage('infusing');
      break;
    case 'infusing':
      wizMarks.pressure = now;
      setTimerStage('resting');
      break;
    case 'resting':
      wizMarks.pull = now;
      setTimerStage('pulling');
      break;
    case 'pulling':
      wizMarks.stop = now;
      setTimerStage('done');
      break;
    default:
      break;    // 'done' — use Next; another tap must not restart the shot
  }
}

/* Straight to the pull: no pre-infusion on this shot, or the method has none. */
function skipToPull() {
  wizMarks = { start: null, pressure: null, pull: performance.now(), stop: null };
  setTimerStage('pulling');
}

function resetTimer() {
  wizMarks = { start: null, pressure: null, pull: null, stop: null };
  setTimerStage('idle');
}

function wizTimedShot() {
  return {
    preinfusion_s: secs(wizMarks.start, wizMarks.pressure),
    pause_s: secs(wizMarks.pressure, wizMarks.pull),
    time_s: secs(wizMarks.pull, wizMarks.stop),
  };
}

function showWizStep(step) {
  wizStep = step;
  [1, 2, 3].forEach((n) => {
    const pane = $(`wizard-step-${n}`);
    if (pane) pane.classList.toggle('hidden', n !== step);
  });
  const titles = { 1: 'Grind & dose', 2: 'Time the shot', 3: 'What came out' };
  const title = $('wizard-title');
  const label = $('wizard-step-label');
  if (title) title.textContent = titles[step];
  if (label) label.textContent = `Step ${step} of 3`;

  if (step === 3) {
    // Carry the timed shot forward, but leave it editable.
    const timed = wizTimedShot();
    const timeField = $('wiz-time');
    if (timeField && timed.time_s !== null) timeField.value = String(timed.time_s);
    const hint = $('wiz-time-hint');
    if (hint) {
      hint.textContent = timed.time_s !== null
        ? 'Taken from the timer — adjust if you stopped it late.'
        : 'Not timed. Type the shot time if you know it, or leave it blank.';
    }
  }
  updateWizardChrome();
}

function updateWizardChrome() {
  const back = $('btn-wiz-back');
  const next = $('btn-wiz-next');
  if (back) back.classList.toggle('hidden', wizStep === 1);
  if (!next) return;
  if (wizStep === 3) { next.textContent = 'Log this shot'; return; }
  if (wizStep === 2) {
    const stage = wizTimerStage();
    // Nudge toward finishing the shot rather than skipping past it.
    next.textContent = stage === 'done' ? 'Next' : 'Skip timing';
    return;
  }
  next.textContent = 'Next';
}

function openShotWizard() {
  if (!currentCoffeeData && !currentBeanId) {
    showToast('Nothing to log — pick a coffee first');
    return;
  }
  const dose = currentScanDose() ?? currentCoffeeData?.preferred_dose_g ?? '';
  $('wiz-grind').value = currentRecipe?.grind_clicks ?? '';
  $('wiz-dose').value = dose === '' ? '' : String(dose);
  $('wiz-yield').value = currentRecipe?.yield_g ?? currentRecipe?.water_g ?? '';
  $('wiz-time').value = '';
  // The engine's target if it recommends one, else whatever you used last.
  const temp = currentRecipe?.brew_temp_c ?? lastBrewTempC;
  $('wiz-temp').value = temp === null || temp === undefined ? '' : String(temp);
  const tempHint = $('wiz-temp-hint');
  if (tempHint) {
    tempHint.textContent = currentRecipe?.brew_temp_c != null
      ? 'Suggested for this roast.'
      : 'Recorded either way — shots at different temperatures are not '
        + 'compared as evidence about the grind.';
  }
  $('wiz-astringent').checked = false;
  wizTaste = null;
  document.querySelectorAll('#taste-scale .taste-btn')
    .forEach((b) => b.classList.remove('is-selected'));

  const label = $('wiz-yield-label');
  if (label) {
    label.textContent =
      currentRecipe && currentRecipe.method !== 'espresso' ? 'Water in (g)' : 'Out (g)';
  }
  const skip = $('btn-timer-skip');
  if (skip) skip.hidden = false;

  resetTimer();
  // No low-pressure phase to hold on a moka pot: start at the pull.
  if (currentRecipe?.method === 'moka') {
    skipToPull();
    if (skip) skip.hidden = true;
  }

  showWizStep(1);
  $('shot-wizard').classList.remove('hidden');
  document.body.classList.add('modal-open');
}

function closeShotWizard() {
  stopTicker();
  $('shot-wizard')?.classList.add('hidden');
  syncModalScrollLock();
}

on('timer-surface', 'click', () => advanceTimer());
on('btn-timer-skip', 'click', (e) => { e.stopPropagation(); skipToPull(); });
on('btn-timer-reset', 'click', (e) => { e.stopPropagation(); resetTimer(); });
on('btn-wizard-exit', 'click', () => closeShotWizard());
on('btn-wiz-back', 'click', () => showWizStep(Math.max(1, wizStep - 1)));

on('btn-wiz-next', 'click', () => {
  if (wizStep < 3) { showWizStep(wizStep + 1); return; }
  const timed = wizTimedShot();
  const typedTime = parseFloat($('wiz-time').value);
  saveFeedback({
    grind: $('wiz-grind').value.trim(),
    dose: parseFloat($('wiz-dose').value),
    yield_g: parseFloat($('wiz-yield').value),
    time_s: Number.isFinite(typedTime) ? typedTime : timed.time_s,
    preinfusion_s: timed.preinfusion_s,
    pause_s: timed.pause_s,
    taste_axis: wizTaste,
    astringent: $('wiz-astringent').checked,
    brew_temp_c: parseFloat($('wiz-temp').value),
  });
});

document.querySelectorAll('#taste-scale .taste-btn').forEach((btn) => {
  btn.addEventListener('click', () => {
    const value = btn.dataset.taste;
    wizTaste = wizTaste === value ? null : value;
    document.querySelectorAll('#taste-scale .taste-btn').forEach((b) => {
      b.classList.toggle('is-selected', b.dataset.taste === wizTaste);
    });
  });
});

on('btn-worked', 'click', () => openShotWizard());


async function saveFeedback(worked) {
  if (!currentCoffeeData && !currentBeanId) {
    // Was a silent early-return, which swallowed the shot with no explanation.
    showToast('Nothing to log — pick a coffee first');
    return;
  }
  // The wizard stays open until the save is known to have worked. Closing it
  // first threw away everything the user had just typed whenever the request
  // failed, so a failed save cost them the shot as well as the log.
  const next = $('btn-wiz-next');
  const nextLabel = next ? next.textContent : '';
  if (next) { next.disabled = true; next.textContent = 'Saving…'; }

  const actualGrind = worked && worked.grind ? worked.grind : null;
  const doseUsed = worked && worked.dose > 0
    ? worked.dose
    : (currentScanDose() ?? currentCoffeeData.preferred_dose_g ?? null);
  const num = (v) => (Number.isFinite(v) && v > 0 ? v : null);
  if (num(worked?.brew_temp_c) !== null) lastBrewTempC = worked.brew_temp_c;

  try {
    const res = await fetch('/api/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        coffee_data:    currentCoffeeData,
        recommendation: currentRecommendation,
        actual_grind:   actualGrind,
        dose_g:         doseUsed,
        // Anything left blank is sent as null and stored as unmeasured.
        // Never filled in with a plausible-looking default.
        yield_g:        num(worked?.yield_g),
        time_s:         num(worked?.time_s),
        taste_axis:     worked?.taste_axis ?? null,
        astringent:     worked?.astringent ?? null,
        preinfusion_s:  num(worked?.preinfusion_s),
        pause_s:        num(worked?.pause_s),
        brew_temp_c:    num(worked?.brew_temp_c),
        recommendation_id: currentRecommendationId,
        image_name:     currentCoffeeData?.image_name ?? null,
      }),
    });
    if (!res.ok) {
      // getApiErrorMessage, not `d.detail`: a 422 sends detail as an array of
      // objects, and stringifying that is where "❌ [object Object]" came from.
      const d = await res.json().catch(() => ({}));
      throw new Error(getApiErrorMessage(d, 'Save failed'));
    }

    closeShotWizard();
    // That recommendation has been consumed. Clearing it here is what stops
    // a second shot being logged against the same recommendation_id.
    clearRecommendation();
    showPanel('scan-success');
    loadHistory(currentBeanId);

    // Fold the shot into the next suggestion, so "Next shot" already has it.
    const refreshed = await refreshRecommendation({
      dose: currentScanDose(),
      silent: true,
    });
    const sub = $('success-sub');
    if (sub) {
      sub.textContent = refreshed
        ? 'Recipe updated with that shot. Tap "Next shot" to see it.'
        : 'Every measured shot sharpens the next recommendation.';
    }
  } catch (err) {
    showToast('❌ ' + (err.message || 'Could not save'));
  } finally {
    if (next) { next.disabled = false; next.textContent = nextLabel; }
  }
}

/* ── Settings ───────────────────────────────────────────────────────────── */
// Who the server says we are. Only meaningful on the shared instance, so the
// card stays hidden in single-user mode rather than showing a placeholder name.
async function loadAccount() {
  const group = $('account-group');
  if (!group) return;
  try {
    const res = await fetch('/api/whoami');
    if (!res.ok) return;
    const data = await res.json();
    if (data.auth_mode !== 'tailscale' || !data.owner) return;
    $('account-owner').textContent = data.owner;
    group.hidden = false;
  } catch {
    // Non-fatal: the rest of Settings is still usable without it.
  }
}

async function loadSettings() {
  try {
    const [eqRes, setRes] = await Promise.all([
      fetch('/api/equipment'),
      fetch('/api/settings'),
    ]);
    const eq  = await eqRes.json();
    const set = await setRes.json();

    const gearName = item =>
      item ? `${item.brand ?? ''} ${item.model ?? ''}`.trim() || 'Not set' : 'Not set';
    $('active-grinder-name').textContent = gearName(eq.grinder);
    $('active-machine-name').textContent = gearName(eq.machine);

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
    if (!res.ok) throw new Error(getApiErrorMessage(data, 'Could not load setups'));

    const activeId = Number(data.active_setup_id);
    cachedSetups = Array.isArray(data.setups) ? data.setups : [];

    const active = cachedSetups.find((s) => Number(s.id) === activeId);
    activeSetupId = activeId || null;
    activeSetupName = active?.name || '';
    activeSetupMethod = active?.method || null;
    renderSetupChip();

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

const EQUIPMENT_TYPE_LABELS = {
  grinder: 'grinder',
  espresso_machine: 'espresso machine',
  filter: 'filter brewer',
  other: 'other',
};
function labelForType(type) {
  return EQUIPMENT_TYPE_LABELS[type] || type || 'equipment';
}

async function loadEquipmentLibrary() {
  try {
    const res = await fetch('/api/equipment/library');
    const data = await res.json();
    if (!res.ok) throw new Error(getApiErrorMessage(data, 'Could not load equipment'));

    cachedEquipmentLibrary = {
      grinders: Array.isArray(data.grinders) ? data.grinders : [],
      machines: Array.isArray(data.machines) ? data.machines : [],
    };

    renderEquipmentSelects();
    renderEquipmentList();
    renderEquipmentSummary();
  } catch (err) {
    showToast('⚠️ ' + (err.message || 'Could not load equipment'));
  }
}

function renderEquipmentSummary() {
  const list = $('equipment-summary-list');
  if (!list) return;

  const items = [
    ...cachedEquipmentLibrary.grinders,
    ...cachedEquipmentLibrary.machines,
  ];
  if (!items.length) {
    list.innerHTML = '<div class="gear-list-empty">No equipment saved yet — add some from “Manage equipment”.</div>';
    return;
  }

  list.innerHTML = '';
  items.forEach(item => {
    const row = document.createElement('div');
    row.className = 'gear-list-item';
    row.innerHTML = `
      <span class="gear-list-name">${escapeHtml(item.brand)} ${escapeHtml(item.model)}</span>
      <span class="gear-list-badge">${escapeHtml(labelForType(item.type))}</span>
    `;
    list.appendChild(row);
  });
}

function renderEquipmentSelects() {
  const grinderSelect = $('setup-form-grinder-id');
  const machineSelect = $('setup-form-machine-id');
  if (!grinderSelect || !machineSelect) return;

  grinderSelect.innerHTML = '';
  machineSelect.innerHTML = '';

  if (!cachedEquipmentLibrary.grinders.length) {
    const option = document.createElement('option');
    option.value = '';
    option.textContent = 'No grinders saved yet';
    grinderSelect.appendChild(option);
  } else {
    cachedEquipmentLibrary.grinders.forEach(item => {
      const option = document.createElement('option');
      option.value = String(item.id);
      option.textContent = `${item.brand} ${item.model}`;
      grinderSelect.appendChild(option);
    });
  }

  if (!cachedEquipmentLibrary.machines.length) {
    const option = document.createElement('option');
    option.value = '';
    option.textContent = 'No machines/brewers saved yet';
    machineSelect.appendChild(option);
  } else {
    cachedEquipmentLibrary.machines.forEach(item => {
      const option = document.createElement('option');
      option.value = String(item.id);
      option.textContent = `${item.brand} ${item.model} · ${labelForType(item.type)}`;
      machineSelect.appendChild(option);
    });
  }
}

function renderEquipmentList() {
  const list = $('equipment-list');
  if (!list) return;

  const activeSetupId = Number($('setup-select')?.value || 0);
  const activeSetup = cachedSetups.find(s => Number(s.id) === activeSetupId) || null;

  const items = [
    ...cachedEquipmentLibrary.grinders,
    ...cachedEquipmentLibrary.machines,
  ];
  if (!items.length) {
    list.innerHTML = '<div class="logs-empty logs-empty-compact">No equipment saved yet.</div>';
    return;
  }

  list.innerHTML = '';
  items.forEach(item => {
    const row = document.createElement('div');
    row.className = 'setup-item';
    const usageCount = cachedSetups.filter(
      s => Number(s.grinder?.id) === Number(item.id) || Number(s.machine?.id) === Number(item.id)
    ).length;
    const isActive = activeSetup
      ? Number(activeSetup.grinder?.id) === Number(item.id) || Number(activeSetup.machine?.id) === Number(item.id)
      : false;
    row.innerHTML = `
      <div class="setup-item-main">
        <div class="setup-item-name">
          ${escapeHtml(item.brand)} ${escapeHtml(item.model)}
          ${isActive ? '<span class="setup-active-pill">In active setup</span>' : ''}
          ${usageCount > 0 ? `<span class="setup-active-pill">Used by ${usageCount} setup${usageCount === 1 ? '' : 's'}</span>` : ''}
        </div>
        <div class="setup-item-meta">${escapeHtml(labelForType(item.type))}</div>
      </div>
      <div class="setup-item-actions">
        <button class="btn btn-sm btn-ghost js-equipment-edit">Edit</button>
        <button class="btn btn-sm btn-ghost js-equipment-delete">Delete</button>
      </div>
    `;
    row.querySelector('.js-equipment-edit')?.addEventListener('click', () => populateEquipmentForm(item));
    row.querySelector('.js-equipment-delete')?.addEventListener('click', () => deleteEquipment(item));
    list.appendChild(row);
  });
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
        <div class="setup-item-meta">${escapeHtml(setup.grinder.brand)} ${escapeHtml(setup.grinder.model)} &nbsp;·&nbsp; ${escapeHtml(setup.machine.brand)} ${escapeHtml(setup.machine.model)}</div>
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

const METHOD_LABELS = {
  espresso: 'espresso',
  pourover: 'pour-over',
  moka: 'moka',
};

function renderSetupChip() {
  const name = $('setup-chip-name');
  const method = $('setup-chip-method');
  if (name) name.textContent = activeSetupName || 'No setup';
  if (method) {
    method.textContent = activeSetupMethod
      ? METHOD_LABELS[activeSetupMethod] || activeSetupMethod
      : '';
  }
}

function openSetupSwitch() {
  const list = $('setup-switch-list');
  if (!list) return;
  list.innerHTML = '';

  if (!cachedSetups.length) {
    list.innerHTML = '<div class="logs-empty">No setups yet. Add one in Settings.</div>';
  }

  cachedSetups.forEach((setup) => {
    const isActive = Number(setup.id) === activeSetupId;
    const row = document.createElement('button');
    row.type = 'button';
    row.className = 'setup-item' + (isActive ? ' is-active' : '');
    row.innerHTML = `
      <div class="setup-item-main">
        <span class="setup-item-name">${escapeHtml(setup.name)}</span>
        <span class="setup-item-method">${escapeHtml(
          METHOD_LABELS[setup.method] || setup.method || 'espresso'
        )} · ${escapeHtml(setup.grinder?.model || '')}</span>
      </div>
      ${isActive ? '<span class="setup-active-pill">Active</span>' : ''}
    `;
    row.addEventListener('click', () => selectSetup(setup.id));
    list.appendChild(row);
  });

  openDialog('setup-switch-dialog');
}

async function selectSetup(setupId) {
  const parsed = Number(setupId);
  if (!parsed) return;
  if (parsed === activeSetupId) { closeDialog('setup-switch-dialog'); return; }

  try {
    const res = await fetch('/api/setups/active', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ setup_id: parsed, active_setup_id: parsed }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(getApiErrorMessage(data, 'Could not switch setup'));

    closeDialog('setup-switch-dialog');
    await loadSetups();
    loadSettings();

    // The recipe on screen belongs to the setup it was computed for. Leaving
    // it there after a switch would show espresso numbers labelled as filter.
    if (currentBeanId || currentCoffeeData) {
      await refreshRecommendation({ dose: currentScanDose() });
      loadHistory(currentBeanId);
    } else {
      clearRecommendation();
    }
    showToast(`Now on ${activeSetupName || 'the new setup'}`);
  } catch (err) {
    showToast('❌ ' + (err.message || 'Could not switch setup'));
  }
}

function openSetupManager() {
  setupEditingId = null;
  clearSetupForm();
  $('setup-manager-title').textContent = 'Manage setups';
  openDialog('setup-manager-dialog');
  const currentActive = Number($('setup-select').value || 0);
  renderSetupManagerList(currentActive || null);
  loadEquipmentLibrary();
}

function closeSetupManager() {
  closeDialog('setup-manager-dialog');
  setupEditingId = null;
}

function openEquipmentManager() {
  openDialog('equipment-manager-dialog');
  clearEquipmentForm();
  renderEquipmentList();
  loadEquipmentLibrary();
}

function closeEquipmentManager() {
  closeDialog('equipment-manager-dialog');
}

/* Capability fields, mapped to their inputs. Blank means "unknown", which the
   engine treats as a reason to abstain rather than a reason to guess. */
const CAP_FIELDS = {
  grind_min_clicks: 'equipment-form-grind-min',
  grind_max_clicks: 'equipment-form-grind-max',
  grind_step_clicks: 'equipment-form-grind-step',
  grind_um_per_click: 'equipment-form-grind-um',
  finer_direction: 'equipment-form-finer-direction',
  burr_type: 'equipment-form-burr-type',
  basket_size_g: 'equipment-form-basket',
  temp_min_c: 'equipment-form-temp-min',
  temp_max_c: 'equipment-form-temp-max',
  spec_source: 'equipment-form-spec-source',
};

function showCapsFor(type) {
  // A grinder has no basket; a brewer has no burrs.
  $('equipment-grinder-caps').style.display = type === 'grinder' ? '' : 'none';
  $('equipment-machine-caps').style.display = type === 'grinder' ? 'none' : '';
}

function clearEquipmentForm() {
  equipmentEditingId = null;
  $('equipment-form-title').textContent = 'Add equipment';
  $('equipment-form-type').value = 'grinder';
  $('equipment-form-brand').value = '';
  $('equipment-form-model').value = '';
  Object.values(CAP_FIELDS).forEach((id) => { $(id).value = ''; });
  $('equipment-form-finer-direction').value = 'lower_is_finer';
  $('equipment-form-temp-controllable').checked = false;
  showCapsFor('grinder');
  $('btn-cancel-equipment-edit').hidden = true;
}

function populateEquipmentForm(item) {
  equipmentEditingId = Number(item.id);
  $('equipment-form-title').textContent = `Edit ${item.brand} ${item.model}`;
  $('equipment-form-type').value = item.type || 'grinder';
  $('equipment-form-brand').value = item.brand || '';
  $('equipment-form-model').value = item.model || '';
  Object.entries(CAP_FIELDS).forEach(([key, id]) => {
    $(id).value = item[key] ?? '';
  });
  $('equipment-form-finer-direction').value = item.finer_direction || 'lower_is_finer';
  $('equipment-form-temp-controllable').checked = Boolean(item.temp_controllable);
  showCapsFor(item.type || 'grinder');
  $('btn-cancel-equipment-edit').hidden = false;
  $('equipment-form-title').scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

on('equipment-form-type', 'change', (e) => showCapsFor(e.target.value));

function clearSetupForm() {
  $('setup-form-name').value = '';
  $('setup-form-method').value = '';
  const grinderSelect = $('setup-form-grinder-id');
  const machineSelect = $('setup-form-machine-id');
  if (grinderSelect) grinderSelect.value = grinderSelect.options[0]?.value || '';
  if (machineSelect) machineSelect.value = machineSelect.options[0]?.value || '';
}

function populateSetupForm(setup) {
  setupEditingId = Number(setup.id);
  $('setup-manager-title').textContent = `Editing setup: ${setup.name}`;
  $('setup-form-name').value = setup.name || '';
  $('setup-form-grinder-id').value = String(setup.grinder?.id || '');
  $('setup-form-machine-id').value = String(setup.machine?.id || '');
  $('setup-form-method').value = setup.method || '';
}

async function saveSetupFromForm() {
  const payload = {
    name: $('setup-form-name').value.trim(),
    grinder_id: Number($('setup-form-grinder-id').value),
    machine_id: Number($('setup-form-machine-id').value),
    // Blank means "work it out from the brewer".
    method: $('setup-form-method').value || null,
  };

  if (!payload.name || !payload.grinder_id || !payload.machine_id) {
    showToast('Pick a name, grinder, and machine');
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
    if (!res.ok) throw new Error(getApiErrorMessage(data, 'Could not save setup'));

    setupEditingId = null;
    clearSetupForm();
    $('setup-manager-title').textContent = 'Manage setups';
    await Promise.all([loadSetups(), loadSettings()]);
    showToast('Setup saved');
  } catch (err) {
    showToast('❌ ' + (err.message || 'Could not save setup'));
  }
}

async function saveEquipmentFromForm() {
  const payload = {
    type: $('equipment-form-type').value,
    brand: $('equipment-form-brand').value.trim(),
    model: $('equipment-form-model').value.trim(),
    temp_controllable: $('equipment-form-temp-controllable').checked,
  };

  // Only send what was actually filled in. A blank stays unknown rather than
  // being sent as a zero the engine would treat as a real limit.
  Object.entries(CAP_FIELDS).forEach(([key, id]) => {
    const raw = $(id).value;
    if (raw === '' || raw === null) return;
    const numeric = key !== 'finer_direction' && key !== 'burr_type'
      && key !== 'spec_source';
    payload[key] = numeric ? Number(raw) : raw.trim();
  });

  if (!payload.brand || !payload.model) {
    showToast('Enter brand and model');
    return;
  }

  try {
    const isEdit = Boolean(equipmentEditingId);
    const url = equipmentEditingId
      ? `/api/equipment/library/${equipmentEditingId}`
      : '/api/equipment/library';
    const method = equipmentEditingId ? 'PUT' : 'POST';
    const res = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(getApiErrorMessage(data, 'Could not save equipment'));

    clearEquipmentForm();
    await Promise.all([loadEquipmentLibrary(), loadSetups(), loadSettings()]);
    showToast(isEdit ? 'Equipment updated' : 'Equipment saved');
  } catch (err) {
    showToast('❌ ' + (err.message || 'Could not save equipment'));
  }
}

async function deleteEquipment(item) {
  if (!item?.id) return;
  if (!window.confirm(`Delete equipment "${item.brand} ${item.model}"?`)) return;

  try {
    const res = await fetch(`/api/equipment/library/${item.id}`, { method: 'DELETE' });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(getApiErrorMessage(data, 'Could not delete equipment'));

    clearEquipmentForm();
    await Promise.all([loadEquipmentLibrary(), loadSetups(), loadSettings()]);
    showToast('Equipment deleted');
  } catch (err) {
    showToast('❌ ' + (err.message || 'Could not delete equipment'));
  }
}

async function deleteSetup(setup) {
  if (!setup || !setup.id) return;
  if (!window.confirm(`Delete setup "${setup.name}"?`)) return;

  try {
    const res = await fetch(`/api/setups/${setup.id}`, { method: 'DELETE' });
    const data = await res.json();
    if (!res.ok) throw new Error(getApiErrorMessage(data, 'Could not delete setup'));

    await Promise.all([loadSetups(), loadSettings()]);
    showToast('Setup deleted');
  } catch (err) {
    showToast('❌ ' + (err.message || 'Could not delete setup'));
  }
}

on('btn-open-equipment-manager', 'click', () => openEquipmentManager());

on('btn-save-dose', 'click', async () => {
  const val = parseFloat($('dose-input').value);
  if (!val || val <= 0) { showToast('Enter a valid dose'); return; }
  await putJson('/api/settings/dose', { dose_g: val }, `Dose set to ${val}g ✓`);
});

on('btn-save-offset', 'click', async () => {
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
      throw new Error(getApiErrorMessage(d, 'Update failed'));
    }
    showToast('' + successMsg);
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

/* ── Dismiss dialogs: tap the backdrop or press Escape ─────────────────── */
const DIALOG_DISMISS = {
  'photo-viewer': () => closePhotoViewer(),
  'grind-dialog': () => closeDialog('grind-dialog'),
  'log-editor-dialog': () => closeRecordEditor(),
  'setup-manager-dialog': () => closeSetupManager(),
  'equipment-manager-dialog': () => closeEquipmentManager(),
};

function dismissDialog(id) {
  (DIALOG_DISMISS[id] || (() => closeDialog(id)))();
}

document.querySelectorAll('.dialog-overlay').forEach(overlay => {
  overlay.addEventListener('click', event => {
    if (event.target === overlay) dismissDialog(overlay.id);
  });
});

document.addEventListener('keydown', event => {
  if (event.key !== 'Escape') return;
  const open = document.querySelector('.dialog-overlay:not(.hidden)');
  if (open) dismissDialog(open.id);
});

/* ── Version chip ───────────────────────────────────────────────────────── */
/* Two numbers, because one cannot answer the question: what this bundle is,
   and what the server is currently serving. When they differ, the deploy has
   not reached this device yet. */
async function loadVersion() {
  const chip = $('version-chip');
  if (!chip) return;
  chip.textContent = BUNDLE_VERSION ? `v${BUNDLE_VERSION}` : 'v?';

  try {
    const res = await fetch('/api/version', { cache: 'no-store' });
    const data = await res.json();
    serverAssetVersion = data.asset_version ?? null;
    engineVersion = data.engine_version ?? null;

    if (serverAssetVersion && BUNDLE_VERSION && serverAssetVersion !== BUNDLE_VERSION) {
      chip.classList.add('is-stale');
      chip.textContent = `v${BUNDLE_VERSION} → v${serverAssetVersion}`;
      chip.title = 'A newer version is available — tap to update';
    } else {
      chip.title = 'App version';
    }
  } catch {
    // Offline: keep showing the honest local number rather than guessing.
  }
}

async function updateToLatest() {
  showToast('⏳ Fetching the new version…');
  try {
    const regs = (await navigator.serviceWorker?.getRegistrations?.()) ?? [];
    await Promise.all(regs.map((r) => r.update().catch(() => {})));
    const keys = (await caches?.keys?.()) ?? [];
    await Promise.all(keys.map((k) => caches.delete(k).catch(() => {})));
  } catch {
    // Even if clearing fails, a reload against a no-cache shell usually works.
  }
  location.reload();
}

on('version-chip', 'click', () => {
  if (serverAssetVersion && BUNDLE_VERSION && serverAssetVersion !== BUNDLE_VERSION) {
    // Never automatic: a reload loop against a broken deploy is worse than
    // running a stale bundle for another minute.
    updateToLatest();
    return;
  }
  const engine = engineVersion ? ` · engine ${engineVersion}` : '';
  showToast(`Up to date (v${BUNDLE_VERSION ?? '?'})${engine}`);
});

/* ── Service worker registration ────────────────────────────────────────── */
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => {});
  });
}

/* ── Boot ───────────────────────────────────────────────────────────────── */
clearCoffee();
showPanel('recipe-empty');
showTab('tab-home', { push: false });
history.replaceState({ tab: 'tab-home' }, '');
loadSetups();
loadVersion();

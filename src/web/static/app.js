/* ── State ──────────────────────────────────────────────────────────────── */
let currentCoffeeData = null;
let currentRecommendation = null;
let editingBeanId = null;
let setupEditingId = null;
let equipmentEditingId = null;
let cachedSetups = [];
let cachedEquipmentLibrary = { grinders: [], machines: [] };

/* ── Helpers ────────────────────────────────────────────────────────────── */
function $(id) { return document.getElementById(id); }

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

function showPanel(id) {
  ['scan-idle', 'scan-loading', 'scan-results', 'scan-success'].forEach(p => {
    const el = $(p);
    el && el.classList.toggle('hidden', p !== id);
  });
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
      loadEquipmentLibrary();
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

    // Pre-fill the per-shot dose with a roast-aware guess; the user can override
    // it and hit "Update recipe" to regenerate the recommendation.
    const baseDose = Number(currentCoffeeData.preferred_dose_g) || 16;
    const guessDose = suggestedDoseForRoast(currentCoffeeData.roast_level, baseDose);
    setScanDose(guessDose, {
      fromRoast: guessDose !== baseDose,
      roastLevel: currentCoffeeData.roast_level,
    });

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

$('scan-dose-input').addEventListener('input', () => {
  const dose = currentScanDose();
  if (currentCoffeeData && dose !== null) currentCoffeeData.preferred_dose_g = dose;
});

$('btn-recalc').addEventListener('click', async () => {
  if (!currentCoffeeData) return;
  const dose = currentScanDose();
  if (dose === null) { showToast('Enter a valid dose'); return; }

  const btn = $('btn-recalc');
  const prevLabel = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Updating…';
  try {
    const res = await fetch('/api/recommendation', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ coffee_data: currentCoffeeData, dose_g: dose }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(getApiErrorMessage(data, 'Could not update recipe'));

    currentRecommendation = data.recommendation;
    currentCoffeeData.preferred_dose_g = dose;
    $('recommendation-text').textContent = currentRecommendation || '—';
    $('dose-adjust-hint').textContent = `Recipe updated for ${dose} g.`;
    showToast(`✅ Recipe updated for ${dose} g`);
  } catch (err) {
    showToast('❌ ' + (err.message || 'Could not update recipe'));
  } finally {
    btn.disabled = false;
    btn.textContent = prevLabel;
  }
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
$('btn-manage-equipment').addEventListener('click', () => openEquipmentManager());
$('btn-save-equipment').addEventListener('click', () => saveEquipmentFromForm());
$('btn-close-equipment').addEventListener('click', () => closeEquipmentManager());
$('btn-cancel-equipment-edit').addEventListener('click', () => clearEquipmentForm());

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
        ${logMedia(entry.origin, hasLatest ? latest.image_url : null)}
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
      wireLogMedia(card);
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

  // Derive every varying quantity from a different slice of the hash.
  const hue = h % 360;
  const hue2 = (hue + 25 + ((h >> 9) % 40)) % 360;
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
            <stop offset="0%" stop-color="hsl(${hue} 58% 30%)"/>
            <stop offset="100%" stop-color="hsl(${hue2} 48% 13%)"/>
          </linearGradient>
          <radialGradient id="${uid}g">
            <stop offset="0%" stop-color="hsl(${(hue + 45) % 360} 90% 78%)" stop-opacity=".95"/>
            <stop offset="45%" stop-color="hsl(${(hue + 45) % 360} 88% 66%)" stop-opacity=".45"/>
            <stop offset="100%" stop-color="hsl(${(hue + 45) % 360} 85% 60%)" stop-opacity="0"/>
          </radialGradient>
        </defs>
        <rect width="${W}" height="${H}" fill="url(#${uid}s)"/>
        <circle cx="${sunX}" cy="${sunY}" r="46" fill="url(#${uid}g)"/>
        <path d="${ridge(70, 26, seed * 1.3)}"       fill="hsl(${hue} 42% 21%)"/>
        <path d="${ridge(88, 21, seed * 2.1 + 2)}"   fill="hsl(${hue} 47% 14%)"/>
        <path d="${ridge(106, 15, seed * 1.7 + 4)}"  fill="hsl(${hue} 52% 8%)"/>
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

function wireLogMedia(card) {
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

/* ── Feedback: "It worked!" ─────────────────────────────────────────────── */
function suggestedGrindFromRecommendation(text) {
  // Pull the number out of e.g. "**Suggested Grind Setting:** 33 clicks".
  const match = /Suggested Grind Setting:\**\s*([0-9]+(?:\.[0-9]+)?)/i.exec(String(text || ''));
  return match ? match[1] : '';
}

$('btn-worked').addEventListener('click', () => {
  const dose = currentScanDose() ?? currentCoffeeData?.preferred_dose_g ?? '';
  $('worked-dose-input').value = dose === '' ? '' : String(dose);
  $('grind-input').value = suggestedGrindFromRecommendation(currentRecommendation);
  openDialog('grind-dialog');
});

$('btn-save-grind').addEventListener('click', () => saveFeedback({
  grind: $('grind-input').value.trim(),
  dose: parseFloat($('worked-dose-input').value),
}));
$('btn-skip-grind').addEventListener('click', () => closeDialog('grind-dialog'));

async function saveFeedback(worked) {
  closeDialog('grind-dialog');
  if (!currentCoffeeData || !currentRecommendation) return;

  const actualGrind = worked && worked.grind ? worked.grind : null;
  const doseUsed = worked && worked.dose > 0
    ? worked.dose
    : (currentScanDose() ?? currentCoffeeData.preferred_dose_g ?? null);

  try {
    const res = await fetch('/api/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        coffee_data:    currentCoffeeData,
        recommendation: currentRecommendation,
        actual_grind:   actualGrind,
        dose_g:         doseUsed,
        image_name:     currentCoffeeData.image_name ?? null,
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
    if (!res.ok) throw new Error(data.detail || 'Could not load equipment');

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
        <div class="setup-item-meta">⚙ ${escapeHtml(setup.grinder.brand)} ${escapeHtml(setup.grinder.model)} &nbsp;·&nbsp; ☕ ${escapeHtml(setup.machine.brand)} ${escapeHtml(setup.machine.model)}</div>
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
    const res = await fetch('/api/setups/active', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ setup_id: parsed, active_setup_id: parsed }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(getApiErrorMessage(data, 'Could not switch setup'));

    await Promise.all([loadSetups(), loadSettings()]);
    showToast('✅ Setup switched');
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

function clearEquipmentForm() {
  equipmentEditingId = null;
  $('equipment-form-title').textContent = 'Add equipment';
  $('equipment-form-type').value = 'grinder';
  $('equipment-form-brand').value = '';
  $('equipment-form-model').value = '';
  $('btn-cancel-equipment-edit').hidden = true;
}

function populateEquipmentForm(item) {
  equipmentEditingId = Number(item.id);
  $('equipment-form-title').textContent = `Edit ${item.brand} ${item.model}`;
  $('equipment-form-type').value = item.type || 'grinder';
  $('equipment-form-brand').value = item.brand || '';
  $('equipment-form-model').value = item.model || '';
  $('btn-cancel-equipment-edit').hidden = false;
  $('equipment-form-title').scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

function clearSetupForm() {
  $('setup-form-name').value = '';
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
}

async function saveSetupFromForm() {
  const payload = {
    name: $('setup-form-name').value.trim(),
    grinder_id: Number($('setup-form-grinder-id').value),
    machine_id: Number($('setup-form-machine-id').value),
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
    if (!res.ok) throw new Error(data.detail || 'Could not save setup');

    setupEditingId = null;
    clearSetupForm();
    $('setup-manager-title').textContent = 'Manage setups';
    await Promise.all([loadSetups(), loadSettings()]);
    showToast('✅ Setup saved');
  } catch (err) {
    showToast('❌ ' + (err.message || 'Could not save setup'));
  }
}

async function saveEquipmentFromForm() {
  const payload = {
    type: $('equipment-form-type').value,
    brand: $('equipment-form-brand').value.trim(),
    model: $('equipment-form-model').value.trim(),
  };

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
    showToast(isEdit ? '✅ Equipment updated' : '✅ Equipment saved');
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
    showToast('✅ Equipment deleted');
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
    if (!res.ok) throw new Error(data.detail || 'Could not delete setup');

    await Promise.all([loadSetups(), loadSettings()]);
    showToast('✅ Setup deleted');
  } catch (err) {
    showToast('❌ ' + (err.message || 'Could not delete setup'));
  }
}

$('btn-open-equipment-manager').addEventListener('click', () => openEquipmentManager());

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

/* ── Dismiss dialogs: tap the backdrop or press Escape ─────────────────── */
const DIALOG_DISMISS = {
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

/* ── Service worker registration ────────────────────────────────────────── */
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => {});
  });
}

loadSetups();

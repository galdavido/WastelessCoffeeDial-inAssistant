/* Admin dashboard.
 *
 * Everything is drawn as inline SVG built here -- the CSP is `default-src
 * 'self'`, so a charting library from a CDN would be blocked, and hand-rolled
 * SVG is what originArtwork() in app.js already does. For the same reason
 * nothing here writes a style="" attribute: dynamic geometry goes through
 * presentation attributes or element.style, which is CSSOM and allowed. */

'use strict';

const $ = (id) => document.getElementById(id);
const TOKEN_KEY = 'wcda-admin-token';

let days = 90;

/* ── Token ──────────────────────────────────────────────────────────────── */

function token() {
  try { return localStorage.getItem(TOKEN_KEY) || ''; } catch { return ''; }
}
function setToken(value) {
  try { value ? localStorage.setItem(TOKEN_KEY, value) : localStorage.removeItem(TOKEN_KEY); }
  catch { /* private window: the session still works, it just will not stick */ }
}

function showGate(message) {
  const gate = $('admin-gate');
  gate.hidden = false;
  $('admin-dash').hidden = true;
  if (message) {
    gate.classList.add('is-bad');
    $('admin-gate-note').textContent = message;
  }
  $('admin-token-input').focus();
}

/* ── Formatting ─────────────────────────────────────────────────────────── */

const escapeHtml = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
));

const pct = (v) => (v === null || v === undefined ? '—' : `${v}%`);

/* A rate in whatever unit reads as a real number. One recipe in ninety days is
   "0.1/wk", never "0/day" -- a rounded-to-nothing rate looks like no usage. */
function rate(count, days) {
  if (!count || !days) return '';
  const perDay = count / days;
  if (perDay >= 1) return `${perDay.toFixed(1)}/day`;
  if (perDay * 7 >= 1) return `${(perDay * 7).toFixed(1)}/wk`;
  return `${(perDay * 30).toFixed(1)}/mo`;
}

function sinceLabel(iso) {
  if (!iso) return { text: 'never', cls: '' };
  const hours = (Date.now() - new Date(iso).getTime()) / 36e5;
  if (hours < 1) return { text: 'just now', cls: 'fresh' };
  if (hours < 24) return { text: `${Math.round(hours)}h ago`, cls: 'fresh' };
  const d = Math.round(hours / 24);
  if (d === 1) return { text: 'yesterday', cls: 'fresh' };
  if (d < 14) return { text: `${d}d ago`, cls: '' };
  if (d < 60) return { text: `${Math.round(d / 7)}w ago`, cls: d > 28 ? 'stale' : '' };
  return { text: `${Math.round(d / 30)}mo ago`, cls: 'stale' };
}

const shortDate = (iso) => new Date(iso + 'T00:00:00Z').toLocaleDateString(undefined, {
  day: 'numeric', month: 'short', timeZone: 'UTC',
});

/* ── Hover layer ────────────────────────────────────────────────────────── */

function bindTip(host) {
  const tip = $('chart-tip');
  host.addEventListener('mousemove', (e) => {
    const mark = e.target.closest('[data-tip]');
    if (!mark) { tip.hidden = true; return; }
    tip.innerHTML = mark.getAttribute('data-tip');
    tip.hidden = false;
    // Flip to the left of the cursor near the right edge so it never clips.
    const w = tip.offsetWidth;
    const x = e.clientX + 14 + w > window.innerWidth ? e.clientX - 14 - w : e.clientX + 14;
    tip.style.left = `${Math.max(8, x)}px`;
    tip.style.top = `${Math.max(8, e.clientY - 12)}px`;
  });
  host.addEventListener('mouseleave', () => { tip.hidden = true; });
}

/* ── Weekly activity: one series, so one hue and no legend ──────────────── */

function renderWeekly(weeks) {
  const host = $('chart-weekly');
  if (!weeks.length) {
    host.innerHTML = '<p class="chart-empty">No shots logged in this window yet.</p>';
    return;
  }

  const W = 840, H = 240, padL = 42, padR = 8, padT = 14, padB = 30;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;
  const base = padT + plotH;

  const peak = Math.max(...weeks.map((w) => w.shots), 1);
  // A round ceiling so the gridline labels are readable numbers.
  const step = Math.max(1, Math.ceil(peak / 3 / 5) * 5);
  const top = step * 3;
  const y = (v) => base - (v / top) * plotH;

  const slot = plotW / weeks.length;
  const barW = Math.max(6, Math.min(48, slot - 14));

  const grid = [0, 1, 2, 3].map((i) => {
    const v = step * i;
    return `<line x1="${padL}" y1="${y(v)}" x2="${W - padR}" y2="${y(v)}"
                  stroke="${i ? 'var(--bg-input)' : 'var(--border)'}" stroke-width="1"/>
            <text x="${padL - 8}" y="${y(v) + 4}" text-anchor="end"
                  fill="var(--text-3)" font-size="11">${v}</text>`;
  }).join('');

  const bars = weeks.map((w, i) => {
    const h = Math.max(w.shots > 0 ? 2 : 0, base - y(w.shots));
    const x = padL + i * slot + (slot - barW) / 2;
    const last = i === weeks.length - 1;
    const tip = `Week of <b>${shortDate(w.week)}</b><br><b>${w.shots}</b> shots · `
      + `<b>${w.recommendations}</b> recipes<br><b>${w.people}</b> ${w.people === 1 ? 'person' : 'people'}`;
    return `<rect class="bar" x="${x.toFixed(1)}" y="${(base - h).toFixed(1)}"
                  width="${barW.toFixed(1)}" height="${h.toFixed(1)}" rx="4"
                  fill="${last ? 'var(--accent)' : 'var(--cat-1)'}"
                  data-tip="${escapeHtml(tip).replace(/&lt;(\/?b|br)&gt;/g, '<$1>')}"/>`;
  }).join('');

  // Every third week keeps the axis readable without labels colliding.
  const labels = weeks.map((w, i) => (
    (i % 3 === 0 || i === weeks.length - 1)
      ? `<text x="${padL + i * slot + slot / 2}" y="${H - 8}" text-anchor="middle"
              fill="var(--text-3)" font-size="11">${shortDate(w.week)}</text>`
      : ''
  )).join('');

  host.innerHTML =
    `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Shots logged per week">
       ${grid}${bars}${labels}
     </svg>`;
  bindTip(host);
}

/* ── Method mix: three series, so a legend AND direct labels ────────────── */

function renderMethods(methods) {
  const host = $('chart-methods');
  const total = methods.reduce((sum, m) => sum + m.shots, 0);
  if (!total) {
    host.innerHTML = '<p class="chart-empty">Nothing logged in this window.</p>';
    return;
  }
  const hue = (i) => `var(--cat-${(i % 3) + 1})`;

  const segs = methods.map((m, i) => {
    const el = document.createElement('div');
    el.className = 'mix-seg';
    el.style.width = `${(m.shots / total) * 100}%`;
    el.style.background = hue(i);
    return el;
  });
  const bar = document.createElement('div');
  bar.className = 'mix-bar';
  segs.forEach((s) => bar.appendChild(s));

  const legend = document.createElement('div');
  legend.className = 'mix-legend';
  methods.forEach((m, i) => {
    const row = document.createElement('div');
    row.className = 'mix-row';
    const sw = document.createElement('span');
    sw.className = 'mix-swatch';
    sw.style.background = hue(i);
    const name = document.createElement('span');
    name.className = 'mix-name';
    name.textContent = m.method;
    const val = document.createElement('span');
    val.className = 'mix-value';
    val.textContent = `${pct(m.share_pct)} · ${m.shots}`;
    row.append(sw, name, val);
    legend.appendChild(row);
  });

  host.replaceChildren(bar, legend);
}

/* ── Sparkline: 12 weeks of one person's shots ──────────────────────────── */

function sparkline(weekly, weeks) {
  const values = weeks.map((w) => weekly[w.week] || 0);
  if (!values.some((v) => v > 0)) return '<span class="kpi-aside">—</span>';
  const W = 130, H = 26, peak = Math.max(...values, 1);
  const step = values.length > 1 ? W / (values.length - 1) : 0;
  const pts = values.map((v, i) => `${(i * step).toFixed(1)},${(H - 3 - (v / peak) * (H - 6)).toFixed(1)}`);
  const [lx, ly] = pts[pts.length - 1].split(',');
  return `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" aria-hidden="true">
            <polyline points="${pts.join(' ')}" fill="none" stroke="var(--cat-1)"
                      stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            <circle cx="${lx}" cy="${ly}" r="2.6" fill="var(--accent)"/>
          </svg>`;
}

/* ── Painting ───────────────────────────────────────────────────────────── */

function renderKpis(s) {
  const change = s.shots_change_pct;
  const changeCls = change === null ? '' : change >= 0 ? 'is-up' : 'is-down';
  const changeText = change === null ? '' : `${change >= 0 ? '+' : ''}${change}%`;
  const dormant = s.owners_total - s.active_7d;

  $('kpi-row').innerHTML = [
    ['Active this week', s.active_7d, `of ${s.owners_total}`, '',
      dormant > 0
        ? `${dormant} ${dormant === 1 ? 'person has' : 'people have'} not opened it in a week.`
        : 'Everyone has been in this week.'],
    ['Shots logged', s.shots, changeText, changeCls, 'Against the previous window of the same length.'],
    ['Recipes requested', s.recommendations, rate(s.recommendations, s.days), '',
      'Each one is a Gemini call.'],
    ['Follow-through', pct(s.follow_through_pct), '', '',
      'Recipes that ended in a logged shot.'],
  ].map(([label, value, aside, cls, note]) => `
    <div class="kpi">
      <span class="kpi-label">${escapeHtml(label)}</span>
      <div class="kpi-figure">
        <span class="kpi-value">${escapeHtml(value)}</span>
        ${aside ? `<span class="kpi-aside ${cls}">${escapeHtml(aside)}</span>` : ''}
      </div>
      <span class="kpi-note">${escapeHtml(note)}</span>
    </div>`).join('');
}

function renderUsage(u) {
  $('usage-list').innerHTML = [
    ['Shots that used the timer', u.timer_pct],
    ['Shots with a measured yield', u.measured_pct],
    ['Shots pulled from a recipe', u.from_recipe_pct],
    ['Bags added by scanning', u.scanned_pct],
  ].map(([label, value]) => `
    <div class="usage-row">
      <span>${escapeHtml(label)}</span>
      <span class="usage-value">${pct(value)}</span>
    </div>`).join('');
}

function renderPeople(people, weeks) {
  const body = $('people-rows');
  if (!people.length) {
    body.innerHTML = '<tr><td colspan="9">Nobody has used it in this window.</td></tr>';
    return;
  }
  body.innerHTML = people.map((p) => {
    const seen = sinceLabel(p.last_seen);
    const ft = p.follow_through_pct;
    return `
      <tr class="${p.shots === 0 ? 'is-dormant' : ''}">
        <td class="owner">${escapeHtml(p.owner)}</td>
        <td class="num">${p.shots}</td>
        <td class="num">${p.coffees}</td>
        <td class="num">${p.recommendations}</td>
        <td>
          <div class="ft-cell">
            <div class="ft-track"><div class="ft-fill" data-ft="${ft === null ? 0 : ft}"></div></div>
            <span class="ft-value">${pct(ft)}</span>
          </div>
        </td>
        <td class="num">${pct(p.timer_pct)}</td>
        <td class="num">${p.active_days}</td>
        <td class="${seen.cls}">${escapeHtml(seen.text)}</td>
        <td class="num">${sparkline(p.weekly, weeks)}</td>
      </tr>`;
  }).join('');
  // Widths go on after the markup exists: CSSOM, not a style attribute.
  body.querySelectorAll('.ft-fill').forEach((el) => {
    el.style.width = `${el.getAttribute('data-ft')}%`;
  });
}

/* ── Load ───────────────────────────────────────────────────────────────── */

async function load() {
  const status = $('admin-status');
  status.textContent = 'Loading…';
  let res;
  try {
    res = await fetch(`/api/admin/stats?days=${days}`, {
      headers: { 'X-Admin-Token': token() },
      cache: 'no-store',
    });
  } catch {
    status.textContent = 'Could not reach the server.';
    return;
  }
  if (res.status === 401) {
    setToken('');
    showGate('That token was not accepted. Check WCDA_ADMIN_TOKEN in .env.');
    return;
  }
  if (!res.ok) {
    status.textContent = `The friends database did not answer (HTTP ${res.status}). `
      + 'Is the prod stack up?';
    return;
  }

  const data = await res.json();
  $('admin-gate').hidden = true;
  $('admin-dash').hidden = false;
  renderKpis(data.summary);
  renderWeekly(data.weekly);
  renderMethods(data.methods);
  renderUsage(data.usage);
  renderPeople(data.people, data.weekly);
  status.textContent = '';
  $('admin-source').textContent =
    `read-only view of the friends instance · ${new Date(data.generated_at).toLocaleTimeString()}`;
}

/* ── Wiring ─────────────────────────────────────────────────────────────── */

$('admin-gate-form').addEventListener('submit', (e) => {
  e.preventDefault();
  const value = $('admin-token-input').value.trim();
  if (!value) return;
  setToken(value);
  $('admin-gate').classList.remove('is-bad');
  load();
});

$('admin-forget').addEventListener('click', () => {
  setToken('');
  showGate('Token forgotten.');
});

$('admin-range').addEventListener('click', (e) => {
  const btn = e.target.closest('.admin-range-btn');
  if (!btn) return;
  days = Number(btn.dataset.days);
  $('admin-range').querySelectorAll('.admin-range-btn')
    .forEach((b) => b.classList.toggle('is-active', b === btn));
  load();
});

if (token()) load(); else showGate();

// ── Providers ──────────────────────────────────────────────────────────────
const HPC = new Set(["IONITY","Tesla Supercharger","Fastned","ARAL Pulse","Allego"]);
let providers = [];

async function loadProviders() {
  try {
    const res = await fetch('/providers');
    const data = await res.json();
    providers = data.providers;
    renderProviders();
  } catch(e) {
    providers = [
      {name:"IONITY",hpc:true},{name:"Tesla Supercharger",hpc:true},
      {name:"EnBW mobility+",hpc:false},{name:"Fastned",hpc:true},
      {name:"Allego",hpc:true},{name:"Maingau Energie",hpc:false},
      {name:"Lidl",hpc:false},{name:"ARAL Pulse",hpc:true},
      {name:"Shell Recharge",hpc:false},{name:"E.ON Drive",hpc:false},
      {name:"EWE Go",hpc:false},{name:"Total Energies",hpc:false},
    ];
    renderProviders();
  }
}

function renderProviders() {
  const grid = document.getElementById('providers-grid');
  grid.innerHTML = providers.map(p => `
    <label class="provider-chip" onclick="toggleChip(this)">
      <input type="checkbox" value="${p.name}">
      <span>${p.name}</span>
      ${p.hpc ? '<span class="chip-hpc">HPC</span>' : ''}
    </label>
  `).join('');
  updatePlanButton();
}

function toggleChip(label) {
  const cb = label.querySelector('input');
  setTimeout(() => {
    label.classList.toggle('selected', cb.checked);
    updatePlanButton();
  }, 0);
}

function filterProviders(query) {
  const q = query.toLowerCase().trim();
  document.querySelectorAll('.provider-chip').forEach(chip => {
    const name = chip.querySelector('input').value.toLowerCase();
    const match = !q || name.includes(q);
    if (!match) {
      chip.classList.add('filtered-out');
    } else {
      chip.classList.remove('filtered-out');
      chip.style.animation = 'chip-appear 0.2s ease';
      chip.addEventListener('animationend', () => chip.style.animation = '', { once: true });
    }
  });
}

function toggleAll() {
  const chips = document.querySelectorAll('.provider-chip:not(.filtered-out)');
  const anyChecked = [...chips].some(c => c.querySelector('input').checked);
  chips.forEach(chip => {
    const cb = chip.querySelector('input');
    cb.checked = !anyChecked;
    chip.classList.toggle('selected', !anyChecked);
  });
  updatePlanButton();
}

function updatePlanButton() {
  const selected = document.querySelectorAll('.provider-chip input:checked');
  const btn = document.getElementById('btn-plan');
  const hint = document.getElementById('provider-hint');
  if (selected.length === 0) {
    btn.disabled = true;
    if (hint) hint.style.display = 'block';
  } else {
    if (!btn.dataset.planning) btn.disabled = false;
    if (hint) hint.style.display = 'none';
  }
}

// ── Agent State ────────────────────────────────────────────────────────────
let currentAgent = 0;
const TOTAL_AGENTS = 4;

function setAgentActive(n) {
  for (let i = 1; i <= TOTAL_AGENTS; i++) {
    const el = document.getElementById(`agent-${i}`);
    el.classList.remove('active','done');
    if (i < n) el.classList.add('done');
    else if (i === n) el.classList.add('active');
  }
  currentAgent = n;
}

function setAgentStatus(n, msg) {
  document.getElementById(`status-${n}`).textContent = msg;
}

function resetAgents() {
  for (let i = 1; i <= TOTAL_AGENTS; i++) {
    document.getElementById(`agent-${i}`).classList.remove('active','done');
    document.getElementById(`status-${i}`).textContent = '';
  }
}

// ── Terminal Log ───────────────────────────────────────────────────────────
function log(msg, type = 'info') {
  const term = document.getElementById('terminal');
  const cursor = term.querySelector('.cursor');
  if (cursor) cursor.remove();

  const line = document.createElement('div');
  line.className = `log-line ${type}`;
  line.textContent = msg;
  term.appendChild(line);

  const newCursor = document.createElement('span');
  newCursor.className = 'cursor';
  term.appendChild(newCursor);

  term.scrollTop = term.scrollHeight;
}

// ── Planning ───────────────────────────────────────────────────────────────
async function startPlanning() {
  const origin = document.getElementById('origin').value.trim();
  const destination = document.getElementById('destination').value.trim();

  if (!origin || !destination) {
    alert('Bitte Start und Ziel eingeben.');
    return;
  }

  const selectedProviders = [...document.querySelectorAll('.provider-chip input:checked')]
    .map(cb => cb.value).join(',');

  if (!selectedProviders) {
    alert('Bitte mindestens einen Ladeanbieter auswaehlen.');
    return;
  }

  const payload = {
    origin,
    destination,
    range_km: parseFloat(document.getElementById('range_km').value),
    waypoints: document.getElementById('waypoints').value.trim(),
    preferred_providers: selectedProviders,
    min_power_kw: parseFloat(document.getElementById('min_power').value),
  };

  // UI state
  const btn = document.getElementById('btn-plan');
  btn.disabled = true;
  btn.dataset.planning = 'true';
  document.getElementById('idle-state').style.display = 'none';
  document.getElementById('result-card').classList.remove('visible');
  document.getElementById('terminal').innerHTML = '<span class="cursor"></span>';
  resetAgents();

  log(`Route: ${origin} → ${destination}`, 'info');
  log(`  Reichweite: ${payload.range_km} km | Min Leistung: ${payload.min_power_kw} kW`, 'info');

  setAgentActive(1);
  setAgentStatus(1, 'Geocodierung & Routenanalyse...');

  // 1) POST to start job
  let job_id;
  try {
    const res = await fetch('/plan-route', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`Server ${res.status}: ${text}`);
    }
    ({ job_id } = await res.json());
  } catch(err) {
    log(`Fehler beim Starten: ${err.message}`, 'error');
    document.getElementById('btn-plan').disabled = false;
    return;
  }

  // 2) GET SSE stream via EventSource
  const es = new EventSource(`/stream/${job_id}`);

  function onEvent(e) {
    try {
      const evt = JSON.parse(e.data);
      handleEvent(evt);
      if (evt.type === 'complete' || evt.type === 'error') {
        es.close();
        delete document.getElementById('btn-plan').dataset.planning;
        updatePlanButton();
      }
    } catch(err) {}
  }

  es.addEventListener('connected', onEvent);
  es.addEventListener('agent_start', onEvent);
  es.addEventListener('log', onEvent);
  es.addEventListener('complete', onEvent);
  es.addEventListener('error', onEvent);

  es.onerror = () => {
    es.close();
    document.getElementById('btn-plan').disabled = false;
  };
}

function handleEvent(evt) {
  switch (evt.type) {

    case 'agent_start':
      log(`${evt.agent} (${evt.model}): ${evt.message}`, 'info');
      break;

    case 'log':
      const msg = evt.message;
      if (msg.includes('EV Route Planner')) {
        if (currentAgent < 1) {
          setAgentActive(1);
          setAgentStatus(1, 'Analysiert Route...');
        }
      } else if (msg.includes('Charging Station Specialist')) {
        if (currentAgent < 2) {
          setAgentActive(2);
          setAgentStatus(2, 'Sucht Ladestationen...');
          setAgentStatus(1, 'Abgeschlossen');
        }
      } else if (msg.includes('Provider Quality Checker')) {
        if (currentAgent < 3) {
          setAgentActive(3);
          setAgentStatus(3, 'Validiert Anbieter...');
          setAgentStatus(2, 'Abgeschlossen');
        }
      } else if (msg.includes('Route Builder')) {
        if (currentAgent < 4) {
          setAgentActive(4);
          setAgentStatus(4, 'Baut Google Maps Link...');
          setAgentStatus(3, 'Abgeschlossen');
        }
      }

      const clean = msg.replace(/\x1b\[[0-9;]*m/g, '').trim();
      if (clean && clean.length > 2 && clean.length < 300) {
        log(clean);
      }
      break;

    case 'complete':
      setAgentActive(0);
      for (let i = 1; i <= TOTAL_AGENTS; i++) {
        document.getElementById(`agent-${i}`).classList.add('done');
        document.getElementById(`agent-${i}`).classList.remove('active');
      }
      setAgentStatus(TOTAL_AGENTS, 'Abgeschlossen');
      log('Route erfolgreich geplant!', 'success');
      renderResult(evt);
      break;

    case 'error':
      log(`Fehler: ${evt.message}`, 'error');
      setAgentStatus(currentAgent, 'Fehler');
      document.getElementById('btn-plan').disabled = false;
      break;
  }
}

// ── Result Renderer ─────────────────────────────────────────────────────────
function renderResult(evt) {
  const raw = evt.result || '';
  const resultCard = document.getElementById('result-card');
  const resultText = document.getElementById('result-text');
  const mapsLink = document.getElementById('maps-link');
  const summaryEl = document.getElementById('route-summary');
  const stationsEl = document.getElementById('stations-list');
  const stationsSection = document.getElementById('stations-section');
  const endpointsEl = document.getElementById('route-endpoints');

  // Raw text in collapsible section
  resultText.textContent = raw;

  // Use server-parsed stations if available, otherwise parse client-side
  const stations = (evt.stations && evt.stations.length > 0)
    ? evt.stations
    : parseStations(evt.full_log || raw);

  // Parse route info from full log (more data) or raw result
  const searchText = evt.full_log || raw;
  const distMatch = searchText.match(/(?:TOTAL_DISTANCE|Gesamtdistanz|Gesamtstrecke|Distanz|distance)[\s:]*(\d[\d.,]*)\s*km/i);
  const totalDist = distMatch ? distMatch[1] : null;
  const durationMatch = searchText.match(/(?:Fahrzeit|duration)[\s:]*(\d+h\s*\d+min)/i);
  const duration = durationMatch ? durationMatch[1] : null;

  // Route endpoints (Start → Zwischenstopps → Ziel)
  const origin = document.getElementById('origin').value.trim();
  const destination = document.getElementById('destination').value.trim();
  const waypoints = document.getElementById('waypoints').value.trim();
  let endpointsHTML = `
    <div>
      <div class="route-ep-label">Start</div>
      <div class="route-ep-name">${escHtml(origin)}</div>
    </div>`;
  if (waypoints) {
    const wpList = waypoints.split(',').map(w => w.trim()).filter(Boolean);
    for (const wp of wpList) {
      endpointsHTML += `
        <div class="route-ep-arrow">→</div>
        <div>
          <div class="route-ep-label">Zwischenstop</div>
          <div class="route-ep-name">${escHtml(wp)}</div>
        </div>`;
    }
  }
  endpointsHTML += `
    <div class="route-ep-arrow">→</div>
    <div style="flex:1">
      <div class="route-ep-label">Ziel</div>
      <div class="route-ep-name">${escHtml(destination)}</div>
    </div>`;
  endpointsEl.innerHTML = endpointsHTML;

  // Summary bar
  let summaryHTML = '';
  if (totalDist) {
    summaryHTML += `<div class="route-stat"><div class="route-stat-label">Distanz</div><div class="route-stat-value">${totalDist} km</div></div>`;
  }
  if (duration) {
    summaryHTML += `<div class="route-stat"><div class="route-stat-label">Fahrzeit</div><div class="route-stat-value">${duration}</div></div>`;
  }
  summaryHTML += `<div class="route-stat"><div class="route-stat-label">Ladestopps</div><div class="route-stat-value">${stations.length}</div></div>`;
  if (stations.length > 0) {
    const providerSet = [...new Set(stations.map(s => s.provider).filter(Boolean))];
    if (providerSet.length > 0) {
      summaryHTML += `<div class="route-stat"><div class="route-stat-label">Anbieter</div><div class="route-stat-value" style="font-size:13px">${providerSet.join(', ')}</div></div>`;
    }
  }
  summaryEl.innerHTML = summaryHTML;

  // Station cards
  if (stations.length > 0) {
    stationsSection.style.display = 'block';
    stationsEl.innerHTML = stations.map((s, i) => `
      <div class="station-card">
        <div class="station-number">${i + 1}</div>
        <div class="station-info">
          <div class="station-name">${escHtml(s.name)}</div>
          <div class="station-details">
            ${s.provider ? `<span class="station-detail">${escHtml(s.provider)}</span>` : ''}
            ${s.address ? `<span class="station-detail">${escHtml(s.address)}</span>` : ''}
          </div>
        </div>
        ${s.power ? `<div class="station-power">${escHtml(s.power)}</div>` : ''}
      </div>
    `).join('');
  } else {
    stationsSection.style.display = 'none';
    stationsEl.innerHTML = '';
  }

  // Maps link
  let url = evt.maps_url || null;
  if (!url) {
    const urlMatch = raw.match(/https:\/\/www\.google\.com\/maps\/dir\/[^\s\n)>*]*/);
    if (urlMatch) url = urlMatch[0].replace(/[*).>,;'"]+$/, '');
  }
  // Clean any trailing markdown artifacts from URL
  if (url) url = url.replace(/[*).>,;'"]+$/, '');
  if (url) {
    mapsLink.href = url;
    mapsLink.style.display = 'flex';
  } else {
    mapsLink.style.display = 'none';
  }

  resultCard.classList.add('visible');
}

function parseStations(text) {
  const stations = [];

  // Strategy 1: Split on numbered station/stop headers (many formats)
  const headerPattern = /(?:STATION\s*\d+\s*:|---\s*Station\s*\d+\s*---|(?:^|\n)\s*Station\s*\d+\s*:|STOP\s*\d+\s*:|\*\*\s*(?:Station|Stop|Ladestopp)\s*\d+[\s:]*\*\*|(?:^|\n)\s*\d+[\.\)]\s+(?:Station|Stop|Ladestopp|Charging))/gim;

  // Find all header positions
  const headers = [];
  let m;
  while ((m = headerPattern.exec(text)) !== null) {
    headers.push(m.index);
  }

  if (headers.length > 0) {
    for (let i = 0; i < headers.length; i++) {
      const start = headers[i];
      const end = i + 1 < headers.length ? headers[i + 1] : text.length;
      const block = text.substring(start, end);
      const station = parseStationBlock(block, i + 1);
      if (station) stations.push(station);
    }
  }

  // Strategy 2: If no headers found, try line-by-line for "Name - Provider" patterns
  if (stations.length === 0) {
    const lines = text.split('\n');
    for (const line of lines) {
      // Match patterns like "- IONITY Alsfeld Nord (IONITY, 350 kW)"
      const lineMatch = line.match(/[-•]\s*(.+?)\s*\(([^,)]+),?\s*(\d+\s*kW)?\)/);
      if (lineMatch) {
        stations.push({
          name: lineMatch[1].trim().replace(/\*\*/g, ''),
          provider: lineMatch[2].trim(),
          power: lineMatch[3] || '',
          address: '',
          coords: '',
        });
      }
    }
  }

  // Strategy 3: Look for coordinate patterns with names
  if (stations.length === 0) {
    const coordLines = text.match(/(.+?):\s*(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)/g);
    if (coordLines) {
      for (const cl of coordLines) {
        const cm = cl.match(/(.+?):\s*(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)/);
        if (cm && !cm[1].match(/(?:START|DESTINATION|ORIGIN|ZIEL|Von|Nach)/i)) {
          stations.push({
            name: cm[1].trim().replace(/^[\d.\-*)\s]+/, ''),
            provider: '',
            power: '',
            address: '',
            coords: `${cm[2]}, ${cm[3]}`,
          });
        }
      }
    }
  }

  return stations;
}

function parseStationBlock(block, idx) {
  const station = {};
  const clean = block.replace(/\*\*/g, '');

  // Name
  const nameMatch = clean.match(/(?:Name|Station|Ladestopp)\s*(?:\d+)?\s*[:]\s*(.+)/i);
  station.name = nameMatch ? nameMatch[1].trim() : '';
  if (!station.name) {
    const firstLine = clean.match(/(?:STATION|STOP|Station|Stop)\s*\d+\s*[:.]?\s*(.+)/i);
    if (firstLine) station.name = firstLine[1].trim().replace(/^[:\-*\s]+/, '');
  }
  if (!station.name) {
    const lines = clean.split('\n').filter(l => l.trim());
    if (lines.length > 0) station.name = lines[0].trim().replace(/^[\d.\-*:)\s]+/, '');
  }

  // Provider
  const provMatch = clean.match(/(?:PROVIDER|Anbieter|Operator|Betreiber)\s*[:]\s*(.+)/i);
  station.provider = provMatch ? provMatch[1].trim().replace(/\s*\(ID:.*\)/, '').replace(/\*\*/g, '') : '';

  // Power
  const powerMatch = clean.match(/(\d+)\s*kW/i);
  station.power = powerMatch ? `${powerMatch[1]} kW` : '';

  // Address
  const addrMatch = clean.match(/(?:ADDRESS|Adresse|Ort)\s*[:]\s*(.+)/i);
  station.address = addrMatch ? addrMatch[1].trim() : '';

  // Coords
  const coordMatch = clean.match(/(?:COORDS|Koordinaten|GPS|coordinates|Coord)\s*[:]\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)/i);
  station.coords = coordMatch ? `${coordMatch[1]}, ${coordMatch[2]}` : '';

  if (station.name && station.name.length > 1) {
    return station;
  }
  return null;
}

function escHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// ── Init ───────────────────────────────────────────────────────────────────
loadProviders();

fetch('/health').then(r => r.json()).then(data => {
  const missing = Object.entries(data.api_keys)
    .filter(([k,v]) => !v).map(([k]) => k);
  if (missing.length) {
    log(`API Keys fehlen: ${missing.join(', ')}`, 'error');
  } else {
    log('Alle API Keys konfiguriert.', 'success');
  }
}).catch(() => {});

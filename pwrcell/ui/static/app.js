/**
 * PWRcell Explorer v3 Single-Page Reactive Client.
 */

// Base path helper for Home Assistant Ingress compatibility
const getApiBase = () => {
  const p = window.location.pathname;
  return p.endsWith('/') ? p : p + '/';
};
const apiPath = (endpoint) => `${getApiBase()}${endpoint.replace(/^\//, '')}`;

// Application State
const state = {
  devices: [],
  activeDevice: null,
  activeDeviceModels: [],
  selectedModel: 'all',
  groupByModel: false,
  activeFields: [],
  selectedHaKeys: new Set(),
  modifiedDeviceSerials: new Set(),
  activeFilter: 'all',
  hideScaleFactors: true,
  hideCombinedRaw: true,
  searchQuery: '',
  isMock: false,
  eventSource: null,
  sortCriteria: [], // [{ column: 'model', dir: 'asc' }, ...]
  multiSortMode: false,
};

// DOM Elements
const el = {
  deviceList: document.getElementById('deviceList'),
  deviceCountBadge: document.getElementById('deviceCountBadge'),
  activeDeviceName: document.getElementById('activeDeviceName'),
  activeDeviceSerial: document.getElementById('activeDeviceSerial'),
  activeDeviceSlaveId: document.getElementById('activeDeviceSlaveId'),
  activeDeviceVersion: document.getElementById('activeDeviceVersion'),
  activeDeviceModelCount: document.getElementById('activeDeviceModelCount'),
  activeDeviceFieldCount: document.getElementById('activeDeviceFieldCount'),
  btnPollAllModels: document.getElementById('btnPollAllModels'),
  fieldTableBody: document.getElementById('fieldTableBody'),
  searchInput: document.getElementById('searchInput'),
  searchClear: document.getElementById('searchClear'),
  modelSelect: document.getElementById('modelSelect'),
  groupByModel: document.getElementById('groupByModel'),
  filterPills: document.getElementById('filterPills'),
  hideScaleFactors: document.getElementById('hideScaleFactors'),
  hideCombinedRaw: document.getElementById('hideCombinedRaw'),
  multiSortToggle: document.getElementById('multiSortToggle'),
  sortBar: document.getElementById('sortBar'),
  sortPills: document.getElementById('sortPills'),
  btnClearSort: document.getElementById('btnClearSort'),
  topSolar: document.getElementById('topSolar'),
  topLoad: document.getElementById('topLoad'),
  topGrid: document.getElementById('topGrid'),
  topBattery: document.getElementById('topBattery'),
  modeSelect: document.getElementById('modeSelect'),
  modeTag: document.getElementById('modeTag'),
  haSelectedCount: document.getElementById('haSelectedCount'),
  btnSelectRecommended: document.getElementById('btnSelectRecommended'),
  btnDeselectAll: document.getElementById('btnDeselectAll'),
  btnApplySameType: document.getElementById('btnApplySameType'),
  btnPreviewHA: document.getElementById('btnPreviewHA'),
  btnSaveHA: document.getElementById('btnSaveHA'),
  previewModal: document.getElementById('previewModal'),
  previewCode: document.getElementById('previewCode'),
  btnCloseModal: document.getElementById('btnCloseModal'),
  btnClosePreview: document.getElementById('btnClosePreview'),
  btnCopyPreview: document.getElementById('btnCopyPreview'),
  writeModal: document.getElementById('writeModal'),
  writeModalTitle: document.getElementById('writeModalTitle'),
  writeModalDesc: document.getElementById('writeModalDesc'),
  writeInputContainer: document.getElementById('writeInputContainer'),
  btnCancelWrite: document.getElementById('btnCancelWrite'),
  btnCancelWriteModal: document.getElementById('btnCancelWriteModal'),
  btnConfirmWrite: document.getElementById('btnConfirmWrite'),
  btnOpenCompare: document.getElementById('btnOpenCompare'),
  btnSyncModbus: document.getElementById('btnSyncModbus'),
  compareModal: document.getElementById('compareModal'),
  btnCloseCompare: document.getElementById('btnCloseCompare'),
  btnCloseCompareFooter: document.getElementById('btnCloseCompareFooter'),
  compareTableBody: document.getElementById('compareTableBody'),
  unrecCompareSection: document.getElementById('unrecCompareSection'),
  unrecCount: document.getElementById('unrecCount'),
  unrecTableBody: document.getElementById('unrecTableBody'),
  toast: document.getElementById('toast'),
  counts: {
    all: document.getElementById('countAll'),
    compound: document.getElementById('countCompound'),
    selected: document.getElementById('countSelected'),
    sensor: document.getElementById('countSensors'),
    writable: document.getElementById('countWritable'),
    push: document.getElementById('countPush'),
    modbus: document.getElementById('countModbus'),
    scalefactor: document.getElementById('countScaleFactor'),
  }
};

// Initialize Application
async function initApp() {
  setupEventListeners();
  updateSortUI();
  await Promise.all([
    fetchOverview(),
    fetchHaConfig(),
  ]);
  await fetchDevices();
  connectSSE();
}

// Fetch Overview Data
async function fetchOverview() {
  try {
    const res = await fetch(apiPath('api/overview'));
    const data = await res.json();
    updateOverviewUI(data);
  } catch (err) {
    console.error('Failed fetching overview:', err);
  }
}

function updateOverviewUI(data) {
  state.isMock = data.is_mock;
  el.modeTag.textContent = data.is_mock ? 'Simulator' : 'Live Unit';
  el.modeTag.style.borderColor = data.is_mock ? '#3b82f640' : '#10b98140';
  el.modeTag.style.color = data.is_mock ? '#3b82f6' : '#10b981';

  el.topSolar.textContent = `${data.solar_power_w} W`;
  el.topLoad.textContent = `${data.load_power_w} W`;
  el.topGrid.textContent = `${data.grid_power_w} W`;

  const socStr = data.battery_soc !== null ? `${data.battery_soc}%` : '--%';
  el.topBattery.textContent = `${socStr} (${data.battery_power_w} W)`;

  if (data.system_mode !== undefined && data.system_mode !== null && el.modeSelect) {
    const modeMap = {
      0: 'SAFETY_SHUTDOWN',
      1: 'GRID_CONNECT',
      2: 'SELF_SUPPLY',
      3: 'CLEAN_BACKUP',
      4: 'PRIORITY_BACKUP',
      5: 'ARBITRAGE',
      6: 'FULL_EXPORT',
      'GRID_TIE': 'GRID_CONNECT',
      'REMOTE_ARBITRAGE': 'ARBITRAGE',
      'SELL': 'FULL_EXPORT',
    };
    const norm = modeMap[data.system_mode] || String(data.system_mode).toUpperCase();
    for (let i = 0; i < el.modeSelect.options.length; i++) {
      const optVal = el.modeSelect.options[i].value;
      if (optVal === norm || modeMap[optVal] === norm || optVal === String(data.system_mode)) {
        el.modeSelect.selectedIndex = i;
        break;
      }
    }
  }
}

// Fetch Saved HA Config
async function fetchHaConfig() {
  try {
    const res = await fetch(apiPath('api/ha/config'));
    const data = await res.json();
    state.selectedHaKeys = new Set(data.selected_fields || []);
    updateHaCounter();
    updateFilterCounts();
    if (state.activeDevice) {
      renderFieldTable();
    }
  } catch (err) {
    console.error('Failed fetching HA config:', err);
  }
}

// Fetch All Devices
async function fetchDevices() {
  try {
    const res = await fetch(apiPath('api/devices'));
    state.devices = await res.json();
    renderDeviceSidebar();

    if (state.devices.length > 0 && !state.activeDevice) {
      selectDevice(state.devices[0].serial_number);
    }
  } catch (err) {
    console.error('Failed fetching devices:', err);
  }
}

// Render Device Sidebar
function renderDeviceSidebar() {
  el.deviceCountBadge.textContent = state.devices.length;
  el.deviceList.innerHTML = '';

  state.devices.forEach(dev => {
    const card = document.createElement('div');
    card.className = `device-card ${state.activeDevice?.serial_number === dev.serial_number ? 'active' : ''}`;
    card.dataset.sn = dev.serial_number;

    const typeIcons = {
      inverter: '⚡',
      battery: '🔋',
      rebus_beacon: '🛰️',
      pv_link: '☀️',
      icm: '🎛️'
    };

    card.innerHTML = `
      <div class="device-card-header">
        <span class="device-title">${typeIcons[dev.device_type] || '📦'} ${dev.model_name}</span>
        <span class="device-type-tag">${dev.device_type.replace('_', ' ')}</span>
      </div>
      <div class="device-card-body">
        <span>SN: ${dev.serial_number}</span> &bull; <span>ID: ${dev.slave_id ?? 'N/A'}</span>
      </div>
    `;

    card.addEventListener('click', () => selectDevice(dev.serial_number));
    el.deviceList.appendChild(card);
  });
}

// Format device type plural label
function formatDeviceTypePlural(type) {
  if (!type) return 'Devices';
  switch (type) {
    case 'pv_link': return 'PV Links';
    case 'battery': return 'Batteries';
    case 'inverter': return 'Inverters';
    case 'rebus_beacon': return 'Beacons';
    case 'icm': return 'ICMs';
    default:
      return type.replace('_', ' ') + 's';
  }
}

// Select a Device
async function selectDevice(serialNumber) {
  const dev = state.devices.find(d => d.serial_number === serialNumber);
  if (!dev) return;

  state.activeDevice = dev;
  renderDeviceSidebar();

  el.activeDeviceName.textContent = dev.model_name;
  el.activeDeviceSerial.textContent = dev.serial_number;
  el.activeDeviceSlaveId.textContent = dev.slave_id ?? 'N/A';
  el.activeDeviceVersion.textContent = dev.version || 'v1.0';

  if (el.btnApplySameType) {
    const peerDevices = (state.devices || []).filter(d => d.device_type === dev.device_type);
    if (peerDevices.length > 1) {
      const typeLabel = formatDeviceTypePlural(dev.device_type);
      el.btnApplySameType.style.display = 'inline-flex';
      el.btnApplySameType.textContent = `📋 Apply to All ${typeLabel} (${peerDevices.length})`;
      el.btnApplySameType.title = `Apply current selected fields to all ${peerDevices.length} ${typeLabel}`;
    } else {
      el.btnApplySameType.style.display = 'none';
    }
  }

  el.fieldTableBody.innerHTML = `<tr><td colspan="8" class="empty-state">Loading fields...</td></tr>`;

  try {
    const [devRes, haRes] = await Promise.all([
      fetch(apiPath(`api/devices/${serialNumber}`)),
      fetch(apiPath('api/ha/config')),
    ]);
    const data = await devRes.json();

    if (haRes.ok) {
      try {
        const haData = await haRes.json();
        if (Array.isArray(haData.selected_fields)) {
          const serverKeys = haData.selected_fields;
          const unmodifiedSerials = new Set(
            (state.devices || [])
              .map(d => (d.serial_number || '').trim().toUpperCase())
              .filter(sn => sn && !state.modifiedDeviceSerials.has(sn))
          );

          // Clear keys for devices that haven't been locally modified
          for (const k of Array.from(state.selectedHaKeys)) {
            const sn = k.includes(':') ? k.split(':')[0].trim().toUpperCase() : null;
            if (sn && unmodifiedSerials.has(sn)) {
              state.selectedHaKeys.delete(k);
            }
          }

          // Merge authoritative server keys
          serverKeys.forEach(k => {
            const sn = k.includes(':') ? k.split(':')[0].trim().toUpperCase() : null;
            if (!sn || unmodifiedSerials.has(sn)) {
              state.selectedHaKeys.add(k);
            }
          });
          updateHaCounter();
        }
      } catch (e) {
        console.warn('Failed parsing HA config response:', e);
      }
    }

    const rawFields = Object.values(data.fields || {});
    const compoundFields = (data.compound_fields || []).map(cf => ({
      ...cf,
      is_compound: true,
    }));

    // Build lookup of raw keys that are covered by compound fields on this device
    const combinedRawKeys = new Set();
    const compoundKeyByRaw = new Map();
    for (const cf of compoundFields) {
      if (cf.mqtt_key) {
        combinedRawKeys.add(cf.mqtt_key);
        compoundKeyByRaw.set(cf.mqtt_key, cf.key);
      }
      if (cf.modbus_key) {
        combinedRawKeys.add(cf.modbus_key);
        compoundKeyByRaw.set(cf.modbus_key, cf.key);
      }
      if (Array.isArray(cf.modbus_candidates)) {
        for (const cand of cf.modbus_candidates) {
          combinedRawKeys.add(cand);
          compoundKeyByRaw.set(cand, cf.key);
        }
      }
    }

    rawFields.forEach(f => {
      if (f.is_compound_raw || combinedRawKeys.has(f.key) || (f.mqtt_equivalent && combinedRawKeys.has(f.mqtt_equivalent))) {
        f.is_compound_raw = true;
        f.compound_key = f.compound_key || compoundKeyByRaw.get(f.key) || compoundKeyByRaw.get(f.mqtt_equivalent);
      }
    });

    // Compound fields first, then raw fields
    state.activeFields = [...compoundFields, ...rawFields];
    el.activeDeviceFieldCount.textContent = state.activeFields.length;
    state.activeDeviceModels = data.models || [];
    if (el.activeDeviceModelCount) {
      el.activeDeviceModelCount.textContent = state.activeDeviceModels.length || (dev.supported_models ? dev.supported_models.length : '--');
    }
    populateModelDropdown(state.activeDeviceModels, state.activeFields);
    updateFilterCounts();
    renderFieldTable();
  } catch (err) {
    console.error('Failed fetching device fields:', err);
  }
}

// Populate Model Selector Dropdown
function populateModelDropdown(models, fields) {
  if (!el.modelSelect) return;
  const currentVal = state.selectedModel;
  el.modelSelect.innerHTML = '';

  const optAll = document.createElement('option');
  optAll.value = 'all';
  optAll.textContent = `All Models (${models.length} models, ${fields.length} points)`;
  el.modelSelect.appendChild(optAll);

  // Add an option for Merged / Compound if compound fields exist
  const compoundCount = fields.filter(f => f.is_compound).length;
  if (compoundCount > 0) {
    const optComp = document.createElement('option');
    optComp.value = 'compound';
    optComp.textContent = `⚡ Merged Telemetry (${compoundCount} points)`;
    el.modelSelect.appendChild(optComp);
  }

  models.forEach(m => {
    const count = fields.filter(f => f.model_id === m.model_id).length;
    const opt = document.createElement('option');
    opt.value = String(m.model_id);
    opt.textContent = `Model ${m.model_id}: ${m.label || m.name} (${count} points)`;
    el.modelSelect.appendChild(opt);
  });

  // Preserve previous selection if still valid
  const hasMatch = Array.from(el.modelSelect.options).some(o => o.value === currentVal);
  if (hasMatch) {
    el.modelSelect.value = currentVal;
    state.selectedModel = currentVal;
  } else {
    el.modelSelect.value = 'all';
    state.selectedModel = 'all';
  }
}

// Column labels for sort bar and tooltips
const COLUMN_LABELS = {
  ha: 'HA Export',
  model: 'Model #',
  name: 'Field Name',
  value: 'Current Value',
  unit: 'Unit',
  source: 'Source',
  type: 'Type / Platform',
};

// Helper to get device serial number for a field or fallback to active device
function getFieldDeviceSn(f) {
  return (f?.device_sn || state.activeDevice?.serial_number || '').trim().toUpperCase();
}

// Check if a field is selected for Home Assistant (supports device-scoped and legacy global keys)
function isFieldSelected(f) {
  if (!f) return false;
  const sn = getFieldDeviceSn(f);
  if (sn) {
    if (state.selectedHaKeys.has(`${sn}:${f.key}`)) return true;
    if (f.mqtt_key && state.selectedHaKeys.has(`${sn}:${f.mqtt_key}`)) return true;
  }
  // Fall back to legacy global key
  if (state.selectedHaKeys.has(f.key)) return true;
  if (f.mqtt_key && state.selectedHaKeys.has(f.mqtt_key)) return true;
  return false;
}

// Toggle Home Assistant Field Selection (scoped by device)
function toggleHaSelection(f, isSelected) {
  const sn = getFieldDeviceSn(f);
  if (sn) {
    state.modifiedDeviceSerials.add(sn);
  }
  const scopedKey = sn ? `${sn}:${f.key}` : f.key;
  const scopedMqttKey = (sn && f.mqtt_key) ? `${sn}:${f.mqtt_key}` : f.mqtt_key;

  if (isSelected) {
    state.selectedHaKeys.add(scopedKey);
  } else {
    state.selectedHaKeys.delete(scopedKey);
    state.selectedHaKeys.delete(f.key);
    if (scopedMqttKey) state.selectedHaKeys.delete(scopedMqttKey);
    if (f.mqtt_key) state.selectedHaKeys.delete(f.mqtt_key);
  }
  updateHaCounter();
  updateFilterCounts();
}

// Value extraction helpers for multi-column sorting
function getHaSortValue(f) {
  return isFieldSelected(f) ? 1 : 0;
}

function getModelSortValue(f) {
  if (f.is_compound) return -1;
  if (f.model_id !== undefined && f.model_id !== null) {
    const num = Number(f.model_id);
    return isNaN(num) ? 999999 : num;
  }
  if (f.source === 'MQTT_PUSH') return 900000;
  return 999999;
}

function getNameSortValue(f) {
  return (f.label || f.name || f.key || '').toLowerCase();
}

function getValueSortValue(f) {
  const val = f.is_compound ? f.latest_value : f.value;
  if (val === null || val === undefined || val === '') {
    return { isNull: true, num: null, str: '' };
  }
  if (typeof val === 'boolean') {
    return { isNull: false, num: val ? 1 : 0, str: val ? 'true' : 'false' };
  }
  if (typeof val === 'number') {
    return { isNull: false, num: val, str: String(val) };
  }
  if (typeof val === 'string') {
    const trimmed = val.trim();
    if (trimmed !== '' && !isNaN(trimmed) && !isNaN(parseFloat(trimmed))) {
      return { isNull: false, num: parseFloat(trimmed), str: trimmed.toLowerCase() };
    }
    return { isNull: false, num: null, str: trimmed.toLowerCase() };
  }
  return { isNull: false, num: null, str: String(val).toLowerCase() };
}

function getUnitSortValue(f) {
  return (f.units || '').toLowerCase();
}

function getSourceSortValue(f) {
  if (f.is_compound) return '1_compound';
  if (f.source === 'MQTT_PUSH') return '2_mqtt_push';
  if (f.source === 'MODBUS_POLL') return '3_modbus_poll';
  if (f.source === 'MODBUS_CONFIG') return '4_modbus_config';
  return (f.source || '').toLowerCase();
}

function getTypeSortValue(f) {
  return `${f.ha_platform || ''} ${f.ha_device_class || ''}`.trim().toLowerCase();
}

// Multi-column comparator
function compareFields(a, b, sortCriteria) {
  for (const { column, dir } of sortCriteria) {
    const factor = dir === 'desc' ? -1 : 1;
    let cmp = 0;

    switch (column) {
      case 'ha': {
        cmp = getHaSortValue(a) - getHaSortValue(b);
        break;
      }
      case 'model': {
        cmp = getModelSortValue(a) - getModelSortValue(b);
        break;
      }
      case 'name': {
        cmp = getNameSortValue(a).localeCompare(getNameSortValue(b));
        if (cmp === 0) {
          cmp = (a.key || '').localeCompare(b.key || '');
        }
        break;
      }
      case 'value': {
        const aV = getValueSortValue(a);
        const bV = getValueSortValue(b);
        if (aV.isNull && bV.isNull) {
          cmp = 0;
        } else if (aV.isNull) {
          return 1; // nulls always sort to bottom
        } else if (bV.isNull) {
          return -1; // nulls always sort to bottom
        } else if (aV.num !== null && bV.num !== null) {
          cmp = aV.num - bV.num;
        } else if (aV.num !== null && bV.num === null) {
          cmp = -1; // numbers before strings
        } else if (aV.num === null && bV.num !== null) {
          cmp = 1;
        } else {
          cmp = aV.str.localeCompare(bV.str);
        }
        break;
      }
      case 'unit': {
        const aU = getUnitSortValue(a);
        const bU = getUnitSortValue(b);
        if (!aU && !bU) cmp = 0;
        else if (!aU) cmp = 1;
        else if (!bU) cmp = -1;
        else cmp = aU.localeCompare(bU);
        break;
      }
      case 'source': {
        cmp = getSourceSortValue(a).localeCompare(getSourceSortValue(b));
        break;
      }
      case 'type': {
        cmp = getTypeSortValue(a).localeCompare(getTypeSortValue(b));
        break;
      }
    }

    if (cmp !== 0) {
      return cmp * factor;
    }
  }
  return 0;
}

// Column header click handler (supports Shift+click and Multi-Sort mode)
function handleColumnHeaderClick(column, isShiftPressed) {
  const isMulti = isShiftPressed || state.multiSortMode;
  const existingIdx = state.sortCriteria.findIndex(c => c.column === column);

  if (isMulti) {
    if (existingIdx >= 0) {
      const cur = state.sortCriteria[existingIdx];
      if (cur.dir === 'asc') {
        cur.dir = 'desc';
      } else {
        // Remove from sort criteria when cycling past desc
        state.sortCriteria.splice(existingIdx, 1);
      }
    } else {
      state.sortCriteria.push({ column, dir: 'asc' });
    }
    if (isShiftPressed && el.multiSortToggle && !el.multiSortToggle.checked) {
      el.multiSortToggle.checked = true;
      state.multiSortMode = true;
    }
  } else {
    if (state.sortCriteria.length === 1 && state.sortCriteria[0].column === column) {
      const cur = state.sortCriteria[0];
      if (cur.dir === 'asc') {
        cur.dir = 'desc';
      } else {
        state.sortCriteria = [];
      }
    } else {
      state.sortCriteria = [{ column, dir: 'asc' }];
    }
  }

  updateSortUI();
  renderFieldTable();
}

// Update Sort UI (header icons, badges, sort status bar)
function updateSortUI() {
  document.querySelectorAll('.field-table thead th.sortable').forEach(th => {
    const col = th.dataset.sort;
    const idx = state.sortCriteria.findIndex(c => c.column === col);
    const indicator = th.querySelector('.sort-indicator');

    th.classList.remove('sorted', 'sorted-asc', 'sorted-desc');

    if (idx >= 0) {
      const { dir } = state.sortCriteria[idx];
      th.classList.add('sorted', dir === 'asc' ? 'sorted-asc' : 'sorted-desc');
      const arrow = dir === 'asc' ? '▲' : '▼';
      const badge = state.sortCriteria.length > 1 ? `<span class="sort-priority">${idx + 1}</span>` : '';
      if (indicator) {
        indicator.innerHTML = `${arrow}${badge}`;
      }
    } else {
      if (indicator) {
        indicator.innerHTML = `<span class="sort-faint">⇅</span>`;
      }
    }
  });

  if (el.sortBar && el.sortPills) {
    if (state.sortCriteria.length === 0) {
      el.sortBar.style.display = 'none';
      el.sortPills.innerHTML = '';
    } else {
      el.sortBar.style.display = 'flex';
      el.sortPills.innerHTML = '';

      state.sortCriteria.forEach((crit, i) => {
        const pill = document.createElement('div');
        pill.className = 'sort-pill';
        const arrow = crit.dir === 'asc' ? '▲' : '▼';
        const label = COLUMN_LABELS[crit.column] || crit.column;

        pill.innerHTML = `
          <span class="sort-pill-idx">${i + 1}</span>
          <span class="sort-pill-name">${label}</span>
          <span class="sort-pill-arrow">${arrow}</span>
          <span class="sort-pill-remove" title="Remove ${label} from sort">&times;</span>
        `;

        pill.addEventListener('click', (e) => {
          if (e.target.classList.contains('sort-pill-remove')) return;
          crit.dir = crit.dir === 'asc' ? 'desc' : 'asc';
          updateSortUI();
          renderFieldTable();
        });

        const removeBtn = pill.querySelector('.sort-pill-remove');
        removeBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          state.sortCriteria.splice(i, 1);
          updateSortUI();
          renderFieldTable();
        });

        el.sortPills.appendChild(pill);
      });
    }
  }
}

// Render Field Table with Search, Filter & Multi-Column Sorting
function renderFieldTable() {
  const filtered = state.activeFields.filter(f => {
    // Model filter
    if (state.selectedModel !== 'all') {
      if (state.selectedModel === 'compound') {
        if (!f.is_compound) return false;
      } else if (String(f.model_id) !== String(state.selectedModel)) {
        return false;
      }
    }

    // If Scale Factors pill is selected, only show scale factors
    if (state.activeFilter === 'scalefactor') {
      if (!f.is_scale_factor) return false;
    } else if (state.hideScaleFactors && f.is_scale_factor && !state.searchQuery) {
      // Hide scale factors in regular views unless user explicitly searched
      return false;
    }

    // Hide raw MQTT / Modbus fields covered by combined telemetry
    if (state.hideCombinedRaw && f.is_compound_raw && !state.searchQuery && state.activeFilter !== 'push' && state.activeFilter !== 'modbus' && state.activeFilter !== 'selected') {
      return false;
    }

    // Search query
    if (state.searchQuery) {
      const q = state.searchQuery.toLowerCase();
      const match = f.label.toLowerCase().includes(q) ||
                    f.key.toLowerCase().includes(q) ||
                    (f.units && f.units.toLowerCase().includes(q)) ||
                    (f.description && f.description.toLowerCase().includes(q));
      if (!match) return false;
    }

    // Filter pill
    switch (state.activeFilter) {
      case 'compound':
        return f.is_compound;
      case 'selected':
        return isFieldSelected(f);
      case 'sensor':
        return f.ha_platform === 'sensor';
      case 'writable':
        return f.is_writable;
      case 'push':
        return f.source === 'MQTT_PUSH' && !f.is_compound;
      case 'modbus':
        return (f.source === 'MODBUS_POLL' || f.source === 'MODBUS_CONFIG') && !f.is_compound;
      case 'scalefactor':
        return f.is_scale_factor;
      default:
        return true;
    }
  });

  if (filtered.length === 0) {
    el.fieldTableBody.innerHTML = `<tr><td colspan="8" class="empty-state">No fields match the current filters</td></tr>`;
    return;
  }

  // Apply multi-column sort if criteria are defined
  if (state.sortCriteria.length > 0) {
    filtered.sort((a, b) => compareFields(a, b, state.sortCriteria));
  }

  el.fieldTableBody.innerHTML = '';

  const renderSingleRow = (f) => {
    const tr = document.createElement('tr');
    tr.id = `row-${sanitizeId(f.key)}`;

    const modelCellContent = f.is_compound
      ? `<span class="badge-compound" title="Unified compound view merging MQTT and Modbus">⚡ Compound</span>`
      : (f.model_id
          ? `<span class="badge-model" title="SunSpec Model ${f.model_id}: ${f.model_label || f.model_name || ''}">M${f.model_id}</span>`
          : `<span class="badge-push-simple" title="Direct Push MQTT">Push</span>`);

    if (f.is_compound) {
      const isChecked = isFieldSelected(f);
      const latestVal = formatFieldValue(f.latest_value, f);
      const mqttVal = formatFieldValue(f.mqtt_value, f);
      const mbVal = formatFieldValue(f.modbus_value, f);
      const mbRaw = formatFieldValue(f.modbus_raw_value);
      const latestSrcIcon = f.latest_source === 'MQTT_PUSH' ? '⚡' : (f.latest_source === 'MODBUS_POLL' ? '🔄' : '•');
      const latestSrcName = f.latest_source === 'MQTT_PUSH' ? 'MQTT' : (f.latest_source === 'MODBUS_POLL' ? 'Modbus' : 'None');
      const latestClass = f.latest_source === 'MQTT_PUSH' ? 'mqtt' : (f.latest_source === 'MODBUS_POLL' ? 'modbus' : 'dim');
      const rawNote = (f.modbus_raw_value !== null && f.modbus_raw_value !== undefined && f.modbus_raw_value !== f.modbus_value) ? ` <small class="raw-note">(raw ${mbRaw})</small>` : '';

      tr.className = 'compound-row';
      tr.innerHTML = `
        <td class="text-center">
          <input type="checkbox" class="ha-checkbox" data-key="${f.key}" ${isChecked ? 'checked' : ''} />
        </td>
        <td class="field-model-cell">
          ${modelCellContent}
        </td>
        <td>
          <div class="field-cell-main">
            <div class="field-label-line">
              <span class="field-label" title="${f.description || ''}">${f.label}</span>
            </div>
            <span class="field-key">${f.key}</span>
          </div>
        </td>
        <td>
          <div class="compound-val-container">
            <div class="val-latest-line">
              <span class="label-dim">Latest:</span>
              <span class="field-value-badge latest" id="val-${sanitizeId(f.key)}">${latestVal}</span>
              <span class="source-sub-badge ${latestClass}" id="src-${sanitizeId(f.key)}">${latestSrcIcon} ${latestSrcName}</span>
            </div>
            <div class="compound-sources-grid">
              <div class="source-item mqtt">
                <span class="source-lbl">MQTT:</span>
                <span class="source-val" id="val-mqtt-${sanitizeId(f.key)}">${mqttVal}</span>
              </div>
              <div class="source-item modbus">
                <span class="source-lbl">Modbus:</span>
                <span class="source-val" id="val-modbus-${sanitizeId(f.key)}">${mbVal}${rawNote}</span>
              </div>
            </div>
          </div>
        </td>
        <td>${f.units || '&mdash;'}</td>
        <td>
          <span class="source-tag compound" title="Latest update from ${latestSrcName}">⚡ Compound</span>
        </td>
        <td>
          <span class="type-tag">${f.ha_platform}${f.ha_device_class ? ': ' + f.ha_device_class : ''}</span>
        </td>
        <td class="text-right">
          ${f.is_writable ? `<button class="btn btn-secondary btn-sm btn-edit" data-key="${f.key}">Set</button>` : ''}
        </td>
      `;
    } else {
      const isChecked = isFieldSelected(f);
      const sourceClass = f.source === 'MQTT_PUSH' ? 'mqtt' : 'modbus';
      const sourceLabel = f.source === 'MQTT_PUSH' ? 'Push MQTT' : 'Modbus';
      const displayVal = formatFieldValue(f.value, f);

      tr.innerHTML = `
        <td class="text-center">
          <input type="checkbox" class="ha-checkbox" data-key="${f.key}" ${isChecked ? 'checked' : ''} />
        </td>
        <td class="field-model-cell">
          ${modelCellContent}
        </td>
        <td>
          <div class="field-cell-main">
            <div class="field-label-line">
              <span class="field-label" title="${f.description || ''}">${f.label}</span>
              ${f.mqtt_equivalent ? `<span class="badge-mqtt-linked" title="Direct Push MQTT equivalent: ${f.mqtt_equivalent}">⚡ Push MQTT</span>` : ''}
              ${f.compound_key ? `<span class="badge-compound-linked" title="Represented by merged telemetry point: ${f.compound_key}">⚡ Merged</span>` : ''}
            </div>
            <span class="field-key">${f.key}</span>
          </div>
        </td>
        <td>
          <span class="field-value-badge" id="val-${sanitizeId(f.key)}">${displayVal}</span>
        </td>
        <td>${f.units || '&mdash;'}</td>
        <td>
          <span class="source-tag ${sourceClass}">${sourceLabel}</span>
        </td>
        <td>
          <span class="type-tag">${f.ha_platform}${f.ha_device_class ? ': ' + f.ha_device_class : ''}</span>
        </td>
        <td class="text-right">
          ${f.is_writable ? `<button class="btn btn-secondary btn-sm btn-edit" data-key="${f.key}">Set</button>` : ''}
        </td>
      `;
    }

    // Checkbox toggle
    const chk = tr.querySelector('.ha-checkbox');
    chk.addEventListener('change', (e) => {
      toggleHaSelection(f, e.target.checked);
    });

    // Edit button
    const editBtn = tr.querySelector('.btn-edit');
    if (editBtn) {
      editBtn.addEventListener('click', () => openWriteModal(f));
    }

    return tr;
  };

  if (state.groupByModel) {
    // Group fields by model
    const groups = new Map();
    filtered.forEach(f => {
      let gKey;
      let gTitle;
      let gDesc = '';
      if (f.is_compound) {
        gKey = 'compound';
        gTitle = '⚡ Merged Telemetry (Push MQTT + Modbus)';
        gDesc = 'Real-time unified virtual fields';
      } else if (f.model_id) {
        gKey = `model_${f.model_id}`;
        gTitle = `Model ${f.model_id}: ${f.model_label || f.model_name || ''}`;
        gDesc = f.model_name || '';
      } else if (f.source === 'MQTT_PUSH') {
        gKey = 'mqtt_live';
        gTitle = 'Internal Push MQTT Telemetry';
        gDesc = 'Direct push fields from unit';
      } else {
        gKey = 'other';
        gTitle = 'Other Fields';
      }

      if (!groups.has(gKey)) {
        groups.set(gKey, { key: gKey, title: gTitle, desc: gDesc, fields: [] });
      }
      groups.get(gKey).fields.push(f);
    });

    // Sort groups if model sort is present
    const modelCrit = state.sortCriteria.find(c => c.column === 'model');
    let groupArray = Array.from(groups.values());
    if (modelCrit) {
      const factor = modelCrit.dir === 'desc' ? -1 : 1;
      groupArray.sort((a, b) => {
        const getGroupModelVal = (g) => {
          if (g.key === 'compound') return -1;
          if (g.key.startsWith('model_')) return Number(g.key.replace('model_', '')) || 0;
          if (g.key === 'mqtt_live') return 900000;
          return 999999;
        };
        return (getGroupModelVal(a) - getGroupModelVal(b)) * factor;
      });
    }

    groupArray.forEach(grp => {
      const headerTr = document.createElement('tr');
      headerTr.className = 'model-group-row';
      headerTr.innerHTML = `
        <td colspan="8">
          <div class="model-group-header">
            <span class="model-badge-lg">${grp.title}</span>
            ${grp.desc ? `<span class="model-group-desc">${grp.desc}</span>` : ''}
            <span class="model-group-count">${grp.fields.length} points</span>
          </div>
        </td>
      `;
      el.fieldTableBody.appendChild(headerTr);
      grp.fields.forEach(f => {
        el.fieldTableBody.appendChild(renderSingleRow(f));
      });
    });
  } else {
    filtered.forEach(f => {
      el.fieldTableBody.appendChild(renderSingleRow(f));
    });
  }
}

function lookupEnumSymbol(field, val) {
  if (!field) return null;
  const symbols = field.symbols;
  if (!symbols || !Array.isArray(symbols) || symbols.length === 0) return null;

  const testVals = [val];
  if (field.raw_value !== undefined && field.raw_value !== null && field.raw_value !== val) {
    testVals.push(field.raw_value);
  }

  for (const v of testVals) {
    if (v === null || v === undefined) continue;

    // 1. Match by integer value
    const num = Number(v);
    if (!Number.isNaN(num)) {
      for (const s of symbols) {
        if (typeof s === 'object' && s !== null && s.value !== undefined && s.value !== null) {
          if (Number(s.value) === num) return s;
        }
      }
    }

    // 2. Match by symbol name or label (case-insensitive)
    const str = String(v).trim().toUpperCase();
    for (const s of symbols) {
      if (typeof s === 'object' && s !== null) {
        if (s.name && String(s.name).trim().toUpperCase() === str) return s;
        if (s.label && String(s.label).trim().toUpperCase() === str) return s;
      } else if (typeof s === 'string') {
        if (s.trim().toUpperCase() === str) return { name: s, value: null };
      }
    }
  }

  return null;
}

function decodeBitfieldSymbols(field, val) {
  const symbols = field ? (field.symbols || []) : [];

  // Case 1: val is an array of symbol names (already decoded by backend)
  if (Array.isArray(val)) {
    return val;
  }
  if (field && field.bitmask_flags && Array.isArray(field.bitmask_flags)) {
    return field.bitmask_flags;
  }

  // Case 2: raw_value or val is integer
  let rawInt = null;
  if (typeof val === 'number') {
    rawInt = val;
  } else if (field && field.raw_value !== undefined && field.raw_value !== null && typeof field.raw_value === 'number') {
    rawInt = field.raw_value;
  } else if (typeof val === 'string' && /^-?\d+$/.test(val.trim())) {
    rawInt = parseInt(val.trim(), 10);
  }

  if (rawInt !== null && symbols.length > 0) {
    const active = [];
    const sorted = [...symbols].sort((a, b) => (Number(a.value) || 0) - (Number(b.value) || 0));
    for (const s of sorted) {
      const bit = Number(s.value);
      if (!Number.isNaN(bit) && (rawInt & (1 << bit)) !== 0) {
        active.push(s.name);
      }
    }
    return active;
  }

  // Case 3: comma separated string
  if (typeof val === 'string' && val.includes(',')) {
    return val.split(',').map(s => s.trim()).filter(Boolean);
  }

  return [];
}

function formatBitfieldValue(val, field) {
  const activeFlags = decodeBitfieldSymbols(field, val);
  const rawNum = field && typeof field.raw_value === 'number' ? field.raw_value : (typeof val === 'number' ? val : null);
  const rawHex = rawNum !== null ? `0x${(rawNum >>> 0).toString(16).toUpperCase()}` : null;
  const rawSuffix = rawNum !== null ? ` <small class="raw-note">(${rawHex} / ${rawNum})</small>` : '';

  if (!activeFlags || activeFlags.length === 0) {
    return `<span class="badge-flag none">NONE (0)</span>${rawSuffix}`;
  }

  const tags = activeFlags.map(flag => {
    let title = flag;
    if (field && field.symbols) {
      const sym = field.symbols.find(s => s.name === flag);
      if (sym) {
        title = `Bit ${sym.value}: ${sym.label || sym.name}${sym.desc ? ' - ' + sym.desc : ''}`;
      }
    }
    return `<span class="badge-flag active" title="${title}">${flag}</span>`;
  }).join(' ');

  return `<div class="bitfield-badges-wrap">${tags}${rawSuffix}</div>`;
}

function formatFieldValue(val, field = null) {
  if (val === null || val === undefined) return '&mdash;';

  if (field) {
    if (field.is_bitfield || (field.point_type && field.point_type.startsWith('bitfield'))) {
      return formatBitfieldValue(val, field);
    }

    const sym = lookupEnumSymbol(field, val);
    if (sym) {
      if (sym.value !== null && sym.value !== undefined) {
        return `${sym.name} <small class="raw-note">(${sym.value})</small>`;
      }
      return sym.name;
    }
  }

  if (typeof val === 'number') {
    return Number.isInteger(val) ? val.toString() : val.toFixed(2);
  }
  return String(val);
}

function sanitizeId(key) {
  return key.replace(/[^a-zA-Z0-9_-]/g, '_');
}

// Update Filter Pill Counts
function updateFilterCounts() {
  const fields = state.activeFields;
  el.counts.all.textContent = fields.length;
  if (el.counts.compound) {
    el.counts.compound.textContent = fields.filter(f => f.is_compound).length;
  }
  el.counts.selected.textContent = fields.filter(f => isFieldSelected(f)).length;
  el.counts.sensor.textContent = fields.filter(f => f.ha_platform === 'sensor').length;
  el.counts.writable.textContent = fields.filter(f => f.is_writable).length;
  el.counts.push.textContent = fields.filter(f => f.source === 'MQTT_PUSH' && !f.is_compound).length;
  el.counts.modbus.textContent = fields.filter(f => (f.source === 'MODBUS_POLL' || f.source === 'MODBUS_CONFIG') && !f.is_compound).length;
  el.counts.scalefactor.textContent = fields.filter(f => f.is_scale_factor).length;
}

function updateHaCounter() {
  el.haSelectedCount.textContent = state.selectedHaKeys.size;
}

// Server-Sent Events (SSE) Live Feed
function connectSSE() {
  if (state.eventSource) {
    state.eventSource.close();
  }

  const sse = new EventSource(apiPath('api/stream'));
  state.eventSource = sse;

  sse.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.type === 'field_update') {
        handleLiveFieldUpdate(msg.field);
      } else if (msg.type === 'compound_update') {
        handleLiveCompoundUpdate(msg.field);
      }
    } catch (e) {
      // Keepalive ping or ignore
    }
  };

  sse.onerror = () => {
    document.getElementById('connStatusText').textContent = 'Reconnecting...';
    document.getElementById('liveIndicator').classList.remove('live');
  };

  sse.onopen = () => {
    document.getElementById('connStatusText').textContent = 'Live Feed';
    document.getElementById('liveIndicator').classList.add('live');
  };
}

// Handle Live Compound Field Update from SSE
function handleLiveCompoundUpdate(cField) {
  // Update header quick telemetry
  if (cField.mapping_id === 'solar_power') {
    el.topSolar.textContent = `${cField.latest_value} W`;
  } else if (cField.mapping_id === 'grid_power') {
    el.topGrid.textContent = `${cField.latest_value} W`;
  } else if (cField.mapping_id === 'battery_soc') {
    const batW = state.activeFields.find(f => f.mapping_id === 'battery_power')?.latest_value || 0;
    el.topBattery.textContent = `${cField.latest_value}% (${batW} W)`;
  } else if (cField.mapping_id === 'system_mode' && el.modeSelect) {
    el.modeSelect.value = cField.latest_value;
  }

  // Update in active field cache if this device is open
  if (state.activeDevice && state.activeDevice.serial_number === cField.device_sn) {
    const cached = state.activeFields.find(f => f.key === cField.key);
    if (cached) {
      Object.assign(cached, cField);
    }

    const id = sanitizeId(cField.key);
    // Update latest value
    const latestBadge = document.getElementById(`val-${id}`);
    if (latestBadge) {
      latestBadge.innerHTML = formatFieldValue(cField.latest_value, cField);
      latestBadge.classList.add('value-flash');
      setTimeout(() => latestBadge.classList.remove('value-flash'), 600);
    }
    // Update source badge
    const srcBadge = document.getElementById(`src-${id}`);
    if (srcBadge) {
      const icon = cField.latest_source === 'MQTT_PUSH' ? '⚡' : (cField.latest_source === 'MODBUS_POLL' ? '🔄' : '•');
      const name = cField.latest_source === 'MQTT_PUSH' ? 'MQTT' : (cField.latest_source === 'MODBUS_POLL' ? 'Modbus' : 'None');
      const cls = cField.latest_source === 'MQTT_PUSH' ? 'mqtt' : (cField.latest_source === 'MODBUS_POLL' ? 'modbus' : 'dim');
      srcBadge.textContent = `${icon} ${name}`;
      srcBadge.className = `source-sub-badge ${cls}`;
    }
    // Update MQTT sub-val
    const mqttElem = document.getElementById(`val-mqtt-${id}`);
    if (mqttElem) {
      mqttElem.innerHTML = formatFieldValue(cField.mqtt_value, cField);
    }
    // Update Modbus sub-val
    const mbElem = document.getElementById(`val-modbus-${id}`);
    if (mbElem) {
      const rawNote = (cField.modbus_raw_value !== null && cField.modbus_raw_value !== undefined && cField.modbus_raw_value !== cField.modbus_value) ? ` <small class="raw-note">(raw ${formatFieldValue(cField.modbus_raw_value)})</small>` : '';
      mbElem.innerHTML = `${formatFieldValue(cField.modbus_value, cField)}${rawNote}`;
    }
  }
}

// Handle Live Field Update from SSE
function handleLiveFieldUpdate(field) {
  // Update header quick telemetry if applicable
  if (field.key === 'inverter.live.solar_power_w') {
    el.topSolar.textContent = `${field.value} W`;
  } else if (field.key === 'inverter.live.load_power_w') {
    el.topLoad.textContent = `${field.value} W`;
  } else if (field.key === 'inverter.live.grid_power_w') {
    el.topGrid.textContent = `${field.value} W`;
  } else if (field.key === 'battery.live.state_of_charge') {
    const batW = state.activeFields.find(f => f.key === 'battery.live.battery_power_w')?.value || 0;
    el.topBattery.textContent = `${field.value}% (${batW} W)`;
  } else if (field.key === 'inverter.live.system_mode' && el.modeSelect) {
    el.modeSelect.value = field.value;
  }

  // Update in active field cache if this device is open
  if (state.activeDevice && state.activeDevice.serial_number === field.device_sn) {
    const cached = state.activeFields.find(f => f.key === field.key);
    if (cached) {
      cached.value = field.value;
      cached.last_updated = field.last_updated;
    }

    // Flash value in table
    const valBadge = document.getElementById(`val-${sanitizeId(field.key)}`);
    if (valBadge) {
      valBadge.innerHTML = formatFieldValue(field.value, field);
      valBadge.classList.add('value-flash');
      setTimeout(() => valBadge.classList.remove('value-flash'), 600);
    }
  }
}

// Write Modal Handling
let targetWriteField = null;

function openWriteModal(field) {
  targetWriteField = field;
  el.writeModalTitle.textContent = `Set ${field.label}`;
  
  let desc = field.description || `Write new value for register ${field.name}`;
  if (field.point_type) {
    desc += ` (Type: ${field.point_type}${field.units ? ', Unit: ' + field.units : ''})`;
  }
  el.writeModalDesc.textContent = desc;

  el.writeInputContainer.innerHTML = '';

  const isBitfieldField = field.is_bitfield || (field.point_type && field.point_type.startsWith('bitfield'));
  const isEnumField = !isBitfieldField && (field.is_enum || (field.symbols && Array.isArray(field.symbols) && field.symbols.length > 0));

  if (isBitfieldField && field.symbols && Array.isArray(field.symbols) && field.symbols.length > 0) {
    // Multi-checkbox checklist for bitfields
    const container = document.createElement('div');
    container.id = 'writeBitfieldContainer';

    const actions = document.createElement('div');
    actions.className = 'bitfield-actions';
    actions.innerHTML = `
      <button type="button" class="btn btn-secondary btn-sm" id="btnBfAll">Select All</button>
      <button type="button" class="btn btn-secondary btn-sm" id="btnBfClear">Clear All</button>
    `;
    container.appendChild(actions);

    const checklist = document.createElement('div');
    checklist.className = 'bitfield-checklist';

    const activeFlags = decodeBitfieldSymbols(field, field.value);
    const activeSet = new Set(activeFlags.map(f => String(f).toUpperCase()));

    const sortedSyms = [...field.symbols].sort((a, b) => (Number(a.value) || 0) - (Number(b.value) || 0));

    sortedSyms.forEach(sym => {
      const bitNum = sym.value !== undefined ? sym.value : 0;
      const symName = sym.name || String(sym);
      const isChecked = activeSet.has(symName.toUpperCase());

      const item = document.createElement('label');
      item.className = 'bitfield-check-item';
      item.innerHTML = `
        <input type="checkbox" value="${symName}" data-bit="${bitNum}" ${isChecked ? 'checked' : ''} />
        <span class="bitfield-bit-num">[Bit ${bitNum}]</span>
        <span class="bitfield-sym-name">${symName}</span>
        ${sym.label && sym.label !== symName ? `<span class="bitfield-sym-label">${sym.label}</span>` : ''}
      `;
      checklist.appendChild(item);
    });

    container.appendChild(checklist);

    const summary = document.createElement('div');
    summary.className = 'bitfield-summary';
    summary.id = 'writeBitfieldSummary';
    container.appendChild(summary);

    function updateBitfieldSummary() {
      let mask = 0;
      const checkedNames = [];
      checklist.querySelectorAll('input[type="checkbox"]:checked').forEach(cb => {
        const bit = parseInt(cb.dataset.bit, 10);
        if (!isNaN(bit)) {
          mask |= (1 << bit);
        }
        checkedNames.push(cb.value);
      });
      const hex = `0x${(mask >>> 0).toString(16).toUpperCase()}`;
      summary.innerHTML = `<span><strong>Selected:</strong> ${checkedNames.length} flag(s)</span> <span><strong>Mask:</strong> ${mask} (${hex})</span>`;
    }

    checklist.addEventListener('change', updateBitfieldSummary);
    actions.querySelector('#btnBfAll').addEventListener('click', () => {
      checklist.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = true);
      updateBitfieldSummary();
    });
    actions.querySelector('#btnBfClear').addEventListener('click', () => {
      checklist.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = false);
      updateBitfieldSummary();
    });

    updateBitfieldSummary();
    el.writeInputContainer.appendChild(container);
  } else if (isEnumField) {
    // Dropdown restricted to valid enum symbols
    const sel = document.createElement('select');
    sel.className = 'text-input';
    sel.id = 'writeSelectInput';

    const activeSym = lookupEnumSymbol(field, field.value);

    field.symbols.forEach(sym => {
      const opt = document.createElement('option');
      const symName = typeof sym === 'object' && sym !== null ? sym.name : String(sym);
      const symVal = typeof sym === 'object' && sym !== null && sym.value !== undefined ? sym.value : null;
      const symLabel = typeof sym === 'object' && sym !== null && sym.label ? sym.label : null;

      opt.value = symName;
      opt.dataset.numValue = symVal !== null ? symVal : '';

      let optText = symName;
      if (symVal !== null) {
        optText += ` (${symVal})`;
      }
      if (symLabel && symLabel.toUpperCase() !== symName.toUpperCase()) {
        optText += ` - ${symLabel}`;
      }
      opt.textContent = optText;

      // Select if matches active value or symbol
      if (
        (activeSym && activeSym.name === symName) ||
        field.value === symName ||
        field.value === symVal ||
        field.raw_value === symVal ||
        String(field.value) === String(symVal) ||
        String(field.value).toUpperCase() === symName.toUpperCase()
      ) {
        opt.selected = true;
      }
      sel.appendChild(opt);
    });
    el.writeInputContainer.appendChild(sel);
  } else if (field.point_type && ['uint16', 'int16', 'uint32', 'int32', 'uint64', 'int64', 'acc16', 'acc32'].includes(field.point_type)) {
    // Numeric input restricted to integer bounds
    const input = document.createElement('input');
    input.type = 'number';
    input.step = '1';
    input.className = 'text-input';
    input.id = 'writeTextInput';

    const bounds = {
      uint16: [0, 65535],
      int16: [-32768, 32767],
      uint32: [0, 4294967295],
      int32: [-2147483648, 2147483647],
      acc16: [0, 65535],
      acc32: [0, 4294967295],
    };
    if (bounds[field.point_type]) {
      input.min = bounds[field.point_type][0];
      input.max = bounds[field.point_type][1];
      const hint = document.createElement('small');
      hint.className = 'field-input-hint';
      hint.style.display = 'block';
      hint.style.marginTop = '4px';
      hint.style.color = 'var(--text-muted)';
      hint.textContent = `Allowed range: ${input.min} to ${input.max}`;
      el.writeInputContainer.appendChild(input);
      el.writeInputContainer.appendChild(hint);
    } else {
      el.writeInputContainer.appendChild(input);
    }
    input.value = field.raw_value !== null && field.raw_value !== undefined ? field.raw_value : (field.value !== null ? field.value : '');
  } else if (field.point_type && ['float32', 'float64'].includes(field.point_type)) {
    // Float numeric input
    const input = document.createElement('input');
    input.type = 'number';
    input.step = 'any';
    input.className = 'text-input';
    input.id = 'writeTextInput';
    input.value = field.value !== null && field.value !== undefined ? field.value : '';
    el.writeInputContainer.appendChild(input);
  } else {
    // Text input
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'text-input';
    input.id = 'writeTextInput';
    input.value = field.value !== null && field.value !== undefined ? field.value : '';
    el.writeInputContainer.appendChild(input);
  }

  el.writeModal.classList.add('open');
}

async function submitWrite() {
  if (!targetWriteField) return;

  const bitfieldContainer = document.getElementById('writeBitfieldContainer');
  const selectEl = document.getElementById('writeSelectInput');
  const textEl = document.getElementById('writeTextInput');
  let newVal = null;

  if (bitfieldContainer) {
    const checked = [];
    bitfieldContainer.querySelectorAll('input[type="checkbox"]:checked').forEach(cb => {
      checked.push(cb.value);
    });
    newVal = checked;
  } else if (selectEl) {
    newVal = selectEl.value;
  } else if (textEl) {
    newVal = textEl.value.trim();
  }

  if (newVal === null || (typeof newVal === 'string' && newVal === '')) {
    alert('Please enter a value');
    return;
  }

  // Client-side restriction based on field descriptor
  if (targetWriteField.point_type && ['uint16', 'int16', 'uint32', 'int32', 'acc16', 'acc32'].includes(targetWriteField.point_type)) {
    const num = Number(newVal);
    if (!Number.isInteger(num)) {
      alert(`Value must be an integer for ${targetWriteField.point_type}`);
      return;
    }
    const bounds = {
      uint16: [0, 65535],
      int16: [-32768, 32767],
      uint32: [0, 4294967295],
      int32: [-2147483648, 2147483647],
      acc16: [0, 65535],
      acc32: [0, 4294967295],
    };
    if (bounds[targetWriteField.point_type]) {
      const [minB, maxB] = bounds[targetWriteField.point_type];
      if (num < minB || num > maxB) {
        alert(`Value ${num} is out of range for ${targetWriteField.point_type} (${minB} to ${maxB})`);
        return;
      }
    }
  }

  try {
    const res = await fetch(apiPath('api/fields/write'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ field_key: targetWriteField.key, value: newVal }),
    });
    const data = await res.json();
    if (data.success) {
      const confirmedVal = data.value !== undefined ? data.value : newVal;
      const displayConfirmed = Array.isArray(confirmedVal) ? (confirmedVal.join(', ') || 'NONE') : confirmedVal;
      showToast(`Wrote ${targetWriteField.label} = ${displayConfirmed}`);
      targetWriteField.value = confirmedVal;
      targetWriteField.last_updated = Date.now() / 1000;

      // Update UI row immediately
      const id = sanitizeId(targetWriteField.key);
      const valBadge = document.getElementById(`val-${id}`);
      if (valBadge) {
        valBadge.innerHTML = formatFieldValue(confirmedVal, targetWriteField);
        valBadge.classList.add('value-flash');
        setTimeout(() => valBadge.classList.remove('value-flash'), 600);
      }

      el.writeModal.classList.remove('open');
    } else {
      alert(`Error writing value: ${data.error}`);
    }
  } catch (err) {
    alert(`Failed sending write request: ${err}`);
  }
}

// Setup Event Listeners
function setupEventListeners() {
  // Search
  el.searchInput.addEventListener('input', (e) => {
    state.searchQuery = e.target.value.trim();
    el.searchClear.style.display = state.searchQuery ? 'block' : 'none';
    renderFieldTable();
  });

  el.searchClear.addEventListener('click', () => {
    el.searchInput.value = '';
    state.searchQuery = '';
    el.searchClear.style.display = 'none';
    renderFieldTable();
  });

  // Filter Pills
  el.filterPills.querySelectorAll('.pill').forEach(pill => {
    pill.addEventListener('click', () => {
      el.filterPills.querySelectorAll('.pill').forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      state.activeFilter = pill.dataset.filter;
      renderFieldTable();
    });
  });

  // Hide Scale Factors Checkbox
  if (el.hideScaleFactors) {
    el.hideScaleFactors.addEventListener('change', (e) => {
      state.hideScaleFactors = e.target.checked;
      renderFieldTable();
    });
  }

  // Hide Combined Raw Checkbox
  if (el.hideCombinedRaw) {
    el.hideCombinedRaw.addEventListener('change', (e) => {
      state.hideCombinedRaw = e.target.checked;
      renderFieldTable();
    });
  }

  // Model Select Dropdown
  if (el.modelSelect) {
    el.modelSelect.addEventListener('change', (e) => {
      state.selectedModel = e.target.value;
      renderFieldTable();
    });
  }

  // Group by Model Checkbox
  if (el.groupByModel) {
    el.groupByModel.addEventListener('change', (e) => {
      state.groupByModel = e.target.checked;
      renderFieldTable();
    });
  }

  // Multi-Sort Mode Checkbox
  if (el.multiSortToggle) {
    el.multiSortToggle.addEventListener('change', (e) => {
      state.multiSortMode = e.target.checked;
    });
  }

  // Clear Sort Button
  if (el.btnClearSort) {
    el.btnClearSort.addEventListener('click', () => {
      state.sortCriteria = [];
      updateSortUI();
      renderFieldTable();
    });
  }

  // Sortable Table Column Headers
  document.querySelectorAll('.field-table thead th.sortable').forEach(th => {
    th.addEventListener('click', (e) => {
      handleColumnHeaderClick(th.dataset.sort, e.shiftKey);
    });
  });

  // Poll All Models on Active Device
  if (el.btnPollAllModels) {
    el.btnPollAllModels.addEventListener('click', async () => {
      if (!state.activeDevice) return;
      const sn = state.activeDevice.serial_number;
      el.btnPollAllModels.disabled = true;
      const originalText = el.btnPollAllModels.textContent;
      el.btnPollAllModels.textContent = 'Polling...';
      try {
        const res = await fetch(apiPath(`api/devices/${sn}/poll_all`), { method: 'POST' });
        const data = await res.json();
        if (data.success) {
          showToast(`Polled ${data.count || 0} models (${data.field_count || 0} fields total)`);
          await selectDevice(sn);
        } else {
          showToast(`Poll failed: ${data.message || data.error || 'Unknown error'}`);
        }
      } catch (err) {
        showToast(`Failed polling models: ${err}`);
      } finally {
        el.btnPollAllModels.disabled = false;
        el.btnPollAllModels.textContent = originalText;
      }
    });
  }

  // System Mode Dropdown
  el.modeSelect.addEventListener('change', async (e) => {
    const newMode = e.target.value;
    try {
      const res = await fetch(apiPath('api/fields/write'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ field_key: 'inverter.live.system_mode', value: newMode }),
      });
      const data = await res.json();
      if (data.success) {
        showToast(`System operating mode set to ${newMode}`);
      } else {
        alert(`Error setting mode: ${data.error}`);
      }
    } catch (err) {
      alert(`Failed setting mode: ${err}`);
    }
  });

  // Select Recommended
  el.btnSelectRecommended.addEventListener('click', async () => {
    try {
      const sn = state.activeDevice ? state.activeDevice.serial_number : '';
      if (sn) {
        state.modifiedDeviceSerials.add(sn.trim().toUpperCase());
      }
      const url = sn ? apiPath(`api/ha/recommended?serial_number=${encodeURIComponent(sn)}`) : apiPath('api/ha/recommended');
      const res = await fetch(url);
      const data = await res.json();
      const rec = data.recommended_fields || [];
      rec.forEach(k => state.selectedHaKeys.add(k));
      updateHaCounter();
      updateFilterCounts();
      renderFieldTable();
      showToast(`Selected ${rec.length} recommended entities`);
    } catch (err) {
      console.error(err);
    }
  });

  // Deselect All on current device
  el.btnDeselectAll.addEventListener('click', () => {
    if (!state.activeDevice) return;
    const sn = (state.activeDevice.serial_number || '').trim().toUpperCase();
    if (sn) {
      state.modifiedDeviceSerials.add(sn);
    }
    state.activeFields.forEach(f => {
      if (sn) {
        state.selectedHaKeys.delete(`${sn}:${f.key}`);
        if (f.mqtt_key) state.selectedHaKeys.delete(`${sn}:${f.mqtt_key}`);
      }
      state.selectedHaKeys.delete(f.key);
      if (f.mqtt_key) state.selectedHaKeys.delete(f.mqtt_key);
    });
    updateHaCounter();
    updateFilterCounts();
    renderFieldTable();
    showToast('Cleared selections on active device');
  });

  // Apply selections to all devices of the same type
  if (el.btnApplySameType) {
    el.btnApplySameType.addEventListener('click', () => {
      if (!state.activeDevice) return;
      const activeDev = state.activeDevice;
      const devType = activeDev.device_type;
      const activeSn = (activeDev.serial_number || '').trim().toUpperCase();
      const peerDevices = (state.devices || []).filter(d => d.device_type === devType);

      if (peerDevices.length <= 1) {
        showToast('No other devices of this type');
        return;
      }

      // Collect all selected fields for the active device
      const selectedFields = state.activeFields.filter(f => isFieldSelected(f));
      const typeLabel = formatDeviceTypePlural(devType);

      // Copy selections to all peer devices in state.selectedHaKeys
      peerDevices.forEach(peer => {
        const peerSn = (peer.serial_number || '').trim().toUpperCase();
        if (peerSn) {
          state.modifiedDeviceSerials.add(peerSn);
        }

        // Clear existing selections for this peer device
        for (const k of Array.from(state.selectedHaKeys)) {
          if (k.startsWith(`${peerSn}:`)) {
            state.selectedHaKeys.delete(k);
          }
        }

        // Apply selected fields to this peer device
        selectedFields.forEach(f => {
          state.selectedHaKeys.add(`${peerSn}:${f.key}`);
          if (f.mqtt_key) {
            state.selectedHaKeys.add(`${peerSn}:${f.mqtt_key}`);
          }
        });
      });

      // Clean up any legacy unqualified keys for this device type to prevent ambiguity
      selectedFields.forEach(f => {
        state.selectedHaKeys.delete(f.key);
        if (f.mqtt_key) state.selectedHaKeys.delete(f.mqtt_key);
      });

      updateHaCounter();
      updateFilterCounts();
      renderFieldTable();

      if (selectedFields.length === 0) {
        showToast(`Cleared selections across all ${peerDevices.length} ${typeLabel}`);
      } else {
        showToast(`Applied ${selectedFields.length} selected field${selectedFields.length === 1 ? '' : 's'} to all ${peerDevices.length} ${typeLabel}`);
      }
    });
  }

  // Save HA Config
  el.btnSaveHA.addEventListener('click', async () => {
    const keys = Array.from(state.selectedHaKeys);
    const targetSerials = Array.from(state.modifiedDeviceSerials);
    if (targetSerials.length === 0 && state.activeDevice) {
      targetSerials.push(state.activeDevice.serial_number.trim().toUpperCase());
    }
    const activeSn = state.activeDevice ? state.activeDevice.serial_number.trim().toUpperCase() : undefined;

    try {
      const res = await fetch(apiPath('api/ha/config'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          selected_fields: keys,
          device_serials: targetSerials,
          device_serial: activeSn,
          merge: true,
        }),
      });
      const data = await res.json();
      if (data.success) {
        state.modifiedDeviceSerials.clear();
        if (Array.isArray(data.selected_fields)) {
          state.selectedHaKeys = new Set(data.selected_fields);
          updateHaCounter();
          updateFilterCounts();
          renderFieldTable();
        }
        showToast(`Saved ${data.count} entities to ha_config.yaml!`);
      }
    } catch (err) {
      alert(`Failed saving config: ${err}`);
    }
  });

  // Preview HA MQTT Discovery
  el.btnPreviewHA.addEventListener('click', async () => {
    try {
      el.previewModal.classList.add('open');
      el.previewCode.textContent = 'Generating MQTT Discovery preview...';
      const res = await fetch(apiPath('api/ha/preview'));
      const data = await res.json();
      el.previewCode.textContent = JSON.stringify(data, null, 2);
    } catch (err) {
      el.previewCode.textContent = `Error: ${err}`;
    }
  });

  el.btnCloseModal.addEventListener('click', () => el.previewModal.classList.remove('open'));
  el.btnClosePreview.addEventListener('click', () => el.previewModal.classList.remove('open'));
  el.btnCopyPreview.addEventListener('click', () => {
    navigator.clipboard.writeText(el.previewCode.textContent);
    showToast('Copied JSON to clipboard!');
  });

  // Write Modal
  el.btnCancelWrite.addEventListener('click', () => el.writeModal.classList.remove('open'));
  el.btnCancelWriteModal.addEventListener('click', () => el.writeModal.classList.remove('open'));
  el.btnConfirmWrite.addEventListener('click', submitWrite);

  // Compare Modal
  if (el.btnOpenCompare) {
    el.btnOpenCompare.addEventListener('click', openCompareModal);
    el.btnCloseCompare.addEventListener('click', closeCompareModal);
    el.btnCloseCompareFooter.addEventListener('click', closeCompareModal);
  }

  // On-demand Modbus Keypad / Config Sync
  if (el.btnSyncModbus) {
    el.btnSyncModbus.addEventListener('click', async () => {
      try {
        el.btnSyncModbus.disabled = true;
        el.btnSyncModbus.textContent = '🔄 Syncing...';
        const res = await fetch(apiPath('api/poller/trigger'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tier: 'config' }),
        });
        const data = await res.json();
        showToast('Modbus keypad & config sync triggered');
        if (state.selectedDeviceSn) {
          await fetchDeviceFields(state.selectedDeviceSn);
        }
      } catch (err) {
        showToast(`Sync failed: ${err}`);
      } finally {
        el.btnSyncModbus.disabled = false;
        el.btnSyncModbus.textContent = '🔄 Sync Config';
      }
    });
  }
}

// Telemetry Compare Modal
let compareTimer = null;

async function fetchAndRenderCompare() {
  try {
    const res = await fetch(apiPath('api/compare'));
    const data = await res.json();
    const rows = Array.isArray(data) ? data : (data.comparisons || []);
    const unrec = (!Array.isArray(data) && data.unrecognized_proto_fields) ? data.unrecognized_proto_fields : [];

    if (!rows || rows.length === 0) {
      el.compareTableBody.innerHTML = '<tr><td colspan="6" class="empty-state">No comparison mappings found</td></tr>';
    } else {
      el.compareTableBody.innerHTML = '';
      rows.forEach(r => {
        const tr = document.createElement('tr');
        let statusBadge = '';
        if (r.status === 'EXACT') statusBadge = '<span class="status-badge exact">EXACT MATCH ✓</span>';
        else if (r.status === 'CLOSE') statusBadge = '<span class="status-badge close">CLOSE (~)</span>';
        else if (r.status === 'DIVERGENT') statusBadge = '<span class="status-badge divergent">DIVERGENT ✗</span>';
        else statusBadge = `<span class="status-badge missing">${r.status.replace('_', ' ')}</span>`;

        const mqttDisplay = r.mqtt_value !== null ? `${formatFieldValue(r.mqtt_value)} ${r.unit}` : '<span class="text-muted">--</span>';
        const mbDisplay = r.modbus_value !== null ? `${formatFieldValue(r.modbus_value)} ${r.unit}` : '<span class="text-muted">--</span>';
        const matchDisplay = r.match_pct !== null ? `${r.match_pct}%` : '&mdash;';

        tr.innerHTML = `
          <td>
            <div class="field-cell-main">
              <strong>${r.label}</strong>
              <span class="field-key">${r.notes || r.mapping_id}</span>
            </div>
          </td>
          <td><span class="field-value-badge">${mqttDisplay}</span></td>
          <td>
            <div class="field-cell-main">
              <span>${r.modbus_label}</span>
              <span class="field-key">${r.modbus_key}</span>
            </div>
          </td>
          <td><span class="field-value-badge">${mbDisplay}</span></td>
          <td><strong>${matchDisplay}</strong></td>
          <td>${statusBadge}</td>
        `;
        el.compareTableBody.appendChild(tr);
      });
    }

    // Render Unrecognized / Unmapped Protobuf Telemetry
    if (el.unrecCompareSection && el.unrecTableBody) {
      if (unrec.length > 0) {
        el.unrecCompareSection.style.display = 'block';
        if (el.unrecCount) el.unrecCount.textContent = unrec.length;
        el.unrecTableBody.innerHTML = '';
        unrec.forEach(item => {
          const tr = document.createElement('tr');
          const cat = item.category || 'UNKNOWN';
          let catClass = 'unmapped';
          if (cat === 'WIRE_UNKNOWN_FIELD') catClass = 'wire';
          else if (cat === 'UNRECOGNIZED_TOPIC') catClass = 'topic';

          const fieldName = item.field_name || (item.field_number ? `Field #${item.field_number}` : '--');
          const valDisplay = item.value !== undefined && item.value !== null ? String(item.value) : '--';
          const desc = item.description || '';

          tr.innerHTML = `
            <td><span class="unrec-cat-badge ${catClass}">${cat.replace('_', ' ')}</span></td>
            <td><span class="field-key">${item.location || '--'}</span></td>
            <td><strong>${fieldName}</strong></td>
            <td><span class="field-value-badge">${valDisplay}</span></td>
            <td><span class="text-muted">${desc}</span></td>
          `;
          el.unrecTableBody.appendChild(tr);
        });
      } else {
        el.unrecCompareSection.style.display = 'none';
      }
    }
  } catch (err) {
    el.compareTableBody.innerHTML = `<tr><td colspan="6" class="empty-state">Error fetching comparisons: ${err}</td></tr>`;
  }
}

function openCompareModal() {
  el.compareModal.classList.add('open');
  fetchAndRenderCompare();
  if (compareTimer) clearInterval(compareTimer);
  compareTimer = setInterval(fetchAndRenderCompare, 2000);
}

function closeCompareModal() {
  el.compareModal.classList.remove('open');
  if (compareTimer) {
    clearInterval(compareTimer);
    compareTimer = null;
  }
}

// Toast Notifications
function showToast(message) {
  el.toast.textContent = message;
  el.toast.classList.add('show');
  setTimeout(() => el.toast.classList.remove('show'), 3000);
}

// Start App on DOM Ready
document.addEventListener('DOMContentLoaded', initApp);

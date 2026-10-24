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
  viewMode: 'unified', // 'unified' (grouped concepts) or 'raw' (all registers)
  unifiedFields: [],
  preferredSources: {}, // { [concept_id]: preferred_field_key }
  optimizationPlan: null,
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
  bannerCollapsed: false,
  showAvoidedModels: false,
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
  viewModeToggle: document.getElementById('viewModeToggle'),
  countUnified: document.getElementById('countUnified'),
  countRaw: document.getElementById('countRaw'),
  viewModeBadge: document.getElementById('viewModeBadge'),
  optimizationBanner: document.getElementById('optimizationBanner'),
  optBannerTitle: document.getElementById('optBannerTitle'),
  optBannerSubtitle: document.getElementById('optBannerSubtitle'),
  optModelsBadges: document.getElementById('optModelsBadges'),
  btnResetPins: document.getElementById('btnResetPins'),
  thModelContent: document.getElementById('thModelContent'),
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
  writeModalError: document.getElementById('writeModalError'),
  writeModalBounds: document.getElementById('writeModalBounds'),
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
  tabCmpDiscrepancies: document.getElementById('tabCmpDiscrepancies'),
  tabCmpMulti: document.getElementById('tabCmpMulti'),
  tabCmpMatches: document.getElementById('tabCmpMatches'),
  tabCmpAll: document.getElementById('tabCmpAll'),
  cntCmpDiscrepancies: document.getElementById('cntCmpDiscrepancies'),
  cntCmpMulti: document.getElementById('cntCmpMulti'),
  cntCmpMatches: document.getElementById('cntCmpMatches'),
  cntCmpAll: document.getElementById('cntCmpAll'),
  cmpDeviceSelect: document.getElementById('cmpDeviceSelect'),
  cmpSearchInput: document.getElementById('cmpSearchInput'),
  unrecCompareSection: document.getElementById('unrecCompareSection'),
  unrecCount: document.getElementById('unrecCount'),
  unrecTableBody: document.getElementById('unrecTableBody'),
  modbusDetailsModal: document.getElementById('modbusDetailsModal'),
  detailsModalTitle: document.getElementById('detailsModalTitle'),
  detailsModalKey: document.getElementById('detailsModalKey'),
  detailsModalBody: document.getElementById('detailsModalBody'),
  detailsSourceBadge: document.getElementById('detailsSourceBadge'),
  detailsDeviceLabel: document.getElementById('detailsDeviceLabel'),
  btnCloseDetailsModal: document.getElementById('btnCloseDetailsModal'),
  btnCloseDetailsFooter: document.getElementById('btnCloseDetailsFooter'),
  btnCopyDetailsJson: document.getElementById('btnCopyDetailsJson'),
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

  if (state.selectedDeviceSn !== serialNumber) {
    state.preferredSources = {};
  }
  state.selectedDeviceSn = serialNumber;

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
    state.unifiedFields = data.unified_fields || [];
    // Populate state.preferredSources from backend if not already set locally
    state.unifiedFields.forEach(g => {
      if (g.preferred_source_key && !state.preferredSources[g.id]) {
        state.preferredSources[g.id] = g.preferred_source_key;
      }
    });
    el.activeDeviceFieldCount.textContent = state.viewMode === 'unified' ? state.unifiedFields.length : state.activeFields.length;
    if (el.countUnified) el.countUnified.textContent = state.unifiedFields.length;
    if (el.countRaw) el.countRaw.textContent = state.activeFields.length;
    state.activeDeviceModels = data.models || [];
    if (el.activeDeviceModelCount) {
      el.activeDeviceModelCount.textContent = state.activeDeviceModels.length || (dev.supported_models ? dev.supported_models.length : '--');
    }
    populateModelDropdown(state.activeDeviceModels, state.activeFields);
    updateFilterCounts();
    renderFieldTable();
    updateOptimizationPlan();
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

  const checkKey = (k) => {
    if (!k) return false;
    if (sn && state.selectedHaKeys.has(`${sn}:${k}`)) return true;
    return state.selectedHaKeys.has(k);
  };

  if (checkKey(f.key)) return true;
  if (checkKey(f.id)) return true;
  if (checkKey(f.mqtt_key)) return true;
  if (checkKey(f.active_source_key)) return true;
  if (f.sources && Array.isArray(f.sources)) {
    for (const s of f.sources) {
      if (checkKey(s.field_key)) return true;
    }
  }
  return false;
}

// Toggle Home Assistant Field Selection (scoped by device)
function toggleHaSelection(f, isSelected) {
  const sn = getFieldDeviceSn(f);
  if (sn) {
    state.modifiedDeviceSerials.add(sn);
  }

  const primaryKey = f.active_source_key || f.key || f.id;
  const scopedPrimaryKey = sn ? `${sn}:${primaryKey}` : primaryKey;
  const scopedId = (sn && f.id) ? `${sn}:${f.id}` : f.id;
  const scopedKey = (sn && f.key) ? `${sn}:${f.key}` : f.key;
  const scopedMqttKey = (sn && f.mqtt_key) ? `${sn}:${f.mqtt_key}` : f.mqtt_key;

  if (isSelected) {
    state.selectedHaKeys.add(scopedPrimaryKey);
    if (scopedId && f.sources) state.selectedHaKeys.add(scopedId);
  } else {
    state.selectedHaKeys.delete(scopedPrimaryKey);
    state.selectedHaKeys.delete(primaryKey);
    if (scopedId) {
      state.selectedHaKeys.delete(scopedId);
      state.selectedHaKeys.delete(f.id);
    }
    if (scopedKey) {
      state.selectedHaKeys.delete(scopedKey);
      state.selectedHaKeys.delete(f.key);
    }
    if (scopedMqttKey) state.selectedHaKeys.delete(scopedMqttKey);
    if (f.mqtt_key) state.selectedHaKeys.delete(f.mqtt_key);
    if (f.sources && Array.isArray(f.sources)) {
      for (const s of f.sources) {
        state.selectedHaKeys.delete(s.field_key);
        if (sn) state.selectedHaKeys.delete(`${sn}:${s.field_key}`);
      }
    }
  }
  updateHaCounter();
  updateFilterCounts();
}

// Value extraction helpers for multi-column sorting
function getHaSortValue(f) {
  return isFieldSelected(f) ? 1 : 0;
}

function getModelSortValue(f) {
  if (f.sources && Array.isArray(f.sources)) {
    const firstModel = f.sources.find(s => s.model_id !== null && s.model_id !== undefined);
    return firstModel ? Number(firstModel.model_id) : -1;
  }
  if (f.is_compound) return -1;
  if (f.model_id !== undefined && f.model_id !== null) {
    const num = Number(f.model_id);
    return isNaN(num) ? 999999 : num;
  }
  if (f.source === 'MQTT_PUSH') return 900000;
  return 999999;
}

function getNameSortValue(f) {
  return (f.label || f.name || f.concept_key || f.key || '').toLowerCase();
}

function getValueSortValue(f) {
  const val = (f.latest_value !== undefined) ? f.latest_value : f.value;
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
  if (f.sources && Array.isArray(f.sources)) return '0_unified';
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

// SunSpec Bounds Helpers
function getFieldBounds(field) {
  if (field && field.bounds) {
    return field.bounds;
  }
  if (!field) return null;

  const rawBounds = {
    uint16: [0, 65535],
    int16: [-32768, 32767],
    uint32: [0, 4294967295],
    int32: [-2147483648, 2147483647],
    uint64: [0, 18446744073709551615],
    int64: [-9223372036854775808, 9223372036854775807],
    acc16: [0, 65535],
    acc32: [0, 4294967295],
    count: [0, 65535],
    sunssf: [-10, 10],
  };

  const pType = field.point_type || 'uint16';
  const isBf = field.is_bitfield || (pType && pType.startsWith('bitfield'));
  const isEn = !isBf && (field.is_enum || (field.symbols && Array.isArray(field.symbols) && field.symbols.length > 0));

  if (isEn && field.symbols && field.symbols.length > 0) {
    const syms = field.symbols.map(s => typeof s === 'object' && s !== null ? s : { name: String(s), value: null });
    const vals = syms.map(s => s.value).filter(v => v !== null && v !== undefined);
    const names = syms.map(s => s.name);
    return {
      category: 'enum',
      point_type: pType,
      raw_min: vals.length ? Math.min(...vals) : 0,
      raw_max: vals.length ? Math.max(...vals) : 65535,
      min_value: vals.length ? Math.min(...vals) : 0,
      max_value: vals.length ? Math.max(...vals) : 65535,
      step: 1,
      units: field.units || null,
      symbols: syms,
      valid_values: vals,
      valid_names: names,
      description: `${names.length} options: ${names.join(', ')}`,
    };
  }

  if (isBf) {
    const maxBits = (field.size || 1) * 16;
    const maxMask = (1 << maxBits) - 1;
    const hex = `0x${(maxMask >>> 0).toString(16).toUpperCase()}`;
    return {
      category: 'bitfield',
      point_type: pType,
      raw_min: 0,
      raw_max: maxMask,
      min_value: 0,
      max_value: maxMask,
      step: 1,
      max_bits: maxBits,
      mask_hex: hex,
      units: field.units || null,
      symbols: field.symbols || [],
      description: `Bitmask 0x0000 to ${hex} (${maxBits} bits)`,
    };
  }

  if (rawBounds[pType]) {
    const [rawMin, rawMax] = rawBounds[pType];
    return {
      category: 'numeric',
      point_type: pType,
      raw_min: rawMin,
      raw_max: rawMax,
      min_value: rawMin,
      max_value: rawMax,
      step: 1,
      units: field.units || null,
      sf: field.scale_factor_point || field.sf || null,
      description: `${rawMin.toLocaleString()} to ${rawMax.toLocaleString()}${field.units ? ' ' + field.units : ''}`,
    };
  }

  if (pType === 'string') {
    const maxLen = (field.size || 1) * 2;
    return {
      category: 'string',
      point_type: pType,
      max_length: maxLen,
      description: `Max ${maxLen} characters (${field.size || 1} registers)`,
    };
  }

  return {
    category: 'other',
    point_type: pType,
    units: field.units || null,
    description: `Type: ${pType}`,
  };
}

function formatBoundsBadge(field) {
  if (!field.is_writable) return '';
  const b = getFieldBounds(field);
  if (!b) return '';

  let text = '';
  let fullDesc = b.description || 'SunSpec Bounds Restriction';

  if (b.category === 'numeric') {
    if (b.scaled_min !== null && b.scaled_min !== undefined && b.scaled_max !== null && b.scaled_max !== undefined) {
      text = `${b.scaled_min} .. ${b.scaled_max}${b.units ? ' ' + b.units : ''}`;
    } else if (b.raw_min !== null && b.raw_min !== undefined) {
      text = `${b.raw_min.toLocaleString()} .. ${b.raw_max.toLocaleString()}${b.units ? ' ' + b.units : ''}`;
    }
  } else if (b.category === 'enum') {
    if (b.valid_names && b.valid_names.length > 0) {
      text = b.valid_names.length <= 2 
        ? b.valid_names.join(', ')
        : `${b.valid_names.slice(0, 2).join(', ')}... (+${b.valid_names.length - 2})`;
    } else if (b.raw_min !== null && b.raw_min !== undefined) {
      text = `${b.raw_min} .. ${b.raw_max}`;
    }
  } else if (b.category === 'bitfield') {
    text = `Mask: 0x0000 .. ${b.mask_hex || '0xFFFF'}`;
  } else if (b.category === 'string') {
    text = `Max ${b.max_length || ((field.size || 1) * 2)} chars`;
  } else if (b.category === 'float') {
    text = `Float (${b.units || 'any'})`;
  }

  if (!text) return '';
  return `
    <div class="field-bounds-line">
      <span class="field-bounds-badge" title="SunSpec Bounds: ${escapeHtml(fullDesc)}">
        <span class="bounds-icon">📏</span>
        <span class="bounds-text">${escapeHtml(text)}</span>
      </span>
    </div>
  `;
}

// Update Polling Optimization Plan & Minimal Model Set
async function updateOptimizationPlan() {
  if (!state.activeDevice) {
    if (el.optimizationBanner) el.optimizationBanner.style.display = 'none';
    return;
  }

  const sn = state.activeDevice.serial_number;
  try {
    const res = await fetch(apiPath(`api/devices/${encodeURIComponent(sn)}/optimize_polling`), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        selected_keys: Array.from(state.selectedHaKeys),
        preferred_sources: state.preferredSources,
      }),
    });
    if (!res.ok) return;
    const data = await res.json();
    state.optimizationPlan = data;

    // Render optimization banner
    if (el.optimizationBanner) {
      const stats = data.stats || {};
      const minModels = data.minimal_models || [];
      const avoidedModels = data.models_avoided || [];
      const totalItems = stats.total_items || 0;

      if (totalItems > 0 || Object.keys(state.preferredSources).length > 0) {
        el.optimizationBanner.style.display = 'block';
        if (el.optBannerTitle) {
          el.optBannerTitle.innerHTML = `<strong>Optimal Polling Plan:</strong> ${minModels.length} Model${minModels.length === 1 ? '' : 's'} Selected (${minModels.map(m => 'M' + m).join(', ')}) &bull; <span class="text-muted">${avoidedModels.length} avoided &bull; ${totalItems} selected field${totalItems === 1 ? '' : 's'}</span>`;
        }
        if (el.optBannerSubtitle) {
          el.optBannerSubtitle.textContent = avoidedModels.length > 0
            ? `${avoidedModels.length} redundant models excluded from Modbus polling to reduce RS-485 bus traffic.`
            : `All active models required for the selected fields.`;
        }

        if (el.optModelsBadges) {
          const activeBadges = minModels.map(m => `<span class="badge-opt-active" title="Model ${m} selected for active Modbus polling">M${m} (Polled)</span>`).join(' ');
          const mqttBadge = stats.mqtt_covered_count ? `<span class="badge-opt-mqtt" title="${stats.mqtt_covered_count} points provided via Push MQTT">⚡ ${stats.mqtt_covered_count} Push MQTT</span>` : '';
          const avoidedToggle = avoidedModels.length > 0
            ? `<button type="button" class="btn-avoided-toggle" id="btnToggleAvoided" title="Toggle list of avoided models">${state.showAvoidedModels ? '▴ Hide Avoided' : `+${avoidedModels.length} avoided ▾`}</button>`
            : '';
          const avoidedDrawer = avoidedModels.length > 0
            ? `<div class="opt-avoided-drawer" id="optAvoidedDrawer" style="display: ${state.showAvoidedModels ? 'flex' : 'none'};">${avoidedModels.map(m => `<span class="badge-opt-avoided" title="Model ${m} avoided to reduce RS-485 bus traffic">M${m} (Avoided)</span>`).join(' ')}</div>`
            : '';

          el.optModelsBadges.innerHTML = `
            <div class="opt-models-row">
              ${activeBadges} ${mqttBadge} ${avoidedToggle}
            </div>
            ${avoidedDrawer}
          `;

          const toggleBtn = el.optModelsBadges.querySelector('#btnToggleAvoided');
          if (toggleBtn) {
            toggleBtn.addEventListener('click', (e) => {
              e.stopPropagation();
              state.showAvoidedModels = !state.showAvoidedModels;
              const drawer = el.optModelsBadges.querySelector('#optAvoidedDrawer');
              if (drawer) {
                drawer.style.display = state.showAvoidedModels ? 'flex' : 'none';
                toggleBtn.textContent = state.showAvoidedModels ? '▴ Hide Avoided' : `+${avoidedModels.length} avoided ▾`;
              }
            });
          }
        }

        if (el.btnResetPins) {
          el.btnResetPins.style.display = Object.keys(state.preferredSources).length > 0 ? 'inline-block' : 'none';
        }
      } else {
        el.optimizationBanner.style.display = 'none';
      }
    }

    // Update state.unifiedFields from authoritative backend response
    if (data.unified_fields && Array.isArray(data.unified_fields)) {
      state.unifiedFields = data.unified_fields;
      // Clean up state.preferredSources if any were unpinned on backend
      Object.keys(state.preferredSources).forEach(gId => {
        const grp = state.unifiedFields.find(g => g.id === gId);
        if (!grp || !grp.preferred_source_key) {
          delete state.preferredSources[gId];
        }
      });
      state.unifiedFields.forEach(g => {
        if (g.preferred_source_key) {
          state.preferredSources[g.id] = g.preferred_source_key;
        }
      });
      if (state.viewMode === 'unified') {
        renderFieldTable();
      }
    } else if (data.assignments && state.unifiedFields) {
      state.unifiedFields.forEach(g => {
        const chosen = data.assignments[g.id];
        let foundActive = false;
        if (state.preferredSources[g.id]) {
          (g.sources || []).forEach(s => {
            const isPin = s.field_key === state.preferredSources[g.id];
            s.is_pinned = isPin;
            if (isPin) {
              g.active_source_key = s.field_key;
              g.latest_value = s.value;
              g.latest_source = s.source_id;
              foundActive = true;
            }
          });
        }
        if (!foundActive) {
          (g.sources || []).forEach(s => {
            s.is_pinned = false;
            const isMatch = chosen !== undefined && ((chosen === 'MQTT' && s.source_type === 'MQTT') || (s.model_id === chosen));
            s.is_optimal = isMatch;
            if (isMatch && !foundActive) {
              g.active_source_key = s.field_key;
              g.latest_value = s.value;
              g.latest_source = s.source_id;
              foundActive = true;
            }
          });
        }
      });
      if (state.viewMode === 'unified') {
        renderFieldTable();
      }
    }
  } catch (err) {
    console.error('Failed optimizing polling:', err);
  }
}

// Helper to determine if a field or group is a SunSpec scale factor
function isScaleFactorField(f) {
  if (!f) return false;
  if (f.is_scale_factor) return true;
  if (f.point_type === 'sunssf') return true;
  if (f.name && (f.name.endsWith('_SF') || f.name.endsWith('_sf') || f.name.startsWith('sf_') || f.name.startsWith('SF_') || f.name.startsWith('sunssf_'))) return true;
  if (f.concept_key && (f.concept_key.endsWith('_sf') || f.concept_key.endsWith('_SF') || f.concept_key.startsWith('sf_') || f.concept_key.startsWith('SF_') || f.concept_key.startsWith('sunssf_'))) return true;
  if (f.key && (f.key.endsWith('_sf') || f.key.endsWith('_SF') || f.key.includes('.sf_') || f.key.includes('.SF_') || f.key.includes('.sunssf_'))) return true;
  if (f.id && (f.id.endsWith('_sf') || f.id.endsWith('_SF') || f.id.includes('.sf_') || f.id.includes('.SF_') || f.id.includes('.sunssf_'))) return true;
  if (f.label && f.label.toLowerCase().includes('scale factor')) return true;
  if (f.sources && f.sources.some(s => isScaleFactorField(s))) return true;
  return false;
}

// Render Field Table with Search, Filter & Multi-Column Sorting
function renderFieldTable() {
  const isUnified = state.viewMode === 'unified';
  const sourceItems = isUnified ? state.unifiedFields : state.activeFields;

  const filtered = sourceItems.filter(f => {
    if (isUnified) {
      // Unified model filter
      if (state.selectedModel !== 'all') {
        if (state.selectedModel === 'compound') {
          if (!f.sources || f.sources.length <= 1) return false;
        } else {
          const hasModel = f.sources && f.sources.some(s => String(s.model_id) === String(state.selectedModel));
          if (!hasModel) return false;
        }
      }

      // Filter pill & Scale Factor toggle
      if (state.activeFilter === 'scalefactor') {
        if (!isScaleFactorField(f)) return false;
      } else if (state.hideScaleFactors && isScaleFactorField(f) && !state.searchQuery) {
        return false;
      }

      // Search query
      if (state.searchQuery) {
        const q = state.searchQuery.toLowerCase();
        const match = (f.label && f.label.toLowerCase().includes(q)) ||
                      (f.concept_key && f.concept_key.toLowerCase().includes(q)) ||
                      (f.id && f.id.toLowerCase().includes(q)) ||
                      (f.units && f.units.toLowerCase().includes(q)) ||
                      (f.description && f.description.toLowerCase().includes(q)) ||
                      (f.sources && f.sources.some(s => s.field_key.toLowerCase().includes(q) || s.name.toLowerCase().includes(q)));
        if (!match) return false;
      }

      switch (state.activeFilter) {
        case 'compound':
          return f.sources && f.sources.length > 1;
        case 'selected':
          return isFieldSelected(f);
        case 'sensor':
          return f.ha_platform === 'sensor';
        case 'writable':
          return f.is_writable;
        case 'push':
          return f.sources && f.sources.some(s => s.source_type === 'MQTT');
        case 'modbus':
          return f.sources && f.sources.some(s => s.source_type === 'SUNSPEC');
        case 'scalefactor':
          return isScaleFactorField(f);
        default:
          return true;
      }
    } else {
      // Raw mode filtering
      if (state.selectedModel !== 'all') {
        if (state.selectedModel === 'compound') {
          if (!f.is_compound) return false;
        } else if (String(f.model_id) !== String(state.selectedModel)) {
          return false;
        }
      }

      if (state.activeFilter === 'scalefactor') {
        if (!isScaleFactorField(f)) return false;
      } else if (state.hideScaleFactors && isScaleFactorField(f) && !state.searchQuery) {
        return false;
      }

      if (state.hideCombinedRaw && f.is_compound_raw && !state.searchQuery && state.activeFilter !== 'push' && state.activeFilter !== 'modbus' && state.activeFilter !== 'selected') {
        return false;
      }

      if (state.searchQuery) {
        const q = state.searchQuery.toLowerCase();
        const match = f.label.toLowerCase().includes(q) ||
                      f.key.toLowerCase().includes(q) ||
                      (f.units && f.units.toLowerCase().includes(q)) ||
                      (f.description && f.description.toLowerCase().includes(q));
        if (!match) return false;
      }

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

  const renderUnifiedRow = (f) => {
    const tr = document.createElement('tr');
    tr.id = `row-${sanitizeId(f.id)}`;
    tr.className = 'unified-row';

    const isChecked = isFieldSelected(f);
    const displayVal = formatFieldValue(f.latest_value, f);
    const isBf = isBitfield(f, f.latest_value);
    const pinnedKey = state.preferredSources[f.id] || f.preferred_source_key;

    const minModelsSet = new Set((state.optimizationPlan && state.optimizationPlan.minimal_models) || []);

    // Build candidate source pills
    const sourcePillsHtml = (f.sources || []).map(s => {
      const isOptimal = s.is_optimal;
      const isPinned = pinnedKey ? (pinnedKey === s.field_key) : false;
      const isMqtt = s.source_type === 'MQTT';
      const isPolled = isMqtt || (s.model_id && minModelsSet.has(s.model_id));
      const pillClass = isPinned ? 'pinned' : (isOptimal ? 'optimal' : (isMqtt ? 'mqtt' : (isPolled ? 'polled' : 'alternate')));
      const prefix = isPinned ? '📌 ' : (isOptimal ? '★ ' : '');
      const sVal = formatFieldValue(s.value, f);
      const title = isPinned
        ? `📌 Pinned preferred source: ${s.source_id} (${s.field_key})\nValue: ${sVal}\nClick to unpin and use automatic minimal set solver.`
        : (isOptimal
            ? `★ Optimal source: ${s.source_id} (${s.field_key})\nSelected in minimal polling plan.\nValue: ${sVal}`
            : (isPolled
                ? `⚡ ${s.source_id} (${s.field_key})\nIncluded in minimal polling plan.\nValue: ${sVal}\nClick to pin this source.`
                : `${s.source_id} (${s.field_key})\nExcluded / avoided from Modbus polling.\nValue: ${sVal}\nClick to pin this source.`));

      return `<button class="source-pill ${pillClass}" data-group-id="${f.id}" data-field-key="${s.field_key}" data-source-id="${s.source_id}" title="${escapeHtml(title)}">${prefix}${s.source_id}</button>`;
    }).join(' ');

    const countBadge = (f.sources && f.sources.length > 1)
      ? `<span class="badge-source-count" title="${f.sources.length} sources available">${f.sources.length} sources</span>`
      : '';

    // Active source description
    const activeSrc = (f.sources || []).find(s => s.field_key === (pinnedKey || f.active_source_key)) || (f.sources ? f.sources[0] : null);
    const isPinned = activeSrc && pinnedKey === activeSrc.field_key;
    const isPolled = activeSrc && (activeSrc.source_type === 'MQTT' || (activeSrc.model_id && minModelsSet.has(activeSrc.model_id)));
    const activeBadge = activeSrc
      ? (isPinned
          ? `<span class="badge-source-pinned" title="Manually pinned by user">📌 ${activeSrc.source_id} (Pinned)</span>`
          : (activeSrc.source_type === 'MQTT'
              ? `<span class="badge-push-simple" title="Direct Push MQTT">⚡ Push MQTT</span>`
              : (isPolled
                  ? `<span class="badge-optimal" title="Model ${activeSrc.model_id} selected in minimal polling plan">★ ${activeSrc.source_id} (Polled)</span>`
                  : `<span class="badge-optimal" title="Selected by minimal model set solver">★ ${activeSrc.source_id} (Optimal)</span>`)))
      : '&mdash;';

    // Construct a comprehensive targetFieldRef for actions (details, write, copy)
    const targetFieldRef = activeSrc
      ? {
          ...activeSrc,
          key: activeSrc.field_key,
          id: f.id,
          device_sn: f.device_sn,
          point_type: activeSrc.point_type || f.point_type,
          is_bitfield: f.is_bitfield,
          is_enum: f.is_enum,
          symbols: activeSrc.symbols || f.symbols,
          bounds: activeSrc.bounds || f.bounds,
        }
      : {
          ...f,
          key: f.active_source_key || f.id,
          field_key: f.active_source_key || f.id,
          device_sn: f.device_sn,
        };

    tr.innerHTML = `
      <td class="text-center">
        <input type="checkbox" class="ha-checkbox" data-key="${f.id}" ${isChecked ? 'checked' : ''} />
      </td>
      <td class="field-model-cell">
        <div class="source-pill-group">
          ${sourcePillsHtml}
        </div>
      </td>
      <td>
        <div class="field-cell-main">
          <div class="field-label-line">
            <span class="field-label" title="${escapeHtml(f.description || '')}">${f.label}</span>
            ${f.is_writable ? '<span class="badge-writable" title="Settable register (Read/Write)">RW</span>' : ''}
            ${countBadge}
          </div>
          <span class="field-key">${f.concept_key} &bull; <small>${f.id}</small></span>
          ${formatBoundsBadge(f)}
        </div>
      </td>
      <td>
        <span class="field-value-badge latest${isBf ? ' is-bitfield' : ''}" id="val-${sanitizeId(f.id)}">${displayVal}</span>
      </td>
      <td>${f.units || '&mdash;'}</td>
      <td>
        ${activeBadge}
      </td>
      <td>
        <span class="type-tag">${f.ha_platform}${f.ha_device_class ? ': ' + f.ha_device_class : ''}</span>
      </td>
      <td class="text-right">
        <div class="action-cell-container">
          ${f.is_writable ? `<button class="btn btn-secondary btn-sm btn-edit" data-key="${targetFieldRef.key}">Set</button>` : ''}
          <button class="btn btn-secondary btn-sm btn-details" data-key="${targetFieldRef.key}" title="Explore Modbus register definition &amp; associated registers">Details</button>
          <div class="action-menu-wrapper">
            <button class="btn btn-secondary btn-sm btn-icon-more" data-key="${targetFieldRef.key}" title="More Actions">⋮</button>
            <div class="action-dropdown-menu">
              <button class="action-menu-item item-details" data-key="${targetFieldRef.key}">📋 Modbus Details</button>
              ${f.is_writable ? `<button class="action-menu-item item-edit" data-key="${targetFieldRef.key}">✏️ Edit Value</button>` : ''}
              <button class="action-menu-item item-copy" data-key="${targetFieldRef.key}">📄 Copy Key</button>
            </div>
          </div>
        </div>
      </td>
    `;

    // Event listeners
    const chk = tr.querySelector('.ha-checkbox');
    chk.addEventListener('change', (e) => {
      toggleHaSelection(f, e.target.checked);
      updateOptimizationPlan();
    });

    tr.querySelectorAll('.source-pill').forEach(pill => {
      pill.addEventListener('click', (e) => {
        e.stopPropagation();
        const gId = pill.dataset.groupId;
        const fKey = pill.dataset.fieldKey;
        const currentPin = state.preferredSources[gId] || f.preferred_source_key;

        if (currentPin === fKey) {
          delete state.preferredSources[gId];
          f.preferred_source_key = null;
          (f.sources || []).forEach(s => { s.is_pinned = false; });
          showToast(`Unpinned ${f.label}; returned to automatic solver`);
        } else {
          state.preferredSources[gId] = fKey;
          f.preferred_source_key = fKey;
          (f.sources || []).forEach(s => { s.is_pinned = (s.field_key === fKey); });
          const srcName = pill.dataset.sourceId || pill.textContent.trim().replace(/^[📌★]\s*/, '');
          showToast(`Pinned ${f.label} to ${srcName}`);
        }
        updateOptimizationPlan();
      });
    });

    const detailsBtn = tr.querySelector('.btn-details');
    if (detailsBtn) {
      detailsBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        openFieldDetails(targetFieldRef);
      });
    }

    const labelSpan = tr.querySelector('.field-label');
    if (labelSpan) {
      labelSpan.style.cursor = 'pointer';
      labelSpan.title = (f.description ? `${f.description}\n` : '') + 'Click to view Modbus register details';
      labelSpan.addEventListener('click', () => openFieldDetails(targetFieldRef));
    }

    const editBtn = tr.querySelector('.btn-edit');
    if (editBtn) {
      editBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        openWriteModal(targetFieldRef);
      });
    }

    const moreBtn = tr.querySelector('.btn-icon-more');
    const dropdownMenu = tr.querySelector('.action-dropdown-menu');
    if (moreBtn && dropdownMenu) {
      moreBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        document.querySelectorAll('.action-dropdown-menu.show').forEach(m => {
          if (m !== dropdownMenu) m.classList.remove('show');
        });
        dropdownMenu.classList.toggle('show');
      });

      const menuDetails = dropdownMenu.querySelector('.item-details');
      if (menuDetails) {
        menuDetails.addEventListener('click', (e) => {
          e.stopPropagation();
          dropdownMenu.classList.remove('show');
          openFieldDetails(targetFieldRef);
        });
      }

      const menuEdit = dropdownMenu.querySelector('.item-edit');
      if (menuEdit) {
        menuEdit.addEventListener('click', (e) => {
          e.stopPropagation();
          dropdownMenu.classList.remove('show');
          openWriteModal(targetFieldRef);
        });
      }

      const menuCopy = dropdownMenu.querySelector('.item-copy');
      if (menuCopy) {
        menuCopy.addEventListener('click', (e) => {
          e.stopPropagation();
          dropdownMenu.classList.remove('show');
          const copyKey = targetFieldRef.key || targetFieldRef.field_key || f.id;
          copyToClipboard(copyKey);
          showToast(`Copied ${copyKey} to clipboard`);
        });
      }
    }

    return tr;
  };

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
      const isLatestBf = isBitfield(f, f.latest_value);
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
              ${f.is_writable ? '<span class="badge-writable" title="Settable SunSpec register (Read/Write)">RW</span>' : ''}
            </div>
            <span class="field-key">${f.key}</span>
            ${formatBoundsBadge(f)}
          </div>
        </td>
        <td>
          <div class="compound-val-container">
            <div class="val-latest-line">
              <span class="label-dim">Latest:</span>
              <span class="field-value-badge latest${isLatestBf ? ' is-bitfield' : ''}" id="val-${sanitizeId(f.key)}">${latestVal}</span>
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
          <div class="action-cell-container">
            ${f.is_writable ? `<button class="btn btn-secondary btn-sm btn-edit" data-key="${f.key}">Set</button>` : ''}
            <button class="btn btn-secondary btn-sm btn-details" data-key="${f.key}" title="Explore Modbus register definition &amp; associated registers">Details</button>
            <div class="action-menu-wrapper">
              <button class="btn btn-secondary btn-sm btn-icon-more" data-key="${f.key}" title="More Actions">⋮</button>
              <div class="action-dropdown-menu">
                <button class="action-menu-item item-details" data-key="${f.key}">📋 Modbus Details</button>
                ${f.is_writable ? `<button class="action-menu-item item-edit" data-key="${f.key}">✏️ Edit Value</button>` : ''}
                <button class="action-menu-item item-copy" data-key="${f.key}">📄 Copy Key</button>
              </div>
            </div>
          </div>
        </td>
      `;
    } else {
      const isChecked = isFieldSelected(f);
      const sourceClass = f.source === 'MQTT_PUSH' ? 'mqtt' : 'modbus';
      const sourceLabel = f.source === 'MQTT_PUSH' ? 'Push MQTT' : 'Modbus';
      const displayVal = formatFieldValue(f.value, f);
      const isBf = isBitfield(f, f.value);

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
              ${f.is_writable ? '<span class="badge-writable" title="Settable SunSpec register (Read/Write)">RW</span>' : ''}
              ${f.mqtt_equivalent ? `<span class="badge-mqtt-linked" title="Direct Push MQTT equivalent: ${f.mqtt_equivalent}">⚡ Push MQTT</span>` : ''}
              ${f.compound_key ? `<span class="badge-compound-linked" title="Represented by merged telemetry point: ${f.compound_key}">⚡ Merged</span>` : ''}
            </div>
            <span class="field-key">${f.key}</span>
            ${formatBoundsBadge(f)}
          </div>
        </td>
        <td>
          <span class="field-value-badge${isBf ? ' is-bitfield' : ''}" id="val-${sanitizeId(f.key)}">${displayVal}</span>
        </td>
        <td>${f.units || '&mdash;'}</td>
        <td>
          <span class="source-tag ${sourceClass}">${sourceLabel}</span>
        </td>
        <td>
          <span class="type-tag">${f.ha_platform}${f.ha_device_class ? ': ' + f.ha_device_class : ''}</span>
        </td>
        <td class="text-right">
          <div class="action-cell-container">
            ${f.is_writable ? `<button class="btn btn-secondary btn-sm btn-edit" data-key="${f.key}">Set</button>` : ''}
            <button class="btn btn-secondary btn-sm btn-details" data-key="${f.key}" title="Explore Modbus register definition &amp; associated registers">Details</button>
            <div class="action-menu-wrapper">
              <button class="btn btn-secondary btn-sm btn-icon-more" data-key="${f.key}" title="More Actions">⋮</button>
              <div class="action-dropdown-menu">
                <button class="action-menu-item item-details" data-key="${f.key}">📋 Modbus Details</button>
                ${f.is_writable ? `<button class="action-menu-item item-edit" data-key="${f.key}">✏️ Edit Value</button>` : ''}
                <button class="action-menu-item item-copy" data-key="${f.key}">📄 Copy Key</button>
              </div>
            </div>
          </div>
        </td>
      `;
    }

    // Checkbox toggle
    const chk = tr.querySelector('.ha-checkbox');
    chk.addEventListener('change', (e) => {
      toggleHaSelection(f, e.target.checked);
    });

    // Details button
    const detailsBtn = tr.querySelector('.btn-details');
    if (detailsBtn) {
      detailsBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        openFieldDetails(f);
      });
    }

    // Label click to open details
    const labelSpan = tr.querySelector('.field-label');
    if (labelSpan) {
      labelSpan.style.cursor = 'pointer';
      labelSpan.title = (f.description ? `${f.description}\n` : '') + 'Click to view Modbus register details';
      labelSpan.addEventListener('click', () => openFieldDetails(f));
    }

    // Actions dropdown menu
    const moreBtn = tr.querySelector('.btn-icon-more');
    const dropdownMenu = tr.querySelector('.action-dropdown-menu');
    if (moreBtn && dropdownMenu) {
      moreBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        document.querySelectorAll('.action-dropdown-menu.show').forEach(m => {
          if (m !== dropdownMenu) m.classList.remove('show');
        });
        dropdownMenu.classList.toggle('show');
      });

      const menuDetails = dropdownMenu.querySelector('.item-details');
      if (menuDetails) {
        menuDetails.addEventListener('click', (e) => {
          e.stopPropagation();
          dropdownMenu.classList.remove('show');
          openFieldDetails(f);
        });
      }

      const menuEdit = dropdownMenu.querySelector('.item-edit');
      if (menuEdit) {
        menuEdit.addEventListener('click', (e) => {
          e.stopPropagation();
          dropdownMenu.classList.remove('show');
          openWriteModal(f);
        });
      }

      const menuCopy = dropdownMenu.querySelector('.item-copy');
      if (menuCopy) {
        menuCopy.addEventListener('click', (e) => {
          e.stopPropagation();
          dropdownMenu.classList.remove('show');
          copyToClipboard(f.key);
          showToast(`Copied ${f.key} to clipboard`);
        });
      }
    }

    // Edit button
    const editBtn = tr.querySelector('.btn-edit');
    if (editBtn) {
      editBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        openWriteModal(f);
      });
    }

    return tr;
  };

  const fragment = document.createDocumentFragment();

  if (isUnified) {
    filtered.forEach(f => {
      fragment.appendChild(renderUnifiedRow(f));
    });
  } else if (state.groupByModel) {
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
      fragment.appendChild(headerTr);
      grp.fields.forEach(f => {
        fragment.appendChild(renderSingleRow(f));
      });
    });
  } else {
    filtered.forEach(f => {
      fragment.appendChild(renderSingleRow(f));
    });
  }

  el.fieldTableBody.appendChild(fragment);
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

function isBitfield(field, val) {
  if (field && (field.is_bitfield || (field.point_type && field.point_type.startsWith('bitfield')))) {
    return true;
  }
  if (Array.isArray(val)) {
    return true;
  }
  if (typeof val === 'string') {
    const s = val.trim();
    if (s.startsWith('[') && s.endsWith(']') && s.includes(',')) {
      return true;
    }
  }
  return false;
}

function decodeBitfieldSymbols(field, val) {
  const symbols = field ? (field.symbols || []) : [];

  // Case 1: val is an array of symbol names (already decoded by backend)
  if (Array.isArray(val)) {
    return val.map(s => String(s).trim()).filter(Boolean);
  }
  if (field && field.bitmask_flags && Array.isArray(field.bitmask_flags)) {
    return field.bitmask_flags.map(s => String(s).trim()).filter(Boolean);
  }

  // Case 2: bracketed or comma separated string e.g. "[ REBUS_CONNECTED,GRID_CONNECTED,... ]"
  if (typeof val === 'string') {
    let cleanVal = val.trim();
    if (cleanVal.startsWith('[') && cleanVal.endsWith(']')) {
      cleanVal = cleanVal.slice(1, -1).trim();
    }
    if (cleanVal.includes(',')) {
      return cleanVal.split(',').map(s => s.trim().replace(/^['"]|['"]$/g, '')).filter(Boolean);
    }
  }

  // Case 3: raw_value or val is integer
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

  return [];
}

function formatBitfieldValue(val, field) {
  const activeFlags = decodeBitfieldSymbols(field, val);
  const rawNum = field && typeof field.raw_value === 'number' ? field.raw_value : (typeof val === 'number' ? val : null);
  const rawHex = rawNum !== null ? `0x${(rawNum >>> 0).toString(16).toUpperCase()}` : null;
  const rawSuffix = rawNum !== null ? `<span class="bitfield-raw-note">(${rawHex} / ${rawNum})</span>` : '';

  if (!activeFlags || activeFlags.length === 0) {
    return `<div class="bitfield-badges-wrap"><span class="badge-flag none">NONE (0)</span>${rawSuffix}</div>`;
  }

  const tags = activeFlags.map(flag => {
    let title = flag;
    if (field && field.symbols) {
      const sym = field.symbols.find(s => s.name === flag || String(s.value) === String(flag));
      if (sym) {
        title = `Bit ${sym.value}: ${sym.label || sym.name}${sym.desc ? ' - ' + sym.desc : ''}`;
      }
    }
    return `<span class="badge-flag active" title="${escapeHtml(title)}">${escapeHtml(flag)}</span>`;
  }).join('');

  return `<div class="bitfield-badges-wrap">${tags}${rawSuffix}</div>`;
}

function formatFieldValue(val, field = null) {
  if (val === null || val === undefined) return '&mdash;';

  if (isBitfield(field, val)) {
    return formatBitfieldValue(val, field);
  }

  if (field) {
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
  const isUnified = state.viewMode === 'unified';
  if (isUnified) {
    const fields = state.unifiedFields || [];
    if (el.counts.all) el.counts.all.textContent = fields.length;
    if (el.counts.compound) {
      el.counts.compound.textContent = fields.filter(f => f.sources && f.sources.length > 1).length;
    }
    if (el.counts.selected) el.counts.selected.textContent = fields.filter(f => isFieldSelected(f)).length;
    if (el.counts.sensor) el.counts.sensor.textContent = fields.filter(f => f.ha_platform === 'sensor').length;
    if (el.counts.writable) el.counts.writable.textContent = fields.filter(f => f.is_writable).length;
    if (el.counts.push) el.counts.push.textContent = fields.filter(f => f.sources && f.sources.some(s => s.source_type === 'MQTT')).length;
    if (el.counts.modbus) el.counts.modbus.textContent = fields.filter(f => f.sources && f.sources.some(s => s.source_type === 'SUNSPEC')).length;
    if (el.counts.scalefactor) el.counts.scalefactor.textContent = fields.filter(f => isScaleFactorField(f)).length;
  } else {
    const fields = state.activeFields;
    if (el.counts.all) el.counts.all.textContent = fields.length;
    if (el.counts.compound) {
      el.counts.compound.textContent = fields.filter(f => f.is_compound).length;
    }
    if (el.counts.selected) el.counts.selected.textContent = fields.filter(f => isFieldSelected(f)).length;
    if (el.counts.sensor) el.counts.sensor.textContent = fields.filter(f => f.ha_platform === 'sensor').length;
    if (el.counts.writable) el.counts.writable.textContent = fields.filter(f => f.is_writable).length;
    if (el.counts.push) el.counts.push.textContent = fields.filter(f => f.source === 'MQTT_PUSH' && !f.is_compound).length;
    if (el.counts.modbus) el.counts.modbus.textContent = fields.filter(f => (f.source === 'MODBUS_POLL' || f.source === 'MODBUS_CONFIG') && !f.is_compound).length;
    if (el.counts.scalefactor) el.counts.scalefactor.textContent = fields.filter(f => isScaleFactorField(f)).length;
  }

  // Dynamic visibility for mode-specific controls to save vertical space
  const currentFields = isUnified ? (state.unifiedFields || []) : (state.activeFields || []);
  const hasSf = currentFields.some(f => isScaleFactorField(f));
  const sfPill = el.filterPills ? el.filterPills.querySelector('[data-filter="scalefactor"]') : null;
  if (sfPill) {
    sfPill.style.display = hasSf ? 'inline-flex' : 'none';
  }
  const optScale = document.getElementById('optHideScaleFactors');
  const optRaw = document.getElementById('optHideCombinedRaw');
  if (optScale) optScale.style.display = hasSf ? 'inline-flex' : 'none';
  if (optRaw) optRaw.style.display = isUnified ? 'none' : 'inline-flex';
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

    // Update unified fields cache
    if (state.unifiedFields) {
      state.unifiedFields.forEach(g => {
        let matched = false;
        (g.sources || []).forEach(s => {
          if (s.field_key === field.key) {
            s.value = field.value;
            s.raw_value = field.raw_value;
            matched = true;
          }
        });
        if (matched) {
          const activeKey = state.preferredSources[g.id] || g.active_source_key;
          if (activeKey === field.key) {
            g.latest_value = field.value;
            const valBadge = document.getElementById(`val-${sanitizeId(g.id)}`);
            if (valBadge) {
              valBadge.innerHTML = formatFieldValue(field.value, g);
              valBadge.classList.toggle('is-bitfield', isBitfield(g, field.value));
              valBadge.classList.add('value-flash');
              setTimeout(() => valBadge.classList.remove('value-flash'), 600);
            }
          }
        }
      });
    }

    // Flash value in table
    const valBadge = document.getElementById(`val-${sanitizeId(field.key)}`);
    if (valBadge) {
      valBadge.innerHTML = formatFieldValue(field.value, field);
      valBadge.classList.toggle('is-bitfield', isBitfield(field, field.value));
      valBadge.classList.add('value-flash');
      setTimeout(() => valBadge.classList.remove('value-flash'), 600);
    }
  }
}

// Write Modal Handling
let targetWriteField = null;

function renderWriteModalBounds(field) {
  if (!el.writeModalBounds) return;
  const b = getFieldBounds(field);
  if (!b) {
    el.writeModalBounds.innerHTML = '';
    return;
  }

  let rangeText = '--';
  let rawText = '--';
  let sfText = b.sf ? `${b.sf}${b.sf_value !== null && b.sf_value !== undefined ? ' (10^' + b.sf_value + ')' : ''}` : 'Direct (No Scale Factor)';
  let stepText = b.step !== undefined ? String(b.step) : '1';
  let typeDesc = b.point_type || 'uint16';
  let sentinelText = b.sentinel ? `0x${b.sentinel.toString(16).toUpperCase()}` : 'None';

  if (b.category === 'numeric') {
    if (b.scaled_min !== null && b.scaled_min !== undefined && b.scaled_max !== null && b.scaled_max !== undefined) {
      rangeText = `${b.scaled_min} to ${b.scaled_max} ${b.units || ''}`.trim();
      rawText = `${b.raw_min.toLocaleString()} to ${b.raw_max.toLocaleString()}`;
    } else if (b.raw_min !== null && b.raw_min !== undefined) {
      rangeText = `${b.raw_min.toLocaleString()} to ${b.raw_max.toLocaleString()} ${b.units || ''}`.trim();
      rawText = rangeText;
    }
  } else if (b.category === 'enum') {
    rangeText = `${b.valid_values?.length || 0} discrete symbols`;
    rawText = b.raw_min !== null && b.raw_min !== undefined ? `${b.raw_min} to ${b.raw_max}` : 'Discrete symbols';
  } else if (b.category === 'bitfield') {
    rangeText = `Bitmask 0x0000 to ${b.mask_hex || '0xFFFF'}`;
    rawText = `0 to ${b.raw_max}`;
  } else if (b.category === 'string') {
    rangeText = `Max ${b.max_length} characters`;
    rawText = `${field.size || 1} register(s)`;
  } else if (b.category === 'float') {
    rangeText = `IEEE 754 Float ${b.units || ''}`.trim();
    rawText = '32-bit float';
  }

  el.writeModalBounds.innerHTML = `
    <div class="write-bounds-card">
      <div class="write-bounds-header">
        <span class="write-bounds-title">📏 SunSpec Bounds &amp; Restrictions</span>
        <span class="badge-writable">Read/Write (RW)</span>
      </div>
      <div class="write-bounds-grid">
        <div class="write-bounds-item">
          <span class="write-bounds-lbl">Allowed Range</span>
          <span class="write-bounds-val">${escapeHtml(rangeText)}</span>
        </div>
        <div class="write-bounds-item">
          <span class="write-bounds-lbl">Data Type</span>
          <span class="write-bounds-val">${escapeHtml(typeDesc)}</span>
        </div>
        ${b.category === 'numeric' ? `
        <div class="write-bounds-item">
          <span class="write-bounds-lbl">Raw Modbus Range</span>
          <span class="write-bounds-val">${escapeHtml(rawText)}</span>
        </div>
        <div class="write-bounds-item">
          <span class="write-bounds-lbl">Resolution / Step</span>
          <span class="write-bounds-val">${escapeHtml(stepText)}</span>
        </div>
        ` : ''}
        ${b.sf ? `
        <div class="write-bounds-item">
          <span class="write-bounds-lbl">Scale Factor</span>
          <span class="write-bounds-val">${escapeHtml(sfText)}</span>
        </div>
        ` : ''}
        ${b.sentinel ? `
        <div class="write-bounds-item">
          <span class="write-bounds-lbl">Reserved Sentinel</span>
          <span class="write-bounds-val">${escapeHtml(sentinelText)}</span>
        </div>
        ` : ''}
      </div>
      ${b.description ? `<div class="write-bounds-desc">ℹ️ <strong>SunSpec Specification:</strong> ${escapeHtml(b.description)}</div>` : ''}
    </div>
  `;
}

function openWriteModal(field) {
  targetWriteField = field;
  el.writeModalTitle.textContent = `Set ${field.label}`;
  
  if (el.writeModalError) {
    el.writeModalError.style.display = 'none';
    el.writeModalError.textContent = '';
  }

  renderWriteModalBounds(field);

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
  } else if (field.point_type && ['uint16', 'int16', 'uint32', 'int32', 'uint64', 'int64', 'acc16', 'acc32', 'count', 'sunssf'].includes(field.point_type)) {
    // Numeric input restricted to bounds
    const input = document.createElement('input');
    input.type = 'number';
    input.className = 'text-input';
    input.id = 'writeTextInput';

    const b = getFieldBounds(field);
    const minVal = b.scaled_min !== null && b.scaled_min !== undefined ? b.scaled_min : b.raw_min;
    const maxVal = b.scaled_max !== null && b.scaled_max !== undefined ? b.scaled_max : b.raw_max;
    if (minVal !== null && minVal !== undefined) input.min = minVal;
    if (maxVal !== null && maxVal !== undefined) input.max = maxVal;
    input.step = b.step !== null && b.step !== undefined ? b.step : 1;

    const hint = document.createElement('small');
    hint.className = 'field-input-hint';
    hint.style.display = 'block';
    hint.style.marginTop = '6px';
    hint.style.color = 'var(--text-muted)';
    hint.textContent = `SunSpec allowed range: ${minVal} to ${maxVal}${b.units ? ' ' + b.units : ''} (step: ${input.step})`;

    input.value = field.value !== null && field.value !== undefined ? field.value : (field.raw_value !== null ? field.raw_value : '');
    el.writeInputContainer.appendChild(input);
    el.writeInputContainer.appendChild(hint);
  } else if (field.point_type === 'string') {
    // String input with max length
    const b = getFieldBounds(field);
    const maxLen = b.max_length || ((field.size || 1) * 2);
    const input = document.createElement('input');
    input.type = 'text';
    input.maxLength = maxLen;
    input.className = 'text-input';
    input.id = 'writeTextInput';
    input.value = field.value !== null && field.value !== undefined ? field.value : '';

    const counter = document.createElement('div');
    counter.className = 'write-char-counter';
    counter.id = 'writeCharCounter';
    counter.textContent = `${input.value.length} / ${maxLen} characters`;

    input.addEventListener('input', () => {
      counter.textContent = `${input.value.length} / ${maxLen} characters`;
    });

    el.writeInputContainer.appendChild(input);
    el.writeInputContainer.appendChild(counter);
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

  function showWriteError(msg) {
    if (el.writeModalError) {
      el.writeModalError.innerHTML = `<span>⚠️ ${escapeHtml(msg)}</span>`;
      el.writeModalError.style.display = 'flex';
    } else {
      alert(msg);
    }
  }

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
    showWriteError('Please enter a value');
    return;
  }

  // Client-side validation against SunSpec bounds
  const b = getFieldBounds(targetWriteField);
  if (b) {
    if (b.category === 'numeric') {
      const num = Number(newVal);
      if (isNaN(num)) {
        showWriteError(`Value must be a valid number`);
        return;
      }
      const isIntegerType = ['uint16', 'int16', 'uint32', 'int32', 'acc16', 'acc32', 'count'].includes(targetWriteField.point_type);
      if (isIntegerType && b.scaled_min === null && !Number.isInteger(num)) {
        showWriteError(`Value must be an integer for ${targetWriteField.point_type}`);
        return;
      }
      const minVal = b.scaled_min !== null && b.scaled_min !== undefined ? b.scaled_min : b.raw_min;
      const maxVal = b.scaled_max !== null && b.scaled_max !== undefined ? b.scaled_max : b.raw_max;
      if (minVal !== null && maxVal !== null && (num < minVal || num > maxVal)) {
        showWriteError(`Value ${num} is out of SunSpec bounds (${minVal} to ${maxVal}${b.units ? ' ' + b.units : ''})`);
        return;
      }
    } else if (b.category === 'string') {
      if (b.max_length && newVal.length > b.max_length) {
        showWriteError(`Value exceeds maximum SunSpec character length of ${b.max_length}`);
        return;
      }
    } else if (b.category === 'enum') {
      if (b.valid_names && b.valid_names.length > 0) {
        const isValid = b.valid_names.includes(newVal) || (b.valid_values && b.valid_values.includes(Number(newVal)));
        if (!isValid) {
          showWriteError(`Invalid enum symbol '${newVal}'. Allowed: ${b.valid_names.join(', ')}`);
          return;
        }
      }
    }
  }

  const targetKey = targetWriteField.field_key || targetWriteField.key || targetWriteField.active_source_key || targetWriteField.id;

  try {
    const res = await fetch(apiPath('api/fields/write'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ field_key: targetKey, value: newVal }),
    });
    const data = await res.json();
    if (data.success) {
      const confirmedVal = data.value !== undefined ? data.value : newVal;
      const displayConfirmed = Array.isArray(confirmedVal) ? (confirmedVal.join(', ') || 'NONE') : confirmedVal;
      showToast(`Wrote ${targetWriteField.label} = ${displayConfirmed}`);
      targetWriteField.value = confirmedVal;
      targetWriteField.last_updated = Date.now() / 1000;

      // Update UI row immediately
      const id = sanitizeId(targetKey);
      const valBadge = document.getElementById(`val-${id}`) || (targetWriteField.id ? document.getElementById(`val-${sanitizeId(targetWriteField.id)}`) : null);
      if (valBadge) {
        valBadge.innerHTML = formatFieldValue(confirmedVal, targetWriteField);
        valBadge.classList.toggle('is-bitfield', isBitfield(targetWriteField, confirmedVal));
        valBadge.classList.add('value-flash');
        setTimeout(() => valBadge.classList.remove('value-flash'), 600);
      }

      el.writeModal.classList.remove('open');
    } else {
      showWriteError(data.error || 'Failed writing value');
    }
  } catch (err) {
    showWriteError(`Failed sending write request: ${err}`);
  }
}

// Utilities
function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function copyToClipboard(text) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text);
  } else {
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
  }
}

let currentDetailsData = null;

function closeFieldDetails() {
  if (el.modbusDetailsModal) {
    el.modbusDetailsModal.classList.remove('open');
  }
}

async function openFieldDetails(fieldOrKey, optSerial) {
  let fieldKey = '';
  let devSerial = optSerial || '';

  if (typeof fieldOrKey === 'string') {
    fieldKey = fieldOrKey;
  } else if (fieldOrKey && typeof fieldOrKey === 'object') {
    fieldKey = fieldOrKey.field_key || fieldOrKey.key || fieldOrKey.active_source_key || fieldOrKey.id || '';
    if (!devSerial && fieldOrKey.device_sn) {
      devSerial = fieldOrKey.device_sn;
    }
  }

  if (!devSerial && state.activeDevice) {
    devSerial = state.activeDevice.serial_number;
  }

  if (!fieldKey || fieldKey === 'undefined') {
    console.error('openFieldDetails called without valid field key:', fieldOrKey);
    showToast('Unable to determine field key for details');
    return;
  }

  if (!devSerial) {
    showToast('Select a device to view Modbus details');
    return;
  }

  if (el.modbusDetailsModal) {
    el.modbusDetailsModal.classList.add('open');
    if (el.detailsModalTitle) {
      el.detailsModalTitle.textContent = (typeof fieldOrKey === 'object' && fieldOrKey.label) ? fieldOrKey.label : fieldKey;
    }
    if (el.detailsModalKey) {
      el.detailsModalKey.textContent = fieldKey;
    }
    if (el.detailsModalBody) {
      el.detailsModalBody.innerHTML = '<div class="loading-spinner">Loading Modbus details...</div>';
    }
  }

  try {
    const url = apiPath(`api/devices/${encodeURIComponent(devSerial)}/field_details?field_key=${encodeURIComponent(fieldKey)}`);
    const res = await fetch(url);
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.error || `HTTP ${res.status}`);
    }
    const data = await res.json();
    currentDetailsData = data;
    renderFieldDetailsModal(data);
  } catch (err) {
    console.error('Failed loading field details:', err);
    if (el.detailsModalBody) {
      el.detailsModalBody.innerHTML = `
        <div class="empty-state">
          <p style="color: #ef4444; font-weight: 600; margin-bottom: 8px;">Failed to load Modbus details</p>
          <p class="text-muted">${escapeHtml(err.message)}</p>
        </div>
      `;
    }
  }
}

function renderFieldDetailsModal(data) {
  if (!el.detailsModalBody) return;

  const f = data.field || {};
  const pt = data.point_def || {};
  const model = data.model || {};
  const sf = data.scale_factor;
  const dev = data.device || {};

  // Update header badges
  if (el.detailsModalTitle) {
    el.detailsModalTitle.textContent = f.label || pt.label || f.name || f.key;
  }
  if (el.detailsModalKey) {
    el.detailsModalKey.textContent = f.key || pt.name;
  }
  if (el.detailsSourceBadge) {
    const src = f.source || 'MODBUS';
    el.detailsSourceBadge.textContent = src === 'MQTT_PUSH' ? '⚡ PUSH MQTT' : (f.is_compound ? '⚡ COMPOUND' : 'MODBUS REGISTER');
    el.detailsSourceBadge.className = `source-tag ${src === 'MQTT_PUSH' ? 'mqtt' : (f.is_compound ? 'compound' : 'modbus')}`;
  }
  if (el.detailsDeviceLabel) {
    el.detailsDeviceLabel.textContent = `Device: ${dev.model_name || dev.device_type} (SN: ${dev.serial_number}${dev.slave_id !== null && dev.slave_id !== undefined ? `, Slave ID: ${dev.slave_id}` : ''})`;
  }

  let html = '';

  // 1. Top Summary Cards (Current Value, Raw Register, Addressing, Access & Type)
  const displayVal = formatFieldValue(f.value, f);
  const offsetStr = (f.offset !== null && f.offset !== undefined) ? `+${f.offset}` : ((pt.offset !== null && pt.offset !== undefined) ? `+${pt.offset}` : '--');
  const sizeStr = f.size || pt.size || 1;
  const bitsStr = `${sizeStr * 16}-bit`;
  const accessStr = f.access === 'RW' || pt.access === 'RW' ? 'Read-Write (RW)' : 'Read-Only (R)';
  const fcStr = f.access === 'RW' || pt.access === 'RW' ? 'FC03 / FC06, FC16' : 'FC03 (Read)';
  const modelTag = model.model_id ? `Model ${model.model_id} (${model.name})` : (f.model_name || 'N/A');

  html += `
    <div class="details-summary-grid">
      <div class="details-card">
        <span class="details-card-lbl">Current Processed Value</span>
        <div class="details-card-val">
          <span>${displayVal}</span>
          ${f.units ? `<span class="unit-text">${f.units}</span>` : ''}
        </div>
        <span class="details-card-sub">Interpreted physical engineering value</span>
      </div>

      <div class="details-card">
        <span class="details-card-lbl">Raw Modbus Register Content</span>
        <div class="details-card-val">
          <span>${f.raw_value !== null && f.raw_value !== undefined ? f.raw_value : '--'}</span>
          ${f.raw_hex ? `<span class="raw-hex-badge">${f.raw_hex}</span>` : ''}
        </div>
        ${f.raw_bin ? `<span class="details-card-sub" style="font-family: var(--font-mono); font-size: 10px;">BIN: ${f.raw_bin}</span>` : '<span class="details-card-sub">Unscaled holding register word(s)</span>'}
      </div>

      <div class="details-card">
        <span class="details-card-lbl">Modbus Addressing</span>
        <div class="details-card-val">
          <span>Offset ${offsetStr}</span>
        </div>
        <span class="details-card-sub">${modelTag} • ${sizeStr} word (${bitsStr}, ${fcStr})</span>
      </div>

      <div class="details-card">
        <span class="details-card-lbl">SunSpec Metamodel &amp; Access</span>
        <div class="details-card-val">
          <span style="font-size: 15px;">${f.point_type || pt.type || 'uint16'}</span>
        </div>
        <span class="details-card-sub">${accessStr} • Big-Endian</span>
      </div>
    </div>
  `;

  // 2. SunSpec Bounds & Restrictions Card
  const bounds = data.bounds || pt.bounds || f.bounds || getFieldBounds(f);
  if (bounds) {
    const isSettable = f.is_writable || pt.is_writable || false;
    let bRange = '--';
    let bRaw = '--';
    let bStep = bounds.step !== undefined ? String(bounds.step) : '1';
    let bType = bounds.point_type || pt.type || f.point_type || 'uint16';
    let bSentinel = bounds.sentinel ? `0x${bounds.sentinel.toString(16).toUpperCase()} (Invalid / Unsupported)` : 'None';
    let bSf = bounds.sf ? `${bounds.sf}${bounds.sf_value !== null && bounds.sf_value !== undefined ? ' (10^' + bounds.sf_value + ')' : ''}` : 'Direct (No Scale Factor)';

    if (bounds.category === 'numeric') {
      if (bounds.scaled_min !== null && bounds.scaled_min !== undefined && bounds.scaled_max !== null && bounds.scaled_max !== undefined) {
        bRange = `${bounds.scaled_min} to ${bounds.scaled_max} ${bounds.units || ''}`.trim();
        bRaw = `${bounds.raw_min.toLocaleString()} to ${bounds.raw_max.toLocaleString()}`;
      } else if (bounds.raw_min !== null && bounds.raw_min !== undefined) {
        bRange = `${bounds.raw_min.toLocaleString()} to ${bounds.raw_max.toLocaleString()} ${bounds.units || ''}`.trim();
        bRaw = bRange;
      }
    } else if (bounds.category === 'enum') {
      bRange = `${bounds.valid_values?.length || 0} discrete symbols`;
      bRaw = bounds.raw_min !== null && bounds.raw_min !== undefined ? `${bounds.raw_min} to ${bounds.raw_max}` : 'Discrete symbols';
    } else if (bounds.category === 'bitfield') {
      bRange = `Bitmask 0x0000 to ${bounds.mask_hex || '0xFFFF'}`;
      bRaw = `0 to ${bounds.raw_max}`;
    } else if (bounds.category === 'string') {
      bRange = `Max ${bounds.max_length} characters`;
      bRaw = `${bounds.size_words || f.size || 1} register(s)`;
    } else if (bounds.category === 'float') {
      bRange = `IEEE 754 Float ${bounds.units || ''}`.trim();
      bRaw = '32-bit float';
    }

    html += `
      <div class="details-bounds-card">
        <div class="details-bounds-header">
          <div class="details-bounds-title">
            <span>📏 SunSpec Bounds &amp; Restrictions</span>
          </div>
          <span class="${isSettable ? 'badge-writable' : 'source-tag'}">
            ${isSettable ? 'RW (Settable)' : 'R (Read-Only)'}
          </span>
        </div>
        <div class="details-bounds-grid">
          <div class="write-bounds-item">
            <span class="write-bounds-lbl">Settable Status</span>
            <span class="write-bounds-val">${isSettable ? 'Read/Write (FC03/FC06/FC16)' : 'Read-Only (FC03)'}</span>
          </div>
          <div class="write-bounds-item">
            <span class="write-bounds-lbl">Allowed Range</span>
            <span class="write-bounds-val">${escapeHtml(bRange)}</span>
          </div>
          <div class="write-bounds-item">
            <span class="write-bounds-lbl">Data Type Definition</span>
            <span class="write-bounds-val">${escapeHtml(bType)}</span>
          </div>
          ${bounds.category === 'numeric' ? `
          <div class="write-bounds-item">
            <span class="write-bounds-lbl">Raw Modbus Range</span>
            <span class="write-bounds-val">${escapeHtml(bRaw)}</span>
          </div>
          <div class="write-bounds-item">
            <span class="write-bounds-lbl">Resolution / Step</span>
            <span class="write-bounds-val">${escapeHtml(bStep)}</span>
          </div>
          ` : ''}
          ${bounds.sf ? `
          <div class="write-bounds-item">
            <span class="write-bounds-lbl">Scale Factor Ref</span>
            <span class="write-bounds-val">${escapeHtml(bSf)}</span>
          </div>
          ` : ''}
          ${bounds.sentinel ? `
          <div class="write-bounds-item">
            <span class="write-bounds-lbl">Reserved Sentinel</span>
            <span class="write-bounds-val">${escapeHtml(bSentinel)}</span>
          </div>
          ` : ''}
        </div>
        ${bounds.description ? `<div class="write-bounds-desc">ℹ️ <strong>SunSpec Specification:</strong> ${escapeHtml(bounds.description)}</div>` : ''}
      </div>
    `;
  }

  // 2. Scale Factor Section
  if (sf) {
    html += `
      <div class="scale-factor-card">
        <div class="sf-card-header">
          <div class="sf-card-title">
            <span>⚖️ Associated Scale Factor: <strong>${escapeHtml(sf.name)}</strong></span>
            <span class="badge-model">Offset +${sf.offset !== null && sf.offset !== undefined ? sf.offset : '--'}</span>
          </div>
          <button class="btn btn-secondary btn-xs btn-inspect-sf" data-key="${escapeHtml(sf.key)}" data-serial="${escapeHtml(dev.serial_number)}" title="Explore Scale Factor Details">
            Inspect ${escapeHtml(sf.name)} ➔
          </button>
        </div>
        <div class="sf-card-content">
          <div class="sf-item">
            <span class="sf-item-lbl">Scale Factor Register</span>
            <span class="sf-item-val">${escapeHtml(sf.label || sf.name)} (${escapeHtml(sf.key)})</span>
            <span class="text-muted" style="font-size: 11px;">${escapeHtml(sf.description || 'SunSpec exponent factor')}</span>
          </div>
          <div class="sf-item">
            <span class="sf-item-lbl">Multiplier &amp; Exponent</span>
            <span class="sf-item-val">Raw Value: <strong>${sf.raw_value !== null ? sf.raw_value : '--'}</strong> ${sf.raw_hex ? `(${sf.raw_hex})` : ''} &bull; Multiplier: <strong>${sf.multiplier !== null ? sf.multiplier : '--'}</strong> (10<sup>${sf.value !== null ? sf.value : 0}</sup>)</span>
          </div>
        </div>
        ${sf.formula ? `<div class="sf-formula-box">📐 ${escapeHtml(sf.formula)}</div>` : ''}
      </div>
    `;
  } else if (f.is_scale_factor || pt.is_scale_factor) {
    html += `
      <div class="scale-factor-card" style="border-color: rgba(16, 185, 129, 0.35); background: linear-gradient(135deg, rgba(16, 185, 129, 0.08), rgba(56, 189, 248, 0.08));">
        <div class="sf-card-header">
          <div class="sf-card-title" style="color: #34d399;">
            <span>⚖️ SunSpec Scale Factor Register (sunssf)</span>
          </div>
        </div>
        <p style="font-size: 12px; color: var(--text-secondary);">
          This register defines an integer base-10 exponent factor (<strong>10<sup>${f.value !== null ? f.value : 0}</sup> = ${f.value !== null && -10 <= f.value && f.value <= 10 ? (10 ** f.value) : '--'}</strong>) applied to scale other telemetry registers in Model ${model.model_id || ''}.
        </p>
      </div>
    `;
  }

  // 3. Points Scaled by this Register (if this point is a scale factor)
  if (data.scaled_points && data.scaled_points.length > 0) {
    html += `
      <div class="details-section">
        <div class="details-section-header">
          <div class="details-section-title">
            <span>🎯 Registers Scaled by this Point</span>
            <span class="details-count-pill">${data.scaled_points.length} registers</span>
          </div>
        </div>
        <div class="table-container" style="max-height: 220px; overflow-y: auto;">
          <table class="associated-regs-table">
            <thead>
              <tr>
                <th>Register</th>
                <th>Offset</th>
                <th>Type</th>
                <th>Raw Value</th>
                <th>Scaled Value</th>
                <th width="70" class="text-right">Action</th>
              </tr>
            </thead>
            <tbody>
              ${data.scaled_points.map(sp => `
                <tr>
                  <td>
                    <div><strong>${escapeHtml(sp.name)}</strong> <small class="text-muted">${escapeHtml(sp.label || '')}</small></div>
                    <span class="field-key">${escapeHtml(sp.key)}</span>
                  </td>
                  <td>+${sp.offset !== null && sp.offset !== undefined ? sp.offset : '--'}</td>
                  <td>${escapeHtml(sp.type || 'uint16')}</td>
                  <td>${sp.raw_value !== null ? sp.raw_value : '--'} ${sp.raw_hex ? `<span class="raw-hex-badge">${sp.raw_hex}</span>` : ''}</td>
                  <td><strong>${sp.value !== null ? sp.value : '--'}</strong> ${sp.units ? escapeHtml(sp.units) : ''}</td>
                  <td class="text-right">
                    <button class="btn btn-secondary btn-xs btn-inspect-reg" data-key="${escapeHtml(sp.key)}" data-serial="${escapeHtml(dev.serial_number)}">View</button>
                  </td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      </div>
    `;
  }

  // 4. Associated & Sibling Registers Table
  if (data.associated_registers && data.associated_registers.length > 0) {
    html += `
      <div class="details-section">
        <div class="details-section-header">
          <div class="details-section-title">
            <span>🔗 Associated Registers</span>
            <span class="details-count-pill">${data.associated_registers.length}</span>
          </div>
        </div>
        <div class="table-container" style="max-height: 240px; overflow-y: auto;">
          <table class="associated-regs-table">
            <thead>
              <tr>
                <th>Register &amp; Label</th>
                <th>Relationship</th>
                <th>Offset</th>
                <th>Type</th>
                <th>Raw</th>
                <th>Current Value</th>
                <th width="70" class="text-right">Action</th>
              </tr>
            </thead>
            <tbody>
              ${data.associated_registers.map(ar => {
                let relClass = 'rel-shared-sf';
                if (ar.relationship === 'Scale Factor') relClass = 'rel-scale-factor';
                else if (ar.relationship.startsWith('Scaled by')) relClass = 'rel-scaled-by';
                else if (ar.relationship === 'Phase Sibling') relClass = 'rel-sibling';

                const dispVal = ar.value !== null && ar.value !== undefined ? `${ar.value} ${ar.units || ''}` : '--';
                return `
                  <tr>
                    <td>
                      <div><strong>${escapeHtml(ar.name)}</strong> <small class="text-muted">${escapeHtml(ar.label || '')}</small></div>
                      <span class="field-key">${escapeHtml(ar.key)}</span>
                    </td>
                    <td><span class="rel-badge ${relClass}">${escapeHtml(ar.relationship)}</span></td>
                    <td>+${ar.offset !== null && ar.offset !== undefined ? ar.offset : '--'}</td>
                    <td>${escapeHtml(ar.type || 'uint16')}</td>
                    <td>${ar.raw_value !== null ? ar.raw_value : '--'} ${ar.raw_hex ? `<span class="raw-hex-badge">${ar.raw_hex}</span>` : ''}</td>
                    <td><strong>${escapeHtml(dispVal)}</strong></td>
                    <td class="text-right">
                      <button class="btn btn-secondary btn-xs btn-inspect-reg" data-key="${escapeHtml(ar.key)}" data-serial="${escapeHtml(dev.serial_number)}">View</button>
                    </td>
                  </tr>
                `;
              }).join('')}
            </tbody>
          </table>
        </div>
      </div>
    `;
  }

  // 5. Enum Symbols Table (if enum)
  if (data.enum_symbols && data.enum_symbols.length > 0) {
    html += `
      <div class="details-section">
        <div class="details-section-header">
          <div class="details-section-title">
            <span>🔢 Enum Option Symbols</span>
            <span class="details-count-pill">${data.enum_symbols.length} symbols</span>
          </div>
        </div>
        <div class="table-container" style="max-height: 200px; overflow-y: auto;">
          <table class="modal-symbols-table">
            <thead>
              <tr>
                <th width="60">Value</th>
                <th>Symbol Name</th>
                <th>Label / Description</th>
                <th width="90" class="text-center">Status</th>
              </tr>
            </thead>
            <tbody>
              ${data.enum_symbols.map(sym => `
                <tr class="${sym.is_active ? 'symbol-row-active' : ''}">
                  <td><code>${sym.value}</code></td>
                  <td><strong>${escapeHtml(sym.name)}</strong></td>
                  <td>${escapeHtml(sym.label || '')} <small class="text-muted">${escapeHtml(sym.desc || '')}</small></td>
                  <td class="text-center">
                    ${sym.is_active ? '<span class="badge-active-sym">✓ ACTIVE</span>' : '<span class="text-muted">&mdash;</span>'}
                  </td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      </div>
    `;
  }

  // 6. Bitfield Flags Table (if bitfield)
  if (data.bitfield_flags && data.bitfield_flags.length > 0) {
    html += `
      <div class="details-section">
        <div class="details-section-header">
          <div class="details-section-title">
            <span>🚩 Bitfield Flag Definitions</span>
            <span class="details-count-pill">${data.bitfield_flags.length} flags</span>
          </div>
        </div>
        <div class="table-container" style="max-height: 220px; overflow-y: auto;">
          <table class="modal-symbols-table">
            <thead>
              <tr>
                <th width="50">Bit</th>
                <th width="80">Mask</th>
                <th>Flag Name</th>
                <th>Description</th>
                <th width="90" class="text-center">Status</th>
              </tr>
            </thead>
            <tbody>
              ${data.bitfield_flags.map(bf => `
                <tr class="${bf.is_set ? 'symbol-row-active' : ''}">
                  <td><code>${bf.bit}</code></td>
                  <td><code>${bf.mask}</code></td>
                  <td><strong>${escapeHtml(bf.name)}</strong></td>
                  <td><span class="text-muted">${escapeHtml(bf.desc || bf.label || '')}</span></td>
                  <td class="text-center">
                    ${bf.is_set ? '<span class="badge-set-flag">SET (1)</span>' : '<span class="badge-clear-flag">CLEAR (0)</span>'}
                  </td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      </div>
    `;
  }

  // 7. Compound / Telemetry Link Card (if linked or compound)
  if (data.compound_link) {
    const cl = data.compound_link;
    const matchStr = cl.match_pct !== null && cl.match_pct !== undefined ? `${cl.match_pct}% match` : '';
    const deltaStr = cl.delta !== null && cl.delta !== undefined ? `Delta: ${cl.delta}` : '';
    html += `
      <div class="scale-factor-card" style="border-color: rgba(236, 72, 153, 0.35); background: linear-gradient(135deg, rgba(236, 72, 153, 0.08), rgba(99, 102, 241, 0.08));">
        <div class="sf-card-header">
          <div class="sf-card-title" style="color: #f472b6;">
            <span>⚡ Unified Telemetry Link: <strong>${escapeHtml(cl.label || cl.mapping_id || cl.key)}</strong></span>
          </div>
          <span class="source-tag compound">Compound View</span>
        </div>
        <div class="sf-card-content" style="grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));">
          <div class="sf-item">
            <span class="sf-item-lbl">Latest Combined Value</span>
            <span class="sf-item-val" style="font-size: 15px; font-weight: 700;">${cl.latest_value !== null ? cl.latest_value : '--'}</span>
            <span class="text-muted" style="font-size: 11px;">Source: ${cl.latest_source || 'NONE'}</span>
          </div>
          <div class="sf-item">
            <span class="sf-item-lbl">Direct Push MQTT</span>
            <span class="sf-item-val">${cl.mqtt_value !== null ? cl.mqtt_value : '--'}</span>
            <span class="text-muted" style="font-size: 11px;">${cl.mqtt_key || '--'}</span>
          </div>
          <div class="sf-item">
            <span class="sf-item-lbl">Polled Modbus Register</span>
            <span class="sf-item-val">${cl.modbus_value !== null ? cl.modbus_value : '--'}</span>
            <span class="text-muted" style="font-size: 11px;">${cl.modbus_key || '--'}</span>
          </div>
          <div class="sf-item">
            <span class="sf-item-lbl">Correlation</span>
            <span class="sf-item-val">${matchStr} ${deltaStr ? `(${deltaStr})` : ''}</span>
          </div>
        </div>
      </div>
    `;
  }

  // 8. Raw Specification Properties Grid
  html += `
    <div class="details-section">
      <div class="details-section-header">
        <div class="details-section-title">
          <span>📋 SunSpec &amp; Modbus Register Definition Specification</span>
        </div>
      </div>
      <table class="def-props-table">
        <tbody>
          <tr>
            <td class="def-prop-key">Point Identifier</td>
            <td class="def-prop-val"><strong>${escapeHtml(pt.name || f.name)}</strong></td>
          </tr>
          <tr>
            <td class="def-prop-key">Official Label</td>
            <td class="def-prop-val">${escapeHtml(pt.label || f.label || '')}</td>
          </tr>
          <tr>
            <td class="def-prop-key">Field Key</td>
            <td class="def-prop-val"><code>${escapeHtml(f.key || '')}</code></td>
          </tr>
          <tr>
            <td class="def-prop-key">SunSpec Description</td>
            <td class="def-prop-val">${escapeHtml(pt.desc || f.description || 'No description provided')}</td>
          </tr>
          <tr>
            <td class="def-prop-key">SunSpec Model</td>
            <td class="def-prop-val">Model ${model.model_id || 'N/A'}: ${escapeHtml(model.label || model.name || '')} (<code>${escapeHtml(model.name || '')}</code>)</td>
          </tr>
          ${model.desc ? `
          <tr>
            <td class="def-prop-key">Model Description</td>
            <td class="def-prop-val text-muted">${escapeHtml(model.desc)}</td>
          </tr>
          ` : ''}
          <tr>
            <td class="def-prop-key">Modbus Word Offset</td>
            <td class="def-prop-val">+${offsetStr} (relative to SunSpec model block start)</td>
          </tr>
          <tr>
            <td class="def-prop-key">Register Word Count</td>
            <td class="def-prop-val">${sizeStr} register${sizeStr > 1 ? 's' : ''} (${sizeStr * 16} bits, ${sizeStr * 2} bytes)</td>
          </tr>
          <tr>
            <td class="def-prop-key">Modbus Function Codes</td>
            <td class="def-prop-val"><code>${fcStr}</code> &bull; Holding Registers</td>
          </tr>
          <tr>
            <td class="def-prop-key">Byte &amp; Word Order</td>
            <td class="def-prop-val">Big-Endian (SunSpec standard MSB-first)</td>
          </tr>
          <tr>
            <td class="def-prop-key">SunSpec Point Type</td>
            <td class="def-prop-val"><code>${escapeHtml(pt.type || f.point_type || 'uint16')}</code></td>
          </tr>
          <tr>
            <td class="def-prop-key">Modbus Access</td>
            <td class="def-prop-val">${accessStr}</td>
          </tr>
          <tr>
            <td class="def-prop-key">Physical Units</td>
            <td class="def-prop-val">${pt.units || f.units || 'None (Dimensionless)'}</td>
          </tr>
          <tr>
            <td class="def-prop-key">Scale Factor Reference</td>
            <td class="def-prop-val">${pt.sf || f.scale_factor_point ? `<code>${escapeHtml(pt.sf || f.scale_factor_point)}</code>` : 'None (Unscaled / Direct)'}</td>
          </tr>
          <tr>
            <td class="def-prop-key">Mandatory Register</td>
            <td class="def-prop-val">${pt.mandatory ? 'Yes (M - Required by standard)' : 'No (Optional)'}</td>
          </tr>
          <tr>
            <td class="def-prop-key">Static Definition</td>
            <td class="def-prop-val">${pt.static ? 'Yes (Static / Constant metadata)' : 'No (Dynamic operational metric)'}</td>
          </tr>
          <tr>
            <td class="def-prop-key">Home Assistant Mapping</td>
            <td class="def-prop-val"><code>${escapeHtml(f.ha_platform || 'sensor')}${f.ha_device_class ? ' (' + escapeHtml(f.ha_device_class) + ')' : ''}</code></td>
          </tr>
        </tbody>
      </table>
    </div>
  `;

  el.detailsModalBody.innerHTML = html;

  // Wire up inspect buttons in the modal to seamlessly jump to related registers
  el.detailsModalBody.querySelectorAll('.btn-inspect-reg, .btn-inspect-sf').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const targetKey = btn.dataset.key;
      const targetSerial = btn.dataset.serial || (dev ? dev.serial_number : '');
      if (targetKey) {
        openFieldDetails(targetKey, targetSerial);
      }
    });
  });
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

  // View Mode Segmented Toggle
  if (el.viewModeToggle) {
    el.viewModeToggle.querySelectorAll('.view-mode-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        el.viewModeToggle.querySelectorAll('.view-mode-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        state.viewMode = btn.dataset.mode;
        if (el.viewModeBadge) {
          el.viewModeBadge.textContent = state.viewMode === 'unified' ? '✨ Semantic Deduplication Active' : '📋 All Registers Active';
        }
        if (el.thModelContent) {
          el.thModelContent.innerHTML = state.viewMode === 'unified'
            ? 'Sources<span class="sort-indicator"></span>'
            : 'Model<span class="sort-indicator"></span>';
        }
        if (el.activeDeviceFieldCount) {
          el.activeDeviceFieldCount.textContent = state.viewMode === 'unified'
            ? state.unifiedFields.length
            : state.activeFields.length;
        }
        updateFilterCounts();
        renderFieldTable();
      });
    });
  }

  // Reset Pinned Sources Button
  if (el.btnResetPins) {
    el.btnResetPins.addEventListener('click', () => {
      state.preferredSources = {};
      (state.unifiedFields || []).forEach(g => {
        g.preferred_source_key = null;
        (g.sources || []).forEach(s => { s.is_pinned = false; });
      });
      showToast('Reset all pins; using automatic minimal model solver');
      updateOptimizationPlan();
    });
  }

  // Optimization Banner Collapse / Expand Toggle
  const btnToggleBanner = document.getElementById('btnToggleBanner');
  const optBannerBody = document.getElementById('optBannerBody');
  if (btnToggleBanner && optBannerBody) {
    btnToggleBanner.addEventListener('click', (e) => {
      e.stopPropagation();
      state.bannerCollapsed = !state.bannerCollapsed;
      optBannerBody.style.display = state.bannerCollapsed ? 'none' : 'flex';
      btnToggleBanner.textContent = state.bannerCollapsed ? '＋' : '−';
      btnToggleBanner.title = state.bannerCollapsed ? 'Expand Polling Plan' : 'Minimize Polling Plan';
      if (el.optimizationBanner) {
        el.optimizationBanner.classList.toggle('collapsed', state.bannerCollapsed);
      }
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

  // Details Modal
  if (el.btnCloseDetailsModal) {
    el.btnCloseDetailsModal.addEventListener('click', closeFieldDetails);
  }
  if (el.btnCloseDetailsFooter) {
    el.btnCloseDetailsFooter.addEventListener('click', closeFieldDetails);
  }
  if (el.modbusDetailsModal) {
    el.modbusDetailsModal.addEventListener('click', (e) => {
      if (e.target === el.modbusDetailsModal) closeFieldDetails();
    });
  }
  if (el.btnCopyDetailsJson) {
    el.btnCopyDetailsJson.addEventListener('click', () => {
      if (currentDetailsData) {
        copyToClipboard(JSON.stringify(currentDetailsData, null, 2));
        showToast('Copied Modbus register details JSON to clipboard!');
      }
    });
  }
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      closeFieldDetails();
    }
  });
  document.addEventListener('click', () => {
    document.querySelectorAll('.action-dropdown-menu.show').forEach(m => m.classList.remove('show'));
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

    // Tab buttons
    const bindTab = (btn, tabName) => {
      if (btn) {
        btn.addEventListener('click', () => {
          compareState.activeTab = tabName;
          updateCompareTabActiveStyles();
          if (compareState.data) {
            const rows = Array.isArray(compareState.data) ? compareState.data : (compareState.data.comparisons || []);
            renderCompareTableRows(rows);
          }
        });
      }
    };
    bindTab(el.tabCmpDiscrepancies, 'discrepancies');
    bindTab(el.tabCmpMulti, 'multisource');
    bindTab(el.tabCmpMatches, 'matches');
    bindTab(el.tabCmpAll, 'all');

    // Device selector
    if (el.cmpDeviceSelect) {
      el.cmpDeviceSelect.addEventListener('change', (e) => {
        compareState.selectedDevice = e.target.value;
        if (compareState.data) {
          const rows = Array.isArray(compareState.data) ? compareState.data : (compareState.data.comparisons || []);
          renderCompareTableRows(rows);
        }
      });
    }

    // Search input
    if (el.cmpSearchInput) {
      el.cmpSearchInput.addEventListener('input', (e) => {
        compareState.searchQuery = e.target.value;
        if (compareState.data) {
          const rows = Array.isArray(compareState.data) ? compareState.data : (compareState.data.comparisons || []);
          renderCompareTableRows(rows);
        }
      });
    }
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

// Grouped Registers & Telemetry Compare Modal
let compareTimer = null;
const compareState = {
  activeTab: 'discrepancies',
  selectedDevice: '',
  searchQuery: '',
  data: null,
  hasInitializedTab: false,
};

async function fetchAndRenderCompare() {
  try {
    const res = await fetch(apiPath('api/compare'));
    const data = await res.json();
    compareState.data = data;
    const rows = Array.isArray(data) ? data : (data.comparisons || []);
    const stats = (!Array.isArray(data) && data.stats) ? data.stats : {};
    const unrec = (!Array.isArray(data) && data.unrecognized_proto_fields) ? data.unrecognized_proto_fields : [];

    // Calculate or update stats counts
    const discrepantCount = stats.discrepancies_count !== undefined
      ? stats.discrepancies_count
      : rows.filter(r => r.is_discrepant || ['DIVERGENT', 'UNIT_MISMATCH', 'POLARITY_MISMATCH', 'SCALE_MISMATCH'].includes(r.status)).length;

    const multiCount = stats.multi_source_groups !== undefined
      ? stats.multi_source_groups
      : rows.filter(r => (r.sources && r.sources.length > 1) || r.source_count > 1).length;

    const matchCount = (stats.exact_match_count !== undefined && stats.close_match_count !== undefined)
      ? (stats.exact_match_count + stats.close_match_count)
      : rows.filter(r => ['EXACT', 'CLOSE'].includes(r.status)).length;

    const allCount = stats.total_groups !== undefined ? stats.total_groups : rows.length;

    if (el.cntCmpDiscrepancies) el.cntCmpDiscrepancies.textContent = discrepantCount;
    if (el.cntCmpMulti) el.cntCmpMulti.textContent = multiCount;
    if (el.cntCmpMatches) el.cntCmpMatches.textContent = matchCount;
    if (el.cntCmpAll) el.cntCmpAll.textContent = allCount;

    // Default to 'discrepancies' tab if discrepancies exist on first load, otherwise 'multisource'
    if (!compareState.hasInitializedTab) {
      if (discrepantCount > 0) {
        compareState.activeTab = 'discrepancies';
      } else if (multiCount > 0) {
        compareState.activeTab = 'multisource';
      } else {
        compareState.activeTab = 'all';
      }
      compareState.hasInitializedTab = true;
      updateCompareTabActiveStyles();
    }

    // Populate device dropdown if empty
    if (el.cmpDeviceSelect) {
      const currentVal = el.cmpDeviceSelect.value || compareState.selectedDevice;
      const devicesMap = new Map();
      rows.forEach(r => {
        if (r.device_sn) {
          const label = r.device_name || `${r.device_type} (${r.device_sn.slice(-4)})`;
          devicesMap.set(r.device_sn, label);
        }
      });
      if (devicesMap.size > 0 && el.cmpDeviceSelect.options.length <= 1) {
        el.cmpDeviceSelect.innerHTML = '<option value="">All Devices</option>';
        devicesMap.forEach((label, sn) => {
          const opt = document.createElement('option');
          opt.value = sn;
          opt.textContent = label;
          if (sn === currentVal) opt.selected = true;
          el.cmpDeviceSelect.appendChild(opt);
        });
      }
    }

    renderCompareTableRows(rows);

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
    if (el.compareTableBody) {
      el.compareTableBody.innerHTML = `<tr><td colspan="3" class="empty-state">Error fetching comparisons: ${err}</td></tr>`;
    }
  }
}

function updateCompareTabActiveStyles() {
  const tabs = [
    { btn: el.tabCmpDiscrepancies, name: 'discrepancies' },
    { btn: el.tabCmpMulti, name: 'multisource' },
    { btn: el.tabCmpMatches, name: 'matches' },
    { btn: el.tabCmpAll, name: 'all' },
  ];
  tabs.forEach(t => {
    if (t.btn) {
      if (t.name === compareState.activeTab) t.btn.classList.add('active');
      else t.btn.classList.remove('active');
    }
  });
}

function renderCompareTableRows(rows) {
  if (!el.compareTableBody) return;

  const tab = compareState.activeTab;
  const devFilter = compareState.selectedDevice.trim().toUpperCase();
  const query = compareState.searchQuery.trim().toLowerCase();

  const filtered = rows.filter(r => {
    // 1. Tab filter
    if (tab === 'discrepancies') {
      const isDisc = r.is_discrepant || ['DIVERGENT', 'UNIT_MISMATCH', 'POLARITY_MISMATCH', 'SCALE_MISMATCH'].includes(r.status);
      if (!isDisc) return false;
    } else if (tab === 'multisource') {
      const isMulti = (r.sources && r.sources.length > 1) || r.source_count > 1;
      if (!isMulti) return false;
    } else if (tab === 'matches') {
      if (!['EXACT', 'CLOSE'].includes(r.status)) return false;
    }

    // 2. Device filter
    if (devFilter) {
      const rowSn = (r.device_sn || '').toUpperCase();
      const rowDev = (r.device_type || '').toUpperCase();
      if (rowSn !== devFilter && rowDev !== devFilter) return false;
    }

    // 3. Search query filter
    if (query) {
      const matchLabel = (r.label || '').toLowerCase().includes(query);
      const matchKey = (r.concept_key || r.mapping_id || '').toLowerCase().includes(query);
      const matchDevice = (r.device_name || r.device_type || '').toLowerCase().includes(query);
      const matchSource = (r.sources || []).some(s =>
        (s.field_key || '').toLowerCase().includes(query) ||
        (s.name || '').toLowerCase().includes(query) ||
        (s.label || '').toLowerCase().includes(query)
      );
      if (!matchLabel && !matchKey && !matchDevice && !matchSource) return false;
    }

    return true;
  });

  if (filtered.length === 0) {
    let emptyMsg = 'No comparisons found matching filters';
    if (tab === 'discrepancies') {
      emptyMsg = '🎉 No register grouping discrepancies detected! All grouped registers agree.';
    }
    el.compareTableBody.innerHTML = `<tr><td colspan="3" class="empty-state">${emptyMsg}</td></tr>`;
    return;
  }

  el.compareTableBody.innerHTML = '';
  filtered.forEach(r => {
    const tr = document.createElement('tr');

    // Status Badge
    let statusClass = 'missing';
    let statusText = r.status_label || r.status || 'UNKNOWN';
    const st = (r.status || '').toLowerCase();

    if (st === 'exact') statusClass = 'exact';
    else if (st === 'close') statusClass = 'close';
    else if (st === 'divergent') statusClass = 'divergent';
    else if (st === 'unit_mismatch') statusClass = 'unit_mismatch';
    else if (st === 'polarity_mismatch') statusClass = 'polarity_mismatch';
    else if (st === 'scale_mismatch') statusClass = 'scale_mismatch';
    else if (st === 'partially_polled') statusClass = 'partially_polled';
    else if (st === 'single_source') statusClass = 'single_source';

    const statusBadge = `<span class="status-badge ${statusClass}">${escapeHtml(statusText)}</span>`;

    // Agreement & Discrepancy column content
    let agreementHtml = `<div class="compare-status-wrap">${statusBadge}</div>`;
    if (r.is_discrepant && r.discrepancy_reason) {
      agreementHtml += `<div class="compare-discrepancy-note">⚠️ ${escapeHtml(r.discrepancy_reason)}</div>`;
    }
    if (r.delta !== null && r.delta !== undefined && (r.sources && r.sources.length > 1)) {
      const deltaFormatted = formatFieldValue(r.delta);
      const pctFormatted = r.match_pct !== null && r.match_pct !== undefined ? `${r.match_pct}% match` : '';
      agreementHtml += `<div class="compare-delta-note">Δ ${deltaFormatted} ${escapeHtml(r.unit || '')} ${pctFormatted ? `(${pctFormatted})` : ''}</div>`;
    }

    // Device & Concept column content
    const devBadge = r.device_name ? `<span class="compare-device-pill">${escapeHtml(r.device_name)}</span>` : '';
    const conceptCol = `
      <div class="field-cell-main">
        ${devBadge}
        <strong>${escapeHtml(r.label || r.concept_key)}</strong>
        <span class="field-key">${escapeHtml(r.concept_key || r.mapping_id || '')}</span>
      </div>
    `;

    // Sources column content
    let sourcesCol = '';
    const sources = r.sources || [];
    if (sources.length > 0) {
      const cardsHtml = sources.map(s => {
        const isDivergent = s.is_divergent || false;
        const srcChipClass = s.source_type === 'MQTT' ? 'src-mqtt' : 'src-sunspec';
        const valDisplay = s.value !== null && s.value !== undefined
          ? `${formatFieldValue(s.value)} ${escapeHtml(s.units || r.unit || '')}`
          : '<span class="text-muted">--</span>';

        const rawDisplay = (s.raw_value !== null && s.raw_value !== undefined && s.raw_value !== s.value)
          ? `<span class="compare-source-raw" title="Raw unscaled value">raw: ${formatFieldValue(s.raw_value)}</span>`
          : '';

        const tfDisplay = s.transform
          ? `<span class="compare-source-tag transform" title="Transform: ${escapeHtml(s.transform)}">⚙ ${escapeHtml(s.transform)}</span>`
          : '';

        const optDisplay = s.is_optimal
          ? `<span class="compare-source-tag optimal" title="Selected optimal source">★ Optimal</span>`
          : '';

        const pinDisplay = s.is_pinned
          ? `<span class="compare-source-tag pinned" title="Manually pinned by user">📌 Pinned</span>`
          : '';

        return `
          <div class="compare-source-card ${isDivergent ? 'is-divergent' : ''}">
            <div class="compare-source-left">
              <span class="source-chip ${srcChipClass}">${escapeHtml(s.source_id || 'SRC')}</span>
              <div class="compare-source-meta">
                <span class="compare-source-name">${escapeHtml(s.label || s.name || '')}</span>
                <span class="compare-source-key">${escapeHtml(s.field_key || '')}</span>
              </div>
            </div>
            <div class="compare-source-right">
              <span class="compare-source-value ${isDivergent ? 'val-divergent' : ''}">${valDisplay}</span>
              ${rawDisplay}
              ${tfDisplay}
              ${optDisplay}
              ${pinDisplay}
            </div>
          </div>
        `;
      }).join('');

      sourcesCol = `<div class="compare-sources-list">${cardsHtml}</div>`;
    } else {
      // Legacy fallback row
      const mqttDisplay = r.mqtt_value !== null && r.mqtt_value !== undefined
        ? `${formatFieldValue(r.mqtt_value)} ${escapeHtml(r.unit || '')}`
        : '<span class="text-muted">--</span>';
      const mbDisplay = r.modbus_value !== null && r.modbus_value !== undefined
        ? `${formatFieldValue(r.modbus_value)} ${escapeHtml(r.unit || '')}`
        : '<span class="text-muted">--</span>';

      sourcesCol = `
        <div class="compare-sources-list">
          <div class="compare-source-card">
            <div class="compare-source-left">
              <span class="source-chip src-mqtt">MQTT</span>
              <div class="compare-source-meta">
                <span class="compare-source-key">${escapeHtml(r.mqtt_key || 'MQTT Push')}</span>
              </div>
            </div>
            <div class="compare-source-right">
              <span class="compare-source-value">${mqttDisplay}</span>
            </div>
          </div>
          <div class="compare-source-card">
            <div class="compare-source-left">
              <span class="source-chip src-sunspec">MODBUS</span>
              <div class="compare-source-meta">
                <span class="compare-source-name">${escapeHtml(r.modbus_label || '')}</span>
                <span class="compare-source-key">${escapeHtml(r.modbus_key || '')}</span>
              </div>
            </div>
            <div class="compare-source-right">
              <span class="compare-source-value">${mbDisplay}</span>
            </div>
          </div>
        </div>
      `;
    }

    tr.innerHTML = `
      <td>${conceptCol}</td>
      <td>${agreementHtml}</td>
      <td>${sourcesCol}</td>
    `;
    el.compareTableBody.appendChild(tr);
  });
}

function openCompareModal() {
  el.compareModal.classList.add('open');
  compareState.hasInitializedTab = false;
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

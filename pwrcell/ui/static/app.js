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
  haCategoryOverrides: {}, // { '<SN>:<KEY>': 'primary' | 'diagnostic' }
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
  showPlanDetails: false,
  showAllPlanFields: false,
  groupingModalData: null,
  boundsModalField: null,
  expandedGroups: new Set(),
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
  btnTogglePlanDetails: document.getElementById('btnTogglePlanDetails'),
  optPlanBreakdown: document.getElementById('optPlanBreakdown'),
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
  btnCleanHA: document.getElementById('btnCleanHA'),
  btnResetHA: document.getElementById('btnResetHA'),
  btnSaveHA: document.getElementById('btnSaveHA'),
  btnResetAllGroupings: document.getElementById('btnResetAllGroupings'),
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
  btnOpenSuggestions: document.getElementById('btnOpenSuggestions'),
  cntHeaderSuggestions: document.getElementById('cntHeaderSuggestions'),
  btnSyncModbus: document.getElementById('btnSyncModbus'),
  compareModal: document.getElementById('compareModal'),
  btnCloseCompare: document.getElementById('btnCloseCompare'),
  btnCloseCompareFooter: document.getElementById('btnCloseCompareFooter'),
  compareTableContainer: document.getElementById('compareTableContainer'),
  compareTableBody: document.getElementById('compareTableBody'),
  compareSuggestionsContainer: document.getElementById('compareSuggestionsContainer'),
  suggestionsList: document.getElementById('suggestionsList'),
  suggestionsToolbar: document.getElementById('suggestionsToolbar'),
  cmpSuggestionsConfidence: document.getElementById('cmpSuggestionsConfidence'),
  btnRefreshSuggestions: document.getElementById('btnRefreshSuggestions'),
  btnBatchApproveVisible: document.getElementById('btnBatchApproveVisible'),
  btnBatchDismissVisible: document.getElementById('btnBatchDismissVisible'),
  cntBatchApprove: document.getElementById('cntBatchApprove'),
  tabCmpDiscrepancies: document.getElementById('tabCmpDiscrepancies'),
  tabCmpSuggestions: document.getElementById('tabCmpSuggestions'),
  tabCmpMulti: document.getElementById('tabCmpMulti'),
  tabCmpMatches: document.getElementById('tabCmpMatches'),
  tabCmpAll: document.getElementById('tabCmpAll'),
  cntCmpDiscrepancies: document.getElementById('cntCmpDiscrepancies'),
  cntCmpSuggestions: document.getElementById('cntCmpSuggestions'),
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
  groupingModal: document.getElementById('groupingModal'),
  btnCloseGroupingModal: document.getElementById('btnCloseGroupingModal'),
  btnCancelGroupingModal: document.getElementById('btnCancelGroupingModal'),
  btnSaveGroupingModal: document.getElementById('btnSaveGroupingModal'),
  btnResetGroupingModal: document.getElementById('btnResetGroupingModal'),
  groupingFieldKeyBadge: document.getElementById('groupingFieldKeyBadge'),
  groupingDeviceLabel: document.getElementById('groupingDeviceLabel'),
  groupingCurrentConceptLabel: document.getElementById('groupingCurrentConceptLabel'),
  groupingTargetConceptSelect: document.getElementById('groupingTargetConceptSelect'),
  groupingNewConceptKey: document.getElementById('groupingNewConceptKey'),
  groupingNewConceptLabel: document.getElementById('groupingNewConceptLabel'),
  radioGroupExisting: document.getElementById('radioGroupExisting'),
  radioGroupNew: document.getElementById('radioGroupNew'),
  radioGroupUngroup: document.getElementById('radioGroupUngroup'),
  radioTransformNone: document.getElementById('radioTransformNone'),
  radioTransformNegate: document.getElementById('radioTransformNegate'),
  polarityModal: document.getElementById('polarityModal'),
  btnClosePolarityModal: document.getElementById('btnClosePolarityModal'),
  btnCancelPolarityModal: document.getElementById('btnCancelPolarityModal'),
  btnPolarityPositive: document.getElementById('btnPolarityPositive'),
  btnPolarityNegative: document.getElementById('btnPolarityNegative'),
  btnPolarityDirect: document.getElementById('btnPolarityDirect'),
  polarityModalDesc: document.getElementById('polarityModalDesc'),
  polarityPositiveLabel: document.getElementById('polarityPositiveLabel'),
  polarityNegativeLabel: document.getElementById('polarityNegativeLabel'),
  polarityPositiveDesc: document.getElementById('polarityPositiveDesc'),
  polarityNegativeDesc: document.getElementById('polarityNegativeDesc'),
  boundsModal: document.getElementById('boundsModal'),
  boundsModalTitle: document.getElementById('boundsModalTitle'),
  boundsFieldKeyBadge: document.getElementById('boundsFieldKeyBadge'),
  boundsFieldName: document.getElementById('boundsFieldName'),
  boundsDefaultLimits: document.getElementById('boundsDefaultLimits'),
  boundsCurrentStatus: document.getElementById('boundsCurrentStatus'),
  boundsMinInput: document.getElementById('boundsMinInput'),
  boundsMaxInput: document.getElementById('boundsMaxInput'),
  boundsStepInput: document.getElementById('boundsStepInput'),
  boundsApplyAll: document.getElementById('boundsApplyAll'),
  btnCloseBoundsModal: document.getElementById('btnCloseBoundsModal'),
  btnCancelBoundsModal: document.getElementById('btnCancelBoundsModal'),
  btnSaveBoundsModal: document.getElementById('btnSaveBoundsModal'),
  btnResetBoundsModal: document.getElementById('btnResetBoundsModal'),
  btnOpenExportMappings: document.getElementById('btnOpenExportMappings'),
  exportMappingsModal: document.getElementById('exportMappingsModal'),
  btnCloseExportModal: document.getElementById('btnCloseExportModal'),
  btnCloseExportFooter: document.getElementById('btnCloseExportFooter'),
  btnFormatGeneralized: document.getElementById('btnFormatGeneralized'),
  btnFormatTelemetry: document.getElementById('btnFormatTelemetry'),
  exportTargetFilename: document.getElementById('exportTargetFilename'),
  exportTargetLocation: document.getElementById('exportTargetLocation'),
  exportYamlCode: document.getElementById('exportYamlCode'),
  btnCopyExportYaml: document.getElementById('btnCopyExportYaml'),
  btnDownloadExportYaml: document.getElementById('btnDownloadExportYaml'),
  btnApplyCleanSlate: document.getElementById('btnApplyCleanSlate'),
  toast: document.getElementById('toast'),
  counts: {
    all: document.getElementById('countAll'),
    compound: document.getElementById('countCompound'),
    selected: document.getElementById('countSelected'),
    sensor: document.getElementById('countSensors'),
    writable: document.getElementById('countWritable'),
    primary: document.getElementById('countPrimary'),
    diagnostic: document.getElementById('countDiagnostic'),
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
    fetchGroupingSuggestions(),
  ]);
  await fetchDevices();
  connectSSE();
}

// Fetch Grouping Suggestions
async function fetchGroupingSuggestions() {
  try {
    const res = await fetch(apiPath('api/grouping/suggestions'));
    const data = await res.json();
    compareState.suggestions = data.suggestions || [];
    const count = data.count !== undefined ? data.count : compareState.suggestions.length;
    if (el.cntHeaderSuggestions) el.cntHeaderSuggestions.textContent = count;
    if (el.cntCmpSuggestions) el.cntCmpSuggestions.textContent = count;
    if (el.btnOpenSuggestions) {
      el.btnOpenSuggestions.style.display = count > 0 ? 'inline-flex' : 'none';
    }
    if (compareState.activeTab === 'suggestions') {
      renderCompareSuggestions(compareState.suggestions);
    }
  } catch (err) {
    console.warn('Failed fetching grouping suggestions:', err);
  }
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
    state.haCategoryOverrides = data.category_overrides || {};
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

// Check if a field is classified as a Home Assistant Diagnostic entity
function isFieldDiagnostic(f) {
  if (!f) return false;
  const sn = getFieldDeviceSn(f);
  const overrides = state.haCategoryOverrides || {};

  const checkOverride = (k) => {
    if (!k) return null;
    if (sn && overrides[`${sn}:${k}`]) return String(overrides[`${sn}:${k}`]).toLowerCase();
    if (overrides[k]) return String(overrides[k]).toLowerCase();
    return null;
  };

  const o = checkOverride(f.id) || checkOverride(f.key) || checkOverride(f.concept_key) || checkOverride(f.active_source_key) || checkOverride(f.mqtt_key);
  if (o) {
    return o === 'diagnostic';
  }
  return f.ha_category === 'diagnostic' || f.is_diagnostic === true;
}

// Check if a field has a user category override
function hasCategoryOverride(f) {
  if (!f || !state.haCategoryOverrides) return false;
  const sn = getFieldDeviceSn(f);
  const overrides = state.haCategoryOverrides;

  const checkOverride = (k) => {
    if (!k) return false;
    if (sn && overrides[`${sn}:${k}`]) return true;
    return !!overrides[k];
  };

  return checkOverride(f.id) || checkOverride(f.key) || checkOverride(f.concept_key) || checkOverride(f.active_source_key) || checkOverride(f.mqtt_key);
}

// Render HTML badge button for toggling entity category in table
function renderCatToggleHtml(f) {
  const isDiag = isFieldDiagnostic(f);
  const isOverride = hasCategoryOverride(f);
  const isSelected = isFieldSelected(f);
  const catLabel = isDiag ? 'Diagnostic' : 'Primary';
  const catIcon = isDiag ? '🏷️' : '⚡';
  const overrideMarker = isOverride ? ' <span class="cat-override-indicator" title="Custom user override">*</span>' : '';
  const keyToUse = f.id || f.key || f.concept_key || '';
  const snToUse = getFieldDeviceSn(f);

  return `
    <button type="button" class="badge-cat-toggle ${isDiag ? 'is-diagnostic' : 'is-primary'} ${isOverride ? 'has-override' : ''} ${!isSelected ? 'is-dimmed' : ''}"
            data-key="${escapeHtml(keyToUse)}"
            data-sn="${escapeHtml(snToUse)}"
            title="Home Assistant Category: ${catLabel}${isOverride ? ' (User Override)' : ' (Default)'}\nClick to toggle category (${isDiag ? 'Switch to Primary' : 'Switch to Diagnostic'})${!isSelected ? '\n(Field is currently not selected for HA export)' : ''}">
      <span class="cat-icon">${catIcon}</span>
      <span class="cat-text">${catLabel}</span>${overrideMarker}
    </button>
  `;
}

// Action to toggle or reset entity category override
async function toggleFieldCategoryAction(deviceSn, fieldKey, targetCategory, label) {
  try {
    const sn = (deviceSn || state.activeDevice?.serial_number || '').trim().toUpperCase();
    const cleanKey = (fieldKey || '').trim();
    if (!cleanKey) return;

    // Optimistic in-memory update
    const qualKey = sn ? `${sn}:${cleanKey}` : cleanKey;
    if (!state.haCategoryOverrides) state.haCategoryOverrides = {};

    if (targetCategory === 'reset' || !targetCategory) {
      delete state.haCategoryOverrides[qualKey];
      delete state.haCategoryOverrides[cleanKey];
    } else {
      state.haCategoryOverrides[qualKey] = targetCategory;
    }

    renderFieldTable();
    updateFilterCounts();

    const res = await fetch(apiPath('api/ha/category_override'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        device_serial: sn,
        field_key: cleanKey,
        category: targetCategory === 'reset' ? 'reset' : targetCategory,
      }),
    });

    const data = await res.json();
    if (!res.ok || data.error) {
      throw new Error(data.error || 'Failed updating category');
    }

    if (data.category_overrides) {
      state.haCategoryOverrides = data.category_overrides;
    }

    const catName = targetCategory === 'diagnostic' ? 'Diagnostic' : (targetCategory === 'reset' ? 'Default' : 'Primary sensor');
    showToast(`${label || cleanKey} set to ${catName} in Home Assistant`);
    renderFieldTable();
    updateFilterCounts();
  } catch (err) {
    console.error('Failed toggling HA category:', err);
    showToast(`Error: ${err.message}`, 'error');
    await fetchHaConfig();
  }
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
  const isDiag = isFieldDiagnostic(f);
  return `${f.ha_platform || ''} ${isDiag ? 'diagnostic' : 'primary'} ${f.ha_device_class || ''}`.trim().toLowerCase();
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
  const customTag = b.is_custom ? ' <span class="badge-custom-bounds" title="Custom limits active">CUSTOM</span>' : '';
  return `
    <div class="field-bounds-line">
      <span class="field-bounds-badge${b.is_custom ? ' is-custom' : ''}" title="${b.is_custom ? 'Custom Bounds: ' : 'SunSpec Bounds: '}${escapeHtml(fullDesc)}">
        <span class="bounds-icon">📏</span>
        <span class="bounds-text">${escapeHtml(text)}</span>
      </span>
      ${customTag}
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
          const activeBadges = minModels.map(m => `<span class="badge-opt-active" data-model="${m}" style="cursor: pointer;" title="Model ${m} selected for active Modbus polling - click to view fields">M${m} (Polled)</span>`).join(' ');
          const mqttBadge = stats.mqtt_covered_count ? `<span class="badge-opt-mqtt" data-source="mqtt" style="cursor: pointer;" title="${stats.mqtt_covered_count} points provided via Push MQTT - click to view fields">⚡ ${stats.mqtt_covered_count} Push MQTT</span>` : '';
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

          // Badge click shortcuts to jump into detailed breakdown
          el.optModelsBadges.querySelectorAll('.badge-opt-active, .badge-opt-mqtt').forEach(badge => {
            badge.addEventListener('click', (e) => {
              e.stopPropagation();
              state.showPlanDetails = true;
              renderPlanBreakdown(data);
              const mId = badge.dataset.model;
              const targetCardId = mId ? `planCardM${mId}` : 'planCardMqtt';
              const targetCard = document.getElementById(targetCardId);
              if (targetCard) {
                targetCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
              }
            });
          });
        }

        if (el.btnResetPins) {
          el.btnResetPins.style.display = Object.keys(state.preferredSources).length > 0 ? 'inline-block' : 'none';
        }

        renderPlanBreakdown(data);
      } else {
        el.optimizationBanner.style.display = 'none';
        if (el.optPlanBreakdown) el.optPlanBreakdown.style.display = 'none';
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

// Render Detailed Polling Plan Breakdown by Source
function renderPlanBreakdown(data) {
  if (!el.optPlanBreakdown) return;

  if (!state.showPlanDetails) {
    el.optPlanBreakdown.style.display = 'none';
    if (el.btnTogglePlanDetails) {
      el.btnTogglePlanDetails.classList.remove('active');
      el.btnTogglePlanDetails.textContent = '📋 Fields by Source ▾';
    }
    return;
  }

  el.optPlanBreakdown.style.display = 'flex';
  if (el.btnTogglePlanDetails) {
    el.btnTogglePlanDetails.classList.add('active');
    el.btnTogglePlanDetails.textContent = '📋 Hide Breakdown ▴';
  }

  const planData = data || state.optimizationPlan || {};
  const minModels = planData.minimal_models || [];
  const avoidedModels = planData.models_avoided || [];
  const assignments = planData.assignments || {};
  const groups = planData.unified_fields || state.unifiedFields || [];
  const rawFields = state.activeFields || [];

  const mqttItems = [];
  const modelItems = {};
  minModels.forEach(mId => {
    modelItems[mId] = [];
  });

  // Track items already added to prevent duplicates
  const processedKeys = new Set();

  // 1. Process Unified Groups
  groups.forEach(g => {
    const isSelected = isFieldSelected(g) || g.is_selected || (assignments[g.id] !== undefined);
    if (!state.showAllPlanFields && !isSelected) return;

    const prefKey = state.preferredSources[g.id] || g.preferred_source_key;
    let activeSrc = null;

    if (prefKey && g.sources) {
      activeSrc = g.sources.find(s => s.field_key === prefKey);
    }
    if (!activeSrc && assignments[g.id] !== undefined && g.sources) {
      const assigned = assignments[g.id];
      if (assigned === 'MQTT') {
        activeSrc = g.sources.find(s => s.source_type === 'MQTT');
      } else {
        activeSrc = g.sources.find(s => s.model_id === assigned);
      }
    }
    if (!activeSrc && g.active_source_key && g.sources) {
      activeSrc = g.sources.find(s => s.field_key === g.active_source_key);
    }
    if (!activeSrc && g.sources && g.sources.length > 0) {
      activeSrc = g.sources.find(s => s.is_optimal) || g.sources[0];
    }

    const isMqtt = (assignments[g.id] === 'MQTT') || (activeSrc && activeSrc.source_type === 'MQTT');
    const modelId = (!isMqtt && activeSrc && activeSrc.model_id)
      ? activeSrc.model_id
      : (typeof assignments[g.id] === 'number' ? assignments[g.id] : null);

    const val = (activeSrc && activeSrc.value !== undefined) ? activeSrc.value : g.latest_value;
    const entry = {
      id: g.id,
      rowId: `row-${sanitizeId(g.id)}`,
      label: g.label || g.name || g.id,
      fieldKey: (activeSrc && activeSrc.field_key) || g.id,
      sourceId: (activeSrc && activeSrc.source_id) || (isMqtt ? 'MQTT' : (modelId ? `M${modelId}` : '')),
      value: val,
      lastUpdated: (activeSrc && activeSrc.last_updated) || g.latest_updated || g.last_updated,
      rawItem: g,
      isPinned: (activeSrc && activeSrc.is_pinned) || (prefKey !== undefined && prefKey !== null)
    };

    processedKeys.add(g.id);
    if (activeSrc && activeSrc.field_key) processedKeys.add(activeSrc.field_key);

    if (isMqtt) {
      mqttItems.push(entry);
    } else if (modelId && minModels.includes(modelId)) {
      if (!modelItems[modelId]) modelItems[modelId] = [];
      modelItems[modelId].push(entry);
    }
  });

  // 2. Process Raw Fields (if not already represented in a unified group)
  rawFields.forEach(f => {
    if (processedKeys.has(f.key)) return;
    if (groups.some(g => (g.sources || []).some(s => s.field_key === f.key))) return;

    const isSelected = isFieldSelected(f) || (assignments[f.key] !== undefined);
    if (!state.showAllPlanFields && !isSelected) return;

    const isMqtt = f.is_mqtt || f.key?.startsWith('mqtt.') || f.source_type === 'MQTT';
    const modelId = f.model_id;
    const entry = {
      id: f.key,
      rowId: `row-${sanitizeId(f.key)}`,
      label: f.label || f.name || f.key,
      fieldKey: f.key,
      sourceId: isMqtt ? 'MQTT' : (modelId ? `M${modelId}` : ''),
      value: f.value,
      lastUpdated: f.last_updated || f.timestamp,
      rawItem: f,
      isPinned: false
    };

    if (isMqtt) {
      mqttItems.push(entry);
    } else if (modelId && minModels.includes(modelId)) {
      if (!modelItems[modelId]) modelItems[modelId] = [];
      modelItems[modelId].push(entry);
    }
  });

  const totalPoints = mqttItems.length + Object.values(modelItems).reduce((sum, list) => sum + list.length, 0);

  // Helper to render individual field items
  const renderItemHtml = (item) => {
    const formattedVal = formatFieldValue(item.value, item.rawItem);
    const tsStr = formatTimestamp(item.lastUpdated);
    const tsHtml = tsStr ? `<span class="opt-field-time" title="Read at ${tsStr}">🕒 ${tsStr}</span>` : '';
    return `
      <div class="opt-field-item" data-row-id="${escapeHtml(item.rowId)}" title="Click to jump to this field in the table">
        <div class="opt-field-info">
          <span class="opt-field-name">${escapeHtml(item.label)}</span>
          <span class="opt-field-path">${escapeHtml(item.fieldKey)}</span>
        </div>
        <div class="opt-field-meta">
          <span class="opt-field-val">${formattedVal}</span>
          ${tsHtml}
          ${item.isPinned ? '<span class="opt-pin-icon" title="Pinned preferred data source">📌</span>' : ''}
        </div>
      </div>
    `;
  };

  // Build Grid Cards
  let cardsHtml = '';

  // MQTT Card
  if (mqttItems.length > 0 || planData.stats?.mqtt_covered_count > 0) {
    cardsHtml += `
      <div class="opt-source-card mqtt" id="planCardMqtt">
        <div class="opt-source-card-header">
          <div class="opt-source-badge-wrap">
            <span class="badge-opt-mqtt">⚡ Push MQTT</span>
            <span class="opt-source-count">${mqttItems.length} field${mqttItems.length === 1 ? '' : 's'}</span>
          </div>
          <div class="opt-source-title">Push Telemetry</div>
          <div class="opt-source-desc">Streaming live via broker &bull; 0 Modbus bus latency</div>
        </div>
        <div class="opt-field-list">
          ${mqttItems.length > 0 ? mqttItems.map(renderItemHtml).join('') : '<div class="text-muted" style="font-size: 11px; padding: 4px;">No selected fields assigned to MQTT.</div>'}
        </div>
      </div>
    `;
  }

  // Modbus Model Cards
  minModels.forEach(mId => {
    const mMeta = (state.activeDeviceModels || []).find(m => m.model_id === mId);
    const mName = mMeta ? (mMeta.label || mMeta.name || `Model ${mId}`) : `Model ${mId}`;
    const items = modelItems[mId] || [];

    cardsHtml += `
      <div class="opt-source-card modbus" id="planCardM${mId}">
        <div class="opt-source-card-header">
          <div class="opt-source-badge-wrap">
            <span class="badge-opt-active">M${mId} (Polled)</span>
            <span class="opt-source-count">${items.length} field${items.length === 1 ? '' : 's'}</span>
          </div>
          <div class="opt-source-title">Model ${mId}: ${escapeHtml(mName)}</div>
          <div class="opt-source-desc">Polled cyclically over Modbus RS-485</div>
        </div>
        <div class="opt-field-list">
          ${items.length > 0 ? items.map(renderItemHtml).join('') : '<div class="text-muted" style="font-size: 11px; padding: 4px;">Model active for required block coverage.</div>'}
        </div>
      </div>
    `;
  });

  // Avoided Models Card
  if (avoidedModels.length > 0) {
    cardsHtml += `
      <div class="opt-source-card avoided" id="planCardAvoided">
        <div class="opt-source-card-header">
          <div class="opt-source-badge-wrap">
            <span class="badge-opt-avoided">${avoidedModels.length} Excluded</span>
          </div>
          <div class="opt-source-title">Avoided SunSpec Models</div>
          <div class="opt-source-desc">Redundant models omitted from polling to minimize bus traffic</div>
        </div>
        <div class="opt-avoided-list">
          ${avoidedModels.map(aId => {
            const mMeta = (state.activeDeviceModels || []).find(m => m.model_id === aId);
            const aName = mMeta ? (mMeta.label || mMeta.name || `Model ${aId}`) : `Model ${aId}`;
            return `
              <div class="opt-avoided-item">
                <span class="opt-avoided-name">M${aId}: ${escapeHtml(aName)}</span>
                <span class="opt-avoided-reason">Covered by active plan</span>
              </div>
            `;
          }).join('')}
        </div>
      </div>
    `;
  }

  el.optPlanBreakdown.innerHTML = `
    <div class="opt-plan-summary-bar">
      <span><strong>Polling Plan Breakdown:</strong> ${totalPoints} active point${totalPoints === 1 ? '' : 's'} across ${minModels.length} polled model${minModels.length === 1 ? '' : 's'}${mqttItems.length > 0 ? ' &amp; Push MQTT' : ''}. Click any field to jump to its row.</span>
      <label class="toggle-label" style="font-size: 10px; cursor: pointer;" title="Toggle between showing only actively polled/selected fields vs all points available in these models">
        <input type="checkbox" id="chkShowAllPlanFields" ${state.showAllPlanFields ? 'checked' : ''} />
        Show all model fields
      </label>
    </div>
    <div class="opt-plan-grid">
      ${cardsHtml || '<div class="empty-state" style="padding: 12px; grid-column: 1 / -1;">No active data sources or models found.</div>'}
    </div>
  `;

  // Attach Checkbox Handler
  const chkShowAll = el.optPlanBreakdown.querySelector('#chkShowAllPlanFields');
  if (chkShowAll) {
    chkShowAll.addEventListener('change', (e) => {
      state.showAllPlanFields = e.target.checked;
      renderPlanBreakdown(state.optimizationPlan);
    });
  }

  // Attach Item Click Handlers
  el.optPlanBreakdown.querySelectorAll('.opt-field-item').forEach(itemEl => {
    itemEl.addEventListener('click', () => {
      const rowId = itemEl.dataset.rowId;
      if (!rowId) return;
      const targetRow = document.getElementById(rowId);
      if (targetRow) {
        targetRow.scrollIntoView({ behavior: 'smooth', block: 'center' });
        targetRow.classList.remove('highlight-row-flash');
        void targetRow.offsetWidth;
        targetRow.classList.add('highlight-row-flash');
        setTimeout(() => targetRow.classList.remove('highlight-row-flash'), 1800);
      } else {
        showToast('Field is currently filtered out or on another page');
      }
    });
  });
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
        case 'primary':
          return !isFieldDiagnostic(f);
        case 'diagnostic':
          return isFieldDiagnostic(f);
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
        case 'primary':
          return !isFieldDiagnostic(f);
        case 'diagnostic':
          return isFieldDiagnostic(f);
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
      const sVal = formatFieldValuePlain(s.value, f);
      const sTime = formatTimestamp(s.last_updated);
      const sTimeNote = sTime ? ` (read @ ${sTime})` : '';
      const title = isPinned
        ? `📌 Pinned preferred source: ${s.source_id} (${s.field_key})\nValue: ${sVal}${sTimeNote}\nClick to unpin and use automatic minimal set solver.`
        : (isOptimal
            ? `★ Optimal source: ${s.source_id} (${s.field_key})\nSelected in minimal polling plan.\nValue: ${sVal}${sTimeNote}`
            : (isPolled
                ? `⚡ ${s.source_id} (${s.field_key})\nIncluded in minimal polling plan.\nValue: ${sVal}${sTimeNote}\nClick to pin this source.`
                : `${s.source_id} (${s.field_key})\nExcluded / avoided from Modbus polling.\nValue: ${sVal}${sTimeNote}\nClick to pin this source.`));

      return `<button class="source-pill ${pillClass}" data-group-id="${f.id}" data-field-key="${s.field_key}" data-source-id="${s.source_id}" title="${escapeHtml(title)}">${prefix}${s.source_id}</button>`;
    }).join(' ');

    const countBadge = (f.sources && f.sources.length > 1)
      ? `<span class="badge-source-count" title="${f.sources.length} sources available">${f.sources.length} sources</span>`
      : '';

    const hasChildren = f.sources && f.sources.length > 1;
    const isExpanded = hasChildren && state.expandedGroups && state.expandedGroups.has(f.id);
    const expandBtnHtml = hasChildren
      ? `<button class="btn-group-expand ${isExpanded ? 'is-expanded' : ''}" data-group-id="${escapeHtml(f.id)}" title="${isExpanded ? 'Collapse child sources' : 'Expand contributing child fields'}">${isExpanded ? '▼' : '▶'}</button>`
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
            ${expandBtnHtml}
            <span class="field-label" title="${escapeHtml(f.description || '')}">${f.label}</span>
            ${f.is_writable ? '<span class="badge-writable" title="Settable register (Read/Write)">RW</span>' : ''}
            ${countBadge}
          </div>
          <span class="field-key">${f.concept_key} &bull; <small>${f.id}</small></span>
          ${formatBoundsBadge(f)}
        </div>
      </td>
      <td>
        <div class="value-cell-wrap">
          <span class="field-value-badge latest${isBf ? ' is-bitfield' : ''}" id="val-${sanitizeId(f.id)}">${displayVal}</span>
          ${formatTimestampBadge(f.latest_updated || f.last_updated || (activeSrc && activeSrc.last_updated), `ts-${sanitizeId(f.id)}`)}
        </div>
      </td>
      <td>${f.units || '&mdash;'}</td>
      <td>
        ${activeBadge}
      </td>
      <td>
        <div class="type-cell-wrap">
          <span class="type-tag">${f.ha_platform}${f.ha_device_class ? ': ' + f.ha_device_class : ''}</span>
          ${renderCatToggleHtml(f)}
        </div>
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
              ${(f.is_writable || f.bounds) ? `<button class="action-menu-item item-bounds" data-key="${targetFieldRef.key}">📏 Configure Bounds...</button>` : ''}
              <button class="action-menu-item item-copy" data-key="${targetFieldRef.key}">📄 Copy Key</button>
              <button class="action-menu-item item-toggle-cat" data-key="${targetFieldRef.key}">${isFieldDiagnostic(f) ? '⚡ Set as Primary Sensor' : '🏷️ Set as Diagnostic'}</button>
              ${hasCategoryOverride(f) ? `<button class="action-menu-item item-reset-cat" data-key="${targetFieldRef.key}">↺ Reset Category to Default</button>` : ''}
              ${!isScaleFactorField(f) && !isScaleFactorField(targetFieldRef) ? `
                <button class="action-menu-item item-group-with" data-key="${targetFieldRef.key}">🔗 Group with Concept...</button>
                ${(f.sources && f.sources.length > 1) ? `<button class="action-menu-item item-ungroup" data-key="${targetFieldRef.key}">✂️ Ungroup Field</button>` : ''}
                ${(f.sources && f.sources.length > 1) ? `<button class="action-menu-item item-ungroup-all" data-concept="${f.concept_key}">✂️ Ungroup All Sources</button>` : ''}
                ${f.is_custom_override ? `<button class="action-menu-item item-reset-group" data-key="${targetFieldRef.key}">↩️ Reset Grouping</button>` : ''}
              ` : ''}
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

      const menuBounds = dropdownMenu.querySelector('.item-bounds');
      if (menuBounds) {
        menuBounds.addEventListener('click', (e) => {
          e.stopPropagation();
          dropdownMenu.classList.remove('show');
          openBoundsModal(targetFieldRef || f);
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

      const menuGroupWith = dropdownMenu.querySelector('.item-group-with');
      if (menuGroupWith) {
        menuGroupWith.addEventListener('click', (e) => {
          e.stopPropagation();
          dropdownMenu.classList.remove('show');
          const devSn = f.device_sn || (state.activeDevice ? state.activeDevice.serial_number : '');
          const fKey = targetFieldRef.key || targetFieldRef.field_key || f.active_source_key || (f.sources && f.sources[0] ? f.sources[0].field_key : '');
          openGroupingModal(devSn, fKey, f.concept_key, f.label);
        });
      }

      const menuUngroup = dropdownMenu.querySelector('.item-ungroup');
      if (menuUngroup) {
        menuUngroup.addEventListener('click', async (e) => {
          e.stopPropagation();
          dropdownMenu.classList.remove('show');
          const devSn = f.device_sn || (state.activeDevice ? state.activeDevice.serial_number : '');
          const fKey = targetFieldRef.key || targetFieldRef.field_key || f.active_source_key || (f.sources && f.sources[0] ? f.sources[0].field_key : '');
          await ungroupFieldAction(devSn, fKey);
        });
      }

      const menuUngroupAll = dropdownMenu.querySelector('.item-ungroup-all');
      if (menuUngroupAll) {
        menuUngroupAll.addEventListener('click', async (e) => {
          e.stopPropagation();
          dropdownMenu.classList.remove('show');
          const devSn = f.device_sn || (state.activeDevice ? state.activeDevice.serial_number : '');
          await ungroupAllAction(devSn, f.concept_key);
        });
      }

      const menuResetGroup = dropdownMenu.querySelector('.item-reset-group');
      if (menuResetGroup) {
        menuResetGroup.addEventListener('click', async (e) => {
          e.stopPropagation();
          dropdownMenu.classList.remove('show');
          const devSn = f.device_sn || (state.activeDevice ? state.activeDevice.serial_number : '');
          const fKey = targetFieldRef.key || targetFieldRef.field_key || f.active_source_key || (f.sources && f.sources[0] ? f.sources[0].field_key : '');
          await resetGroupingAction(devSn, fKey);
        });
      }

      const menuToggleCat = dropdownMenu.querySelector('.item-toggle-cat');
      if (menuToggleCat) {
        menuToggleCat.addEventListener('click', async (e) => {
          e.stopPropagation();
          dropdownMenu.classList.remove('show');
          const currentIsDiag = isFieldDiagnostic(f);
          const targetCat = currentIsDiag ? 'primary' : 'diagnostic';
          const sn = getFieldDeviceSn(f);
          const fKey = f.id || f.key || f.concept_key;
          await toggleFieldCategoryAction(sn, fKey, targetCat, f.label || f.name);
        });
      }

      const menuResetCat = dropdownMenu.querySelector('.item-reset-cat');
      if (menuResetCat) {
        menuResetCat.addEventListener('click', async (e) => {
          e.stopPropagation();
          dropdownMenu.classList.remove('show');
          const sn = getFieldDeviceSn(f);
          const fKey = f.id || f.key || f.concept_key;
          await toggleFieldCategoryAction(sn, fKey, 'reset', f.label || f.name);
        });
      }
    }

    const catBtn = tr.querySelector('.badge-cat-toggle');
    if (catBtn) {
      catBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const currentIsDiag = isFieldDiagnostic(f);
        const targetCat = currentIsDiag ? 'primary' : 'diagnostic';
        const sn = getFieldDeviceSn(f);
        const fKey = f.id || f.key || f.concept_key;
        await toggleFieldCategoryAction(sn, fKey, targetCat, f.label || f.name);
      });
    }

    const expandBtn = tr.querySelector('.btn-group-expand');
    if (expandBtn) {
      expandBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        if (state.expandedGroups.has(f.id)) {
          state.expandedGroups.delete(f.id);
        } else {
          state.expandedGroups.add(f.id);
        }
        renderFieldTable();
      });
    }

    let subTr = null;
    if (isExpanded && hasChildren) {
      subTr = document.createElement('tr');
      subTr.className = 'group-children-row';
      subTr.id = `children-${sanitizeId(f.id)}`;

      const childRowsHtml = (f.sources || []).map(s => {
        const isOptimal = s.is_optimal;
        const isPinned = pinnedKey ? (pinnedKey === s.field_key) : false;
        const isMqtt = s.source_type === 'MQTT';
        const isPolled = isMqtt || (s.model_id && minModelsSet.has(s.model_id));

        let roleBadge = '';
        if (s.is_primary) {
          roleBadge = `<span class="badge-source-role primary" title="Active primary source driving Home Assistant">⚡ Primary</span>`;
        } else if (isPolled) {
          roleBadge = `<span class="badge-source-role secondary" title="Polled in minimal model plan; actively cross-checked">★ Polled</span>`;
        } else {
          roleBadge = `<span class="badge-source-role standby" title="Avoided from Modbus polling by optimizer">○ Standby</span>`;
        }

        const sourceLabel = isMqtt ? 'MQTT Push' : (s.model_name ? `${s.model_name} (M${s.model_id})` : `Model ${s.model_id}`);
        const rawValDisplay = formatFieldValue(s.raw_value, f);
        const transValDisplay = formatFieldValue(s.value, f);

        let valDisplayHtml = `<strong>${transValDisplay}</strong>`;
        if (s.transform && s.transform !== 'none') {
          valDisplayHtml = `<span class="raw-val-dim">${rawValDisplay}</span> <span class="arrow-trans">➔</span> <strong>${transValDisplay}</strong> <span class="badge-tf">${s.transform}</span>`;
        }

        return `
          <tr class="child-source-item" data-field-key="${escapeHtml(s.field_key)}">
            <td class="child-role-cell">${roleBadge}</td>
            <td class="child-protocol-cell"><span class="source-type-pill ${isMqtt ? 'mqtt' : 'modbus'}">${escapeHtml(sourceLabel)}</span></td>
            <td class="child-key-cell"><code class="code-path">${escapeHtml(s.field_key)}</code></td>
            <td class="child-val-cell">
              <div class="child-val-wrap">
                ${valDisplayHtml}
                ${formatTimestampBadge(s.last_updated, `ts-${sanitizeId(s.field_key)}`)}
              </div>
            </td>
            <td class="child-actions-cell text-right">
              ${!isMqtt ? `<button class="btn btn-xs btn-invert-polarity ${s.transform === 'negate' ? 'active' : ''}" data-sn="${escapeHtml(s.device_sn || f.device_sn || '')}" data-key="${escapeHtml(s.field_key)}" title="Toggle polarity negation (multiply by -1)">± ${s.transform === 'negate' ? 'Inverted' : 'Invert'}</button>` : ''}
              <button class="btn btn-xs btn-pin-source ${isPinned ? 'active' : ''}" data-group-id="${escapeHtml(f.id)}" data-key="${escapeHtml(s.field_key)}" title="${isPinned ? 'Unpin source' : 'Pin source'}">${isPinned ? '📌 Pinned' : 'Pin'}</button>
              ${s.is_custom_override || (f.sources && f.sources.length > 1) ? `<button class="btn btn-xs btn-remove-member" data-sn="${escapeHtml(s.device_sn || f.device_sn || '')}" data-key="${escapeHtml(s.field_key)}" title="Remove this field from the group">✕ Remove</button>` : ''}
            </td>
          </tr>
        `;
      }).join('');

      const cleanDeviceType = f.device_type || 'inverter';
      const haEntityId = `sensor.pwrcell_${cleanDeviceType}_${f.concept_key}`;

      let syncBadge = '';
      if (f.delta !== null && f.delta !== undefined) {
        if (f.is_discrepant) {
          syncBadge = `<span class="badge-discrepancy alert" title="${escapeHtml(f.discrepancy_reason || 'Values deviate across sources')}">⚠️ Divergent (Δ ${formatNumber(f.delta, 2)} ${f.units || ''})</span>`;
        } else {
          syncBadge = `<span class="badge-discrepancy ok">✓ In Sync (Δ ${formatNumber(f.delta, 2)} ${f.units || ''}, ${(f.match_pct || 100).toFixed(1)}%)</span>`;
        }
      }

      const validTimestamps = (f.sources || []).map(s => s.last_updated).filter(t => typeof t === 'number' && t > 0);
      let skewBadge = '';
      if (validTimestamps.length > 1) {
        const minT = Math.min(...validTimestamps);
        const maxT = Math.max(...validTimestamps);
        const deltaSec = maxT - minT;
        if (deltaSec >= 1.0) {
          skewBadge = `<span class="badge-skew-note" title="Difference in sample read times between sources in this group">⏱️ Δt ${deltaSec < 60 ? `${deltaSec.toFixed(1)}s` : `${Math.round(deltaSec / 60)}m`} poll skew</span>`;
        }
      }

      const childKeysJson = escapeHtml(JSON.stringify((f.sources || []).map(s => s.field_key)));
      const syncChildBtn = (f.sources && f.sources.length > 1)
        ? `<button class="btn-group-sync-sample" data-sn="${escapeHtml(f.device_sn || '')}" data-concept-key="${escapeHtml(f.concept_key || '')}" data-field-keys="${childKeysJson}" title="Sample all contributing sources together at the exact same moment to compare values and verify polling skew">⚡ Sync Sample</button>`
        : '';

      subTr.innerHTML = `
        <td colspan="8" class="group-children-container-cell">
          <div class="group-children-panel">
            <div class="group-children-header">
              <div class="group-children-header-left">
                <span class="group-children-title">Contributing Telemetry Sources (${f.sources.length})</span>
                ${syncBadge}
                ${skewBadge}
                ${syncChildBtn}
              </div>
              <div class="ha-preview-tag" title="Home Assistant Entity ID published via MQTT Discovery">
                <span class="ha-preview-label">HA Entity:</span> <code>${haEntityId}</code>
              </div>
            </div>
            <table class="group-children-table">
              <thead>
                <tr>
                  <th width="110">Role</th>
                  <th width="170">Protocol / Model</th>
                  <th>Field Path</th>
                  <th width="210">Live Value</th>
                  <th width="180" class="text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                ${childRowsHtml}
              </tbody>
            </table>
          </div>
        </td>
      `;

      // Event listeners for child actions
      subTr.querySelectorAll('.btn-invert-polarity').forEach(btn => {
        btn.addEventListener('click', async (e) => {
          e.stopPropagation();
          const sn = btn.dataset.sn;
          const key = btn.dataset.key;
          try {
            const res = await fetch(apiPath('api/grouping/invert'), {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ device_sn: sn, field_key: key }),
            });
            const data = await res.json();
            if (data.status === 'ok') {
              showToast(`Updated polarity transform for ${key}`);
              await refreshAfterGroupingChange(state.activeDevice ? state.activeDevice.serial_number : sn);
            } else {
              alert(`Error: ${data.error || 'Failed to update polarity'}`);
            }
          } catch (err) {
            alert(`Failed to invert: ${err}`);
          }
        });
      });

      subTr.querySelectorAll('.btn-pin-source').forEach(btn => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          const gId = btn.dataset.groupId;
          const fKey = btn.dataset.key;
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
            showToast(`Pinned ${f.label} to ${fKey}`);
          }
          updateOptimizationPlan();
        });
      });

      subTr.querySelectorAll('.btn-remove-member').forEach(btn => {
        btn.addEventListener('click', async (e) => {
          e.stopPropagation();
          const sn = btn.dataset.sn || (state.activeDevice ? state.activeDevice.serial_number : '');
          const key = btn.dataset.key;
          if (confirm(`Remove ${key} from group "${f.label}"?`)) {
            await ungroupFieldAction(sn, key);
          }
        });
      });

      const syncBtn = subTr.querySelector('.btn-group-sync-sample');
      if (syncBtn) {
        syncBtn.addEventListener('click', async (e) => {
          e.stopPropagation();
          const sn = syncBtn.dataset.sn;
          const conceptKey = syncBtn.dataset.conceptKey;
          const fieldKeys = JSON.parse(syncBtn.dataset.fieldKeys || '[]');
          await syncSampleAction(fieldKeys, sn, conceptKey, syncBtn);
        });
      }
    }

    return subTr ? [tr, subTr] : tr;
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
              ${formatTimestampBadge(f.last_updated || f.timestamp, `ts-${sanitizeId(f.key)}`)}
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
          <div class="type-cell-wrap">
            <span class="type-tag">${f.ha_platform}${f.ha_device_class ? ': ' + f.ha_device_class : ''}</span>
            ${renderCatToggleHtml(f)}
          </div>
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
                ${(f.is_writable || f.bounds) ? `<button class="action-menu-item item-bounds" data-key="${f.key}">📏 Configure Bounds...</button>` : ''}
                <button class="action-menu-item item-copy" data-key="${f.key}">📄 Copy Key</button>
                <button class="action-menu-item item-toggle-cat" data-key="${f.key}">${isFieldDiagnostic(f) ? '⚡ Set as Primary Sensor' : '🏷️ Set as Diagnostic'}</button>
                ${hasCategoryOverride(f) ? `<button class="action-menu-item item-reset-cat" data-key="${f.key}">↺ Reset Category to Default</button>` : ''}
                ${!isScaleFactorField(f) ? `
                  <button class="action-menu-item item-group-with" data-key="${f.key}">🔗 Group with Concept...</button>
                  ${f.is_custom_override ? `<button class="action-menu-item item-reset-group" data-key="${f.key}">↩️ Reset Grouping</button>` : ''}
                ` : ''}
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
          <div class="value-cell-wrap">
            <span class="field-value-badge${isBf ? ' is-bitfield' : ''}" id="val-${sanitizeId(f.key)}">${displayVal}</span>
            ${formatTimestampBadge(f.last_updated || f.timestamp, `ts-${sanitizeId(f.key)}`)}
          </div>
        </td>
        <td>${f.units || '&mdash;'}</td>
        <td>
          <span class="source-tag ${sourceClass}">${sourceLabel}</span>
        </td>
        <td>
          <div class="type-cell-wrap">
            <span class="type-tag">${f.ha_platform}${f.ha_device_class ? ': ' + f.ha_device_class : ''}</span>
            ${renderCatToggleHtml(f)}
          </div>
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
                ${(f.is_writable || f.bounds) ? `<button class="action-menu-item item-bounds" data-key="${f.key}">📏 Configure Bounds...</button>` : ''}
                <button class="action-menu-item item-copy" data-key="${f.key}">📄 Copy Key</button>
                <button class="action-menu-item item-toggle-cat" data-key="${f.key}">${isFieldDiagnostic(f) ? '⚡ Set as Primary Sensor' : '🏷️ Set as Diagnostic'}</button>
                ${hasCategoryOverride(f) ? `<button class="action-menu-item item-reset-cat" data-key="${f.key}">↺ Reset Category to Default</button>` : ''}
                ${!isScaleFactorField(f) ? `
                  <button class="action-menu-item item-group-with" data-key="${f.key}">🔗 Group with Concept...</button>
                  ${f.is_custom_override ? `<button class="action-menu-item item-reset-group" data-key="${f.key}">↩️ Reset Grouping</button>` : ''}
                ` : ''}
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

      const menuBounds = dropdownMenu.querySelector('.item-bounds');
      if (menuBounds) {
        menuBounds.addEventListener('click', (e) => {
          e.stopPropagation();
          dropdownMenu.classList.remove('show');
          openBoundsModal(f);
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

      const menuGroupWith = dropdownMenu.querySelector('.item-group-with');
      if (menuGroupWith) {
        menuGroupWith.addEventListener('click', (e) => {
          e.stopPropagation();
          dropdownMenu.classList.remove('show');
          openGroupingModal(f.device_sn, f.key, f.concept_key || '', f.label || f.name);
        });
      }

      const menuResetGroup = dropdownMenu.querySelector('.item-reset-group');
      if (menuResetGroup) {
        menuResetGroup.addEventListener('click', async (e) => {
          e.stopPropagation();
          dropdownMenu.classList.remove('show');
          await resetGroupingAction(f.device_sn, f.key);
        });
      }

      const menuToggleCat = dropdownMenu.querySelector('.item-toggle-cat');
      if (menuToggleCat) {
        menuToggleCat.addEventListener('click', async (e) => {
          e.stopPropagation();
          dropdownMenu.classList.remove('show');
          const currentIsDiag = isFieldDiagnostic(f);
          const targetCat = currentIsDiag ? 'primary' : 'diagnostic';
          const sn = getFieldDeviceSn(f);
          const fKey = f.id || f.key || f.concept_key;
          await toggleFieldCategoryAction(sn, fKey, targetCat, f.label || f.name);
        });
      }

      const menuResetCat = dropdownMenu.querySelector('.item-reset-cat');
      if (menuResetCat) {
        menuResetCat.addEventListener('click', async (e) => {
          e.stopPropagation();
          dropdownMenu.classList.remove('show');
          const sn = getFieldDeviceSn(f);
          const fKey = f.id || f.key || f.concept_key;
          await toggleFieldCategoryAction(sn, fKey, 'reset', f.label || f.name);
        });
      }
    }

    const catBtn = tr.querySelector('.badge-cat-toggle');
    if (catBtn) {
      catBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const currentIsDiag = isFieldDiagnostic(f);
        const targetCat = currentIsDiag ? 'primary' : 'diagnostic';
        const sn = getFieldDeviceSn(f);
        const fKey = f.id || f.key || f.concept_key;
        await toggleFieldCategoryAction(sn, fKey, targetCat, f.label || f.name);
      });
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
      const rowResult = renderUnifiedRow(f);
      if (Array.isArray(rowResult)) {
        rowResult.forEach(r => fragment.appendChild(r));
      } else {
        fragment.appendChild(rowResult);
      }
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

function formatBitfieldPlain(val, field) {
  const activeFlags = decodeBitfieldSymbols(field, val);
  const rawNum = field && typeof field.raw_value === 'number' ? field.raw_value : (typeof val === 'number' ? val : null);
  const rawHex = rawNum !== null ? `0x${(rawNum >>> 0).toString(16).toUpperCase()}` : null;
  const rawSuffix = rawNum !== null ? ` (${rawHex} / ${rawNum})` : '';

  if (!activeFlags || activeFlags.length === 0) {
    return `NONE (0)${rawSuffix}`;
  }
  return `${activeFlags.join(', ')}${rawSuffix}`;
}

function formatNumber(val, decimals = 2) {
  if (val === null || val === undefined || isNaN(val)) return '0';
  const num = Number(val);
  return Number.isInteger(num) ? num.toString() : num.toFixed(decimals);
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

function formatFieldValuePlain(val, field = null) {
  if (val === null || val === undefined) return '--';

  if (isBitfield(field, val)) {
    return formatBitfieldPlain(val, field);
  }

  if (field) {
    const sym = lookupEnumSymbol(field, val);
    if (sym) {
      if (sym.value !== null && sym.value !== undefined) {
        return `${sym.name} (${sym.value})`;
      }
      return sym.name;
    }
  }

  if (typeof val === 'number') {
    return Number.isInteger(val) ? val.toString() : val.toFixed(2);
  }
  return String(val);
}

// Format a timestamp (epoch seconds or ms) into HH:MM:SS
function formatTimestamp(ts) {
  if (!ts || isNaN(ts) || Number(ts) <= 0) return '';
  const num = Number(ts);
  const ms = num > 1e11 ? num : num * 1000;
  const d = new Date(ms);
  if (isNaN(d.getTime())) return '';
  const pad = (n) => String(n).padStart(2, '0');
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

// Format data age e.g. "3s ago", "2m 14s ago"
function formatDataAge(ts) {
  if (!ts || isNaN(ts) || Number(ts) <= 0) return '';
  const now = Date.now();
  const num = Number(ts);
  const ms = num > 1e11 ? num : num * 1000;
  const diffSec = Math.max(0, Math.round((now - ms) / 1000));
  if (diffSec < 60) return `${diffSec}s ago`;
  const min = Math.floor(diffSec / 60);
  const sec = diffSec % 60;
  return `${min}m ${sec}s ago`;
}

// Generate HTML badge for timestamp
function formatTimestampBadge(ts, elementId = null) {
  if (!ts || isNaN(ts) || Number(ts) <= 0) return '';
  const timeStr = formatTimestamp(ts);
  if (!timeStr) return '';
  const ageStr = formatDataAge(ts);
  const title = `Read at ${timeStr}${ageStr ? ` (${ageStr})` : ''}`;
  const idAttr = elementId ? ` id="${escapeHtml(elementId)}"` : '';
  return `<span class="field-timestamp-badge"${idAttr} title="${escapeHtml(title)}"><span class="ts-icon">🕒</span> ${escapeHtml(timeStr)}</span>`;
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
    if (el.counts.primary) el.counts.primary.textContent = fields.filter(f => !isFieldDiagnostic(f)).length;
    if (el.counts.diagnostic) el.counts.diagnostic.textContent = fields.filter(f => isFieldDiagnostic(f)).length;
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
    if (el.counts.primary) el.counts.primary.textContent = fields.filter(f => !isFieldDiagnostic(f)).length;
    if (el.counts.diagnostic) el.counts.diagnostic.textContent = fields.filter(f => isFieldDiagnostic(f)).length;
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
    // Update timestamp badge
    const tsBadge = document.getElementById(`ts-${id}`);
    if (tsBadge) {
      const ts = cField.last_updated || Date.now() / 1000;
      const tsStr = formatTimestamp(ts);
      const ageStr = formatDataAge(ts);
      tsBadge.innerHTML = `<span class="ts-icon">🕒</span> ${escapeHtml(tsStr)}`;
      tsBadge.title = `Read at ${tsStr}${ageStr ? ` (${ageStr})` : ''}`;
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
            if (field.last_updated) s.last_updated = field.last_updated;
            matched = true;
          }
        });
        if (matched) {
          const activeKey = state.preferredSources[g.id] || g.active_source_key;
          if (activeKey === field.key) {
            g.latest_value = field.value;
            if (field.last_updated) g.latest_updated = field.last_updated;
            const valBadge = document.getElementById(`val-${sanitizeId(g.id)}`);
            if (valBadge) {
              valBadge.innerHTML = formatFieldValue(field.value, g);
              valBadge.classList.toggle('is-bitfield', isBitfield(g, field.value));
              valBadge.classList.add('value-flash');
              setTimeout(() => valBadge.classList.remove('value-flash'), 600);
            }
            const tsBadge = document.getElementById(`ts-${sanitizeId(g.id)}`);
            if (tsBadge && g.latest_updated) {
              const tsStr = formatTimestamp(g.latest_updated);
              const ageStr = formatDataAge(g.latest_updated);
              tsBadge.innerHTML = `<span class="ts-icon">🕒</span> ${escapeHtml(tsStr)}`;
              tsBadge.title = `Read at ${tsStr}${ageStr ? ` (${ageStr})` : ''}`;
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
    const childTsBadge = document.getElementById(`ts-${sanitizeId(field.key)}`);
    if (childTsBadge && field.last_updated) {
      const tsStr = formatTimestamp(field.last_updated);
      const ageStr = formatDataAge(field.last_updated);
      childTsBadge.innerHTML = `<span class="ts-icon">🕒</span> ${escapeHtml(tsStr)}`;
      childTsBadge.title = `Read at ${tsStr}${ageStr ? ` (${ageStr})` : ''}`;
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
        <span class="write-bounds-title">
          📏 SunSpec Bounds &amp; Restrictions
          ${b.is_custom ? '<span class="badge-custom-bounds" style="margin-left: 6px;">Custom</span>' : ''}
        </span>
        <div style="display: flex; gap: 8px; align-items: center;">
          <button type="button" class="btn btn-secondary btn-xs btn-edit-bounds-from-write" style="padding: 1px 6px; font-size: 11px;" title="Configure custom bounds for this field">✏️ Edit Bounds</button>
          <span class="badge-writable">Read/Write (RW)</span>
        </div>
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

  const btnEditBounds = el.writeModalBounds.querySelector('.btn-edit-bounds-from-write');
  if (btnEditBounds) {
    btnEditBounds.addEventListener('click', (e) => {
      e.stopPropagation();
      openBoundsModal(field);
    });
  }
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
            ${bounds.is_custom ? '<span class="badge-custom-bounds" style="margin-left: 8px;">Custom</span>' : ''}
          </div>
          <div style="display: flex; gap: 8px; align-items: center;">
            <button type="button" class="btn btn-secondary btn-xs btn-open-bounds-from-details" title="Configure custom bounds for this field">✏️ Edit Bounds</button>
            <span class="${isSettable ? 'badge-writable' : 'source-tag'}">
              ${isSettable ? 'RW (Settable)' : 'R (Read-Only)'}
            </span>
          </div>
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
          <tr>
            <td class="def-prop-key">Home Assistant Category</td>
            <td class="def-prop-val">
              <div style="display: flex; align-items: center; gap: 10px;">
                <select id="detailsModalCatSelect" style="font-size: 12px; padding: 3px 8px; border-radius: var(--radius-sm, 4px); background: var(--bg-tertiary); color: var(--text-primary); border: 1px solid var(--border-color);">
                  <option value="reset" ${!hasCategoryOverride(f) ? 'selected' : ''}>Default (${isFieldDiagnostic(f) && !hasCategoryOverride(f) ? 'Diagnostic' : 'Primary'})</option>
                  <option value="primary" ${hasCategoryOverride(f) && !isFieldDiagnostic(f) ? 'selected' : ''}>⚡ Primary Sensor</option>
                  <option value="diagnostic" ${hasCategoryOverride(f) && isFieldDiagnostic(f) ? 'selected' : ''}>🏷️ Diagnostic</option>
                </select>
                <span class="text-muted" style="font-size: 11px;">${hasCategoryOverride(f) ? 'Custom Override Active' : 'Default Automatic Heuristic'}</span>
              </div>
            </td>
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

  const editBoundsFromDetails = el.detailsModalBody.querySelector('.btn-open-bounds-from-details');
  if (editBoundsFromDetails) {
    editBoundsFromDetails.addEventListener('click', () => {
      openBoundsModal({
        key: f.key || pt.key || fieldKey,
        name: f.name || pt.name,
        label: f.label || pt.label || f.name || pt.name,
        units: f.units || pt.units,
        device_sn: dev ? dev.serial_number : '',
        bounds: bounds,
        point_type: f.point_type || pt.type,
      });
    });
  }

  const catSelect = el.detailsModalBody.querySelector('#detailsModalCatSelect');
  if (catSelect) {
    catSelect.addEventListener('change', async (e) => {
      const targetCat = e.target.value;
      const sn = dev ? dev.serial_number : getFieldDeviceSn(f);
      const fKey = f.id || f.key || f.concept_key || fieldKey;
      await toggleFieldCategoryAction(sn, fKey, targetCat, f.label || f.name);
    });
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

  // Polling Plan Detailed Breakdown Toggle
  if (el.btnTogglePlanDetails) {
    el.btnTogglePlanDetails.addEventListener('click', (e) => {
      e.stopPropagation();
      state.showPlanDetails = !state.showPlanDetails;
      if (state.bannerCollapsed && state.showPlanDetails) {
        state.bannerCollapsed = false;
        if (optBannerBody) optBannerBody.style.display = 'flex';
        if (btnToggleBanner) {
          btnToggleBanner.textContent = '−';
          btnToggleBanner.title = 'Minimize Polling Plan';
        }
        if (el.optimizationBanner) el.optimizationBanner.classList.remove('collapsed');
      }
      renderPlanBreakdown(state.optimizationPlan);
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
          category_overrides: state.haCategoryOverrides,
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

  // Clean Stale HA MQTT Discovery Topics
  if (el.btnCleanHA) {
    el.btnCleanHA.addEventListener('click', async () => {
      if (!confirm('Scan the MQTT broker and purge any orphaned or obsolete PWRcell discovery topics (such as old concept entities)? Active entities will be re-published cleanly.')) {
        return;
      }
      const origText = el.btnCleanHA.textContent;
      try {
        el.btnCleanHA.disabled = true;
        el.btnCleanHA.textContent = '🧹 Cleaning...';
        const res = await fetch(apiPath('api/ha/clean_discovery'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        });
        const data = await res.json();
        if (data.success) {
          showToast(`Purged ${data.purged_count || 0} orphaned MQTT discovery topics and re-published active entities.`);
        } else {
          alert(`Error cleaning discovery: ${data.error || 'Unknown error'}`);
        }
      } catch (err) {
        alert(`Failed cleaning discovery: ${err}`);
      } finally {
        el.btnCleanHA.disabled = false;
        el.btnCleanHA.textContent = origText;
      }
    });
  }

  // Reset HA Config to Defaults
  if (el.btnResetHA) {
    el.btnResetHA.addEventListener('click', async () => {
      if (!confirm('Reset all Home Assistant entity selections back to the default recommended configuration? This will overwrite ha_config.yaml with default fields, purge stale topics, and re-publish discovery.')) {
        return;
      }
      const origText = el.btnResetHA.textContent;
      try {
        el.btnResetHA.disabled = true;
        el.btnResetHA.textContent = '↺ Resetting...';
        const res = await fetch(apiPath('api/ha/reset_defaults'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ purge_mqtt: true }),
        });
        const data = await res.json();
        if (data.success) {
          state.modifiedDeviceSerials.clear();
          state.haCategoryOverrides = {};
          if (Array.isArray(data.selected_fields)) {
            state.selectedHaKeys = new Set(data.selected_fields);
            updateHaCounter();
            updateFilterCounts();
            renderFieldTable();
          }
          showToast(`Reset to defaults: ${data.count} entities selected!`);
        } else {
          alert(`Error resetting config: ${data.error || 'Unknown error'}`);
        }
      } catch (err) {
        alert(`Failed resetting config: ${err}`);
      } finally {
        el.btnResetHA.disabled = false;
        el.btnResetHA.textContent = origText;
      }
    });
  }

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
    el.btnOpenCompare.addEventListener('click', () => openCompareModal());
    if (el.btnOpenSuggestions) {
      el.btnOpenSuggestions.addEventListener('click', () => openCompareModal('suggestions'));
    }
    el.btnCloseCompare.addEventListener('click', closeCompareModal);
    el.btnCloseCompareFooter.addEventListener('click', closeCompareModal);

    // Tab buttons
    const bindTab = (btn, tabName) => {
      if (btn) {
        btn.addEventListener('click', () => {
          compareState.activeTab = tabName;
          updateCompareTabActiveStyles();
          if (tabName === 'suggestions') {
            renderCompareSuggestions(compareState.suggestions || []);
          } else if (compareState.data) {
            const rows = Array.isArray(compareState.data) ? compareState.data : (compareState.data.comparisons || []);
            renderCompareTableRows(rows);
          }
        });
      }
    };
    bindTab(el.tabCmpDiscrepancies, 'discrepancies');
    bindTab(el.tabCmpSuggestions, 'suggestions');
    bindTab(el.tabCmpMulti, 'multisource');
    bindTab(el.tabCmpMatches, 'matches');
    bindTab(el.tabCmpAll, 'all');

    // Device selector
    if (el.cmpDeviceSelect) {
      el.cmpDeviceSelect.addEventListener('change', (e) => {
        compareState.selectedDevice = e.target.value;
        if (compareState.activeTab === 'suggestions') {
          renderCompareSuggestions(compareState.suggestions || []);
        } else if (compareState.data) {
          const rows = Array.isArray(compareState.data) ? compareState.data : (compareState.data.comparisons || []);
          renderCompareTableRows(rows);
        }
      });
    }

    // Search input
    if (el.cmpSearchInput) {
      el.cmpSearchInput.addEventListener('input', (e) => {
        compareState.searchQuery = e.target.value;
        if (compareState.activeTab === 'suggestions') {
          renderCompareSuggestions(compareState.suggestions || []);
        } else if (compareState.data) {
          const rows = Array.isArray(compareState.data) ? compareState.data : (compareState.data.comparisons || []);
          renderCompareTableRows(rows);
        }
      });
    }

    // Suggestions action delegation (Approve, Dismiss, Customize)
    if (el.suggestionsList) {
      el.suggestionsList.addEventListener('click', async (e) => {
        const approveBtn = e.target.closest('[data-action="approve-suggestion"]');
        if (approveBtn) {
          const sId = approveBtn.dataset.id;
          const deviceSn = approveBtn.dataset.sn;
          const targetConcept = approveBtn.dataset.concept;
          const customLabel = approveBtn.dataset.label;
          const fieldKeys = JSON.parse(approveBtn.dataset.fieldKeys || '[]');
          const isInverted = approveBtn.dataset.inverted === 'true';
          const suggestedTransform = approveBtn.dataset.suggestedTransform || null;

          const executeApprove = async (chosenTransform, polarityInfo = {}) => {
            approveBtn.disabled = true;
            approveBtn.textContent = 'Merging...';

            try {
              const res = await fetch(apiPath('api/grouping/suggestions/approve'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  device_sn: deviceSn,
                  field_keys: fieldKeys,
                  target_concept: targetConcept,
                  label: customLabel,
                  suggestion_id: sId,
                  transform: chosenTransform,
                  negate_field_key: polarityInfo.negateFieldKey || null,
                  positive_field_key: polarityInfo.positiveFieldKey || approveBtn.dataset.posKey || null,
                  negative_field_key: polarityInfo.negativeFieldKey || approveBtn.dataset.negKey || null,
                  polarity_convention: polarityInfo.polarityConvention || null,
                }),
              });
              const data = await res.json();
              if (data.status === 'ok') {
                showToast(`Merged into ${customLabel || targetConcept}!`);
                await refreshAfterGroupingChange(deviceSn);
                await fetchGroupingSuggestions();
                fetchAndRenderCompare();
              } else {
                alert(`Error approving suggestion: ${data.error || 'Unknown error'}`);
              }
            } catch (err) {
              alert(`Failed approving suggestion: ${err}`);
            } finally {
              approveBtn.disabled = false;
              approveBtn.textContent = '✅ Approve & Merge';
            }
          };

          if (isInverted || suggestedTransform === 'negate') {
            const currentSug = (compareState.suggestions || []).find(s => s.id === sId) || {
              suggested_label: customLabel,
              suggested_concept_key: targetConcept,
              positive_field_key: approveBtn.dataset.posKey,
              negative_field_key: approveBtn.dataset.negKey,
            };
            promptPolaritySelection({
              suggestion: currentSug,
              onSelect: (pol) => executeApprove(pol.transform, pol),
            });
            return;
          }

          await executeApprove(suggestedTransform);
          return;
        }

        const dismissBtn = e.target.closest('[data-action="dismiss-suggestion"]');
        if (dismissBtn) {
          const sId = dismissBtn.dataset.id;
          dismissBtn.disabled = true;
          try {
            const res = await fetch(apiPath('api/grouping/suggestions/dismiss'), {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ suggestion_id: sId }),
            });
            const data = await res.json();
            if (data.status === 'ok') {
              showToast('Suggestion dismissed');
              await fetchGroupingSuggestions();
              fetchAndRenderCompare();
            }
          } catch (err) {
            alert(`Failed dismissing suggestion: ${err}`);
          }
          return;
        }

        const customizeBtn = e.target.closest('[data-action="customize-suggestion"]');
        if (customizeBtn) {
          const deviceSn = customizeBtn.dataset.sn;
          const fieldKeys = JSON.parse(customizeBtn.dataset.fieldKeys || '[]');
          const targetConcept = customizeBtn.dataset.concept;
          const customLabel = customizeBtn.dataset.label;
          const isInverted = customizeBtn.dataset.inverted === 'true' || customizeBtn.dataset.suggestedTransform === 'negate';
          if (fieldKeys.length > 0) {
            openGroupingModal(deviceSn, fieldKeys[0], targetConcept);
            if (el.radioGroupNew) {
              el.radioGroupNew.checked = true;
              if (el.groupingNewConceptKey) el.groupingNewConceptKey.value = targetConcept;
              if (el.groupingNewConceptLabel) el.groupingNewConceptLabel.value = customLabel;
            }
            if (isInverted && el.radioTransformNegate) {
              el.radioTransformNegate.checked = true;
            }
          }
          return;
        }

        const syncSuggBtn = e.target.closest('[data-action="sync-sample-suggestion"]');
        if (syncSuggBtn) {
          e.stopPropagation();
          const sn = syncSuggBtn.dataset.sn;
          const fieldKeys = JSON.parse(syncSuggBtn.dataset.fieldKeys || '[]');
          await syncSampleAction(fieldKeys, sn, null, syncSuggBtn);
          return;
        }

        const batchDeviceBtn = e.target.closest('[data-action="batch-approve-device"]');
        if (batchDeviceBtn) {
          const deviceSn = batchDeviceBtn.dataset.sn;
          const items = JSON.parse(batchDeviceBtn.dataset.items || '[]');
          if (items.length === 0) return;

          batchDeviceBtn.disabled = true;
          batchDeviceBtn.textContent = 'Approving...';
          try {
            const res = await fetch(apiPath('api/grouping/suggestions/batch-approve'), {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ suggestions: items }),
            });
            const data = await res.json();
            if (data.status === 'ok') {
              showToast(`Approved ${items.length} suggestions for ${deviceSn.slice(-4)}!`);
              await refreshAfterGroupingChange(deviceSn);
              await fetchGroupingSuggestions();
              fetchAndRenderCompare();
            } else {
              alert(`Error approving suggestions: ${data.error || 'Unknown error'}`);
            }
          } catch (err) {
            alert(`Failed approving suggestions: ${err}`);
          }
          return;
        }

        // Copy key inside suggestion
        const copyBtn = e.target.closest('.btn-copy-key');
        if (copyBtn) {
          e.stopPropagation();
          const keyToCopy = copyBtn.dataset.copyKey;
          if (keyToCopy) {
            copyToClipboard(keyToCopy);
            showToast(`Copied ${keyToCopy} to clipboard`);
          }
          return;
        }

        // Toggle expand suggestion card
        if (e.target.closest('.compare-source-key.selectable')) {
          return;
        }

        const card = e.target.closest('.suggestion-card');
        if (card && card.dataset.suggestionId) {
          const sId = card.dataset.suggestionId;
          if (compareState.expandedSuggestions.has(sId)) {
            compareState.expandedSuggestions.delete(sId);
          } else {
            compareState.expandedSuggestions.add(sId);
          }
          renderCompareSuggestions(compareState.suggestions || []);
          return;
        }
      });
    }

    // Suggestions Toolbar Controls
    if (el.cmpSuggestionsConfidence) {
      el.cmpSuggestionsConfidence.addEventListener('change', (e) => {
        compareState.suggestionConfidence = e.target.value;
        renderCompareSuggestions(compareState.suggestions || []);
      });
    }

    if (el.btnRefreshSuggestions) {
      el.btnRefreshSuggestions.addEventListener('click', async () => {
        el.btnRefreshSuggestions.disabled = true;
        el.btnRefreshSuggestions.textContent = '🔄 Scanning...';
        try {
          await fetchGroupingSuggestions();
          showToast('Updated grouping suggestions');
        } finally {
          el.btnRefreshSuggestions.disabled = false;
          el.btnRefreshSuggestions.textContent = '🔄 Re-scan';
        }
      });
    }

    if (el.btnBatchApproveVisible) {
      el.btnBatchApproveVisible.addEventListener('click', async () => {
        const visible = compareState.visibleSuggestions || [];
        if (visible.length === 0) return;
        const confirmMsg = `Approve all ${visible.length} visible grouping suggestions?`;
        if (!confirm(confirmMsg)) return;

        el.btnBatchApproveVisible.disabled = true;
        el.btnBatchApproveVisible.textContent = 'Approving...';
        try {
          const items = visible.map(s => ({
            device_sn: s.device_sn,
            field_keys: (s.sources || []).map(src => src.field_key),
            target_concept: s.suggested_concept_key,
            label: s.suggested_label,
            suggestion_id: s.id,
            transform: s.suggested_transform,
            positive_field_key: s.positive_field_key || null,
            negative_field_key: s.negative_field_key || null,
            negate_field_key: s.negative_field_key || null,
            polarity_convention: 'positive',
          }));
          const res = await fetch(apiPath('api/grouping/suggestions/batch-approve'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ suggestions: items }),
          });
          const data = await res.json();
          if (data.status === 'ok') {
            showToast(`Approved ${items.length} suggestions!`);
            const firstSn = visible[0] ? visible[0].device_sn : '';
            if (firstSn) await refreshAfterGroupingChange(firstSn);
            await fetchGroupingSuggestions();
            fetchAndRenderCompare();
          } else {
            alert(`Error approving suggestions: ${data.error || 'Unknown error'}`);
          }
        } catch (err) {
          alert(`Failed approving suggestions: ${err}`);
        } finally {
          el.btnBatchApproveVisible.disabled = false;
        }
      });
    }

    if (el.btnBatchDismissVisible) {
      el.btnBatchDismissVisible.addEventListener('click', async () => {
        const visible = compareState.visibleSuggestions || [];
        if (visible.length === 0) return;
        const confirmMsg = `Dismiss all ${visible.length} visible grouping suggestions?`;
        if (!confirm(confirmMsg)) return;

        el.btnBatchDismissVisible.disabled = true;
        el.btnBatchDismissVisible.textContent = 'Dismissing...';
        try {
          const ids = visible.map(s => s.id);
          const res = await fetch(apiPath('api/grouping/suggestions/batch-dismiss'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ suggestion_ids: ids }),
          });
          const data = await res.json();
          if (data.status === 'ok') {
            showToast(`Dismissed ${ids.length} suggestions`);
            await fetchGroupingSuggestions();
            fetchAndRenderCompare();
          } else {
            alert(`Error dismissing suggestions: ${data.error || 'Unknown error'}`);
          }
        } catch (err) {
          alert(`Failed dismissing suggestions: ${err}`);
        } finally {
          el.btnBatchDismissVisible.disabled = false;
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
          await selectDevice(state.selectedDeviceSn);
        }
      } catch (err) {
        showToast(`Sync failed: ${err}`);
      } finally {
        el.btnSyncModbus.disabled = false;
        el.btnSyncModbus.textContent = '🔄 Sync Config';
      }
    });
  }

  // Grouping Modal
  if (el.btnCloseGroupingModal) {
    el.btnCloseGroupingModal.addEventListener('click', closeGroupingModal);
  }
  if (el.btnCancelGroupingModal) {
    el.btnCancelGroupingModal.addEventListener('click', closeGroupingModal);
  }
  if (el.btnSaveGroupingModal) {
    el.btnSaveGroupingModal.addEventListener('click', saveGroupingAction);
  }
  if (el.btnResetGroupingModal) {
    el.btnResetGroupingModal.addEventListener('click', async () => {
      if (!state.groupingModalData) return;
      await resetGroupingAction(state.groupingModalData.deviceSn, state.groupingModalData.fieldKey);
      closeGroupingModal();
    });
  }
  if (el.groupingModal) {
    el.groupingModal.addEventListener('click', (e) => {
      if (e.target === el.groupingModal) closeGroupingModal();
    });
  }

  // Bounds Modal
  if (el.btnCloseBoundsModal) {
    el.btnCloseBoundsModal.addEventListener('click', closeBoundsModal);
  }
  if (el.btnCancelBoundsModal) {
    el.btnCancelBoundsModal.addEventListener('click', closeBoundsModal);
  }
  if (el.btnSaveBoundsModal) {
    el.btnSaveBoundsModal.addEventListener('click', saveBoundsAction);
  }
  if (el.btnResetBoundsModal) {
    el.btnResetBoundsModal.addEventListener('click', resetBoundsAction);
  }
  if (el.boundsModal) {
    el.boundsModal.addEventListener('click', (e) => {
      if (e.target === el.boundsModal) closeBoundsModal();
    });
  }

  // Export Mappings Modal
  if (el.btnOpenExportMappings) {
    el.btnOpenExportMappings.addEventListener('click', () => openExportModal());
  }
  if (el.btnCloseExportModal) {
    el.btnCloseExportModal.addEventListener('click', closeExportModal);
  }
  if (el.btnCloseExportFooter) {
    el.btnCloseExportFooter.addEventListener('click', closeExportModal);
  }
  if (el.exportMappingsModal) {
    el.exportMappingsModal.addEventListener('click', (e) => {
      if (e.target === el.exportMappingsModal) closeExportModal();
    });
  }
  if (el.btnFormatGeneralized) {
    el.btnFormatGeneralized.addEventListener('click', async () => {
      currentExportFormat = 'generalized';
      updateExportFormatUI();
      await fetchExportYaml();
    });
  }
  if (el.btnFormatTelemetry) {
    el.btnFormatTelemetry.addEventListener('click', async () => {
      currentExportFormat = 'telemetry_mappings';
      updateExportFormatUI();
      await fetchExportYaml();
    });
  }
  if (el.btnCopyExportYaml) {
    el.btnCopyExportYaml.addEventListener('click', () => {
      if (currentExportYaml) {
        copyToClipboard(currentExportYaml);
        showToast(`Copied ${currentExportFilename} to clipboard!`);
      }
    });
  }
  if (el.btnDownloadExportYaml) {
    el.btnDownloadExportYaml.addEventListener('click', () => {
      window.location.href = apiPath(`api/grouping/export?format=${encodeURIComponent(currentExportFormat)}&download=true`);
    });
  }
  if (el.btnApplyCleanSlate) {
    el.btnApplyCleanSlate.addEventListener('click', async () => {
      if (!confirm('This will update groupings.yaml with all current mappings and ungrouped fields, and clear local overrides in custom_groupings.yaml so you start fresh. Proceed?')) {
        return;
      }
      try {
        el.btnApplyCleanSlate.disabled = true;
        el.btnApplyCleanSlate.textContent = 'Saving...';
        const res = await fetch(apiPath('api/grouping/save-to-mappings'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ clear_custom_overrides: true, only_custom: false }),
        });
        const data = await res.json();
        if (data.status === 'ok') {
          showToast(`Saved ${data.mappings_count || data.groups_count || ''} mappings (${data.ungrouped_count || 0} ungrouped) to groupings.yaml! Clean slate active.`);
          closeExportModal();
          await fetchExportYaml();
          if (typeof fetchCompareData === 'function') {
            await fetchCompareData();
          }
        } else {
          alert('Failed to save mappings: ' + (data.error || 'Unknown error'));
        }
      } catch (err) {
        alert('Failed to save mappings: ' + err);
      } finally {
        el.btnApplyCleanSlate.disabled = false;
        el.btnApplyCleanSlate.textContent = '💾 Save to Mappings & Clean Slate';
      }
    });
  }

  // Compare Table Event Delegation for Grouping Actions
  if (el.compareTableBody) {
    el.compareTableBody.addEventListener('click', async (e) => {
      const btn = e.target.closest('.btn-group-action, .btn-sync-sample-pair');
      if (btn) {
        e.stopPropagation();
        const action = btn.dataset.action;
        let sn = btn.dataset.sn || (state.activeDevice ? state.activeDevice.serial_number : '') || compareState.selectedDevice || '';
        const fieldKey = btn.dataset.fieldKey;
        const conceptKey = btn.dataset.conceptKey;
        const conceptLabel = btn.dataset.conceptLabel;

        if (action === 'sync-sample-pair') {
          const fieldKeys = JSON.parse(btn.dataset.fieldKeys || '[]');
          await syncSampleAction(fieldKeys, sn, conceptKey, btn);
        } else if (action === 'ungroup') {
          await ungroupFieldAction(sn, fieldKey);
        } else if (action === 'group-with') {
          openGroupingModal(sn, fieldKey, conceptKey, conceptLabel);
        } else if (action === 'reset-group') {
          await resetGroupingAction(sn, fieldKey);
        } else if (action === 'ungroup-all') {
          await ungroupAllAction(sn, conceptKey);
        }
        return;
      }

      const copyBtn = e.target.closest('.btn-copy-key');
      if (copyBtn) {
        e.stopPropagation();
        const keyToCopy = copyBtn.dataset.copyKey;
        if (keyToCopy) {
          copyToClipboard(keyToCopy);
          showToast(`Copied ${keyToCopy} to clipboard`);
        }
        return;
      }

      if (e.target.closest('.compare-source-key.selectable') || e.target.closest('input') || e.target.closest('select')) {
        return;
      }

      const row = e.target.closest('tr.compare-row');
      if (row && row.dataset.rowId) {
        const rowId = row.dataset.rowId;
        if (compareState.expandedRows.has(rowId)) {
          compareState.expandedRows.delete(rowId);
        } else {
          compareState.expandedRows.add(rowId);
        }
        if (compareState.data) {
          const rows = Array.isArray(compareState.data) ? compareState.data : (compareState.data.comparisons || []);
          renderCompareTableRows(rows);
        }
      }
    });
  }
}

// Polarity Selection Helper for Inverted Telemetry Pairs
function promptPolaritySelection({ suggestion, onSelect }) {
  if (!el.polarityModal) {
    onSelect({
      transform: 'negate',
      negateFieldKey: suggestion.negative_field_key,
      positiveFieldKey: suggestion.positive_field_key,
      negativeFieldKey: suggestion.negative_field_key,
      polarityConvention: 'positive',
    });
    return;
  }
  const posKey = suggestion.positive_field_key || 'Positive Register';
  const negKey = suggestion.negative_field_key || 'Negative Register';

  if (el.polarityModalDesc) {
    el.polarityModalDesc.textContent = `The suggested registers for "${suggestion.suggested_label || suggestion.suggested_concept_key}" report values with opposite signs. Choose whether the combined concept should be positive or negative:`;
  }
  if (el.polarityPositiveDesc) {
    el.polarityPositiveDesc.textContent = `Align to positive (+): inverts ${negKey} so both streams match as positive.`;
  }
  if (el.polarityNegativeDesc) {
    el.polarityNegativeDesc.textContent = `Align to negative (-): inverts ${posKey} so both streams match as negative.`;
  }

  const cleanup = () => {
    el.polarityModal.classList.remove('open');
    if (el.btnPolarityPositive) el.btnPolarityPositive.onclick = null;
    if (el.btnPolarityNegative) el.btnPolarityNegative.onclick = null;
    if (el.btnPolarityDirect) el.btnPolarityDirect.onclick = null;
    if (el.btnClosePolarityModal) el.btnClosePolarityModal.onclick = null;
    if (el.btnCancelPolarityModal) el.btnCancelPolarityModal.onclick = null;
  };

  if (el.btnPolarityPositive) {
    el.btnPolarityPositive.onclick = () => {
      cleanup();
      onSelect({
        transform: 'negate',
        negateFieldKey: suggestion.negative_field_key,
        positiveFieldKey: suggestion.positive_field_key,
        negativeFieldKey: suggestion.negative_field_key,
        polarityConvention: 'positive',
      });
    };
  }
  if (el.btnPolarityNegative) {
    el.btnPolarityNegative.onclick = () => {
      cleanup();
      onSelect({
        transform: 'negate',
        negateFieldKey: suggestion.positive_field_key,
        positiveFieldKey: suggestion.positive_field_key,
        negativeFieldKey: suggestion.negative_field_key,
        polarityConvention: 'negative',
      });
    };
  }
  if (el.btnPolarityDirect) {
    el.btnPolarityDirect.onclick = () => {
      cleanup();
      onSelect({
        transform: 'none',
        negateFieldKey: null,
        positiveFieldKey: suggestion.positive_field_key,
        negativeFieldKey: suggestion.negative_field_key,
        polarityConvention: 'none',
      });
    };
  }
  if (el.btnClosePolarityModal) el.btnClosePolarityModal.onclick = cleanup;
  if (el.btnCancelPolarityModal) el.btnCancelPolarityModal.onclick = cleanup;

  el.polarityModal.classList.add('open');
}

// Field Bounds Configuration Modal Logic
function openBoundsModal(field) {
  if (!el.boundsModal || !field) return;
  state.boundsModalField = field;

  const b = getFieldBounds(field) || {};
  const isCustom = !!b.is_custom;
  const unit = field.units || b.units || '';
  const fieldKey = field.key || field.field_key || field.id || '';
  const label = field.label || field.name || fieldKey;

  // Header & Context
  if (el.boundsModalTitle) el.boundsModalTitle.textContent = `Configure Bounds: ${label}`;
  if (el.boundsFieldKeyBadge) el.boundsFieldKeyBadge.textContent = fieldKey;
  if (el.boundsFieldName) el.boundsFieldName.textContent = `${label} (${fieldKey})`;

  // Default SunSpec specification explanation
  let defaultText = 'No raw bounds specified';
  if (b.raw_min !== undefined && b.raw_max !== undefined) {
    if (b.scaled_min !== undefined && b.scaled_max !== undefined && b.sf) {
      defaultText = `${b.scaled_min} to ${b.scaled_max} ${unit}`.trim() + ` (raw: ${b.raw_min.toLocaleString()} to ${b.raw_max.toLocaleString()}, SF: ${b.sf})`;
    } else {
      defaultText = `${b.raw_min.toLocaleString()} to ${b.raw_max.toLocaleString()} ${unit}`.trim();
    }
  }
  if (el.boundsDefaultLimits) el.boundsDefaultLimits.textContent = defaultText;

  // Current status
  if (el.boundsCurrentStatus) {
    if (isCustom) {
      el.boundsCurrentStatus.innerHTML = `<span style="color: #10b981; font-weight: 600;">Active Custom Limits: ${b.min_value} to ${b.max_value} ${unit} (step: ${b.step !== undefined ? b.step : 1})</span>`;
    } else {
      el.boundsCurrentStatus.textContent = 'Using SunSpec register specification defaults';
    }
  }

  // Toggle Reset button
  if (el.btnResetBoundsModal) {
    el.btnResetBoundsModal.style.display = isCustom ? 'inline-block' : 'none';
  }

  // Update unit labels
  document.querySelectorAll('.bounds-unit-label').forEach(lbl => {
    lbl.textContent = unit || 'units';
  });

  // Populate inputs with current values
  if (el.boundsMinInput) {
    el.boundsMinInput.value = b.min_value !== undefined && b.min_value !== null
      ? b.min_value
      : (b.scaled_min !== undefined && b.scaled_min !== null ? b.scaled_min : (b.raw_min !== undefined ? b.raw_min : 0));
  }
  if (el.boundsMaxInput) {
    el.boundsMaxInput.value = b.max_value !== undefined && b.max_value !== null
      ? b.max_value
      : (b.scaled_max !== undefined && b.scaled_max !== null ? b.scaled_max : (b.raw_max !== undefined ? b.raw_max : ''));
  }
  if (el.boundsStepInput) {
    el.boundsStepInput.value = b.step !== undefined && b.step !== null
      ? b.step
      : (b.sf_value !== undefined && b.sf_value !== null && -10 <= b.sf_value && b.sf_value <= 10 ? Math.pow(10, b.sf_value) : 1);
  }
  if (el.boundsApplyAll) {
    el.boundsApplyAll.checked = true;
  }

  el.boundsModal.classList.add('open');
}

function closeBoundsModal() {
  if (el.boundsModal) {
    el.boundsModal.classList.remove('open');
  }
  state.boundsModalField = null;
}

async function saveBoundsAction() {
  if (!state.boundsModalField) return;
  const field = state.boundsModalField;
  const fieldKey = field.key || field.field_key || field.id || '';
  const minValStr = el.boundsMinInput ? el.boundsMinInput.value.trim() : '';
  const maxValStr = el.boundsMaxInput ? el.boundsMaxInput.value.trim() : '';
  const stepValStr = el.boundsStepInput ? el.boundsStepInput.value.trim() : '';

  if (minValStr === '' || maxValStr === '') {
    alert('Please enter both a minimum and maximum value.');
    return;
  }

  const minNum = parseFloat(minValStr);
  const maxNum = parseFloat(maxValStr);
  if (isNaN(minNum) || isNaN(maxNum)) {
    alert('Minimum and Maximum must be valid numbers.');
    return;
  }
  if (minNum > maxNum) {
    alert('Minimum value cannot exceed Maximum value.');
    return;
  }

  const stepNum = stepValStr !== '' ? parseFloat(stepValStr) : 1;
  const applyAll = el.boundsApplyAll ? el.boundsApplyAll.checked : true;
  const devSn = field.device_sn || (state.activeDevice ? state.activeDevice.serial_number : '');

  try {
    if (el.btnSaveBoundsModal) {
      el.btnSaveBoundsModal.disabled = true;
      el.btnSaveBoundsModal.textContent = 'Saving...';
    }

    const payload = {
      field_key: fieldKey,
      device_sn: devSn,
      apply_all: applyAll,
      min: minNum,
      max: maxNum,
      step: stepNum,
    };

    const res = await fetch(apiPath('api/grouping/bounds'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();

    if (data.success) {
      showToast(`Saved custom bounds for ${field.name || field.label || fieldKey}: ${minNum} to ${maxNum} ${field.units || ''}`);
      closeBoundsModal();
      if (devSn) {
        await selectDevice(devSn);
      }
      if (el.modbusDetailsModal && el.modbusDetailsModal.classList.contains('open')) {
        await openFieldDetails(fieldKey, devSn);
      }
    } else {
      alert(`Error saving bounds: ${data.error || 'Unknown error'}`);
    }
  } catch (err) {
    alert(`Failed saving bounds: ${err}`);
  } finally {
    if (el.btnSaveBoundsModal) {
      el.btnSaveBoundsModal.disabled = false;
      el.btnSaveBoundsModal.textContent = 'Save Bounds';
    }
  }
}

async function resetBoundsAction() {
  if (!state.boundsModalField) return;
  const field = state.boundsModalField;
  const fieldKey = field.key || field.field_key || field.id || '';
  const devSn = field.device_sn || (state.activeDevice ? state.activeDevice.serial_number : '');

  try {
    if (el.btnResetBoundsModal) {
      el.btnResetBoundsModal.disabled = true;
      el.btnResetBoundsModal.textContent = 'Resetting...';
    }

    const res = await fetch(apiPath('api/grouping/bounds'), {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        field_key: fieldKey,
        device_sn: devSn,
      }),
    });
    const data = await res.json();

    if (data.success) {
      showToast(`Reset bounds for ${field.name || field.label || fieldKey} to defaults`);
      closeBoundsModal();
      if (devSn) {
        await selectDevice(devSn);
      }
      if (el.modbusDetailsModal && el.modbusDetailsModal.classList.contains('open')) {
        await openFieldDetails(fieldKey, devSn);
      }
    } else {
      alert(`Error resetting bounds: ${data.error || 'Unknown error'}`);
    }
  } catch (err) {
    alert(`Failed resetting bounds: ${err}`);
  } finally {
    if (el.btnResetBoundsModal) {
      el.btnResetBoundsModal.disabled = false;
      el.btnResetBoundsModal.textContent = '↩️ Reset to Default';
    }
  }
}

// Field Grouping & Ungrouping Modal Logic
const GENERIC_CONCEPTS = new Set(['energy', 'power', 'voltage', 'current', 'frequency', 'temperature', 'status', 'state', 'standalone', 'null', 'none', '']);

async function openGroupingModal(deviceSn, fieldKey, currentConceptKey, currentConceptLabel) {
  if (!el.groupingModal) return;
  const sn = deviceSn || (state.activeDevice ? state.activeDevice.serial_number : '') || compareState.selectedDevice || '';
  const cleanConceptKey = (currentConceptKey || '').trim();
  const isGenericOrStandalone = !cleanConceptKey || GENERIC_CONCEPTS.has(cleanConceptKey.toLowerCase());

  state.groupingModalData = {
    deviceSn: sn,
    fieldKey,
    currentConceptKey: cleanConceptKey,
    currentConceptLabel: currentConceptLabel || cleanConceptKey || '(Standalone)',
  };

  el.groupingFieldKeyBadge.textContent = fieldKey;
  el.groupingDeviceLabel.textContent = sn || '(All Devices)';
  el.groupingCurrentConceptLabel.textContent = state.groupingModalData.currentConceptLabel;

  if (el.radioTransformNone) el.radioTransformNone.checked = true;

  // Derive suggested new concept key and label from fieldKey and label
  const pointName = (fieldKey || '').split('.').pop() || 'field';
  let suggestedNewKey = '';
  let suggestedNewLabel = '';

  if (currentConceptLabel && !GENERIC_CONCEPTS.has(currentConceptLabel.toLowerCase()) && currentConceptLabel !== '(Standalone)') {
    suggestedNewLabel = currentConceptLabel.replace(/\(.*?\)/g, '').trim();
    suggestedNewKey = suggestedNewLabel.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
  } else {
    suggestedNewLabel = pointName;
    suggestedNewKey = pointName.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
  }

  el.groupingNewConceptKey.value = suggestedNewKey;
  el.groupingNewConceptLabel.value = suggestedNewLabel;

  // Default to 'Create a new custom concept' when field is standalone or in a generic pool
  // This prevents accidental merging into large existing groups.
  if (isGenericOrStandalone) {
    if (el.radioGroupNew) el.radioGroupNew.checked = true;
  } else {
    if (el.radioGroupExisting) el.radioGroupExisting.checked = true;
  }

  el.groupingTargetConceptSelect.innerHTML = '<option value="">-- Loading concepts... --</option>';
  el.groupingModal.classList.add('open');

  try {
    const fetchUrl = sn ? `api/devices/${encodeURIComponent(sn)}/unified_fields` : 'api/overview';
    const res = await fetch(apiPath(fetchUrl));
    const data = await res.json();
    const groups = data.unified_fields || [];
    
    // Sort concepts by label
    groups.sort((a, b) => (a.label || a.concept_key).localeCompare(b.label || b.concept_key));

    el.groupingTargetConceptSelect.innerHTML = '<option value="">-- Choose an existing concept --</option>';
    groups.forEach(g => {
      if (isScaleFactorField(g)) return;
      const isCurrent = !isGenericOrStandalone && g.concept_key === cleanConceptKey;
      const opt = document.createElement('option');
      opt.value = g.concept_key;
      opt.dataset.label = g.label || g.concept_key;
      opt.dataset.sources = JSON.stringify((g.sources || []).map(s => s.field_key).filter(Boolean));
      opt.textContent = `${g.label || g.concept_key} (${g.concept_key})${isCurrent ? ' [Current]' : ''}`;
      if (isCurrent) opt.selected = true;
      el.groupingTargetConceptSelect.appendChild(opt);
    });
  } catch (err) {
    el.groupingTargetConceptSelect.innerHTML = '<option value="">Failed loading concepts</option>';
  }
}

function closeGroupingModal() {
  if (el.groupingModal) {
    el.groupingModal.classList.remove('open');
  }
  state.groupingModalData = null;
}

async function saveGroupingAction() {
  if (!state.groupingModalData) return;
  let { deviceSn, fieldKey } = state.groupingModalData;
  if (!deviceSn) {
    deviceSn = (state.activeDevice ? state.activeDevice.serial_number : '') || compareState.selectedDevice || '';
  }

  let targetConcept = null;
  let customLabel = null;
  let memberFieldKeys = [fieldKey];

  if (el.radioGroupExisting.checked) {
    targetConcept = el.groupingTargetConceptSelect.value;
    if (!targetConcept) {
      alert('Please select an existing concept from the dropdown, or choose "Create a new custom concept".');
      return;
    }
    const selectedOpt = el.groupingTargetConceptSelect.selectedOptions ? el.groupingTargetConceptSelect.selectedOptions[0] : null;
    if (selectedOpt) {
      if (selectedOpt.dataset.label) {
        customLabel = selectedOpt.dataset.label;
      }
      if (selectedOpt.dataset.sources) {
        try {
          const parsed = JSON.parse(selectedOpt.dataset.sources);
          if (Array.isArray(parsed)) {
            memberFieldKeys.push(...parsed);
          }
        } catch (e) {}
      }
    }
  } else if (el.radioGroupNew.checked) {
    targetConcept = el.groupingNewConceptKey.value.trim().toLowerCase().replace(/[\s-]+/g, '_');
    customLabel = el.groupingNewConceptLabel.value.trim();
    if (!targetConcept) {
      alert('Please enter a concept key (e.g. "pool_heater_power").');
      return;
    }
  } else if (el.radioGroupUngroup.checked) {
    targetConcept = null;
  }

  let transform = null;
  if (el.radioTransformNegate && el.radioTransformNegate.checked) {
    transform = 'negate';
  }

  try {
    el.btnSaveGroupingModal.disabled = true;
    el.btnSaveGroupingModal.textContent = 'Saving...';

    const res = await fetch(apiPath('api/grouping/override'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        device_sn: deviceSn,
        field_key: fieldKey,
        member_field_keys: memberFieldKeys,
        target_concept: targetConcept,
        custom_label: customLabel,
        transform: transform,
      }),
    });
    const data = await res.json();
    if (data.status === 'ok') {
      showToast(targetConcept ? `Grouped ${fieldKey} with ${targetConcept}` : `Ungrouped ${fieldKey}`);
      closeGroupingModal();
      await refreshAfterGroupingChange(deviceSn);
    } else {
      alert(`Error saving grouping: ${data.error || 'Unknown error'}`);
    }
  } catch (err) {
    alert(`Failed saving grouping: ${err}`);
  } finally {
    if (el.btnSaveGroupingModal) {
      el.btnSaveGroupingModal.disabled = false;
      el.btnSaveGroupingModal.textContent = 'Save Grouping';
    }
  }
}

async function syncSampleAction(fieldKeys, deviceSn, conceptKey, btnElement) {
  if (!fieldKeys || fieldKeys.length === 0) return;
  const originalHtml = btnElement ? btnElement.innerHTML : '';
  if (btnElement) {
    btnElement.disabled = true;
    btnElement.innerHTML = '⏳ Sampling...';
  }

  try {
    const res = await fetch(apiPath('api/compare/sync_sample'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        field_keys: fieldKeys,
        device_sn: deviceSn,
        concept_key: conceptKey,
      }),
    });
    const data = await res.json();
    if (data.status === 'ok') {
      const skewMsg = typeof data.skew_seconds === 'number'
        ? ` (Δt ${data.skew_seconds < 1 ? `${Math.round(data.skew_seconds * 1000)}ms` : `${data.skew_seconds.toFixed(2)}s`} skew)`
        : '';
      showToast(`⚡ Sampled ${fieldKeys.length} fields together${skewMsg}`);

      // If comparison row was returned, update comparison data cache
      if (data.comparison && compareState.data) {
        const rows = Array.isArray(compareState.data) ? compareState.data : (compareState.data.comparisons || []);
        const targetId = data.comparison.id || `${data.comparison.device_sn || ''}:${data.comparison.concept_key || ''}`;
        const idx = rows.findIndex(r => (r.id === targetId) || (r.concept_key === data.comparison.concept_key && r.device_sn === data.comparison.device_sn));
        if (idx >= 0) {
          rows[idx] = data.comparison;
        }
        if (compareState.activeTab !== 'suggestions') {
          renderCompareTableRows(rows);
        }
      }

      // If suggestions tab is active, update candidate source values in-place
      if (compareState.suggestions && compareState.suggestions.length > 0 && Array.isArray(data.sources)) {
        let suggestionUpdated = false;
        compareState.suggestions.forEach(s => {
          (s.sources || []).forEach(src => {
            const updated = data.sources.find(u => u.field_key === src.field_key);
            if (updated) {
              src.value = updated.value;
              src.raw_value = updated.raw_value;
              src.last_updated = updated.last_updated;
              suggestionUpdated = true;
            }
          });
        });
        if (suggestionUpdated && compareState.activeTab === 'suggestions') {
          renderCompareSuggestions(compareState.suggestions);
        }
      }

      // Also refresh main table active fields if open
      if (state.activeFields && Array.isArray(data.sources)) {
        data.sources.forEach(u => {
          const f = state.activeFields.find(af => af.key === u.field_key);
          if (f) {
            f.value = u.value;
            f.raw_value = u.raw_value;
            f.last_updated = u.last_updated;
          }
        });
        if (state.unifiedFields) {
          state.unifiedFields.forEach(g => {
            let matched = false;
            (g.sources || []).forEach(s => {
              const u = data.sources.find(src => src.field_key === s.field_key);
              if (u) {
                s.value = u.value;
                s.raw_value = u.raw_value;
                s.last_updated = u.last_updated;
                matched = true;
              }
            });
            if (matched) {
              const activeKey = state.preferredSources[g.id] || g.active_source_key;
              const activeSrc = (g.sources || []).find(s => s.field_key === activeKey);
              if (activeSrc) {
                g.latest_value = activeSrc.value;
                g.latest_updated = activeSrc.last_updated;
              }
            }
          });
        }
        renderFieldTable();
      }
    } else {
      alert(`Failed to sync sample: ${data.error || 'Unknown error'}`);
    }
  } catch (err) {
    alert(`Sync sample failed: ${err}`);
  } finally {
    if (btnElement) {
      btnElement.disabled = false;
      btnElement.innerHTML = originalHtml;
    }
  }
}

async function ungroupFieldAction(deviceSnOrKey, fieldKeyOrSn) {
  let sn = '';
  let fieldKey = '';
  if (deviceSnOrKey && fieldKeyOrSn) {
    if (deviceSnOrKey.includes('.') || deviceSnOrKey.startsWith('inverter') || deviceSnOrKey.startsWith('battery') || deviceSnOrKey.startsWith('rebus')) {
      fieldKey = deviceSnOrKey;
      sn = fieldKeyOrSn;
    } else {
      sn = deviceSnOrKey;
      fieldKey = fieldKeyOrSn;
    }
  } else {
    fieldKey = deviceSnOrKey || fieldKeyOrSn;
    sn = (state.activeDevice ? state.activeDevice.serial_number : '') || compareState.selectedDevice || '';
  }
  if (!fieldKey) {
    alert('Error: field_key is required to ungroup field');
    return;
  }
  try {
    const res = await fetch(apiPath('api/grouping/override'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        device_sn: sn,
        field_key: fieldKey,
        target_concept: null,
      }),
    });
    const data = await res.json();
    if (data.status === 'ok') {
      showToast(`Removed ${fieldKey} from group`);
      await refreshAfterGroupingChange(sn);
    } else {
      alert(`Error ungrouping field: ${data.error || 'Unknown error'}`);
    }
  } catch (err) {
    alert(`Failed ungrouping field: ${err}`);
  }
}

async function resetGroupingAction(deviceSn, fieldKey) {
  const sn = deviceSn || (state.activeDevice ? state.activeDevice.serial_number : '') || compareState.selectedDevice || '';
  if (!fieldKey) {
    alert('Error: field_key is required to reset grouping');
    return;
  }
  try {
    const res = await fetch(apiPath('api/grouping/reset'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        device_sn: sn,
        field_key: fieldKey,
      }),
    });
    const data = await res.json();
    if (data.status === 'ok') {
      showToast(`Reset ${fieldKey} to default grouping`);
      await refreshAfterGroupingChange(sn);
    } else {
      alert(`Error resetting grouping: ${data.error || 'Unknown error'}`);
    }
  } catch (err) {
    alert(`Failed resetting grouping: ${err}`);
  }
}

async function ungroupAllAction(deviceSn, conceptKey) {
  const sn = deviceSn || (state.activeDevice ? state.activeDevice.serial_number : '') || compareState.selectedDevice || '';
  if (!conceptKey) {
    alert('Error: concept_key is required to ungroup all');
    return;
  }
  if (!confirm(`Are you sure you want to ungroup all sources in '${conceptKey}'? Each register will become an independent standalone field.`)) {
    return;
  }
  try {
    const res = await fetch(apiPath('api/grouping/ungroup_all'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        device_sn: sn,
        concept_key: conceptKey,
      }),
    });
    const data = await res.json();
    if (data.status === 'ok') {
      showToast(`Ungrouped all sources in ${conceptKey}`);
      await refreshAfterGroupingChange(sn);
    } else {
      alert(`Error ungrouping concept: ${data.error || 'Unknown error'}`);
    }
  } catch (err) {
    alert(`Failed ungrouping concept: ${err}`);
  }
}

async function refreshAfterGroupingChange(deviceSn) {
  if (state.activeDevice && state.activeDevice.serial_number === deviceSn) {
    await selectDevice(deviceSn);
  }
  if (el.compareModal && el.compareModal.classList.contains('open')) {
    await fetchAndRenderCompare();
  }
}

// Reset All Grouping Overrides
if (el.btnResetAllGroupings) {
  el.btnResetAllGroupings.addEventListener('click', async () => {
    if (!confirm('Clear all custom field grouping and polarity overrides and revert to automatic defaults?')) {
      return;
    }
    try {
      const res = await fetch(apiPath('api/grouping/reset_defaults'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      const data = await res.json();
      if (data.success) {
        showToast('Grouping overrides reset to default!');
        if (state.activeDevice) {
          await selectDevice(state.activeDevice.serial_number);
        }
        if (el.compareModal && el.compareModal.classList.contains('open')) {
          await fetchAndRenderCompare();
        }
      } else {
        alert(`Error resetting groupings: ${data.error || 'Unknown error'}`);
      }
    } catch (err) {
      alert(`Failed resetting groupings: ${err}`);
    }
  });
}

// Export Custom Mappings Logic
let currentExportFormat = 'generalized';
let currentExportYaml = '';
let currentExportFilename = 'custom_groupings.yaml';

async function openExportModal(initialFormat = 'generalized') {
  if (!el.exportMappingsModal) return;
  currentExportFormat = initialFormat;
  updateExportFormatUI();
  el.exportMappingsModal.classList.add('open');
  await fetchExportYaml();
}

function closeExportModal() {
  if (el.exportMappingsModal) {
    el.exportMappingsModal.classList.remove('open');
  }
}

function updateExportFormatUI() {
  if (currentExportFormat === 'generalized') {
    if (el.btnFormatGeneralized) el.btnFormatGeneralized.classList.add('active');
    if (el.btnFormatTelemetry) el.btnFormatTelemetry.classList.remove('active');
    if (el.exportTargetFilename) el.exportTargetFilename.textContent = 'custom_groupings.yaml';
    if (el.exportTargetLocation) el.exportTargetLocation.textContent = 'Place in /data/custom_groupings.yaml or config/custom_groupings.yaml';
    currentExportFilename = 'custom_groupings.yaml';
  } else {
    if (el.btnFormatGeneralized) el.btnFormatGeneralized.classList.remove('active');
    if (el.btnFormatTelemetry) el.btnFormatTelemetry.classList.add('active');
    if (el.exportTargetFilename) el.exportTargetFilename.textContent = 'groupings.yaml';
    if (el.exportTargetLocation) el.exportTargetLocation.textContent = 'Place in pwrcell/data/groupings.yaml or use to submit a PR';
    currentExportFilename = 'groupings.yaml';
  }
}

async function fetchExportYaml() {
  if (!el.exportYamlCode) return;
  el.exportYamlCode.textContent = '# Generating export YAML...';
  try {
    const res = await fetch(apiPath(`api/grouping/export?format=${encodeURIComponent(currentExportFormat)}`));
    const data = await res.json();
    if (data.status === 'ok') {
      currentExportYaml = data.yaml || '';
      el.exportYamlCode.textContent = currentExportYaml || '# No custom groupings defined yet.';
      currentExportFilename = data.filename || currentExportFilename;
      if (el.exportTargetFilename) el.exportTargetFilename.textContent = currentExportFilename;
    } else {
      el.exportYamlCode.textContent = `# Error generating export: ${data.error || 'Unknown error'}`;
    }
  } catch (err) {
    el.exportYamlCode.textContent = `# Failed to load export: ${err}`;
  }
}

// Grouped Registers & Telemetry Compare Modal
let compareTimer = null;
let isFetchingCompare = false;
const compareState = {
  activeTab: 'discrepancies',
  selectedDevice: '',
  searchQuery: '',
  data: null,
  suggestions: [],
  suggestionConfidence: 'high',
  visibleSuggestions: [],
  hasInitializedTab: false,
  expandedRows: new Set(),
  expandedSuggestions: new Set(),
};

async function fetchAndRenderCompare(forceSuggestions = false) {
  if (isFetchingCompare) return;
  isFetchingCompare = true;
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

    // Fetch and sync grouping suggestions only when explicitly requested or on initial load
    const shouldFetchSuggestions = forceSuggestions || (!compareState.suggestions || compareState.suggestions.length === 0) || !compareState.hasInitializedTab;
    if (shouldFetchSuggestions) {
      try {
        const suggRes = await fetch(apiPath('api/grouping/suggestions'));
        const suggData = await suggRes.json();
        compareState.suggestions = suggData.suggestions || [];
        const suggCount = suggData.count !== undefined ? suggData.count : compareState.suggestions.length;
        if (el.cntCmpSuggestions) el.cntCmpSuggestions.textContent = suggCount;
        if (el.cntHeaderSuggestions) el.cntHeaderSuggestions.textContent = suggCount;
        if (el.btnOpenSuggestions) {
          el.btnOpenSuggestions.style.display = suggCount > 0 ? 'inline-flex' : 'none';
        }
      } catch (e) {
        console.warn('Failed to fetch grouping suggestions:', e);
      }
    }

    // Default tab on first load
    if (!compareState.hasInitializedTab) {
      if (discrepantCount > 0) {
        compareState.activeTab = 'discrepancies';
      } else if (compareState.suggestions && compareState.suggestions.length > 0) {
        compareState.activeTab = 'suggestions';
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
      (compareState.suggestions || []).forEach(s => {
        if (s.device_sn && !devicesMap.has(s.device_sn)) {
          devicesMap.set(s.device_sn, s.device_name || s.device_type);
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

    if (compareState.activeTab === 'suggestions') {
      renderCompareSuggestions(compareState.suggestions);
    } else {
      renderCompareTableRows(rows);
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
    if (el.compareTableBody) {
      el.compareTableBody.innerHTML = `<tr><td colspan="3" class="empty-state">Error fetching comparisons: ${err}</td></tr>`;
    }
  } finally {
    isFetchingCompare = false;
  }
}

function updateCompareTabActiveStyles() {
  const tabs = [
    { btn: el.tabCmpDiscrepancies, name: 'discrepancies' },
    { btn: el.tabCmpSuggestions, name: 'suggestions' },
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

  if (compareState.activeTab === 'suggestions') {
    if (el.compareTableContainer) el.compareTableContainer.style.display = 'none';
    if (el.compareSuggestionsContainer) el.compareSuggestionsContainer.style.display = 'block';
  } else {
    if (el.compareTableContainer) el.compareTableContainer.style.display = 'block';
    if (el.compareSuggestionsContainer) el.compareSuggestionsContainer.style.display = 'none';
  }
}

function renderCompareSuggestions(suggestions) {
  if (!el.suggestionsList) return;
  const devFilter = (compareState.selectedDevice || '').trim().toUpperCase();
  const query = (compareState.searchQuery || '').trim().toLowerCase();
  const confFilter = (compareState.suggestionConfidence || 'high').toLowerCase();

  const filtered = (suggestions || []).filter(s => {
    if (confFilter === 'high' && s.confidence_label !== 'HIGH' && (s.confidence || 0) < 0.85) {
      return false;
    }
    if (devFilter) {
      const sSn = (s.device_sn || '').toUpperCase();
      const sDev = (s.device_type || '').toUpperCase();
      if (sSn !== devFilter && sDev !== devFilter) return false;
    }
    if (query) {
      const matchLabel = (s.suggested_label || '').toLowerCase().includes(query);
      const matchKey = (s.suggested_concept_key || '').toLowerCase().includes(query);
      const matchDev = (s.device_name || s.device_type || '').toLowerCase().includes(query);
      const matchSrc = (s.sources || []).some(src =>
        (src.name || '').toLowerCase().includes(query) ||
        (src.field_key || '').toLowerCase().includes(query) ||
        (src.label || '').toLowerCase().includes(query)
      );
      if (!matchLabel && !matchKey && !matchDev && !matchSrc) return false;
    }
    return true;
  });

  // Store visible suggestions on compareState so batch actions know what to approve/dismiss
  compareState.visibleSuggestions = filtered;

  if (el.cntBatchApprove) el.cntBatchApprove.textContent = filtered.length;
  if (el.btnBatchApproveVisible) el.btnBatchApproveVisible.disabled = filtered.length === 0;
  if (el.btnBatchDismissVisible) el.btnBatchDismissVisible.disabled = filtered.length === 0;

  if (filtered.length === 0) {
    el.suggestionsList.innerHTML = `
      <div class="empty-state" style="padding: 30px; text-align: center;">
        <span style="font-size: 28px; display: block; margin-bottom: 8px;">✨</span>
        <strong>No Grouping Suggestions Found</strong>
        <p class="text-muted" style="margin-top: 4px; font-size: 13px;">
          ${confFilter === 'high' ? 'No high-confidence (≥85%) suggestions found. Switch to "All Candidates" to view lower confidence pairings.' : 'All compatible telemetry streams with high correlation are already grouped or dismissed.'}
        </p>
      </div>
    `;
    return;
  }

  // Group by device
  const deviceGroups = {};
  filtered.forEach(s => {
    const key = s.device_sn || 'UNKNOWN';
    if (!deviceGroups[key]) {
      deviceGroups[key] = {
        name: s.device_name || s.device_type,
        device_sn: s.device_sn,
        items: [],
      };
    }
    deviceGroups[key].items.push(s);
  });

  el.suggestionsList.innerHTML = Object.values(deviceGroups).map(dg => {
    const cardsHtml = dg.items.map(s => {
      const sId = s.id;
      const isExpanded = compareState.expandedSuggestions.has(sId);
      const confClass = s.confidence_label === 'HIGH' ? 'high' : 'medium';
      const confPct = Math.round((s.confidence || 0) * 100);

      const sourcesHtml = (s.sources || []).map(src => {
        let srcClass = 'src-sunspec';
        if (src.source_type === 'MQTT') srcClass = 'src-mqtt';
        else if (src.model_id && src.model_id >= 64200) srcClass = 'src-vendor';

        const valDisplay = src.value !== null && src.value !== undefined
          ? `${formatFieldValue(src.value)} ${escapeHtml(src.units || s.units || '')}`
          : '<span class="text-muted">--</span>';

        const rawDisplay = (src.raw_value !== null && src.raw_value !== undefined && src.raw_value !== src.value)
          ? `<span class="compare-source-raw" title="Raw unscaled value">raw: ${formatFieldValue(src.raw_value)}</span>`
          : '';

        if (isExpanded) {
          return `
            <div class="compare-source-card is-expanded">
              <div class="compare-source-card-main">
                <div class="compare-source-left">
                  <span class="source-chip ${srcClass}">${escapeHtml(src.source_id || src.source_type)}</span>
                  <div class="compare-source-meta expanded">
                    <span class="compare-source-name" title="${escapeHtml(src.label || src.name)}">${escapeHtml(src.label || src.name)}</span>
                    <div class="compare-source-key-row">
                      <span class="compare-source-key selectable" title="${escapeHtml(src.field_key)}">${escapeHtml(src.field_key)}</span>
                      <button class="btn-copy-key" data-copy-key="${escapeHtml(src.field_key)}" title="Copy register key">📋</button>
                    </div>
                  </div>
                </div>
                <div class="compare-source-right">
                  <div class="compare-source-value-group">
                    <span class="compare-source-value">${valDisplay}</span>
                    ${rawDisplay}
                    ${src.last_updated ? `<span class="compare-source-time" title="Read at ${formatTimestamp(src.last_updated)}">🕒 ${formatTimestamp(src.last_updated)}</span>` : ''}
                  </div>
                </div>
              </div>
              <div class="compare-source-expanded-meta">
                <span class="expanded-meta-item"><strong>Source Type:</strong> ${escapeHtml(src.source_type || 'SUNSPEC')}</span>
                ${src.model_id ? `<span class="expanded-meta-item"><strong>Model ID:</strong> ${escapeHtml(String(src.model_id))}</span>` : ''}
                ${src.units || s.units ? `<span class="expanded-meta-item"><strong>Units:</strong> ${escapeHtml(src.units || s.units)}</span>` : ''}
                ${src.raw_value !== null && src.raw_value !== undefined ? `<span class="expanded-meta-item"><strong>Raw Reg Value:</strong> ${formatFieldValue(src.raw_value)}</span>` : ''}
                ${src.last_updated ? `<span class="expanded-meta-item"><strong>Last Updated:</strong> ${formatTimestamp(src.last_updated)} (${formatDataAge(src.last_updated)})</span>` : ''}
                <span class="expanded-meta-item"><strong>Device:</strong> ${escapeHtml(dg.name || s.device_sn || '')}</span>
              </div>
            </div>
          `;
        }

        return `
          <div class="compare-source-card">
            <div class="compare-source-left">
              <span class="source-chip ${srcClass}">${escapeHtml(src.source_id || src.source_type)}</span>
              <div class="compare-source-meta">
                <span class="compare-source-name" title="${escapeHtml(src.label || src.name)}">${escapeHtml(src.label || src.name)}</span>
                <span class="compare-source-key" title="${escapeHtml(src.field_key)}">${escapeHtml(src.field_key)}</span>
              </div>
            </div>
            <div class="compare-source-right">
              <div class="compare-source-value-group">
                <span class="compare-source-value">${valDisplay}</span>
                ${rawDisplay}
                ${src.last_updated ? `<span class="compare-source-time" title="Read at ${formatTimestamp(src.last_updated)}">🕒 ${formatTimestamp(src.last_updated)}</span>` : ''}
              </div>
            </div>
          </div>
        `;
      }).join('');

      const reasonsHtml = (s.reasons || []).map(r => `
        <div class="suggestion-reason-item">
          <span>✔</span>
          <span>${escapeHtml(r)}</span>
        </div>
      `).join('');

      const fieldKeysJson = escapeHtml(JSON.stringify((s.sources || []).map(src => src.field_key)));
      const isInverted = s.inverted_pair || s.suggested_transform === 'negate';
      const polarityBadge = isInverted ? `
        <span class="suggestion-polarity-badge" title="Registers report opposite signs. Polarity negation is recommended.">
          ⚡ Opposite Polarity (Needs Negation)
        </span>
      ` : '';

      return `
        <div class="suggestion-card ${isExpanded ? 'is-expanded' : ''}" data-suggestion-id="${escapeHtml(s.id)}">
          <div class="suggestion-card-header">
            <div class="suggestion-title-group">
              <span class="suggestion-concept-badge">💡 ${escapeHtml(s.suggested_label)} (${escapeHtml(s.suggested_concept_key)})</span>
              <span class="suggestion-confidence-badge ${confClass}">${confPct}% ${escapeHtml(s.confidence_label)} Confidence</span>
              ${polarityBadge}
              <button class="btn-toggle-suggestion-expand" data-id="${escapeHtml(s.id)}" title="Click to ${isExpanded ? 'collapse' : 'expand'} full field details">
                <span>${isExpanded ? '▲' : '▼'}</span>
                <span>${isExpanded ? 'Collapse' : 'Details'}</span>
              </button>
            </div>
            <div class="suggestion-actions">
              <button class="btn-sync-sample-suggestion"
                      data-action="sync-sample-suggestion"
                      data-id="${escapeHtml(s.id)}"
                      data-sn="${escapeHtml(s.device_sn)}"
                      data-field-keys="${fieldKeysJson}"
                      title="Read both candidate fields together right now to compare their values at a closer point in time">
                ⚡ Sync Sample
              </button>
              <button class="btn-approve-suggestion"
                      data-action="approve-suggestion"
                      data-id="${escapeHtml(s.id)}"
                      data-sn="${escapeHtml(s.device_sn)}"
                      data-concept="${escapeHtml(s.suggested_concept_key)}"
                      data-label="${escapeHtml(s.suggested_label)}"
                      data-field-keys="${fieldKeysJson}"
                      data-inverted="${isInverted ? 'true' : 'false'}"
                      data-suggested-transform="${escapeHtml(s.suggested_transform || '')}"
                      data-pos-key="${escapeHtml(s.positive_field_key || '')}"
                      data-neg-key="${escapeHtml(s.negative_field_key || '')}"
                      title="Merge these fields into a single unified telemetry point">
                ✅ Approve &amp; Merge
              </button>
              <button class="btn-customize-suggestion"
                      data-action="customize-suggestion"
                      data-id="${escapeHtml(s.id)}"
                      data-sn="${escapeHtml(s.device_sn)}"
                      data-concept="${escapeHtml(s.suggested_concept_key)}"
                      data-label="${escapeHtml(s.suggested_label)}"
                      data-field-keys="${fieldKeysJson}"
                      data-inverted="${isInverted ? 'true' : 'false'}"
                      data-suggested-transform="${escapeHtml(s.suggested_transform || '')}"
                      title="Open grouping modal to customize concept key or label before saving">
                ✏️ Customize
              </button>
              <button class="btn-dismiss-suggestion"
                      data-action="dismiss-suggestion"
                      data-id="${escapeHtml(s.id)}"
                      title="Dismiss this suggestion">
                ✕ Dismiss
              </button>
            </div>
          </div>

          <div class="compare-sources-list">
            ${sourcesHtml}
          </div>

          <div class="suggestion-reasons-list">
            ${reasonsHtml}
          </div>
        </div>
      `;
    }).join('');

    const dgItemsJson = escapeHtml(JSON.stringify(dg.items.map(s => ({
      device_sn: s.device_sn,
      field_keys: (s.sources || []).map(src => src.field_key),
      target_concept: s.suggested_concept_key,
      label: s.suggested_label,
      suggestion_id: s.id,
      transform: s.suggested_transform,
      positive_field_key: s.positive_field_key || null,
      negative_field_key: s.negative_field_key || null,
      negate_field_key: s.negative_field_key || null,
      polarity_convention: 'positive',
    }))));

    return `
      <div class="device-suggestions-group">
        <div class="device-suggestions-header">
          <div class="device-suggestions-title">
            <span class="compare-device-pill">${escapeHtml(dg.name)}</span>
            <span class="text-muted" style="font-size: 12px;">${dg.items.length} suggestion${dg.items.length === 1 ? '' : 's'}</span>
          </div>
          <div class="device-suggestions-actions">
            <button class="btn-approve-suggestion btn-sm"
                    data-action="batch-approve-device"
                    data-sn="${escapeHtml(dg.device_sn)}"
                    data-items="${dgItemsJson}"
                    title="Approve all suggestions for this device">
              ✅ Approve All for Device (${dg.items.length})
            </button>
          </div>
        </div>
        <div class="device-suggestions-body">
          ${cardsHtml}
        </div>
      </div>
    `;
  }).join('');
}

function renderCompareTableRows(rows) {
  if (!el.compareTableBody) return;

  const tab = compareState.activeTab;
  const devFilter = compareState.selectedDevice.trim().toUpperCase();
  const query = compareState.searchQuery.trim().toLowerCase();

  const filtered = rows.filter(r => {
    // Exclude scale factor registers from comparison & merging rows
    if (r.is_scale_factor || isScaleFactorField(r)) return false;

    // 1. Tab filter
    if (tab === 'discrepancies') {
      const isExplicit = r.is_explicitly_grouped || (
        ((r.sources && r.sources.length > 1) || (r.source_count && r.source_count > 1) || (r.mqtt_value !== null && r.mqtt_value !== undefined && r.modbus_value !== null && r.modbus_value !== undefined)) &&
        !((r.id || '').includes('.standalone.') || (r.concept_key || '').startsWith('standalone_') || (r.label || '').includes('(Ungrouped)'))
      );
      if (!isExplicit) return false;
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
    const rowId = r.id || `${r.device_sn || ''}:${r.concept_key || r.mapping_id || ''}`;
    const isExpanded = compareState.expandedRows.has(rowId);

    tr.className = `compare-row ${isExpanded ? 'is-expanded' : ''} ${r.is_discrepant ? 'has-divergence' : ''}`;
    tr.dataset.rowId = rowId;

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

    const validTimestamps = (r.sources || []).map(s => s.last_updated).filter(t => typeof t === 'number' && t > 0);
    if (validTimestamps.length > 1) {
      const minT = Math.min(...validTimestamps);
      const maxT = Math.max(...validTimestamps);
      const deltaSec = maxT - minT;
      if (deltaSec >= 1.0) {
        agreementHtml += `<div class="compare-skew-note"><span class="badge-skew-note" title="Difference in sample read times between sources">⏱️ Δt ${deltaSec < 60 ? `${deltaSec.toFixed(1)}s` : `${Math.round(deltaSec / 60)}m`} poll skew</span></div>`;
      }
    }

    // Device & Concept column content
    const sources = r.sources || [];
    const fieldKeysJson = escapeHtml(JSON.stringify(sources.map(s => s.field_key)));
    const syncPairBtn = sources.length > 1
      ? `<div class="compare-sync-wrap"><button class="btn-sync-sample-pair" data-action="sync-sample-pair" data-sn="${escapeHtml(r.device_sn || '')}" data-concept-key="${escapeHtml(r.concept_key || '')}" data-field-keys="${fieldKeysJson}" title="Sample all sources in this comparison together at the exact same moment to eliminate polling skew"><span class="sync-icon">⚡</span> <span>Sync Sample</span></button></div>`
      : '';
    if (syncPairBtn) {
      agreementHtml += syncPairBtn;
    }
    const devBadge = r.device_name ? `<span class="compare-device-pill">${escapeHtml(r.device_name)}</span>` : '';
    const ungroupAllBtn = (sources.length > 1)
      ? `<button class="btn-group-action btn-ungroup-action" data-action="ungroup-all" data-sn="${escapeHtml(r.device_sn || '')}" data-concept-key="${escapeHtml(r.concept_key)}" style="margin-top: 5px; width: fit-content;" title="Ungroup all sources in this concept into standalone fields">✂️ Ungroup All</button>`
      : '';
    const expandToggleBtn = `<button class="btn-expand-compare" data-action="toggle-expand" data-row-id="${escapeHtml(rowId)}" title="Click to ${isExpanded ? 'collapse' : 'expand'} full details">
      <span>${isExpanded ? '▼' : '▶'}</span>
      <span>${isExpanded ? 'Collapse' : 'Details'}</span>
    </button>`;

    const conceptCol = `
      <div class="field-cell-main">
        ${devBadge}
        <strong>${escapeHtml(r.label || r.concept_key)}</strong>
        <span class="field-key">${escapeHtml(r.concept_key || r.mapping_id || '')}</span>
        ${ungroupAllBtn}
        ${expandToggleBtn}
      </div>
    `;

    // Sources column content
    let sourcesCol = '';
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

        const sTime = formatTimestamp(s.last_updated);
        const sTimeHtml = sTime ? `<span class="compare-source-time" title="Read at ${sTime}">🕒 ${sTime}</span>` : '';

        const tfDisplay = s.transform
          ? `<span class="compare-source-tag transform" title="Transform: ${escapeHtml(s.transform)}">⚙ ${escapeHtml(s.transform)}</span>`
          : '';

        const optDisplay = s.is_optimal
          ? `<span class="compare-source-tag optimal" title="Selected optimal source in polling plan">★ Optimal</span>`
          : '';

        const pinDisplay = s.is_pinned
          ? `<span class="compare-source-tag pinned" title="Manually pinned by user">📌 Pinned</span>`
          : '';

        const customDisplay = s.is_custom_override
          ? `<span class="badge-custom-override" title="Custom grouping override active">Custom</span>`
          : '';

        const actionButtons = (!s.is_scale_factor && !isScaleFactorField(s)) ? `
          <div class="compare-source-actions">
            ${sources.length > 1 ? `<button class="btn-group-action btn-ungroup-action" data-action="ungroup" data-sn="${escapeHtml(s.device_sn || r.device_sn || '')}" data-field-key="${escapeHtml(s.field_key)}" title="Ungroup this field from '${escapeHtml(r.label || r.concept_key)}'">✂️ Ungroup</button>` : ''}
            <button class="btn-group-action btn-group-with-action" data-action="group-with" data-sn="${escapeHtml(s.device_sn || r.device_sn || '')}" data-field-key="${escapeHtml(s.field_key)}" data-concept-key="${escapeHtml(r.concept_key)}" data-concept-label="${escapeHtml(r.label || r.concept_key)}" title="Group this field with an existing or new concept...">🔗 Group...</button>
            ${s.is_custom_override ? `<button class="btn-group-action btn-reset-action" data-action="reset-group" data-sn="${escapeHtml(s.device_sn || r.device_sn || '')}" data-field-key="${escapeHtml(s.field_key)}" title="Reset to default automatic grouping">↩️ Reset</button>` : ''}
          </div>
        ` : '';

        if (isExpanded) {
          return `
            <div class="compare-source-card is-expanded ${isDivergent ? 'is-divergent' : ''}">
              <div class="compare-source-card-main">
                <div class="compare-source-left">
                  <span class="source-chip ${srcChipClass}">${escapeHtml(s.source_id || 'SRC')}</span>
                  <div class="compare-source-meta expanded">
                    <span class="compare-source-name" title="${escapeHtml(s.label || s.name || '')}">${escapeHtml(s.label || s.name || '')}</span>
                    <div class="compare-source-key-row">
                      <span class="compare-source-key selectable" title="Full register key: ${escapeHtml(s.field_key || '')}">${escapeHtml(s.field_key || '')}</span>
                      <button class="btn-copy-key" data-copy-key="${escapeHtml(s.field_key || '')}" title="Copy register key">📋</button>
                    </div>
                  </div>
                </div>
                <div class="compare-source-right">
                  <div class="compare-source-value-group">
                    <span class="compare-source-value ${isDivergent ? 'val-divergent' : ''}">${valDisplay}</span>
                    ${rawDisplay}
                    ${sTimeHtml}
                  </div>
                  ${tfDisplay}
                  ${optDisplay}
                  ${pinDisplay}
                  ${customDisplay}
                  ${actionButtons}
                </div>
              </div>
              <div class="compare-source-expanded-meta">
                <span class="expanded-meta-item"><strong>Source:</strong> ${escapeHtml(s.source_type || 'SUNSPEC')}</span>
                ${s.model_id ? `<span class="expanded-meta-item"><strong>SunSpec Model:</strong> ${escapeHtml(String(s.model_id))}${s.model_name ? ` (${escapeHtml(s.model_name)})` : ''}</span>` : ''}
                ${s.units || r.unit ? `<span class="expanded-meta-item"><strong>Units:</strong> ${escapeHtml(s.units || r.unit)}</span>` : ''}
                ${s.raw_value !== null && s.raw_value !== undefined ? `<span class="expanded-meta-item"><strong>Raw Reg Value:</strong> ${formatFieldValue(s.raw_value)}</span>` : ''}
                ${s.scale_factor ? `<span class="expanded-meta-item"><strong>Scale Factor:</strong> ${escapeHtml(s.scale_factor)}</span>` : ''}
                ${s.point_type ? `<span class="expanded-meta-item"><strong>Point Type:</strong> ${escapeHtml(s.point_type)}</span>` : ''}
                ${s.offset !== null && s.offset !== undefined ? `<span class="expanded-meta-item"><strong>Offset:</strong> ${s.offset}</span>` : ''}
                ${s.transform ? `<span class="expanded-meta-item"><strong>Transform:</strong> ${escapeHtml(s.transform)}</span>` : ''}
                ${s.last_updated ? `<span class="expanded-meta-item"><strong>Last Updated:</strong> ${formatTimestamp(s.last_updated)} (${formatDataAge(s.last_updated)})</span>` : ''}
                ${s.device_sn ? `<span class="expanded-meta-item"><strong>Device SN:</strong> ${escapeHtml(s.device_sn)}</span>` : ''}
              </div>
            </div>
          `;
        }

        return `
          <div class="compare-source-card ${isDivergent ? 'is-divergent' : ''}">
            <div class="compare-source-left">
              <span class="source-chip ${srcChipClass}">${escapeHtml(s.source_id || 'SRC')}</span>
              <div class="compare-source-meta">
                <span class="compare-source-name" title="${escapeHtml(s.label || s.name || '')}">${escapeHtml(s.label || s.name || '')}</span>
                <span class="compare-source-key" title="${escapeHtml(s.field_key || '')}">${escapeHtml(s.field_key || '')}</span>
              </div>
            </div>
            <div class="compare-source-right">
              <div class="compare-source-value-group">
                <span class="compare-source-value ${isDivergent ? 'val-divergent' : ''}">${valDisplay}</span>
                ${rawDisplay}
                ${sTimeHtml}
              </div>
              ${tfDisplay}
              ${optDisplay}
              ${pinDisplay}
              ${customDisplay}
              ${actionButtons}
            </div>
          </div>
        `;
      }).join('');

      let discrepancyCard = '';
      if (isExpanded && r.is_discrepant) {
        discrepancyCard = `
          <div class="compare-expanded-discrepancy-card">
            <div class="discrepancy-header">
              <span class="warning-badge-icon">⚠️</span>
              <span><strong>${escapeHtml(r.status_label || r.status || 'Divergent')}:</strong> ${escapeHtml(r.discrepancy_reason || 'Values diverge between sources')}</span>
            </div>
            ${(r.delta !== null && r.delta !== undefined) ? `
              <div class="discrepancy-metrics">
                <span class="disc-metric"><strong>Δ Difference:</strong> ${formatFieldValue(r.delta)} ${escapeHtml(r.unit || '')}</span>
                ${r.match_pct !== null && r.match_pct !== undefined ? `<span class="disc-metric"><strong>Agreement:</strong> ${r.match_pct}% match</span>` : ''}
              </div>
            ` : ''}
          </div>
        `;
      }

      sourcesCol = `<div class="compare-sources-list">${discrepancyCard}${cardsHtml}</div>`;
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
          <div class="compare-source-card ${isExpanded ? 'is-expanded' : ''}">
            <div class="compare-source-card-main">
              <div class="compare-source-left">
                <span class="source-chip src-mqtt">MQTT</span>
                <div class="compare-source-meta ${isExpanded ? 'expanded' : ''}">
                  <span class="compare-source-key ${isExpanded ? 'selectable' : ''}">${escapeHtml(r.mqtt_key || 'MQTT Push')}</span>
                </div>
              </div>
              <div class="compare-source-right">
                <span class="compare-source-value">${mqttDisplay}</span>
              </div>
            </div>
          </div>
          <div class="compare-source-card ${isExpanded ? 'is-expanded' : ''}">
            <div class="compare-source-card-main">
              <div class="compare-source-left">
                <span class="source-chip src-sunspec">MODBUS</span>
                <div class="compare-source-meta ${isExpanded ? 'expanded' : ''}">
                  <span class="compare-source-name">${escapeHtml(r.modbus_label || '')}</span>
                  <span class="compare-source-key ${isExpanded ? 'selectable' : ''}">${escapeHtml(r.modbus_key || '')}</span>
                </div>
              </div>
              <div class="compare-source-right">
                <span class="compare-source-value">${mbDisplay}</span>
              </div>
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

function openCompareModal(initialTab = null) {
  el.compareModal.classList.add('open');
  if (initialTab) {
    compareState.activeTab = initialTab;
    compareState.hasInitializedTab = true;
    updateCompareTabActiveStyles();
  } else {
    compareState.hasInitializedTab = false;
  }
  fetchAndRenderCompare(true);
  if (compareTimer) clearInterval(compareTimer);
  compareTimer = setInterval(() => {
    // Only refresh telemetry comparison table on background timer; avoid re-rendering suggestions view
    if (compareState.activeTab !== 'suggestions') {
      fetchAndRenderCompare(false);
    }
  }, 5000);
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

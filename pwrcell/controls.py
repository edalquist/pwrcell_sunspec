"""Controls Dispatcher for Generac PWRcell.

Dispatches writable commands (e.g., system mode, battery reserves, grid reconnect timers)
safely to the serialized Modbus worker and updates the unified state store.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional, Union

from .catalog import (
    MODEL_INVERTER_STATUS,
    MODEL_REBUS_DIR,
    ModelCatalog,
    get_catalog,
)
from .modbus import SerializedModbusClient
from .state import StateStore

logger = logging.getLogger(__name__)

# Canonical SunSpec Model 64200 SysMd integer-to-name map (note: 0 is SAFETY_SHUTDOWN, unlike MQTT proto where 0 is UNKNOWN and 16 is SAFETY_SHUTDOWN)
SUNSPEC_SYS_MD_NAMES: Dict[int, str] = {
    0: "SAFETY_SHUTDOWN",
    1: "GRID_TIE",
    2: "SELF_SUPPLY",
    3: "CLEAN_BACKUP",
    4: "PRIORITY_BACKUP",
    5: "REMOTE_ARBITRAGE",
    6: "SELL",
}

# System operating mode mapping (includes SunSpec XML symbol aliases)
OPERATING_MODES: Dict[str, int] = {
    "SAFETY_SHUTDOWN": 0,
    "GRID_TIE": 1,
    "GRID_CONNECT": 1,
    "SELF_SUPPLY": 2,
    "CLEAN_BACKUP": 3,
    "PRIORITY_BACKUP": 4,
    "REMOTE_ARBITRAGE": 5,
    "ARBITRAGE": 5,
    "SELL": 6,
    "FULL_EXPORT": 6,
}


class ControlDispatcher:
    """Manages writable operations on Generac PWRcell devices."""

    def __init__(
        self,
        modbus_client: Optional[SerializedModbusClient],
        state_store: StateStore,
        catalog: Optional[ModelCatalog] = None,
    ):
        self.modbus_client = modbus_client
        self.state_store = state_store
        self.catalog = catalog or get_catalog()

    def set_system_mode(self, mode: Union[str, int]) -> int:
        """Change system operating mode (e.g., 'CLEAN_BACKUP', 'SELF_SUPPLY', 'GRID_TIE')."""
        rebus_dir_model = self.catalog.get_model_by_name("REbus_dir") if self.catalog else None
        inv_status_model = self.catalog.get_model_by_name("inverter_status") if self.catalog else None
        rebus_dir_id = rebus_dir_model.model_id if rebus_dir_model else MODEL_REBUS_DIR
        inv_status_id = inv_status_model.model_id if inv_status_model else MODEL_INVERTER_STATUS

        point_def = self.catalog.get_point(rebus_dir_id, "SysMd") or self.catalog.get_point(inv_status_id, "SysMd")
        int_mode: Optional[int] = None
        mode_name: Optional[str] = None

        if isinstance(mode, str):
            mode_upper = mode.strip().upper()
            if mode_upper in OPERATING_MODES:
                int_mode = OPERATING_MODES[mode_upper]
                mode_name = mode_upper
            elif point_def:
                try:
                    int_mode, mode_name = point_def.validate_and_convert(mode_upper)
                except ValueError:
                    pass

            if int_mode is None or mode_name is None:
                valid = sorted(list(set(list(OPERATING_MODES.keys()) + ([s.name for s in point_def.symbols] if point_def else []))))
                raise ValueError(f"Invalid operating mode '{mode}'. Valid modes: {valid}")
        else:
            try:
                int_mode = int(mode)
            except (ValueError, TypeError):
                raise ValueError(f"Invalid operating mode value '{mode}'")

            if point_def and int_mode in point_def.symbols_by_value:
                mode_name = point_def.symbols_by_value[int_mode].name
            elif int_mode in OPERATING_MODES.values():
                mode_name = next((k for k, v in OPERATING_MODES.items() if v == int_mode), f"MODE_{int_mode}")
            else:
                valid_vals = set(OPERATING_MODES.values())
                if point_def:
                    valid_vals.update(point_def.symbols_by_value.keys())
                raise ValueError(f"Invalid operating mode integer {int_mode}. Valid values: {sorted(list(valid_vals))}")

        logger.info("Setting system operating mode to %s (%d)", mode_name, int_mode)

        beacon = self.state_store.get_beacon()
        if not beacon or beacon.slave_id is None:
            # Fall back to inverter
            inv = self.state_store.get_inverter()
            target_device = inv
            model_id = inv_status_id
        else:
            target_device = beacon
            model_id = rebus_dir_id

        if not target_device or target_device.slave_id is None:
            raise RuntimeError("No target device (beacon or inverter) discovered for system mode control")

        if self.modbus_client:
            device_tcp = self.modbus_client.get_or_create_device(target_device.slave_id)
            # Write SysMd point
            readback_mode = self.modbus_client.write_point_value(
                device=device_tcp,
                model_id=model_id,
                point_name="SysMd",
                value=int_mode,
            )
            if isinstance(readback_mode, int) and readback_mode != int_mode:
                logger.warning(
                    "System mode write read-back mismatch on %s: requested %s (%d), device returned %d",
                    target_device.serial_number,
                    mode_name,
                    int_mode,
                    readback_mode,
                )
                int_mode = readback_mode
                if point_def and int_mode in point_def.symbols_by_value:
                    mode_name = point_def.symbols_by_value[int_mode].name
                elif int_mode in SUNSPEC_SYS_MD_NAMES:
                    mode_name = SUNSPEC_SYS_MD_NAMES[int_mode]
                else:
                    mode_name = f"MODE_{int_mode}"

        # Update SysMd on target device under both model_64200 and REbus_dir (if REbus_dir model)
        target_subgroups = [f"model_{rebus_dir_id}", "REbus_dir"] if model_id == rebus_dir_id else [f"model_{model_id}"]
        for sub_g in target_subgroups:
            self.state_store.set_field(
                device_sn=target_device.serial_number,
                name="SysMd",
                label="System Operating Mode",
                description="System operating mode",
                value=mode_name,
                raw_value=int_mode,
                access="RW",
                symbols=[s.to_dict() for s in point_def.symbols] if point_def else None,
                point_type="enum16",
                is_enum=True,
                sub_group=sub_g,
            )

        # Also update any other SysMd fields across devices in state store
        for dev in self.state_store.get_devices_snapshot():
            if dev.serial_number == target_device.serial_number:
                continue
            for f_key, f in list(dev.fields.items()):
                if f.name == "SysMd" or f_key.endswith(".SysMd"):
                    parts = f.key.split(".")
                    sub_g = parts[1] if len(parts) > 2 else None
                    self.state_store.set_field(
                        device_sn=dev.serial_number,
                        name=f.name,
                        label=f.label,
                        description=f.description,
                        value=mode_name,
                        raw_value=int_mode,
                        units=f.units,
                        source=f.source,
                        access=f.access,
                        symbols=f.symbols,
                        point_type=f.point_type,
                        is_enum=f.is_enum,
                        is_bitfield=f.is_bitfield,
                        bitmask_flags=f.bitmask_flags,
                        is_scale_factor=f.is_scale_factor,
                        scale_factor_point=f.scale_factor_point,
                        offset=f.offset,
                        size=f.size,
                        ha_hint=f.ha_hint,
                        sub_group=sub_g,
                        model_id=f.model_id,
                        model_name=f.model_name,
                        model_label=f.model_label,
                    )

        # Also update compound view for system_mode
        c_view = self.state_store.get_compound_view("system_mode")
        if c_view:
            c_view.modbus_value = mode_name
            c_view.modbus_raw_value = int_mode
            c_view.latest_value = mode_name
            c_view.latest_source = "MODBUS_POLL"
            c_view.latest_updated = time.time()
            self.state_store.notify_compound_change(c_view)

        return int_mode

    def write_field(self, field_key: str, new_value: Any) -> Any:
        """Write any writable field by key (e.g. 'rebus_beacon.REbus_dir.SysMd', 'inverter.compound.system_mode').
        
        Restricts inputs based on the field descriptor from the SunSpec metamodel catalog.
        """
        target_field = None
        target_dev = None

        # Handle system mode specifically (raw or compound)
        if (
            field_key.endswith(".SysMd")
            or field_key.endswith(".system_mode")
            or field_key in ("inverter.live.system_mode", "system_mode", "inverter.compound.system_mode")
        ):
            self.set_system_mode(new_value)
            for dev in self.state_store.get_devices_snapshot():
                if field_key in dev.fields:
                    return dev.fields[field_key].value
            c_view = self.state_store.get_compound_view("system_mode")
            if c_view:
                return c_view.latest_value
            return new_value

        # Handle other compound fields
        if ".compound." in field_key:
            mapping_id = field_key.split(".compound.", 1)[-1]
            c_view = self.state_store.get_compound_view(mapping_id)
            if not c_view:
                raise KeyError(f"Compound field '{field_key}' not found in state store")
            if not c_view.is_writable:
                raise PermissionError(f"Compound field '{field_key}' is read-only")
            target_mb_key = c_view.modbus_key
            if not target_mb_key:
                for cand in c_view.modbus_candidates:
                    pt = self.catalog.get_point_for_field(cand) if self.catalog else None
                    if pt and pt.is_writable:
                        target_mb_key = cand
                        break
            if not target_mb_key:
                raise PermissionError(f"Compound field '{field_key}' has no writable modbus target point")
            res = self.write_field(target_mb_key, new_value)
            updated_c = self.state_store.get_compound_view(mapping_id)
            if updated_c:
                self.state_store.notify_compound_change(updated_c)
            return res

        for dev in self.state_store.get_devices_snapshot():
            if field_key in dev.fields:
                target_field = dev.fields[field_key]
                target_dev = dev
                break

        if not target_field or not target_dev:
            raise KeyError(f"Field '{field_key}' not found in state store")

        if target_field.name in ("SysMd", "system_mode"):
            self.set_system_mode(new_value)
            updated_f = target_dev.fields.get(field_key)
            return updated_f.value if updated_f else target_field.value

        if not target_field.is_writable:
            raise PermissionError(f"Field '{field_key}' is read-only (access: {target_field.access})")

        # Look up point descriptor from catalog
        point_def = self.catalog.get_point_for_field(field_key)
        sf_val = target_dev.get_scale_factor_value(target_field) if hasattr(target_dev, "get_scale_factor_value") else None

        if point_def:
            raw_val, display_val = point_def.validate_and_convert(new_value, sf_value=sf_val)
        elif target_field.symbols:
            # Fallback validation for fields with symbols directly on StateField
            raw_val, display_val = self._validate_against_symbols(target_field, new_value)
        else:
            raw_val = new_value
            display_val = new_value

        # Generic Modbus write if client is available
        if self.modbus_client and target_dev.slave_id is not None:
            parts = field_key.split(".")
            group_name = parts[1] if len(parts) > 2 else ""
            model_def = self.catalog.get_model_by_name(group_name)
            model_id = (
                getattr(target_field, "model_id", None)
                or (model_def.model_id if model_def else (point_def.model_id if hasattr(point_def, "model_id") else None))
            )
            if not model_id and group_name.startswith("model_"):
                try:
                    model_id = int(group_name[6:])
                except ValueError:
                    pass

            if model_id:
                device_tcp = self.modbus_client.get_or_create_device(target_dev.slave_id)
                # write_point_value assigns point.cvalue = value, which expects scaled engineering units for numeric points
                cvalue_to_write = display_val if (point_def and point_def.is_numeric) else raw_val
                readback = self.modbus_client.write_point_value(
                    device=device_tcp,
                    model_id=model_id,
                    point_name=target_field.name,
                    value=cvalue_to_write,
                )
                if readback is not None and readback != cvalue_to_write:
                    logger.warning(
                        "Write read-back mismatch on %s: requested %r, device returned %r",
                        field_key,
                        cvalue_to_write,
                        readback,
                    )
                    if point_def:
                        try:
                            raw_val, display_val = point_def.validate_and_convert(readback, ignore_access=True, sf_value=sf_val)
                        except ValueError:
                            display_val = readback
                            raw_val = readback
                    elif target_field.symbols:
                        try:
                            raw_val, display_val = self._validate_against_symbols(target_field, readback)
                        except ValueError:
                            display_val = readback
                            raw_val = readback
                    else:
                        display_val = readback
                        raw_val = readback

        parts = field_key.split(".")
        sub_g = parts[1] if len(parts) > 2 else None
        is_bf = bool(getattr(target_field, "is_bitfield", False) or (point_def and point_def.is_bitfield))
        bf_flags = (
            display_val
            if isinstance(display_val, list)
            else (point_def.decode_bitfield(raw_val) if (point_def and is_bf) else target_field.bitmask_flags)
        )
        self.state_store.set_field(
            device_sn=target_dev.serial_number,
            name=target_field.name,
            label=target_field.label,
            description=target_field.description,
            value=display_val,
            raw_value=raw_val,
            units=target_field.units,
            source=target_field.source,
            access=target_field.access,
            symbols=target_field.symbols,
            point_type=target_field.point_type,
            is_enum=target_field.is_enum,
            is_bitfield=is_bf,
            bitmask_flags=bf_flags,
            is_scale_factor=target_field.is_scale_factor,
            scale_factor_point=target_field.scale_factor_point,
            offset=target_field.offset,
            size=target_field.size,
            ha_hint=target_field.ha_hint,
            sub_group=sub_g,
            model_id=target_field.model_id,
            model_name=target_field.model_name,
            model_label=target_field.model_label,
        )
        return display_val

    def _validate_against_symbols(self, field: Any, new_value: Any) -> tuple[Any, Any]:
        """Validate input value against symbols present on the field."""
        symbols = field.symbols or []
        is_bf = getattr(field, "is_bitfield", False) or (getattr(field, "point_type", "") or "").startswith("bitfield")
        
        if is_bf:
            sym_by_name = {}
            sym_by_val = {}
            for s in symbols:
                s_name = s.get("name", "") if isinstance(s, dict) else str(s)
                s_val = s.get("value", 0) if isinstance(s, dict) else 0
                sym_by_name[s_name.upper()] = s_val
                sym_by_val[s_val] = s_name

            if isinstance(new_value, int):
                mask = new_value
            elif isinstance(new_value, str) and (new_value.isdigit() or (new_value.startswith("-") and new_value[1:].isdigit())):
                mask = int(new_value)
            elif isinstance(new_value, str):
                import re
                parts = [p.strip() for p in re.split(r'[,|; \t\n]+', new_value) if p.strip()]
                mask = 0
                for p in parts:
                    clean = p.upper()
                    if clean in sym_by_name:
                        mask |= (1 << sym_by_name[clean])
                    elif clean.isdigit():
                        mask |= (1 << int(clean))
                    else:
                        raise ValueError(f"Invalid symbol '{p}' for bitfield '{field.name}'. Valid flags: {list(sym_by_name.keys())}")
            elif isinstance(new_value, (list, tuple, set)):
                mask = 0
                for item in new_value:
                    if isinstance(item, int):
                        mask |= (1 << item)
                    elif isinstance(item, str):
                        clean = item.strip().upper()
                        if clean in sym_by_name:
                            mask |= (1 << sym_by_name[clean])
                        elif clean.isdigit():
                            mask |= (1 << int(clean))
                        else:
                            raise ValueError(f"Invalid symbol '{item}' for bitfield '{field.name}'. Valid flags: {list(sym_by_name.keys())}")
                    else:
                        raise ValueError(f"Invalid flag item '{item}' for bitfield '{field.name}'")
            else:
                raise ValueError(f"Invalid input '{new_value}' for bitfield '{field.name}'")

            active = [name for val, name in sorted(sym_by_val.items()) if (mask & (1 << val)) != 0]
            return mask, active

        # Check string match for enums
        if isinstance(new_value, str) and not (new_value.isdigit() or (new_value.startswith("-") and new_value[1:].isdigit())):
            val_upper = new_value.strip().upper()
            for s in symbols:
                s_name = s.get("name", "") if isinstance(s, dict) else str(s)
                if s_name.upper() == val_upper:
                    s_val = s.get("value") if isinstance(s, dict) else s_name
                    return s_val, s_name
            valid_names = [s.get("name", str(s)) if isinstance(s, dict) else str(s) for s in symbols]
            raise ValueError(f"Invalid symbol '{new_value}' for field '{field.name}'. Valid options: {valid_names}")

        try:
            int_val = int(new_value)
            for s in symbols:
                if isinstance(s, dict) and s.get("value") == int_val:
                    return int_val, s.get("name", str(int_val))
            valid_opts = [f"{s.get('name', '')} ({s.get('value', '')})" if isinstance(s, dict) else str(s) for s in symbols]
            raise ValueError(f"Invalid integer value {int_val} for enum '{field.name}'. Valid values: {valid_opts}")
        except (ValueError, TypeError) as e:
            if isinstance(e, ValueError) and "Invalid" in str(e):
                raise
            raise ValueError(f"Invalid input '{new_value}' for field '{field.name}'")

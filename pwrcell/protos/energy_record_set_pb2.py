"""Version-independent runtime protobuf loader for energy_record_set.proto.

The schema is loaded from the precompiled FileDescriptorSet (energy_record_set.desc)
using only public google.protobuf APIs so the module remains compatible across
protobuf runtime major versions without regenerating *_pb2.py with protoc.

If energy_record_set.proto changes, regenerate energy_record_set.desc with:
    python3 util/proto_descriptor.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

from google.protobuf import descriptor as _descriptor
from google.protobuf import descriptor_pb2 as _descriptor_pb2
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import message_factory as _message_factory


class _EnumType:
    """Public-API wrapper providing standard pb2 enum lookup helpers."""

    def __init__(self, enum_descriptor: _descriptor.EnumDescriptor) -> None:
        self.DESCRIPTOR = enum_descriptor
        self._by_name: Dict[str, int] = {
            v.name: v.number for v in enum_descriptor.values
        }
        self._by_number: Dict[int, str] = {}
        for v in enum_descriptor.values:
            self._by_number.setdefault(v.number, v.name)

    def Name(self, number: int) -> str:
        """Return the enum value name for the given numeric value."""
        try:
            return self._by_number[number]
        except KeyError as exc:
            raise ValueError(
                f"Enum {self.DESCRIPTOR.name} has no name defined for value {number}"
            ) from exc

    def Value(self, name: str) -> int:
        """Return the numeric value for the given enum value name."""
        try:
            return self._by_name[name]
        except KeyError as exc:
            raise ValueError(
                f"Enum {self.DESCRIPTOR.name} has no value named {name!r}"
            ) from exc

    def keys(self) -> List[str]:
        """Return all enum value names in definition order."""
        return [v.name for v in self.DESCRIPTOR.values]

    def values(self) -> List[int]:
        """Return all enum numeric values in definition order."""
        return [v.number for v in self.DESCRIPTOR.values]

    def items(self) -> List[Tuple[str, int]]:
        """Return (name, number) pairs in definition order."""
        return [(v.name, v.number) for v in self.DESCRIPTOR.values]

    def __getattr__(self, name: str) -> int:
        if name in self._by_name:
            return self._by_name[name]
        raise AttributeError(
            f"Enum {self.DESCRIPTOR.name} has no attribute {name!r}"
        )


def _load_descriptor() -> _descriptor.FileDescriptor:
    """Load energy_record_set.desc into a dedicated DescriptorPool."""
    desc_path = Path(__file__).with_name("energy_record_set.desc")
    fds = _descriptor_pb2.FileDescriptorSet()
    fds.ParseFromString(desc_path.read_bytes())

    pool = _descriptor_pool.DescriptorPool()
    for file_proto in fds.file:
        pool.AddSerializedFile(file_proto.SerializeToString())

    return pool.FindFileByName("energy_record_set.proto")


DESCRIPTOR = _load_descriptor()

_globals = globals()
for _enum_name, _enum_desc in DESCRIPTOR.enum_types_by_name.items():
    _globals[_enum_name] = _EnumType(_enum_desc)
    for _enum_val in _enum_desc.values:
        _globals[_enum_val.name] = _enum_val.number

for _msg_name, _msg_desc in DESCRIPTOR.message_types_by_name.items():
    _globals[_msg_name] = _message_factory.GetMessageClass(_msg_desc)

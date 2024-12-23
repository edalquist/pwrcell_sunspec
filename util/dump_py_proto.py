import importlib
import os
import sys

from google.protobuf.descriptor import FieldDescriptor, Descriptor

util_dir = os.path.dirname(__file__)
host_lib_dir = os.path.join(util_dir, "../../lib")
sys.path.append(host_lib_dir)

FIELD_TYPE_MAP = {
	FieldDescriptor.TYPE_BOOL : "bool",
	FieldDescriptor.TYPE_BYTES : "bytes",
	FieldDescriptor.TYPE_DOUBLE : "double",
	FieldDescriptor.TYPE_ENUM : "enum",
	FieldDescriptor.TYPE_FIXED32 : "fixed32",
	FieldDescriptor.TYPE_FIXED64 : "fixed64",
	FieldDescriptor.TYPE_FLOAT : "float",
	FieldDescriptor.TYPE_GROUP : "group",
	FieldDescriptor.TYPE_INT32 : "int32",
	FieldDescriptor.TYPE_INT64 : "int64",
	FieldDescriptor.TYPE_MESSAGE : "message",
	FieldDescriptor.TYPE_SFIXED32 : "sfixed32",
	FieldDescriptor.TYPE_SFIXED64 : "sfixed64",
	FieldDescriptor.TYPE_SINT32 : "sint32",
	FieldDescriptor.TYPE_SINT64 : "sint64",
	FieldDescriptor.TYPE_STRING : "string",
	FieldDescriptor.TYPE_UINT32 : "uint32",
	FieldDescriptor.TYPE_UINT64 : "uint64",
}

def print_proto_like_format(descriptor, found_types=[]):
    """Prints protobuf field information in a format resembling a .proto file."""

    output = ""
    output +=  f"message {descriptor.name} {{\n"

    types_to_print = []
    enums_to_print = []

    for field in descriptor.fields:
        field_line = "  "
        if field.label == FieldDescriptor.LABEL_REPEATED:
            field_line += "repeated "

        if field.message_type:
        	field_line += f"{field.message_type.name} "
    	elif field.enum_type:
    		field_line += f"{field.enum_type.name} "
		else:
			field_line += f"{FIELD_TYPE_MAP.get(field.type, field.type)} "
		field_line += f"{field.name} = {field.number};"

        if field.has_default_value:
            if isinstance(field.default_value, str):
                field_line += f' [default = "{field.default_value}"];'
            else:
                field_line += f' [default = {field.default_value}];'
        output += field_line + "\n"

        if field.message_type:
        	if field.message_type not in types_to_print and field.message_type not in found_types:
        		types_to_print.append(field.message_type)
        if field.enum_type:
        	if field.message_type not in enums_to_print and field.message_type not in found_types:
        		enums_to_print.append(field.enum_type)

    output += "}\n"

    found_types = found_types + types_to_print + enums_to_print
    for type in types_to_print:
    	output += print_proto_like_format(type, found_types)
	for type in enums_to_print:
		output += print_enum_like_format(type)

    return output


def print_enum_like_format(enum_descriptor):
    """Prints enum information in a format resembling a .proto file."""
    output = ""
    output += f"enum {enum_descriptor.name} {{\n"
    for value in enum_descriptor.values:
        output += "  " + f"{value.name} = {value.number};\n"
    output += "}\n"
    return output


def load_and_print(module, message):
	print(f"{module}\n")
	try:
		proto_mod = importlib.import_module(module)
		proto_cls = getattr(proto_mod, message)
		print(print_proto_like_format(proto_cls.DESCRIPTOR))
	except Exception as e:
		print(e)

load_and_print("beaconLogger.logEvent_pb2", "LogEvent")
load_and_print("dataplatform.recordset_pb2", "RecordSet")
load_and_print("energy_record_set.energyRecordSet_pb2", "EnergyRecordSet")
load_and_print("file_store.file_store_pb2", "FileStoreRequest")
load_and_print("file_store.file_store_pb2", "FileStoreResponse")
load_and_print("load_controller.ess_pb2", "EssConfig")
load_and_print("penguin_shared_lib.can_handler.system_control_mode.system_control_mode_pb2", "SystemControlModeRequest")
load_and_print("penguin_shared_lib.can_handler.uds.uds_dfu_pb2", "UdsDfuStartRequest")
load_and_print("penguin_shared_lib.can_handler.uds.uds_read_by_id_pb2", "UdsReadByIdRequest")
load_and_print("penguin_shared_lib.can_handler.uds.uds_write_by_id_pb2", "UdsWriteByIdRequest")
load_and_print("penguin_shared_lib.pwrtalk.dexi_data_pb2", "SubscriptionData")
load_and_print("spt_monitor.sptMonitor_pb2", "SPTMonitorEvent")
load_and_print("system_control.base_pb2", "BaseRequest")
load_and_print("system_control.base_pb2", "BaseResponse")
load_and_print("system_control.notification_pb2", "Notification")
load_and_print("system_devices.install_system_devices_pb2", "InstalledDevicesPutErrorResponse")
load_and_print("system_devices.install_system_devices_pb2", "InstalledDevicesPutRequest")
load_and_print("system_devices.install_system_devices_pb2", "InstalledDevicesPutSuccessResponse")
load_and_print("system_devices.system_device_list_pb2", "DeviceListRejectedResponse")
load_and_print("system_devices.system_device_list_pb2", "DeviceListRequest")
load_and_print("system_devices.system_device_list_pb2", "SystemDeviceList")

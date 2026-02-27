"""
Dumper-7 Dumpspace importer for IDA.

Purpose:
- Import as many SDK symbols as possible from Dumper-7 Dumpspace JSON files.
- Apply function names and parameter names/types to native function addresses.
- Create enums and struct/class layouts in IDA Structures.
- Build an in-IDA symbol index for reflected functions that have no native code address.

Expected input directory (Dumpspace):
- FunctionsInfo.json
- ClassesInfo.json
- StructsInfo.json
- EnumsInfo.json
- OffsetsInfo.json (optional)

Usage:
1) Run Dumper-7 in game and obtain Dumpspace output directory.
2) In IDA: File -> Script file... -> select this script.
3) Select Dumpspace/FunctionsInfo.json when prompted.

Notes:
- Not every reflected UE function has native machine code.
  Those entries cannot be renamed to code symbols because no stable code address exists.
- For functions without native addresses, this script creates searchable index symbols
  under dedicated versioned segments (e.g. `.d7_symidx`, `.d7_symidx_1`).
"""

from __future__ import annotations

import json
import os
import re
import sys
import traceback
import zlib
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

_IMPORT_ERRORS: Dict[str, str] = {}


def _import_ida_module(name: str):
    existing = globals().get(name)
    if existing is not None:
        return existing

    main_mod = sys.modules.get("__main__")
    if main_mod is not None:
        main_obj = getattr(main_mod, name, None)
        if main_obj is not None:
            return main_obj

    try:
        import builtins

        builtins_obj = getattr(builtins, name, None)
        if builtins_obj is not None:
            return builtins_obj
    except Exception:
        pass

    loaded = sys.modules.get(name)
    if loaded is not None:
        return loaded

    alt_map = {
        "idaapi": ("ida_idaapi",),
        "idc": ("ida_idc",),
    }

    candidates = (name,) + alt_map.get(name, ())
    last_exc: Optional[Exception] = None
    for candidate in candidates:
        loaded = sys.modules.get(candidate)
        if loaded is not None:
            return loaded

        try:
            return __import__(candidate)
        except Exception as exc:
            last_exc = exc

    if last_exc is not None:
        _IMPORT_ERRORS[name] = f"{type(last_exc).__name__}: {last_exc}"
    else:
        _IMPORT_ERRORS[name] = "ModuleNotFoundError: unknown import failure"
    return None


idaapi = _import_ida_module("idaapi")
ida_bytes = _import_ida_module("ida_bytes")
ida_enum = _import_ida_module("ida_enum")
ida_funcs = _import_ida_module("ida_funcs")
ida_kernwin = _import_ida_module("ida_kernwin")
ida_name = _import_ida_module("ida_name")
ida_segment = _import_ida_module("ida_segment")
ida_struct = _import_ida_module("ida_struct")
ida_nalt = _import_ida_module("ida_nalt")
ida_ida = _import_ida_module("ida_ida")
idc = _import_ida_module("idc")


BADADDR = 0xFFFFFFFFFFFFFFFF
if idaapi is not None:
    BADADDR = idaapi.BADADDR


STRUCT_COMMENT_PREFIX = "Dumper-7"
OFFSET_NAME_PREFIX = "D7_"
FUNCTION_NAME_MAX_LEN = 512
NO_OFFSET_SEGMENT_BASENAME = ".d7_symidx"
NO_OFFSET_STEP = 0x10
FALLBACK_LOG_PATH = os.path.join(os.environ.get("TEMP", "."), "dumper7_ida_importer.log")

if ida_name is None and idc is not None:
    class _IdaNameCompat:
        pass

    ida_name = _IdaNameCompat()
    ida_name.SN_NOWARN = int(getattr(idc, "SN_NOWARN", 0))
    ida_name.SN_FORCE = int(getattr(idc, "SN_FORCE", 0))
    ida_name.GN_VISIBLE = int(getattr(idc, "GN_VISIBLE", 0))
    ida_name.MAXNAMELEN = int(getattr(idc, "MAXNAMELEN", FUNCTION_NAME_MAX_LEN + 1))


def _safe_print(msg: str) -> None:
    text = str(msg)

    try:
        with open(FALLBACK_LOG_PATH, "a", encoding="utf-8", errors="replace") as f:
            f.write(text + "\n")
    except Exception:
        pass

    try:
        print(text)
        return
    except Exception:
        pass

    try:
        if ida_kernwin is not None and hasattr(ida_kernwin, "msg"):
            ida_kernwin.msg(text + "\n")
            return
    except Exception:
        pass

    try:
        if sys.__stdout__ is not None:
            sys.__stdout__.write(text + "\n")
            sys.__stdout__.flush()
    except Exception:
        pass


def _safe_alert(msg: str, title: str = "Dumper7IDA") -> None:
    text = str(msg)
    _safe_print(text)

    try:
        if ida_kernwin is not None and hasattr(ida_kernwin, "warning"):
            ida_kernwin.warning(text)
            return
    except Exception:
        pass


def _missing_required_ida_modules() -> List[str]:
    required = [
        ("idaapi", idaapi),
        ("idc", idc),
        ("ida_bytes", ida_bytes),
        ("ida_funcs", ida_funcs),
        ("ida_segment", ida_segment),
    ]
    return [name for name, mod in required if mod is None]


def _format_import_errors() -> str:
    if not _IMPORT_ERRORS:
        return ""
    parts = [f"{name}={err}" for name, err in sorted(_IMPORT_ERRORS.items())]
    return "; ".join(parts)


def _is_bad_id(value: Any) -> bool:
    if value is None:
        return True
    try:
        iv = int(value)
    except Exception:
        return False

    bads = {-1}
    try:
        bads.add(int(BADADDR))
    except Exception:
        pass
    if idc is not None and hasattr(idc, "BADADDR"):
        try:
            bads.add(int(getattr(idc, "BADADDR")))
        except Exception:
            pass

    return iv in bads


def _get_imagebase() -> int:
    if idc is not None and hasattr(idc, "get_imagebase"):
        try:
            return int(idc.get_imagebase())
        except Exception:
            pass

    if ida_nalt is not None and hasattr(ida_nalt, "get_imagebase"):
        try:
            return int(ida_nalt.get_imagebase())
        except Exception:
            pass

    if idaapi is not None and hasattr(idaapi, "get_imagebase"):
        try:
            return int(idaapi.get_imagebase())
        except Exception:
            pass

    if idc is not None and hasattr(idc, "get_inf_attr") and hasattr(idc, "INF_MIN_EA"):
        try:
            return int(idc.get_inf_attr(idc.INF_MIN_EA))
        except Exception:
            pass

    if ida_ida is not None and hasattr(ida_ida, "inf_get_min_ea"):
        try:
            return int(ida_ida.inf_get_min_ea())
        except Exception:
            pass

    if idaapi is not None and hasattr(idaapi, "get_inf_structure"):
        try:
            inf = idaapi.get_inf_structure()
            return int(getattr(inf, "min_ea", 0))
        except Exception:
            pass

    return 0


def _set_type(ea: int, decl: str) -> bool:
    for fn_name in ("SetType", "set_type"):
        fn = getattr(idc, fn_name, None) if idc is not None else None
        if callable(fn):
            try:
                return bool(fn(ea, decl))
            except Exception:
                continue
    return False


def _set_local_type(decl: str) -> int:
    for fn_name in ("SetLocalType", "set_local_type"):
        fn = getattr(idc, fn_name, None) if idc is not None else None
        if callable(fn):
            try:
                return int(fn(-1, decl, 0))
            except Exception:
                continue
    return -1


def _get_max_ea() -> int:
    if idc is not None and hasattr(idc, "get_inf_attr") and hasattr(idc, "INF_MAX_EA"):
        try:
            return int(idc.get_inf_attr(idc.INF_MAX_EA))
        except Exception:
            pass

    if ida_ida is not None and hasattr(ida_ida, "inf_get_max_ea"):
        try:
            return int(ida_ida.inf_get_max_ea())
        except Exception:
            pass

    if idaapi is not None and hasattr(idaapi, "inf_get_max_ea"):
        try:
            return int(idaapi.inf_get_max_ea())
        except Exception:
            pass

    if idaapi is not None and hasattr(idaapi, "get_inf_structure"):
        try:
            inf = idaapi.get_inf_structure()
            return int(getattr(inf, "max_ea", 0))
        except Exception:
            pass

    return 0


def _get_screen_ea() -> int:
    if idc is not None and hasattr(idc, "get_screen_ea"):
        try:
            return int(idc.get_screen_ea())
        except Exception:
            pass
    return 0


def _is_valid_dumpspace_dir(path: str) -> bool:
    if not path:
        return False
    required = (
        "FunctionsInfo.json",
        "ClassesInfo.json",
        "StructsInfo.json",
        "EnumsInfo.json",
    )
    for name in required:
        if not os.path.isfile(os.path.join(path, name)):
            return False
    return True


@dataclass
class ImportStats:
    enums_created: int = 0
    enums_failed: int = 0
    enum_members_added: int = 0

    structs_created: int = 0
    structs_failed: int = 0
    struct_members_added: int = 0

    funcs_seen: int = 0
    funcs_with_offset: int = 0
    funcs_renamed: int = 0
    funcs_type_applied: int = 0
    funcs_skipped_unloaded: int = 0
    funcs_skipped_no_offset: int = 0
    funcs_alias_collisions: int = 0
    funcs_failed: int = 0
    funcs_indexed_without_native_addr: int = 0
    strict_types_applied: int = 0
    placeholder_typedefs_created: int = 0

    offsets_named: int = 0


@dataclass
class TypeDescriptor:
    type_name: str = "void"
    type_kind: str = "D"
    extended_type: str = ""
    sub_types: List["TypeDescriptor"] = field(default_factory=list)

    @staticmethod
    def from_raw(raw: Any) -> "TypeDescriptor":
        if not isinstance(raw, list) or len(raw) < 4:
            return TypeDescriptor(type_name="void", type_kind="D", extended_type="", sub_types=[])

        type_name = str(raw[0]) if raw[0] is not None else "void"
        type_kind = str(raw[1]) if raw[1] is not None else "D"
        extended_type = str(raw[2]) if raw[2] is not None else ""

        sub_types: List[TypeDescriptor] = []
        if isinstance(raw[3], list):
            for entry in raw[3]:
                sub_types.append(TypeDescriptor.from_raw(entry))

        return TypeDescriptor(
            type_name=type_name,
            type_kind=type_kind,
            extended_type=extended_type,
            sub_types=sub_types,
        )


@dataclass
class MemberRecord:
    name: str
    type_desc: TypeDescriptor
    offset: int
    size: int
    array_dim: int
    bit_offset: Optional[int]


@dataclass
class StructRecord:
    name: str
    size: int
    inherit_info: List[str]
    members: List[MemberRecord]


@dataclass
class FunctionRecord:
    class_name: str
    func_name: str
    ret_type: TypeDescriptor
    params: List[Tuple[TypeDescriptor, str, str]]
    offset: int
    flags: str


@dataclass
class FunctionIndexRecord:
    symbol_name: str
    signature: str
    reason: str
    original_rva: int


class Dumper7IdaImporter:
    def __init__(self, dumpspace_dir: str):
        self.dumpspace_dir = dumpspace_dir
        self.stats = ImportStats()

        self.struct_name_map: Dict[str, str] = {}
        self.enum_name_map: Dict[str, str] = {}
        self.struct_ida_name_set: set = set()
        self.enum_ida_name_set: set = set()
        self.ea_aliases: Dict[int, List[str]] = {}
        self.placeholder_type_map: Dict[str, str] = {}
        self.no_addr_function_index: List[FunctionIndexRecord] = []
        ida_max_name_len = int(getattr(ida_name, "MAXNAMELEN", FUNCTION_NAME_MAX_LEN))
        # IDA名长度通常包含结尾'\0'，保守减1并限制在合理范围。
        self.max_name_len = max(64, min(FUNCTION_NAME_MAX_LEN, ida_max_name_len - 1))

    @staticmethod
    def log(msg: str) -> None:
        _safe_print(f"[Dumper7IDA] {msg}")

    def run(self) -> ImportStats:
        self._require_ida()

        self.log(f"Using Dumpspace directory: {self.dumpspace_dir}")

        classes_json = self._load_required_json("ClassesInfo.json")
        structs_json = self._load_required_json("StructsInfo.json")
        enums_json = self._load_required_json("EnumsInfo.json")
        functions_json = self._load_required_json("FunctionsInfo.json")
        offsets_json = self._load_optional_json("OffsetsInfo.json")

        self.log("Importing enums...")
        self._import_enums(enums_json.get("data", []))

        self.log("Importing structs/classes...")
        self._import_structs(structs_json.get("data", []), is_class=False)
        self._import_structs(classes_json.get("data", []), is_class=True)

        self.log("Importing functions...")
        self._import_functions(functions_json.get("data", []))
        self._flush_alias_comments()
        self._import_no_address_function_index()

        if offsets_json:
            self.log("Importing offsets...")
            self._import_offsets(offsets_json.get("data", []))

        self._print_summary()
        return self.stats

    def _require_ida(self) -> None:
        missing = _missing_required_ida_modules()
        if not missing:
            return

        details = ", ".join(missing)
        import_diag = _format_import_errors()
        if import_diag:
            raise RuntimeError(f"Missing required IDA modules: {details} | import errors: {import_diag}")
        raise RuntimeError(f"Missing required IDA modules: {details}")

    def _load_required_json(self, filename: str) -> Dict[str, Any]:
        path = os.path.join(self.dumpspace_dir, filename)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Missing required file: {path}")
        return self._load_json(path)

    def _load_optional_json(self, filename: str) -> Optional[Dict[str, Any]]:
        path = os.path.join(self.dumpspace_dir, filename)
        if not os.path.isfile(path):
            return None
        return self._load_json(path)

    @staticmethod
    def _load_json(path: str) -> Dict[str, Any]:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return json.load(f)

    @staticmethod
    def _to_int(value: Any, default: int = 0) -> int:
        try:
            if value is None:
                return default
            if isinstance(value, bool):
                return int(value)
            if isinstance(value, (int, float)):
                return int(value)
            text = str(value).strip()
            if text.startswith(("0x", "0X")):
                return int(text, 16)
            return int(text)
        except Exception:
            return default

    @staticmethod
    def _sanitize_identifier(name: str) -> str:
        cleaned = re.sub(r"[^0-9A-Za-z_]", "_", str(name))
        cleaned = re.sub(r"_+", "_", cleaned).strip("_")
        if not cleaned:
            cleaned = "sym"
        if cleaned[0].isdigit():
            cleaned = "_" + cleaned
        return cleaned

    def _hash_suffix(self, text: str) -> str:
        return format(zlib.crc32(text.encode("utf-8", errors="ignore")) & 0xFFFFFFFF, "08X")

    def _fit_name_length(self, name: str) -> str:
        if len(name) <= self.max_name_len:
            return name

        suffix = self._hash_suffix(name)
        keep = max(1, self.max_name_len - len(suffix) - 1)
        return f"{name[:keep]}_{suffix}"

    @classmethod
    def _unique_name(cls, preferred: str, taken: set) -> str:
        base = cls._sanitize_identifier(preferred)
        if base not in taken:
            taken.add(base)
            return base

        idx = 1
        while True:
            cand = f"{base}_{idx}"
            if cand not in taken:
                taken.add(cand)
                return cand
            idx += 1

    @staticmethod
    def _iter_named_items(data_list: Iterable[Any]) -> Iterable[Tuple[str, Any]]:
        for item in data_list:
            if not isinstance(item, dict):
                continue
            for name, payload in item.items():
                yield str(name), payload

    def _import_enums(self, enums_data: Iterable[Any]) -> None:
        for enum_name, payload in self._iter_named_items(enums_data):
            try:
                self._import_single_enum(enum_name, payload)
            except Exception as exc:
                self.stats.enums_failed += 1
                self.log(f"Enum import failed: {enum_name} ({exc})")

    def _import_single_enum(self, enum_name: str, payload: Any) -> None:
        if not isinstance(payload, list) or len(payload) < 2:
            self.stats.enums_failed += 1
            return

        if not hasattr(idc, "get_enum") or not hasattr(idc, "add_enum") or not hasattr(idc, "add_enum_member"):
            self.stats.enums_failed += 1
            raise RuntimeError("IDAPython idc enum API is unavailable.")

        members_raw = payload[0] if isinstance(payload[0], list) else []
        underlaying = str(payload[1]) if payload[1] is not None else "int32"
        base_enum_name = self._fit_name_length(self._sanitize_identifier(enum_name))
        enum_ida_name = base_enum_name
        if enum_ida_name in self.enum_ida_name_set:
            suffix = 1
            while True:
                cand = self._fit_name_length(f"{base_enum_name}_{suffix}")
                if cand not in self.enum_ida_name_set:
                    enum_ida_name = cand
                    break
                suffix += 1

        existing = idc.get_enum(enum_ida_name)
        if not _is_bad_id(existing):
            try:
                idc.del_enum(existing)
            except Exception:
                pass

        enum_id = idc.add_enum(-1, enum_ida_name, 0)
        if _is_bad_id(enum_id):
            for idx in range(1, 64):
                fallback_enum_name = self._fit_name_length(f"{base_enum_name}_{idx}")
                if fallback_enum_name in self.enum_ida_name_set:
                    continue
                enum_id = idc.add_enum(-1, fallback_enum_name, 0)
                if not _is_bad_id(enum_id):
                    enum_ida_name = fallback_enum_name
                    break
        if _is_bad_id(enum_id):
            self.stats.enums_failed += 1
            return

        self.enum_name_map[enum_name] = enum_ida_name
        self.enum_ida_name_set.add(enum_ida_name)

        width_map = {
            "uint8": 1,
            "int8": 1,
            "uint16": 2,
            "int16": 2,
            "uint32": 4,
            "int32": 4,
            "uint64": 8,
            "int64": 8,
        }
        if hasattr(idc, "set_enum_width"):
            try:
                idc.set_enum_width(enum_id, width_map.get(underlaying, 4))
            except Exception:
                pass

        self.stats.enums_created += 1
        taken_member_names: set = set()
        enum_default_mask = int(getattr(idc, "DEFMASK", -1))

        for entry in members_raw:
            if not isinstance(entry, dict):
                continue
            for member_name, value in entry.items():
                member_val = self._to_int(value, 0)
                base_member = self._sanitize_identifier(str(member_name))
                candidates: List[str] = []

                candidates.append(self._fit_name_length(self._unique_name(base_member, taken_member_names)))
                candidates.append(
                    self._fit_name_length(self._unique_name(f"{enum_ida_name}_{base_member}", taken_member_names))
                )

                added = False
                tried: set = set()
                for cand in candidates:
                    if cand in tried:
                        continue
                    tried.add(cand)
                    try:
                        rc = idc.add_enum_member(enum_id, cand, member_val, enum_default_mask)
                    except Exception:
                        rc = -1
                    if rc == 0:
                        self.stats.enum_members_added += 1
                        added = True
                        break

                if added:
                    continue

                # IDA enum member names are global symbols; add a short hash suffix to avoid cross-enum conflicts.
                for idx in range(1, 16):
                    cand = self._fit_name_length(
                        self._unique_name(f"{enum_ida_name}_{base_member}_{idx}", taken_member_names)
                    )
                    if cand in tried:
                        continue
                    tried.add(cand)
                    try:
                        rc = idc.add_enum_member(enum_id, cand, member_val, enum_default_mask)
                    except Exception:
                        rc = -1
                    if rc == 0:
                        self.stats.enum_members_added += 1
                        added = True
                        break

    def _import_structs(self, structs_data: Iterable[Any], is_class: bool) -> None:
        kind = "class" if is_class else "struct"
        count = 0
        for record_name, payload in self._iter_named_items(structs_data):
            count += 1
            try:
                rec = self._parse_struct_record(record_name, payload)
                self._import_single_struct(rec, is_class=is_class)
            except Exception as exc:
                self.stats.structs_failed += 1
                self.log(f"{kind} import failed: {record_name} ({exc})")

            if count % 500 == 0:
                self.log(f"{kind} import progress: {count}")

    def _parse_struct_record(self, struct_name: str, payload: Any) -> StructRecord:
        members: List[MemberRecord] = []
        inherit_info: List[str] = []
        declared_size = 0

        if isinstance(payload, list):
            for entry in payload:
                if not isinstance(entry, dict):
                    continue
                for key, value in entry.items():
                    key_str = str(key)
                    if key_str == "__MDKClassSize":
                        declared_size = self._to_int(value, 0)
                        continue
                    if key_str == "__InheritInfo":
                        if isinstance(value, list):
                            inherit_info = [str(v) for v in value]
                        continue

                    if not isinstance(value, list) or len(value) < 4:
                        continue

                    type_desc = TypeDescriptor.from_raw(value[0])
                    offset = self._to_int(value[1], 0)
                    size = self._to_int(value[2], 1)
                    array_dim = self._to_int(value[3], 1)
                    bit_offset = self._to_int(value[4], -1) if len(value) >= 5 else -1
                    if bit_offset < 0:
                        bit_offset = None

                    members.append(
                        MemberRecord(
                            name=key_str,
                            type_desc=type_desc,
                            offset=offset,
                            size=max(1, size),
                            array_dim=max(1, array_dim),
                            bit_offset=bit_offset,
                        )
                    )

        computed_size = declared_size
        for mem in members:
            end = mem.offset + mem.size
            if end > computed_size:
                computed_size = end

        members.sort(key=lambda m: (m.offset, m.name))
        return StructRecord(
            name=struct_name,
            size=max(0, computed_size),
            inherit_info=inherit_info,
            members=members,
        )

    @staticmethod
    def _member_flag_for_size(size: int) -> int:
        ff_data = ida_bytes.FF_DATA
        if size == 1:
            return ff_data | ida_bytes.FF_BYTE
        if size == 2:
            return ff_data | ida_bytes.FF_WORD
        if size == 4:
            return ff_data | ida_bytes.FF_DWORD
        if size == 8:
            return ff_data | ida_bytes.FF_QWORD
        if size == 16 and hasattr(ida_bytes, "FF_OWORD"):
            return ff_data | ida_bytes.FF_OWORD
        return ff_data | ida_bytes.FF_BYTE

    def _import_single_struct(self, rec: StructRecord, is_class: bool) -> None:
        base_struct_name = self._fit_name_length(self._sanitize_identifier(rec.name))
        ida_struct_name = base_struct_name
        if ida_struct_name in self.struct_ida_name_set:
            suffix = 1
            while True:
                cand = self._fit_name_length(f"{base_struct_name}_{suffix}")
                if cand not in self.struct_ida_name_set:
                    ida_struct_name = cand
                    break
                suffix += 1

        required_struct_api = ("get_struc_id", "add_struc", "del_struc", "add_struc_member")
        if any(not hasattr(idc, name) for name in required_struct_api):
            self.stats.structs_failed += 1
            raise RuntimeError("IDAPython idc struct API is unavailable.")

        old_sid = idc.get_struc_id(ida_struct_name)
        if not _is_bad_id(old_sid):
            try:
                idc.del_struc(old_sid)
            except Exception:
                pass

        sid = idc.add_struc(-1, ida_struct_name, False)
        if _is_bad_id(sid):
            for idx in range(1, 64):
                fallback_name = self._fit_name_length(f"{base_struct_name}_{idx}")
                if fallback_name in self.struct_ida_name_set:
                    continue
                sid = idc.add_struc(-1, fallback_name, False)
                if not _is_bad_id(sid):
                    ida_struct_name = fallback_name
                    break
        if _is_bad_id(sid):
            self.stats.structs_failed += 1
            return

        self.struct_name_map[rec.name] = ida_struct_name
        self.struct_ida_name_set.add(ida_struct_name)

        self.stats.structs_created += 1

        struct_kind = "class" if is_class else "struct"
        inherit = ", ".join(rec.inherit_info) if rec.inherit_info else "None"
        if hasattr(idc, "set_struc_cmt"):
            idc.set_struc_cmt(
                sid,
                f"{STRUCT_COMMENT_PREFIX} {struct_kind} | size=0x{rec.size:X} | inherit={inherit}",
                True,
            )

        used_names: set = set()
        for member in rec.members:
            if member.offset < 0:
                continue

            member_name = self._unique_name(member.name, used_names)
            nbytes = max(1, member.size)
            flags = self._member_flag_for_size(nbytes)

            rc = idc.add_struc_member(sid, member_name, member.offset, flags, -1, nbytes)
            if rc != 0:
                # If the preferred name failed, try a fallback name once.
                fallback_name = self._unique_name(f"{member_name}_m", used_names)
                rc = idc.add_struc_member(sid, fallback_name, member.offset, flags, -1, nbytes)
                if rc != 0:
                    continue
                member_name = fallback_name

            self.stats.struct_members_added += 1

            if hasattr(idc, "set_member_cmt"):
                type_text = self._type_to_display(member.type_desc)
                if member.array_dim > 1:
                    type_text += f" [{member.array_dim}]"
                if member.bit_offset is not None:
                    type_text += f" bit:{member.bit_offset}"
                try:
                    idc.set_member_cmt(sid, member.offset, type_text, True)
                except Exception:
                    pass

        if rec.size > 0 and hasattr(idc, "get_struc_size") and hasattr(idc, "expand_struc"):
            current_size = idc.get_struc_size(sid)
            if current_size < rec.size:
                idc.expand_struc(sid, current_size, rec.size - current_size, True)

    def _type_to_display(self, type_desc: TypeDescriptor) -> str:
        base = type_desc.type_name
        if type_desc.sub_types:
            inner = ", ".join(self._type_to_display(t) for t in type_desc.sub_types)
            base = f"{base}<{inner}>"
        if type_desc.extended_type:
            base = f"{base}{type_desc.extended_type}"
        return base

    def _register_placeholder_typedef(self, alias_name: str, target_decl: str = "void *") -> bool:
        if alias_name in self.placeholder_type_map:
            return True

        if idc is None:
            return False

        decl = f"typedef {target_decl} {alias_name};"
        rc = _set_local_type(decl)
        if rc <= 0:
            return False

        self.placeholder_type_map[alias_name] = target_decl
        self.stats.placeholder_typedefs_created += 1
        return True

    def _make_placeholder_alias(self, preferred: str, target_decl: str = "void *") -> str:
        base = self._sanitize_identifier(preferred)
        if not base.startswith("D7T_"):
            base = "D7T_" + base

        base = self._fit_name_length(f"{base}_{self._hash_suffix(preferred)}")
        alias = base
        idx = 1
        while alias in self.placeholder_type_map and self.placeholder_type_map.get(alias) != target_decl:
            alias = self._fit_name_length(f"{base}_{idx}")
            idx += 1

        if alias not in self.placeholder_type_map:
            created = self._register_placeholder_typedef(alias, target_decl=target_decl)
            if not created:
                # LocalType registration failed; still return alias text for comments/signatures.
                self.placeholder_type_map.setdefault(alias, target_decl)

        return alias

    def _type_to_cdecl(self, type_desc: TypeDescriptor, by_ref: bool = False) -> str:
        simple = {
            "void": "void",
            "bool": "bool",
            "char": "char",
            "wchar_t": "wchar_t",
            "float": "float",
            "double": "double",
            "int8": "__int8",
            "uint8": "unsigned __int8",
            "int16": "__int16",
            "uint16": "unsigned __int16",
            "int32": "int",
            "uint32": "unsigned int",
            "int64": "__int64",
            "uint64": "unsigned __int64",
        }

        tn = type_desc.type_name
        ext = type_desc.extended_type
        tk = type_desc.type_kind

        if tn in simple:
            result = simple[tn]
        elif tk == "E":
            enum_name = self.enum_name_map.get(tn) or self._sanitize_identifier(tn)
            enum_id = BADADDR
            if hasattr(idc, "get_enum"):
                try:
                    enum_id = idc.get_enum(enum_name)
                except Exception:
                    enum_id = BADADDR
            if not _is_bad_id(enum_id):
                result = f"enum {enum_name}"
            else:
                result = self._make_placeholder_alias(f"Enum_{enum_name}", target_decl="int")
        elif tk in ("C", "S"):
            mapped_name = self.struct_name_map.get(tn)
            if mapped_name:
                result = f"struct {mapped_name}"
                if ext == "*" or by_ref or tk == "C":
                    result += " *"
            else:
                result = self._make_placeholder_alias(tn, target_decl="void *")
                if by_ref:
                    result += " *"
        else:
            # Containers, delegates and unresolved names:
            # keep a readable alias instead of directly collapsing to void*.
            display = self._type_to_display(type_desc)
            result = self._make_placeholder_alias(display, target_decl="void *")
            if by_ref:
                result += " *"

        if ext == "*" and "*" not in result and not result.startswith("D7T_"):
            result += " *"

        if by_ref and "*" not in result and not result.startswith("D7T_"):
            result += " *"

        return result.replace("  ", " ").strip()

    def _make_function_name(self, class_name: str, func_name: str) -> str:
        raw = f"{class_name}__{func_name}"
        out = self._sanitize_identifier(raw)
        return self._fit_name_length(out)

    def _iter_functions(self, functions_data: Iterable[Any]) -> Iterable[FunctionRecord]:
        for class_name, payload in self._iter_named_items(functions_data):
            if not isinstance(payload, list):
                continue

            for func_entry in payload:
                if not isinstance(func_entry, dict):
                    continue

                for func_name, info in func_entry.items():
                    if not isinstance(info, list) or len(info) < 4:
                        continue

                    ret_raw = info[0]
                    params_raw = info[1] if isinstance(info[1], list) else []
                    offset = self._to_int(info[2], 0)
                    flags = str(info[3]) if info[3] is not None else ""

                    parsed_params: List[Tuple[TypeDescriptor, str, str]] = []
                    for p in params_raw:
                        if not isinstance(p, list) or len(p) < 3:
                            continue
                        param_type = TypeDescriptor.from_raw(p[0])
                        param_ref = str(p[1]) if p[1] is not None else ""
                        param_name = str(p[2]) if p[2] is not None else "arg"
                        parsed_params.append((param_type, param_ref, param_name))

                    yield FunctionRecord(
                        class_name=class_name,
                        func_name=str(func_name),
                        ret_type=TypeDescriptor.from_raw(ret_raw),
                        params=parsed_params,
                        offset=offset,
                        flags=flags,
                    )

    def _import_functions(self, functions_data: Iterable[Any]) -> None:
        imagebase = _get_imagebase()

        for idx, func in enumerate(self._iter_functions(functions_data), start=1):
            self.stats.funcs_seen += 1

            readable_sig = self._build_readable_signature(func)
            full_name = f"{func.class_name}::{func.func_name}"

            if func.offset <= 0:
                self.stats.funcs_skipped_no_offset += 1
                self.no_addr_function_index.append(
                    FunctionIndexRecord(
                        symbol_name=self._make_function_name(func.class_name, func.func_name),
                        signature=readable_sig,
                        reason="No native offset in Dumpspace",
                        original_rva=func.offset,
                    )
                )
                continue

            self.stats.funcs_with_offset += 1

            ea = imagebase + func.offset
            if not ida_bytes.is_loaded(ea):
                self.stats.funcs_skipped_unloaded += 1
                self.no_addr_function_index.append(
                    FunctionIndexRecord(
                        symbol_name=self._make_function_name(func.class_name, func.func_name),
                        signature=readable_sig,
                        reason="RVA not loaded in current IDB/module",
                        original_rva=func.offset,
                    )
                )
                continue

            target_ea = self._ensure_function_start(ea)
            if target_ea is None:
                self.stats.funcs_failed += 1
                continue

            if target_ea in self.ea_aliases:
                self.ea_aliases[target_ea].append(full_name)
                self.stats.funcs_alias_collisions += 1
                continue
            self.ea_aliases[target_ea] = []

            ida_func_name = self._make_function_name(func.class_name, func.func_name)
            final_name = self._safe_set_name(target_ea, ida_func_name, ida_name.SN_NOWARN | ida_name.SN_FORCE)
            if final_name:
                self.stats.funcs_renamed += 1
            else:
                gn_visible = getattr(ida_name, "GN_VISIBLE", 0)
                final_name = idc.get_name(target_ea, gn_visible) or ida_func_name

            strict_cdecl = self._build_function_cdecl(final_name, func)
            typed = False
            if strict_cdecl:
                typed = _set_type(target_ea, strict_cdecl)
                if typed:
                    self.stats.strict_types_applied += 1
            if not typed:
                fallback = self._build_fallback_function_cdecl(final_name, func)
                typed = _set_type(target_ea, fallback)
            if typed:
                self.stats.funcs_type_applied += 1

            cmt = f"Dumper-7: {readable_sig}\nFlags: {func.flags}\nRVA: 0x{func.offset:X}"
            ida_bytes.set_cmt(target_ea, cmt, True)

            if idx % 1000 == 0:
                self.log(f"Function import progress: {idx}")

    def _ensure_function_start(self, ea: int) -> Optional[int]:
        f = ida_funcs.get_func(ea)
        if f is None:
            ida_funcs.add_func(ea)
            f = ida_funcs.get_func(ea)

        if f is None:
            return None
        return int(f.start_ea)

    def _ensure_unique_global_name(self, preferred: str, ea: int) -> str:
        name = self._fit_name_length(preferred)
        if idc.get_name_ea_simple(name) in (BADADDR, ea):
            return name

        idx = 1
        while True:
            candidate = self._fit_name_length(f"{preferred}_{idx}")
            cur = idc.get_name_ea_simple(candidate)
            if cur in (BADADDR, ea):
                return candidate
            idx += 1

    def _safe_set_name(self, ea: int, preferred: str, flags: int) -> Optional[str]:
        candidate = self._ensure_unique_global_name(preferred, ea)
        if idc.set_name(ea, candidate, flags):
            return candidate

        # 兜底：用哈希压缩后的名字再试一次
        fallback = self._fit_name_length(f"{preferred}_{self._hash_suffix(preferred + hex(ea))}")
        fallback = self._ensure_unique_global_name(fallback, ea)
        if idc.set_name(ea, fallback, flags):
            return fallback

        return None

    def _build_function_cdecl(self, ida_func_name: str, func: FunctionRecord) -> str:
        ret_type = self._type_to_cdecl(func.ret_type, by_ref=False)

        params: List[str] = []
        used_names: set = set()
        for i, (ptype, pref, pname) in enumerate(func.params):
            by_ref = pref == "&"
            ctype = self._type_to_cdecl(ptype, by_ref=by_ref)
            arg_name = self._unique_name(pname if pname else f"arg{i}", used_names)
            params.append(f"{ctype} {arg_name}")

        params_text = ", ".join(params) if params else "void"
        return f"{ret_type} {ida_func_name}({params_text});"

    def _build_fallback_function_cdecl(self, ida_func_name: str, func: FunctionRecord) -> str:
        used_names: set = set()
        params: List[str] = []
        for i, (_, _, pname) in enumerate(func.params):
            arg_name = self._unique_name(pname if pname else f"arg{i}", used_names)
            params.append(f"void * {arg_name}")

        params_text = ", ".join(params) if params else "void"
        return_type = self._fallback_return_type(func.ret_type)
        return f"{return_type} {ida_func_name}({params_text});"

    @staticmethod
    def _fallback_return_type(ret_type: TypeDescriptor) -> str:
        # Keep true-void returns as void; unresolved/complex returns degrade to pointer.
        if ret_type.type_name == "void" and ret_type.extended_type != "*":
            return "void"
        return "void *"

    def _build_readable_signature(self, func: FunctionRecord) -> str:
        ret_name = self._type_to_display(func.ret_type)

        parts: List[str] = []
        for ptype, pref, pname in func.params:
            part = f"{self._type_to_display(ptype)}{pref} {pname}"
            parts.append(part.strip())

        args = ", ".join(parts)
        return f"{ret_name} {func.class_name}::{func.func_name}({args})"

    def _flush_alias_comments(self) -> None:
        for ea, aliases in self.ea_aliases.items():
            if not aliases:
                continue

            old = ida_bytes.get_cmt(ea, True) or ""
            alias_line = "Alias: " + ", ".join(aliases)
            new_cmt = f"{old}\n{alias_line}".strip()
            ida_bytes.set_cmt(ea, new_cmt, True)

    @staticmethod
    def _align_up(value: int, alignment: int) -> int:
        if alignment <= 0:
            return value
        return ((value + alignment - 1) // alignment) * alignment

    def _existing_segment_name_set(self) -> set:
        names: set = set()
        seg_qty = ida_segment.get_segm_qty()
        for idx in range(seg_qty):
            seg = ida_segment.getnseg(idx)
            if seg is None:
                continue
            name = ida_segment.get_segm_name(seg) or ""
            if name:
                names.add(name)
        return names

    def _next_symbol_index_segment_name(self) -> str:
        names = self._existing_segment_name_set()
        if NO_OFFSET_SEGMENT_BASENAME not in names:
            return NO_OFFSET_SEGMENT_BASENAME

        idx = 1
        while True:
            cand = f"{NO_OFFSET_SEGMENT_BASENAME}_{idx}"
            if cand not in names:
                return cand
            idx += 1

    def _create_symbol_index_segment(self, entry_count: int) -> Optional[int]:
        if entry_count <= 0:
            return None

        max_ea = _get_max_ea()
        if max_ea <= 0:
            max_ea = _get_screen_ea() + 0x100000

        # 兼容某些数据库里 INF_MAX_EA 未覆盖全部段范围的情况。
        seg_qty = ida_segment.get_segm_qty()
        for idx in range(seg_qty):
            seg = ida_segment.getnseg(idx)
            if seg is None:
                continue
            if int(seg.end_ea) > max_ea:
                max_ea = int(seg.end_ea)

        seg_start = self._align_up(max_ea, 0x1000)
        min_size = max(entry_count * NO_OFFSET_STEP, 0x1000)
        seg_size = self._align_up(min_size, 0x1000)
        seg_end = seg_start + seg_size

        seg = ida_segment.segment_t()
        seg.start_ea = seg_start
        seg.end_ea = seg_end
        seg.perm = getattr(ida_segment, "SEGPERM_READ", 0)

        inf = idaapi.get_inf_structure()
        if inf.is_64bit():
            seg.bitness = 2
        elif inf.is_32bit():
            seg.bitness = 1
        else:
            seg.bitness = 0

        seg_name = self._next_symbol_index_segment_name()
        flags = getattr(ida_segment, "ADDSEG_NOSREG", 0) | getattr(ida_segment, "ADDSEG_SPARSE", 0)
        ok = ida_segment.add_segm_ex(seg, seg_name, "DATA", flags)
        if not ok:
            return None

        self.log(f"Created symbol index segment: {seg_name} @ 0x{seg_start:X}")
        return seg_start

    def _import_no_address_function_index(self) -> None:
        if not self.no_addr_function_index:
            return

        # Preserve order but dedupe identical symbol+reason+signature records.
        deduped: List[FunctionIndexRecord] = []
        seen: set = set()
        for rec in self.no_addr_function_index:
            key = (rec.symbol_name, rec.reason, rec.signature, rec.original_rva)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(rec)

        seg_start = self._create_symbol_index_segment(len(deduped))
        if seg_start is None:
            self.log("Failed to create symbol index segment for no-address functions.")
            return

        inf = idaapi.get_inf_structure()
        ptr_size = 8 if inf.is_64bit() else 4
        data_flag = ida_bytes.FF_QWORD if ptr_size == 8 else ida_bytes.FF_DWORD

        for idx, rec in enumerate(deduped):
            ea = seg_start + (idx * NO_OFFSET_STEP)

            ida_bytes.create_data(ea, data_flag, ptr_size, BADADDR)
            if rec.original_rva >= 0:
                if ptr_size == 8:
                    ida_bytes.patch_qword(ea, rec.original_rva & 0xFFFFFFFFFFFFFFFF)
                else:
                    ida_bytes.patch_dword(ea, rec.original_rva & 0xFFFFFFFF)

            preferred_name = f"IDX_{self._sanitize_identifier(rec.symbol_name)}"
            final_name = self._safe_set_name(ea, preferred_name, ida_name.SN_NOWARN | ida_name.SN_FORCE)
            if not final_name:
                final_name = preferred_name

            cmt_lines = [
                "Dumper-7 Symbol Index (no native function address)",
                f"Symbol: {final_name}",
                rec.signature,
                f"Reason: {rec.reason}",
            ]
            if rec.original_rva > 0:
                cmt_lines.append(f"RVA: 0x{rec.original_rva:X}")
            ida_bytes.set_cmt(ea, "\n".join(cmt_lines), True)
            self.stats.funcs_indexed_without_native_addr += 1

    def _import_offsets(self, offsets_data: Iterable[Any]) -> None:
        imagebase = _get_imagebase()
        used_names: set = set()

        for item in offsets_data:
            if not isinstance(item, list) or len(item) < 2:
                continue

            name = str(item[0]) if item[0] is not None else "Offset"
            if not name.startswith("OFFSET_"):
                continue
            rva = self._to_int(item[1], -1)
            if rva < 0:
                continue

            ea = imagebase + rva
            if not ida_bytes.is_loaded(ea):
                continue

            preferred = OFFSET_NAME_PREFIX + self._sanitize_identifier(name)
            final_name = self._unique_name(preferred, used_names)
            if self._safe_set_name(ea, final_name, ida_name.SN_NOWARN):
                self.stats.offsets_named += 1

    def _print_summary(self) -> None:
        s = self.stats
        self.log("Import complete.")
        self.log(
            "Enums: created={} failed={} members={}".format(
                s.enums_created, s.enums_failed, s.enum_members_added
            )
        )
        self.log(
            "Structs/Classes: created={} failed={} members={}".format(
                s.structs_created, s.structs_failed, s.struct_members_added
            )
        )
        self.log(
            "Functions: seen={} with_offset={} renamed={} typed={} alias_collisions={} "
            "skip_no_offset={} skip_unloaded={} failed={}".format(
                s.funcs_seen,
                s.funcs_with_offset,
                s.funcs_renamed,
                s.funcs_type_applied,
                s.funcs_alias_collisions,
                s.funcs_skipped_no_offset,
                s.funcs_skipped_unloaded,
                s.funcs_failed,
            )
        )
        self.log(
            "Function typing: strict_applied={} placeholder_typedefs={} no_addr_indexed={}".format(
                s.strict_types_applied,
                s.placeholder_typedefs_created,
                s.funcs_indexed_without_native_addr,
            )
        )
        self.log(f"Offsets named: {s.offsets_named}")


def choose_dumpspace_dir() -> Optional[str]:
    selected = None
    ask_caption = "Select Dumpspace/FunctionsInfo.json"
    ask_filter = "*.json"

    if idaapi is not None and hasattr(idaapi, "ask_file"):
        try:
            selected = idaapi.ask_file(False, ask_filter, ask_caption)
        except Exception as exc:
            _safe_print(f"[Dumper7IDA] idaapi.ask_file failed: {exc}")
            selected = None

    if not selected and ida_kernwin is not None and hasattr(ida_kernwin, "ask_file"):
        try:
            selected = ida_kernwin.ask_file(False, ask_filter, ask_caption)
        except Exception as exc:
            _safe_print(f"[Dumper7IDA] ida_kernwin.ask_file failed: {exc}")
            selected = None

    if not selected:
        _safe_alert("[Dumper7IDA] Cancelled. No file selected.")
        return None

    selected = os.path.abspath(str(selected))
    if not os.path.isfile(selected):
        _safe_alert(
            "[Dumper7IDA] Selected path is not a file:\n"
            f"{selected}\n"
            "Please select Dumpspace/FunctionsInfo.json."
        )
        return None

    if os.path.basename(selected).lower() != "functionsinfo.json":
        _safe_alert(
            "[Dumper7IDA] Invalid file selected:\n"
            f"{selected}\n"
            "Please select exactly Dumpspace/FunctionsInfo.json."
        )
        return None

    picked = os.path.dirname(selected)
    if _is_valid_dumpspace_dir(picked):
        return picked

    _safe_alert(
        "[Dumper7IDA] Selected file directory is not a valid Dumpspace directory:\n"
        f"{picked}\n"
        "Expected files: FunctionsInfo.json, ClassesInfo.json, StructsInfo.json, EnumsInfo.json"
    )
    return None


def main(dumpspace_dir: Optional[str] = None) -> Optional[ImportStats]:
    _safe_print("[Dumper7IDA] Script entry.")
    missing = _missing_required_ida_modules()
    if missing:
        _safe_alert(
            "[Dumper7IDA] Missing required IDA Python modules:\n"
            + ", ".join(missing)
            + "\nRun from IDA: File -> Script file..."
        )
        import_diag = _format_import_errors()
        if import_diag:
            _safe_print(f"[Dumper7IDA] Import diagnostics: {import_diag}")
        return None

    if dumpspace_dir is None:
        dumpspace_dir = choose_dumpspace_dir()
    elif os.path.isfile(dumpspace_dir):
        dumpspace_dir = os.path.dirname(os.path.abspath(dumpspace_dir))
    else:
        dumpspace_dir = os.path.abspath(dumpspace_dir)

    if dumpspace_dir and not _is_valid_dumpspace_dir(dumpspace_dir):
        maybe_child = os.path.join(dumpspace_dir, "Dumpspace")
        if _is_valid_dumpspace_dir(maybe_child):
            dumpspace_dir = maybe_child

    if not dumpspace_dir:
        _safe_alert("[Dumper7IDA] Cancelled. No valid Dumpspace file selected.")
        return None

    try:
        importer = Dumper7IdaImporter(dumpspace_dir)
        result = importer.run()
        _safe_print("[Dumper7IDA] Script exit.")
        return result
    except Exception:
        _safe_alert(traceback.format_exc())
        raise


if __name__ == "__main__":
    main()

"""
SDK Version Diff Tool — SDK 版本差异对比工具

对比两次 Dumper-7 Dumpspace 输出，识别游戏版本更新后的 SDK 变化。
检测内容：新增/删除的类和结构体、偏移变化、大小变化、成员增删、枚举值变化、函数签名变化。

典型场景：
  - 游戏更新后重新 dump，快速定位哪些类/偏移发生了变化
  - 对比不同游戏（同引擎版本）的 SDK 差异
  - 追踪热更新或小版本补丁对反射系统的影响

前置条件：
  - 需要两个 Dumpspace 目录，每个目录下应包含：
    ClassesInfo.json, StructsInfo.json, EnumsInfo.json, FunctionsInfo.json
  - 这些文件由 Dumper-7 注入游戏后自动生成

命令行参数：
  old_dir          旧版本 Dumpspace 目录路径
  new_dir          新版本 Dumpspace 目录路径
  --output PATH    可选，输出 JSON 格式的详细报告

用法：
    python sdk_diff.py <old_dumpspace_dir> <new_dumpspace_dir> [--output diff_report.json]

示例：
    # 对比同一游戏的两个版本
    python sdk_diff.py "C:/Dumper-7/v1.0/Dumpspace" "C:/Dumper-7/v1.1/Dumpspace"

    # 输出 JSON 报告供程序化处理
    python sdk_diff.py "C:/Dumper-7/v1.0/Dumpspace" "C:/Dumper-7/v1.1/Dumpspace" --output diff.json

输出说明：
  [+] 表示新增  [-] 表示删除  [~] 表示变化
  对于结构体变化，会显示具体哪些成员的偏移移动了或大小改变了
"""

import argparse
import json
import os
import sys
from typing import Dict, List, Optional, Tuple, Any


# ---------------------------------------------------------------------------
# Dumpspace JSON parsers
# ---------------------------------------------------------------------------

def _parse_classes_or_structs(filepath: str) -> Dict[str, dict]:
    """Parse ClassesInfo.json or StructsInfo.json into {name: {size, inherit, members}}."""
    if not os.path.isfile(filepath):
        return {}

    with open(filepath, "r", encoding="utf-8") as f:
        raw = json.load(f)

    result = {}
    for entry in raw.get("data", []):
        for class_name, fields in entry.items():
            info = {"size": 0, "inherit": [], "members": {}}

            for field_dict in fields:
                for key, val in field_dict.items():
                    if key == "__InheritInfo":
                        info["inherit"] = val
                    elif key == "__MDKClassSize":
                        info["size"] = val
                    else:
                        # Member: [type_info, offset, size, count]
                        info["members"][key] = {
                            "type": val[0] if len(val) > 0 else None,
                            "offset": val[1] if len(val) > 1 else 0,
                            "size": val[2] if len(val) > 2 else 0,
                            "count": val[3] if len(val) > 3 else 1,
                        }

            result[class_name] = info

    return result


def _parse_enums(filepath: str) -> Dict[str, dict]:
    """Parse EnumsInfo.json into {name: {type, values}}."""
    if not os.path.isfile(filepath):
        return {}

    with open(filepath, "r", encoding="utf-8") as f:
        raw = json.load(f)

    result = {}
    for entry in raw.get("data", []):
        for enum_name, val in entry.items():
            # val = [[{"Name": int}, ...], "uint8"]
            values = {}
            if len(val) > 0 and isinstance(val[0], list):
                for item in val[0]:
                    if isinstance(item, dict):
                        values.update(item)

            result[enum_name] = {
                "type": val[1] if len(val) > 1 else "uint8",
                "values": values,
            }

    return result


def _parse_offsets(filepath: str) -> Dict[str, int]:
    """Parse OffsetsInfo.json into {name: value}."""
    if not os.path.isfile(filepath):
        return {}

    with open(filepath, "r", encoding="utf-8") as f:
        raw = json.load(f)

    return {entry[0]: entry[1] for entry in raw.get("data", []) if isinstance(entry, list) and len(entry) == 2}


def _parse_functions(filepath: str) -> Dict[str, Dict[str, dict]]:
    """Parse FunctionsInfo.json into {class: {func: {offset, flags, params}}}."""
    if not os.path.isfile(filepath):
        return {}

    with open(filepath, "r", encoding="utf-8") as f:
        raw = json.load(f)

    result = {}
    for entry in raw.get("data", []):
        for class_name, funcs in entry.items():
            func_map = {}
            for func_dict in funcs:
                for func_name, val in func_dict.items():
                    # val = [retType, params, offset, flags]
                    func_map[func_name] = {
                        "return": val[0] if len(val) > 0 else None,
                        "params": val[1] if len(val) > 1 else [],
                        "offset": val[2] if len(val) > 2 else 0,
                        "flags": val[3] if len(val) > 3 else "",
                    }
            result[class_name] = func_map

    return result


# ---------------------------------------------------------------------------
# Diff comparison
# ---------------------------------------------------------------------------

def _diff_structs(old: Dict[str, dict], new: Dict[str, dict], label: str) -> List[dict]:
    """Compare two struct/class maps and return list of changes."""
    changes = []
    old_names, new_names = set(old), set(new)

    for name in sorted(new_names - old_names):
        changes.append({"type": "added", "category": label, "name": name,
                        "size": new[name]["size"]})

    for name in sorted(old_names - new_names):
        changes.append({"type": "removed", "category": label, "name": name,
                        "size": old[name]["size"]})

    for name in sorted(old_names & new_names):
        o, n = old[name], new[name]
        details = []

        if o["size"] != n["size"]:
            details.append({"field": "__size", "old": o["size"], "new": n["size"]})

        om, nm = set(o["members"]), set(n["members"])

        for m in sorted(nm - om):
            mi = n["members"][m]
            details.append({"field": m, "change": "added",
                            "offset": mi["offset"], "size": mi["size"]})

        for m in sorted(om - nm):
            mi = o["members"][m]
            details.append({"field": m, "change": "removed",
                            "offset": mi["offset"], "size": mi["size"]})

        for m in sorted(om & nm):
            ov, nv = o["members"][m], n["members"][m]
            if ov["offset"] != nv["offset"]:
                details.append({"field": m, "change": "offset_moved",
                                "old": ov["offset"], "new": nv["offset"]})
            elif ov["size"] != nv["size"]:
                details.append({"field": m, "change": "size_changed",
                                "old": ov["size"], "new": nv["size"]})

        if details:
            changes.append({"type": "changed", "category": label,
                            "name": name, "details": details})

    return changes


def _diff_enums(old: Dict[str, dict], new: Dict[str, dict]) -> List[dict]:
    """Compare two enum maps."""
    changes = []
    old_names, new_names = set(old), set(new)

    for name in sorted(new_names - old_names):
        changes.append({"type": "added", "category": "enum", "name": name})

    for name in sorted(old_names - new_names):
        changes.append({"type": "removed", "category": "enum", "name": name})

    for name in sorted(old_names & new_names):
        ov, nv = old[name]["values"], new[name]["values"]
        if ov != nv:
            added = {k: v for k, v in nv.items() if k not in ov}
            removed = {k: v for k, v in ov.items() if k not in nv}
            changed = {k: (ov[k], nv[k]) for k in ov if k in nv and ov[k] != nv[k]}
            if added or removed or changed:
                changes.append({"type": "changed", "category": "enum",
                                "name": name, "added": added,
                                "removed": removed, "value_changed": changed})

    return changes


def _diff_functions(old: Dict[str, Dict[str, dict]],
                    new: Dict[str, Dict[str, dict]]) -> List[dict]:
    """Compare two function maps."""
    changes = []
    old_classes, new_classes = set(old), set(new)

    for cls in sorted(new_classes - old_classes):
        for fn in new[cls]:
            changes.append({"type": "added", "category": "function",
                            "class": cls, "name": fn})

    for cls in sorted(old_classes - new_classes):
        for fn in old[cls]:
            changes.append({"type": "removed", "category": "function",
                            "class": cls, "name": fn})

    for cls in sorted(old_classes & new_classes):
        of, nf = old[cls], new[cls]
        old_fns, new_fns = set(of), set(nf)

        for fn in sorted(new_fns - old_fns):
            changes.append({"type": "added", "category": "function",
                            "class": cls, "name": fn})

        for fn in sorted(old_fns - new_fns):
            changes.append({"type": "removed", "category": "function",
                            "class": cls, "name": fn})

        for fn in sorted(old_fns & new_fns):
            if of[fn]["flags"] != nf[fn]["flags"]:
                changes.append({"type": "changed", "category": "function",
                                "class": cls, "name": fn,
                                "old_flags": of[fn]["flags"],
                                "new_flags": nf[fn]["flags"]})

    return changes


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

def _format_text_report(all_changes: List[dict]) -> str:
    """Format changes as human-readable text."""
    lines = []
    added = [c for c in all_changes if c["type"] == "added"]
    removed = [c for c in all_changes if c["type"] == "removed"]
    changed = [c for c in all_changes if c["type"] == "changed"]

    if added:
        lines.append(f"=== ADDED ({len(added)}) ===")
        for c in added:
            cat = c["category"]
            if cat == "function":
                lines.append(f"  [+] {cat}: {c['class']}::{c['name']}")
            elif "size" in c:
                lines.append(f"  [+] {cat}: {c['name']} (size=0x{c['size']:X})")
            else:
                lines.append(f"  [+] {cat}: {c['name']}")

    if removed:
        lines.append(f"\n=== REMOVED ({len(removed)}) ===")
        for c in removed:
            cat = c["category"]
            if cat == "function":
                lines.append(f"  [-] {cat}: {c['class']}::{c['name']}")
            elif "size" in c:
                lines.append(f"  [-] {cat}: {c['name']} (size=0x{c['size']:X})")
            else:
                lines.append(f"  [-] {cat}: {c['name']}")

    if changed:
        lines.append(f"\n=== CHANGED ({len(changed)}) ===")
        for c in changed:
            cat = c["category"]
            if cat == "function":
                lines.append(f"  [~] {c['class']}::{c['name']}")
                lines.append(f"      flags: {c['old_flags']} -> {c['new_flags']}")
            elif cat == "enum":
                lines.append(f"  [~] enum {c['name']}")
                for k, v in c.get("added", {}).items():
                    lines.append(f"      [+] {k} = {v}")
                for k, v in c.get("removed", {}).items():
                    lines.append(f"      [-] {k} = {v}")
            else:
                lines.append(f"  [~] {cat} {c['name']}")
                for d in c.get("details", []):
                    f = d["field"]
                    if f == "__size":
                        lines.append(f"      size: 0x{d['old']:X} -> 0x{d['new']:X}")
                    elif d.get("change") == "added":
                        lines.append(f"      [+] +0x{d['offset']:X} {f} (size={d['size']})")
                    elif d.get("change") == "removed":
                        lines.append(f"      [-] +0x{d['offset']:X} {f} (size={d['size']})")
                    elif d.get("change") == "offset_moved":
                        lines.append(f"      [~] {f}: +0x{d['old']:X} -> +0x{d['new']:X}")

    lines.append(f"\nSummary: {len(added)} added, {len(removed)} removed, {len(changed)} changed")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_diff(old_dir: str, new_dir: str) -> Tuple[List[dict], str]:
    """Run full diff between two Dumpspace directories."""
    all_changes = []

    print("Loading old dump...")
    old_classes = _parse_classes_or_structs(os.path.join(old_dir, "ClassesInfo.json"))
    old_structs = _parse_classes_or_structs(os.path.join(old_dir, "StructsInfo.json"))
    old_enums = _parse_enums(os.path.join(old_dir, "EnumsInfo.json"))
    old_funcs = _parse_functions(os.path.join(old_dir, "FunctionsInfo.json"))

    print("Loading new dump...")
    new_classes = _parse_classes_or_structs(os.path.join(new_dir, "ClassesInfo.json"))
    new_structs = _parse_classes_or_structs(os.path.join(new_dir, "StructsInfo.json"))
    new_enums = _parse_enums(os.path.join(new_dir, "EnumsInfo.json"))
    new_funcs = _parse_functions(os.path.join(new_dir, "FunctionsInfo.json"))

    print(f"Old: {len(old_classes)} classes, {len(old_structs)} structs, "
          f"{len(old_enums)} enums, {len(old_funcs)} function groups")
    print(f"New: {len(new_classes)} classes, {len(new_structs)} structs, "
          f"{len(new_enums)} enums, {len(new_funcs)} function groups")

    print("Comparing...")
    all_changes.extend(_diff_structs(old_classes, new_classes, "class"))
    all_changes.extend(_diff_structs(old_structs, new_structs, "struct"))
    all_changes.extend(_diff_enums(old_enums, new_enums))
    all_changes.extend(_diff_functions(old_funcs, new_funcs))

    report = _format_text_report(all_changes)
    return all_changes, report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare two Dumper-7 Dumpspace outputs.")
    parser.add_argument("old_dir", help="Path to old Dumpspace directory")
    parser.add_argument("new_dir", help="Path to new Dumpspace directory")
    parser.add_argument("--output", default=None,
                        help="Output JSON report path")
    args = parser.parse_args()

    for d in [args.old_dir, args.new_dir]:
        if not os.path.isdir(d):
            print(f"ERROR: Directory not found: {d}", file=sys.stderr)
            sys.exit(1)

    changes, report = run_diff(args.old_dir, args.new_dir)
    print("\n" + report)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump({"changes": changes}, f, indent=2, ensure_ascii=False)
        print(f"\nJSON report written to: {args.output}")


if __name__ == "__main__":
    main()

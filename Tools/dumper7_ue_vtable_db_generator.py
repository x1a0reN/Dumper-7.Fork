"""
UE VTable Database Generator — UE 虚函数表数据库生成器

解析 UE 引擎源码头文件，提取虚函数声明顺序，生成 vtable index 数据库。
生成的数据库用于 Dumper-7 的 VTable 标注工具（IDA 脚本和 CE 符号导入）。

工作原理：
  1. 逐个解析目标类的头文件，提取 virtual 函数声明
  2. 跳过 override 函数（不占新 vtable slot）
  3. 跳过 #if WITH_EDITOR 块（shipping build 不包含）
  4. MSVC x64 虚析构函数占 2 个 slot（scalar + vector deleting destructor）
  5. 按继承链计算每个函数的绝对 vtable index

典型场景：
  - 为 IDA/CE 中的 vtable 函数提供名字标注
  - 验证运行时 dump 的 vtable 与源码是否一致
  - 对比不同 UE 版本的 vtable 布局变化

前置条件：
  - 需要 UE 引擎源码（支持 4.21~5.x）
  - 源码根目录下应有 Engine/Source/Runtime/... 结构

命令行参数：
  ue_source_root   UE 引擎源码根目录
  --version VER    UE 版本号字符串（默认: 4.26）
  --output PATH    可选，输出 JSON 路径（默认: Tools/vtable_db/<version>.json）

用法：
    python ue_vtable_db_generator.py <ue_source_root> [--version 4.26] [--output vtable_db/4.26.json]

示例：
    # 生成 UE 4.26 的 vtable 数据库
    python ue_vtable_db_generator.py "D:/UE/UnrealEngine-4.26" --version 4.26

    # 生成 UE 5.3 的 vtable 数据库到指定路径
    python ue_vtable_db_generator.py "D:/UE/UnrealEngine-5.3" --version 5.3 --output my_vtable.json

验证方法：
  - 检查输出 JSON 中 UObject 的 ProcessEvent index 是否与游戏中实际值一致
  - 例如 UE 4.26 中 ProcessEvent 通常在 index 67
"""

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Configuration: class definitions and their header file paths
# ---------------------------------------------------------------------------

# Each entry: (class_name, parent_class_name, header_relative_path)
CLASS_DEFINITIONS = [
    ("UObjectBase", None,
     "Engine/Source/Runtime/CoreUObject/Public/UObject/UObjectBase.h"),
    ("UObjectBaseUtility", "UObjectBase",
     "Engine/Source/Runtime/CoreUObject/Public/UObject/UObjectBaseUtility.h"),
    ("UObject", "UObjectBaseUtility",
     "Engine/Source/Runtime/CoreUObject/Public/UObject/Object.h"),
    ("AActor", "UObject",
     "Engine/Source/Runtime/Engine/Classes/GameFramework/Actor.h"),
    ("APawn", "AActor",
     "Engine/Source/Runtime/Engine/Classes/GameFramework/Pawn.h"),
    ("ACharacter", "APawn",
     "Engine/Source/Runtime/Engine/Classes/GameFramework/Character.h"),
    ("AController", "AActor",
     "Engine/Source/Runtime/Engine/Classes/GameFramework/Controller.h"),
    ("APlayerController", "AController",
     "Engine/Source/Runtime/Engine/Classes/GameFramework/PlayerController.h"),
    ("UGameViewportClient", "UObject",
     "Engine/Source/Runtime/Engine/Classes/Engine/GameViewportClient.h"),
    ("AHUD", "AActor",
     "Engine/Source/Runtime/Engine/Classes/GameFramework/HUD.h"),
    ("UEngine", "UObject",
     "Engine/Source/Runtime/Engine/Classes/Engine/Engine.h"),
    ("UGameEngine", "UEngine",
     "Engine/Source/Runtime/Engine/Classes/Engine/GameEngine.h"),
    ("UWorld", "UObject",
     "Engine/Source/Runtime/Engine/Classes/Engine/World.h"),
    ("UGameInstance", "UObject",
     "Engine/Source/Runtime/Engine/Classes/Engine/GameInstance.h"),
    ("APlayerState", "AActor",
     "Engine/Source/Runtime/Engine/Classes/GameFramework/PlayerState.h"),
    ("AGameStateBase", "AActor",
     "Engine/Source/Runtime/Engine/Classes/GameFramework/GameStateBase.h"),
    ("AGameModeBase", "AActor",
     "Engine/Source/Runtime/Engine/Classes/GameFramework/GameModeBase.h"),
]


@dataclass
class VirtualFunction:
    name: str
    is_destructor: bool = False
    line_number: int = 0


@dataclass
class ClassVTable:
    class_name: str
    parent_name: Optional[str]
    own_functions: List[VirtualFunction] = field(default_factory=list)
    base_index: int = 0  # first vtable index for this class's own functions


# ---------------------------------------------------------------------------
# Preprocessor state tracker — skip WITH_EDITOR blocks
# ---------------------------------------------------------------------------

EDITOR_MACROS = {"WITH_EDITOR", "WITH_EDITORONLY_DATA", "WITH_EDITOR_ONLY_DATA"}


def _is_editor_ifdef(line: str) -> bool:
    """Check if a preprocessor line opens a WITH_EDITOR block."""
    stripped = line.strip()
    for macro in EDITOR_MACROS:
        if re.match(rf"#\s*if\s+(defined\s*\(\s*{macro}\s*\)|{macro}\b)", stripped):
            return True
        if re.match(rf"#\s*ifdef\s+{macro}\b", stripped):
            return True
    return False


# ---------------------------------------------------------------------------
# Virtual function extractor
# ---------------------------------------------------------------------------

# Matches: virtual <return_type> <name>(...) [const] [= 0] [override] [final] ;
# Also matches: virtual ~ClassName(...)
_RE_VIRTUAL = re.compile(
    r"\bvirtual\b"
)
_RE_OVERRIDE = re.compile(
    r"\boverride\b"
)
_RE_DESTRUCTOR = re.compile(
    r"virtual\s+~\s*(\w+)\s*\("
)
_RE_FUNC_NAME = re.compile(
    r"virtual\s+(?:[\w:*&<>,\s]+?)\s+(\w+)\s*\("
)


def _extract_func_name(decl: str) -> Tuple[str, bool]:
    """Extract function name and whether it's a destructor from a virtual declaration."""
    m = _RE_DESTRUCTOR.search(decl)
    if m:
        return f"~{m.group(1)}", True

    m = _RE_FUNC_NAME.search(decl)
    if m:
        return m.group(1), False

    # Fallback: try to find any identifier after 'virtual'
    parts = decl.split("(")[0].split()
    for i, p in enumerate(parts):
        if p == "virtual" and i + 1 < len(parts):
            name = parts[-1].lstrip("*&")
            if name:
                return name, name.startswith("~")

    return "unknown", False


def _process_declaration(decl: str, line_no: int, results: List[VirtualFunction]) -> None:
    """Check if a collected declaration is a new (non-override) virtual function."""
    if not _RE_VIRTUAL.search(decl):
        return
    if _RE_OVERRIDE.search(decl):
        return  # override reuses parent slot, not a new entry

    name, is_dtor = _extract_func_name(decl)
    results.append(VirtualFunction(name=name, is_destructor=is_dtor, line_number=line_no))


def parse_header(filepath: str, class_name: str) -> List[VirtualFunction]:
    """Parse a C++ header and extract new (non-override) virtual function declarations."""
    if not os.path.isfile(filepath):
        print(f"  WARNING: File not found: {filepath}", file=sys.stderr)
        return []

    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    results: List[VirtualFunction] = []
    editor_depth = 0  # nesting depth inside WITH_EDITOR blocks
    pp_depth_stack: List[bool] = []  # stack of (is_editor_block) for each #if level
    in_class = False
    brace_depth = 0
    class_brace_depth = 0

    # We need to find the class declaration and track its scope
    class_pattern = re.compile(
        rf"\bclass\b[^;]*?\b{re.escape(class_name)}\b"
    )

    # Accumulator for multi-line declarations
    accum = ""
    accum_start_line = 0

    for line_no, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()

        # --- Preprocessor tracking ---
        if line.startswith("#"):
            if re.match(r"#\s*if", line):
                is_editor = _is_editor_ifdef(line)
                pp_depth_stack.append(is_editor)
                if is_editor:
                    editor_depth += 1
            elif re.match(r"#\s*elif", line):
                # Treat elif as closing the previous and opening a new block
                pass
            elif re.match(r"#\s*else", line):
                # In a WITH_EDITOR block, #else means we're now in the non-editor path
                if pp_depth_stack and pp_depth_stack[-1] and editor_depth > 0:
                    editor_depth -= 1
                    pp_depth_stack[-1] = False  # no longer an editor block
            elif re.match(r"#\s*endif", line):
                if pp_depth_stack:
                    was_editor = pp_depth_stack.pop()
                    if was_editor and editor_depth > 0:
                        editor_depth -= 1
            continue

        # Skip content inside WITH_EDITOR blocks
        if editor_depth > 0:
            continue

        # --- Class scope tracking ---
        if not in_class:
            if class_pattern.search(raw_line):
                in_class = True
                # Find the opening brace on this or subsequent lines
                brace_depth = raw_line.count("{") - raw_line.count("}")
                class_brace_depth = 1
                if brace_depth <= 0:
                    # Opening brace might be on the next line
                    brace_depth = 0
                    class_brace_depth = 0
            continue

        # Track braces to know when we leave the class
        opens = raw_line.count("{")
        closes = raw_line.count("}")
        brace_depth += opens - closes

        if class_brace_depth == 0 and opens > 0:
            class_brace_depth = brace_depth

        if brace_depth <= 0 and class_brace_depth > 0:
            in_class = False
            continue

        # --- Virtual function detection ---
        # Accumulate lines for multi-line declarations
        if accum or _RE_VIRTUAL.search(line):
            if not accum:
                accum_start_line = line_no
            accum += " " + line

            # Check if declaration is complete (has semicolon or opening brace)
            if ";" in accum or ("{" in accum and "}" in accum):
                _process_declaration(accum, accum_start_line, results)
                accum = ""
            elif "{" in accum:
                # Inline function body started — declaration is complete
                _process_declaration(accum, accum_start_line, results)
                accum = ""

    return results


# ---------------------------------------------------------------------------
# VTable database builder
# ---------------------------------------------------------------------------

def build_vtable_db(ue_root: str, version: str) -> dict:
    """Build the complete vtable database for all configured classes."""
    class_map: Dict[str, ClassVTable] = {}

    for class_name, parent_name, header_rel in CLASS_DEFINITIONS:
        header_path = os.path.join(ue_root, header_rel.replace("/", os.sep))
        print(f"Parsing {class_name} from {header_rel}...")

        own_funcs = parse_header(header_path, class_name)

        vtable = ClassVTable(
            class_name=class_name,
            parent_name=parent_name,
            own_functions=own_funcs,
        )
        class_map[class_name] = vtable

        print(f"  Found {len(own_funcs)} new virtual functions")

    # Calculate absolute vtable indices based on inheritance chain
    _assign_base_indices(class_map)

    # Build output JSON
    return _format_output(class_map, version)


def _assign_base_indices(class_map: Dict[str, ClassVTable]) -> None:
    """Walk the inheritance chain and assign absolute vtable base indices."""
    resolved: Dict[str, int] = {}  # class_name -> total vtable size (next free index)

    def resolve(name: str) -> int:
        if name in resolved:
            return resolved[name]

        vtable = class_map.get(name)
        if vtable is None:
            return 0

        parent_total = 0
        if vtable.parent_name:
            parent_total = resolve(vtable.parent_name)

        vtable.base_index = parent_total

        # Count slots: destructors occupy 2 on MSVC x64
        own_slots = 0
        for func in vtable.own_functions:
            if func.is_destructor:
                own_slots += 2
            else:
                own_slots += 1

        total = parent_total + own_slots
        resolved[name] = total
        return total

    for name in class_map:
        resolve(name)


def _format_output(class_map: Dict[str, ClassVTable], version: str) -> dict:
    """Format the vtable database as a JSON-serializable dict."""
    classes = {}

    for name, vtable in class_map.items():
        functions = []
        idx = vtable.base_index

        for func in vtable.own_functions:
            functions.append([idx, func.name, func.is_destructor])
            if func.is_destructor:
                idx += 2  # MSVC x64: scalar + vector deleting destructor
            else:
                idx += 1

        classes[name] = {
            "parent": vtable.parent_name,
            "base_index": vtable.base_index,
            "own_count": len(vtable.own_functions),
            "total_slots": idx,
            "functions": functions,
        }

    return {
        "ue_version": version,
        "generator": "ue_vtable_db_generator.py",
        "classes": classes,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate UE VTable function name database from source headers."
    )
    parser.add_argument(
        "ue_source_root",
        help="Path to UE source root (e.g. D:\\Projects\\UnrealEngine\\UnrealEngine-4.26)",
    )
    parser.add_argument(
        "--version", default="4.26",
        help="UE version string (default: 4.26)",
    )
    parser.add_argument(
        "--output", default=None,
        help="Output JSON path (default: Tools/vtable_db/<version>.json)",
    )
    args = parser.parse_args()

    ue_root = os.path.abspath(args.ue_source_root)
    if not os.path.isdir(ue_root):
        print(f"ERROR: UE source root not found: {ue_root}", file=sys.stderr)
        sys.exit(1)

    db = build_vtable_db(ue_root, args.version)

    # Determine output path
    if args.output:
        out_path = args.output
    else:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        out_dir = os.path.join(script_dir, "vtable_db")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"{args.version}.json")

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)

    print(f"\nVTable DB written to: {out_path}")

    # Print summary
    for name, info in db["classes"].items():
        print(f"  {name}: {info['own_count']} own, total slots={info['total_slots']}")


if __name__ == "__main__":
    main()

"""
UE Source vs Dump Comparison Tool — UE 源码与 Dump 结构对比工具

将 Dumper-7 的 Dumpspace 输出与 UE 引擎源码进行交叉对比，识别：
  - 引擎成员 [ENGINE]：源码和 dump 中都存在的成员（引擎原生）
  - 游戏自定义成员 [GAME CUSTOM]：dump 中有但源码中没有的成员（游戏开发者添加）
  - 仅源码成员 [SOURCE ONLY]：源码中有但 dump 中没有的成员（通常是 bitfield 或编辑器专用）

典型场景：
  - 逆向游戏时区分哪些是引擎标准成员、哪些是游戏自定义的
  - 快速定位游戏在引擎类上扩展了哪些字段
  - 验证 dump 结果与引擎源码的一致性

前置条件：
  - 需要 UE 引擎源码（支持 4.21~5.x）
  - 需要 Dumpspace 目录（包含 ClassesInfo.json 和/或 StructsInfo.json）

命令行参数：
  ue_source_root   UE 引擎源码根目录（包含 Engine/Source/ 的那一层）
  dumpspace_dir    Dumpspace 输出目录
  --classes NAMES  可选，逗号分隔的类名列表（默认对比所有已知引擎类）
  --output PATH    可选，输出 JSON 格式的详细报告

用法：
    python dumper7_ue_source_compare.py <ue_source_root> <dumpspace_dir> [--classes AActor,APawn]

示例：
    # 对比所有已知引擎类
    python dumper7_ue_source_compare.py "D:/UE/UnrealEngine-4.26" "C:/Dumper-7/v1.0/Dumpspace"

    # 只对比指定类
    python dumper7_ue_source_compare.py "D:/UE/UnrealEngine-4.26" "C:/Dumper-7/v1.0/Dumpspace" \
        --classes AActor,ACharacter,APawn

    # 输出 JSON 报告
    python dumper7_ue_source_compare.py "D:/UE/UnrealEngine-4.26" "C:/Dumper-7/v1.0/Dumpspace" \
        --output compare_report.json

已知限制：
  - bitfield 成员（如 uint8 bHidden:1）在源码解析时名字可能带 :1 后缀，
    与 dump 中的名字不完全匹配，会同时出现在 GAME CUSTOM 和 SOURCE ONLY 中
  - 仅解析 UPROPERTY() 修饰的成员（与 Dumper-7 的反射范围一致）
"""

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SourceMember:
    name: str
    type_str: str
    line_number: int = 0


@dataclass
class SourceClass:
    name: str
    parent: Optional[str]
    members: List[SourceMember] = field(default_factory=list)
    header_path: str = ""


# Known UE class -> header path mappings (Engine source relative paths)
CLASS_HEADERS = {
    "UObject":              "Engine/Source/Runtime/CoreUObject/Public/UObject/Object.h",
    "UObjectBase":          "Engine/Source/Runtime/CoreUObject/Public/UObject/UObjectBase.h",
    "UObjectBaseUtility":   "Engine/Source/Runtime/CoreUObject/Public/UObject/UObjectBaseUtility.h",
    "AActor":               "Engine/Source/Runtime/Engine/Classes/GameFramework/Actor.h",
    "APawn":                "Engine/Source/Runtime/Engine/Classes/GameFramework/Pawn.h",
    "ACharacter":           "Engine/Source/Runtime/Engine/Classes/GameFramework/Character.h",
    "AController":          "Engine/Source/Runtime/Engine/Classes/GameFramework/Controller.h",
    "APlayerController":    "Engine/Source/Runtime/Engine/Classes/GameFramework/PlayerController.h",
    "APlayerState":         "Engine/Source/Runtime/Engine/Classes/GameFramework/PlayerState.h",
    "AGameStateBase":       "Engine/Source/Runtime/Engine/Classes/GameFramework/GameStateBase.h",
    "AGameModeBase":        "Engine/Source/Runtime/Engine/Classes/GameFramework/GameModeBase.h",
    "UActorComponent":      "Engine/Source/Runtime/Engine/Classes/Components/ActorComponent.h",
    "USceneComponent":      "Engine/Source/Runtime/Engine/Classes/Components/SceneComponent.h",
    "UPrimitiveComponent":  "Engine/Source/Runtime/Engine/Classes/Components/PrimitiveComponent.h",
    "UMeshComponent":       "Engine/Source/Runtime/Engine/Classes/Components/MeshComponent.h",
    "USkeletalMeshComponent": "Engine/Source/Runtime/Engine/Classes/Components/SkeletalMeshComponent.h",
    "UStaticMeshComponent": "Engine/Source/Runtime/Engine/Classes/Components/StaticMeshComponent.h",
    "UGameViewportClient":  "Engine/Source/Runtime/Engine/Classes/Engine/GameViewportClient.h",
    "AHUD":                 "Engine/Source/Runtime/Engine/Classes/GameFramework/HUD.h",
    "UEngine":              "Engine/Source/Runtime/Engine/Classes/Engine/Engine.h",
    "UWorld":               "Engine/Source/Runtime/Engine/Classes/Engine/World.h",
    "UGameInstance":        "Engine/Source/Runtime/Engine/Classes/Engine/GameInstance.h",
    "UMovementComponent":   "Engine/Source/Runtime/Engine/Classes/GameFramework/MovementComponent.h",
    "UCharacterMovementComponent": "Engine/Source/Runtime/Engine/Classes/GameFramework/CharacterMovementComponent.h",
    "UWidgetComponent":     "Engine/Source/Runtime/UMG/Public/Components/WidgetComponent.h",
    "UUserWidget":          "Engine/Source/Runtime/UMG/Public/Blueprint/UserWidget.h",
}

# Editor-only macros to skip
EDITOR_MACROS = {"WITH_EDITOR", "WITH_EDITORONLY_DATA", "WITH_EDITOR_ONLY_DATA"}


# ---------------------------------------------------------------------------
# UE source header parser — extract UPROPERTY members
# ---------------------------------------------------------------------------

def _is_editor_ifdef(line: str) -> bool:
    stripped = line.strip()
    for macro in EDITOR_MACROS:
        if re.match(rf"#\s*if\s+(defined\s*\(\s*{macro}\s*\)|{macro}\b)", stripped):
            return True
        if re.match(rf"#\s*ifdef\s+{macro}\b", stripped):
            return True
    return False


def parse_header_members(filepath: str, class_name: str) -> SourceClass:
    """Parse a UE header and extract UPROPERTY-decorated members for a class."""
    result = SourceClass(name=class_name, parent=None, header_path=filepath)

    if not os.path.isfile(filepath):
        print(f"  WARNING: File not found: {filepath}", file=sys.stderr)
        return result

    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    # State tracking
    editor_depth = 0
    pp_stack: List[bool] = []
    in_class = False
    brace_depth = 0
    class_brace_depth = 0
    saw_uproperty = False

    class_pat = re.compile(rf"\bclass\b[^;]*?\b{re.escape(class_name)}\b")
    parent_pat = re.compile(rf"\b{re.escape(class_name)}\b\s*:\s*public\s+(\w+)")

    for line_no, raw in enumerate(lines, start=1):
        line = raw.strip()

        # Preprocessor tracking
        if line.startswith("#"):
            if re.match(r"#\s*if", line):
                is_ed = _is_editor_ifdef(line)
                pp_stack.append(is_ed)
                if is_ed:
                    editor_depth += 1
            elif re.match(r"#\s*else", line):
                if pp_stack and pp_stack[-1] and editor_depth > 0:
                    editor_depth -= 1
                    pp_stack[-1] = False
            elif re.match(r"#\s*endif", line):
                if pp_stack:
                    was = pp_stack.pop()
                    if was and editor_depth > 0:
                        editor_depth -= 1
            continue

        if editor_depth > 0:
            continue

        # Find class declaration
        if not in_class:
            if class_pat.search(raw):
                in_class = True
                m = parent_pat.search(raw)
                if m:
                    result.parent = m.group(1)
                brace_depth = raw.count("{") - raw.count("}")
                class_brace_depth = 1
                if brace_depth <= 0:
                    brace_depth = 0
                    class_brace_depth = 0
            continue

        # Track braces
        brace_depth += raw.count("{") - raw.count("}")
        if class_brace_depth == 0 and "{" in raw:
            class_brace_depth = brace_depth
        if brace_depth <= 0 and class_brace_depth > 0:
            in_class = False
            continue

        # Detect UPROPERTY()
        if re.match(r"\s*UPROPERTY\s*\(", line):
            saw_uproperty = True
            continue

        # After UPROPERTY, next non-empty non-macro line is the member
        if saw_uproperty and line and not line.startswith("//"):
            saw_uproperty = False
            # Extract member name: last identifier before ; or =
            decl = line.rstrip(";").strip()
            # Remove default value
            if "=" in decl:
                decl = decl[:decl.index("=")].strip()
            # Remove array brackets
            decl = re.sub(r"\[.*\]", "", decl)
            parts = decl.split()
            if parts:
                name = parts[-1].lstrip("*&")
                type_str = " ".join(parts[:-1])
                result.members.append(SourceMember(
                    name=name, type_str=type_str, line_number=line_no))

    return result


# ---------------------------------------------------------------------------
# Dumpspace loader
# ---------------------------------------------------------------------------

def _load_dump_classes(dumpspace_dir: str) -> Dict[str, dict]:
    """Load ClassesInfo + StructsInfo into {name: {size, members}}."""
    result = {}
    for filename in ["ClassesInfo.json", "StructsInfo.json"]:
        filepath = os.path.join(dumpspace_dir, filename)
        if not os.path.isfile(filepath):
            continue
        with open(filepath, "r", encoding="utf-8") as f:
            raw = json.load(f)
        for entry in raw.get("data", []):
            for cls_name, fields in entry.items():
                info = {"size": 0, "members": {}}
                for fd in fields:
                    for key, val in fd.items():
                        if key == "__MDKClassSize":
                            info["size"] = val
                        elif not key.startswith("__"):
                            info["members"][key] = {
                                "offset": val[1] if len(val) > 1 else 0,
                                "size": val[2] if len(val) > 2 else 0,
                            }
                result[cls_name] = info
    return result


# ---------------------------------------------------------------------------
# Comparison logic
# ---------------------------------------------------------------------------

def compare_class(source: SourceClass, dump: dict) -> dict:
    """Compare a single class between UE source and dump."""
    source_names = {m.name for m in source.members}
    dump_names = set(dump["members"].keys())

    engine = []
    for m in source.members:
        if m.name in dump_names:
            dm = dump["members"][m.name]
            engine.append({"name": m.name, "source_type": m.type_str,
                           "dump_offset": dm["offset"], "dump_size": dm["size"]})

    game_custom = []
    for name in sorted(dump_names - source_names):
        dm = dump["members"][name]
        game_custom.append({"name": name, "offset": dm["offset"], "size": dm["size"]})

    source_only = []
    for m in source.members:
        if m.name not in dump_names:
            source_only.append({"name": m.name, "type": m.type_str, "line": m.line_number})

    return {
        "class": source.name, "dump_size": dump["size"],
        "source_members": len(source.members), "dump_members": len(dump["members"]),
        "engine": engine, "game_custom": game_custom, "source_only": source_only,
    }


def format_report(reports: List[dict]) -> str:
    """Format comparison reports as readable text."""
    lines = []
    for r in reports:
        lines.append(f"{'='*60}")
        lines.append(f"{r['class']}  (dump size=0x{r['dump_size']:X})")
        lines.append(f"  Source UPROPERTY: {r['source_members']}  |  Dump members: {r['dump_members']}")

        if r["engine"]:
            lines.append(f"\n  [ENGINE] ({len(r['engine'])} members matched)")
            for m in r["engine"]:
                lines.append(f"    +0x{m['dump_offset']:04X}  {m['name']}  ({m['source_type']}, size={m['dump_size']})")

        if r["game_custom"]:
            lines.append(f"\n  [GAME CUSTOM] ({len(r['game_custom'])} members)")
            for m in r["game_custom"]:
                lines.append(f"    +0x{m['offset']:04X}  {m['name']}  (size={m['size']})")

        if r["source_only"]:
            lines.append(f"\n  [SOURCE ONLY] ({len(r['source_only'])} - in source but not in dump)")
            for m in r["source_only"]:
                lines.append(f"    {m['name']}  ({m['type']})  line {m['line']}")

        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare Dumper-7 dump against UE source code.")
    parser.add_argument("ue_source_root",
                        help="Path to UE source root")
    parser.add_argument("dumpspace_dir",
                        help="Path to Dumpspace output directory")
    parser.add_argument("--classes", default=None,
                        help="Comma-separated class names to compare (default: all known)")
    parser.add_argument("--output", default=None,
                        help="Output JSON report path")
    args = parser.parse_args()

    ue_root = os.path.abspath(args.ue_source_root)
    if not os.path.isdir(ue_root):
        print(f"ERROR: UE source root not found: {ue_root}", file=sys.stderr)
        sys.exit(1)

    dump = _load_dump_classes(args.dumpspace_dir)
    print(f"Loaded {len(dump)} classes/structs from dump")

    # Determine which classes to compare
    if args.classes:
        target_classes = [c.strip() for c in args.classes.split(",")]
    else:
        target_classes = list(CLASS_HEADERS.keys())

    reports = []
    for cls in target_classes:
        header_rel = CLASS_HEADERS.get(cls)
        if not header_rel:
            print(f"  Skipping {cls} — no header mapping")
            continue

        # Find matching dump entry (try with and without prefix)
        dump_entry = dump.get(cls)
        if not dump_entry:
            # Try without U/A prefix
            short = cls[1:] if cls[0] in "UA" else cls
            dump_entry = dump.get(short)
        if not dump_entry:
            print(f"  Skipping {cls} — not found in dump")
            continue

        header_path = os.path.join(ue_root, header_rel.replace("/", os.sep))
        print(f"  Parsing {cls} from {header_rel}...")
        source = parse_header_members(header_path, cls)
        print(f"    Found {len(source.members)} UPROPERTY members")

        report = compare_class(source, dump_entry)
        reports.append(report)

    text = format_report(reports)
    print("\n" + text)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump({"reports": reports}, f, indent=2, ensure_ascii=False)
        print(f"JSON report written to: {args.output}")


if __name__ == "__main__":
    main()

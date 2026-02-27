"""
Dumper-7 Tools 使用示例

本文件演示 Tools 目录下所有 Python 工具的用法。
可以直接运行本文件查看各工具的帮助信息，也可以参考下方代码在自己的脚本中调用。

工具列表：
  1. dumper7_ida_import.py  — IDA 符号导入脚本（在 IDA 中运行）
  2. dumper7_sdk_diff.py                  — SDK 版本差异对比
  3. dumper7_ue_source_compare.py         — UE 源码与 Dump 结构对比
  4. dumper7_ue_vtable_db_generator.py    — UE 虚函数表数据库生成器

运行本文件：
    python dumper7_examples.py
"""

import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def print_header(title: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}\n")


# =========================================================================
# 示例 1: SDK 版本差异对比 (dumper7_sdk_diff.py)
# =========================================================================

def example_sdk_diff():
    """
    对比两个 Dumpspace 目录，找出 SDK 变化。

    典型用途：游戏更新后重新 dump，快速定位偏移变化。

    命令行用法：
        python dumper7_sdk_diff.py <旧版目录> <新版目录> [--output report.json]

    Python API 用法：
        from dumper7_sdk_diff import run_diff
        changes, report = run_diff("path/to/old", "path/to/new")
        print(report)
    """
    print_header("示例 1: SDK 版本差异对比 (dumper7_sdk_diff.py)")

    print("命令行用法:")
    print('  python dumper7_sdk_diff.py "C:/Dumper-7/v1.0/Dumpspace" "C:/Dumper-7/v1.1/Dumpspace"')
    print()
    print("带 JSON 输出:")
    print('  python dumper7_sdk_diff.py "C:/Dumper-7/v1.0/Dumpspace" "C:/Dumper-7/v1.1/Dumpspace" --output diff.json')
    print()

    # Python API 调用示例
    print("Python API 调用:")
    print("  from dumper7_sdk_diff import run_diff")
    print('  changes, report = run_diff("old_dumpspace/", "new_dumpspace/")')
    print("  print(report)")
    print()
    print("  # 程序化处理变化列表")
    print("  for c in changes:")
    print('      if c["type"] == "changed" and c["category"] == "class":')
    print('          print(f"类 {c[\'name\']} 发生了变化:")')
    print('          for d in c.get("details", []):')
    print('              print(f"  {d}")')


# =========================================================================
# 示例 2: UE 源码与 Dump 结构对比 (dumper7_ue_source_compare.py)
# =========================================================================

def example_ue_source_compare():
    """
    将 dump 结果与 UE 引擎源码交叉对比，区分引擎成员和游戏自定义成员。

    命令行用法：
        python dumper7_ue_source_compare.py <UE源码根目录> <Dumpspace目录> [--classes AActor,APawn]

    Python API 用法：
        from dumper7_ue_source_compare import parse_header_members, compare_class, _load_dump_classes
    """
    print_header("示例 2: UE 源码与 Dump 结构对比 (dumper7_ue_source_compare.py)")

    print("命令行用法:")
    print('  python dumper7_ue_source_compare.py "D:/UE/UnrealEngine-4.26" "C:/Dumper-7/v1.0/Dumpspace"')
    print()
    print("只对比指定类:")
    print('  python dumper7_ue_source_compare.py "D:/UE/UnrealEngine-4.26" "C:/Dumper-7/v1.0/Dumpspace" \\')
    print('      --classes AActor,ACharacter,APawn')
    print()
    print("输出 JSON 报告:")
    print('  python dumper7_ue_source_compare.py "D:/UE/UnrealEngine-4.26" "C:/Dumper-7/v1.0/Dumpspace" \\')
    print('      --output compare_report.json')
    print()

    # Python API 调用示例
    print("Python API 调用:")
    print("  from dumper7_ue_source_compare import parse_header_members, _load_dump_classes, compare_class")
    print()
    print("  # 解析 UE 源码头文件")
    print('  source = parse_header_members("path/to/Actor.h", "AActor")')
    print('  print(f"找到 {len(source.members)} 个 UPROPERTY 成员")')
    print()
    print("  # 加载 dump 数据")
    print('  dump = _load_dump_classes("path/to/Dumpspace")')
    print()
    print("  # 对比")
    print('  report = compare_class(source, dump["AActor"])')
    print('  print(f"引擎成员: {len(report[\'engine\'])}")')
    print('  print(f"游戏自定义: {len(report[\'game_custom\'])}")')


# =========================================================================
# 示例 3: UE VTable 数据库生成 (dumper7_ue_vtable_db_generator.py)
# =========================================================================

def example_vtable_db_generator():
    """
    从 UE 源码生成 vtable 函数名数据库。

    命令行用法：
        python dumper7_ue_vtable_db_generator.py <UE源码根目录> [--version 4.26]

    Python API 用法：
        from dumper7_ue_vtable_db_generator import build_vtable_db
    """
    print_header("示例 3: UE VTable 数据库生成 (dumper7_ue_vtable_db_generator.py)")

    print("命令行用法:")
    print('  python dumper7_ue_vtable_db_generator.py "D:/UE/UnrealEngine-4.26" --version 4.26')
    print()
    print("指定输出路径:")
    print('  python dumper7_ue_vtable_db_generator.py "D:/UE/UnrealEngine-5.3" --version 5.3 --output vtable_5.3.json')
    print()

    # Python API 调用示例
    print("Python API 调用:")
    print("  from dumper7_ue_vtable_db_generator import build_vtable_db, parse_header")
    print()
    print("  # 生成完整数据库")
    print('  db = build_vtable_db("D:/UE/UnrealEngine-4.26", "4.26")')
    print('  for name, info in db["classes"].items():')
    print('      print(f"{name}: {info[\'own_count\']} own virtual functions")')
    print()
    print("  # 单独解析一个类的虚函数")
    print('  funcs = parse_header("path/to/Actor.h", "AActor")')
    print("  for f in funcs:")
    print('      print(f"  [{f.line_number}] {f.name} (destructor={f.is_destructor})")')


# =========================================================================
# 示例 4: IDA 符号导入 (dumper7_ida_import.py)
# =========================================================================

def example_ida_import():
    """
    在 IDA 中导入 Dumper-7 的符号信息。

    注意：此脚本只能在 IDA 的 IDAPython 环境中运行，不能在命令行直接运行。
    """
    print_header("示例 4: IDA 符号导入 (dumper7_ida_import.py)")

    print("此脚本在 IDA Pro 中运行，不能在命令行直接调用。")
    print()
    print("使用步骤:")
    print("  1. 注入 Dumper-7 到目标游戏，等待生成 Dumpspace 目录")
    print("  2. 在 IDA 中打开游戏的 .exe 文件")
    print("  3. File -> Script file... -> 选择 dumper7_ida_import.py")
    print("  4. 在弹出的对话框中选择 Dumpspace/FunctionsInfo.json")
    print("  5. 脚本自动从同目录加载其他 JSON 文件并导入符号")
    print()
    print("导入内容:")
    print("  - 函数名和参数类型标注")
    print("  - 结构体/类布局 (IDA Structures)")
    print("  - 枚举类型 (IDA Enums)")
    print("  - 全局偏移符号 (GObjects, GNames, GWorld 等)")
    print("  - VTable 函数符号 (如果有 VTableInfo.json)")
    print()
    print("嵌入式运行:")
    print("  Dumper-7 编译时会将此脚本嵌入 DLL，注入后自动生成")
    print("  dumper7_ida_import.py 到 Dumpspace 目录，方便直接使用。")


# =========================================================================
# 示例 5: UE 版本指纹识别 (dumper7_ue_version_detect.py)
# =========================================================================

def example_ue_version_detect():
    """
    无需注入，通过分析游戏 PE 二进制特征识别 UE 引擎版本。

    命令行用法：
        python dumper7_ue_version_detect.py <game.exe> [--json] [--output report.txt]

    Python API 用法：
        from dumper7_ue_version_detect import detect_version, format_report
    """
    print_header("示例 5: UE 版本指纹识别 (dumper7_ue_version_detect.py)")

    print("命令行用法:")
    print('  python dumper7_ue_version_detect.py "C:/Games/MyGame/Binaries/Win64/MyGame-Win64-Shipping.exe"')
    print()
    print("JSON 格式输出:")
    print('  python dumper7_ue_version_detect.py "C:/Games/MyGame/MyGame.exe" --json')
    print()
    print("输出到文件:")
    print('  python dumper7_ue_version_detect.py "C:/Games/MyGame/MyGame.exe" --output report.txt')
    print()

    print("Python API 调用:")
    print("  from dumper7_ue_version_detect import detect_version, format_report")
    print()
    print('  result = detect_version("path/to/game.exe")')
    print(f'  print(f"Version: {{result.version}}, Confidence: {{result.confidence}}")')
    print()
    print("  # 人类可读报告")
    print("  print(format_report(result))")
    print()
    print("  # 遍历检测证据")
    print("  for e in result.evidence:")
    print('      print(f"  [{e.method}] {e.detail} (weight={e.weight})")')


# =========================================================================
# 示例 6: 完整工作流
# =========================================================================

def example_full_workflow():
    """演示从 dump 到分析的完整工作流。"""
    print_header("示例 6: 完整工作流")

    print("步骤 1: 检测游戏 UE 版本（无需注入）")
    print('  python dumper7_ue_version_detect.py "C:/Games/MyGame/MyGame.exe"')
    print("  -> 确定 UE 版本，选择正确的 VTableDB")
    print()
    print("步骤 2: 注入 Dumper-7 到游戏")
    print("  -> 生成 C:/Dumper-7/<version>/Dumpspace/ 目录")
    print()
    print("步骤 3: 生成 VTable 数据库（需要 UE 源码）")
    print('  python dumper7_ue_vtable_db_generator.py "D:/UE/UnrealEngine-4.26" --version 4.26')
    print("  -> 生成 Tools/vtable_db/4.26.json")
    print("  -> 复制到 Dumpspace 目录并重命名为 VTableDB.json")
    print()
    print("步骤 4: 在 IDA 中导入符号")
    print("  IDA: File -> Script file -> dumper7_ida_import.py")
    print("  -> 选择 FunctionsInfo.json")
    print()
    print("步骤 5: 在 CE 中加载符号")
    print("  CE: Table -> Execute Script -> 打开 Dumpspace/ce_symbols.lua")
    print("  -> 加载所有函数、结构体、枚举符号")
    print()
    print("步骤 6: 对比 UE 源码（识别游戏自定义成员）")
    print('  python dumper7_ue_source_compare.py "D:/UE/UnrealEngine-4.26" "C:/Dumper-7/v1.0/Dumpspace"')
    print()
    print("步骤 7: 游戏更新后对比 SDK 差异")
    print('  python dumper7_sdk_diff.py "C:/Dumper-7/v1.0/Dumpspace" "C:/Dumper-7/v1.1/Dumpspace"')


# =========================================================================
# Main
# =========================================================================

def main():
    print("Dumper-7 Tools 使用示例")
    print("=" * 70)

    example_sdk_diff()
    example_ue_source_compare()
    example_vtable_db_generator()
    example_ida_import()
    example_ue_version_detect()
    example_full_workflow()

    print(f"\n{'=' * 70}")
    print("所有工具都支持 --help 参数查看详细用法:")
    print("  python dumper7_sdk_diff.py --help")
    print("  python dumper7_ue_source_compare.py --help")
    print("  python dumper7_ue_vtable_db_generator.py --help")
    print("  python dumper7_ue_version_detect.py --help")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()

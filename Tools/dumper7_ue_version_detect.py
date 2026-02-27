"""
UE Version Fingerprinter — UE 引擎版本指纹识别工具

无需注入游戏，通过分析游戏可执行文件（PE 二进制）的特征来识别 UE 引擎版本。
检测方法包括：版本字符串扫描、Build ID 识别、导入表分析、特征字符串匹配。

典型场景：
  - 在注入 Dumper-7 之前确定游戏使用的 UE 版本
  - 选择正确版本的 VTableDB 数据库
  - 快速判断目标游戏的引擎版本范围

前置条件：
  - 需要游戏的主可执行文件（.exe）或主模块（.dll）
  - 支持 64 位 PE 文件

命令行参数：
  exe_path         游戏可执行文件路径
  --json           可选，输出 JSON 格式
  --output PATH    可选，输出到文件

用法：
    python ue_version_detect.py <game.exe> [--json] [--output report.txt]

示例：
    # 检测游戏 UE 版本
    python ue_version_detect.py "C:/Games/MyGame/Binaries/Win64/MyGame-Win64-Shipping.exe"

    # JSON 格式输出
    python ue_version_detect.py "C:/Games/MyGame/MyGame.exe" --json

输出说明：
  Confidence 分为 HIGH / MEDIUM / LOW 三级
  HIGH: 找到明确的版本字符串
  MEDIUM: 通过多个间接特征推断
  LOW: 仅有少量线索
"""

from __future__ import annotations

import argparse
import json
import os
import re
import struct
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class Evidence:
    """A single piece of version evidence."""
    method: str
    detail: str
    offset: int = 0
    version: str = ""
    weight: int = 1


@dataclass
class DetectionResult:
    """Aggregated detection result."""
    file_path: str
    file_size: int
    version: str = "Unknown"
    confidence: str = "LOW"
    evidence: List[Evidence] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)


# ── PE parsing ──

def _read_pe_imports(data: bytes) -> List[str]:
    """Extract imported DLL names from a PE file."""
    dlls: List[str] = []
    try:
        if data[:2] != b"MZ":
            return dlls
        pe_off = struct.unpack_from("<I", data, 0x3C)[0]
        if data[pe_off:pe_off + 4] != b"PE\x00\x00":
            return dlls

        coff = pe_off + 4
        num_sec = struct.unpack_from("<H", data, coff + 2)[0]
        opt_sz = struct.unpack_from("<H", data, coff + 16)[0]
        opt = coff + 20

        magic = struct.unpack_from("<H", data, opt)[0]
        if magic == 0x20B:
            imp_dir_off = opt + 120
        elif magic == 0x10B:
            imp_dir_off = opt + 104
        else:
            return dlls

        imp_rva = struct.unpack_from("<I", data, imp_dir_off)[0]
        if imp_rva == 0:
            return dlls

        sec_start = opt + opt_sz
        sections = []
        for i in range(num_sec):
            s = sec_start + i * 40
            vrva = struct.unpack_from("<I", data, s + 12)[0]
            vsz = struct.unpack_from("<I", data, s + 8)[0]
            rsz = struct.unpack_from("<I", data, s + 16)[0]
            rptr = struct.unpack_from("<I", data, s + 20)[0]
            sections.append((vrva, vsz, rptr, rsz))

        def rva2off(rva: int) -> Optional[int]:
            for vrva, vsz, rptr, rsz in sections:
                if vrva <= rva < vrva + max(vsz, rsz):
                    return rptr + (rva - vrva)
            return None

        off = rva2off(imp_rva)
        if off is None:
            return dlls

        idx = 0
        while True:
            entry = off + idx * 20
            if entry + 20 > len(data):
                break
            name_rva = struct.unpack_from("<I", data, entry + 12)[0]
            if name_rva == 0:
                break
            name_off = rva2off(name_rva)
            if name_off and name_off < len(data):
                end = data.index(0, name_off) if 0 in data[name_off:name_off + 256] else name_off + 256
                dlls.append(data[name_off:end].decode("ascii", errors="replace"))
            idx += 1
    except Exception:
        pass
    return dlls


# ── Regex patterns ──

_VERSION_FULL_RE = re.compile(
    rb"([45]\.\d{1,2}\.\d{1,2})-(\d{6,12})\+\+\+UE[45]\+Release-\d+\.\d+",
)
_VERSION_SHORT_RE = re.compile(
    rb"([45]\.\d{1,2}\.\d{1,2})-(\d{6,12})",
)
_BUILD_ID_RE = re.compile(
    rb"\+\+UE([45])\+Release-(\d+\.\d+)",
)

# Import-based version hints
_IMPORT_HINTS: List[Tuple[str, str, str]] = [
    ("mimalloc.dll",  ">=5.4", "mimalloc allocator (UE 5.4+)"),
    ("jemalloc.dll",  ">=5.0", "jemalloc allocator (UE 5.x)"),
    ("libcrypto-3-x64.dll", ">=5.0", "OpenSSL 3.x (UE 5.x)"),
    ("libcrypto-1_1-x64.dll", "<=4.27", "OpenSSL 1.1 (UE 4.x)"),
    ("libssl-3-x64.dll", ">=5.0", "OpenSSL 3.x SSL (UE 5.x)"),
]

# Feature strings that hint at specific versions
_FEATURE_STRINGS: List[Tuple[bytes, str, str]] = [
    (b"FNamePool", ">=4.23", "FNamePool (UE 4.23+)"),
    (b"FFieldClass", ">=4.25", "FField system (UE 4.25+)"),
    (b"LargeWorldCoordinates", ">=5.0", "Large World Coordinates (UE 5.0+)"),
    (b"Nanite", ">=5.0", "Nanite rendering (UE 5.0+)"),
    (b"Lumen", ">=5.0", "Lumen GI (UE 5.0+)"),
    (b"WorldPartition", ">=5.0", "World Partition (UE 5.0+)"),
    (b"FObjectPtrProperty", ">=5.0", "Object pointer property (UE 5.0+)"),
    (b"MetaSoundSource", ">=5.0", "MetaSound (UE 5.0+)"),
    (b"Chaos", ">=4.26", "Chaos physics (UE 4.26+)"),
    (b"PhysX", "<=4.26", "PhysX physics (UE 4.26 and earlier)"),
]


# ── Core detection ──

def detect_version(file_path: str) -> DetectionResult:
    """Analyze a PE binary and detect its UE version."""
    file_size = os.path.getsize(file_path)
    result = DetectionResult(file_path=file_path, file_size=file_size)

    with open(file_path, "rb") as f:
        data = f.read()

    # 1. PE import analysis
    result.imports = _read_pe_imports(data)
    imports_lower = [d.lower() for d in result.imports]

    for dll_name, ver_hint, desc in _IMPORT_HINTS:
        if dll_name.lower() in imports_lower:
            result.evidence.append(Evidence(
                method="IMPORT", detail=desc,
                version=ver_hint, weight=2,
            ))

    # 2. Full version string scan (highest confidence)
    for m in _VERSION_FULL_RE.finditer(data):
        ver_str = m.group(1).decode("ascii")
        changelist = m.group(2).decode("ascii")
        result.evidence.append(Evidence(
            method="STRING",
            detail=f"{ver_str}-{changelist}+++UE Release",
            offset=m.start(), version=ver_str, weight=10,
        ))

    # 3. Short version string scan
    if not any(e.weight >= 10 for e in result.evidence):
        seen_versions = set()
        for m in _VERSION_SHORT_RE.finditer(data):
            ver_str = m.group(1).decode("ascii")
            if ver_str in seen_versions:
                continue
            seen_versions.add(ver_str)
            result.evidence.append(Evidence(
                method="STRING",
                detail=f"Version string: {ver_str}",
                offset=m.start(), version=ver_str, weight=5,
            ))

    # 4. Build ID scan
    for m in _BUILD_ID_RE.finditer(data):
        ue_gen = m.group(1).decode("ascii")
        ver_branch = m.group(2).decode("ascii")
        result.evidence.append(Evidence(
            method="BUILD_ID",
            detail=f"++UE{ue_gen}+Release-{ver_branch}",
            offset=m.start(), version=ver_branch, weight=7,
        ))

    # 5. Feature string scan
    for pattern, ver_hint, desc in _FEATURE_STRINGS:
        if pattern in data:
            idx = data.index(pattern)
            result.evidence.append(Evidence(
                method="FEATURE",
                detail=desc,
                offset=idx, version=ver_hint, weight=1,
            ))

    # ── Aggregate results ──
    if not result.evidence:
        return result

    # Pick the best exact version from weighted evidence
    version_scores: Dict[str, int] = {}
    for e in result.evidence:
        v = e.version
        if v.startswith(">=") or v.startswith("<="):
            continue  # hints, not exact versions
        version_scores[v] = version_scores.get(v, 0) + e.weight

    if version_scores:
        best = max(version_scores, key=version_scores.get)  # type: ignore[arg-type]
        best_weight = version_scores[best]
        result.version = best

        if best_weight >= 10:
            result.confidence = "HIGH"
        elif best_weight >= 5:
            result.confidence = "MEDIUM"
        else:
            result.confidence = "LOW"
    else:
        # Only range hints available — try to narrow down
        ge_versions: List[str] = []
        le_versions: List[str] = []
        for e in result.evidence:
            if e.version.startswith(">="):
                ge_versions.append(e.version[2:])
            elif e.version.startswith("<="):
                le_versions.append(e.version[2:])

        if ge_versions:
            best_ge = max(ge_versions, key=lambda v: [int(x) for x in v.split(".")])
            result.version = f">={best_ge}"
            result.confidence = "LOW"
        elif le_versions:
            best_le = min(le_versions, key=lambda v: [int(x) for x in v.split(".")])
            result.version = f"<={best_le}"
            result.confidence = "LOW"

    return result


# ── Report formatting ──

def format_report(result: DetectionResult) -> str:
    """Format detection result as human-readable text."""
    lines: List[str] = []
    lines.append("UE Version Detection Report")
    lines.append("=" * 40)
    lines.append(f"File: {os.path.basename(result.file_path)}")
    lines.append(f"Path: {result.file_path}")
    lines.append(f"Size: {result.file_size / (1024 * 1024):.1f} MB")
    lines.append("")
    lines.append(f"Detected Version: {result.version}")
    lines.append(f"Confidence: {result.confidence}")
    lines.append("")

    if result.evidence:
        lines.append("Evidence:")
        for e in sorted(result.evidence, key=lambda x: -x.weight):
            off_str = f" at offset 0x{e.offset:X}" if e.offset else ""
            lines.append(f"  [{e.method}] {e.detail}{off_str} (weight={e.weight})")
        lines.append("")

    if result.imports:
        ue_related = [d for d in result.imports if any(
            k in d.lower() for k in ("ue4", "ue5", "unreal", "mimalloc", "jemalloc",
                                      "libcrypto", "libssl", "steam")
        )]
        if ue_related:
            lines.append("Notable imports:")
            for d in ue_related:
                lines.append(f"  - {d}")
            lines.append("")

    return "\n".join(lines)


def result_to_dict(result: DetectionResult) -> dict:
    """Convert detection result to a JSON-serializable dict."""
    return {
        "file_path": result.file_path,
        "file_size": result.file_size,
        "version": result.version,
        "confidence": result.confidence,
        "evidence": [
            {
                "method": e.method,
                "detail": e.detail,
                "offset": e.offset,
                "version": e.version,
                "weight": e.weight,
            }
            for e in result.evidence
        ],
        "imports": result.imports,
    }


# ── CLI ──

def main() -> None:
    parser = argparse.ArgumentParser(
        description="UE Version Fingerprinter — 通过分析 PE 二进制特征识别 UE 引擎版本",
    )
    parser.add_argument("exe_path", help="游戏可执行文件路径 (.exe / .dll)")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    parser.add_argument("--output", metavar="PATH", help="输出到文件")
    args = parser.parse_args()

    if not os.path.isfile(args.exe_path):
        print(f"Error: file not found: {args.exe_path}", file=sys.stderr)
        sys.exit(1)

    result = detect_version(args.exe_path)

    if args.json:
        output = json.dumps(result_to_dict(result), indent=2, ensure_ascii=False)
    else:
        output = format_report(result)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"Report written to {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()

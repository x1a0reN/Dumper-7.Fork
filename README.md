# Dumper-7.Fork

本 `README` 仅记录本版本相对原版 `Dumper-7` 的增量能力，不再重复原版说明。

## 增量功能

- `PostRender` 虚表索引自动识别
  - 新增 `UGameViewportClient::PostRender` 与 `AHUD::PostRender` 的运行时检测。
  - 支持 `Dumper-7.ini` 的 `[PostRender]` 手动覆盖：
    - `GVCPostRenderIndex`
    - `HUDPostRenderIndex`
  - 检测结果写入生成 SDK：
    - `Offsets::GVCPostRenderIdx`
    - `Offsets::HUDPostRenderIdx`

- SDK 函数偏移注释
  - 在生成的 `*_classes.hpp` 函数声明后，追加模块偏移注释：
    - `XXX.exe+0x123456`

- CppSDK 工程模板生成
  - 自动生成 `Inject` / `Proxy` 两套工程模板（`.slnx + .vcxproj + Main.cpp`）。
  - 支持直接编译 DLL，并包含可运行的 Hook 示例模板。

- `VTHook` 工具库生成
  - 自动生成 `VTHook.hpp`。
  - 提供 `SetVirtualFunction` 与 `VTableHook`（RAII）封装。

- Dumpspace 扩展导出
  - 导出 `VTableInfo.json`。
  - 导出 `ce_symbols.lua`。
  - 导出 `DataTables/*.json`。
  - 导出 IDA 导入脚本（由内置脚本生成到 Dumpspace 目录）。

- 工具链增强（`Tools`）
  - IDA 符号导入
  - SDK 差异对比
  - UE 源码与 Dump 结构对比
  - UE 版本离线识别
  - UE 虚表数据库生成

## Tools 命名规范

本版本统一使用 `dumper7_*.py`：

- `Tools/dumper7_examples.py`
- `Tools/dumper7_ida_import.py`
- `Tools/dumper7_sdk_diff.py`
- `Tools/dumper7_ue_source_compare.py`
- `Tools/dumper7_ue_version_detect.py`
- `Tools/dumper7_ue_vtable_db_generator.py`

## 配置增量

`Dumper-7.ini` 新增：

```ini
[PostRender]
GVCPostRenderIndex=-1
HUDPostRenderIndex=-1
```
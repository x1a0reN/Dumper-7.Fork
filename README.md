
# Dumper-7

SDK Generator for all Unreal Engine games. Supported versions are all of UE4 and UE5.

## How to use

- Compile the dll in x64-Release
- Inject the dll into your target game
- The SDK is generated into the path specified by `Settings::SDKGenerationPath`, by default this is `C:\\Dumper-7`
- **See [UsingTheSDK](UsingTheSDK.md) for a guide to get started, or to migrate from an old SDK.**

## Fork 增强功能（相对原版）

本仓库是定向增强版，核心新增能力如下：

- PostRender 虚表索引自动识别：
  - 新增 `UGameViewportClient::PostRender` 与 `AHUD::PostRender` 双通道识别。
  - 支持 `Dumper-7.ini` 的 `[PostRender]` 手动覆盖（`GVCPostRenderIndex` / `HUDPostRenderIndex`）。
  - 识别结果写入生成 SDK 的 `Offsets::GVCPostRenderIdx` / `Offsets::HUDPostRenderIdx`。
- SDK 函数地址注释增强：
  - 在生成的 `*_classes.hpp` 函数声明后追加模块偏移注释，如 `XXX.exe+0x123456`。
- CppSDK 项目一键可编译：
  - 生成 `Inject` 与 `Proxy` 两套工程模板（`.slnx + .vcxproj + Main.cpp`）。
  - 支持直接以 DLL 方式编译并包含 Hook 示例。
- VTable Hook 工具库：
  - 自动生成 `VTHook.hpp`，提供 `SetVirtualFunction` 和 `VTableHook`（RAII）封装。
- Dumpspace 扩展导出：
  - 内置 IDA 导入脚本嵌入与导出。
  - 新增 `VTableInfo.json`、`ce_symbols.lua`、`DataTables/*.json` 导出能力。
- 分析辅助工具集（Tools）：
  - IDA 导入、SDK 差异分析、UE 源码对比、UE 版本识别、VTable 数据库生成。

## Tools 脚本命名规范

本 fork 统一采用 `dumper7_*.py` 命名，脚本如下：

- `Tools/dumper7_examples.py`
- `Tools/dumper7_ida_import.py`
- `Tools/dumper7_sdk_diff.py`
- `Tools/dumper7_ue_source_compare.py`
- `Tools/dumper7_ue_version_detect.py`
- `Tools/dumper7_ue_vtable_db_generator.py`

示例：

```bash
python Tools/dumper7_examples.py
python Tools/dumper7_sdk_diff.py <old_dumpspace_dir> <new_dumpspace_dir>
python Tools/dumper7_ue_version_detect.py <game.exe>
```

## Support Me

KoFi: https://ko-fi.com/fischsalat \
Patreon: https://www.patreon.com/u119629245

LTC (LTC-network): `LLtXWxDbc5H9d96VJF36ZpwVX6DkYGpTJU` \
BTC (Bitcoin): `1DVDUMcotWzEG1tyd1FffyrYeu4YEh7spx` \
USDT (Tron (TRC20)): `TWHDoUr2H52Gb2WYdZe7z1Ct316gMg64ps`

## Overriding Offsets

- ### Only override any offsets if the generator doesn't find them, or if they are incorrect
- All overrides are made in **Generator::InitEngineCore()** inside of **Generator.cpp**

- GObjects (see [GObjects-Layout](#overriding-gobjects-layout) too)
  ```cpp
  ObjectArray::Init(/*GObjectsOffset*/, /*ChunkSize*/, /*bIsChunked*/);
  ```
  ```cpp
  /* Make sure only to use types which exist in the sdk (eg. uint8, uint64) */
  InitObjectArrayDecryption([](void* ObjPtr) -> uint8* { return reinterpret_cast<uint8*>(uint64(ObjPtr) ^ 0x8375); });
  ```
- FName::AppendString
  - Forcing GNames:
    ```cpp
    FName::Init(/*bForceGNames*/); // Useful if the AppendString offset is wrong
    ```
  - Overriding the offset:
    ```cpp
    FName::Init(/*OverrideOffset, OverrideType=[AppendString, ToString, GNames], bIsNamePool*/);
    ```
- ProcessEvent
  ```cpp
  Off::InSDK::InitPE(/*PEIndex*/);
  ```
## Overriding GObjects-Layout
- Only add a new layout if GObjects isn't automatically found for your game.
- Layout overrides are at roughly line 30 of `ObjectArray.cpp`
- For UE4.11 to UE4.20 add the layout to `FFixedUObjectArrayLayouts`
- For UE4.21 and higher add the layout to `FChunkedFixedUObjectArrayLayouts`
- **Examples:**
  ```cpp
  FFixedUObjectArrayLayout // Default UE4.11 - UE4.20
  {
      .ObjectsOffset = 0x0,
      .MaxObjectsOffset = 0x8,
      .NumObjectsOffset = 0xC
  }
  ```
  ```cpp
  FChunkedFixedUObjectArrayLayout // Default UE4.21 and above
  {
      .ObjectsOffset = 0x00,
      .MaxElementsOffset = 0x10,
      .NumElementsOffset = 0x14,
      .MaxChunksOffset = 0x18,
      .NumChunksOffset = 0x1C,
  }
  ```

## Config File
You can optionally dynamically change settings through a `Dumper-7.ini` file, instead of modifying `Settings.h`.
- **Per-game**: Create `Dumper-7.ini` in the same directory as the game's exe file.
- **Global**: Create `Dumper-7.ini` under `C:\Dumper-7`

Example:
```ini
[Settings]
SleepTimeout=100
SDKNamespaceName=MyOwnSDKNamespace

[PostRender]
GVCPostRenderIndex=-1
HUDPostRenderIndex=-1
```
## Issues

If you have any issues using the Dumper, please create an Issue on this repository\
and explain the problem **in detail**.

- Should your game be crashing while dumping, attach Visual Studios' debugger to the game and inject the Dumper-7.dll in debug-configuration.
Then include screenshots of the exception causing the crash, a screenshot of the callstack, as well as the console output.

- Should there be any compiler-errors in the SDK please send screenshots of them. Please note that **only build errors** are considered errors, as Intellisense often reports false positives.
Make sure to always send screenshots of the code causing the first error, as it's likely to cause a chain-reaction of errors.

- Should your own dll-project crash, verify your code thoroughly to make sure the error actually lies within the generated SDK.

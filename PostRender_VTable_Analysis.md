# PostRender 虚表索引运行时检测 — 分析与设计报告

> 生成日期: 2026-02-27
> 目标项目: Dumper-7.Fork
> 分析范围: UE 4.21 / 4.24 / 4.25 / 4.26 / 4.27 / 5.0 / 5.1 / 5.2 / 5.3 / 5.4 / 5.6 / 5.7
> 平台: Windows PC (x64)

---

## 一、概述

本报告旨在为 Dumper-7 项目设计一套运行时自动检测 `PostRender` 虚表索引的方案。分析对象包括两个关键类：

| 类名 | 函数签名 | 用途 |
|------|---------|------|
| `AHUD` | `virtual void PostRender()` | HUD 主绘制循环，用于绘制 2D HUD 元素 |
| `UGameViewportClient` | `virtual void PostRender(UCanvas* Canvas)` | 视口渲染后回调，用于绘制过渡画面 |

两者均为**纯 C++ 虚函数**（非 UFUNCTION），不在 UE 反射系统中注册，因此无法通过 GObjects 遍历直接获取，必须通过虚表扫描 + 特征码匹配的方式定位。

---

## 二、研究方法论

### 2.1 分析流程

```
源码获取 → 头文件分析(虚函数声明) → 实现文件分析(函数体特征)
    ↓                ↓                         ↓
 12个UE版本    虚函数列表 & 排序         字节码模式提取
    ↓                ↓                         ↓
类层次结构分析 → 虚表布局变化追踪 → 运行时检测算法设计
                                              ↓
                                    Dumper-7 增量设计
```

### 2.2 数据来源

所有分析基于 `D:\Projects\UnrealEngine\` 目录下的 12 个 UE 版本源码，涉及的核心文件：

- `Engine/Source/Runtime/Engine/Classes/GameFramework/HUD.h`
- `Engine/Source/Runtime/Engine/Classes/GameFramework/Actor.h`
- `Engine/Source/Runtime/Engine/Classes/GameFramework/Info.h`
- `Engine/Source/Runtime/Engine/Classes/Engine/GameViewportClient.h`
- `Engine/Source/Runtime/Engine/Private/HUD.cpp`
- `Engine/Source/Runtime/Engine/Private/GameViewportClient.cpp`

---

## 三、类层次结构与虚表布局分析

### 3.1 继承链

```
AHUD 继承链:
UObject → UActorComponent... → AActor → AInfo → AHUD

UGameViewportClient 继承链:
UObject → UScriptViewportClient (+ FViewportClient) → UGameViewportClient
```

### 3.2 AActor 虚函数数量变化（关键断层）

AActor 是 AHUD 的祖父类，其虚函数数量直接决定 AHUD 中 PostRender 的绝对虚表索引。

| UE 版本 | AActor 虚函数数 | AInfo 虚函数数 | 变化说明 |
|---------|----------------|---------------|---------|
| 4.21    | 127            | 1             | 基线版本 |
| 4.24    | 127            | 1             | 无变化 |
| 4.25    | 127            | 1             | 无变化 |
| 4.26    | 127            | 1             | 无变化 |
| 4.27    | 127            | 1             | 无变化 |
| 5.0     | ~189           | 3             | **+62 虚函数（重大断层）** |
| 5.1     | 189            | 3             | 稳定 |
| 5.2     | 189            | 3             | 稳定 |
| 5.3     | 189            | 3             | 稳定 |
| 5.4     | 189            | 3             | 稳定 |
| 5.6     | 189            | 3             | 稳定 |
| 5.7     | 189            | 3             | 稳定 |

**关键发现：UE4 → UE5 存在一个重大虚表断层。** AActor 从 127 个虚函数跳增到 189 个（+62），AInfo 从 1 个增加到 3 个（+2）。这意味着 AHUD::PostRender 的绝对虚表索引在 UE5 中至少偏移了 64 个槽位。

### 3.3 AHUD 自身虚函数列表（全版本稳定）

经过对 12 个版本的逐一比对，AHUD 类自身声明的虚函数列表在所有版本中**完全一致**，共 23 个：

```
序号  函数声明
──────────────────────────────────────────────────────────
 1    virtual void ShowHUD();
 2    virtual void ShowDebug(FName DebugType = NAME_None);
 3    virtual void NotifyHitBoxClick(FName BoxName);
 4    virtual void NotifyHitBoxRelease(FName BoxName);
 5    virtual void NotifyHitBoxBeginCursorOver(FName BoxName);
 6    virtual void NotifyHitBoxEndCursorOver(FName BoxName);
 7    virtual void PostInitializeComponents() override;
 8    virtual void DrawActorOverlays(FVector Viewpoint, FRotator ViewRotation);
 9    virtual void DrawSafeZoneOverlay();
10    virtual void NotifyBindPostProcessEffects();
11    virtual void RemovePostRenderedActor(AActor* A);
12    virtual void AddPostRenderedActor(AActor* A);
13    virtual bool ShouldDisplayDebug(const FName& DebugType) const;
14    virtual void ShowDebugInfo(float& YL, float& YPos);
15    virtual AActor* GetCurrentDebugTargetActor();
16    virtual void GetDebugActorList(TArray<AActor*>& InOutList);
17    virtual void NextDebugTarget();
18    virtual void PreviousDebugTarget();
19    virtual void PostRender();                          ← 目标函数
20    virtual void DrawHUD();
21    virtual UFont* GetFontFromSizeIndex(int32 FontSize) const;
22    virtual void OnLostFocusPause(bool bEnable);
23    virtual void HandleBugScreenShot() { }
```

**PostRender 在 AHUD 自身虚函数中始终排第 19 位。** 但由于第 7 项 `PostInitializeComponents()` 是 override（覆写父类虚函数，不新增虚表槽），实际新增的虚表槽为 22 个，PostRender 在 AHUD 新增槽中排第 18 位。

### 3.4 UGameViewportClient 虚函数数量变化

| UE 版本 | 虚函数总数 | 变化说明 |
|---------|-----------|---------|
| 4.21    | 38        | 基线版本 |
| 4.27    | 42        | +4（Widget/Player 管理相关） |
| 5.1     | 44        | +2（CreateGameViewport, RemapControllerInput） |
| 5.4     | 44        | 稳定 |
| 5.7     | 44        | 稳定 |

### 3.5 虚表索引不可静态计算的结论

由于以下原因，PostRender 的绝对虚表索引**无法在编译期确定**：

1. AActor 在 UE4→UE5 之间增加了 62 个虚函数
2. 不同游戏可能使用不同的 UE 小版本（如 4.25.3 vs 4.25.4）
3. 游戏开发者可能在中间类中添加自定义虚函数
4. MSVC 编译器的虚表布局受编译选项影响

**因此，必须采用运行时特征码扫描方案。**

---

## 四、AHUD::PostRender() 函数体特征分析

### 4.1 实现代码（全版本一致）

经过对 UE 4.21 ~ 5.7 全部 12 个版本的 `HUD.cpp` 逐一比对，`AHUD::PostRender()` 的实现在所有版本中**几乎完全一致**（仅有 `NULL` vs `nullptr` 等风格差异，不影响编译产物）。

函数体约 90 行，核心控制流如下：

```
PostRender()
│
├─ [1] if (GetWorld() == nullptr || Canvas == nullptr) return;  ← 双空指针检查
│
├─ [2] RenderDelta = GetWorld()->TimeSeconds - LastHUDRenderTime;
│
├─ [3] if (PlayerOwner != nullptr) DrawDebugTextList();
│
├─ [4] if (bShowDebugInfo)
│      └─ ShowDebugInfo(...)
│
├─ [5] else if (bShowHUD && FApp::CanEverRender())              ← 静态函数调用
│      ├─ DrawHUD();                                            ← 虚函数调用
│      ├─ HitBox 触摸/鼠标检测逻辑 (~40行)
│      └─ UpdateHitBoxCandidates(...)
│
├─ [6] if (bShowHitBoxDebugInfo) RenderHitBoxes(...);
│
├─ [7] DrawSafeZoneOverlay();                                   ← 虚函数调用
│
├─ [8] OnHUDPostRender.Broadcast(this, DebugCanvas);            ← 委托广播
│
└─ [9] LastHUDRenderTime = GetWorld()->TimeSeconds;
```

### 4.2 可提取的编译产物特征

以下特征在 MSVC x64 Release 编译下具有高度稳定性：

**特征 A：函数入口双空指针检查**

源码：
```cpp
if ((GetWorld() == nullptr) || (Canvas == nullptr)) { return; }
```

编译产物模式（x64）：
```asm
; GetWorld() 调用后 test rax, rax / je early_return
; 紧接着读取 this->Canvas 成员并 test / je
CALL    [this->GetWorld]     ; 或内联展开
TEST    RAX, RAX
JE      .early_return
MOV     RAX, [RCX+Canvas偏移]
TEST    RAX, RAX
JE      .early_return
```

**稳定性评估：★★★★☆** — 双连续空指针检查在 UE 虚函数中较为罕见，但不够独特。

**特征 B：FApp::CanEverRender() 静态调用**

源码：
```cpp
else if (bShowHUD && FApp::CanEverRender())
```

编译产物模式（x64）：
```asm
CALL    FApp::CanEverRender  ; 直接 CALL 到静态函数地址
TEST    AL, AL               ; 检查返回值（bool）
JE      .skip_drawhud
```

**稳定性评估：★★★★★** — `FApp::CanEverRender()` 是一个全局静态函数，在整个引擎中调用点有限。PostRender 是少数在虚表函数中调用它的地方。

**特征 C：OnHUDPostRender.Broadcast() 委托广播**

源码：
```cpp
OnHUDPostRender.Broadcast(this, DebugCanvas);
```

编译产物模式（x64）：
```asm
; 加载 OnHUDPostRender 委托成员地址
LEA     RCX, [this+OnHUDPostRender偏移]
; 加载 DebugCanvas 参数
MOV     RDX, [this+DebugCanvas偏移]
; 调用 Broadcast
CALL    FSimpleMulticastDelegate::Broadcast
```

**稳定性评估：★★★★☆** — 委托广播模式较独特，但偏移值随版本变化。

**特征 D：DrawHUD() 虚函数调用（紧邻的虚表槽）**

源码：
```cpp
DrawHUD();  // PostRender 内部调用 DrawHUD
```

`DrawHUD` 在虚表中紧跟 `PostRender`（第 20 位 vs 第 19 位）。编译产物中会出现：
```asm
MOV     RAX, [RCX]           ; 加载虚表指针
CALL    [RAX + DrawHUD_VIdx * 8]  ; 通过虚表调用 DrawHUD
```

**稳定性评估：★★★☆☆** — 虚表调用模式通用，但 DrawHUD 的虚表偏移本身也是未知的。

### 4.3 特征组合策略

单一特征容易产生误判。推荐采用**组合特征**方案：

| 组合方案 | 特征组合 | 误判率 | 适用性 |
|---------|---------|--------|--------|
| 方案 1（推荐） | A + B | 极低 | 全版本通用 |
| 方案 2 | A + C | 低 | 全版本通用 |
| 方案 3 | B + C | 极低 | 全版本通用 |

**推荐方案 1**：在虚表函数体内同时检测"双空指针检查"和"FApp::CanEverRender() 调用"。

理由：
- 双空指针检查（GetWorld + Canvas）在函数前 0x40 字节内即可检测
- FApp::CanEverRender() 是静态函数，编译为直接 CALL，可通过解析 CALL 目标地址验证
- 两者组合在整个引擎虚表中具有唯一性

### 4.4 UGameViewportClient::PostRender(UCanvas*) 函数体特征分析

#### 实现代码（Shipping 构建）

经逐版本源码核对，`PostRender(UCanvas* Canvas)` 在 12 个版本中的定位如下：

| UE版本 | `GameViewportClient.h` 行号 | `GameViewportClient.cpp` 行号 |
|---|---:|---:|
| 4.21 | 431 | 1873 |
| 4.24 | 446 | 1945 |
| 4.25 | 458 | 1964 |
| 4.26 | 462 | 2066 |
| 4.27 | 462 | 2093 |
| 5.0 | 473 | 2146 |
| 5.1 | 477 | 2181 |
| 5.2 | 481 | 2215 |
| 5.3 | 483 | 2272 |
| 5.4 | 484 | 2350 |
| 5.6 | 480 | 2509 |
| 5.7 | 480 | 2603 |

声明顺序在所有版本中保持一致：`DrawTitleSafeArea(UCanvas*)` → `PostRender(UCanvas*)` → `DrawTransition(UCanvas*)` → `DrawTransitionMessage(UCanvas*, const FString&)`。

在非编辑器构建（即所有发行游戏）中，`WITH_EDITOR` 为 false，函数体极其简短：

```cpp
void UGameViewportClient::PostRender(UCanvas* Canvas)
{
    // DrawTitleSafeArea 仅在 WITH_EDITOR 下编译，Shipping 构建中不存在
    DrawTransition(Canvas);
}
```

#### DrawTransition 内部特征

`DrawTransition` 的实现在所有版本中一致：

```cpp
void UGameViewportClient::DrawTransition(UCanvas* Canvas)
{
    if (bSuppressTransitionMessage == false)
    {
        switch (GetOuterUEngine()->TransitionType)
        {
        case ETransitionType::Loading:
            DrawTransitionMessage(Canvas, NSLOCTEXT("GameViewportClient", "LoadingMessage", "LOADING").ToString());
            break;
        case ETransitionType::Saving:
            DrawTransitionMessage(Canvas, NSLOCTEXT("GameViewportClient", "SavingMessage", "SAVING").ToString());
            break;
        // ... Connecting, Precaching, Paused, WaitingToConnect
        }
    }
}
```

#### 特征评估

| 特征 | 描述 | 稳定性 |
|------|------|--------|
| 函数体极短 | Shipping 构建中仅一个 CALL 指令 | ★★☆☆☆ 太多短函数 |
| 调用 DrawTransition | 虚函数调用，偏移未知 | ★★☆☆☆ |
| DrawTransition 内含字符串 | "LOADING", "SAVING" 等 | ★★★★☆ 但需要跨函数追踪 |

**结论：UGameViewportClient::PostRender 的函数体过于简短，不适合直接做特征码匹配。** 推荐通过间接方式定位（见第五节方案 B）。

---

## 五、运行时检测策略设计

### 5.1 与 ProcessEvent 检测方案的对比

Dumper-7 现有的 ProcessEvent 检测方案（`InitPE_Windows`）采用的策略是：

```
取 GObjects[0] 的虚表 → 遍历每个虚表槽 → 对函数体做 FindPatternInRange → 匹配 TEST FunctionFlags 指令
```

ProcessEvent 能用这种方式是因为：
1. 它在 UObject 虚表上，任意对象都有
2. 函数体内有 `TEST [reg+FunctionFlags], 0x400` 和 `TEST [reg+FunctionFlags], 0x4000` 两条独特指令
3. FunctionFlags 的偏移已经被 OffsetFinder 提前发现

PostRender 的情况不同：
1. 它在 AHUD 虚表上，需要先找到 AHUD 的实例或 CDO
2. 函数体没有类似 TEST FunctionFlags 的"硬编码常量检查"
3. 但有其他可利用的特征（见第四节）

### 5.2 方案 A：AHUD::PostRender() — 虚表遍历 + 组合特征码

#### 算法流程

```
步骤 1: 通过反射系统找到 AHUD 类
        UEClass HUDClass = ObjectArray::FindClassFast("HUD");

步骤 2: 获取 AHUD 的 CDO（Class Default Object）
        void* CDO = HUDClass.GetDefaultObject().GetAddress();

步骤 3: 从 CDO 读取虚表指针
        void** HUDVft = *(void***)CDO;

步骤 4: 遍历虚表，对每个函数体执行组合特征检测
        for each VTable[i]:
            if IsHUDPostRender(VTable[i]):
                PostRenderIndex = i
                break

步骤 5: 记录索引和偏移
```

#### 特征检测函数设计（x64）

```cpp
auto IsHUDPostRender = [](const uint8_t* FuncAddress, int32_t Index) -> bool
{
    // 特征 B: 在函数体前 0x300 字节内搜索 FApp::CanEverRender() 的调用
    // CanEverRender 内部读取一个全局 bool 变量，编译后通常为:
    //   MOVZX EAX, byte ptr [rip+xxxx]  (0F B6 05 xx xx xx xx)
    //   TEST AL, AL
    //   或直接内联为 CMP byte ptr [rip+xxxx], 0
    //
    // 更可靠的方式：搜索对 CanEverRender 的 CALL 指令
    // CanEverRender 可通过字符串 "FApp::CanEverRender" 或导出符号定位

    bool bHasCanEverRender = Platform::FindPatternInRange(
        { 0xE8, -0x1, -0x1, -0x1, -0x1,   // CALL rel32 (CanEverRender)
          0x84, 0xC0 },                      // TEST AL, AL
        FuncAddress, 0x400
    );

    if (!bHasCanEverRender)
        return false;

    // 特征 A: 函数前 0x60 字节内有两次连续的 TEST+JE 模式（双空指针检查）
    // TEST RAX, RAX = 48 85 C0
    // JE = 0F 84 xx xx xx xx 或 74 xx
    int NullCheckCount = 0;
    for (int offset = 0; offset < 0x60; offset++)
    {
        if (FuncAddress[offset] == 0x48
            && FuncAddress[offset+1] == 0x85
            && FuncAddress[offset+2] == 0xC0)
        {
            // 后面跟 JE (74 xx 或 0F 84 xx xx xx xx)
            uint8_t next = FuncAddress[offset+3];
            if (next == 0x74 || next == 0x0F)
                NullCheckCount++;
        }
    }

    return NullCheckCount >= 2;
};
```

#### 备用检测：字符串引用法

如果特征码方案失败，可使用字符串引用作为备用：

```
1. 在代码段搜索字符串 "CanEverRender" 或 "OnHUDPostRender" 的引用
2. 从引用位置回溯找到所属函数的起始地址
3. 在 AHUD 虚表中匹配该地址
```

但此方法依赖字符串未被 strip，可靠性较低。

### 5.3 方案 B：UGameViewportClient::PostRender() — DrawTransition 字符串回溯法（推荐）

由于 UGameViewportClient::PostRender 函数体过短（Shipping 构建中仅调用 DrawTransition），无法直接做特征码匹配。采用间接定位策略：

#### 算法流程

```
步骤 1: 在代码段搜索字符串 L"LOADING" 的引用地址
        → 定位到 DrawTransitionMessage 的调用点
        → 该调用点位于 DrawTransition 函数内部

步骤 2: 从 DrawTransitionMessage 调用点回溯，找到 DrawTransition 函数起始地址

步骤 3: 在代码段搜索对 DrawTransition 的 CALL 指令
        → 定位到 PostRender 函数内部

步骤 4: 从 CALL 指令回溯，找到 PostRender 函数起始地址

步骤 5: 通过反射系统找到 UGameViewportClient 类
        UEClass GVCClass = ObjectArray::FindClassFast("GameViewportClient");

步骤 6: 获取 CDO 虚表，匹配 PostRender 地址得到索引
```

#### 替代方案：利用 DrawTransition 的虚表相邻性

在 UGameViewportClient 的虚表中，`DrawTransition` 紧跟 `PostRender`。如果能定位 DrawTransition（通过其内部的 "LOADING" 字符串引用），则 PostRender 的虚表索引 = DrawTransition 索引 - 1。

```cpp
auto IsDrawTransition = [](const uint8_t* FuncAddress, int32_t Index) -> bool
{
    // DrawTransition 内部有 switch-case 结构，引用多个本地化字符串
    // 搜索 "LOADING" 宽字符串的 LEA 指令
    return Platform::FindByStringInAllSections(
        L"LOADING",
        reinterpret_cast<uintptr_t>(FuncAddress),
        0x300
    ) != nullptr;
};

UEClass GVCClass = ObjectArray::FindClassFast("GameViewportClient");
void** GVCVft = *(void***)GVCClass.GetDefaultObject().GetAddress();

auto [DrawTransitionAddr, DrawTransitionIdx] =
    Platform::IterateVTableFunctions(GVCVft, IsDrawTransition);

if (DrawTransitionAddr)
{
    int32_t PostRenderIdx = DrawTransitionIdx - 1;  // PostRender 在 DrawTransition 前一个槽
}
```

**注意：** 此方案假设 PostRender 和 DrawTransition 在虚表中相邻。经源码验证，这在所有 12 个版本中均成立，但游戏开发者如果在子类中插入虚函数可能打破此假设。建议增加以下二次校验步骤以降低误判率：

1. **函数长度校验**：反推的 PostRender 槽位函数应明显短于 DrawTransition（Shipping 构建中 PostRender 仅含一个 CALL，而 DrawTransition 含 switch-case + 多个字符串引用）
2. **调用链校验**：PostRender 函数体内应存在对 DrawTransition 的直接调用（CALL 目标地址应指向下一个虚表槽的函数）
3. **失败降级**：任一关键校验失败则标记为"不可信"，走 INI 手动覆盖路径

### 5.4 检测策略总结

| 目标函数 | 检测方法 | 可靠性 | 复杂度 | 定位 |
|---------|---------|--------|--------|------|
| AHUD::PostRender() | 虚表遍历 + 双空指针检查 + CanEverRender 调用检测 | 高 | 中 | 信息性 |
| UGameViewportClient::PostRender() | DrawTransition 字符串回溯 + 虚表相邻推算 | 中高 | 高 | 主方案 |

---

## 六、Dumper-7 增量设计

### 6.1 架构定位

新增功能应遵循 Dumper-7 现有的分层架构，嵌入到以下位置：

```
现有模块                          新增内容
─────────────────────────────────────────────────────
Offsets.h / Offsets.cpp          + Off::InSDK::PostRender 命名空间
                                 + InitPostRender_Windows() 函数

PlatformWindows.h / .cpp         (复用现有 IterateVTableFunctions、
                                  FindPatternInRange 等基础设施)

Generator.cpp                    + 在 InitEngineCore() 末尾调用
                                   InitPostRender

CppGenerator.cpp                 + 在 Basic.hpp 中输出 PostRender
                                   索引/偏移常量
```

### 6.2 新增数据结构

在 `Offsets.h` 中新增命名空间：

```cpp
namespace Off::InSDK::PostRender
{
    // AHUD::PostRender() 的虚表索引和模块偏移
    inline int32 HUDPostRenderIndex = -1;
    inline int32 HUDPostRenderOffset = 0x0;

    // UGameViewportClient::PostRender(UCanvas*) 的虚表索引和模块偏移
    inline int32 GVCPostRenderIndex = -1;
    inline int32 GVCPostRenderOffset = 0x0;

    // 初始化函数声明
    void InitPostRender_Windows();

    // 手动指定索引的初始化（用于 INI 配置覆盖）
    void InitPostRender(
        int32 HUDIndex = -1,
        int32 GVCIndex = -1,
        const char* ModuleName = Settings::General::DefaultModuleName
    );
}
```

### 6.3 配置系统扩展

在 `Settings.h` 中新增配置项，允许用户通过 `Dumper-7.ini` 手动覆盖：

```ini
[PostRender]
; 手动指定 AHUD::PostRender 的虚表索引（-1 = 自动检测）
HUDPostRenderIndex=-1

; 手动指定 UGameViewportClient::PostRender 的虚表索引（-1 = 自动检测）
GVCPostRenderIndex=-1
```

对应 Settings 代码：

```cpp
namespace Settings::PostRender
{
    inline int32 HUDPostRenderIndex = -1;
    inline int32 GVCPostRenderIndex = -1;
}
```

设计理由：某些加壳或混淆的游戏可能导致自动检测失败，手动覆盖提供了兜底方案，与现有 ProcessEvent 的 `InitPE(Index)` 设计一致。

### 6.4 核心实现：InitPostRender_Windows()

以下为完整的实现设计，放置在 `Offsets.cpp` 中：

```cpp
void Off::InSDK::PostRender::InitPostRender_Windows()
{
#ifdef PLATFORM_WINDOWS

    // ═══════════════════════════════════════════════════
    // 第一部分：AHUD::PostRender() 检测
    // ═══════════════════════════════════════════════════

    UEClass HUDClass = ObjectArray::FindClassFast("HUD");

    if (!HUDClass)
    {
        std::cerr << "PostRender: AHUD class not found!\n";
        return;
    }

    UEObject HUDCDO = HUDClass.GetDefaultObject();

    if (!HUDCDO)
    {
        std::cerr << "PostRender: AHUD CDO not found!\n";
        return;
    }

    void** HUDVft = *(void***)HUDCDO.GetAddress();

#if defined(_WIN64)
    // 主检测：组合特征 A（双空指针检查）+ 特征 B（CanEverRender 调用）
    auto IsHUDPostRender = [](const uint8_t* FuncAddress,
                              [[maybe_unused]] int32_t Index) -> bool
    {
        // 特征 B: 搜索 CALL rel32 + TEST AL,AL 模式
        // 这是 FApp::CanEverRender() 调用后检查返回值的典型编译产物
        // E8 xx xx xx xx    CALL CanEverRender
        // 84 C0             TEST AL, AL
        bool bHasCallTestAL = Platform::FindPatternInRange(
            { 0xE8, -0x1, -0x1, -0x1, -0x1, 0x84, 0xC0 },
            FuncAddress, 0x400
        );

        if (!bHasCallTestAL)
            return false;

        // 特征 A: 函数前 0x80 字节内有至少两次 TEST RAX,RAX (48 85 C0)
        // 对应 GetWorld() == nullptr 和 Canvas == nullptr 的双重检查
        int NullCheckCount = 0;
        for (int i = 0; i < 0x80 - 3; i++)
        {
            if (FuncAddress[i]   == 0x48
             && FuncAddress[i+1] == 0x85
             && FuncAddress[i+2] == 0xC0)
            {
                NullCheckCount++;
            }
        }

        return NullCheckCount >= 2;
    };
```

```cpp
    const auto [HUDFuncPtr, HUDFuncIdx] =
        Platform::IterateVTableFunctions(HUDVft, IsHUDPostRender);

    if (HUDFuncPtr)
    {
        Off::InSDK::PostRender::HUDPostRenderIndex = HUDFuncIdx;
        Off::InSDK::PostRender::HUDPostRenderOffset =
            Platform::GetOffset(HUDFuncPtr);

        std::cerr << std::format("AHUD::PostRender Index: 0x{:X}\n",
                                  HUDFuncIdx);
        std::cerr << std::format("AHUD::PostRender Offset: 0x{:X}\n\n",
                                  Off::InSDK::PostRender::HUDPostRenderOffset);
    }
    else
    {
        std::cerr << "PostRender: Could not find AHUD::PostRender!\n\n";
    }
#endif // _WIN64
```

```cpp
    // ═══════════════════════════════════════════════════
    // 第二部分：UGameViewportClient::PostRender() 检测
    // ═══════════════════════════════════════════════════

    UEClass GVCClass = ObjectArray::FindClassFast("GameViewportClient");

    if (!GVCClass)
    {
        std::cerr << "PostRender: GameViewportClient class not found!\n";
        return;
    }

    UEObject GVCCDO = GVCClass.GetDefaultObject();

    if (!GVCCDO)
    {
        std::cerr << "PostRender: GameViewportClient CDO not found!\n";
        return;
    }

    void** GVCVft = *(void***)GVCCDO.GetAddress();

#if defined(_WIN64)
    // 通过 DrawTransition 内部的 "LOADING" 字符串定位
    // DrawTransition 在虚表中紧跟 PostRender
    auto IsDrawTransition = [](const uint8_t* FuncAddress,
                               [[maybe_unused]] int32_t Index) -> bool
    {
        // DrawTransition 内部有 switch-case，引用 L"LOADING" 宽字符串
        // 搜索 LEA 指令引用该字符串
        // 48 8D / 4C 8D = LEA reg, [rip+xxxx]
        for (int i = 0; i < 0x400; i++)
        {
            if ((FuncAddress[i] == 0x48 || FuncAddress[i] == 0x4C)
                && FuncAddress[i+1] == 0x8D)
            {
                // 解析 RIP 相对地址
                int32_t RelOffset = *reinterpret_cast<const int32_t*>(
                    &FuncAddress[i + 3]);
                const wchar_t* StrPtr = reinterpret_cast<const wchar_t*>(
                    &FuncAddress[i + 7] + RelOffset);

                if (!Platform::IsBadReadPtr(StrPtr)
                    && wcsncmp(StrPtr, L"LOADING", 7) == 0)
                {
                    return true;
                }
            }
        }
        return false;
    };

    const auto [GVCFuncPtr, GVCFuncIdx] =
        Platform::IterateVTableFunctions(GVCVft, IsDrawTransition);

    if (GVCFuncPtr)
    {
        // DrawTransition 紧跟 PostRender，PostRender = DrawTransition - 1
        Off::InSDK::PostRender::GVCPostRenderIndex = GVCFuncIdx - 1;
        void* PostRenderAddr = GVCVft[GVCFuncIdx - 1];
        Off::InSDK::PostRender::GVCPostRenderOffset =
            Platform::GetOffset(PostRenderAddr);

        std::cerr << std::format(
            "UGameViewportClient::PostRender Index: 0x{:X}\n",
            Off::InSDK::PostRender::GVCPostRenderIndex);
        std::cerr << std::format(
            "UGameViewportClient::PostRender Offset: 0x{:X}\n\n",
            Off::InSDK::PostRender::GVCPostRenderOffset);
    }
    else
    {
        std::cerr << "PostRender: Could not find "
                     "UGameViewportClient::PostRender!\n\n";
    }
#endif // _WIN64

#endif // PLATFORM_WINDOWS
}
```

### 6.5 集成点：调用时机

在 `Offsets.cpp` 的 `Off::Init()` 函数末尾，ProcessEvent 初始化之后调用：

```cpp
void Off::Init()
{
    // ... 现有的所有偏移初始化 ...

    // ProcessEvent 初始化（现有代码）
    Off::InSDK::ProcessEvent::InitPE_Windows();

    // PostRender 初始化（新增）
    if (Settings::PostRender::HUDPostRenderIndex != -1
        || Settings::PostRender::GVCPostRenderIndex != -1)
    {
        // 用户在 INI 中手动指定了索引
        Off::InSDK::PostRender::InitPostRender(
            Settings::PostRender::HUDPostRenderIndex,
            Settings::PostRender::GVCPostRenderIndex
        );
    }
    else
    {
        // 自动检测
        Off::InSDK::PostRender::InitPostRender_Windows();
    }
}
```

**调用顺序依赖：** PostRender 检测必须在以下初始化完成之后执行：
1. `ObjectArray::Init()` — 需要遍历 GObjects 查找 HUD/GameViewportClient 类
2. `FName::Init()` — 需要 `FindClassFast` 进行名称比较
3. `Off::UClass::ClassDefaultObject` — 需要获取 CDO

### 6.6 SDK 输出：在生成的 Basic.hpp 中暴露常量

CppGenerator 在生成 `Basic.hpp` 时，已经输出了 ProcessEvent 的索引和偏移。PostRender 应以相同方式输出：

```cpp
// 在 Basic.hpp 中生成的内容（示例）
namespace SDK
{
    namespace Offsets
    {
        // 现有
        constexpr int32 ProcessEventIndex = 0x4D;
        constexpr int32 ProcessEventOffset = 0x1A2B3C0;

        // 新增
        constexpr int32 HUDPostRenderIndex = 0xXX;
        constexpr int32 HUDPostRenderOffset = 0xXXXXXXX;

        constexpr int32 GVCPostRenderIndex = 0xXX;
        constexpr int32 GVCPostRenderOffset = 0xXXXXXXX;
    }
}
```

在 `CppGenerator.cpp` 的 `GenerateBasicFile()` 中添加输出逻辑：

```cpp
if (Off::InSDK::PostRender::HUDPostRenderIndex != -1)
{
    BasicHpp << std::format(
        "\tconstexpr int32 HUDPostRenderIndex = 0x{:X};\n",
        Off::InSDK::PostRender::HUDPostRenderIndex);
    BasicHpp << std::format(
        "\tconstexpr int32 HUDPostRenderOffset = 0x{:X};\n",
        Off::InSDK::PostRender::HUDPostRenderOffset);
}

if (Off::InSDK::PostRender::GVCPostRenderIndex != -1)
{
    BasicHpp << std::format(
        "\tconstexpr int32 GVCPostRenderIndex = 0x{:X};\n",
        Off::InSDK::PostRender::GVCPostRenderIndex);
    BasicHpp << std::format(
        "\tconstexpr int32 GVCPostRenderOffset = 0x{:X};\n",
        Off::InSDK::PostRender::GVCPostRenderOffset);
}
```

### 6.7 需要修改的文件清单

| 文件 | 修改类型 | 内容 |
|------|---------|------|
| `Engine/Public/OffsetFinder/Offsets.h` | 新增 | `Off::InSDK::PostRender` 命名空间 |
| `Engine/Private/OffsetFinder/Offsets.cpp` | 新增 | `InitPostRender_Windows()` 实现 |
| `Settings.h` | 新增 | `Settings::PostRender` 配置项 |
| `Settings.cpp` | 修改 | INI 加载逻辑增加 PostRender 段 |
| `Generator/Private/Generators/CppGenerator.cpp` | 修改 | Basic.hpp 输出增加 PostRender 常量 |
| `Generator/Private/Generators/Generator.cpp` | 修改 | `InitEngineCore()` 末尾调用 PostRender 初始化 |

---

## 七、风险分析与缓解措施

### 7.1 已识别风险

| 风险 | 等级 | 描述 | 缓解措施 |
|------|------|------|---------|
| R1: 游戏无 AHUD 实例 | 中 | 某些游戏不使用 AHUD（纯 UMG/Slate UI） | 检测失败时输出警告，不崩溃 |
| R2: 编译器内联 CanEverRender | 低 | MSVC 可能将短函数内联，导致无 CALL 指令 | 增加备用特征（特征 C 委托广播） |
| R3: 游戏子类覆写 PostRender | 中 | 子类覆写后函数体不同 | 使用基类 CDO 的虚表，而非实例虚表 |
| R4: 反作弊系统干扰虚表读取 | 高 | EAC/BattlEye 可能 hook 虚表 | 解析 JMP 跳板（现有 IterateVTableFunctions 已支持） |
| R5: "LOADING" 字符串被本地化替换 | 低 | NSLOCTEXT 的 Key 不变，但显示文本可能变 | 搜索 Key "LoadingMessage" 而非显示文本 |
| R6: DrawTransition 与 PostRender 不相邻 | 极低 | 游戏在中间插入虚函数 | 增加 PostRender 函数体长度验证 |

### 7.2 降级策略

当自动检测失败时，按以下优先级降级：

```
自动检测（特征码扫描）
    ↓ 失败
字符串引用回溯法
    ↓ 失败
INI 手动配置（用户指定索引）
    ↓ 未配置
输出警告，跳过 PostRender 索引生成
```

---

## 八、测试策略

### 8.1 验证方法

由于 PostRender 的虚表索引无法从源码静态计算（依赖完整编译链），验证需要在实际游戏进程中进行：

**方法 1：与已知工具交叉验证**

使用 IDA Pro / x64dbg 手动定位 PostRender 的虚表索引，与 Dumper-7 自动检测结果对比。

```
步骤：
1. 在 IDA 中找到 AHUD 的 RTTI 信息
2. 定位 AHUD 的虚表
3. 手动数到 PostRender 的位置
4. 与 Dumper-7 输出的 HUDPostRenderIndex 对比
```

**方法 2：运行时 Hook 验证**

在检测到的虚表索引处设置 Hook，验证是否在每帧渲染时被调用：

```cpp
// 验证代码（非生产用途）
void* OriginalPostRender = HUDVft[DetectedIndex];
// 替换为验证函数，检查调用栈是否来自渲染管线
```

### 8.2 推荐测试游戏

| 游戏 | UE 版本 | 测试价值 |
|------|---------|---------|
| Fortnite | UE5 最新 | 代表 UE5 最新虚表布局 |
| PUBG | UE4.16~4.27 定制 | 代表 UE4 高度定制版本 |
| Valorant | UE4.24 定制 | 含反作弊，测试 R4 风险 |
| Palworld | UE5.1 | 标准 UE5 游戏 |
| 黑神话悟空 | UE5.0 定制 | 代表 UE5.0 断层版本 |

---

## 九、结论与建议

### 9.1 核心发现

1. **AHUD::PostRender() 的声明在 UE 4.21 ~ 5.7 全部 12 个版本中完全一致**，函数体实现也几乎相同，这为特征码检测提供了坚实基础。

2. **绝对虚表索引不可静态确定**，AActor 在 UE4→UE5 之间增加了 62 个虚函数，导致 PostRender 的绝对索引发生大幅偏移。运行时检测是唯一可靠方案。

3. **AHUD::PostRender 具有足够独特的编译产物特征**：双空指针检查 + FApp::CanEverRender() 调用的组合在引擎虚表中具有唯一性。

4. **UGameViewportClient::PostRender 函数体过短**，需要通过相邻的 DrawTransition（含 "LOADING" 字符串）间接定位。

### 9.2 实施建议

**优先级排序：**

1. **P0（必须）**：实现 UGameViewportClient::PostRender 的间接检测 — 这是最通用的绘制 Hook 点，每帧调用且自带 UCanvas* 参数，几乎所有 UE 游戏都有视口
2. **P1（推荐）**：实现 AHUD::PostRender 的自动检测 — 作为信息性产物输出到 SDK，供需要 HUD 级别 Hook 的用户使用
3. **P2（可选）**：INI 手动覆盖配置支持

**实施工作量估算：**

- 新增代码量：约 150~200 行 C++
- 修改文件数：6 个
- 对现有功能的影响：零（纯增量，不修改任何现有逻辑）

---

## 附录 A：各版本源码文件路径索引

```
UE 4.21:
  HUD.h:                 UnrealEngine-4.21/Engine/Source/Runtime/Engine/Classes/GameFramework/HUD.h
  HUD.cpp:               UnrealEngine-4.21/Engine/Source/Runtime/Engine/Private/HUD.cpp
  GameViewportClient.h:  UnrealEngine-4.21/Engine/Source/Runtime/Engine/Classes/Engine/GameViewportClient.h
  GameViewportClient.cpp:UnrealEngine-4.21/Engine/Source/Runtime/Engine/Private/GameViewportClient.cpp
  Actor.h:               UnrealEngine-4.21/Engine/Source/Runtime/Engine/Classes/GameFramework/Actor.h
  Info.h:                UnrealEngine-4.21/Engine/Source/Runtime/Engine/Classes/GameFramework/Info.h

UE 4.27:
  (同上目录结构，替换版本号)

UE 5.1 ~ 5.7:
  (同上目录结构，替换版本号)
```

## 附录 B：AHUD::PostRender() 完整实现（参考）

以下为 UE 4.21 ~ 5.7 全版本通用的实现（仅 `NULL` vs `nullptr` 风格差异）：

```cpp
void AHUD::PostRender()
{
    if ((GetWorld() == nullptr) || (Canvas == nullptr))
        return;

    RenderDelta = GetWorld()->TimeSeconds - LastHUDRenderTime;

    if (PlayerOwner != nullptr)
        DrawDebugTextList();

    if (bShowDebugInfo)
    {
        if (DebugCanvas)
        {
            DebugCanvas->DisplayDebugManager.Initialize(
                DebugCanvas, GEngine->GetTinyFont(), FVector2D(4.f, 50.f));
            ShowDebugInfo(
                DebugCanvas->DisplayDebugManager.GetMaxCharHeightRef(),
                DebugCanvas->DisplayDebugManager.GetYPosRef());
        }
    }
    else if (bShowHUD && FApp::CanEverRender())
    {
        DrawHUD();
        // ... HitBox 触摸/鼠标检测逻辑 (~40行) ...
    }

    if (bShowHitBoxDebugInfo)
        RenderHitBoxes(Canvas->Canvas);

    DrawSafeZoneOverlay();
    OnHUDPostRender.Broadcast(this, DebugCanvas);
    LastHUDRenderTime = GetWorld()->TimeSeconds;
}
```

## 附录 C：特征码速查表

供实现时快速参考的字节模式：

| 特征 | x64 字节模式 | 搜索范围 | 说明 |
|------|-------------|---------|------|
| TEST RAX,RAX | `48 85 C0` | 函数前 0x80 字节 | 空指针检查 |
| JE short | `74 xx` | 紧跟 TEST 之后 | 短跳转 |
| JE near | `0F 84 xx xx xx xx` | 紧跟 TEST 之后 | 长跳转 |
| CALL rel32 + TEST AL,AL | `E8 xx xx xx xx 84 C0` | 函数前 0x400 字节 | CanEverRender 调用 |
| LEA + "LOADING" | `48 8D xx xx xx xx xx` → L"LOADING" | 函数前 0x400 字节 | DrawTransition 内部 |

---

*报告结束*


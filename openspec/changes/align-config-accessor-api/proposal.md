## Why

canonical-only 改版后，生成的 C#/Lua 配置 accessor 读取 FlatBuffers 二进制，但**接口形状与性能都未对齐** harmony 配置读取器：

- C# 侧没有每表查询 API（`Count/ByID/ByIndex/ByGroupKey`），只有 Lua 有 `ByID`。
- enum 字段返回**裸 `int`**（`public int Rarity => WireReader.I8(...)`），未返回类型化枚举。
- 跨表 `ref` 字段返回**裸 `int`**（`public int ItemTypeId => WireReader.I32(...)`），无类型化查找。
- vector 字段以 `Count + At(i)` 两个分离的访问点暴露，而非 harmony 那种**单一可索引/可枚举容器**（`NArray<T>`/`NStructArray<T>`）。
- vector 每元素都**重新解析 FlatBuffers 向量基址**，长向量下比 harmony 直读慢约 4×。

参考 harmony 与 `fabulous-game` 的 `WireReader`（仅参考，不作约束），已用仓库内可复现基准 `test-proj/ConfigAccessorBench` 验证：**向量基址捕获 ≈4.3× 快**，而**标量/枚举字段偏移缓存收益可忽略**（vtable 已被 L1 缓存命中）。

## What Changes

- **新增独立运行的 reader 运行时**（由我们设计，不绑定游戏现有 `WireReader` 契约；纯 C# + unsafe 读 FlatBuffers，独立于 Unity/游戏可运行）：
  - 指针式字段读取：`WireReader.I32(_row, slot)`（`slot = 4 + 2*字段序`），行句柄持 `IntPtr`。
  - `VecBase(obj, slot)`：一次解析向量基址，供容器 `[i]` 直读。
  - 每表查询：`Count/ByID/ByIndex/ByGroupKey`。
  - 容器类型：`NArray<T>` / `NStructArray<T>` / `NString`。
  - 版本/epoch 守卫；可选/建议字符串驻留（`NStringCache` 等价物）。
- **C# accessor 生成器**（`canonical_accessor.py`）：
  - 每表补 `Count/ByID/ByIndex`（有索引则保留 `ByGroupKey`）。
  - enum → `public ItemRarity Rarity => (ItemRarity)WireReader.I8(_row, slot);`。
  - cross-table `ref` → 保留裸 id 快路径 + 类型化访问（用**一次建立的 id→行缓存**，避免每字段 P/Invoke）。
  - `vector<int>` → `public NArray<int> Tags => new NArray<int>(WireReader.VecBase(_row, slot), count);`；`vector<record>` → `NStructArray<T>`；`vector<string>` → `NStructArray<NString>`。
  - 嵌套 record → 子行结构对齐容器风格。
- **Lua accessor 生成器**：同理，产出 `ByID/Count`、enum 类型化、ref 类型化、惰性容器。
- **不做**（经实测/评估排除）：标量/enum 字段偏移缓存（收益≈10%，可忽略）；`NValue`/`NValueObject` 动态对象；i18n 单表多语言列（属另一架构决策）。

## Capabilities

### New Capabilities
<!-- 无新增能力名；全部落在 flatbuffers-export 能力内 -->

### Modified Capabilities

- **flatbuffers-export**：把 flatc 时代的 C#/Lua Accessor 需求（`GDNative`/`Preload`）替换为 canonical + harmony 对齐的形态；新增“每表查询 API”“向量容器化（基址捕获）”“类型化 enum / 跨表 ref”“字符串驻留”需求。

## Impact

- `ct/src/ct/export/canonical_accessor_model.py`：`AccessorField` 增加 `ref` 元数据；携带容器类型文本；确保 enum 类型名/vector 元素类型可用。
- `ct/src/ct/export/canonical_accessor.py`：C#/Lua 生成器重写（指针式行句柄、查询 API、enum 强转、ref 类型化、vector 容器化、字符串驻留）。
- `ct/src/ct/app/canonical_export.py`：`build_accessor_model` 传表映射（解析 ref 目标表）。
- `ct/src/ct/export/canonical_fbs.py` / `canonical_binary.py`：不改（FlatBuffers 已是连续向量 + offset 嵌套表，`VecBase` 直接可用）。
- **新增 reader 运行时**（仓库内独立项目/模块，独立可跑，游戏后续集成）。
- `test-proj/ConfigAccessorBench`：作为 reader + accessor 的独立验证/基准工程。
- 测试：`ct/tests/export/test_canonical_accessor.py` 更新 golden + 新增容器/ByID/ref/enum/VecBase 用例。

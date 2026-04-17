## Context

游戏项目配表流程：策划填写 Excel → 程序导出为服务器 JSON 和客户端 Binary。目前无统一工具，手动处理易出错。工具需同时服务程序员（关心结构正确性）和策划（关心操作简单、错误提示友好）。C++ 客户端从零开始，无历史包袱。

**约束**：
- 外部依赖 `flatc` 编译器随项目放置，通过 `config/global.yaml` 配置相对路径
- Python 实现，需支持 Windows（策划主力平台）
- 二进制格式选定 FlatBuffers，未来需支持 C#、Lua

## Goals / Non-Goals

**Goals:**
- 单一工具覆盖 Schema 管理、Excel 解析、校验、JSON/Binary 导出、i18n 处理全流程
- 增量导出，大配表场景下只处理变更部分
- 策划友好的错误提示（表名/行号/字段名，而非技术栈报错）
- 自动生成 .fbs 和 Excel 模板头部，减少人工维护两套定义

**Non-Goals:**
- 不提供 GUI（只有 CLI）
- 不管理翻译内容本身（只输出待翻译文件，合并翻译结果）
- 不支持非 Excel 配表来源（数据库、YAML 数据等）
- 不做 Binary 热重载或运行时 patch

## Decisions

### D1：Schema 定义在外部 YAML，不内嵌 Excel

**选择**：独立 `schemas/*.yaml`，由程序维护，工具根据 Schema 生成 Excel 模板头部。

**理由**：内嵌 Schema 到 Excel 使校验 Schema 本身变复杂，且版本控制不友好。外部 YAML 可 code review，可用 Pydantic 强校验结构，策划填数据时工具自动生成正确的列头。

**备选**：Schema 内嵌 Excel 首行 —— 策划自由度高但易写错，拒绝。

---

### D2：FlatBuffers .fbs 从 Schema 自动生成

**选择**：工具从 `schemas/*.yaml` 自动生成 `.fbs` 文件，再调 `flatc` 分别编译 C++、C#、Lua 代码：
- `flatc --cpp` → `output/generated/cpp/`（供 C++ DLL 使用）
- `flatc --csharp` → `output/generated/csharp/`（供 Unity C# 使用）
- `flatc --lua` → `output/generated/lua/`（供 Lua 使用）

**理由**：单一事实来源（YAML Schema），避免 .fbs 和表结构不同步。三种语言各自持有 flatc 生成的类型，直接零拷贝读取同一块内存，无需通过 C++ 做类型转换。

**备选**：手写 .fbs —— 需维护两套文件，拒绝。

---

### D3：Binary Bundle 用 FlatBuffers 套 FlatBuffers

**选择**：Container 格式为 FlatBuffers 根表 `DataBundle { tables: [BundledTable] }`，每个 `BundledTable` 的 `data` 字段存放对应表的原始 FlatBuffers bytes。

```
// container.fbs（自动生成）
table BundledTable {
  name: string;
  data: [ubyte];
}
table DataBundle {
  tables: [BundledTable];
}
```

**理由**：纯 FlatBuffers 方案，无需自研 C++ reader，自描述（name 字段），flatc 自动处理序列化。C++ 全量加载场景下无需懒加载，内表不独立 mmap 的限制可接受。

**备选**：自定义 Pack 格式（Magic + Index + Data）—— 支持懒加载但需额外 ~100 行 C++ reader，目前全量加载场景无需此复杂度，拒绝。

---

### D4：主语言 Binary 全量，次语言 Binary 仅含 i18n 字段

**选择**：
- `data_{primary}.bin`：所有表完整数据
- `data_{secondary}.bin`：只含有 i18n 字段的 I18n 变体表（`ItemI18nTable`），体积约为全量的 20%

有 i18n 字段的表额外在 .fbs 中生成 I18n 变体：
```
table ItemI18nEntry {
  id: int32;     // 主键，用于 C++ 侧 merge
  name: string;  // 仅 i18n 字段
}
table ItemI18nTable {
  entries: [ItemI18nEntry];
}
```

**理由**：次语言之间只有文本差异，非 i18n 字段（数值、引用等）完全相同，无需重复存储。C++ 侧启动加载主语言全量，若目标语言不同则再加载 i18n Bundle 覆盖。

---

### D5：i18n 主数据嵌入真实字符串（非 loc_id）

**选择**：每语言输出独立完整数据文件（`item_zh.json`, `item_en.json`），字符串字段直接内嵌翻译后的值。

**理由**：服务器按语言加载对应版本，运行时无需额外查表合并，逻辑简单。文件数量 = 表数 × 语言数，规模可接受。

**备选**：主数据用 loc_id，运行时查语言包 —— 服务器增加合并逻辑，拒绝。

---

### D6：增量导出基于文件级 MD5 Hash

**选择**：对每个 `.xlsx` 计算 MD5，与 `cache/state.json` 中上次导出的 hash 比对，不同则重新导出，相同则跳过。

**理由**：文件 hash 比文件 mtime 可靠（跨机器、git checkout 后 mtime 变化），比 Sheet 级 hash 实现简单，配表场景修改频率不高，文件级粒度够用。

**校验的特殊处理**：引用校验需要被引用表的 id 集合，hash 未变化的表从 cache 读取 id 集合，避免重新解析。

---

### D7：i18n 独立翻译流程，工具只管 in/out

**选择**：工具导出 `i18n/strings_source.json`（含源语言文本），翻译团队填写 `i18n/strings_{lang}.json`，工具在 export 时自动合并。stale 检测：源文本变化时在 source 文件中标记 `"status": "stale"`。

**理由**：翻译团队有自己的工作流，工具不应强耦合。JSON 格式足够简单，翻译团队可用任何工具处理。

---

### D8：Excel 头部行数基于最大嵌套深度动态计算

**选择**：头部行数 = `max_nesting_depth + 2`（类型行 + 注释行）。无嵌套表为 3 行，一级嵌套 struct 为 4 行，两级嵌套为 5 行。非嵌套列在多出的行中垂直合并单元格，struct 列组在水平方向合并。

```
例：含一级 struct drop_range{min,max} 的表 → 4 行头部

行1（分组）: id   | name     | drop_range [← 合并2列 →] | tags | rarity
行2（字段）: [↕]  | [↕合并]  | min       | max          | [↕]  | [↕]
行3（类型）: int32| str[i18n]| int32     | int32        |array | enum[...]
行4（注释）: 道具 | 名称     | 最小值    | 最大值       | 标签 | 稀有度
```

**理由**：固定 3 行无法表达 struct 层级，策划会看不清哪些列属于同一个 struct。动态行数 + 合并单元格直观呈现层级。Reader 根据 Schema 精确计算跳过行数，无需 magic marker。

---

### D9：复合类型系统（enum / struct / array）

**选择**：

| Schema 类型 | Excel 表现 | FlatBuffers 生成 | JSON 表示 |
|---|---|---|---|
| `enum` | 单列，类型行标注 `enum[v1,v2,v3]` | `enum Name: byte { v1=0, ... }` | 字符串 `"rare"` |
| `struct` | 展开为多列，分组头合并 | FlatBuffers `table`（非 struct） | 对象 `{"min":10}` |
| `array<基础类型>` | 单列，分隔符可配置（默认 `,`） | `[type]` vector | JSON 数组 `[1,2,5]` |
| `array<enum>` | 单列，分隔符可配置 | `[EnumType]` vector | 字符串数组 `["common","rare"]` |

**struct 使用 FlatBuffers table 而非 struct 的理由**：FlatBuffers native `struct` 只允许标量字段，为保留将来 struct 内含 string/array 的扩展空间，统一生成为 FlatBuffers `table`。性能影响可忽略（配表全量加载，非热路径）。

---

### D10：array\<struct\> 不支持

**选择**：`array` 的 `element` 仅支持基础类型和 `enum`，不支持 `struct` 元素。工具遇到 `array<struct>` 定义时在 schema 加载阶段报错，提示改用独立子表 + `ref`。

**理由**：`array<struct>` 在 Excel 二维结构中无自然表示方式（要么固定列数上限导致列爆炸，要么用 JSON 字符串填单元格体验极差）。变长结构体列表场景一律用独立子表解决——数据更清晰，每行可单独校验，Excel 体验更好。

---

### D11：多语言运行时访问架构（C++ / C# / Lua）

**选择**：C++ 作为 xLua 动态库集成进 Unity，只负责加载二进制文件和暴露原始字节，C# 和 Lua 各自用 flatc 生成的代码独立解析，三者共享同一块内存。

```
data_zh.bin + data_en.bin
        ↓  GD_Load()
C++ (集成进 xLua DLL) — 永不因新增表而变动
  GD_Load(main, i18n)         // 加载到内存
  GD_GetMainBytes() → ptr+size // 暴露原始 FlatBuffers 字节
  GD_GetI18nBytes() → ptr+size // 暴露 i18n bundle 字节
        ↓                  ↓
     P/Invoke          xLua 注册函数
        ↓                  ↓
C# ByteBuffer 零拷贝    Lua userdata 零拷贝
flatc 生成 C# 类型      flatc 生成 Lua 类型
工具生成 C# Accessor    工具生成 Lua Accessor
（含 i18n 双包查找逻辑）（含 i18n 双包查找逻辑）
```

**新增表时各方工作量**：

| 层 | 操作 |
|---|---|
| C++ DLL | **不动** |
| xLua 注册代码 | **不动** |
| C# | 工具自动生成 `{Table}Accessor.cs` |
| Lua | 工具自动生成 `{table}_accessor.lua` |

**理由**：
- C++ DLL 预编译进 Unity 工程，不随配表变更重新编译；C# 和 Lua 是脚本层，改动成本低。
- 三种语言各自持有 flatc 生成的零拷贝访问器，无需通过 C++ 做类型转换，性能最优。
- C# 和 Lua 完全独立，不互相依赖，避免 xLua 桥接层的额外开销。
- i18n 双包查找（主语言 fallback）逻辑收敛在工具生成的 Accessor 中，上层业务代码无感知。

**C++ 侧手写（不由导表工具生成）**：
```cpp
extern "C" {
    void        GD_Load(const char* main_path, const char* i18n_path);
    const void* GD_GetMainBytes(size_t* out_size);
    const void* GD_GetI18nBytes(size_t* out_size);
    void        GD_Unload();
}
// xLua 注册：lua["GD"]["Load"] / lua["GD"]["GetMainBytes"] 等
```

**导表工具生成**：
- `output/generated/csharp/{Table}Accessor.cs`：调 `GDNative.GetMainBytes()` 零拷贝，封装 i18n 双包查找
- `output/generated/lua/{table}_accessor.lua`：调 `GD.GetMainBytes()` xLua 接口，封装 i18n 双包查找

## Risks / Trade-offs

| 风险 | 缓解 |
|------|------|
| flatc 未安装或版本不兼容 | 启动时检测 flatc 路径和版本，给出明确安装指引 |
| FlatBuffers Python 库写 Binary 性能较慢 | 配表导出频率低，不是热路径；若成为瓶颈可改用 subprocess 调 flatc 直接编译数据 |
| 次语言 i18n Bundle C++ merge 逻辑需自写 | 提供 C++ 工具函数模板，文档化 merge 方式（按主键 id 覆盖 i18n 字段） |
| Schema 变更（加字段）后旧 Excel 仍可用 | 新增字段设默认值，工具自动补全；gen-template 更新 Excel 头部 |
| 大配表（万行+）解析慢 | 先用 openpyxl read_only 模式；若不够再考虑 pandas |
| 策划填写了 Schema 之外的列 | 记录 warning 但不报错，忽略多余列 |

## Migration Plan

全新项目，无历史数据迁移。部署步骤：
1. `pip install ct-tool`（或从 release 下载单文件可执行）
2. 将 `flatc` 放入项目目录（如 `tools/flatc`），在 `config/global.yaml` 中配置路径
3. 创建 `config/global.yaml` 配置语言和输出路径
4. 编写 `config/schemas/*.yaml`
5. 运行 `ct gen-template --all` 生成 Excel 模板头部
6. 策划填数据后运行 `ct export`

## Open Questions

- 打包分发方式：PyInstaller 单文件 EXE（策划直接用）vs pip 安装（程序用）？建议提供两种。
- `ct export` 失败时产物是否回滚？建议先写临时文件，成功后原子替换。

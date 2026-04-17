## Context

`ct gen-template` 当前实现（[ct-tool/ct/excel/template.py:230-297](ct-tool/ct/excel/template.py#L230-L297)）总是 `wb = Workbook()` 全量重写文件，与 spec 中"不影响数据行"的承诺背离。同时工具缺少 schema 漂移检测：策划改 schema 后无主动信号告知模板已过时。

本次改动的核心是给 Excel 模板赋予"自我描述"能力 —— 让文件知道自己是哪张表、由哪个版本的 schema 生成、表头有几行 —— 然后基于这些自描述信息做正确的更新决策与漂移检测。

## Goals / Non-Goals

**Goals:**
- Excel 模板能精确知道数据行从第几行开始（不再靠推断）。
- 修改 schema 后能被工具主动检测并提示。
- `gen-template` 默认行为安全：不会静默丢失策划已填的数据。
- 用户保留两种逃生通道：`--force` 全量覆盖、`--update-header` 保留数据重建表头。
- table_name 不一致视为高风险误操作，强 force 也拒绝。
- `ct status` 输出 schema 漂移状态。

**Non-Goals:**
- 不做列名级别的数据迁移（数据原样下移，列对齐由用户手工处理）。
- 不引入新的存储后端（沿用 Excel 自身的 Custom Document Properties，无需外部数据库）。
- 不强制 legacy 文件迁移（按"不可信"路径处理即可，不阻塞用户）。
- 不修改 i18n / 增量导出逻辑。
- 不清理 `i18n/{lang}.json` 中因字段删除而产生的孤儿翻译键（i18n 流水线现有的"stale"标记机制已能在 `strings_source.json` 中体现状态；翻译文件清理留作独立 change）。
- 当前处于开发阶段，本地工作区 Excel 视为可丢弃的测试数据；用户实施此 change 时无需考虑工作区文件迁移，可直接删除后用新 `gen-template` 重建。

## Decisions

### 1. 元数据存储位置：Custom Document Properties

**选择**：使用 openpyxl 的 `wb.custom_doc_props`，写入 `docProps/custom.xml`。

**字段**：
| 字段 | 类型 | 用途 |
|------|------|------|
| `ct_tool_version` | string | 工具版本（向前兼容判断） |
| `ct_table_name` | string | 表名归属（防误覆盖） |
| `ct_header_rows` | int | 表头行数（精确定位数据起点） |
| `ct_schema_hash` | string | schema 全字段哈希（漂移检测） |
| `ct_generated_at` | string (ISO 8601) | 生成时间（信息性） |

**备选方案**：
- Defined Names（命名范围）：在 Excel 公式管理器中可见，污染用户视图。
- 隐藏 sheet：占用 sheet 槽位，且策划可能不慎删除。
- 单元格批注：鼠标悬停可见，干扰使用。

Custom Document Properties 是 Office 文档官方的"程序间元数据"机制，对最终用户完全隐藏，是最干净的选择。

### 2. Schema Hash 算法

```python
def compute_schema_hash(schema: TableSchema) -> str:
    data = schema.model_dump()  # 全字段（含 comment, struct nested, enum values...）
    serialized = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]
```

**为何包含注释**：注释会写入表头第 N 行（[template.py:213-219](ct-tool/ct/excel/template.py#L213-L219)），属于"对模板可见的内容"。改注释也应触发"模板过时"提示，避免新注释只活在 schema 里、文件里仍是旧文案。

**为何取前 16 字符**：完整 sha256 是 64 字符，存在元数据里读起来冗长。16 字符（64 bit）的碰撞概率对此场景足够低（同一表的 schema 变更路径有限）。

### 3. gen-template 决策矩阵

```
                              文件存在?
                                  │
                  ┌───────────────┴───────────────┐
                 否                               是
                  │                                │
              generate                          读元数据
              (写元数据)                            │
                          ┌─────────────────┬─────┴──────┬────────────────┐
                       无元数据         table不匹配    hash 一致         hash 不同
                       (legacy)            │             │                │
                          │                │             │            ┌───┴───┐
                ┌─────────┴────────┐    任何 flag      默认: 跳过+提示  无数据  有数据
              默认           --force/  都拒绝        --force: 重建      │       │
              拒绝+提示      --update                                generate  默认: 拒绝
                            -header                                  (写元数据) +提示
                                │                                            │
                          --force: 全量覆盖                          --force: 全量覆盖
                          --update-header:                        --update-header:
                          用新 schema header_rows                 用旧 ct_header_rows
                          推断跳过表头                              跳过表头
```

**关键原则**：
- 任何"可能丢数据"的路径都需要显式 flag。
- table_name 不匹配是唯一的"无逃生通道"路径 —— 这种情况几乎一定是误操作（如把 item.xlsx 复制成 quest.xlsx），用户必须手工处理。
- Legacy 文件特殊在不知道旧 header_rows，`--update-header` 时只能用新 schema 的值近似。

### 4. update_template 实现

```python
def update_template(schema: TableSchema, output_path: Path, *, legacy_fallback: bool) -> None:
    meta = read_template_metadata(output_path)
    old_header_rows = meta.header_rows if meta else schema.header_rows  # legacy 退化
    
    # 1. 读旧文件全部数据行（values_only）
    old_wb = load_workbook(output_path, read_only=True, data_only=True)
    old_ws = old_wb.active
    data_rows = [
        row for idx, row in enumerate(old_ws.iter_rows(values_only=True), start=1)
        if idx > old_header_rows and any(c is not None for c in row)
    ]
    old_wb.close()
    
    # 2. 重新生成模板（含新元数据）
    generate_template(schema, output_path)
    
    # 3. 把旧数据原样追加
    new_wb = load_workbook(output_path)
    new_ws = new_wb.active
    for row in data_rows:
        new_ws.append(list(row))
    new_wb.save(output_path)
```

**两次保存的代价**：可接受。`gen-template` 不在热路径上，可读性优先于性能。

### 5. ct status 漂移检测

每张表对比两个 hash：
- **当前 schema_hash**：从 `compute_schema_hash(schema)` 得出
- **模板内的 ct_schema_hash**：从 Excel 元数据读出

差异即"模板过时"。无元数据的 legacy 文件单列一类（"未跟踪元数据"），避免与"已过时"混淆。

**性能优化（可选）**：在 `cache/state.json` 中也存最近一次的 schema_hash，status 时只对 hash 变化的表才打开 Excel 读元数据。当前 schema 数量级（数十张表）下不优化也没问题，初版可不做。

### 6. 元数据读取的健壮性

`read_template_metadata` 必须容忍：
- 文件本身损坏 → 返回 None，让 caller 走 legacy 路径
- 部分字段缺失 → 任何关键字段缺失视为 None
- 字段类型异常 → catch ValueError，视为 None

不抛异常给上层，让决策逻辑保持单一入口。

## Risks / Trade-offs

- **[策划手工删除元数据]** → 模板退化为 legacy 文件。影响有限：`--update-header` 仍可用，只是依赖新 schema 推断 header_rows。
- **[openpyxl 版本兼容]** → `custom_doc_props` API 在 openpyxl 3.1+ 稳定。`requirements.txt` 已锁定相应版本（实施时验证）。
- **[Schema hash 假阴性]** → 极低概率 sha256 前 16 字符碰撞，会让"已修改"的 schema 被误判为"未变化"。社区中 16-char hash 用于内容标识属常见做法（git short hash 即如此），可接受。
- **[Legacy 文件用新 header_rows 推断]** → 如果旧 schema 嵌套深度与新 schema 不同，会导致部分行被吃掉或部分表头被当数据。此风险只发生在 legacy + 嵌套深度变化的边缘场景；提示文案需明确警示用户检查首尾行。
- **[默认行为变化]** → 老用户可能习惯"运行 gen-template 直接覆盖"。需在 `cli.py` 提示中明确告知 `--force` 的存在，并在 release notes 标注。
- **[两次保存开销]** → 每次 update 多一次 `load_workbook`+`save`。可忽略（gen-template 非热路径）。

## Migration Plan

1. 已存在的 Excel 文件首次运行新版 `gen-template`：会被识别为 legacy。
2. 用户用 `--update-header` 重建一次 → 文件获得元数据 → 后续所有调用走"有元数据"路径。
3. 不需要任何离线迁移脚本；过渡是按需触发的。

**回滚策略**：本次改动纯增量。回滚版本会忽略元数据但不会破坏文件（Custom Document Properties 不影响数据读取）。
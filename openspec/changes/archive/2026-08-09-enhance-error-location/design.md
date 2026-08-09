## Context

Change 1 已把错误建模为 `ValidationIssue`（含 `row_index` / `excel_row` /
`column` / `value` 字段），但 `excel_row` / `column` 从未填充：

- `read_excel` 遍历时知道绝对行号（`row_idx`），却只返回数据 dict，行号丢弃；
- `validate_table` / `validate_refs` 只拿到数据行，且 struct 子字段错误
  只带顶级字段名，无法定位具体叶子列；
- `render()` 用 `row_index` 复现旧文本（相对数据行号，空行会被跳过，
  策划无法对应 Excel 真实行）。

目标见 proposal.md。

## Goals / Non-Goals

**Goals:**

- reader 保留 Excel 绝对行号并穿透校验链，填充 `ValidationIssue.excel_row`；
- 按叶子列计算 `column`（struct 展开列覆盖到具体子字段）；
- `render()` 输出新格式：绝对行号 + 列字母 + 当前值 + 说明；
- 数据与行号分离，导出产物不受影响；
- CLI 错误输出升级（本 change 是行为变更）。

**Non-Goals:**

- 不改校验规则本身（只加定位信息）；
- 不做"一键打开 Excel 定位"（已在探索阶段 cut）；
- 不改导出产物格式、i18n 流程、schema 加载；
- 不实现网页面板（Change 3）。

## Decisions

### D1. `ParsedRows` 容器替代裸 `list[dict]`

```python
@dataclass(frozen=True)
class ParsedRows:
    rows: list[dict[str, Any]]        # 数据（与现在返回完全一致）
    excel_rows: list[int]             # 与 rows 平行的 Excel 绝对行号
```

**备选**：在数据 dict 里塞隐藏 key（如 `__excel_row__`）——否决：泄漏风险
（JSON 写出时忘了剥离就进产物）；并行列表是显式的"数据 / 定位"分离，
消费方要么用 `rows` 要么配对遍历，编译器可见。

调用方适配：`app/validate.parse_and_validate` 用 `excel_rows` 传校验器，
`cli._read_all_rows_for_sync` 只用 `.rows`。

### D2. 校验器签名：`excel_rows` 可选参数

```python
def validate_table(rows, schema, excel_rows: list[int] | None = None) -> list[ValidationIssue]
def validate_refs(rows, schema, id_sets, excel_rows: list[int] | None = None) -> list[ValidationIssue]
```

`excel_rows` 缺省时 `excel_row=None`（回退渲染路径），保证单测与未来
非 Excel 源不强制传行号。

### D3. 列定位：叶子列映射 + dotted path 穿透

- 用 reader 的 `_flatten_fields` / `_column_span`（迁移到共享位置或暴露
  为 `ct/schema` 的纯函数）计算 `{dotted_path: column_index}`；
- `_validate_field_value` / `_validate_struct` 内部改返回
  `(dotted_path, message)` 对，**消息文本保持逐字不变**；
- `validate_table` 用 dotted path 查列映射填充 `column`，顶级字段取
  其首叶子列（array 元素错误定位到字段所在列）。

### D4. `render()` 新格式 + 回退

```python
def render(self) -> str:
    if self.excel_row is not None and self.column is not None:
        letter = get_column_letter(self.column + 1)
        return (f"[{self.table}.xlsx] Excel 第{self.excel_row}行 · 列{letter} "
                f"({self.field}) · 当前值 {self.value!r} → {self.message}")
    # 回退：旧格式（无绝对定位信息时）
    return format_error(self.table, self.row_index, self.field, self.message)
```

`WorkspaceIssue` 文本不变。

### D5. 测试与断言更新

- 新增：reader 空行跳过但 `excel_rows` 正确；struct 叶子列定位；
  `render()` 新格式逐字断言；CLI 构造错误项目验证实际输出；
- 更新：`tests/validate/test_issues.py` 旧格式断言；
- 快照对比：错误输出与预期文本一致（无全量产物回归）。

## Risks / Trade-offs

- [绝对行号语义变化破坏既有文本断言] → 明确这是本 change 的行为变更，
  统一更新断言；`row_index` 仍保留在模型中供回退。
- [struct 叶子列映射复杂化内部校验器] → dotted path 穿透是纯内部改动，
  消息文本逐字不变，由现有错误快照测试兜底。
- [`ParsedRows` 改动波及 i18n sync 路径] → 该路径只消费 `.rows`，
  类型提示强制显式访问，编译器可查。

## Migration Plan

1. reader 引入 `ParsedRows` 并适配两个调用方 → 测试绿；
2. 校验器填充 `excel_row` / `column` → 单测绿；
3. `render()` 升级 + 更新旧断言 → 全量测试绿；
4. CLI 真实错误项目快照验证；
5. 更新 AGENTS.md 相关模块说明。

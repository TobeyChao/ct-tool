## Context

`ct-tool` 的 Excel 模板生成器（[ct-tool/ct/excel/template.py](ct-tool/ct/excel/template.py)）当前把表头分为三段：

```
行 1..N      字段名（N = max_nesting_depth）
行 N+1       类型注解（独立行）
行 N+2       注释
```

struct 字段在 group 行用横向合并的单元格只放字段名（例如 `drop_range`），独立 type 行只填叶子字段的类型，所以 struct 单元格底下露出来的是空白——策划无法在编辑器里直接看出 `drop_range` 在生成的 FBS 里对应 `DropRange` 这个 table。同时整张表头多占一行，纯粹是排版浪费。

reader（[ct-tool/ct/excel/reader.py:209](ct-tool/ct/excel/reader.py#L209)）通过 `schema.header_rows` 决定跳过几行，并不解析表头内容。已生成的所有 Excel 文件均为测试数据，已与用户确认可一次性删除并重新生成，无需迁移。

## Goals / Non-Goals

**Goals:**
- 把字段名 + 类型注解合并到同一个表头单元格，使用 openpyxl 富文本（`CellRichText`）实现两段不同字体的文字。
- struct 字段的横向合并单元格首次开始展示其类型（PascalCase 类名），与 FBS 生成的 table 名一致。
- 表头总行数减少 1（`max_nesting_depth + 1`）。
- 类型行的字体样式在 struct 与叶子之间保持完全一致。
- 抽取 `_pascal_case` 为独立模块，避免 `template.py` 反向依赖 `export/`。

**Non-Goals:**
- 不修改叶子字段类型注解的文本格式（例如不把 `enum[a,b,c]` 改成 `Rarity`、不把 `array<int32>` 改成 `[int32]`）。这些注解的形式给出的是 schema 视角的信息，比 FBS 类型名对策划更有用。
- 不引入"按 schema 字段属性自动配色"等更进一步的视觉增强（例如给 ref / server_only / i18n 字段加角标）——这是另一个独立改动的范围。
- 不为兼容旧布局 Excel 而在 reader 端引入 metadata-driven 跳行——所有旧 Excel 全部重新生成。
- 不改变 reader 端的列展开规则、struct 重组规则、array 拆分规则。

## Decisions

### 决策 1：富文本实现方式 —— 使用 `CellRichText` + `TextBlock`

```python
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont

name_font = InlineFont(rFont="Segoe UI", b=True, sz=12, color="FFFFFF")
type_font = InlineFont(rFont="Consolas", i=True, sz=9, color="D8F3DC")

cell.value = CellRichText([
    TextBlock(name_font, field.name),
    TextBlock(InlineFont(), "\n"),  # 换行
    TextBlock(type_font, type_text),
])
```

**为什么不选其它方案：**
- `\n` + 单一 Font + `wrap_text=True`：只能整格统一字体，无法做"名字粗体白 + 类型斜体浅色"的视觉层级，违背 Goals。
- 两个独立单元格垂直堆叠（去掉合并）：意味着 schema 中每个非 struct 字段实际占用两个 Excel 行，与"只是把 type 行合并到名字行"的语义不符；reader 端的跳行逻辑也要重写。否决。

**类型行配色约束：** 原 type 行底色是 `D8F3DC`（极浅绿），字色是 `1B4332`（深绿）。融入富文本后底色变成名字单元格的底色（`1B4332` 深绿 / `40916C` 中绿 / `C9A227` 金）——直接套原来的"深绿字"会在深绿底上看不见。改用 `D8F3DC`（极浅绿）作为类型字体颜色，在三种底色上对比都足够。

### 决策 2：struct 类型名的来源 —— 复用 FBS 生成器的 `_pascal_case`

抽到新文件 [ct-tool/ct/schema/naming.py](ct-tool/ct/schema/naming.py)：

```python
def to_pascal_case(name: str) -> str:
    return "".join(part.capitalize() for part in name.split("_"))
```

`fbs_generator.py` 改为 `from ct.schema.naming import to_pascal_case` 并删除本地 `_pascal_case`、`_enum_type_name`、`_struct_table_name`（后两者只是 `_pascal_case` 的别名）。

**为什么放在 `ct/schema/`：** `ct/schema/` 是底层模块，被 `excel/`、`export/`、`validate/` 共用——把命名工具放这里符合现有依赖方向，不会形成 `excel → export` 的反向依赖。

**为什么不直接在 template.py 里复制：** `_pascal_case` 是 FBS 命名约定的"单一事实源"。如果 FBS 命名规则未来变化（例如改用 `lower_camel` 或加前缀），所有展示位都要同步——抽到一处后只改一行。

### 决策 3：表头行高 —— 显式设置 36pt

```python
for row_idx in range(1, group_rows + 1):
    ws.row_dimensions[row_idx].height = 36
```

**为什么 36pt：** 12pt 名字 + 9pt 类型 + 行间距 + padding，36pt 在常见 DPI 下能完整露出两行而不显得过空。

**为什么不靠 `wrap_text` 自适应：** openpyxl 写出文件后，Excel 打开时是否自动撑高行依赖客户端实现，部分版本（特别是 WPS、Excel for Mac）不会自动撑高。显式设值最稳。

注释行（`comment_row = group_rows + 1`）保持默认行高，因为只有一行文字。

### 决策 4：删除独立 type row 的所有相关代码

`_write_field_headers` 中：
- 移除 `type_row` 参数
- 移除写 `type_cell` 的代码块
- 在 leaf 分支与 struct 分支统一调用一个新工具 `_make_name_type_richtext(field, is_struct)` 构造富文本并赋给名字单元格

`generate_template`：
- `type_row = group_rows + 1` → 删除
- `comment_row = group_rows + 2` → 改为 `comment_row = group_rows + 1`
- 调用 `_write_field_headers` 不再传 `type_row`

`_TYPE_FILL` 常量：删除（不再有独立 type row 需要这种底色）。

`_type_annotation` 函数：保留并复用，给叶子字段构造类型字符串。新增一个工具 `_struct_type_label(field) -> str` 返回 `to_pascal_case(field.name)`。

### 决策 5：reader 兼容性 —— 不改

reader 端只读 `schema.header_rows`。`header_rows` 公式从 `+ 2` 改为 `+ 1` 后，reader 自动跳过新的行数。所有旧 Excel 已确认删除重生，不会出现"reader 用新公式跳行、Excel 是旧布局"的歧义。

### 决策 6：测试策略

- 单元测试：为 `to_pascal_case` 加最小覆盖（`drop_range` → `DropRange`、`a` → `A`、空字符串边界）。
- 集成测试：跑 `ct gen-template --all` 生成 `gd/excel/*.xlsx`，再跑 `ct export --all` 走完导出流水线，比较 `gd/output/json/` 与改动前是否一致——验证 reader 端无回归。
- 视觉验收：人眼打开 `gd/excel/item.xlsx`（含 struct + i18n + ref + array<enum>），确认：
  - 行数 = `max_nesting_depth + 1`
  - struct 横向合并单元格底部展示 `DropRange` 字样
  - 字体：名字 12pt 粗白、类型 9pt 斜体浅绿
  - 行高足够展示两行不裁切
  - 注释行位于最末

## Risks / Trade-offs

- **[富文本兼容性]** 不同 Excel 客户端对 `CellRichText` 渲染可能有差异（特别是 LibreOffice / WPS）。 → 缓解：openpyxl 写出标准 `<r>` rich-run XML，主流客户端均支持。落地后用 Excel 与 WPS 各打开一次确认。
- **[行高写死 36pt 不能跨 DPI 自适应]** 高 DPI 屏可能显得偏低、低 DPI 屏可能显得偏高。 → 缓解：36pt 是基于 12pt + 9pt 字号在 96 DPI 下的合理值，覆盖主流场景；如果实际验收偏窄可调到 40pt。
- **[移除 `_TYPE_FILL` 是潜在的破坏性改动]** 如果未来想把"类型"再独立成一行（例如打印模板用），需要重新引入这个常量。 → 缓解：常量删除前先 grep 确认无其它引用；未来若需要恢复，git log 可查。
- **[`to_pascal_case` 与 FBS 生成器解耦的回归风险]** 改完后 fbs 产物的类型名必须与之前完全一致。 → 缓解：在改 `fbs_generator.py` 时跑一次 `ct export --all` 并 diff 生成的 `*.fbs`，零差异才算通过。
- **[迁移过程中误删用户数据的风险]** 用户已确认 `gd/excel/` 全是测试数据，但仍需在 tasks 里把"删除"作为显式步骤而不是隐式假设。 → 缓解：tasks.md 把删除作为独立 step 并附 `git status` 复核要求。

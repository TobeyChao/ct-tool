# Excel 写入与迁移选型结论（rust-native-core 任务 1.6）

日期：2026-09-17。基线：openpyxl 3.1.5（`ct/excel/canonical_template.py` +
`planning.py` + `_migrate_excel_rows`）。候选：rust_xlsxwriter 0.99。

**结论：rust_xlsxwriter 覆盖全部所需写入形态，选型成立。**
模板两变体（v1/v2a）与 golden 的 openpyxl 语义转储逐项一致；
迁移（稳定列路径映射）与 Python golden 的数据区逐格一致；
三类阻断场景（缺 manifest / 删除列有数据 / 类型不可转换）均拒绝且不产出文件。

## 对照方法

- `fixtures/template/generate.py`：构造 Item 表（嵌套 Record、固定 vector
  组、bool/int32/float/double、普通 Enum、超 255 字符 Enum），经 Python
  canonical 模板/迁移产出 golden + openpyxl 语义转储（expected/）。
- `tests/compat/tests/template_semantics.rs`：zip 结构断言（冻结窗格、
  19 合并、12 验证、批注部件、自定义属性、富文本 run）+ calamine 回读 +
  迁移数据区与 golden 逐格对照 + 阻断场景。
- `fixtures/template/compare_semantics.py`：Rust 产出的 openpyxl 深度语义
  diff（当前**零差异**，归一规则见下）。

## 覆盖的表头/迁移形态

2D 成对表头（注释行+字段行）、结构节点横向合并、浅层叶纵向合并、
主键/组/数组/槽位/普通填充色、富文本两段（名称 Aptos Bold + 类型
Consolas Italic）、注释行按内容行数的高度计算、冻结 A(2D+1)、
滚动窗格选区锚定、Enum Note（类型+候选+注释）、bool/int32/float/enum
数据验证、超 255 字符枚举降级为 warning 不建下拉、列宽 16、行高 30/38、
自定义文档属性五件套、白色数据区（默认无填充）。

## rust_xlsxwriter 注意点（实现约束）

1. **实心填充必须 `set_pattern(Solid) + set_foreground_color`**；
   `set_background_color` 不隐含 solid 模式（踩坑已修）。
2. `Color::RGB` 只接受 6 位 RRGGBB（8 位 ARGB 被视为无效色 → 黑）。
3. `Note` 默认在文本前缀"作者:\n"，`add_author_prefix(false)` 关闭；
   不要用 `set_author`（作者会进文本）。
4. 自定义属性不支持 filetime 类型：`ct_generated_at` 暂写 Unix 秒整数
   （golden 对照已屏蔽该值；要完全一致需手写 vt:filetime 或等库支持）。
5. 列宽自动补偿 Excel 单元格内边距（16 → 16.7109375 raw），显示等价；
   对照脚本按显示宽度归一。
6. whole/decimal 验证的 `operator="between"` 省略（Excel 缺省即 between），
   与 openpyxl 显式写出语义等价，对照脚本归一。
7. decimal 范围用 `allow_decimal_number_formula("-1E+307")` 保持文本一致；
   直接传 f64 会被展开成 309 位小数字符串。

## 迁移语义（移植自 planning.py）

- stable path 为主键，logical path（去 [g] 组标记）仅在唯一命中时兜底；
- 删除列有数据 → blocker；类型变更且存在不可转换值 → blocker；
- 缺 layout manifest → untracked blocker；blocked 时不产出任何文件；
- 全空行跳过；数据按新列位写入新模板（不落回旧工作簿）。

## 已知边界（不在本次承诺范围）

- 数据区公式透传：Python 迁移按 `data_only=False` 复制公式文本；calamine
  读到的是缓存值。数据区实践上不出现公式，出现时按 Other（文本）透传，
  差异风险记录在案。
- 不承诺任意附加 Sheet/宏/图表的无损保留（与 design.md 决策一致）。
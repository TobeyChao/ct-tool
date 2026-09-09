## Why

Canonical Excel 模板目前把层级路径直接推导成合并区域，导致 Record 兄弟叶子被误合并、类型注解缺失，且单一底部注释行无法表达 Record、数组槽位等结构节点的说明。模板输入辅助、变长 Vector 文法和 JSON 排版也缺少一致且可审查的契约，降低了策划填写体验和版本 diff 可读性。

## What Changes

- **BREAKING** 将表头改为每层一组“注释行 + 字段行”：所有字段节点均显示自身注释，Record/数组节点按后代叶子范围横向合并，较浅叶子字段纵向合并到表头底部。
- 为普通叶子、Record、数组、数组槽位和主键定义可访问的独立配色、字体、对齐、行高及内外边框；冻结完整表头，不生成 AutoFilter。
- **BREAKING** 将 `vector<T>` 的单格输入统一为括号文法（如 `[1,2,3]`），固定逗号分隔并移除 `separator`；String 元素使用 JSON 双引号。
- 明确定长展开 `vector<T>[N]` 的最大槽位语义：最后一个显式填写槽位决定长度，此前空槽位及部分 Record 中的空叶子递归补类型默认值，末尾空槽位不导出。
- 为 Bool、Enum、Ref 和数值字段生成覆盖至 Excel 最大行的数据验证或输入提示；普通数据列保持白底，特殊输入列使用类型辅助色。
- **BREAKING** 将 Enum 项升级为 `{name, comment}`，保持声明顺序作为 wire ordinal；Enum 表头以 Excel Note 展示类型说明及每项注释，短列表直接内嵌下拉，超长列表显式 warning 并降级。
- 将 canonical JSON 改为“一条 Excel 数据记录对应一条 JSON 物理行”，嵌套 Record 和 Vector 不换行，字段保持 Schema 顺序。
- 不提供旧 Excel/manifest、旧 Enum 或旧 Vector 文法的 cutover 迁移/兼容代码；新格式启用 `template-layout/2` manifest，后续同格式重生成仍按稳定叶子路径保留数据。首次切换时删除并重建 `gd` 测试模板、可丢弃 canonical 缓存和导出产物后重新填写测试数据，保留面板历史等非派生状态。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `excel-processing`: 修改 canonical Layout 的表头深度、节点跨度、合并、模板重建、Vector 输入及定长槽位读取规则。
- `excel-template-styling`: 修改表头配色、字体、对齐、行高、边框、冻结窗格、Note、数据区辅助色和整列应用范围。
- `data-validation`: 增加 Bool、Enum、Ref、数值和 Vector 输入辅助及最终校验规则。
- `schema-management`: 修改 Enum 项模型并移除 `separator`，明确 Enum 顺序与注释语义。
- `schema-editor/type-system`: 修改 Vector 和 Enum 的 canonical 编辑模型及显示约束。
- `schema-editor/workbench`: 增加 Enum 项注释编辑以及重排、重命名、删除的风险呈现。
- `json-single-line-records`: 将现有单行记录要求落实到 canonical JSON writer，并明确嵌套值、转义和确定性排版。

## Impact

- Schema/API：`EnumResource.values` 从字符串变为结构化项；`FieldDef.separator` 删除，相关 Workspace command 和 Web JSON 载荷同步变化。
- Excel：`ct.excel.layout`、`canonical_template`、`canonical_reader`、layout manifest、模板 hash、数据验证、Note 和测试需要更新。
- 导出：FBS/Binary/Accessor 需从 Enum 项读取 `name`；canonical JSON writer 改变纯格式输出。
- 测试数据：`gd/config/types/*.yaml`、`gd/excel/*.xlsx`、`gd/output` 全量重建；`gd/excel/layout_manifests/*.json` 作为跨端迁移元数据纳入版本控制，`gd/cache` 仅保留可丢弃的运行时状态。

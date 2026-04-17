## Why

当前 `ct gen-template` 生成的 Excel 模板颜色扁平（全浅色系），视觉层次不清晰，且缺少 enum 下拉、筛选等实用功能，策划填表时容易出错。JSON 输出使用 `indent=2`，大量字段时每条记录占数十行，git diff 噪音极大，不易 review。

## What Changes

- **Excel 模板颜色方案重设计**：采用深绿色系，普通字段名行深森林绿、struct 行中绿、主键列暖金色，形成清晰视觉层次；type 行改为极浅绿，comment 行保留浅灰
- **Excel 模板功能增强**：enum 字段添加 DataValidation 下拉菜单；在表头末行添加 Auto-filter；为数据区设置奇偶行斑马纹条件格式
- **JSON 输出格式改为单行记录**：每条记录紧凑序列化为一行，整体结构（根键 + 数组）保留，方便 git diff

## Capabilities

### New Capabilities

- `excel-template-styling`: Excel 模板的视觉样式与功能增强（颜色层次、主键高亮、enum 下拉、auto-filter、斑马纹）
- `json-single-line-records`: JSON 输出格式，每条记录对应文件中一行

### Modified Capabilities

（无现有 spec 变更）

## Impact

- `ct-tool/ct/excel/template.py` — 颜色常量、样式函数、DataValidation、Auto-filter、条件格式
- `ct-tool/ct/export/json_writer.py` — `write_json` 函数输出格式
- 已生成的 JSON 文件格式发生变化（非 breaking，内容一致，格式不同）
- 无 API / schema / CLI 接口变化
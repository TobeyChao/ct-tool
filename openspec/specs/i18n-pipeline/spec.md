## ADDED Requirements

### Requirement: Extract i18n strings to source file
导出时工具 SHALL 收集所有标记为 `i18n: true` 字段的原文，合并更新 `output/i18n/strings_source.json`，格式为 `{ "{TABLE}_{FIELD}_{ID}": { "text": "原文", "context": "表名/字段注释", "status": "new|translated|stale" } }`。

#### Scenario: New string extracted
- **WHEN** item 表新增一行 id=1003，name="法杖"，首次导出
- **THEN** `strings_source.json` 新增 `"ITEM_NAME_1003": { "text": "法杖", "status": "new" }`

#### Scenario: Changed source string marked stale
- **WHEN** item id=1001 的 name 从 "宝剑" 改为 "神剑"
- **THEN** `strings_source.json` 中 `ITEM_NAME_1001` 的 text 更新为 "神剑"，status 改为 "stale"

#### Scenario: Deleted row cleaned up
- **WHEN** item id=1002 的行从 Excel 中删除
- **THEN** `strings_source.json` 中移除 `ITEM_NAME_1002` 条目

### Requirement: Merge translations for export
导出时工具 SHALL 读取 `output/i18n/strings_{lang}.json`（翻译团队填写），将译文合并到对应语言的导出数据中。

#### Scenario: Translation merged
- **WHEN** `strings_en.json` 中 `ITEM_NAME_1001: "Holy Sword"` 存在
- **THEN** `item_en.json` 和 `data_en.bin` 中该条目的 name 字段值为 "Holy Sword"

#### Scenario: Missing translation uses source
- **WHEN** `strings_en.json` 中无 `ITEM_NAME_1003` 条目
- **THEN** `item_en.json` 中该条目 name 回退为主语言原文，并输出 warning

#### Scenario: Translation file not found
- **WHEN** `strings_en.json` 文件不存在，但 en 在 secondary_langs 中
- **THEN** 所有 i18n 字段使用主语言原文，输出 warning，不报错终止

### Requirement: Report stale translations
导出结束后工具 SHALL 汇总所有 stale 条目，输出统计（多少条需要重新翻译，按表分组）。

#### Scenario: Stale summary shown
- **WHEN** 有 3 条 stale 的 en 翻译
- **THEN** 导出完成后输出：`[i18n] en 有 3 条翻译需要更新：item(2条), quest(1条)`

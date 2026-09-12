## Purpose

按语言把配表数据序列化为 JSON 产物，支持复杂字段类型与 i18n / server_only 标记，作为人类可读的调试与外部消费格式。

## Requirements

### Requirement: Export table data to JSON per language
工具 SHALL 为每张表、每种语言输出独立的 JSON 文件，i18n 字段内嵌对应语言的翻译字符串，`server_only` 字段包含在内，文件路径为 `output/json/{Table}_{lang}.json`。

#### Scenario: Primary language JSON export
- **WHEN** 导出 Item 表，主语言 zh，无次语言
- **THEN** 生成 `output/json/Item_zh.json`，`Name` 字段值为中文原文

#### Scenario: Secondary language JSON export
- **WHEN** 导出 Item 表，次语言 en，翻译文件 `i18n/en/Item.json` 存在
- **THEN** 生成 `output/json/Item_en.json`，`Name` 字段值为英文译文

#### Scenario: Missing translation fallback
- **WHEN** 次语言翻译文件中某条目缺失或状态为 stale
- **THEN** 该字段使用主语言原文，并在导出日志中记录 warning

### Requirement: Include server_only fields in JSON but exclude them from Binary
标记为 `server_only: true` 的字段 SHALL 包含在 JSON（主语言与次语言的 JSON 都是全量行）；同一个字段 SHALL NOT 进入客户端 Binary、FBS 或 Accessor。字段标记只有 `i18n` 与 `server_only`，不存在 `client_only`。

#### Scenario: server_only field in JSON
- **WHEN** 字段 `IsActive` 标记 `server_only: true`
- **THEN** `IsActive` 出现在 JSON 中，不出现在 Binary 中

### Requirement: JSON output format
JSON 文件 SHALL 输出为对象数组格式：`{ "<root>": [ {...}, {...} ] }`，根 key SHALL 为 schema 配置的 `json_key`，未配置时为表名加 `s`（`TableResource.resolved_json_key`）。

#### Scenario: Array root format
- **WHEN** 导出 Item 表（未配置 `json_key`）
- **THEN** JSON 根结构为 `{ "Items": [ { "Id": 1001, "Name": "宝剑", ... } ] }`

### Requirement: Serialize complex field types to JSON
具名 `enum`、具名 `Record` 与 `vector<T>` 类型字段 SHALL 按各自规则序列化到 JSON，保持可读性优先。

#### Scenario: Enum serialized as string
- **WHEN** 字段 `Rarity` 为具名 enum 类型，值为 `rare`
- **THEN** JSON 中输出 `"Rarity": "rare"`（字符串，非整数索引）

#### Scenario: Record serialized as nested object
- **WHEN** 字段 `DropRange` 为具名 Record，值为 `Min=10, Max=20`
- **THEN** JSON 中输出 `"DropRange": { "Min": 10, "Max": 20 }`

#### Scenario: Vector of primitives serialized as JSON array
- **WHEN** 字段 `Tags` 为 `vector<int32>`，值为 `[1, 2, 5]`
- **THEN** JSON 中输出 `"Tags": [1, 2, 5]`

#### Scenario: Vector of enum serialized as string array
- **WHEN** 字段 `AllowedRarities` 为 `vector<ItemRarity>`，值为 `[common, rare]`
- **THEN** JSON 中输出 `"AllowedRarities": ["common", "rare"]`

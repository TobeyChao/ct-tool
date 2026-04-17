## ADDED Requirements

### Requirement: Export table data to JSON per language
工具 SHALL 为每张表、每种语言输出独立的 JSON 文件，i18n 字段内嵌对应语言的翻译字符串，`server_only` 字段包含在内，文件路径为 `output/json/{table}_{lang}.json`。

#### Scenario: Primary language JSON export
- **WHEN** 导出 item 表，主语言 zh，无次语言
- **THEN** 生成 `output/json/item_zh.json`，`name` 字段值为中文原文

#### Scenario: Secondary language JSON export
- **WHEN** 导出 item 表，次语言 en，翻译文件 `strings_en.json` 存在
- **THEN** 生成 `output/json/item_en.json`，`name` 字段值为英文译文

#### Scenario: Missing translation fallback
- **WHEN** 次语言翻译文件中某条目缺失或状态为 stale
- **THEN** 该字段使用主语言原文，并在导出日志中记录 warning

### Requirement: Exclude client-only fields from JSON when configured
标记为 `server_only: true` 的字段 SHALL 包含在 JSON 中；反之，可配置 `client_only` 字段只进 Binary 不进 JSON。

#### Scenario: server_only field in JSON
- **WHEN** 字段 `is_active` 标记 `server_only: true`
- **THEN** `is_active` 出现在 JSON 中，不出现在 Binary 中

### Requirement: JSON output format
JSON 文件 SHALL 输出为对象数组格式：`{ "items": [ {...}, {...} ] }`，根 key 为表名复数形式（或 schema 中配置的 `json_key`）。

#### Scenario: Array root format
- **WHEN** 导出 item 表
- **THEN** JSON 根结构为 `{ "items": [ { "id": 1001, "name": "宝剑", ... } ] }`

### Requirement: Serialize complex field types to JSON
enum、struct、array 类型字段 SHALL 按各自规则序列化到 JSON，保持可读性优先。

#### Scenario: Enum serialized as string
- **WHEN** 字段 `rarity` 为 enum 类型，值为 `rare`
- **THEN** JSON 中输出 `"rarity": "rare"`（字符串，非整数索引）

#### Scenario: Struct serialized as nested object
- **WHEN** 字段 `drop_range` 为 struct，值为 min=10, max=20
- **THEN** JSON 中输出 `"drop_range": { "min": 10, "max": 20 }`

#### Scenario: Array of primitives serialized as JSON array
- **WHEN** 字段 `tags` 为 array<int32>，值为 `[1, 2, 5]`
- **THEN** JSON 中输出 `"tags": [1, 2, 5]`

#### Scenario: Array of enum serialized as string array
- **WHEN** 字段 `allowed_rarities` 为 array<enum>，值为 `[common, rare]`
- **THEN** JSON 中输出 `"allowed_rarities": ["common", "rare"]`

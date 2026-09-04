## MODIFIED Requirements

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

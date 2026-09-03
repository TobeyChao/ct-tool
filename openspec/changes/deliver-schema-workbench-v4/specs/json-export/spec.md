## MODIFIED Requirements

### Requirement: Serialize complex field types to JSON
具名 Enum、具名 Record 与 vector 字段 SHALL 按 canonical Type Expression 序列化到 JSON。Enum SHALL 输出标识符字符串，Record SHALL 输出嵌套对象，vector SHALL 输出保持输入顺序的 JSON array；`vector<Record>` SHALL 输出对象数组。Excel 输入布局、separator 与 `excel_columns` 不得改变 JSON 运行时形状。

#### Scenario: Named enum serialized as string
- **WHEN** Item.Rarity 引用 ItemRarity Enum 且值为 `Rare`
- **THEN** JSON 输出 `"Rarity": "Rare"`，不输出 wire byte 或整数序号

#### Scenario: Named record serialized as nested object
- **WHEN** Item.DropRange 引用 DropRange Record 且值为 Min=10、Max=20
- **THEN** JSON 输出 `"DropRange": {"Min": 10, "Max": 20}`

#### Scenario: Vector of primitives serialized as JSON array
- **WHEN** Tags 类型为 `vector<int32>` 且解析值为 `[1, 2, 5]`
- **THEN** JSON 输出 `"Tags": [1, 2, 5]`

#### Scenario: Vector of enum serialized as string array
- **WHEN** AllowedRarities 类型为 `vector<ItemRarity>` 且值为 `[Common, Rare]`
- **THEN** JSON 输出 `"AllowedRarities": ["Common", "Rare"]`

#### Scenario: Vector of record serialized as object array
- **WHEN** Rewards 类型为 `vector<DropReward>` 且 Excel 解析出两个元素
- **THEN** JSON 输出恰好两个保持顺序的对象，未填写的展开组不产生空对象

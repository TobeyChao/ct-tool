## Purpose

用独立 .NET 测试工程读取 ct 导出的 FlatBuffers 二进制，验证产物在客户端的可读性。

## Requirements

### Requirement: 验证 struct 和 array 字段
程序 SHALL 对 `item` 表的第一行验证 `DropRange`（struct：min <= max）和 `Tags`（array：可为空但不抛异常）字段。

#### Scenario: DropRange 结构验证
- **WHEN** `drop_range` 字段正确序列化
- **THEN** `DropRange.Min <= DropRange.Max`，断言通过

#### Scenario: Tags 数组不抛异常
- **WHEN** 读取 `Tags` 数组
- **THEN** 返回长度 >= 0 的数组，不抛出异常

### Requirement: 验证 item_type 和 quest 表
程序 SHALL 对 `item_type` 和 `quest` 两张表执行相同的行数和主键非零验证。

#### Scenario: item_type 表验证通过
- **WHEN** `item_type` 表存在
- **THEN** `ItemTypeTable.ItemTypesLength > 0`，第一行 `Id > 0`，打印 `[PASS] item_type table`

#### Scenario: quest 表验证通过
- **WHEN** `quest` 表存在
- **THEN** `QuestTable.QuestsLength > 0`，第一行 `Id > 0`，打印 `[PASS] quest table`

### Requirement: PASS/FAIL 汇总退出
程序 SHALL 在所有断言执行完毕后打印汇总行，若有任何断言失败则以退出码 1 退出，全部通过则以退出码 0 退出。

#### Scenario: 全部通过
- **WHEN** 所有表的所有断言均通过
- **THEN** 打印 `All tests passed.`，退出码 0

#### Scenario: 存在失败
- **WHEN** 至少一个断言失败
- **THEN** 打印 `X test(s) failed.`，退出码 1

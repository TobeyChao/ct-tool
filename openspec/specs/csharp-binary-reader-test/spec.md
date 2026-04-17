## Requirements

### Requirement: 工程可独立构建
测试工程 `test-proj/BinaryReaderTest/BinaryReaderTest.csproj` SHALL 以 `dotnet build` 成功编译，仅依赖 `Google.FlatBuffers 24.3.25` NuGet 包，无其他外部依赖。

#### Scenario: 首次构建成功
- **WHEN** 在 `test-proj/BinaryReaderTest/` 下执行 `dotnet build`
- **THEN** 编译无错误退出，输出 `BinaryReaderTest.dll`

### Requirement: 读取并验证 DataBundle
程序 SHALL 从 `gd/output/binary/data_en.bin` 加载字节，使用 `DataBundle.GetRootAsDataBundle` 解析，断言 `TablesLength > 0`。

#### Scenario: Bundle 解析成功
- **WHEN** `data_en.bin` 存在且格式正确
- **THEN** `DataBundle.TablesLength` 大于 0，程序不抛出异常

#### Scenario: 文件缺失时给出明确错误
- **WHEN** `data_en.bin` 不存在
- **THEN** 程序打印包含文件路径的错误信息，以非零退出码退出

### Requirement: 验证 item 表
程序 SHALL 在 Bundle 中找到名称为 `item` 的 BundledTable，将其 `data` 字节反序列化为 `ItemTable`，断言行数 > 0，并验证第一行的 `Id`、`Name`、`Price` 字段值合理（Id > 0，Name 非空，Price >= 0）。

#### Scenario: item 表字段验证通过
- **WHEN** `item` 表存在且数据格式正确
- **THEN** 所有字段断言通过，打印 `[PASS] item table`

#### Scenario: item 表缺失时标记为失败
- **WHEN** Bundle 中找不到名为 `item` 的表
- **THEN** 打印 `[FAIL] item table: not found in bundle`，累计失败计数

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

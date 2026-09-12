## MODIFIED Requirements

### Requirement: Read Excel data according to schema
工具 SHALL 使用 openpyxl 读取 Excel 文件，从 schema 定义的起始数据行开始解析，忽略模板头部行（前 N 行由工具生成）。

整数标量列（`int8` / `uint8` / `int16` / `uint16` / `int32` / `uint32` / `int64` / `uint64`）的值 SHALL 落在该**声明类型**的值域内。越界值 SHALL 在解析校验阶段报为类型错误（`期望 <type> 类型`，定位到表、行与列），使 `ct validate` 与 `ct export` 一致失败；SHALL NOT 留到产物生成阶段由 flatbuffers builder 抛出 `TypeError`（导出主键存进 4 字节索引向量，越界值此前会以 Python traceback 结束）。

#### Scenario: Data parsed correctly
- **WHEN** Excel 文件包含正确的列头和数据行
- **THEN** 工具按字段顺序解析每行数据，空行自动跳过

#### Scenario: Extra columns ignored
- **WHEN** Excel 中存在 schema 未定义的列
- **THEN** 工具记录 warning 但继续处理，忽略多余列

#### Scenario: Excel file not found
- **WHEN** schema 引用的 Excel 文件不存在
- **THEN** 工具报错指明文件路径，终止该表的处理

#### Scenario: Out-of-range integer rejected
- **WHEN** `int32` 字段（含主键）的单元格填写 `5000000000`（超出 `[-2147483648, 2147483647]`）
- **THEN** 工具报类型错误 `期望 int32 类型` 并定位到该行该列，`ct validate` 返回非 0；`ct export` 在解析校验阶段中止，不写任何产物

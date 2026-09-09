## MODIFIED Requirements

### Requirement: 每条记录单行 JSON 输出
canonical JSON writer SHALL 保留根对象和数组的多行外壳，同时将每条 Excel 数据记录序列化为且仅为一条 JSON 物理行。记录内任意深度 Record、vector 及 `vector<Record>` SHALL 紧凑保留在该行；字符串实际换行 SHALL 转义为 `\n`。输出 SHALL 使用 UTF-8 非 ASCII 转义、保持 Schema 字段顺序、拒绝 NaN/Infinity，并以单个文件末尾换行结束。

#### Scenario: 基本记录单行输出
- **WHEN** 导出包含两条记录
- **THEN** 根键和数组括号保持可读缩进，两条对象分别且仅占一条物理行，只有第一条行尾带记录分隔逗号

#### Scenario: 嵌套 struct 单行
- **WHEN** 一条记录包含多层 Record
- **THEN** 所有嵌套对象均在该记录物理行内且 JSON 解析内容不变

#### Scenario: array 字段单行
- **WHEN** 一条记录包含多个 Record 的 vector
- **THEN** 整个数组及内部对象均不引入额外物理行

#### Scenario: Embedded newline is escaped
- **WHEN** string 值包含实际换行
- **THEN** 文件中使用 `\n` 转义且记录仍只有一条物理行

#### Scenario: Schema order is stable
- **WHEN** 字段声明顺序与字母排序不同
- **THEN** JSON 记录按 Schema 声明顺序输出且跨进程结果确定

#### Scenario: Empty table has compact empty array
- **WHEN** 表没有数据记录
- **THEN** 输出根值为同一行的 `[]` 且文件仍是合法 JSON

#### Scenario: 内容等价
- **WHEN** 使用标准 JSON 解析器读取单行记录格式
- **THEN** 解析结果与同一 canonical 数据的缩进格式完全等价，仅物理排版不同

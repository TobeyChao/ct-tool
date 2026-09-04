## Purpose

规定 JSON 导出中每条记录以单行紧凑格式输出的约定，便于 diff 与脚本处理。

## Requirements

### Requirement: 每条记录单行 JSON 输出
`write_json` 函数 SHALL 将每条记录序列化为单行紧凑 JSON，整体结构保留根键和数组格式：
```
{
  "<root_key>": [
    {<record1>},
    {<record2>}
  ]
}
```
记录内部的嵌套对象（struct）和数组均紧凑序列化，不展开换行。

#### Scenario: 基本记录单行输出
- **WHEN** 导出包含多条记录的表
- **THEN** JSON 文件中每条记录占且仅占一行，行内无换行符

#### Scenario: 嵌套 struct 单行
- **WHEN** 记录包含 struct 类型字段
- **THEN** struct 对象在同一行内以 `{"min": 10, "max": 20}` 格式序列化，不展开多行

#### Scenario: array 字段单行
- **WHEN** 记录包含 array 类型字段
- **THEN** 数组在同一行内以 `[1, 2, 5]` 格式序列化，不展开多行

#### Scenario: 内容等价
- **WHEN** 解析新格式与旧格式的 JSON 文件
- **THEN** 解析结果的数据内容完全一致，仅格式不同
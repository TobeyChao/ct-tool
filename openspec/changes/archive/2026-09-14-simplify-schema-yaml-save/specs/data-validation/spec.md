## ADDED Requirements

### Requirement: Validate enum token domain
validate/export SHALL 在读取使用具名 Enum 的字段时校验每个 token（含 scalar、定长 Enum 槽位与变长 Enum vector 的每个元素）属于当前 Enum 声明的 name 集合。未知 token SHALL 报类型错误并定位表、字段、Excel 行与原始值，导出 SHALL NOT 落任何产物；序列化 SHALL NOT 把未知 token 静默映射为任何 ordinal（当前实现会落到 `0`）。

> 为什么必须在数据校验层落地：Binary serializer 用 `names.index(value) if value in names else 0` 解析 Enum，JSON 则原样输出字符串 —— 没有这道闸门时，删除一个仍被数据引用的 Enum item 会让 Binary 静默变成 ordinal 0（JSON 仍显示旧名），两侧产物互相矛盾且没有任何提示。保存侧不读数据，因此这是该约束的唯一执行点。

#### Scenario: Removed enum token blocks export
- **WHEN** 某行 Enum 字段（或 Enum vector 的某个元素）写着已从 schema 删除的旧 token
- **THEN** validate/export 失败并给出表名、字段、Excel 行号与原始值，`output/` 不产生新产物

#### Scenario: Declared tokens still export normally
- **WHEN** 所有 Enum 单元格都是当前声明集合内的 token
- **THEN** 校验与导出照常通过，Binary、JSON、Accessor 的 Enum 语义不变

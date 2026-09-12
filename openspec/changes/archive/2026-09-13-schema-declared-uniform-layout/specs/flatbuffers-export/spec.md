## MODIFIED Requirements

### Requirement: Generated accessors read uniform tables by literal offset

表是否定宽 SHALL **由表 schema 的 `uniform` 键声明**（缺省 `true`），SHALL NOT 由数据、填充率或任何导出期探测结果决定。导出器 SHALL NOT 存在「先探测再决定布局」的阈值判定。

定宽表的行内字段偏移是**表级常量**，生成器 SHALL 据此发射**字面量偏移**读 ——
C# 侧 `WireReader.I32At(row, 28)`，Lua 侧 `GD.I32Off(s, 28)` —— 而不是每次读重走 vtable。
显式 `uniform: false` 的表 SHALL 继续走槽位（偏移不是常量，字面量化会读错），且 SHALL NOT 出现字面量偏移。

填充率 SHALL 仍被计算，但仅用于导出输出中的诊断报告，SHALL NOT 参与布局决策。

#### Scenario: uniform table emits literal offsets

- **WHEN** 表未声明 `uniform`（缺省为真）或显式声明为 `true`
- **THEN** 其 C# / Lua 访问器的标量、字符串、容器取指针均按**导出期算出的常量偏移**读
- **AND** 嵌套 record **内部**字段仍走槽位（record 不是定宽表）

#### Scenario: non-uniform table keeps slot reads

- **WHEN** 表显式声明 `uniform: false`
- **THEN** 访问器走 vtable 槽位读，SHALL NOT 出现字面量偏移

#### Scenario: 改数据不再改变布局

- **WHEN** 某定宽表的某行把字段填成类型默认值（或清空该单元格），使填充率下降
- **THEN** 该表的定宽声明、`slot_offsets`、二进制行布局与生成的访问器 SHALL 均不变化
- **AND** 只有导出输出里的填充率诊断数字变化

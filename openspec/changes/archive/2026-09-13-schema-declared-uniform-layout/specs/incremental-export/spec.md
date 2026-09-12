## MODIFIED Requirements

### Requirement: 生成缓存按有效输入失效

系统 SHALL 根据生成器版本和实际影响该产物的输入复用生成结果，包括表级传递具名类型依赖、有效译文及 **schema 声明的**定宽布局。缓存缺失、损坏或校验和不符 SHALL 自动重建。正式产物缺失或被修改 SHALL 恢复正确内容。缓存命中 SHALL NOT 绕过类型、主键、CodeName 和 ref 校验。

#### Scenario: 有效译文变化只更新相关产物

- **WHEN** 仅 Item 的 en 有效译文改变，布局决策不变
- **THEN** Item_en.json 与 data_en.bin 按需要更新，其他语言和无关表的正式产物不变

#### Scenario: 无效元信息不导致重新生成

- **WHEN** 仅译文文件排版、status 或不参与导出的 orphan 项变化，有效合并行不变
- **THEN** 缓存仍可复用，正式产物不变

#### Scenario: 复用不依赖未接线的指纹辅助函数

- **WHEN** 独立 fingerprint 判定辅助函数未接入生产生成路径，但执行未变化输入的第二次导出
- **THEN** 系统仍通过有效输入生成缓存复用产物，不能把未调用该辅助函数解释为不支持增量

#### Scenario: 定宽决策改变

- **WHEN** Excel 数据变化（含把字段改成类型默认值、清空单元格、增删行），而 schema 的 `uniform` 声明未变
- **THEN** 定宽决策、`slot_offsets`、Binary 行布局与 Accessor SHALL 均不改变，只有数据相关产物更新
- **AND** 该情形不再由数据触发：改 schema 的 `uniform` 才会改变布局决策

#### Scenario: 具名依赖变化

- **WHEN** 表传递引用的 Record 或 Enum 变化
- **THEN** 依赖它的生成结果失效；未引用该资源的表级生成结果继续可复用

#### Scenario: 缓存损坏与输出修复

- **WHEN** 缓存条目损坏或某个正式产物缺失/被改写
- **THEN** 自动重建或从有效缓存恢复正确产物，不需要用户手动清理整个缓存

#### Scenario: 热缓存仍阻止非法数据

- **WHEN** 已有热缓存但当前 Excel 出现重复主键
- **THEN** 导出失败且正式输出不变

#### Scenario: 生成器版本变化

- **WHEN** 生成器版本改变而输入相同
- **THEN** 旧生成缓存不被复用，默认模式下重新生成但字节相同的文件保留 mtime

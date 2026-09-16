## MODIFIED Requirements

### Requirement: 默认增量复用与强制重建

`ct export` SHALL 对捕获的当前输入保持完整校验覆盖；允许复用输入指纹、规则版本和依赖均有效的解析及校验结果，其余部分重新执行，随后复用未失效的生成产物。默认模式 SHALL 保留内容未变化的正式文件及其 mtime。`--all` SHALL 绕过解析、校验和生成缓存，完整解析校验选中表及 ref 依赖，并重写所有选中产物。相同输入下增量与强制生成的 JSON、FBS、Accessor、Binary 字节 SHALL 相同；成功账本不用于跳过解析校验。

#### Scenario: 未变化的表仍被解析校验
- **WHEN** 输入和正式产物均未变化且生成缓存完整
- **THEN** 基于当前捕获字节验证缓存有效性，允许复用解析校验及生成结果，正式文件内容和 mtime 不变

#### Scenario: --all 强制重建并写出
- **WHEN** 用户执行 `ct export --all`
- **THEN** 选中范围及 ref 依赖不复用解析校验缓存，选中产物不使用生成缓存且全部重新写出，字节与同输入的增量结果相同

#### Scenario: 带过滤的导出仍重写共享 Bundle
- **WHEN** 用户执行 `ct export --table Item` 且校验通过
- **THEN** `output/binary/data_{lang}.bin` 按过滤后的表集合生成（仅 Item 或 Item_i18n），不合入未选中表 bytes；默认模式内容相同则不实际重写

### Requirement: 生成缓存按有效输入失效

系统 SHALL 根据生成器版本和实际影响该产物的输入复用生成结果，包括表级传递具名类型依赖、有效译文及 **schema 声明的**定宽布局。缓存缺失、损坏或校验和不符 SHALL 自动重建。正式产物缺失或被修改 SHALL 恢复正确内容。缓存命中 SHALL NOT 降低类型、主键、CodeName 和 ref 校验覆盖；复用校验结果必须绑定当前输入、规则版本与依赖，无法证明有效时重新校验。

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

## ADDED Requirements

### Requirement: Parsed and validated cache dependency correctness
解析与校验缓存 SHALL 可丢弃、版本化并校验完整性；键 SHALL 覆盖实际捕获输入、读取布局、规则版本及对应依赖，不得仅依赖 mtime/size 或成功账本。ref 结果 SHALL 依赖来源外键与目标主键集合，目标主键变更必须使相关 ref 校验失效。默认增量和强制重建 SHALL 对相同输入具有相同成功失败结果和产物。

#### Scenario: Referenced primary key removed
- **WHEN** 来源表字节未变但目标表删除被引用主键
- **THEN** 来源 ref 结果失效并报告错误，不发布产物或推进账本

#### Scenario: Same timestamp edited workbook
- **WHEN** Excel 内容改变但大小和 mtime 被保留
- **THEN** 内容指纹识别变化，重新处理受影响数据，不错误命中旧校验结果

#### Scenario: Corrupt parsed cache
- **WHEN** 解析缓存损坏、缺失或版本不识别
- **THEN** 从捕获输入重建，不能把缺失数据视作空表或绕过校验

#### Scenario: Read-only validation
- **WHEN** 用户运行 validate 且缓存缺失
- **THEN** 在内存完成完整校验，不创建持久缓存或修改工作区

#### Scenario: Unrelated target values changed
- **WHEN** ref 目标表只改非主键且不影响来源校验的字段
- **THEN** 允许复用仍有效的来源 ref 结果，不扩大产物生成范围

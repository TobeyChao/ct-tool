# incremental-export Specification

## Purpose

本文件记录「默认增量复用 + 内容寻址生成缓存」的**正式契约**：`ct export` 每次都完整
解析并校验选中表，随后按生成器版本与实际输入复用未失效的生成产物；`--all` 绕过生成
缓存并重写选中产物。生成缓存（`cache/artifacts/`）是可丢弃的中间物，成功账本
（`cache/state.json`）只在本地发布（CLI 下还包括部署）成功后推进 —— 二者不可混为一谈。

## Requirements

### Requirement: 默认增量复用与强制重建

`ct export` SHALL 每次重新解析并完整校验选中表，随后复用未失效的生成产物。默认模式 SHALL 保留内容未变化的正式文件及其 mtime。`--all` SHALL 绕过生成缓存并重写所有选中产物。相同输入下增量与强制生成的 JSON、FBS、Accessor、Binary 字节 SHALL 相同；成功账本不用于跳过解析校验。

#### Scenario: 未变化的表仍被解析校验
- **WHEN** 输入和正式产物均未变化且生成缓存完整
- **THEN** 表仍被解析校验，生成缓存命中，正式文件内容和 mtime 不变

#### Scenario: --all 强制重建并写出
- **WHEN** 用户执行 `ct export --all`
- **THEN** 选中范围不使用生成缓存，全部选中产物重新写出，字节与同输入的增量结果相同

#### Scenario: 带过滤的导出仍重写共享 Bundle
- **WHEN** 用户执行 `ct export --table Item` 且校验通过
- **THEN** `output/binary/data_{lang}.bin` 按过滤后的表集合生成（仅 Item 或 Item_i18n），不合入未选中表 bytes；默认模式内容相同则不实际重写

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

### Requirement: cache/state.json 是 ct status 的变更账本，不是导出缓存

系统 SHALL 保持 `cache/state.json` 的 `canonical-cache/1` 可读性以及 tables、bundles、excel_hashes 字段。excel_hashes SHALL 用于 status 的数据变化判断，bundles 保存成功导出的 Bundle 指纹；此账本 SHALL NOT 决定跳过解析校验或生成缓存命中。部分导出 SHALL 保留未选中表和语言的账本记录。

CLI export SHALL 仅在本地导出和配置的部署成功后提交账本；Web export SHALL 在本地导出成功后提交账本。失败 SHALL 不推进账本。生成缓存是可丢弃数据，失败运行可以留下有效缓存条目；不得把“账本不变”解释为所有 cache 文件不变。

#### Scenario: 删除 cache 不改变导出行为
- **WHEN** 用户删除 state.json
- **THEN** 下次导出前 status 将存在 Excel 的表报为 changed；下一次成功导出仍可使用独立生成缓存并重新写入成功账本

#### Scenario: 导出失败不污染账本
- **WHEN** 校验、构建、发布或 CLI 部署失败
- **THEN** state.json 保持上一次成功记录

#### Scenario: 账本原子写入失败
- **WHEN** 成功账本替换失败且旧文件仍可读
- **THEN** 旧账本不被部分 JSON 覆盖，操作失败，已完整发布的产物保留

### Requirement: ct status 只报 missing / changed / drifted

`canonical_status` SHALL 返回且仅返回三个类别：`missing`（Excel 不存在）、`changed`（Excel 当前 sha256 与 `excel_hashes` 记录不一致，或无记录）、`drifted`（`excel/layout_manifests/{table}.json` 缺失、其 `schema_hash` 与当前 schema 不一致，或工作簿实际列数与 layout 列数不一致）。

不存在「untracked metadata」类别，也不输出 deploy 行。未完成或损坏的**发布恢复记录**由 `ct status` 另行以 `[publication]` 行报出（只读检测，不执行恢复），其契约见 `export-publication` 能力；它不属于 `canonical_status` 的三个类别。

#### Scenario: 只报三类
- **WHEN** 用户执行 `ct status` 且不存在未完成的发布
- **THEN** 输出只含 `[missing]` / `[changed]` / `[template-stale]` 三种条目，全部为空时输出 `[OK] 所有表已是最新（数据 + 模板）`

#### Scenario: 模板漂移的提示命令
- **WHEN** `Item` 的 schema 已改但 manifest 未重建
- **THEN** 输出 `[template-stale] Item  (建议: ct gen-template --table Item)`，提示中不含 `--update-header`

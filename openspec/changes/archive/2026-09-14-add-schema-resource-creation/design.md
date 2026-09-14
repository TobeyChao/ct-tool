## Context

动机见 proposal.md。当前 reducer 的 `add_resource` 直接将 payload 中的 resource 追加到模型元组，Web `_commands` 却只封装原始 JSON，缺少模型解码。Record 的 fields 与 Enum 的 values 均不允许为空；Enum Python 构造器接受字符串列表的便利行为不应成为 Web 协议。候选层已有名称冲突、具名类型解析、依赖与字段约束校验，可扩展复用。

本变更依赖 `simplify-schema-yaml-save`，使用其 candidate/save API、schemaRevision、candidateHash、净差异和共享 FilePublisher。当前旧 apply 恢复只还原有备份的路径，不能正确撤销新增文件；本功能必须通过共享发布器验证新增目标恢复，不扩展旧 apply。

## Goals / Non-Goals

**Goals:** 统一三类资源从结构化输入到候选、保存和下游使用的契约；复用已有类型编辑、草稿历史、存储事务及生成流程；在空工作区和跨资源草稿中行为一致。

**Non-Goals:** 不实现工作区初始化、复制/导入 Schema、批量创建向导、创建 CLI、自由 YAML 编辑、自动导出部署；不修改现有标量、主键和 Enum wire 规则；不在保存时生成 Excel。

## Decisions

### 1. 以 YAML-only 保存为前置

实现及归档顺序为 simplify-schema-yaml-save → 本变更。本变更只向现有 workbench/workspace-draft 增加创建专属要求，不重复重定义前置的保存事务。全链路验收串联显式步骤而非绑定为单一事务；避免为即将删除的 prepare-apply 增加一条平行路径。

### 2. 一个带类别的可序列化资源命令

命令外形固定为 `{"type":"add_resource","payload":{"kind":"table|record|enum","resource":{...}}}`；resource 使用 canonical 持久化字段和类型表达式文本，服务端从 kind 分派解析，转换为领域模型后执行。Table 的 resource 含 table/primary/fields；Record/Enum 含与外层一致的 kind/name 和 fields/values。kind 不一致、未知键和非对象 Enum 项均显式拒绝。例：

```json
{"type":"add_resource","payload":{"kind":"table","resource":{"table":"Item","primary":"Id","fields":[{"name":"Id","type":"int32"}]}}}
```

```json
{"type":"add_resource","payload":{"kind":"record","resource":{"kind":"record","name":"DropReward","fields":[{"name":"Min","type":"int32"}]}}}
```

```json
{"type":"add_resource","payload":{"kind":"enum","resource":{"kind":"enum","name":"ItemRarity","values":[{"name":"Common","comment":"普通"}]}}}
```

解析复用资源仓库的纯解析/类型表达式能力，必要时抽取无文件 I/O 的解码函数；不通过临时 YAML 文本迂回解析。模型对象只存在于后端重放内部，IndexedDB 存原始 JSON。现有 Python 内部直接传模型的调用点先检索，统一迁移或保留显式内部适配，不让公开 API 接受两套含糊形状。

候选与 save 使用相同解码；错误含命令位置及字段位置，沿用现有问题响应封装。初次构造检查局部形状和同名冲突；最终候选统一解析跨资源依赖，不要求命令解码时所有目标已落盘。初始化 Table 索引状态，避免 merge_indexes 丢失声明或遗留删除后索引。

### 3. 最小合法创建表单，继续在主编辑器完善

Schema 头部放统一入口，资源分组放预选类别入口，空状态复用同一表单。名称和注释通用；Table 固定 Id，沿用默认 excel_file/json_key/uniform，不增加高级配置向导；Record 要求首字段名称与类型，复用类型选择及约束组件，vector<Record> 等必需参数按现有规则联动；Enum 要求首项名称和可选注释。避免隐式生成 Value/Default 占位内容，也不放宽领域模型允许空结构。

客户端快速校验后用候选预检确认拟新增命令，成功才提交正式草稿并关弹窗；请求期间禁止重复提交，失败保留表单。预检响应只对匹配的草稿版本有效，不能覆盖用户后续编辑。后端保存再次校验，客户端通过不构成持久化授权。

### 4. 所有候选资源视图使用同一来源

新增后直接选中新 resourceId，过滤条件若隐藏它则清空过滤并展开其分组；不强行打开折叠的资源 pane。资源树、Quick Open、类型/ref 选择、反向引用与详情均从当前候选派生，检查并消除仅基于已落盘 snapshot 的缓存。候选刷新继续使用前置版本号防止旧响应回写。

undo/redo 或删除后，失效选择回到之前仍存在的资源，找不到则空状态；历史条目中失效资源不出现在可打开结果。依赖删除保护沿用现有规则；整条历史重放及 candidate 校验仍是最终兜底。刷新恢复使用前置草稿格式与 cursor；旧无新增命令草稿继续可读，不在本功能另建存储系统。

### 5. 净差异与落盘路径由服务端决定

新增→编辑→改名归为最终新增；新增→删除归零。新增引用引起的已有资源变化单独列示。Table/Record/Enum 名称按候选全局唯一校验，同时检查生成器保留名及生成名称冲突。路径按配置解析的 schemas/types 目录与合法名称生成，不接受浏览器指定 YAML 路径；比较规范化目标及大小写折叠路径，防止在 Windows/macOS 产生碰撞。已有 Table 的 Excel 目标冲突也须检查，孤立现存工作簿留给显式模板无损预检，不在保存中读写。

save 沿用 schemaRevision 的目录成员保护，并在发布前核对新目标预期不存在；已存在但不属于本次合法替换/删除的目标直接冲突。共享发布事务记录新文件原先不存在的事实，回滚恢复旧文件并删除本事务已发布新文件；不使用缺少此语义的旧 apply。配置允许的目录布局沿用前置路径策略，不硬编码 config/schemas 或 config/types。

### 6. 模板与产物是显式后续步骤

保存成功从返回 snapshot 刷新选择，Table 状态来自实际检查；未保存 Table 的模板按钮禁用并解释先保存。缺失时提供针对该表的生成入口，复用既有 API，不另设创建专用模板生成器。模板失败独立展示，不能逆转 YAML 保存成功状态。

新 Record/Enum 没有独立工作簿。通过引用它们的新表或已有表验证模板、JSON、共享 types.fbs、表 FBS、Binary 和 C#/Lua Accessor；测试覆盖未被引用类型保存后可重新加载，并在后续引用时被正常消费。未生成模板前 validate/export 继续按缺失/漂移闸门失败，不因新建路径而绕过校验。既有 i18n、server_only、ref 和索引规则不变，使用新表数据验证其可以进入现有流程。

## Risks / Trade-offs

- [前置提案仍在途] → 实施任务先确认其完成且协议已落地；若前置范围变化，先修订设计，不能暗中恢复旧 Apply。
- [候选视图遗漏 Quick Open 或类型缓存] → 浏览器跨资源创建、搜索、引用、撤销、刷新串联验收。
- [前后端解码或净差异不一致] → 服务端返回权威候选与摘要，测试真实 JSON 请求而不只传 Python 模型。
- [多文件创建失败留下残余] → 对共享事务注入发布失败/进程中断，验证旧目标恢复和新目标删除及重复恢复。
- [默认 Excel 名称与现存数据碰撞] → 保存不碰工作簿，独立模板操作遵守已有无损预检。

## Migration Plan

1. 先完成前置保存简化，再落地命令协议、候选/保存测试，之后接通前端。
2. 前后端同版本发布；不迁移或重写现存 YAML，复用前置的 IndexedDB 版本兼容策略。增加新增命令能力校验，旧客户端遇到不支持命令不得静默丢弃草稿。
3. 用临时工作区完成三类资源闭环和故障恢复验收，更新说明。
4. 回退前先完成事务恢复；已保存 YAML 保持 canonical 可读。包含新增命令的未保存草稿须保留供兼容版本恢复，不能以降级为由清空。

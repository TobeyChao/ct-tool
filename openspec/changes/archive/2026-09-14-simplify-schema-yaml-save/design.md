## Context

见 proposal.md 的动机。当前 Web 使用 change-plan 展示影响，再以 prepare-apply 重放草稿，最后 apply 暂存的 YAML；plan.py 的 Excel 扫描在 Web 调用中未接通。apply.py 自有 exists/write 锁和 journal，而 export 已有系统锁及 FilePublisher。前端存有 commands/cursor，却用命令数判断 dirty，IndexedDB 未存 cursor，Schema 基线还混入 Excel/i18n 内容。

这是跨 API、前端状态、存储和读取闸门的变更，需要设计文档。用户明确要求保存只改 YAML；这里的「只改」指业务文件，必要的锁、暂存、恢复 journal 属于工具私有事务状态。

## Goals / Non-Goals

**Goals:** 保存行为与文案一致；命令历史和净差异各司其职；源文件原样保留到确实需要修改；外部编辑不被覆盖；旧 Excel 不被新布局错读。

**Non-Goals:** 不重写 Excel 模板生成器，不自动更新模板/翻译/导出/部署，不增加跨保存的 rename 映射库、交互式迁移向导或通用工作流引擎。不承诺保存完成后可直接导出。

## Decisions

### 1. 一个保存请求，删除长寿命计划

新增 POST /api/schema-workspace/save，输入 schemaRevision、commands（当前 cursor 前缀）、candidateHash；candidate 读接口返回权威净差异、结构问题及 candidateHash。save 在服务端重新构建并校验候选、核对 hash，再事务化发布；不信任浏览器的摘要或 valid 标志。成功返回新 snapshot、净变化摘要和是否 no-op；失败返回可定位 issues / conflict / busy，草稿保留。

删除 change-plan、prepare-apply、apply 及其前端链路。结构保存不扫描 Excel 数据，不试运行生成器。已有删除确认保留，内容明确仅删除 YAML，不删除 Excel 或产物；不增加所有保存必经的二次确认。净差异摘要常驻可查看，Enum 顺序等结构兼容性提示保留但不冒充数据扫描结果。

替代方案：合并 prepare 与 review 仍需计划资源生命周期；只保存 YAML 无必要，选择短请求、乐观并发。

### 2. 历史是真实操作，dirty 是最终结构差异

保留 commands + cursor，撤销/重做逐条执行；不在线压缩历史。服务端对 canonical 持久化语义做规范化比较，保留字段/Enum 的有序含义，消除对象键顺序、索引重复表示等噪声。候选是派生结果，base 为编辑时已落盘结构。

差异返回新增、删除、修改、重命名的资源及字段摘要；命令用于重命名身份追踪，A→B→C 归纳为 A→C，A→B→A 归零。不能仅保留最后一条 rename。只有连续显式 rename 才按同一身份连接；delete A + add A 不凭名称推断为 rename，最终内容相同则仍可判为文件无变化。被连带修改引用的资源计入变化资源数，重命名资源计一个，不把旧/新文件算两个。

CodeName 关闭→开启→关闭、字段改回原值、新增后删除等净差异为空时禁用保存，保留撤销/重做；直接调用 no-op save 不写文件。save 期间冻结草稿修改，避免成功响应清除请求之后的新编辑。候选刷新用版本号淘汰旧响应，校验未完成时禁止提交旧 hash。

IndexedDB 新格式完整持久化 base schemaRevision、commands、cursor；恢复不把已撤销命令重新执行。旧草稿未保存 cursor，无法恢复丢失信息：保留可读取命令供查看，明确提示旧格式需核对，不静默将全部命令作为待保存状态。

替代方案：合并 set_property/rename 命令会影响撤销与跨资源顺序，收益不足；前后端各自计算 dirty 易分歧，净差异由服务端权威计算。

### 3. Schema 基线独立于数据变化

schemaRevision 覆盖 global.yaml 原始字节与配置解析出的 schemas/types 目录成员及 YAML 原始字节，包含创建、删除、改名与格式改动；不包含 Excel、i18n、output、cache。保守包含整个 global.yaml，避免解析路径/配置漂移。加载前后捕获并比较，禁止混合源版本构建候选；发布前再次检查输入。

源 Schema 变化返回 conflict，不静默重放到新基线、不自动清空本地草稿；用户可查看原草稿并显式放弃后重载。本轮不做自动 rebase。Excel 或译文变化不让草稿过期。

系统锁只能协调 ct 内部操作，不能阻止外部编辑器；捕获与发布前复核缩小竞争窗口，不宣称可防止任意不合作写入进程在最后一瞬间修改文件。

### 4. 只发布差异 YAML，共享事务实现

保存采用同一规范化 root 的 WorkspaceLock，锁内先恢复，再加载资源。抽出可共享事务入口，避免 Schema 用例依赖导出业务或嵌套加锁。FilePublisher 统一处理 create/replace/delete；目标按实际资源来源路径和配置目录定位，不硬编码 config/schemas，不重排未变化 YAML。重命名先验证目标冲突，发布新增和旧路径删除，更新引用的 YAML 同一事务提交。

保留未变化文件字节与 mtime；YAML 业务内容相同即不因序列化风格重写。业务发布范围不含 Excel/layout manifest/i18n/output/成功账本/迁移映射；journal、锁、备份允许在私有状态中暂存。失败恢复应发生在重新加载工作区前，不能先解析混合 YAML。共享锁统一 busy 文案，覆盖 save/export/deploy。

替代方案：保留旧 Apply 锁/journal 造成两套故障语义；直接逐文件 write 无法保证跨资源引用一致。

### 5. Excel 独立更新，读前验证兼容性

保存返回后刷新现有 missing/drifted 状态；状态读取失败不把已成功保存伪装成保存失败，显示状态暂不可用。不能无条件宣称每次保存都导致模板漂移。

在 validate/export 共用 preparation 中，读取任何实际参与校验的表（含 ref 依赖）之前核对可信旧 manifest 与当前 Layout：header_rows、列索引/稳定路径/类型/展开槽位及重建读取所需结构必须匹配；缺失或无法证明匹配时报告需独立更新模板，导出不写产物、不刷新 manifest 或成功账本。只改注释、索引等且读取布局一致时可以继续校验，模板仍可提示外观漂移；新旧布局相同不免除真实数据类型、外键、Enum token 校验。额外非受管尾列维持现有警告行为，不放宽受管列错位。

布局身份从现有 manifest/工作簿表头能够验证的结构获取；manifest 与真实工作簿不符不得只信 manifest。新增结构核对不得以 schema_hash 不同一概失败，schema_hash 还包含注释等非读取变化。

保存不再有数据预检，原来由 Change Plan 承担的「删除仍被数据使用的 Enum item 时阻止」必须换地方，否则会留下静默错误：Binary serializer 用 `names.index(value) if value in names else 0` 解析 Enum，未知 token 会被写成 ordinal 0，而 JSON 原样输出旧字符串，两侧产物互相矛盾且无提示（实测 `ct validate` 无 issue、导出成功）。因此把 Enum token 域校验补进共享数据校验（与 `codename_issues` 同形）：读取时校验 scalar、定长槽位与变长 vector 的每个 token 属于当前声明集合，未知即报类型错误并定位行列与原始值，导出不落产物。这是把数据闸门从「保存前」搬到「产出前」的必要配套，不新增自动迁移。

gen-template 保持显式入口和既有无损预检，旧 manifest 是旧列定位依据。保存不持久化 rename 映射：字段 A→C 保存后，非空旧 A 列无法按稳定路径对应时必须拒绝自动搬移，并保留原工作簿和 manifest；不按同位置或相似名称猜测。用户需另行处理数据后再次显式更新；本轮不新增自动转换或映射 UI。表删除仅移除 YAML，旧工作簿和产物保留到独立操作处理。

### 6. 用户界面只有草稿与保存

状态条显示「N 个资源有未保存修改」，展开摘要显示净差异；0 净差异但有历史时显示「无未保存修改」并保留可用撤销/重做；没有历史、警告或成功反馈时隐藏。保存期间显示忙碌，成功显示「已保存：…」，失败持久显示问题。移除计划 TTL、产物 rebuild/migrate 清单、删除弹窗嵌套完整计划预览。放弃草稿仍需确认，计数依据净差异；仅有历史时文案为清除编辑历史。

## Risks / Trade-offs

- [YAML 可保存但数据暂不可导出] → 这是明确边界；显示模板状态并保持旧成功产物，读取闸门阻止错列数据。
- [重命名后无法自动搬移 Excel] → 保存前摘要明确 Excel 未修改；独立模板更新在不确定时失败，不引入后台迁移记录。
- [兼容性闸门误伤注释编辑或漏掉相同类型列重排] → 比较读取结构而非仅 schema hash/列数，覆盖嵌套结构、字段身份及注释差异测试。
- [数据闸门搬家留空档] → 删除/重命名 Enum item 后旧 token 仍在数据里时，保存不再拦截；Enum token 域闸门必须与保存切换同批落地，否则 Binary 会静默写成 ordinal 0（JSON 与 Binary 分歧）。
- [旧事务/旧浏览器草稿丢数据] → 切换前恢复旧 journal；不能证明完整时拒绝写入并保留材料；旧草稿不自动应用。
- [保存响应丢失] → 刷新 snapshot 核对最终内容；保留本地草稿供核对，不盲重放 rename，不把 conflict 当成功。

## Migration Plan

1. 先加入净差异、Schema revision、YAML 保存用例与读取保护，完成独立测试。
2. 支持旧 apply journal 的一次性恢复检查：已 committed 可核验收尾；未完成事务必须验证所有旧文件/新增目标信息可可靠还原，否则阻止新写入并给出材料路径。旧锁文件的存在不视为新系统锁。
3. 前后端一起切换 save 协议、草稿格式与文案；删除旧 plan 创建/应用端点及运行时，但保留隔离的旧 journal 检测/恢复适配，直到明确完成迁移周期。未应用旧 plan 不执行；有 journal 的材料不能 TTL 清理。
4. 更新主行为说明及测试；不批量重写用户 YAML/Excel。
5. 回退前用当前版本完成共享发布恢复并备份现场；新 save 不改变 YAML 格式，代码可回退，但旧端点不承诺继续执行此前已失效计划，浏览器草稿格式不可静默降级。

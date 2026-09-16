# 重制能力覆盖与验收索引

本表于 2026-09-17 根据当前工作树复核，包含未提交的 Schema/日志相关实现。它是两个 change 的共同迁移清单，不是“已实现”证明。实施时每行补充原生测试/截图/运行记录；代码和规格存在已知冲突时按下方决策处理，不能按所有历史描述盲目重做。

| 现有能力/依据 | 必须承接的行为 | 负责 change / 验收锚点 |
|---|---|---|
| cli-interface；ct/cli.py；test_cli_filter_and_i18n_output | export 的 all/table/lang/verbose/for-build/root，validate/status/gen-template，i18n sync/status/compact，deploy；退出码和纯 JSON stdout；单值精确过滤 | 内核 6.1；对应 delta；命令级差异测试 |
| tool-workspace-separation | 数据目录不放源码，从 cwd 或 --root 运行；独立安装及隔离开发测试 | 内核 6.6–6.9；对应 delta |
| schema-management；schema tests | YAML 解码、未知字段拒绝、命名/类型/角色、深度/循环、确定顺序、主键 int32、CodeName、Enum wire type、uniform 默认省略 | 内核 2.1–2.5；边界夹具 |
| schema-editor/type-system；test_canonical_reader | 所有标量、嵌套 Record、固定/变长 vector、括号文法、Enum token 域、固定空槽默认 | 内核 2.4–2.5；数据逐项对照 |
| schema-editor/query-indexes；test_query_indexes | id/codename/hash 查询、碰撞比较、稳定顺序、合法角色和重复键闸门 | 内核 3.4–3.6；独立读取端 |
| schema-editor/workspace-draft；schema_save/add_resource tests | 所有结构命令、逐步 undo/redo/字段撤销、净差异、基线/hash、YAML-only、零变更不写、来源路径与 Excel 归属、事务恢复 | 内核 3.10–3.12、4.6；界面 3.3–3.9 |
| schema-editor/workbench；fuzzy/schema browser tests | 三类编辑器、Enum item/ordinal 风险、引用跳转、全局 Quick Open、搜索折叠恢复、类型/索引/依赖视图 | 界面 3.1–3.2、3.7；原生键盘/截图测试 |
| excel-processing；test_reading_compat/test_layout/test_planning | 活跃 Sheet、布局 hash/manifest、原始行号、缺失/损坏 manifest 分支、路径迁移、禁止非空数据丢失 | 内核 1.5–1.6、2.3、3.9、3.13 |
| excel-template-styling；test_canonical_template | 2D 表头、富文本两行字体、合并边框、行列尺寸、A(2D+1)冻结、Enum Note、下拉255限制及 warning、不建隐藏辅助 Sheet、白色数据区 | 内核 1.6、3.9；样式属性及打开检查 |
| data-validation；test_enum_token_gate/test_canonical_validate | 类型/主键/CodeName/ref/Enum、批量结构化错误、Excel 位置；辅助数据验证不是唯一数据闸门 | 内核 2.4–2.6；失败产物不变 |
| json-export / json-single-line-records | 每语言、server_only、嵌套序列化、单记录一行、顺序/Unicode/数字格式 | 内核 3.1、3.7；字节对照 |
| flatbuffers-export / csharp-binary-reader-test | FBS、Bundle、uniform vtable、C#/Lua namespace/API、字段类型、O(1)索引、字符串缓存、ref cache、vector base、稀疏i18n行对齐、语言切换generation与fallback | 内核 3.2–3.7；全部既有生成器测试及独立游戏端对照 |
| i18n-pipeline；test_canonical_i18n/test_state | source骨架、四态、confirmed、orphan、compact dry-run、状态分母、有效译文合并和格式 | 内核 3.7–3.8；界面 4.1–4.3 |
| incremental-export | 无变更mtime、强制写、局部Bundle、输出修复、账本独立、类型/译文依赖；新增解析/ref缓存不得漏校验 | 内核 5.1–5.6；变更/损坏矩阵 |
| export-publication；storage/app publication/input tests | 输入捕获、锁、恢复先于加载、新增清理、删除恢复、晚取消、失败账本、未恢复只读诊断、过滤不清理无关产物 | 内核 4.1–4.6；各阶段故障注入 |
| unity-deploy；test_sync_dir/test_deploy | enabled降级、source/dest解析、for-build、同内容不写、代码meta保留/删除、缺源失败、热导出仍部署、CLI失败账本 | 内核 4.4–4.5；界面 4.4独立部署 |
| web-panel | 翻译表选择器只含i18n、状态筛选/列显隐/长文本、同步和进度、模板状态、模块日志与五条历史 | 界面 4.1–4.8；内核 6.10 |
| web-panel-design-system | 统一视觉、跨模块草稿/任务、持续错误、危险确认、help/about/docs、保存响应不清后续编辑 | 界面 1.2–1.4、3.8–3.9、4.8–4.9 |
| launcher；main.dart/settings/auto_launch/tray/single_instance | 单实例、自启/托盘、窗口生命周期、偏好迁移、内置运行时、安装路径 | 界面 2.2–2.5、4.7、5.3；对应 delta |
| 新增 worker 协议 | 握手、能力、所有业务方法、history/logs/tasks、分页revision、大整数、代次、取消/shutdown、重复ID、未知终态 | 内核 1.4、6.2–6.3、6.10；界面 1.5、2.1、4.6 |
| 性能目标 | 冷全量、热CLI/worker、改单表、译文；输出等价与阶段/RSS配对测量 | 内核 1.2、6.5；界面5.2交互测量 |

## 冲突、替代和明确不迁移的内容

- Web 旧“保存自动改 Excel/删除 Excel”与现行 YAML-only 冲突：保留 YAML-only；模板/翻译/导出显式操作，资源删除不删数据文件。
- 浏览器 HTML/CSS/inert/IndexedDB 的技术形式改为 Flutter 对等交互和应用目录持久化；旧 IndexedDB 草稿不自动导入，首启提示先在旧端保存。localStorage 不是草稿存储。
- 旧固定 720×460 launcher 改为可调原生工作台，最小 1024×700；手机390px布局和 Linux GUI 不属于首发，桌面 Windows/macOS、CLI Windows/macOS/Linux。
- Python `ct panel`、Flask 端口/工具目录回退由原生入口替代；旧 Python 留作隔离对照，不是新版本运行依赖。开发安装和测试入口用 tool-workspace-separation delta 明确更新。
- 当前 incremental-export 要求每次重新解析；本次明确改为有效缓存复用，并同步 cli-interface/unity-deploy 表述；完整正确性覆盖不变。
- i18n-pipeline 标为“未实现”的 stale告警/旧fingerprint联动，不自动扩成迁移必做功能；本次新的有效输入缓存按自己的 delta 验收。
- unity-deploy 标为“未实现”的 Web Deploy阶段/ct status新增deploy输出不照搬；保留现有五阶段与 status 三类。原生独立部署为明确新增入口。
- Excel 模板重建维持当前数据值迁移，不承诺任意附加 Sheet/宏/图表/公式文本的无损保留，也不新增公式计算器；不得宣传成完整Excel编辑。
- `excel-processing` 中标注旧意图/未实现的 custom properties 行为，以现行 layout manifest 实现及测试为准；不恢复废弃元数据格式。
- 生成器对照要求输出字节一致；Excel ZIP容器按实际单元格/样式/迁移语义验证，不要求时间戳等容器字节相同。

## 验收记录要求

每行以现有测试为起点建立新实现的等价场景，不要求把 Python 测试机械翻译为 Rust。无法运行的平台/独立读取端明确保留未完成；OpenSpec strict 只证明规划结构合法，不能证明功能或性能通过。对照发现旧 bug 或规格冲突时记录并显式决定修复范围，不静默削减功能或复制数据损坏行为。

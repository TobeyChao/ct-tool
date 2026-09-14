## Why

Schema 工作台只能编辑已有资源，用户新增 Table、Record、Enum 仍须手写 YAML。底层 `add_resource` 只是追加模型对象，尚未打通结构化 JSON、浏览器草稿、资源导航与持久化，无法完成面板内从创建到使用的闭环。

## What Changes

- 增加统一「新增 Schema」入口，支持 Table、Record、Enum，空工作区、空分组及资源面板折叠时均可达。
- 提供结构化创建表单：Table 自动带固定 `Id: int32` 主键；Record 必填首个字段；Enum 必填首个枚举项，支持注释，创建后继续使用现有编辑器。
- 打通可序列化的新增命令、后端模型解码、名称/目标路径校验、候选资源图、撤销重做、刷新恢复和草稿净差异。
- 同一草稿中新建的 Record/Enum 立即可供字段类型选择，新 Table 可供合法 ref 选择；保存整个候选时统一校验依赖。
- 新增资源随「保存变更」事务化写入配置指定目录；新增后删除归零，冲突或保存失败保留草稿且不覆盖已有文件。
- Table 保存后展示模板缺失状态，支持显式生成模板、填写数据、校验与导出；Record/Enum 通过引用表与共享类型产物进入现有生成链路。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `schema-editor/workbench`: 创建三类资源的入口、表单、校验反馈、草稿资源导航和模板后续操作。
- `schema-editor/workspace-draft`: 新增资源结构化命令契约、候选引用、历史恢复、净差异与事务化创建保护。

## Impact

涉及 `ct/web/static/` 的编辑器、类型选择器、资源搜索及草稿状态，`ct/web/schema_workspace_api.py`、`ct/app/schema_workspace/`、资源模型与命名/路径校验，以及 app/API/browser/导出集成测试和使用文档。不新增第三方依赖，不改变 canonical YAML 格式，不新增 CLI 创建命令。

**依赖与实施顺序：** 以在途 `simplify-schema-yaml-save` 完成为前置，沿用其 YAML-only 保存、共享发布器、Schema revision 和净差异协议；不扩展将被移除的 Change Plan/Apply 链路。全链路指创建→草稿编辑→保存→显式模板生成→校验/导出，不意味着一次创建自动执行所有步骤。若前置提案未采用，须先调整本设计的保存边界再实施。

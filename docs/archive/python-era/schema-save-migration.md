# Schema 保存迁移说明（YAML-only save）

本文件是已归档 change `openspec/changes/archive/2026-09-14-simplify-schema-yaml-save` 的交付说明：**回滚步骤**与
**旧 Apply 事务材料处置**。面向运维/发版同学，不涉及实现细节。

## 变更边界

- 保存只写**配置目录内实际变化的 YAML**：不动 Excel、layout manifest、翻译文件、
  导出产物与成功账本；零差异请求不写任何业务文件。
- 新增资源由保存事务创建 YAML；删除/改名资源在同一事务内移除旧文件（写新路径、
  删旧路径）——全部只发生在配置目录内。
- 一次保存 = 一个请求：`POST /api/schema-workspace/save`
  （`schemaRevision` + `commands`（cursor 前缀）+ `candidateHash`）。
- 已删除：`change-plan`、`prepare-apply`、`apply`、`recover` 端点，以及
  `ct/app/schema_workspace/{plan,apply}.py`、持久化计划与 2 小时 TTL。
  旧计划不再执行，也不承诺继续可读。
- 并发保护换成 `schemaRevision`（`config/global.yaml` 原始字节 + schemas/types
  目录成员与 YAML 字节）。Excel 或译文变化**不会**让草稿过期。

## 旧工作区（工作簿存在但没有 layout manifest）

读取闸门要求每张被读取的表都有 `excel/layout_manifests/<Table>.json`（`ref` 依赖表
也算）。本仓库的 `gd/` 已全部具备，不需要任何额外步骤；只有「工作簿存在、但 sidecar
manifest 缺失」的旧工作区会卡住，表现是：

- `ct validate` / `ct export` 报
  `[<Table>.xlsx] … 缺少布局 manifest，无法确认 Excel 与当前 schema 的读取布局兼容`；
- 此时 `ct gen-template --table <Table>` 也会拒绝：
  `<Table> 的 Excel 缺少布局 manifest，无法安全迁移；请先备份后删除旧文件，再重新生成空模板`。

这是刻意设计：没有旧 manifest 就无法证明「旧列 → 当前字段」的映射，工具不猜、也不在
导出时偷偷补写 manifest（那会掩盖漂移）。`ct status` 会把这类表列为 `[template-stale]`，
但它的建议命令对这类工作区同样会失败 —— 按下面的步骤走。

一次性迁移步骤（逐表进行）：

1. 备份旧工作簿：`cp excel/<Table>.xlsx excel/<Table>.xlsx.bak`（或移到工作区外）；
2. 删除原文件：`rm excel/<Table>.xlsx`；
3. 生成空模板 + manifest：`ct gen-template --table <Table>`；
4. 把备份中的数据按**新表头**搬回模板：列顺序、嵌套组位置、Enum token 都可能与旧文件
   不同，请对照表头逐列填写，Enum 值必须属于当前声明集合；
5. 校验并导出：`ct validate --table <Table>` → `ct export --table <Table>`。

全量迁移时把第 1–3 步换成 `ct gen-template --all`（前提是已逐表备份并删除旧工作簿），
再逐表搬数据。若某张表的数据可以丢弃，跳过第 4 步即可，空模板能直接导出。

## 回滚步骤

1. **先用当前版本完成一次恢复**：在要回滚的工作区执行任一 `ct export`/`ct deploy`
   或一次 Web 保存，让共享发布恢复把未完成事务收尾；然后备份现场
   （`config/`、`excel/`、`i18n/`、`output/`、`cache/state.json`、`.ct/`）。
2. 回退代码到旧版本。**YAML 格式未变**，旧版本可以直接读新版本写出的 YAML。
3. 旧端点不会执行此前生成的计划（计划文件与 TTL 已随新版本停止维护）；
   若仍需旧流程，请在旧版本里重新生成计划后再应用。
4. 浏览器草稿：新格式（`ct-draft-v2`，含 cursor + Schema 基线）**不会静默降级**。
   旧版本读不到该格式时会按「无草稿」处理；需要保留编辑内容的，请先在新版本界面
   完成保存或手工记录，再回退。

## 旧 Apply 事务材料处置

旧版本在 `<cache_dir>/` 下留下：`apply.journal.json`、`backups/<plan_id>/`、
`plans/<plan_id>.json`、`staging/<plan_id>/`、`apply.lock`。
新版本的保存流程在**加载配置之前**会调用 `ct/app/schema_workspace/legacy_apply.py`：

| journal phase | 处理 |
|---|---|
| `committed` | 事务已提交：只清理遗留材料（备份/计划/暂存/journal） |
| `backup` / `publish` | 用 `backups/<plan_id>/<relative>` 回滚到保存前版本，然后清理材料 |
| 无法解析 / 格式未知 / 缺少备份 | **阻止保存并保留全部材料**，错误响应带 `conflict.kind="legacy-apply"` 与材料路径 |

规则与注意事项：

- 回滚或清理之后的那一次保存请求会返回 `conflict.kind="legacy-apply-recovered"`，
  提示重新加载工作区（现场刚被改动，调用方手里的基线已失效）。重新加载后即可正常保存。
- 材料**永不按 TTL 清理**；只有能证明可完整还原时才会被消费。
- 旧 `apply.lock` 的存在**不代表忙碌**（旧实现用 `exists`/写入语义，进程死亡会留下文件）；
  新系统只认 `.ct/export.lock` 的系统 advisory lock。
- 若被阻止，按报错里的材料路径人工核对：确认可以丢弃时，删除
  `apply.journal.json` 与对应 `backups|plans|staging` 子目录；确认需要保留数据时，
  先把备份文件复制回 `config/` 再删除材料。

## 相关测试

- `ct/tests/app/test_schema_save_atomicity.py`：不可还原材料阻止写入、可还原材料回滚、
  `committed` 收尾、旧锁不影响忙碌判定。
- `ct/tests/cutover/test_e2e_safety.py`：外部数据变化不使草稿过期、外部 Schema 变化拒绝覆盖、
  非法候选不落盘、中断发布在下次保存前恢复、索引跨重命名保留。
- `ct/tests/app/test_schema_save_workflow.py`：编辑 → 保存 YAML → 模板不兼容拒绝导出 →
  显式更新模板 → 导出成功的完整链路。

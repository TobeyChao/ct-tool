# Schema 保存迁移说明（YAML-only save）

本文件说明当前原生内核的 YAML-only 保存与旧工作区处理。更早的保存迁移说明保留在
`docs/archive/python-era/schema-save-migration.md`，其中的旧端点与恢复步骤不作为当前运行入口。

## 变更边界

- 保存只写**配置目录内实际变化的 YAML**：不动 Excel、layout manifest、翻译文件、
  导出产物与成功账本；零差异请求不写任何业务文件。
- 新增资源由保存事务创建 YAML；删除/改名资源在同一事务内移除旧文件（写新路径、
  删旧路径）——全部只发生在配置目录内。
- 一次保存 = 一个请求：`POST /api/schema-workspace/save`
  （`schemaRevision` + `commands`（cursor 前缀）+ `candidateHash`）。
- 已删除：`change-plan`、`prepare-apply`、`apply`、`recover` 端点、持久化计划与 2 小时 TTL。
  旧计划不再执行，也不承诺继续可读。
- 并发保护换成 `schemaRevision`（`config/global.yaml` 原始字节 + schemas/types
  目录成员与 YAML 字节）。Excel 或译文变化**不会**让草稿过期。

## 旧工作区（工作簿存在但没有 layout manifest）

读取闸门要求每张被读取的表都有 `excel/layout_manifests/<Table>.json`（`ref` 依赖表
也算）。「工作簿存在、但 sidecar manifest 缺失」的旧工作区会被拦，表现是：

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

## 旧 Apply 与未完成发布

原生内核能处理冻结验收所覆盖的 `.ct/export-publication.json` 发布事务。恢复先于资源加载，
会还原旧文件并移除事务新增文件；Web 顶部提供显式恢复入口，完成后刷新快照并重新核对草稿。

旧 Apply 的 `<cache_dir>/apply.journal.json`、未知 journal 格式或缺失备份不能当作原生发布事务猜测恢复。
原生服务保留所有现场并拒绝写入，页面给出原因和材料路径。不要删除 journal 后直接导出：
先停服务，完整备份工作区和备份/暂存材料，人工确认应保留的版本，恢复一致文件集后再处理旧材料。

锁文件存在不代表忙碌，锁由系统持有；正常停止会等待已接受任务完成。操作系统强杀后的恢复
不能代替备份。升级与原生版本回滚见[迁移说明](native-migration.md)。

## 草稿与原生验收

草稿需要相同浏览器配置及 origin（协议、主机、端口），更换 host/port 不会自动搬迁 IndexedDB。
原生候选刷新不会替换旧草稿基线；未知格式、旧基线冲突和存储失败保留内容并提示，不能自动重放。

- Rust：`schema_save`、`schema_draft`、`publication_recovery`、`python_publication`、`workspace_lock`。
- 真实 HTTP/浏览器：保存双守卫、无 Excel 保存、外部修改、模板显式生成、恢复和旧草稿接续。
- 对应迁移映射见 [Web 清单](../native/docs/baseline/web-parity.md)，实际 G1/G2/G3 结果见
  [macOS 验收](../native/docs/baseline/macos-g3-verification.md)。

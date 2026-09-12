## MODIFIED Requirements

### Requirement: ct export command

`ct export` SHALL 执行 canonical 解析校验并默认增量复用生成产物，`--all` SHALL 强制生成及写出所有选中产物。对外步骤 SHALL 保持 `解析校验 → JSON → Accessor → FBS → Bundle`，不新增 Deploy 步骤。导出 SHALL 不执行 i18n sync、不写 i18n/source、不调用 flatc。

全部生成及结构检查成功后 SHALL 可恢复地发布本地产物。本地发布成功时 CLI SHALL 输出 `导出完成: N 张表`，随后执行配置的 Unity 部署并输出 `[deploy] 完成：N 个文件已同步` 或 `[deploy] 无文件变更`，最后提交成功账本。部署失败 SHALL 非零退出并保留旧账本。缓存全命中 SHALL 不省略部署。Web 导出不属于 CLI 自动部署策略。

`--table` / `--lang` SHALL 只接受单个精确值；不存在时 SHALL 友好失败（`表 'X' 不存在` / `语言 'X' 不在可导出语言中（可用: ...）`），不发布产物或提交账本。语言过滤 SHALL 保留当前兼容行为：只构建所选语言 Bundle 和次语言 JSON，但始终生成选中表的主语言 JSON，共享 FBS/Accessor/manifest 仍参与导出。表过滤的 Bundle SHALL 仅含选中表的相应内容。

#### Scenario: Default full export
- **WHEN** 用户执行 `ct export`
- **THEN** 全部表被解析校验，全部语言生成或复用 JSON/FBS/Accessor/Bundle，未变内容保留 mtime；依次输出导出完成和部署结果

#### Scenario: Export specific table
- **WHEN** 用户执行 `ct export --table Item`
- **THEN** 只选择精确匹配 Item 的表，不接受逗号列表或大小写不匹配，保持当前 ref 校验范围

#### Scenario: Export with specific language
- **WHEN** 主语言为 zh，用户执行 `ct export --lang en`
- **THEN** 生成 en Bundle 与 en JSON，同时保留主语言 zh JSON 的生成行为，不重建 zh Bundle

#### Scenario: Validation failure aborts the whole export
- **WHEN** 选中表出现类型、主键、CodeName 或跨表 ref 校验失败
- **THEN** 整个导出中止，output 与 layout manifest 保持发布前内容，退出码非零

#### Scenario: Verbose export shows debug log
- **WHEN** 执行 `ct export --verbose`
- **THEN** 启用 DEBUG 日志，不输出 i18n sync 汇总

#### Scenario: Unknown table or language fails
- **WHEN** 指定不存在的语言 zz 或表 Nope
- **THEN** 友好报错并非零退出，语言错误含可用取值，不发布产物或提交账本

#### Scenario: Forced export
- **WHEN** 执行 `ct export --all`
- **THEN** 强制生成与写出选中产物，保留原有部署流程及参数组合语义

#### Scenario: Deploy failure keeps the old ledger
- **WHEN** 本地发布成功但 Unity 同步失败
- **THEN** CLI 非零退出并输出 `[deploy error]`，完整本地产物保留，`cache/state.json` 不推进

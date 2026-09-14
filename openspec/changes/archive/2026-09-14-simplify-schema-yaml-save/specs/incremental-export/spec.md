## REMOVED Requirements

### Requirement: 事务化 Apply 只发布 schema YAML（fingerprint/cache 发布未实现）
**Reason**: 独立 Apply 生命周期被 YAML-only 保存事务取代：`ct/app/schema_workspace/apply.py`（`WorkspaceApplyLock`、staging、`cache/apply.journal.json`、`recover()`）与 `prepare-apply` 调用链（`create_plan(..., table_fingerprints={})`）一并删除，本 requirement 描述的机制不再存在。
**Migration**: 保存改用共享工作区锁与 FilePublisher，旧未完成事务由一次性恢复适配处理。本 requirement 记录的**事实结论继续成立**：候选 fingerprint/cache 发布至今未实现，`cache/state.json` 仍只在成功导出/部署后推进，Schema 写入不属于增量复用的指纹来源；该结论由本规格其余 requirement（分层指纹与 `cache/state.json` 契约）承载。

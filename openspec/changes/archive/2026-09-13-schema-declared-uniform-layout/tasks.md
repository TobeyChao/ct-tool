## 1. Schema 层

- [x] 1.1 `ct/schema/resources.py`：`TableResource` 增 `uniform: bool = True`
- [x] 1.2 确认 `extra="forbid"` + `exclude_defaults=True` 的组合行为：默认表不进 `resource_to_data`、`schema_hash` 不变；显式 `false` 进
- [x] 1.3 补 schema-management 测试：默认 true / 显式 false / 非布尔类型报错 / 默认值不出现在 `resource_to_data`

## 2. 导出判定链

- [x] 2.1 `ct/app/exporting/build.py`：`use_uniform = table.uniform`，删除 `UNIFORM_FILL_THRESHOLD` 与 `fill_rate >= 阈值` 判定
- [x] 2.2 `fill_rate` 与 `bytes_normal` 仍计算（诊断用）；`_assert_single_vtable` 的调用条件随之改为按声明
- [x] 2.3 `to_layout_info()` 收敛为 `slot_offsets`（去掉 `uniform` / `fill_rate` / `bytes_normal` 的传递）
- [x] 2.4 `ct/app/canonical_export.py`：移除 `UNIFORM_FILL_THRESHOLD` 的转发

## 3. Layout manifest

- [x] 3.1 `ct/excel/layout_manifest.py`：`LayoutManifest` 去掉 `uniform` / `fill_rate`（字段、`from_layout`、`parse`、`manifest_payload`）
- [x] 3.2 确认 `slot_offsets` 在 `uniform: false` 的表上为空、在默认表上仍写入
- [x] 3.3 补 manifest 测试：payload 不含 `uniform` / `fill_rate`
- [x] 3.4 顺带修掉一个守卫缺陷：写入判据从「解析后比语义」改成「**规范序列化逐字节比较**」——
      被 `parse` 忽略的废弃键（`uniform` / `fill_rate` / `layout_revision`）否则永远不会从磁盘上清掉

## 4. 导出输出提示

- [x] 4.1 该行保留填充率，但以**布局形态**（schema 声明）开头、填充率与体积比随后 —— 不写成「填充率 → 布局」，否则会被读成已删除的数据派生决策；体积比 > 1.25 时追加提示（含膨胀倍数与「可对该表声明 `uniform: false`」的指引）
- [x] 4.2 补测试：稀疏表声明定宽时输出提示；稠密表不输出；变长表不给体积对比；布局形态排在该行最前
- [x] 4.3 同步措辞：主规范 `cli-interface`、本 change 的 delta 与本仓 `ct/docs/README.md`

## 5. 逃生门覆盖

- [x] 5.1 fixture 的 `UIConfig.yaml` 显式声明 `uniform: false`，使非定宽路径持续被测试覆盖（accessor 仍发槽位读、manifest 不写 `slot_offsets`）
- [x] 5.2 确认 `ct status` / `gen-template` 对该表行为不变（全套测试覆盖）

## 6. 测试与规格

- [x] 6.1 修既有测试：`test_layout.py`、`test_canonical_export_smoke.py`、`test_incremental_export.py`、`test_exporting_models.py`
- [x] 6.2 同步 6 份规格：`schema-management` / `flatbuffers-export` / `incremental-export` / `excel-processing` / `csharp-binary-reader-test` / `cli-interface`
- [x] 6.3 `ct/.venv/bin/python -m pytest -q` 全绿（583 passed）
- [x] 6.4 `openspec validate --all` 全绿；本 change 归档

## 7. 游戏仓落地验收

- [x] 7.1 重导：**二进制与 10 个 accessor 逐字节不变**（52 个产物 0 DIFF）—— 5 张表填充率均在阈值上，声明默认 true 与原判定同结果
- [x] 7.2 断言 5 个 layout manifest 各少 `uniform` / `fill_rate` 两个键，其余字段不变
- [x] 7.3 C# E3 全字段对账 **451/0** + 负向对照 33 处失败；Lua accept **442/0** + `NEG=1` 负向对照 25 处失败
- [x] 7.4 反向验证「改数据不再翻布局」：在隔离副本上把 UIConfig 两行 `Stack` 改成 `false`（填充率 79.2% → 70.8%，低于旧阈值 0.75），
      确认 manifest 与 accessor **逐字节不变**、`slot_offsets` 不变、accessor 仍发字面量偏移
- [x] 7.5 同步两侧文档：`Docs/框架/Lua配置系统设计.md` 的「槽位 vs 字面量偏移」表、ct-tool `ct/docs/README.md`、`AGENTS.md`

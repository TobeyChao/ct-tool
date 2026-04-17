## 1. Schema Hash 模块

- [x] 1.1 在 `ct-tool/ct/schema/` 新增 `hashing.py`，实现 `compute_schema_hash(schema: TableSchema) -> str`
- [x] 1.2 实现细节：`json.dumps(schema.model_dump(), sort_keys=True, ensure_ascii=False)`，sha256 取前 16 字符
- [x] 1.3 写单元测试 `tests/schema/test_hashing.py`，覆盖 spec 中的四个 hash scenario：新增字段、改注释、调换顺序、确定性

## 2. 元数据读写

- [x] 2.1 在 `ct-tool/ct/excel/template.py` 新增 `TemplateMetadata` dataclass（5 个字段）
- [x] 2.2 新增 `_write_metadata(wb, schema)` 内部函数，写入 5 个 Custom Document Properties
- [x] 2.3 修改 `generate_template`：保存前调用 `_write_metadata`，确认 openpyxl 3.x API（`wb.custom_doc_props` 或同等接口）
- [x] 2.4 新增公开函数 `read_template_metadata(path: Path) -> TemplateMetadata | None`，遵守 spec：缺失/异常/损坏一律返回 None
- [x] 2.5 单元测试：`test_template_metadata.py`，覆盖正常读写、缺字段返回 None、损坏文件返回 None、字段对人不可见

## 3. update_template 实现

- [x] 3.1 在 `template.py` 新增 `update_template(schema, output_path)` 函数
- [x] 3.2 实现读旧数据：`load_workbook(read_only=True)`、按 `old_header_rows` 跳过、收集非空行
- [x] 3.3 调用 `generate_template` 重建文件（含新元数据）
- [x] 3.4 重新打开新文件 `ws.append(row)` 追加旧数据，保存
- [x] 3.5 处理 legacy 路径：`old_header_rows = meta.header_rows if meta else schema.header_rows`
- [x] 3.6 单元测试：覆盖 spec 的 "Update header preserves data rows" 与 "Legacy file uses new schema header_rows" 两个 scenario

## 4. CLI 决策分支

- [x] 4.1 在 `ct-tool/ct/cli.py` 的 `gen_template` 命令上加 `--force` 与 `--update-header` 两个 typer.Option
- [x] 4.2 实现"决策入口"辅助函数 `_decide_template_action(schema, path, force, update_header) -> Action`，返回枚举：`CREATE_NEW`、`SKIP`、`REBUILD`、`UPDATE_PRESERVE`、`REFUSE`
- [x] 4.3 决策逻辑严格遵守 spec 决策矩阵（六种文件状态 × 三种 flag 组合）
- [x] 4.4 处理 table_name 不匹配：任何 flag 都返回 `REFUSE`，附带带 `quest` / `item` 占位符的明确提示
- [x] 4.5 在 `gen_template` 主循环中根据 Action 调度 `generate_template` / `update_template` / 跳过 / 报错
- [x] 4.6 拒绝路径设置非 0 退出码（不影响其他表继续处理）
- [x] 4.7 集成测试 `tests/cli/test_gen_template.py`，覆盖 spec.cli-interface 的全部 9 个 scenario

## 5. ct status 漂移检测

- [x] 5.1 在 `cli.py` 的 `status` 命令中，遍历每张表读取 `read_template_metadata`
- [x] 5.2 计算当前 `schema_hash`，分类为 `matched` / `drifted` / `untracked`
- [x] 5.3 输出三段：数据变更（保留现有行为）、模板漂移、未跟踪模板
- [x] 5.4 全部为空时输出 `✓ 所有表已是最新（数据 + 模板）`
- [x] 5.5 集成测试覆盖 spec 中 status 的 4 个 scenario

## 6. 缓存优化（可选）

- [x] 6.1 在 `cache/state.json` 的每张表条目里添加 `schema_hash` 字段
- [x] 6.2 `status` 优先比对缓存中的 hash，只在 hash 变化的表才打开 Excel 读元数据
- [x] 6.3 `gen-template` 成功后更新缓存中的 hash

## 7. 文档与回归

- [x] 7.1 更新 `CLAUDE.md` 中 gen-template 章节，说明新增 flag 与决策矩阵
- [x] 7.2 准备一个 legacy Excel（无元数据）的样本文件用于手工烟雾测试
- [x] 7.3 手工跑一遍 6 种文件状态 × 3 种 flag 的真实场景（新建/legacy/不匹配/hash 一致/hash 不同无数据/hash 不同有数据）
- [x] 7.4 在 PR 描述里标注"默认行为变化"以提示老用户
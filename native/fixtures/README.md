# fixtures

小而稳定的测试夹具。大体积基准夹具由 ct-xtask 生成到 `target/`，不提交；
真实 `gd/` 数据永不作为夹具。

- `workspaces/`：minimal / complex_types / i18n_sparse / custom_dirs
- `excel/`：active_sheet、formula_cache、date_1904、rich_text_header、sparse_rows
- `schema/`：enum_token、nested_record、vector_fixed
- `journals/`：apply_publish、apply_committed、export_prepared
- `protocol/`：hello_success、hello_mismatch、export_cancel
## 1. reader 保留绝对行号

- [x] 1.1 `ct/excel/reader.py` 新增 `ParsedRows`（rows + excel_rows），
      `read_excel` 改为返回该容器，遍历时记录真实 Excel 行号
- [x] 1.2 适配调用方：`ct/app/validate.py`（校验时传 `excel_rows`）、
      `ct/cli.py::_read_all_rows_for_sync`（只用 `.rows`）
- [x] 1.3 新增测试：空行被跳过但 `excel_rows` 为真实绝对行号；
      `pytest` 全绿

## 2. 校验器填充定位信息

- [x] 2.1 `validate_table` / `validate_refs` 增加 `excel_rows` 可选参数，
      填充 `ValidationIssue.excel_row`
- [x] 2.2 列映射：把 `_flatten_fields` / `_column_span` 暴露为可复用纯函数，
      构建 `{dotted_path: column_index}` 映射
- [x] 2.3 `_validate_field_value` / `_validate_struct` 返回
      `(dotted_path, message)` 对（消息文本逐字不变），struct 子字段
      定位到具体叶子列；填充 `ValidationIssue.column`
- [x] 2.4 新增测试：类型/主键/引用错误的 `excel_row`、`column`、
      `value` 断言 + struct 叶子列；`pytest` 全绿

## 3. 错误文本升级

- [x] 3.1 `ValidationIssue.render()` 输出新格式
      （绝对行号 + 列字母 + 当前值 + 说明），缺失时回退旧格式
- [x] 3.2 更新 `tests/validate/test_issues.py` 旧格式断言为新格式
- [x] 3.3 新增 CLI 测试：构造含错误项目，`ct export` / `ct validate`
      实际输出包含 `Excel 第N行 · 列X (Field) · 当前值`

## 4. 收尾

- [x] 4.1 `pytest` 全绿 + 导出产物快照对比（确认产物不受影响）
- [x] 4.2 更新 `AGENTS.md` 模块表（reader 返回类型、errors.render 说明）
- [x] 4.3 `git diff` 复核无无关改动

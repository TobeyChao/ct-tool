# benches

基准夹具由 `cargo run -p ct-xtask -- bench-fixtures` 生成到 `target/`（固定种子，
不提交仓库）。正式基准在任务 1.2 建立 Python 对照后，以 criterion 或 xtask
计时实现，记录：耗时（中位数/尾部）、峰值 RSS、阶段耗时、缓存命中与产物摘要。
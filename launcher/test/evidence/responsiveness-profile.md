# 桌面 UI 帧时间（任务 5.2，profile 模式）

- 夹具：M 档（50 表 × 2000 行 × 20 列），真实 `ct worker`（`E:\Proj\ct-tool\native\target\release\ct.exe`）
- 口径：`WidgetsBinding.addTimingsCallback` 采到的逐帧 build/raster 时长
- 预览行数：300
- 60Hz 参考：`totalSpan` p95 应 <16.7ms；下表 p95/max 单位均为毫秒

| 阶段 | 帧数 | build p50/p95/max (ms) | raster p50/p95/max (ms) | totalSpan p50/p95/max (ms) |
|---|---|---|---|---|
| 大字段表 | 126 | 0.361 / 0.754 / 2.811 | 1.236 / 1.402 / 1.793 | 2.424 / 3.342 / 4.747 |
| 分页预览 | 460 | 0.471 / 0.734 / 13.341 | 1.269 / 1.467 / 3.049 | 2.555 / 3.456 / 16.753 |
| 持续日志 | 93 | 0.198 / 0.273 / 2.059 | 0.468 / 0.561 / 1.457 | 1.47 / 2.358 / 3.206 |

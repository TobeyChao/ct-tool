# 桌面 UI 帧时间（任务 5.2，profile 模式）

- 夹具：M 档（50 表 × 2000 行 × 20 列），真实 `ct worker`（`E:\Proj\ct-tool\native\target\release\ct.exe`）
- 口径：`WidgetsBinding.addTimingsCallback` 采到的逐帧 build/raster 时长
- 预览行数：300
- 60Hz 参考：`totalSpan` p95 应 <16.7ms；下表 p95/max 单位均为毫秒

| 阶段 | 帧数 | build p50/p95/max (ms) | raster p50/p95/max (ms) | totalSpan p50/p95/max (ms) |
|---|---|---|---|---|
| 大字段表 | 148 | 0.329 / 0.893 / 20.646 | 1.174 / 1.465 / 7.929 | 2.176 / 3.154 / 41.835 |
| 分页预览 | 477 | 0.438 / 0.671 / 13.19 | 1.203 / 1.422 / 2.169 | 2.298 / 3.411 / 16.894 |
| 持续日志 | 94 | 0.202 / 0.334 / 1.961 | 0.423 / 0.72 / 1.367 | 1.331 / 1.849 / 3.05 |

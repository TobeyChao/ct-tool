# Python 成功账本形状留档

`python-state.json` 由旧版 `ct/src/ct/cache/canonical_state.py` 的 `save_state` 写出，源文件 SHA-256 为 `a2ea7f9e58cc16cf50435aad6a74bc661058f59a30e245670ffaa9324914def1`。字段值是专用哨兵，不对应真实游戏数据：`LegacyOnly` 表和 `ja` Bundle 用来验证原生导出在接续旧账本时保留未触及的记录。运行回归只读取本 JSON，不执行 Python。

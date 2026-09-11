# uniform（定宽布局）校验脚本

复现《定宽布局落地方案.md》§1 的实测结论：**patch 的 `uniform=True` 对枚举字段有 bug，修法已验证**。

用 **ct-tool 自己的 fixture 与 venv** 运行（fixture 的表结构与本项目 5 张表相同）：

```bash
CT=/Users/tobeychao/Documents/Projects/ct-tool

# ① 证明 bug：含枚举的表定宽后仍是 2 种 vtable；probe 给枚举槽位推出 offset=0 → 逐行读错
CT_TOOL=$CT $CT/ct/.venv/bin/python uniform_enum_check.py proof

# （不带参数则输出：常规 vs 定宽 的 bundle/每表体积、vtable 数、probe vs 真实行对比）
CT_TOOL=$CT $CT/ct/.venv/bin/python uniform_enum_check.py

# ② 证明修法有效：枚举走 PrependInt8 + Slot(index) → 全部单 vtable + 逐字段一致
CT_TOOL=$CT $CT/ct/.venv/bin/python uniform_fixed_check.py
```

| 脚本 | 作用 |
|---|---|
| `uniform_enum_check.py` | 逐字复刻 patch 的 uniform 逻辑并注入导出器，对比常规/定宽产物；`proof` 子命令给出「字面量 offset 路径 vs 正确 vtable 路径」的逐行读值差异 |
| `uniform_fixed_check.py` | 用「枚举无条件写槽位」的修正版导出，验证单一 vtable 与逐字段一致性 |

**实测结论（2026-09-11）**：

| | patch 原样 | 枚举已修 |
|---|---|---|
| `Item`（有枚举） | ❌ 2 种 vtable，定宽字段 **6/16 读错**（`Id`/`Price` 也错） | ✅ 1 种 vtable，16/16 一致 |
| `UIConfig`（有枚举） | ❌ 2 种 vtable，2/24 读错 | ✅ 1 种 vtable，24/24 一致 |
| `ItemType` / `Quest`（无枚举） | ✅ 正常 | ✅ 正常 |

> 根因：`PrependInt8Slot(slot, v, 0)` 在 `v == 0`（= 第 0 个枚举值）时**不写槽位**；
> 而 patch 只给标量加了无条件写（`_prepend_scalar_slot`），枚举分支漏了。
> 缺一个槽位会改变行总大小 ⇒ **错位整行的偏移**，所以连枚举前面的 `Id`/`Price` 也读错。

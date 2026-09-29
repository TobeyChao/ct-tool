# native/ 架构说明

> 规划与决策记录见 `openspec/changes/rust-native-core/design.md`。
> 本文件描述目录职责与依赖方向，随实现演进更新。

## 依赖方向（只允许向下依赖）

```text
ct-protocol（传输契约，独立）
ct-domain（纯领域模型，独立）
   ▲        ▲        ▲
ct-excel  ct-export  ct-storage / ct-cache
        \     |     /
         ct-app（用例编排，唯一业务入口）
          ▲           ▲
     ct-worker     ct-cli
```

- `ct-protocol` 不依赖业务 crate，Dart 客户端消费同源 schema/golden samples。
- `ct-app` 不感知 CLI/worker 的存在；完成策略（CLI 自动部署 vs 桌面仅导出）
  由调用方以显式参数传入。
- `ct-test-support` 只被 `tests/*` 与各 crate 的 dev-dependencies 使用。

## 为什么扁平 crates/

参考 rust-analyzer（`crates/*` 单层）、ripgrep（`crates/ + tests/ + fuzz/`）、
tokio（`tests-integration/` 顶层）与 helix（按子系统拆 crate + xtask）：
Cargo 的 crate 命名空间本身是扁平的，扁平布局在 10k–1M 行规模下更易维护。
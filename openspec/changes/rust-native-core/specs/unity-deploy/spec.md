## MODIFIED Requirements

### Requirement: 无变化时仍可部署

CLI export SHALL 在每次成功的本地导出之后执行已配置部署，即使生成缓存全部命中且正式产物没有任何写入。缓存命中 SHALL NOT 降低完整数据校验覆盖；只允许复用绑定当前输入及依赖的有效校验结果。Web export SHALL 保持不执行部署。

#### Scenario: fresh 环境无变化表时补齐产物
- **WHEN** 输入未变化、缓存和本地产物完整，但配置的 Unity 目标缺少产物，执行 CLI export
- **THEN** 完成当前输入的校验覆盖，生成产物被复用，本地未变文件 mtime 保留，Unity 缺失文件被同步

#### Scenario: Web does not deploy warm outputs
- **WHEN** 配置启用 deploy，Web 导出全部命中缓存
- **THEN** Web 正常完成本地导出和记账，Unity 目录不被同步

"""导出应用层：请求/结果模型、准备、构建、可恢复发布与完成策略。

模块边界见 ``openspec/changes/restructure-ct-application-pipeline/design.md``：
``models`` 只放数据对象，``prepare``/``build``/``service`` 承载流程，
``ct.storage`` 承载文件发布与工作区锁。
"""

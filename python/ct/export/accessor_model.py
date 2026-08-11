"""访问器生成共享模型（拆分阶段 6.11）。

C# 与 Lua 生成器此前各自重复"筛选客户端字段 / string 字段 / i18n 字段 /
主键"的派生计算；此处收拢为 `AccessorModel`，两生成器消费同一模型，
各自渲染语言文本。

**明确不含槽位索引**：生成路径直接使用 flatc 产出的访问器方法名，
不存在槽位逻辑（见 change design D4）。
"""

from __future__ import annotations

from dataclasses import dataclass

from ct.schema.models import FieldDef, TableSchema


@dataclass(frozen=True)
class AccessorModel:
    """两个生成器真正共享的派生数据。"""

    schema: TableSchema
    client_fields: list[FieldDef]   # 非 server_only
    string_fields: list[FieldDef]   # 客户端 string 字段（含 i18n string）
    i18n_fields: list[FieldDef]     # 空列表 = 无 i18n
    primary: FieldDef


def build_accessor_model(schema: TableSchema) -> AccessorModel:
    """从 TableSchema 计算访问器模型（行为与两生成器现推导一致）。"""
    client_fields = [f for f in schema.fields if not f.server_only]
    return AccessorModel(
        schema=schema,
        client_fields=client_fields,
        string_fields=[f for f in client_fields if f.type == "string"],
        i18n_fields=schema.i18n_fields,
        primary=schema.primary_field,
    )

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, model_validator

from ct.schema.naming import validate_name

BASIC_TYPES = frozenset({"int32", "int64", "float", "double", "bool", "string"})
ALL_FIELD_TYPES = BASIC_TYPES | {"enum", "struct", "array"}
ARRAY_ELEMENT_TYPES = BASIC_TYPES | {"enum"}


class FieldDef(BaseModel):
    name: str
    type: Literal["int32", "int64", "float", "double", "bool", "string",
                  "enum", "struct", "array"]
    # enum
    values: list[str] | None = None
    # struct
    fields: list[FieldDef] | None = None
    # array
    element: str | None = None
    element_values: list[str] | None = None
    separator: str = ","
    # flags
    i18n: bool = False
    ref: str | None = None
    server_only: bool = False
    comment: str = ""

    @model_validator(mode="after")
    def _validate_field(self) -> FieldDef:
        # 命名校验（WYSIWYG 恒等域，见 ct.schema.naming）
        name_err = validate_name(self.name)
        if name_err:
            raise ValueError(f"字段 {self.name}: {name_err}")
        # i18n + server_only 禁止同时标记
        if self.i18n and self.server_only:
            raise ValueError(
                f"字段 {self.name} 不能同时标记 i18n 和 server_only"
                f"（i18n 字段用于客户端 UI，server_only 字段不进入 Binary）"
            )
        if self.type == "enum":
            if not self.values:
                raise ValueError(f"字段 {self.name}: enum 类型必须提供非空 values 列表")
            for v in self.values:
                if not v.isidentifier():
                    raise ValueError(
                        f"字段 {self.name}: enum 值 '{v}' 不是合法标识符"
                    )
        elif self.type == "struct":
            if not self.fields:
                raise ValueError(f"字段 {self.name}: struct 类型必须提供非空 fields 列表")
            for sf in self.fields:
                if sf.type == "array":
                    raise ValueError(
                        f"字段 {self.name}.{sf.name}: struct 内不允许嵌套 array"
                    )
        elif self.type == "array":
            if not self.element:
                raise ValueError(f"字段 {self.name}: array 类型必须提供 element 声明")
            if self.element == "struct":
                raise ValueError(
                    f"字段 {self.name}: array<struct> 不支持，"
                    f"请使用独立子表 + ref 实现一对多关系"
                )
            if self.element == "enum":
                if not self.element_values:
                    raise ValueError(
                        f"字段 {self.name}: array<enum> 必须提供 element_values"
                    )
            elif self.element not in BASIC_TYPES:
                raise ValueError(
                    f"字段 {self.name}: array element 类型 '{self.element}' 非法，"
                    f"允许: {sorted(ARRAY_ELEMENT_TYPES)}"
                )
        # i18n 只允许 string 类型
        if self.i18n and self.type != "string":
            raise ValueError(f"字段 {self.name}: 只有 string 类型可以标记 i18n")
        return self

    def nesting_depth(self) -> int:
        if self.type == "struct" and self.fields:
            return 1 + max(f.nesting_depth() for f in self.fields)
        return 1


class TableSchema(BaseModel):
    table: str
    primary: str
    fields: list[FieldDef]
    json_key: str | None = None
    excel_file: str | None = None

    @model_validator(mode="after")
    def _validate_table(self) -> TableSchema:
        # 命名校验（WYSIWYG 恒等域，见 ct.schema.naming）
        name_err = validate_name(self.table)
        if name_err:
            raise ValueError(f"表 {self.table}: {name_err}")
        field_names = [f.name for f in self.fields]
        if self.primary not in field_names:
            raise ValueError(
                f"表 {self.table}: 主键 '{self.primary}' 不在字段列表中"
            )
        if len(field_names) != len(set(field_names)):
            seen: set[str] = set()
            for n in field_names:
                if n in seen:
                    raise ValueError(f"表 {self.table}: 字段名 '{n}' 重复")
                seen.add(n)
        return self

    @property
    def max_nesting_depth(self) -> int:
        return max(f.nesting_depth() for f in self.fields)

    @property
    def header_rows(self) -> int:
        return self.max_nesting_depth + 1

    @property
    def resolved_excel_file(self) -> str:
        return self.excel_file or f"{self.table}.xlsx"

    @property
    def resolved_json_key(self) -> str:
        return self.json_key or f"{self.table}s"

    @property
    def i18n_fields(self) -> list[FieldDef]:
        return [f for f in self.fields if f.i18n]

    @property
    def has_i18n(self) -> bool:
        return len(self.i18n_fields) > 0

    @property
    def primary_field(self) -> FieldDef:
        return next(f for f in self.fields if f.name == self.primary)

    def all_refs(self) -> list[tuple[str, str]]:
        """返回 [(field_name, "target_table.target_field"), ...]"""
        refs = []
        for f in self.fields:
            if f.ref:
                refs.append((f.name, f.ref))
        return refs

    def ref_tables(self) -> set[str]:
        return {ref.split(".")[0] for _, ref in self.all_refs()}

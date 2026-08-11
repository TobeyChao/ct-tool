"""字段类型 traits 注册表（函数组合成类 6.9 + 查表取代类型分派）。

字段类型是 schema 字面量闭集（``ALL_FIELD_TYPES``）。跨模块共享的
"按类型"行为——coerce / validate / fbs 类型 / json 值 / C# 类型 /
Excel 表头注解——集中在 ``TYPE_TRAITS`` 注册表；新增标量类型 = 注册表
加一行。struct / array 是组合类型，其递归逻辑（子字段、数组元素）也
收拢在本模块，元素/子字段走同一注册表。

模块特有的策略（binary 槽位写入、C# 代码发射）保留在各模块的本地查表
里，但以同一类型键组织；``tests/schema/test_type_traits.py`` 断言
注册表与各模块查表无遗漏。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ct.schema.conventions import FbsConvention
from ct.schema.models import FieldDef


# Binary 表示是 offset 的类型（FlatBuffers UOffsetT），供 binary_writer 分类。
OFFSET_TYPES = frozenset({"string", "struct", "array"})


@dataclass(frozen=True)
class FieldTraits:
    """单个字段类型的全部跨模块行为。

    - ``coerce``: 单元格原始值 → ``(Python 值, 是否成功)``——失败返回原值
      并显式置 ``False``（不再靠下游"返回原值"猜测）；``array_element=True``
      表示字符串拆分路径，int/bool 语义按元素处理；
    - ``validate``: 值 → ``[(dotted_path, 错误消息)]``（空列表 = 通过）；
    - ``fbs_type``: 字段的 FlatBuffers 类型名；
    - ``json_value``: JSON 序列化值；
    - ``csharp_type``: C# 访问器返回类型；
    - ``excel_annotation``: Excel 表头类型注解文本。
    """

    coerce: Callable[..., Any]
    validate: Callable[[Any, FieldDef], list[tuple[str, str]]]
    fbs_type: Callable[[FieldDef], str]
    json_value: Callable[[FieldDef, Any], Any]
    csharp_type: Callable[[FieldDef], str]
    excel_annotation: Callable[[FieldDef], str]


# ---------------------------------------------------------------------------
# coerce（自旧 excel/reader._coerce_scalar 迁入，行为逐字一致）
# ---------------------------------------------------------------------------

_BOOL_TRUE = frozenset({"true", "1", "yes", "TRUE", "True", "YES", "Yes"})
_BOOL_FALSE = frozenset({"false", "0", "no", "FALSE", "False", "NO", "No"})


def _coerce_int(
    field: FieldDef, value: Any, array_element: bool = False
) -> tuple[Any, bool]:
    if value is None:
        return None, True
    try:
        if array_element:
            return (
                int(float(value)) if "." in value else int(value),
                True,
            )
        if isinstance(value, float) and value == int(value):
            return int(value), True
        return int(value), True
    except (TypeError, ValueError):
        return value, False


def _coerce_float(
    field: FieldDef, value: Any, array_element: bool = False
) -> tuple[Any, bool]:
    if value is None:
        return None, True
    try:
        return float(value), True
    except (TypeError, ValueError):
        return value, False


def _coerce_bool(
    field: FieldDef, value: Any, array_element: bool = False
) -> tuple[Any, bool]:
    if value is None:
        return None, True
    if isinstance(value, bool):
        return value, True
    s = str(value).strip()
    if s in _BOOL_TRUE:
        return True, True
    if s in _BOOL_FALSE:
        return False, True
    return value, False


def _coerce_string(
    field: FieldDef, value: Any, array_element: bool = False
) -> tuple[Any, bool]:
    if value is None:
        return None, True
    return str(value), True


def _coerce_enum(
    field: FieldDef, value: Any, array_element: bool = False
) -> tuple[Any, bool]:
    if value is None:
        return None, True
    return str(value), True


def _coerce_passthrough(
    field: FieldDef, value: Any, array_element: bool = False
) -> tuple[Any, bool]:
    """struct 整体不做标量转换（reader 按叶子列分别 coerce 后组装）。"""
    return value, True


def _coerce_array(
    field: FieldDef, value: Any, array_element: bool = False
) -> tuple[Any, bool]:
    """array：按 separator 拆分字符串并逐元素 coerce。

    数组元素失败不在这里标记（``ok`` 恒为 True）——整格 coerce 对数组
    而言总是"成功"（拆分为列表）；元素级错误由 ``validate`` 报带元素
    序号的精确消息，避免与 reader 的整格 issue 双报。
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return [], True
    raw_str = str(value)
    sep = field.separator or ","
    element_type = field.element or ""
    elem_field = FieldDef.model_construct(name="Elem", type=element_type)
    elements: list[Any] = []
    for e in raw_str.split(sep):
        e = e.strip()
        if not e:
            continue
        coerced, _ok = TYPE_TRAITS[element_type].coerce(elem_field, e, True)
        elements.append(coerced)
    return elements, True


# ---------------------------------------------------------------------------
# validate（自旧 validate/types 迁入，消息文本逐字一致）
# ---------------------------------------------------------------------------

def _validate_int(value: Any, field: FieldDef) -> list[tuple[str, str]]:
    if not isinstance(value, int) or isinstance(value, bool):
        return [
            (
                field.name,
                f"期望整数类型，实际值为 {value!r}（{type(value).__name__}）",
            )
        ]
    return []


def _validate_float(value: Any, field: FieldDef) -> list[tuple[str, str]]:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return [
            (
                field.name,
                f"期望数值类型，实际值为 {value!r}（{type(value).__name__}）",
            )
        ]
    return []


def _validate_bool(value: Any, field: FieldDef) -> list[tuple[str, str]]:
    if not isinstance(value, bool):
        return [
            (
                field.name,
                f"期望布尔类型，实际值为 {value!r}（{type(value).__name__}）",
            )
        ]
    return []


def _validate_string(value: Any, field: FieldDef) -> list[tuple[str, str]]:
    if value is not None and not isinstance(value, str):
        return [
            (
                field.name,
                f"期望字符串类型，实际值为 {value!r}（{type(value).__name__}）",
            )
        ]
    return []


def _validate_enum(value: Any, field: FieldDef) -> list[tuple[str, str]]:
    if not isinstance(value, str):
        return [
            (
                field.name,
                f"期望枚举字符串，实际值为 {value!r}（{type(value).__name__}）",
            )
        ]
    if field.values and value not in field.values:
        return [
            (
                field.name,
                f"枚举值 {value!r} 不在允许列表 {field.values} 中",
            )
        ]
    return []


def _validate_array(value: Any, field: FieldDef) -> list[tuple[str, str]]:
    errors: list[tuple[str, str]] = []
    if not isinstance(value, list):
        errors.append(
            (
                field.name,
                f"期望数组类型，实际值为 {value!r}（{type(value).__name__}）",
            )
        )
        return errors

    element_type = field.element
    if not element_type:
        return errors  # schema 加载已保证 element 存在

    for idx, elem in enumerate(value):
        # 数组元素（含 array<enum>）：构造临时 FieldDef，element_values 作为
        # enum 的 values 传入，复用同一标量/枚举校验器。
        elem_field = FieldDef.model_construct(
            name=f"{field.name}[{idx}]",
            type=element_type,
            values=field.element_values,
        )
        for _path, msg in TYPE_TRAITS[element_type].validate(elem, elem_field):
            errors.append((field.name, f"数组第{idx + 1}个元素{msg}"))
    return errors


def _validate_struct(value: Any, field: FieldDef) -> list[tuple[str, str]]:
    errors: list[tuple[str, str]] = []
    if not isinstance(value, dict):
        errors.append(
            (
                field.name,
                f"期望结构体（dict），实际值为 {value!r}（{type(value).__name__}）",
            )
        )
        return errors

    for sub_field in field.fields or []:
        sub_value = value.get(sub_field.name)
        for path, msg in validate_field_value(sub_value, sub_field):
            errors.append((f"{field.name}.{path}", msg))
    return errors


def validate_field_value(
    value: Any, field: FieldDef
) -> list[tuple[str, str]]:
    """校验单个字段值，返回 ``[(dotted_path, 消息)]``（空列表 = 通过）。"""
    # None / 缺失值：string 视为空串，其余报"值不能为空"。
    if field.type == "string" and value is None:
        return []
    if value is None:
        return [(field.name, f"值不能为空（类型 {field.type}）")]
    return TYPE_TRAITS[field.type].validate(value, field)


# ---------------------------------------------------------------------------
# fbs_type / json_value / csharp_type / excel_annotation
# ---------------------------------------------------------------------------

def _fbs_type(field: FieldDef) -> str:
    if field.type == "enum":
        return f"{field.name}{FbsConvention.ENUM_SUFFIX}"
    if field.type == "struct":
        return f"{field.name}{FbsConvention.STRUCT_SUFFIX}"
    if field.type == "array":
        if field.element == "enum":
            return f"[{field.name}{FbsConvention.ELEM_SUFFIX}]"
        return f"[{FbsConvention.TYPE_MAP.get(field.element, field.element)}]"
    return FbsConvention.TYPE_MAP.get(field.type, field.type)


def _json_scalar(field: FieldDef, value: Any) -> Any:
    return value


def _json_enum(field: FieldDef, value: Any) -> Any:
    return str(value) if value is not None else None


def _json_struct(field: FieldDef, value: Any) -> Any:
    return value if isinstance(value, dict) else None


def _json_array(field: FieldDef, value: Any) -> Any:
    if not isinstance(value, list):
        return []
    if field.element == "enum":
        return [str(v) for v in value]
    return value


_CSHARP_TYPE_MAP: dict[str, str] = {
    "int32": "int",
    "int64": "long",
    "float": "float",
    "double": "double",
    "bool": "bool",
    "string": "string",
    "enum": "byte",
}


def csharp_element_type(type_name: str) -> str:
    """array 元素 / 主键的 C# 类型（element 只可能是标量或 enum）。"""
    return _CSHARP_TYPE_MAP.get(type_name, "int")


def _csharp_type(field: FieldDef) -> str:
    if field.type == "array":
        return f"{csharp_element_type(field.element or '')}[]"
    if field.type == "struct":
        return f"{field.name}Struct"
    return csharp_element_type(field.type)


def _annotation_scalar(field: FieldDef) -> str:
    base = field.type
    parts: list[str] = []
    if field.ref:
        parts.append(f"ref:{field.ref}")
    if field.i18n:
        parts.append("i18n")
    if parts:
        return f"{base}[{','.join(parts)}]"
    return base


def _annotation_enum(field: FieldDef) -> str:
    return f"enum[{','.join(field.values or [])}]"


def _annotation_struct(field: FieldDef) -> str:
    return f"{field.name}Struct"


def _annotation_array(field: FieldDef) -> str:
    element = field.element or "?"
    if element == "enum":
        return f"array<enum[{','.join(field.element_values or [])}]>"
    return f"array<{element}>"


# ---------------------------------------------------------------------------
# 注册表（唯一分派表）
# ---------------------------------------------------------------------------

TYPE_TRAITS: dict[str, FieldTraits] = {
    "int32": FieldTraits(
        coerce=_coerce_int,
        validate=_validate_int,
        fbs_type=_fbs_type,
        json_value=_json_scalar,
        csharp_type=_csharp_type,
        excel_annotation=_annotation_scalar,
    ),
    "int64": FieldTraits(
        coerce=_coerce_int,
        validate=_validate_int,
        fbs_type=_fbs_type,
        json_value=_json_scalar,
        csharp_type=_csharp_type,
        excel_annotation=_annotation_scalar,
    ),
    "float": FieldTraits(
        coerce=_coerce_float,
        validate=_validate_float,
        fbs_type=_fbs_type,
        json_value=_json_scalar,
        csharp_type=_csharp_type,
        excel_annotation=_annotation_scalar,
    ),
    "double": FieldTraits(
        coerce=_coerce_float,
        validate=_validate_float,
        fbs_type=_fbs_type,
        json_value=_json_scalar,
        csharp_type=_csharp_type,
        excel_annotation=_annotation_scalar,
    ),
    "bool": FieldTraits(
        coerce=_coerce_bool,
        validate=_validate_bool,
        fbs_type=_fbs_type,
        json_value=_json_scalar,
        csharp_type=_csharp_type,
        excel_annotation=_annotation_scalar,
    ),
    "string": FieldTraits(
        coerce=_coerce_string,
        validate=_validate_string,
        fbs_type=_fbs_type,
        json_value=_json_scalar,
        csharp_type=_csharp_type,
        excel_annotation=_annotation_scalar,
    ),
    "enum": FieldTraits(
        coerce=_coerce_enum,
        validate=_validate_enum,
        fbs_type=_fbs_type,
        json_value=_json_enum,
        csharp_type=_csharp_type,
        excel_annotation=_annotation_enum,
    ),
    "struct": FieldTraits(
        coerce=_coerce_passthrough,
        validate=_validate_struct,
        fbs_type=_fbs_type,
        json_value=_json_struct,
        csharp_type=_csharp_type,
        excel_annotation=_annotation_struct,
    ),
    "array": FieldTraits(
        coerce=_coerce_array,
        validate=_validate_array,
        fbs_type=_fbs_type,
        json_value=_json_array,
        csharp_type=_csharp_type,
        excel_annotation=_annotation_array,
    ),
}

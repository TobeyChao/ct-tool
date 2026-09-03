"""Canonical recursive field type expressions.

YAML uses a compact text grammar (``int32``, ``ItemRarity``,
``vector<DropReward>``), while the domain keeps explicit scalar/named/vector
nodes. Named references may be unresolved while loading text; repository
resolution later adds the ``record:`` or ``enum:`` resource-id prefix.
"""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ct.schema.naming import validate_name


ScalarName: TypeAlias = Literal[
    "int32",
    "int64",
    "float",
    "double",
    "bool",
    "string",
]
NamedKind: TypeAlias = Literal["record", "enum"]

SCALAR_TYPE_NAMES = frozenset(
    {"int32", "int64", "float", "double", "bool", "string"}
)
RESERVED_TYPE_NAMES = SCALAR_TYPE_NAMES | {"vector", "table", "record", "enum"}


class TypeExpressionError(ValueError):
    """A text type expression cannot be parsed into the canonical grammar."""


class ScalarType(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["scalar"] = "scalar"
    name: ScalarName


class NamedType(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["named"] = "named"
    resource_id: str
    expected_kind: NamedKind | None = None

    @model_validator(mode="after")
    def _validate_reference(self) -> NamedType:
        resource_id = self.resource_id.strip()
        if not resource_id:
            raise ValueError("named type resource_id 不能为空")

        prefix: str | None = None
        name = resource_id
        if ":" in resource_id:
            prefix, separator, name = resource_id.partition(":")
            if not separator or prefix not in {"record", "enum"} or ":" in name:
                raise ValueError(
                    "named type resource_id 必须为 record:<Name> 或 enum:<Name>"
                )
            if self.expected_kind is not None and self.expected_kind != prefix:
                raise ValueError(
                    f"resource_id kind '{prefix}' 与 expected_kind "
                    f"'{self.expected_kind}' 不一致"
                )

        if name in RESERVED_TYPE_NAMES:
            raise ValueError(f"'{name}' 是保留类型名，不能作为具名资源")
        name_error = validate_name(name)
        if name_error:
            raise ValueError(f"具名类型 {name}: {name_error}")

        canonical_id = f"{prefix}:{name}" if prefix else name
        object.__setattr__(self, "resource_id", canonical_id)
        if prefix is not None:
            object.__setattr__(self, "expected_kind", prefix)
        return self

    @property
    def name(self) -> str:
        return self.resource_id.partition(":")[2] or self.resource_id

    @property
    def resolved(self) -> bool:
        return self.expected_kind is not None and ":" in self.resource_id

    def resolve(self, kind: NamedKind) -> NamedType:
        """Return the same reference bound to a concrete workspace kind."""
        return NamedType(resource_id=f"{kind}:{self.name}", expected_kind=kind)


class VectorType(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["vector"] = "vector"
    element: ScalarType | NamedType | VectorType

    @model_validator(mode="after")
    def _reject_nested_vector(self) -> VectorType:
        if isinstance(self.element, VectorType):
            raise ValueError(
                "首版不支持 vector<vector<T>>；请使用具名 Record 包装结构"
            )
        return self


TypeExpression: TypeAlias = Annotated[
    ScalarType | NamedType | VectorType,
    Field(discriminator="kind"),
]


class _TextParser:
    def __init__(self, source: str) -> None:
        self.source = source
        self.position = 0

    def parse(self) -> TypeExpression:
        self._skip_whitespace()
        if self.position == len(self.source):
            raise self._error("类型表达式为空")
        expression = self._parse_expression()
        self._skip_whitespace()
        if self.position != len(self.source):
            raise self._error(f"存在多余内容 {self.source[self.position:]!r}")
        return expression

    def _parse_expression(self) -> TypeExpression:
        identifier = self._parse_identifier()
        if identifier == "vector":
            self._skip_whitespace()
            self._expect("<", "vector 后缺少 '<'")
            self._skip_whitespace()
            if self._peek() == ">":
                raise self._error("vector 元素类型不能为空")
            element = self._parse_expression()
            self._skip_whitespace()
            self._expect(">", "vector 缺少配对的 '>'")
            if isinstance(element, VectorType):
                raise self._error(
                    "首版不支持 vector<vector<T>>；请使用具名 Record 包装结构"
                )
            return VectorType(element=element)
        if identifier in SCALAR_TYPE_NAMES:
            return ScalarType(name=cast(ScalarName, identifier))
        try:
            return NamedType(resource_id=identifier)
        except ValueError as exc:
            raise self._error(str(exc)) from exc

    def _parse_identifier(self) -> str:
        start = self.position
        while self.position < len(self.source):
            char = self.source[self.position]
            if char.isspace() or char in "<>,":
                break
            self.position += 1
        if self.position == start:
            raise self._error("此处需要类型名")
        return self.source[start:self.position]

    def _expect(self, expected: str, message: str) -> None:
        if self._peek() != expected:
            raise self._error(message)
        self.position += 1

    def _peek(self) -> str | None:
        if self.position >= len(self.source):
            return None
        return self.source[self.position]

    def _skip_whitespace(self) -> None:
        while self.position < len(self.source) and self.source[
            self.position
        ].isspace():
            self.position += 1

    def _error(self, message: str) -> TypeExpressionError:
        return TypeExpressionError(
            f"无效类型表达式 {self.source!r}（位置 {self.position + 1}）：{message}"
        )


def parse_type_expression(source: str) -> TypeExpression:
    """Parse the controlled YAML grammar into a canonical expression node."""
    if not isinstance(source, str):
        raise TypeExpressionError("类型表达式必须是字符串")
    return _TextParser(source).parse()


def serialize_type_expression(expression: TypeExpression) -> str:
    """Serialize an expression to the unique human-readable YAML spelling."""
    if isinstance(expression, ScalarType):
        return expression.name
    if isinstance(expression, NamedType):
        return expression.name
    if isinstance(expression, VectorType):
        return f"vector<{serialize_type_expression(expression.element)}>"
    raise TypeError(f"不支持的 Type Expression 节点: {type(expression).__name__}")

"""共享的数据准备与校验内核：选中表 → layout → Excel 读取 → issues + 主键集。

``validate`` 与 ``export`` 消费**同一份**内核，避免两套重复的布局构建、Excel
读取、主键 / CodeName / 跨表 ref 校验。两个入口各自保留自己的诊断包装与选中表范围：

- ``canonical_validate`` 把结果摊平成 ``list[Issue]``（缺 Excel 报 WorkspaceIssue
  并继续处理其他表）；
- ``run_canonical_export`` 在缺 Excel 时抛 ``FileNotFoundError``、过滤无匹配时抛
  ``ValueError``、有校验问题时抛 ``CanonicalValidationError``。

本模块**不写任何文件**、不合并译文、不产出产物。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping

from ct.app.canonical_workspace import CanonicalWorkspace
from ct.diagnostics.errors import Issue, IssueCode, ValidationIssue, WorkspaceIssue
from ct.excel.canonical_reader import CanonicalParsedRows, read_canonical_excel
from ct.excel.layout import Layout, build_layout
from ct.excel.layout_manifest import load_manifest
from ct.excel.reading_compat import check_reading_compatibility
from ct.schema.hashing import compute_schema_hash
from ct.schema.resources import (
    CODENAME_FIELD,
    EnumResource,
    RecordResource,
    TableResource,
)
from ct.schema.type_expression import NamedType, TypeExpression, VectorType


def records_map(workspace: CanonicalWorkspace) -> dict[str, RecordResource]:
    return {record.name: record for record in workspace.records}


def enums_map(workspace: CanonicalWorkspace) -> dict[str, EnumResource]:
    return {enum.name: enum for enum in workspace.enums}


def select_tables(
    workspace: CanonicalWorkspace, table_filter: str | None
) -> tuple[TableResource, ...]:
    """选中表：``table_filter`` 为精确匹配（不接受逗号列表/大小写模糊）。"""
    return tuple(
        table
        for table in workspace.tables
        if table_filter is None or table.table == table_filter
    )


def ref_dependency_tables(
    workspace: CanonicalWorkspace, tables: "tuple[TableResource, ...] | list[TableResource]"
) -> tuple[TableResource, ...]:
    """Every table reachable through ``ref`` fields, excluding the input tables.

    Filtered validate/export still has to *read* these workbooks, otherwise the
    foreign-key check can only report "数据未加载" instead of validating values.
    """
    by_name = {table.table: table for table in workspace.tables}
    seen = {table.table for table in tables}
    pending = list(tables)
    closure: list[TableResource] = []
    while pending:
        table = pending.pop()
        for field in table.fields:
            target = field.ref.partition(".")[0] if field.ref else ""
            if not target or target in seen or target not in by_name:
                continue
            seen.add(target)
            dependency = by_name[target]
            closure.append(dependency)
            pending.append(dependency)
    return tuple(sorted(closure, key=lambda item: item.table))


def excel_path_of(workspace: CanonicalWorkspace, table: TableResource) -> Path:
    excel_dir = workspace.resolve("excel_dir")
    return excel_dir / (table.excel_file or f"{table.table}.xlsx")


@dataclass(frozen=True)
class PreparedTable:
    """成功读取的一张表：布局、Excel 路径与解析结果。"""

    table: TableResource
    layout: Layout
    excel_path: Path
    parsed: CanonicalParsedRows
    #: False for a table read only because another selected table references it
    explicit: bool = True


@dataclass(frozen=True)
class PreparationResult:
    """内核输出。``issues`` 的顺序与逐表发现顺序一致（缺 Excel 在表位置处插入）。"""

    selected: tuple[TableResource, ...]
    prepared: tuple[PreparedTable, ...]
    missing_excel: tuple[Path, ...]
    id_sets: dict[str, set] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)
    #: 过滤值没有匹配到任何表时记录该值（两个入口各自决定怎么报）
    unknown_table: str | None = None


def primary_issues(table: TableResource, parsed: CanonicalParsedRows, seen: set) -> list[Issue]:
    """主键为空 / 重复校验，并填充 ``seen``（该表主键集合）。"""
    issues: list[Issue] = []
    for index, row in enumerate(parsed.rows, start=1):
        pk = row.get(table.primary)
        excel_row = (
            parsed.excel_rows[index - 1] if index - 1 < len(parsed.excel_rows) else None
        )
        if pk is None:
            issues.append(
                ValidationIssue(
                    table.table,
                    IssueCode.TYPE,
                    "主键为空",
                    row_index=index,
                    excel_row=excel_row,
                    field=table.primary,
                )
            )
        elif pk in seen:
            issues.append(
                ValidationIssue(
                    table.table,
                    IssueCode.DUPLICATE_PK,
                    f"主键重复: {pk!r}",
                    row_index=index,
                    excel_row=excel_row,
                    field=table.primary,
                    value=pk,
                )
            )
        else:
            seen.add(pk)
    return issues


def codename_issues(table: TableResource, parsed: CanonicalParsedRows) -> list[Issue]:
    """CodeName 索引的数据闸门：**声明了索引的表，每行必须有一个非空且唯一的 CodeName**。

    为什么必须有这道闸门（实测）：导出器建桶表时对空串 `continue`，桶里也**不判重**
    —— 于是两行写同一个 CodeName 时导出**不报错**，运行期 `ByCodeName()` 只命中探测序
    更靠前的那一行，另一行**永远查不到**，且全程没有任何提示。CodeName 的语义就是
    「这张表按它唯一索引」，静默少一行属于最难查的那类缺陷。

    只对**声明了 codename 索引**的表校验：没声明索引的表里 CodeName 就是个普通字段。
    """
    if not any(index.kind == "codename" for index in table.indexes):
        return []
    issues: list[Issue] = []
    seen: dict[str, int] = {}
    for index, row in enumerate(parsed.rows, start=1):
        excel_row = (
            parsed.excel_rows[index - 1] if index - 1 < len(parsed.excel_rows) else None
        )
        value = row.get(CODENAME_FIELD)
        text = "" if value is None else str(value)
        if text == "":
            issues.append(
                ValidationIssue(
                    table.table,
                    IssueCode.TYPE,
                    f"{CODENAME_FIELD} 为空（该表声明了 codename 索引，"
                    "空值这一行永远查不到）",
                    row_index=index,
                    excel_row=excel_row,
                    field=CODENAME_FIELD,
                    value=value,
                )
            )
        elif text in seen:
            issues.append(
                ValidationIssue(
                    table.table,
                    IssueCode.DUPLICATE_CODENAME,
                    f"{CODENAME_FIELD} 重复: {text!r}"
                    f"（首次出现在第 {seen[text]} 行）",
                    row_index=index,
                    excel_row=excel_row,
                    field=CODENAME_FIELD,
                    value=text,
                )
            )
        else:
            seen[text] = index
    return issues


def ref_issues(
    table: TableResource, parsed: CanonicalParsedRows, id_sets: dict[str, set]
) -> list[Issue]:
    """跨表 ref 外键值校验：``field.ref`` 的值必须存在于引用表主键集。"""
    ref_fields = [field for field in table.fields if field.ref]
    if not ref_fields:
        return []
    issues: list[Issue] = []
    for row_index, row in enumerate(parsed.rows, start=1):
        excel_row = (
            parsed.excel_rows[row_index - 1]
            if row_index - 1 < len(parsed.excel_rows)
            else None
        )
        for field in ref_fields:
            target_table = field.ref.partition(".")[0]
            target_field = field.ref.partition(".")[2] or "id"
            value = row.get(field.name)
            values = value if isinstance(value, list) else [value]
            target_ids = id_sets.get(target_table)
            if target_ids is None:
                issues.append(
                    ValidationIssue(
                        table.table,
                        IssueCode.REF,
                        f"引用表 {target_table} 的数据未加载，无法校验",
                        row_index=row_index,
                        excel_row=excel_row,
                        field=field.name,
                        value=value,
                    )
                )
                continue
            for v in values:
                if v is None:
                    continue
                if v not in target_ids:
                    issues.append(
                        ValidationIssue(
                            table.table,
                            IssueCode.REF,
                            f"值 {v!r} 在引用表 {target_table}.{target_field} 中不存在",
                            row_index=row_index,
                            excel_row=excel_row,
                            field=field.name,
                            value=v,
                        )
                    )
    return issues


def _enum_values(
    type_expr: TypeExpression,
    value: object,
    records: dict[str, RecordResource],
    path: tuple[str, ...],
):
    """Yield ``(path, enum name, tokens)`` for every Enum slot inside a value."""
    if value is None:
        return
    if isinstance(type_expr, NamedType):
        name = type_expr.resource_id.partition(":")[2]
        if type_expr.expected_kind == "enum":
            yield path, name, value if isinstance(value, list) else [value]
        elif type_expr.expected_kind == "record" and isinstance(value, dict):
            record = records.get(name)
            if record is None:
                return
            for field in record.fields:
                yield from _enum_values(
                    field.type_expr, value.get(field.name), records, (*path, field.name)
                )
        return
    if isinstance(type_expr, VectorType):
        element = type_expr.element
        if isinstance(element, NamedType) and element.expected_kind == "enum":
            yield path, element.resource_id.partition(":")[2], (
                value if isinstance(value, list) else [value]
            )
        elif isinstance(element, NamedType) and element.expected_kind == "record":
            if not isinstance(value, list):
                return
            for index, item in enumerate(value, start=1):
                yield from _enum_values(element, item, records, (*path, f"[{index}]"))


def enum_issues(
    table: TableResource,
    parsed: CanonicalParsedRows,
    enums: dict[str, EnumResource],
    records: dict[str, RecordResource] | None = None,
) -> list[Issue]:
    """Enum token 域闸门：数据里的 token 必须属于该 Enum 当前声明的 name 集合。

    保存 YAML 不读数据，所以这里是删除 / 重命名 Enum item 后唯一的执行点。
    没有它，Binary serializer 会按 `names.index(value) if value in names else 0`
    把未知 token 静默写成 ordinal 0，而 JSON 仍输出旧字符串。
    """
    records = records or {}
    slots = [
        (field.name, field.type_expr)
        for field in table.fields
        if isinstance(field.type_expr, (NamedType, VectorType))
    ]
    if not slots:
        return []
    issues: list[Issue] = []
    for row_index, row in enumerate(parsed.rows, start=1):
        excel_row = (
            parsed.excel_rows[row_index - 1]
            if row_index - 1 < len(parsed.excel_rows)
            else None
        )
        for field_name, type_expr in slots:
            for path, enum_name, tokens in _enum_values(
                type_expr, row.get(field_name), records, (field_name,)
            ):
                enum = enums.get(enum_name)
                if enum is None:
                    continue  # 缺类型由 schema 级校验负责
                allowed = [item.name for item in enum.values]
                for token in tokens:
                    if token is None or token == "":
                        continue  # 空格子沿用默认值语义，不算未知 token
                    if token in allowed:
                        continue
                    issues.append(
                        ValidationIssue(
                            table.table,
                            IssueCode.TYPE,
                            f"值 {token!r} 不在 Enum {enum_name} 的声明值中"
                            f"（可选：{', '.join(allowed)}）",
                            row_index=row_index,
                            excel_row=excel_row,
                            field=".".join(path),
                            value=token,
                        )
                    )
    return issues


def prepare_tables(
    workspace: CanonicalWorkspace,
    *,
    table_filter: str | None = None,
    before_table: Callable[[TableResource], None] | None = None,
    after_table: Callable[[TableResource, CanonicalParsedRows], None] | None = None,
    excel_bytes: Mapping[Path, bytes] | None = None,
    read_dependencies: bool = True,
) -> PreparationResult:
    """读取并校验选中的表，返回 prepared / 缺失 / 主键集 / issues。

    缺 Excel 的表**不进入** ``prepared`` 与 ``id_sets``（其 ref 校验因此不可用），
    并就地插入一条 ``WorkspaceIssue``，保持与旧 ``canonical_validate`` 相同的输出顺序。

    ``before_table`` / ``after_table`` 让调用方在不复制内核的前提下保留自己的
    逐表行为（export 用它们做取消检查与进度日志；validate 两者都不传）。
    """
    selected = select_tables(workspace, table_filter)
    if table_filter is not None and not selected:
        return PreparationResult((), (), (), {}, [], unknown_table=table_filter)

    records = records_map(workspace)
    enums = enums_map(workspace)
    manifest_dir = workspace.resolve("excel_dir") / "layout_manifests"
    explicit_names = {table.table for table in selected}
    dependencies = (
        ref_dependency_tables(workspace, selected) if read_dependencies else ()
    )
    read_set = (*selected, *dependencies)
    prepared: list[PreparedTable] = []
    missing: list[Path] = []
    id_sets: dict[str, set] = {}
    issues: list[Issue] = []

    for table in read_set:
        if before_table is not None:
            before_table(table)
        excel_path = excel_path_of(workspace, table)
        if not excel_path.exists():
            missing.append(excel_path)
            issues.append(
                WorkspaceIssue(
                    table.table, IssueCode.WORKSPACE, f"Excel 文件不存在: {excel_path}"
                )
            )
            continue
        layout = build_layout(
            table,
            schema_hash=compute_schema_hash(table, (*workspace.records, *workspace.enums)),
            records=records,
        )
        # 读取前闸门：manifest 与真实受管表头都必须证明能按当前布局读取
        compatibility = check_reading_compatibility(
            table.table,
            layout,
            excel_path,
            manifest=load_manifest(manifest_dir, table.table),
        )
        if not compatibility.ok:
            issues.extend(compatibility.issues)
            continue
        parsed = read_canonical_excel(
            excel_path,
            layout,
            table,
            records=records,
            enums=enums,
            data=(excel_bytes or {}).get(excel_path),
        )
        issues.extend(parsed.issues)
        seen: set = set()
        issues.extend(primary_issues(table, parsed, seen))
        issues.extend(codename_issues(table, parsed))
        issues.extend(enum_issues(table, parsed, enums, records))
        prepared.append(
            PreparedTable(
                table,
                layout,
                excel_path,
                parsed,
                explicit=table.table in explicit_names,
            )
        )
        id_sets[table.table] = seen
        if after_table is not None:
            after_table(table, parsed)

    # 跨表 ref 外键值校验需要全部选中表的主键集，故在所有表读完后单独一轮
    for item in prepared:
        issues.extend(ref_issues(item.table, item.parsed, id_sets))

    return PreparationResult(
        selected=selected,
        prepared=tuple(prepared),
        missing_excel=tuple(missing),
        id_sets=id_sets,
        issues=issues,
    )

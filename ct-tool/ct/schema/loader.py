from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path

import yaml

from ct.schema.models import TableSchema


def load_schemas(schemas_dir: Path) -> list[TableSchema]:
    if not schemas_dir.exists():
        raise FileNotFoundError(f"Schema 目录不存在: {schemas_dir}")

    schemas: list[TableSchema] = []
    seen_names: dict[str, Path] = {}

    for yaml_path in sorted(schemas_dir.glob("*.yaml")):
        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data is None:
            continue
        try:
            schema = TableSchema(**data)
        except Exception as e:
            raise ValueError(f"加载 schema 失败 [{yaml_path.name}]: {e}") from e

        if schema.table in seen_names:
            raise ValueError(
                f"表名 '{schema.table}' 重复: "
                f"{seen_names[schema.table].name} 和 {yaml_path.name}"
            )
        seen_names[schema.table] = yaml_path
        schemas.append(schema)

    return schemas


def build_dependency_graph(
    schemas: list[TableSchema],
) -> dict[str, set[str]]:
    table_names = {s.table for s in schemas}
    graph: dict[str, set[str]] = {s.table: set() for s in schemas}
    for schema in schemas:
        for field_name, ref_target in schema.all_refs():
            ref_table = ref_target.split(".")[0]
            if ref_table not in table_names:
                raise ValueError(
                    f"表 {schema.table} 字段 {field_name}: "
                    f"引用的表 '{ref_table}' 不存在"
                )
            graph[schema.table].add(ref_table)
    return graph


def topological_sort(graph: dict[str, set[str]]) -> list[str]:
    in_degree: dict[str, int] = {node: 0 for node in graph}
    reverse: dict[str, list[str]] = defaultdict(list)
    for node, deps in graph.items():
        for dep in deps:
            reverse[dep].append(node)
            in_degree[node] += 1  # node depends on dep

    # 入度为 0 的节点先处理（被依赖的表）
    queue: deque[str] = deque()
    for node, deg in sorted(in_degree.items()):
        if deg == 0:
            queue.append(node)

    result: list[str] = []
    while queue:
        node = queue.popleft()
        result.append(node)
        for dependent in sorted(reverse.get(node, [])):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    if len(result) != len(graph):
        remaining = set(graph) - set(result)
        # 找循环路径
        cycle_hint = " → ".join(sorted(remaining))
        raise ValueError(f"检测到循环引用: {cycle_hint}")

    return result


def load_and_sort_schemas(
    schemas_dir: Path,
) -> tuple[list[TableSchema], list[str]]:
    schemas = load_schemas(schemas_dir)
    if not schemas:
        return [], []
    graph = build_dependency_graph(schemas)
    order = topological_sort(graph)
    schema_map = {s.table: s for s in schemas}
    sorted_schemas = [schema_map[name] for name in order]
    return sorted_schemas, order

"""Architecture gates: dependency direction, side effects, legacy parsing (14.1/14.3/14.5)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from ct.app.schema_workspace.candidate import validate_candidate
from ct.app.schema_workspace.commands_reducer import Command, DraftLog
from ct.app.schema_workspace.plan import build_change_plan

SRC = Path(__file__).parents[2] / "src" / "ct"

FORBIDDEN_FROM_LOWER = ("ct.app", "ct.web", "ct.cli")


def _modules_under(package: str) -> list[Path]:
    root = SRC / package.replace(".", "/")
    return sorted(
        path for path in root.rglob("*.py") if "__pycache__" not in str(path)
    )


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.append(alias.name)
    return names


def _top(module: str) -> str:
    return module.split(".")[0]


def test_lower_layers_never_import_app_web_cli() -> None:
    violations: list[str] = []
    for package in ("ct.schema", "ct.excel", "ct.validate", "ct.export", "ct.cache", "ct.diagnostics", "ct.config"):
        for path in _modules_under(package):
            for imported in _imports(path):
                for forbidden in FORBIDDEN_FROM_LOWER:
                    if imported == forbidden or imported.startswith(forbidden + "."):
                        violations.append(f"{path.relative_to(SRC)} -> {imported}")
    assert violations == [], "\n".join(violations)


def test_config_and_diagnostics_have_no_ct_imports() -> None:
    violations: list[str] = []
    for package in ("ct.config", "ct.diagnostics"):
        for path in _modules_under(package):
            for imported in _imports(path):
                if _top(imported) == "ct" and imported != package:
                    violations.append(f"{path.relative_to(SRC)} -> {imported}")
    assert violations == [], "\n".join(violations)


def test_schema_domain_does_not_import_validation() -> None:
    violations: list[str] = []
    for path in _modules_under("ct.schema"):
        for imported in _imports(path):
            if imported == "ct.validate" or imported.startswith("ct.validate."):
                violations.append(f"{path.relative_to(SRC)} -> {imported}")
    assert violations == [], "\n".join(violations)


def _snapshot_tree(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in str(path) and ".git" not in str(path)
    }


def test_validate_and_plan_are_side_effect_free(tmp_path) -> None:
    from _helpers import build_project
    from ct.app.canonical_workspace import CanonicalWorkspace

    root = build_project(
        tmp_path / "gd",
        schemas=[
            {"table": "Item", "primary": "Id", "fields": [{"name": "Id", "type": "int32"}]}
        ],
    )
    before = _snapshot_tree(root)
    resources = CanonicalWorkspace.load(root).resources.resources
    log = DraftLog(tuple(resources))
    log.execute(Command("add_field", {"owner": "table:Item", "field": {"name": "Price", "type": "int32"}}))
    current, indexes = log.current()
    validate_candidate(current, indexes)
    build_change_plan(tuple(resources), current, old_indexes={}, new_indexes=indexes)
    after = _snapshot_tree(root)
    assert before == after


def test_legacy_type_parsing_absent_from_canonical_domain() -> None:
    """The canonical  domain must never parse legacy struct/array inline
    fields; any occurrence there is a regression."""
    canonical_domain = [
        "schema/type_expression.py",
        "schema/resources.py",
        "schema/resource_repository.py",
        "schema/resource_graph.py",
        "schema/name_validation.py",
        "schema/identity.py",
        "schema/indexes.py",
        "schema/commands.py",
        "schema/naming.py",
        "export/canonical_json.py",
        "export/canonical_fbs.py",
        "export/canonical_binary.py",
        "export/canonical_accessor.py",
        "export/canonical_accessor_model.py",
        "export/index_query.py",
        "excel/layout.py",
        "excel/canonical_reader.py",
        "excel/canonical_template.py",
        "excel/layout_manifest.py",
        "excel/planning.py",
        "app/canonical_workspace.py",
        "cache/fingerprints.py",
        "cache/canonical_state.py",
    ] + [
        str(path.relative_to(SRC))
        for path in (SRC / "app" / "schema_workspace").rglob("*.py")
    ]
    pattern = re.compile(
        r'type\s*==\s*["\']struct["\']'
        r"|type\s*==\s*['\"]array['\"]"
        r"|type:\s*struct|type:\s*array"
        r"|element_values\b"
    )
    # resource_repository keeps a legacy-key DENYLIST to reject old formats
    # (fail-fast), which is detection, not parsing.
    denylist_files = {"schema/resource_repository.py"}
    violations: list[str] = []
    for relative in canonical_domain:
        path = SRC / relative
        if not path.exists():
            continue
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if pattern.search(line) and relative not in denylist_files:
                violations.append(f"{relative}:{line_number}: {line.strip()}")
    assert violations == [], "canonical 域出现旧格式解析:\n" + "\n".join(violations)


def test_no_dependency_cycle_imports() -> None:
    graph: dict[str, set[str]] = {}
    for path in SRC.rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        module = str(path.relative_to(SRC)).replace("/", ".").removesuffix(".py")
        graph.setdefault(module, set())
        for imported in _imports(path):
            if imported.startswith("ct.") and imported != module:
                graph[module].add(imported)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str, stack: list[str]) -> None:
        if node in visiting:
            raise AssertionError(f"检测到 import 环: {stack + [node]}")
        if node in visited:
            return
        visiting.add(node)
        for dep in graph.get(node, ()):
            visit(dep, stack + [node])
        visiting.discard(node)
        visited.add(node)

    for node in list(graph):
        visit(node, [])


def test_route_modules_contain_no_direct_writes_or_generator_work() -> None:
    """14.4: route modules are thin presenters (no YAML/Excel/cache writes,
    os.replace, or generator orchestration)."""
    route_modules = [
        "web/schema_workspace_api.py",
    ]
    forbidden = [
        "os.replace",
        "yaml.safe_dump",
        "openpyxl",
        "cache/",
        "write_bytes",
        "ExportPipeline",
        "build_canonical_table_bytes",
        "generate_canonical_template",
    ]
    violations: list[str] = []
    for relative in route_modules:
        text = (SRC / relative).read_text(encoding="utf-8")
        for pattern in forbidden:
            if pattern in text:
                violations.append(f"{relative} contains {pattern!r}")
    assert violations == [], "\n".join(violations)


def test_no_orphan_css_and_single_source_colors() -> None:
    """12.5: all  CSS is loaded (no orphan files) and brand/status colors
    are defined only in tokens.css (no duplicate color definitions)."""
    static = SRC / "web" / "static"
    index = (static / "index.html").read_text(encoding="utf-8")
    css_files = sorted((static / "styles").glob("*.css"))
    assert css_files  # at least the layers exist
    for css in css_files:
        assert css.name in index, f"CSS 未被 index.html 加载: {css.name}"
    brand_colors = {"#1B4332", "#2F7A56", "#C9A227", "#B23B3B", "#B7791F"}
    tokens = (static / "styles" / "tokens.css").read_text(encoding="utf-8")
    for color in brand_colors:
        assert color in tokens, f"tokens.css 缺少品牌/状态色 {color}"
    for css in css_files:
        if css.name == "tokens.css":
            continue
        text = css.read_text(encoding="utf-8")
        for color in brand_colors:
            assert color not in text, f"{css.name} 重复定义了品牌/状态色 {color}"


def test_no_live_writable_schema_route() -> None:
    """13.6: the legacy Schema write routes are removed entirely (only reads remain)."""
    app_src = (SRC / "web" / "app.py").read_text(encoding="utf-8")
    routes = re.findall(r'@app\.(?:route|get|post|put|delete)\([^\n]*"/api/schemas[^\n]*', app_src)
    assert not routes, "app.py 不应直接定义 /api/schemas 路由（写协议已退役）"
    # legacy schema_routes 模块整体移除：不再存在写路由文件
    assert not (SRC / "web" / "schema_routes.py").exists(), "legacy schema_routes.py 应已移除"

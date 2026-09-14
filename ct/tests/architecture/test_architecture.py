"""Architecture gates: dependency direction, side effects, legacy parsing.

扫描器把源码统一归一化为 ``ct.*`` 模块名：包目录与单文件模块
（``config.py``）都能被发现，``__init__.py`` 映射为包名，相对 import 按
自身 package 解析，``from pkg import child`` 在 child 是本地模块时记为该
模块的边。每个预期扫描目标都会断言存在——目标被改名/删除时立即失败，
而不是静默扫出空集把门禁变成空转。

负例（临时源码树）用于证明门禁本身会失败；产品行为由行为测试验证，二者
不能互相替代。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from ct.app.schema_workspace.candidate import validate_candidate
from ct.app.schema_workspace.candidate import candidate_hash
from ct.app.schema_workspace.netdiff import compute_net_diff
from ct.app.schema_workspace.commands_reducer import Command, DraftLog

PKG = "ct"
SRC = Path(__file__).parents[2] / "src" / PKG

#: 禁止导入 app/web/cli 的下层包（ct.validate 已随 cutover 删除，不再是扫描目标）。
LOWER_LAYER_PACKAGES = (
    "ct.schema",
    "ct.excel",
    "ct.export",
    "ct.cache",
    "ct.diagnostics",
    "ct.config",
)

#: 不得导入 ct 其他任何部分的包（本包及其子模块除外）。
NO_CT_IMPORT_PACKAGES = ("ct.config", "ct.diagnostics", "ct.contracts")

FORBIDDEN_FROM_LOWER = ("ct.app", "ct.web", "ct.cli")


# --------------------------------------------------------------------- scanner


def _name_of(src: Path, path: Path) -> tuple[str, bool]:
    """(归一化模块名, 是否包)。目录里的 ``__init__.py`` 映射为包本身。"""
    parts = list(path.relative_to(src).parts)
    is_package = parts[-1] == "__init__.py"
    if is_package:
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][: -len(".py")]
    return ".".join([PKG, *parts]) if parts else PKG, is_package


def _discover(src: Path) -> dict[str, Path]:
    """全部本地模块：``ct.x.y`` → 文件路径。"""
    found: dict[str, Path] = {}
    for path in sorted(src.rglob("*.py")):
        if "__pycache__" in str(path):
            continue
        name, _ = _name_of(src, path)
        found[name] = path
    return found


def _imports(src: Path, path: Path, known: set[str]) -> list[str]:
    """该文件导入的**本地**模块名（已归一化为 ``ct.*``）。

    相对 import 按文件自身 package 解析；``from pkg import child`` 在 child
    是本地模块时额外产出 ``pkg.child`` 这条边（别名写法同样保留）。
    """
    module, is_package = _name_of(src, path)
    package = module if is_package else module.rsplit(".", 1)[0]
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                up = package.split(".")
                keep = len(up) - (node.level - 1)
                base = (
                    ".".join([*up[:keep], *([base] if base else [])]) if keep > 0 else base
                )
            if not base:
                continue
            names.append(base)
            names.extend(
                f"{base}.{alias.name}" for alias in node.names if alias.name != "*"
            )
    return [name for name in names if name in known]


def _modules_under(src: Path, package: str) -> list[Path]:
    discovered = _discover(src)
    return sorted(
        path
        for name, path in discovered.items()
        if name == package or name.startswith(package + ".")
    )


def _require_module(src: Path, package: str) -> None:
    """预期扫描目标必须存在；否则门禁会静默空转。"""
    if not _modules_under(src, package):
        raise AssertionError(f"扫描目标不存在: {package}")


# ----------------------------------------------------------------------- gates


def _lower_layer_violations(src: Path) -> list[str]:
    discovered = _discover(src)
    known = set(discovered)
    violations: list[str] = []
    for package in LOWER_LAYER_PACKAGES:
        _require_module(src, package)
        for path in _modules_under(src, package):
            for imported in _imports(src, path, known):
                for forbidden in FORBIDDEN_FROM_LOWER:
                    if imported == forbidden or imported.startswith(forbidden + "."):
                        violations.append(f"{path.relative_to(src)} -> {imported}")
    return violations


def _no_ct_import_violations(src: Path) -> list[str]:
    discovered = _discover(src)
    known = set(discovered)
    violations: list[str] = []
    for package in NO_CT_IMPORT_PACKAGES:
        _require_module(src, package)
        for path in _modules_under(src, package):
            for imported in _imports(src, path, known):
                # 本包及其子模块属于内部，不算跨包导入
                if imported == package or imported.startswith(package + "."):
                    continue
                violations.append(f"{path.relative_to(src)} -> {imported}")
    return violations


def _cycle_violations(src: Path) -> list[str]:
    discovered = _discover(src)
    known = set(discovered)
    graph = {
        name: {edge for edge in _imports(src, path, known) if edge != name}
        for name, path in discovered.items()
    }
    visiting: set[str] = set()
    visited: set[str] = set()
    cycles: list[str] = []

    def visit(node: str, stack: list[str]) -> None:
        if node in visiting:
            cycles.append(" -> ".join([*stack, node]))
            return
        if node in visited:
            return
        visiting.add(node)
        for dep in sorted(graph.get(node, ())):
            visit(dep, [*stack, node])
        visiting.discard(node)
        visited.add(node)

    for node in sorted(graph):
        visit(node, [])
    return cycles


# ----------------------------------------------------------- real-source gates


def test_scan_actually_covers_the_real_sources() -> None:
    """非空断言：模块发现必须真的扫到源码，否则后续门禁全是空转。"""
    discovered = _discover(SRC)
    assert len(discovered) >= 40, f"模块发现过少（{len(discovered)}），扫描器可能已失效"
    for expected in ("ct.config", "ct.contracts", "ct.export.deploy", "ct.app.events"):
        assert expected in discovered, f"未发现预期模块 {expected}"
    for package in (*LOWER_LAYER_PACKAGES, *NO_CT_IMPORT_PACKAGES):
        _require_module(SRC, package)


def test_lower_layers_never_import_app_web_cli() -> None:
    violations = _lower_layer_violations(SRC)
    assert violations == [], "\n".join(violations)


def test_config_diagnostics_and_contracts_have_no_ct_imports() -> None:
    violations = _no_ct_import_violations(SRC)
    assert violations == [], "\n".join(violations)


def test_schema_domain_does_not_import_validation() -> None:
    discovered = _discover(SRC)
    known = set(discovered)
    violations: list[str] = []
    for path in _modules_under(SRC, "ct.schema"):
        for imported in _imports(SRC, path, known):
            if imported == "ct.validate" or imported.startswith("ct.validate."):
                violations.append(f"{path.relative_to(SRC)} -> {imported}")
    assert violations == [], "\n".join(violations)


def test_no_dependency_cycle_imports() -> None:
    cycles = _cycle_violations(SRC)
    assert cycles == [], "检测到 import 环:\n" + "\n".join(cycles)


# --------------------------------------------- negative examples (gate proof)


def _write_tree(root: Path, files: dict[str, str]) -> Path:
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def _pad_required_packages(src: Path) -> Path:
    """补齐所有预期扫描目标（空包），让负例只考验被测规则本身。"""
    discovered = set(_discover(src)) if src.exists() else set()
    for package in (*LOWER_LAYER_PACKAGES, *NO_CT_IMPORT_PACKAGES):
        if package in discovered:
            continue
        path = src / Path(*package.split(".")[1:]) / "__init__.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    return src


def test_gate_flags_lower_layer_importing_app(tmp_path) -> None:
    src = _write_tree(
        tmp_path / "ct",
        {
            "__init__.py": "",
            "app/__init__.py": "",
            "app/events.py": "class ProgressReporter: pass\n",
            "export/__init__.py": "",
            "export/deploy.py": "from ct.app.events import ProgressReporter\n",
        },
    )
    _pad_required_packages(src)
    assert _lower_layer_violations(src) == ["export/deploy.py -> ct.app.events"]


def test_gate_flags_aliased_imports(tmp_path) -> None:
    """别名写法不能绕过门禁（`from pkg import child as x` / `import pkg.child as x`）。"""
    src = _write_tree(
        tmp_path / "ct",
        {
            "__init__.py": "",
            "app/__init__.py": "",
            "app/events.py": "class ProgressReporter: pass\n",
            "export/__init__.py": "",
            "export/deploy.py": "from ct.app import events as ev\n",
            "cache/__init__.py": "",
            "cache/store.py": "import ct.app.events as ev\n",
        },
    )
    _pad_required_packages(src)
    violations = _lower_layer_violations(src)
    assert any("export/deploy.py" in v for v in violations), violations
    assert any("cache/store.py" in v for v in violations), violations


def test_gate_detects_relative_import_cycle(tmp_path) -> None:
    src = _write_tree(
        tmp_path / "ct",
        {
            "__init__.py": "",
            "a/__init__.py": "",
            "a/b.py": "from . import c\n",
            "a/c.py": "from . import b\n",
        },
    )
    cycles = _cycle_violations(src)
    assert cycles, "相对导入环未被检出"


def test_gate_accepts_a_legal_acyclic_graph(tmp_path) -> None:
    src = _write_tree(
        tmp_path / "ct",
        {
            "__init__.py": "",
            "contracts.py": "class ProgressReporter: pass\n",
            "schema/__init__.py": "",
            "schema/resources.py": "from ct.contracts import ProgressReporter\n",
            "export/__init__.py": "",
            "export/build.py": "from ct.schema.resources import ProgressReporter\n",
            "config.py": "class GlobalConfig: pass\n",
            "diagnostics/__init__.py": "from ct.diagnostics.errors import Issue\n",
            "diagnostics/errors.py": "class Issue: pass\n",
        },
    )
    _pad_required_packages(src)
    assert _lower_layer_violations(src) == []
    assert _no_ct_import_violations(src) == []
    assert _cycle_violations(src) == []


def test_missing_scan_target_fails_loudly(tmp_path) -> None:
    """目标被删除/改名时门禁必须报错，而不是静默扫出空集。"""
    src = _write_tree(
        tmp_path / "ct",
        {
            "__init__.py": "",
            "export/__init__.py": "",
            "export/build.py": "",
        },
    )
    try:
        _lower_layer_violations(src)
    except AssertionError as exc:
        assert "扫描目标不存在" in str(exc)
    else:  # pragma: no cover - 门禁失效才会走到
        raise AssertionError("缺少扫描目标却未失败")


def test_gate_flags_config_importing_schema(tmp_path) -> None:
    src = _write_tree(
        tmp_path / "ct",
        {
            "__init__.py": "",
            "contracts.py": "",
            "config.py": "from ct.schema import resources\n",
            "schema/__init__.py": "",
            "schema/resources.py": "",
            "diagnostics/__init__.py": "from ct.diagnostics.errors import Issue\n",
            "diagnostics/errors.py": "class Issue: pass\n",
        },
    )
    violations = _no_ct_import_violations(src)
    assert any("config.py" in v for v in violations), violations


def test_own_subpackage_import_is_not_a_violation(tmp_path) -> None:
    """回归：`ct.diagnostics.__init__` 导入自己的子模块必须合法。

    旧规则用 `imported != package` 字符串相等判断，会把它误报为违规。
    """
    src = _write_tree(
        tmp_path / "ct",
        {
            "__init__.py": "",
            "contracts.py": "",
            "config.py": "",
            "diagnostics/__init__.py": "from ct.diagnostics.errors import Issue\n",
            "diagnostics/errors.py": "class Issue: pass\n",
        },
    )
    assert _no_ct_import_violations(src) == []


# ---------------------------------------------------------- side-effect gates


def _snapshot_tree(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in str(path) and ".git" not in str(path)
    }


def test_validate_and_net_diff_are_side_effect_free(tmp_path) -> None:
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
    compute_net_diff(
        (tuple(resources), {}), (current, indexes), log.commands, cursor=log.cursor
    )
    candidate_hash(current, indexes)
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
        "contracts.py",
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


def test_adapters_do_not_orchestrate_generators_or_the_ledger() -> None:
    """CLI/Web 只负责参数、呈现与任务生命周期。

    生成器编排与成功记账必须留在应用用例（``ct.app.exporting.service``）里；
    适配器可以导入 ``ct.config`` 做只读展示（例如面板显示 cache 目录）。
    """
    forbidden = (
        "run_pipeline(",
        "persist_export_state",
        "ArtifactCache",
        "build_canonical_table_bytes",
        "build_canonical_bundle",
    )
    violations: list[str] = []
    for relative in ("cli.py", "web/tasks.py"):
        text = (SRC / relative).read_text(encoding="utf-8")
        for pattern in forbidden:
            if pattern in text:
                violations.append(f"{relative} contains {pattern!r}")
    assert violations == [], "适配器里出现生成器编排或记账：\n" + "\n".join(violations)


def test_no_orphan_css_and_single_source_colors() -> None:
    """12.5: all  CSS is loaded (no orphan files) and brand/status colors
    are defined only in tokens.css (no duplicate color definitions)."""
    static = SRC / "web" / "static"
    index = (static / "index.html").read_text(encoding="utf-8")
    css_files = sorted((static / "styles").glob("*.css"))
    assert css_files  # at least the layers exist
    for css in css_files:
        assert css.name in index, f"CSS 未被 index.html 加载: {css.name}"
    brand_colors = {"#1E4635", "#2F7A56", "#C9A227", "#A83B3B", "#A8731F"}
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

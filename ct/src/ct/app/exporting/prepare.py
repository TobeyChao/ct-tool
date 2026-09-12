"""输入捕获与复核：本次导出消费的输入快照，以及「从捕获内容读取」。

设计要点（design 决策 2）：

- ``InputRevision`` 记录**规范化绝对路径**、存在性与 SHA-256，并额外记录
  schemas/types 目录的成员列表——只比对文件内容无法发现新增/删除的资源。
- 源 Excel 字节**只捕获一次**，reader 从该字节读取，因此成功账本里的 Excel hash
  必然等于实际解析的内容（不再在生成完成后重读磁盘）。
- 捕获前后与发布前各复核一次；不一致即友好失败，不发布混合输入集合。
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from ct.app.canonical_workspace import CanonicalWorkspace
from ct.app.exporting.models import InputChangedError
from ct.config import GlobalConfig, load_config
from ct.schema.resources import TableResource


def normalize(path: Path) -> Path:
    """规范化路径：解析符号链接/相对段并统一大小写，作为快照的身份键。"""
    return Path(os.path.normcase(str(Path(path).resolve())))


@dataclass(frozen=True)
class FileRevision:
    path: str
    exists: bool
    sha256: str | None = None
    size: int | None = None


@dataclass(frozen=True)
class InputRevision:
    """一次输入快照：文件集合 + 资源目录成员。"""

    files: tuple[FileRevision, ...]
    #: (目录规范化路径, 该目录下 *.yaml 成员名有序元组)
    directories: tuple[tuple[str, tuple[str, ...]], ...] = ()

    @classmethod
    def capture(
        cls, paths: Iterable[Path], directories: Iterable[Path] = ()
    ) -> "InputRevision":
        revisions: list[FileRevision] = []
        seen: set[str] = set()
        for path in paths:
            key = str(normalize(path))
            if key in seen:
                continue
            seen.add(key)
            if path.is_file():
                payload = path.read_bytes()
                revisions.append(
                    FileRevision(
                        key,
                        True,
                        hashlib.sha256(payload).hexdigest(),
                        len(payload),
                    )
                )
            else:
                revisions.append(FileRevision(key, False))
        members = tuple(
            (
                str(normalize(directory)),
                tuple(sorted(p.name for p in directory.glob("*.yaml"))),
            )
            for directory in directories
        )
        return cls(tuple(revisions), members)

    def hash_of(self, path: Path) -> str | None:
        key = str(normalize(path))
        for revision in self.files:
            if revision.path == key:
                return revision.sha256
        return None

    def changes_since(self, other: "InputRevision") -> list[str]:
        """相对 ``other`` 的变化描述（新增 / 删除 / 内容变化 / 目录成员变化）。"""
        changes: list[str] = []
        left = {r.path: r for r in other.files}
        right = {r.path: r for r in self.files}
        for key in sorted(set(left) | set(right)):
            before, after = left.get(key), right.get(key)
            if before is None and after is not None:
                changes.append(f"新增输入 {key}")
            elif after is None and before is not None:
                changes.append(f"移出输入范围 {key}")
            elif before is not None and after is not None:
                if before.exists != after.exists:
                    changes.append(
                        f"输入{'出现' if after.exists else '消失'} {key}"
                    )
                elif before.sha256 != after.sha256:
                    changes.append(f"输入内容变化 {key}")
        dirs_left = dict(other.directories)
        dirs_right = dict(self.directories)
        for key in sorted(set(dirs_left) | set(dirs_right)):
            if dirs_left.get(key) != dirs_right.get(key):
                added = sorted(set(dirs_right.get(key, ())) - set(dirs_left.get(key, ())))
                removed = sorted(set(dirs_left.get(key, ())) - set(dirs_right.get(key, ())))
                detail = []
                if added:
                    detail.append("新增 " + ", ".join(added))
                if removed:
                    detail.append("删除 " + ", ".join(removed))
                changes.append(f"资源目录成员变化 {key}（{'；'.join(detail)}）")
        return changes


def excel_path_of(workspace: CanonicalWorkspace, table: TableResource) -> Path:
    return workspace.resolve("excel_dir") / (
        table.excel_file or f"{table.table}.xlsx"
    )


def capture_sources(root: Path) -> tuple[GlobalConfig, dict[Path, bytes]]:
    """捕获 ``global.yaml`` + ``schemas/*.yaml`` + ``types/*.yaml`` 的字节。

    返回**从捕获内容解析出的** ``GlobalConfig`` 与路径→字节映射；两者一起交给
    ``CanonicalWorkspace.load``，schema 资源集合也由这份映射决定（不再 glob），
    因此「解析用的内容」与「复核的内容」是同一份。
    """
    config_path = Path(root).resolve() / "config" / "global.yaml"
    contents: dict[Path, bytes] = {}
    text: str | None = None
    if config_path.is_file():
        contents[config_path] = config_path.read_bytes()
        text = contents[config_path].decode("utf-8")
    config = load_config(root, text=text)
    for directory in (config.resolve("schemas_dir"), config.resolve("types_dir")):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.yaml")):
            contents[path] = path.read_bytes()
    return config, contents


def capture_translation_contents(
    workspace: CanonicalWorkspace,
    *,
    tables: Iterable[TableResource],
    languages: Iterable[str],
    primary_lang: str,
) -> dict[Path, bytes]:
    """捕获本次导出**实际消费**的译文文件字节（含主语言）。"""
    i18n_dir = workspace.resolve("i18n_dir")
    captured: dict[Path, bytes] = {}
    for table in tables:
        for lang in sorted({*languages, primary_lang}):
            path = i18n_dir / lang / f"{table.table}.json"
            if path.is_file():
                captured[path] = path.read_bytes()
    return captured


def capture_manifest_contents(
    workspace: CanonicalWorkspace, *, tables: Iterable[TableResource]
) -> dict[Path, bytes]:
    """捕获旧的 layout manifest 字节（作为本次导出消费的输入快照）。"""
    manifest_dir = workspace.resolve("excel_dir") / "layout_manifests"
    captured: dict[Path, bytes] = {}
    for table in tables:
        path = manifest_dir / f"{table.table}.json"
        if path.is_file():
            captured[path] = path.read_bytes()
    return captured


def read_excel_bytes(
    workspace: CanonicalWorkspace, tables: Iterable[TableResource]
) -> dict[Path, bytes]:
    """**只捕获一次**选中表的 Excel 字节，供 reader 与账本共用。"""
    captured: dict[Path, bytes] = {}
    for table in tables:
        path = excel_path_of(workspace, table)
        if path.is_file():
            captured[path] = path.read_bytes()
    return captured


def consumed_paths(
    workspace: CanonicalWorkspace,
    *,
    tables: Iterable[TableResource],
    languages: Iterable[str],
    primary_lang: str,
    include_manifests: bool = True,
) -> list[Path]:
    """本次导出实际消费的输入文件集合（含旧 layout manifest 与译文）。

    ``include_manifests``：layout manifest 既被**读**（作为比较旧布局的输入）又被
    本次导出**写**（design 决策 4 把它列为发布目标）。因此它只进入「记录用」快照，
    不进入发布前的变更复核 —— 否则本次自己刚写的 manifest 会被判成「输入变化」。
    """
    config = workspace.config
    excel_dir = config.resolve("excel_dir")
    i18n_dir = config.resolve("i18n_dir")
    paths: list[Path] = [config.project_root / "config" / "global.yaml"]
    paths.extend(sorted(config.resolve("schemas_dir").glob("*.yaml")))
    paths.extend(sorted(config.resolve("types_dir").glob("*.yaml")))
    langs = {*languages, primary_lang}
    for table in tables:
        paths.append(excel_path_of(workspace, table))
        if include_manifests:
            paths.append(excel_dir / "layout_manifests" / f"{table.table}.json")
        for lang in sorted(langs):
            paths.append(i18n_dir / lang / f"{table.table}.json")
    return paths


def capture_export_inputs(
    workspace: CanonicalWorkspace,
    *,
    tables: Iterable[TableResource],
    languages: Iterable[str],
    primary_lang: str,
    include_manifests: bool = False,
) -> InputRevision:
    """捕获输入快照。默认**不含** layout manifest（它是发布目标，见上）。"""
    config = workspace.config
    return InputRevision.capture(
        consumed_paths(
            workspace,
            tables=tables,
            languages=languages,
            primary_lang=primary_lang,
            include_manifests=include_manifests,
        ),
        directories=[config.resolve("schemas_dir"), config.resolve("types_dir")],
    )


def verify_inputs_unchanged(
    before: InputRevision,
    after: InputRevision,
    *,
    when: str,
) -> None:
    """复核输入未变；有变化即失败（不发布混合输入集合）。"""
    changes = after.changes_since(before)
    if changes:
        preview = "；".join(changes[:5])
        more = f"（共 {len(changes)} 处）" if len(changes) > 5 else ""
        raise InputChangedError(
            f"输入在{when}发生变化，已中止导出以免发布混合版本：{preview}{more}"
        )

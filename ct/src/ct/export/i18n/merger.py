from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_translation(i18n_dir: Path, lang: str, table: str) -> dict[str, dict[str, Any]]:
    """读取 i18n/{lang}/{table}.json，文件不存在返回空 dict。"""
    path = i18n_dir / lang / f"{table}.json"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _sort_keys(keys: list[str], field_order: list[str]) -> list[str]:
    """key 形如 '{id}.{field}'。先按 id 数值升序，再按 field 在 schema 中的顺序。"""
    field_index = {name: i for i, name in enumerate(field_order)}

    def sort_key(k: str) -> tuple:
        head, _, tail = k.partition(".")
        try:
            id_part: tuple[int, int | str] = (0, int(head))
        except ValueError:
            id_part = (1, head)
        rank = field_index.get(tail, len(field_order))
        return id_part, rank, tail

    return sorted(keys, key=sort_key)


def _serialize_object(data: dict[str, Any], field_order: list[str]) -> str:
    """紧凑 JSON：每个 key 占一行，按 id 数值 + 字段顺序排序（便于翻译者扫读/diff）。"""
    if not data:
        return "{}\n"
    keys = _sort_keys(list(data.keys()), field_order)
    lines = ["{"]
    for i, key in enumerate(keys):
        key_str = json.dumps(key, ensure_ascii=False)
        value_str = json.dumps(data[key], ensure_ascii=False, separators=(", ", ": "))
        suffix = "," if i < len(keys) - 1 else ""
        lines.append(f"  {key_str}: {value_str}{suffix}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _write_if_changed(path: Path, content: str) -> None:
    """内容一致时不重写，避免无谓的 mtime 变化（触发外部增量检测/重新导入）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if path.read_text(encoding="utf-8") == content:
            return
    except FileNotFoundError:
        pass
    path.write_text(content, encoding="utf-8")


def write_lang_file(
    data: dict[str, dict[str, Any]], path: Path, field_order: list[str]
) -> None:
    """写出 lang 文件。data 形如 {'1001.name': {'source': ..., 'text': ..., 'confirmed': ..., 'status': ...}}。"""
    _write_if_changed(path, _serialize_object(data, field_order))


def write_source_file(data: dict[str, str], path: Path, field_order: list[str]) -> None:
    """写出 source 文件。data 形如 {'1001.name': '铁剑'}。"""
    _write_if_changed(path, _serialize_object(data, field_order))

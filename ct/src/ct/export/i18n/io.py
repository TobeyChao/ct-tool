from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _entry_value_to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(", ", ": "))


def _sort_keys(keys: list[str], field_order: list[str]) -> list[str]:
    """key 形如 '{id}.{field}'。先按 id 数值升序，再按 field 在 schema 中的顺序。"""
    field_index = {name: i for i, name in enumerate(field_order)}

    def sort_key(k: str) -> tuple:
        head, _, tail = k.partition(".")
        try:
            id_part: tuple[int, int | str] = (0, int(head))
        except ValueError:
            id_part = (1, head)
        field_rank = field_index.get(tail, len(field_order))
        return id_part, field_rank, tail

    return sorted(keys, key=sort_key)


def _serialize_object(data: dict[str, Any], field_order: list[str]) -> str:
    if not data:
        return "{}\n"
    keys = _sort_keys(list(data.keys()), field_order)
    lines = ["{"]
    for i, key in enumerate(keys):
        key_str = json.dumps(key, ensure_ascii=False)
        value_str = _entry_value_to_json(data[key])
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


def _write_with_roundtrip_check(content: str, data: dict[str, Any], path: Path) -> None:
    parsed = json.loads(content)
    if parsed != data:
        raise RuntimeError(
            f"紧凑 JSON 写出自检失败: {path}（往返结果不等价）"
        )
    _write_if_changed(path, content)


def dump_lang_file(data: dict[str, dict[str, Any]], path: Path, field_order: list[str]) -> None:
    """写出 lang 文件。data 形如 {'1001.name': {'source': ..., 'text': ..., 'confirmed': ..., 'status': ...}}。"""
    content = _serialize_object(data, field_order)
    _write_with_roundtrip_check(content, data, path)


def dump_source_file(data: dict[str, str], path: Path, field_order: list[str]) -> None:
    """写出 source 文件。data 形如 {'1001.name': '铁剑'}。"""
    content = _serialize_object(data, field_order)
    _write_with_roundtrip_check(content, data, path)

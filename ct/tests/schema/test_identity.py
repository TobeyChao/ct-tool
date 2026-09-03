from __future__ import annotations

from uuid import UUID

from ct.schema.identity import FieldIdentity, canonical_field_path, resource_id
from ct.schema.resources import FieldDef, TableResource, resource_to_data


def test_resource_and_canonical_field_paths_are_explicit() -> None:
    owner = resource_id("table", "Item")

    assert owner == "table:Item"
    assert canonical_field_path(owner, "Rewards") == "table:Item/Rewards"
    assert canonical_field_path(owner, "Rewards", "ItemId") == (
        "table:Item/Rewards/ItemId"
    )


def test_persisted_field_id_survives_reorder() -> None:
    before = FieldIdentity.from_persisted(
        source_key="config/schemas/Item.yaml",
        owner_id="table:Item",
        field_segments=("Name",),
    )
    after_reorder = FieldIdentity.from_persisted(
        source_key="config/schemas/Item.yaml",
        owner_id="table:Item",
        field_segments=("Name",),
    )

    assert before == after_reorder
    assert before.field_id.startswith("field:")


def test_explicit_rename_and_move_keep_draft_session_identity() -> None:
    original = FieldIdentity.from_persisted(
        source_key="config/schemas/Item.yaml",
        owner_id="table:Item",
        field_segments=("Name",),
    )

    renamed = original.relocate(
        owner_id="table:Item",
        field_segments=("DisplayName",),
    )
    moved = renamed.relocate(
        owner_id="record:Presentation",
        field_segments=("DisplayName",),
    )

    assert renamed.field_id == original.field_id == moved.field_id
    assert renamed.canonical_path == "table:Item/DisplayName"
    assert moved.canonical_path == "record:Presentation/DisplayName"


def test_new_draft_field_uses_ephemeral_uuid_only_in_session() -> None:
    identity = FieldIdentity.for_draft(
        owner_id="table:Item",
        field_segments=("NewField",),
        uuid_factory=lambda: UUID("12345678-1234-5678-1234-567812345678"),
    )
    table = TableResource(
        table="Item",
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="NewField", type="string"),
        ],
    )

    assert identity.field_id == "draft-field:12345678-1234-5678-1234-567812345678"
    assert "uuid" not in str(resource_to_data(table)).lower()
    assert "draft-field" not in str(resource_to_data(table))

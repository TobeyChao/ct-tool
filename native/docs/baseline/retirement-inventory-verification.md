# Python retirement inventory and active documentation (2026-09-30)

[The inventory](python-retirement-inventory.json) contains 312 classified entries:
262 removals, 33 retained current entries, and 17 retained historical experiments.
It expands the initial reference scan to every one of the 249 versioned files in
`ct/`, all native Python fixture/benchmark adapters, both formal test-proj preparation
scripts, their historical counterparts, and the active CI/tool/document references.

Each entry records its owner, source checksum, disposition, concrete replacement,
historical snapshot where needed, and reason. All replacement/archive paths were
checked. The 85-file/690-function test reference inventory is preserved, and source
checksums match it. Static Web files map to their migrated locations and all old
documents/assets have a historical snapshot under `docs/archive/python-era/`.
Python generator snapshots and independent fixture manifests remain immutable.

This inventory is the concrete deletion scope, not evidence that deletion has happened.
Ignored/untracked caches, virtual environments, unrelated experiments and real `gd/`
are not part of the removal list. Two formal test-proj scripts will be removed; the
17 audited historical experiments remain non-active and retain their source hashes.
Explicit live-Python benchmark options are listed for final removal alongside the
old business/install/pytest workflow. The obsolete isolation script that defaults to
Windows and real `gd/` is superseded by temporary-workspace runtime-check acceptance.

Commands actually run:

```sh
node native/tools/check-retirement.mjs
node native/tools/check-docs.mjs
```

The first check verified all 312 classifications, all replacement/archive paths,
262 pre-removal source checksums and all frozen historical test checksums. Its
`--after-deletion` mode requires removed paths absent and rejects newly introduced
unclassified Python code. The inventory's SHA-256 guard rejects malformed edits
before checking scope. The second check verified nine active documents, all 26 local
file links, and absence of retired documentation/install entry points.

Current documentation is now in `docs/README.md`, `docs/agent-project-reference.md`,
`docs/schema-save-migration.md` and `docs/native-migration.md`. Root README, AGENTS,
native/Web README and the active reader reference now point there. Python-specific
module descriptions/install commands were replaced; existing Schema, i18n, binary,
template and deploy semantics remain available. Old Apply is explicitly distinguished
from supported publication recovery. Origin-bound drafts, unknown journals and old
same-name `ct` commands are described.

The packaged macOS ct actually accepted top-level/export/validate/status/gen-template/
deploy/panel/i18n sync/status/compact help commands. Build, fixture, Web/Flutter and
independent reader commands were previously executed in [G3](macos-g3-verification.md).
Documentation changes do not rerun all performance samples.

The user required actual Unity integration before deletion. That additional gate
now passed in the running game Editor, including the real native gd/xlua plugin,
42 configuration tests, 2 Play Mode Lua tests and 4,608 field comparisons. See
[Unity evidence](unity-integration-verification.md). The inventory still describes
the planned deletion scope; removal is separately verified after execution.

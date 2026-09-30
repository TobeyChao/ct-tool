# Python retirement inventory and active documentation (2026-09-30)

[The inventory](python-retirement-inventory.json) contains 313 classified entries:
262 removals, 33 retained current entries, and 18 retained historical paths.
It expands the initial reference scan to every one of the 249 versioned files in
`ct/`, all native Python fixture/benchmark adapters, both formal test-proj preparation
scripts, their historical counterparts, the archived OpenSpec baseline capture script,
and the active CI/tool/document references.

Each entry records its owner, source checksum, disposition, concrete replacement,
historical snapshot where needed, and reason. All replacement/archive paths were
checked. The 85-file/690-function test reference inventory is preserved, and source
checksums match it. Static Web files map to their migrated locations and all old
documents/assets have a historical snapshot under `docs/archive/python-era/`.
Python generator snapshots and independent fixture manifests remain immutable.

This inventory is the concrete deletion scope, not evidence that deletion has happened
(execution is separately verified in
[python-retirement-verification.md](python-retirement-verification.md)).
Ignored/untracked caches, virtual environments, unrelated experiments and real `gd/`
are not part of the removal list. Two formal test-proj scripts are removed; the
18 audited historical paths remain non-active and retain their recorded source hashes.
Explicit live-Python benchmark options were listed for removal alongside the
old business/install/pytest workflow. The obsolete isolation script that defaults to
Windows and real `gd/` is superseded by temporary-workspace runtime-check acceptance.

Commands actually run:

```sh
node native/tools/check-retirement.mjs
node native/tools/check-docs.mjs
```

The first check verified all 313 classifications, all replacement/archive paths,
262 pre-removal source checksums and all frozen historical test checksums. Its
`--after-deletion` mode requires removed paths absent and rejects newly introduced
unclassified Python code. The inventory's SHA-256 guard rejects malformed edits
before checking scope. The second check verified twelve active documents, all 37 local
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
[Unity evidence](unity-integration-verification.md). The inventory describes the
classified deletion scope; removal is separately verified after execution, and the
addendum below records the post-deletion scope extension.

## Addendum: repository-wide scan scope (post-deletion)

Deletion was executed and separately verified in
[python-retirement-verification.md](python-retirement-verification.md). A follow-up
repository-wide audit found that the scan in `check-retirement.mjs` stopped at `ct`,
`native` and `test-proj`, so the archived OpenSpec baseline capture script
`openspec/changes/archive/2026-09-13-restructure-ct-application-pipeline/baseline/capture.py`
was executable Python that no inventory entry covered. It is now classified as
`retain-historical` (313 entries, 18 retained historical paths) and its archived
JSON snapshots stay frozen; the current six-scenario CLI comparison is the successor
anchor.

The scan now covers every versioned top-level scope (`ct`, `native`, `test-proj`,
`openspec`, `docs`, `web`, `launcher`, `.github`), so a new or changed unclassified
`.py` anywhere in those trees fails the check instead of joining CI silently.
This addendum changed classification and documentation only: no fixture, golden,
oracle or expected value was regenerated.

The leftover local `ct/` checkout (venv, PyInstaller build, release dist) was then
deleted from the developer machine, which made the root `.gitignore` `/ct/` entry and
`native/.gitignore`'s bytecode rules dead; both were dropped. Restored `ct/` sources
still fail this check, so removal of the ignore entry did not remove the guard.
`.gitattributes` now declares `*.py -text diff=python`: the 18 frozen Python oracles
keep their recorded raw-byte checksums on any checkout while still diffing as Python.

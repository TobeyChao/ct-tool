# Python retirement completed — 2026-09-30

G1, G2, G3 and the user's additional actual Unity gate passed before deletion.
The retirement checkpoint is `fea11c4`; all 262 classified versioned paths were
removed, including all 249 files of the old ct project. [The exact list](retired-files.json)
and [guarded inventory](python-retirement-inventory.json) remain. No cache directory,
venv, untracked local material or user gd output was deleted. The retired local ct
directory was ignored at retirement time to prevent accidental staging of its
remaining caches/builds; it was deleted afterwards together with that ignore entry,
and restored `ct/` sources are still rejected by `check-retirement.mjs`.
Eighteen audited historical paths remain non-active: the seventeen test-proj
experiments plus the archived OpenSpec baseline capture script, which a later
repository-wide audit added to the inventory when the scan scope was widened beyond
`ct`/`native`/`test-proj` (see the addendum in
[retirement-inventory-verification.md](retirement-inventory-verification.md)). No
formal runtime, build, test or fixture entry executes Python. Archived sources/oracles
are still checked, rather than treating the missing old implementation as a test skip.

The clean Git checkout at `49ef3f1c22ec5af8fcec146e3a0856d46df4f960` excluded gd and
contained no old ct project, virtual environment, node_modules or build outputs.
Cargo/SDK/dependency caches were reused only to avoid reinstalling toolchains; fixture,
reader and release outputs were newly generated. The PATH allowlist contained no
python/python3/py; Python environment variables were removed. The host's Node upgraded
from 26.8.2 to 26.10.0 during this work, so the old allowlist symlink was replaced
in a new owned tool directory before continuing. No failed step was counted as passed.

| Post-deletion check | Actual result |
|---|---|
| Cargo workspace, offline, locked | 334 passed, 0 failed/ignored |
| HTTP | 39 passed, 0 skipped |
| Browser | 115 passed |
| Flutter lifecycle / analysis | 15 passed / no issues |
| Independent C# reader | 127 values, 0 mismatches |
| Old Web coverage mapping | 146/146, 0 pending |
| Frozen CLI / artifacts | all six scenarios matched |
| Excel boundary inputs | 129 frozen files verified, six workbooks regenerated |
| Benchmark regeneration | S rebuilt from empty and validated |
| S archived performance regression | all five scenarios regression-pass |
| New native release / ZIP | package self-check, actual unzip and runtime check passed |
| New signed macOS app / read-only DMG | payload and actual embedded-runtime checks passed |

The runtime checks run CLI, worker, native panel, embedded resources, health/real API
and safe stdin EOF against temporary workspaces. ZIP executable permissions were
validated by actually running its unpacked binary. The binary is 8,018,960 bytes,
SHA-256 `42907c89d6e0963e88d2c3d047fcc9c29d656f9def60b9793a793bb64ea6783c`;
the new package manifest records a clean checkout (dirtyPaths 0).
The default-port Rust case cannot bind 8000 while the user's preview service is
running; default startup was exercised in the previous G3 run and the preview still
serves 8000. This limitation is unrelated to Python absence and no other case was
removed. Release checks use assigned free ports.

The clean-checkout fingerprint exposed Finder `.DS_Store` in the old local source
inventory, then Git's explicit CRLF checkout of platform scripts differing from the
local LF file. Finder metadata is excluded, and only ps1/bat/cmd line endings are
canonicalized for source fingerprints. Two regression tests cover these cases;
frozen fixture/oracle bytes and their independent checksum guards remain exact.
The final clean fingerprint check passed. The first ZIP harness assumed an outer
directory, while the archive intentionally puts bin/ct at its root; the corrected
actual extraction path passed. Initial failures and final results are retained.

Backup/rollback used the new packaged binary and the previously accepted G3 native
binary (`47c306b913dc642185534426c8cc39de52ea2bed32553070c12ab203391c92fe`).
Both development packages identify as 0.0.0, so their revision and binary SHA identify
the two tested builds. Five directories were relocated to custom names with spaces.
All 100 workspace files, including Excel/manifests, translations, artifacts, ledger,
private state and unrelated notes, were copied and restored with byte/mtime checks.
A real translation upgrade changed the binary; restore removed the new file, the
previous native revision's status preserved the workspace, and its export reproduced
the original artifacts. Unknown Apply recovery and template mutation both refused,
preserving every file. This is not a promise of arbitrary future-format downgrade.

Five capabilities were synchronized to main specs, preserving unrelated scenarios;
native-web-runtime is new. Superseded old launcher/Python-directory deltas were moved
to handoff-history and the old standalone runtime clause now follows macOS/panel
scope. Other changes' unfinished tasks and unverified capabilities were not promoted.
All five affected specs and this change pass strict validation. Global normal
validation passes 22/22; global strict retains pre-existing wording warnings in
i18n-pipeline and json-single-line-records. It is not reported as a global strict pass.

Raw execution records, exact commands, environment, package manifests, runtime checks,
repaired harness failures, release build, performance and rollback data are in
[post-retirement/](post-retirement/). The previous S/M/L five-sample evidence and
[actual Unity evidence](unity-integration-verification.md) remain valid; no generator
behavior changed during final retirement. Remote CI, Windows, Linux and standalone
Unity Player/IL2CPP were not executed: Windows is deferred, Linux unsupported, and
the Unity acceptance is real Editor/EditMode/PlayMode with gd/xlua.

The change is **45/45 complete** and remains unarchived. The user preview service
continues at its original address. Real gd changes from the user's tryout remain
uncommitted and excluded from all migration commits.

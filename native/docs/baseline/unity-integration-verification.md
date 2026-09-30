# Actual Unity game integration — 2026-09-30

The user explicitly required Unity integration before Python removal. This gate
passed in fabulous-game/Client's running Unity 6000.5.2f1 Editor on macOS arm64,
using Unity CLI 1.0.0-beta.10 and Pipeline 0.7.0-exp.1. No second Editor, licensing
process termination, Python export, Assets overwrite or game source change was used.

The game's config/Excel/i18n inputs were copied to a system temporary directory;
deploy was disabled in that copy. The packaged native ct exported 14 tables and
91 files successfully. Its 15 C# files matched the currently compiled game Gen
sources; 3 binary, 42 JSON and 15 Lua files matched the existing deployed game
artifacts byte for byte. This establishes that existing suites read the same bytes
and generated Accessors as the new native export. The explicit memory probe also
loaded the newly generated temporary binaries directly, without deploying them.

The [probe](../../../../test-proj/UnityIntegration/VerifyNative.cs) executed through
the actual gd/xlua plugin: 14 tables, 7,956 checks, 4,608 scalar field comparisons
across zh/en/ja/zh, vectors/records, ByID/ByIndex/CodeName, stable main pointer and
generation during language switches, held rows observing the new language, missing
language fallback, and stale rows rejected after full reload. The 356 server-only
observations are the two explicitly excluded fields, not skipped client checks.

Unity Test Runner independently passed **42/42 EditMode ConfigTableTests** and
**2/2 PlayMode LuaConfigAccessorTests**, with zero failures/skips/inconclusives.
The Lua suite initializes the real LuaManager and runs ConfigTest.lua assertions,
then verifies Japanese and primary-language fallback. These are actual Editor and
Play Mode results; they do not claim standalone Player, IL2CPP, Windows or Linux
validation. Windows remains deferred and Linux unsupported.

The first probe rejected Text.Note because the probe initially allowed only
Item.IsActive as server_only. The copied schema confirmed both exclusions; the
corrected probe passed. The first Lua filter in EditMode returned zero results,
which was not counted as a pass. The proper Play Mode suite ran both tests.
Initial failed/zero executions are retained alongside the final results.

All 115 monitored real-game config source/deployed/input files retained their
original SHA-256, size and mtime. The initially unloaded GDNative state, language
zh and idle non-compiling Editor were restored. Lua tests preserve PlayerPrefs;
the copied probe outside Assets was removed. Unrelated game modifications and
the user's current ct-tool/gd outputs were not changed by this acceptance.

Raw evidence in [unity-integration/](unity-integration/): native-export.txt,
accessor-compare.json, game-artifact-compare.json, native-reader.json,
config-tests.json, lua-playmode-tests.json, source-before.json,
source-preservation.json, state-before.json, state-after.json and console-after.json.
Reproduction instructions are in
[UnityIntegration](../../../../test-proj/UnityIntegration/README.md).

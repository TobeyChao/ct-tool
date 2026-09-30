# Actual Unity integration

`VerifyNative.cs` runs in memory inside the real fabulous-game Editor through
Unity CLI's `run_script`. It reads new native-generated binaries through the game's
compiled Accessors and gd/xlua plugin, comparing all client field values with JSON.
It refuses Play Mode, compilation or an already loaded configuration, and unloads
its configuration in `finally`. The current 14-table fixture has two server-only
fields (Item.IsActive and Text.Note), explicitly excluded from client getters.

Copy only `Config/gd/{config,excel,i18n}` into a temporary workspace. Disable deploy
in that copy and export with the native ct. Before using the game's compiled
Accessors, compare all 15 generated C# files byte for byte against
`Client/Assets/Scripts/Config/Gen`. Compare the 3 binaries, 42 JSON files and 15 Lua
files to the deployed game artifacts before treating existing tests as evidence
for native output. Refuse differences; do not overwrite the game's Assets.

Place a copy of this probe at `Client/Temp/CtNativeUnityVerification.cs`, outside
Assets. With the existing idle Editor and its Unity Pipeline running:

```sh
unity command run_script --file Temp/CtNativeUnityVerification.cs \
  --entry CtNativeUnityVerification.Run --args '["/absolute/temp/workspace/output"]' --json
unity command run_tests --mode editor --filter ConfigTableTests --async_tests true --json
unity command test_status --json
unity command run_tests --mode playmode \
  --filter GameFramework.Tests.LuaConfigAccessorTests --async_tests true --json
unity command test_status --json
```

Run these sequentially, waiting for each test run to complete. Inspect the nested
`run_script` result's success as well as the CLI envelope, and require 42/42 and
2/2 tests; a zero-result filter is a failure to execute, not a pass. LuaTests is
a Play Mode assembly. Both suites use the existing game binaries only after their
SHA-256 equality with the new native artifacts has been established.

Restore the initially unloaded GDNative state after the suites using
`GDNative.Unload(); TableVersion.MarkFullReload();`, preserve language preferences,
remove only the copied Temp probe, and compare original files' SHA/mtime snapshots.
Do not run this cleanup if the initial game configuration was loaded: the initial
probe guard requires an unloaded Editor. These are environment-dependent game
acceptance checks, not silently skipped CI tests.

Actual macOS execution and its limits are recorded in
[Unity evidence](../../native/docs/baseline/unity-integration-verification.md).

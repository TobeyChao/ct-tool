# Diagnostics surfaced by the orchestration harness

These lines are transcribed from tool output, not presented as original per-step
log files. The original runner and both failed fingerprint outputs are also retained.

- The host upgraded Node and removed the pinned old installation. The first Node
  spawn reported `Error: spawn node ENOENT`; the old allowlist pointed to
  `/opt/homebrew/Cellar/node/26.8.2/bin/node`. A new owned allowlist uses the actual
  Node 26.10.0 executable, still excluding Python. Passed Cargo steps were retained.
- The first attempt to resume the harness reported `EEXIST: file already exists,
  mkdir .../ct-post-retirement-XMFBrJ/logs`. Resume now creates that directory with
  recursive mode. No acceptance step was skipped because of this harness error.
- First fingerprint differences: launcher 81/80 files, caused by `.DS_Store`.
  Second differences: launcher 80/80 files but 677508/677597 bytes, caused by Git's
  CRLF checkout for build_windows.ps1. Metadata exclusion and platform-script newline
  normalization have distinct regression tests; final clean checking passed.
- The initial extraction smoke assumed a package-name directory within the ZIP.
  Runtime checking reported `Error: 原生二进制不存在` / `No such file or directory`.
  Listing the actual archive established `unpacked/bin/ct`; executing that file,
  the app runtime and the read-only mounted DMG runtime all passed.
- The first automated main-spec merge extracted an empty native-web-runtime Purpose.
  Validation rejected it. Its exact nonempty delta Purpose was then copied and all
  five changed specs validated strictly. Global strict also surfaces pre-existing
  warnings in two unrelated historical specs; those are reported separately.

Original successful subprocess logs remain verbatim, including terminal whitespace.

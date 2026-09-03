# Schema Workbench v4 repository-cutover baseline

This fixture freezes the last supported pre-v4 workspace before the canonical
Type Expression cutover. It contains the repository's four Schema files, four
Excel workbooks, translation inputs and the complete JSON, FBS, Binary and
C#/Lua output tree produced by a clean full export.

`baseline.json` records the source commands and content fingerprints. The
integration test copies only the source inputs to a temporary workspace, runs a
clean full export and compares every generated path and byte with this golden.
Do not refresh this baseline after converting the repository to the v4 format;
it is the evidence used for the cutover parity check.

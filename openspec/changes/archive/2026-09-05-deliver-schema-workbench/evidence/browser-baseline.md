# Browser and packaged-launcher baseline

Recorded on 2026-09-02 before the  production entry was enabled.

## Local Web Panel

- Runner: Python Playwright 1.62.0 with bundled Chromium, loading the local Flask
  panel and its vendored Vue runtime directly; no npm or frontend build step.
- Workspace: `ct/tests/fixtures/repository_cutover/workspace` inputs copied to
  an isolated temporary directory.
- Matrix: 1600×900, 1360×768, 1280×720, 960×640, 720×460 and 390×844 at
  100%, 125% and 150% simulated browser zoom (18 captures).
- Result: 18/18 loaded the Schema read-only entry without console errors or old
  direct-write controls.
- Full local captures: `test-artifacts/web-baseline/` (ignored generated
  output); CI uploads the same directory as the `web-baseline` artifact.
- Retained representatives:
  - `panel-pre-720x460-z100.png`
  - `panel-pre-390x844-z150.png`

These are intentionally pre defect/reference captures, not approval goldens
for the final workbench. The matrix manifest at
`ct/tests/fixtures/web/schema_workbench_matrix.json` remains the executable
fixture for later  screenshots and layout assertions.

## Final  workbench qualification

Re-run on 2026-09-03 after the production workbench redesign. The executable
matrix produced 18/18 passing captures across all six physical viewports and
100%, 125% and 150% zoom. Each case opens a Schema resource and asserts the
expected projection, bounded activity rail, absence of global horizontal
scroll, and a stable inspector restore control. Manual inspection of the wide,
medium, compact and phone representatives found no residual pane strip, header
drift, covered field action or mixed-resource state.

The packaged macOS launcher smoke below remains applicable: the launcher owns
the tested 720×460 native window while the panel is served from the selected ct
runtime. The Web matrix separately exercises the current static assets at that
same logical size.

## Packaged macOS launcher

- Package: `launcher/build/macos/Build/Products/Release/ct_launcher.app`
- Signature verification: `codesign --verify --deep --strict` passed.
- Runtime: the package contains `Contents/Resources/runtime/ct`.
- CoreGraphics logical bounds: exactly 720×460.
- Result: the Release launcher opened successfully and rendered its Overview
  page without clipping; the smoke process was stopped after capture.
- Evidence: `launcher-macos-720x460.png` (Retina screenshot includes the native
  window shadow, so the PNG pixel bounds are larger than the logical content
  bounds).

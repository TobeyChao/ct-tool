# Desktop workbench information architecture and layout research

Research date: 2026-09-22. Sources are limited to first-party Material 3, Flutter, Microsoft Fluent/Windows, VS Code, and Apple documentation.

## Recommended shell for ct launcher

```text
┌ title / workspace / global commands ───────────────────────────────┐
│ rail │ optional local nav │ primary work area │ optional inspector │
│      │                    │                   │                    │
│      ├────────────────────┴───────────────────┴────────────────────┤
│      │ collapsible Tasks / Problems / Output panel                │
├──────┴─────────────────────────────────────────────────────────────┤
│ workspace • worker • validation • background task • context       │
└────────────────────────────────────────────────────────────────────┘
```

- Keep the leading rail stable and reserve it for top-level work modes: Overview, Schema, Export, Localization, History, with Settings pinned at the bottom. Material recommends a consistent rail position and 3–7 destinations; Windows recommends left navigation for roughly 5–10 top-level categories. [[M3 navigation rail](https://m3.material.io/components/navigation-rail/overview)] [[Windows NavigationView](https://learn.microsoft.com/en-us/windows/apps/develop/ui/controls/navigationview)]
- Put resource lists and step navigation in a route-local sidebar, not in the global rail. Put commands such as validate, generate template, export, and deploy in the page header or contextual toolbar. This keeps navigation (where am I?) separate from actions (what can I do?).
- Give the primary work area a consistent hierarchy: compact page header (title, scope, state, primary action), optional summary/guard strip, then the editor/table/diff. Use an optional right inspector for selected-item details, candidate differences, or validation context.
- Use the bottom panel for durable task evidence—Problems, Tasks, Output, and logs—rather than mixing long logs into the main page. VS Code uses a bottom panel for Problems, Terminal, and Output, while allowing panels and views to be moved and remembered. [[VS Code custom layout](https://code.visualstudio.com/docs/configure/custom-layout)]
- Keep a thin status bar for workspace-wide and contextual state, not prose. VS Code places global status on the left and secondary/contextual state on the right. [[VS Code status bar](https://code.visualstudio.com/api/ux-guidelines/status-bar)]

## Findings by design concern

### Navigation and hierarchy

- Material 3 positions navigation rails at medium and larger window sizes, supports 3–7 destinations, and allows collapsed and expanded variants to transition into each other. The active destination should remain unmistakable. [[M3 navigation rail](https://m3.material.io/components/navigation-rail/overview)]
- Windows NavigationView adapts from minimal to compact to expanded left navigation as the window grows. This is a useful model for ct: preserve the same destinations and selection while changing only presentation. [[Windows NavigationView](https://learn.microsoft.com/en-us/windows/apps/develop/ui/controls/navigationview)]
- A second simultaneously visible sidebar is justified only when it carries a different level of hierarchy or context. VS Code uses a Primary Side Bar for navigation/views and an opposite Secondary Side Bar for a second concurrent view. [[VS Code custom layout](https://code.visualstudio.com/docs/configure/custom-layout)]
- Persistently highlight the selected item in every pane that leads to the detail view; Apple notes that this clarifies pane relationships and maintains orientation. [[Apple split views](https://developer.apple.com/design/human-interface-guidelines/split-views)]

### Compact density and target sizes

- Start from Fluent's 4 px spacing rhythm. For ct, a practical compact scale is 4 px within a control, 8 px between related controls, 12–16 px between groups, and 24 px between major sections. Whitespace should communicate grouping; density should not erase hierarchy. [[Fluent 2 layout](https://fluent2.microsoft.design/layout)]
- Offer Default and Compact density as coherent modes, not one-off squeezed widgets. VS Code's Compact mode removes inter-panel spacing and reduces spacing inside panels, and persists the choice. [[VS Code custom layout](https://code.visualstudio.com/docs/configure/custom-layout)]
- Keep icon-only and small controls visually compact while preserving their hit area. Material recommends a 48 × 48 dp target even when the icon is 24 dp; Windows defines a touchable minimum of 40 × 40 epx, or 32 epx high only when at least 120 epx wide. [[M3 target sizes](https://m3.material.io/foundations/designing/structure)] [[Windows touch interactions](https://learn.microsoft.com/en-us/windows/apps/develop/input/touch-interactions)]
- A sound desktop default is a 40 px visible height for primary buttons (matching M3's default 40 dp button), 40 px hit boxes for icon actions, and the 32 px exception only for wide, text-labeled, mouse-first controls. Do not make dense table rows the only click target for destructive or primary actions. [[M3 buttons](https://m3.material.io/components/buttons/overview)]

### Panels and resizing

- Let users resize local navigation, inspector, and bottom panel with visible hover affordance; persist sizes and open/closed state per workspace. VS Code permits panel placement on any edge, drag-and-drop between regions, and session persistence. [[VS Code custom layout](https://code.visualstudio.com/docs/configure/custom-layout)]
- Define useful default, minimum, and maximum sizes so a pane cannot crush the work area or hide its divider. Apple explicitly recommends min/max pane sizes, optional pane hiding, and more than one way to restore a hidden pane (toolbar/menu/shortcut). [[Apple split views](https://developer.apple.com/design/human-interface-guidelines/split-views)]
- Prefer a visually thin divider with a larger invisible pointer hit region. Double-click reset and keyboard commands are useful desktop affordances; the toolbar must also expose panel visibility so discoverability does not depend on dragging.
- At constrained widths, collapse in this order: inspector, route-local sidebar, expanded rail labels. Preserve the main task and selection; never solve width pressure by uniformly shrinking text and targets.

### Status and progress

- Use three levels of feedback:
  1. Inline beside the initiating control for immediate validation and short operations.
  2. Status bar plus expandable Tasks/Output panel for background export, generation, or deployment.
  3. Notification/dialog only for completion that needs attention, failure, conflict, or a decision.
- VS Code recommends a status-bar loading item for discreet background progress and a progress notification when attention must be elevated. Keep labels short and avoid turning the status bar into a row of badges. [[VS Code status bar](https://code.visualstudio.com/api/ux-guidelines/status-bar)]
- Show determinate progress when completion can be measured and indeterminate progress when it cannot. Windows also distinguishes non-blocking progress bars from a blocking indeterminate ring; ct's long jobs should normally remain non-blocking and expose Cancel when cancellation is safe. [[Windows progress controls](https://learn.microsoft.com/en-us/windows/apps/develop/ui/controls/progress-controls)]
- Keep final success/error evidence in Tasks/Output after animation ends. Never rely on a spinner alone to communicate which workspace, phase, or file is active.

### Responsive behavior

- Base layout decisions on the actual window constraints, not OS, device label, or orientation. Flutter specifically recommends `MediaQuery.sizeOf` or `LayoutBuilder`, because apps run in resizable and multi-window contexts. [[Flutter adaptive best practices](https://docs.flutter.dev/ui/adaptive-responsive/best-practices)]
- Material's width breakpoints are a useful starting vocabulary: compact `<600`, medium `600–839`, expanded `840–1199`, large `1200–1599`, and extra-large `1600+` logical pixels. Layouts normally move from one to two to three panes rather than simply stretching. [[M3 breakpoints](https://m3.material.io/foundations/layout/breakpoints)]
- Suggested ct behavior:
  - `<600`: one task pane; modal/minimal navigation; inspector and output become full-width overlays or routes.
  - `600–839`: collapsed rail plus one main pane; show only one auxiliary pane at a time.
  - `840–1199`: rail plus main pane; optional resizable sidebar or inspector; bottom output panel.
  - `1200–1599`: expanded or user-expandable rail; main pane plus persistent inspector where useful.
  - `1600+`: allow three panes, but cap readable/editor widths rather than stretching every control.
- Treat these as behavioral thresholds to tune against ct's minimum usable editor widths, not immutable device classes. Flutter's own adaptive guidance uses `<600` for bottom navigation and `≥600` for a rail as an example, while emphasizing available window size. [[Flutter adaptive approach](https://docs.flutter.dev/ui/adaptive-responsive/general)]

### Motion

- Animate relationships, not decoration: rail expand/collapse, pane reveal, selection continuity, and progress changes. For top-level destination changes, Fluent recommends a quick fade instead of moving a large portion of the UI, which avoids implying false hierarchy or causing disorientation. [[Fluent 2 motion](https://fluent2.microsoft.design/motion)]
- Keep motion local to the changed element and keep durations short enough that repeated developer workflows never wait on animation. Avoid animating entire tables or the whole workbench after every refresh.
- Honor reduced-motion settings. Material recommends subtle fades instead of intense sliding/scaling and disabling decorative parallax or shape morphing; Flutter exposes platform animation preferences through `MediaQuery`/accessibility features. [[M3 transitions](https://m3.material.io/styles/motion/transitions/applying-transitions)] [[Flutter MediaQuery](https://api.flutter.dev/flutter/widgets/MediaQuery-class.html)]
- Progress motion must not be the only signal: pair it with text/state, preserve the completed result, and avoid perpetual activity when the worker is idle.

## Implementation priorities

1. Establish the stable shell and clear top-level navigation before visual polish.
2. Add resizable/persisted auxiliary panes and a durable Tasks/Output surface.
3. Normalize a 4 px spacing scale, 40 px desktop action targets, and Default/Compact density modes.
4. Implement width-driven pane collapse with golden tests at each behavioral threshold and at 100%, 125%, and 150% scaling.
5. Add purposeful transitions and reduced-motion behavior last; motion should explain state changes, not mask layout instability.

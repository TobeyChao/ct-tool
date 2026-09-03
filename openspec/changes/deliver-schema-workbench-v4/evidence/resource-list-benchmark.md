# Resource discovery benchmark

Measured on 2026-09-03 with Playwright Chromium 151 at a 1600×900 viewport. The
test intercepts only the workspace snapshot so server-side YAML parsing is not
mistaken for resource-list rendering cost. Both the resource tree and Quick
Open use the same `fixedRowWindow` calculation with a 34 px row and 8-row
overscan.

| Resources | First paint | Exact query | DOM nodes | Visible resource rows | JS heap* |
|---:|---:|---:|---:|---:|---:|
| 100 | 219.4 ms | 12.9 ms | 204 | 29 | 10.0 MB |
| 1,000 | 185.2 ms | 9.3 ms | 204 | 29 | 10.0 MB |
| 10,000 | 208.1 ms | 13.1 ms | 204 | 29 | 10.0 MB |

Acceptance budgets are 5 s first paint, 2 s query response, fewer than 100
rendered resource rows and fewer than 8,000 total DOM nodes. Deep scrolling is
also checked to reach the final stable-key row. Quick Open searches the entire
set while retaining a bounded DOM window.

\* Chromium exposes a coarse `performance.memory` value in this headless test;
DOM-node constancy is the more useful regression signal here.

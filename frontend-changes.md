# Frontend Changes: Visible Header

## Summary

The app previously had no visible header (`header { display: none; }` in CSS) and the theme-toggle button floated as a `position: fixed` overlay in the top-right corner of the viewport. Replaced this with a real, visible header bar containing the app title/subtitle on the left and the theme toggle on the right.

## Files changed

- `frontend/index.html`
- `frontend/style.css`

## Details

### 1. Header markup (`index.html`)

- Wrapped the existing `<h1>Course Materials Assistant</h1>` and `<p class="subtitle">` in a new `.header-text` div inside `<header class="app-header">`.
- Moved `#themeToggle` (previously a sibling of `.container`, fixed-positioned) into the header, after `.header-text`, so it now sits inline on the right side of the header row. No changes to the button's markup, `aria-*` attributes, or icons — and no changes to `script.js`, since it looks the button up by ID regardless of its position in the DOM.

### 2. Header styling (`style.css`)

- Removed `header { display: none; }`. `header` is now a flex row (`justify-content: space-between; align-items: center;`) with `background: var(--surface)` and `border-bottom: 1px solid var(--border-color)` — the same surface/border pairing already used by the sidebar, so it matches the existing design system.
- Added `.header-text { display: flex; flex-direction: column; text-align: left; }` to group the title/subtitle on the left side of the row.
- `header h1` keeps its pre-existing gradient text treatment (`linear-gradient(135deg, #667eea 0%, #764ba2 100%)` clipped to text) and larger font size (1.75rem) relative to `.subtitle` (0.95rem) — this styling already existed but was dormant while the header was hidden.
- `.theme-toggle` no longer uses `position: fixed`/`top`/`right`/`z-index`; it now lays out as a normal flex child at the end of the header row (`flex-shrink: 0` keeps it from being squeezed on narrow screens). All other button styling (circular shape, colors, hover/active/focus-visible states, sun/moon icon cross-fade) is unchanged.
- Updated the `@media (max-width: 768px)` rule for `.theme-toggle` to drop the now-meaningless `top`/`right` overrides, keeping only the smaller 38px size.

## Verification

Verified in-browser with Playwright MCP against the running dev server (`http://localhost:8000`):
- Header renders with the gradient title left-aligned, subtitle beneath it, and the toggle button on the right — in both dark and light themes.
- Clicking and keyboard-activating (Enter and Space, after Tab-focusing) the toggle both correctly flip `data-theme` and update the button's `aria-label`.
- Resized to a 375px-wide mobile viewport: header wraps the title across two lines without overlapping the toggle button or overflowing.

# Frontend Changes: Dark/Light Theme Toggle

## Summary

Added a light theme variant and a top-right toggle button that switches between it and the existing dark theme, with the preference persisted across page loads.

## Files changed

- `frontend/index.html`
- `frontend/style.css`
- `frontend/script.js`

## Details

### 1. Theme toggle button (`index.html`)

- Added a circular icon button (`#themeToggle`) fixed to the top-right of the viewport, containing a sun icon and a moon icon (both inline SVGs, feather-icon style to match the existing send button).
- `aria-label`, `aria-pressed`, and `title` attributes are kept in sync with the active theme for screen readers. It's a native `<button>`, so it's reachable and activatable via keyboard (Tab, Enter/Space) with no extra wiring.
- Added a small inline `<script>` in `<head>` that reads the saved theme from `localStorage` and sets `data-theme` on `<html>` before the page paints, avoiding a flash of the wrong theme on load.

### 2. Light theme variant + toggle styling (`style.css`)

- Added a `:root[data-theme="light"]` block that overrides every themed CSS variable used by the dark `:root` block:
  - **Backgrounds/surfaces**: `--background: #f8fafc`, `--surface: #ffffff`, `--surface-hover: #e2e8f0`.
  - **Text**: `--text-primary: #0f172a` (near-black on light surfaces), `--text-secondary: #475569` — both comfortably exceed WCAG AA contrast (>7:1) against the light backgrounds.
  - **Borders**: `--border-color: #cbd5e1`.
  - **Primary/accent**: `--primary-color: #1d4ed8` / `--primary-hover: #1e40af` — darkened relative to the dark theme's `#2563eb` so white button text stays above 4.5:1 contrast on a light background; `--user-message` follows the same color.
  - **Status colors**: added new `--error-color` / `--success-color` variables (`#b91c1c` / `#15803d` for light, `#f87171` / `#4ade80` for dark) so error/success banner text keeps sufficient contrast against their tinted backgrounds in both themes. `.error-message` and `.success-message` now read these variables instead of hardcoded colors.
  - **Shadow/focus ring/welcome banner**: adjusted (`--shadow`, `--focus-ring`, `--welcome-bg`, `--welcome-border`) to suit a light background.
- Since the rest of the stylesheet already styled everything through these CSS variables, the whole app (sidebar, chat bubbles, inputs, scrollbars, markdown content, sources panel) re-themes automatically — no other selectors needed changes.
- Fixed a pre-existing bug where `.message-content blockquote` referenced the undefined `var(--primary)`; changed to `var(--primary-color)`.
- Added `.theme-toggle` and related `.theme-icon*` rules: circular button matching the app's existing bordered/rounded button aesthetic, hover/active/focus-visible states consistent with `#sendButton`/`.suggested-item`, and a 0.4s rotate+fade cross-transition between the sun and moon icons driven purely by CSS (`:root[data-theme="light"] .theme-icon-*`).
- Added a `background-color`/`color` transition on `body` (0.3s) so switching themes animates smoothly instead of snapping.
- Added a small `@media (max-width: 768px)` rule to shrink the toggle button on narrow viewports.

### 3. Toggle logic (`script.js`)

- Added `themeToggle` to the cached DOM elements and wired a `click` listener to `toggleTheme()`.
- `initializeTheme()` reads the `data-theme` already set by the inline head script and syncs the button's `aria-pressed`/`aria-label`.
- `toggleTheme()` flips between `light`/`dark`, applies it via `applyTheme()`, and persists the choice to `localStorage` (wrapped in try/catch in case storage is unavailable).
- `applyTheme(theme)` sets `data-theme` on `<html>` and updates the button's accessibility attributes.

## Accessibility notes

- All text/background pairings in the light theme were checked to stay at or above WCAG AA contrast (4.5:1 for normal text), including the previously-too-light error/success message colors.
- Toggle button has visible focus styling (`:focus-visible` box-shadow ring matching the rest of the UI) and descriptive `aria-label` that updates with state.

### 4. App-wide smooth theme transitions (`style.css`)

- The initial pass only animated `body`'s `background-color`/`color`, so other panels (sidebar, chat bubbles, inputs, cards, borders) would snap instantly when the theme changed. Replaced that with a universal rule right after the CSS reset:
  ```css
  *, *::before, *::after {
      transition-property: background-color, border-color, color, box-shadow, fill, stroke;
      transition-duration: 0.3s;
      transition-timing-function: ease;
  }
  ```
  This makes every element that reads a themed CSS variable (background, border, text color, etc.) cross-fade together over 0.3s when `data-theme` flips, without needing to enumerate each selector individually.
- Elements that already declared their own `transition` (e.g. `#sendButton`, `#chatInput`, `.suggested-item`, `.source-link`, `.theme-toggle`, `.theme-icon-*`) keep their existing timing/property list — a class/ID selector's specificity beats the universal selector, so their hover/focus/icon-swap animations are unaffected.
- Removed the now-redundant explicit transition declaration on `body` since it's covered by the universal rule.

### 5. CSS variables + `data-theme` audit (`style.css`)

Confirmed/finished the implementation approach explicitly:

- Theming is driven entirely by CSS custom properties scoped to `:root` (dark, default) and `:root[data-theme="light"]` (light override) — no duplicated component rules per theme; every component reads `var(--...)`.
- `data-theme` is set on the `<html>` element (`document.documentElement`), both by the pre-paint inline script in `index.html` and by `applyTheme()` in `script.js`.
- Audited every hardcoded (non-variable) color in the stylesheet to confirm it still reads correctly in both themes:
  - `rgba(0, 0, 0, 0.2)` overlays (code/pre blocks, welcome-message shadow) are relative darkening effects that work against either a dark or light surface, so they were left as-is.
  - Error/success message tint backgrounds keep their fixed low-alpha red/green regardless of theme, while their text now reads `var(--error-color)`/`var(--success-color)` (see previous section) for contrast.
  - Found and fixed one inconsistency: `#sendButton:hover`'s glow shadow was hardcoded to the old dark-theme primary blue (`rgba(37, 99, 235, 0.3)`), which no longer matched the light theme's darker primary (`#1d4ed8`). Added a `--primary-glow` variable (per-theme, matching each theme's `--primary-color`) and switched the hover rule to `box-shadow: 0 4px 12px var(--primary-glow);` so the glow color always tracks the active theme's primary.
- Visual hierarchy is preserved in both themes: nested/recessed surfaces (`.stat-item`, `.suggested-item`, `.source-link`) intentionally use `var(--background)` while their containers use `var(--surface)`, keeping the same "card sits on a slightly different plane than its container" relationship in both light and dark palettes.

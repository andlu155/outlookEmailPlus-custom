# UI Style Switcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve the classic UI as the default and expose the new dashboard UI as a persistent user-selectable style.

**Architecture:** The original stylesheet remains the default cascade. The dashboard additions are gated by an HTML data attribute that a small extension to the existing theme initialization controls. Docker Compose points to the GHCR image produced by this repository's workflow.

**Tech Stack:** Flask templates, vanilla JavaScript, CSS, Docker Compose, Jest.

---

### Task 1: Add the style-selection contract

**Files:**
- Create: `tests/browser-extension/ui-style-switcher.test.js`

- [ ] **Step 1: Write the failing static contract tests**

```js
expect(html).toContain('id="uiStyleSelect"');
expect(script).toContain("localStorage.setItem('ol_ui_style', style)");
expect(script).toContain("applyUiStyle(localStorage.getItem('ol_ui_style') || 'classic')");
expect(css).toContain('[data-ui-style="dashboard"]');
expect(compose).toContain('ghcr.io/andlu155/outlook-email-plus:${IMAGE_TAG:-latest}');
```

- [ ] **Step 2: Verify the test fails**

Run: `npx jest --runInBand --config tests/browser-extension/jest.config.js tests/browser-extension/ui-style-switcher.test.js`

Expected: FAIL because the selector, storage key, scoped dashboard rule, and corrected image namespace are absent.

### Task 2: Implement the classic-default style switcher

**Files:**
- Modify: `templates/index.html`
- Modify: `static/js/main.js`
- Modify: `static/css/main.css`

- [ ] **Step 1: Add the sidebar selector**

Insert a `<select id="uiStyleSelect" onchange="applyUiStyle(this.value)">` with `classic` and `dashboard` options before `themeToggleBtn`.

- [ ] **Step 2: Add style persistence**

Add `applyUiStyle(style)` beside `applyTheme(theme)`. It normalizes to `classic` or `dashboard`, sets `document.documentElement.dataset.uiStyle`, stores `ol_ui_style`, and synchronizes the selector. Initialize with `localStorage.getItem('ol_ui_style') || 'classic'`.

- [ ] **Step 3: Scope the dashboard override**

Change the dashboard theme block to start with `[data-ui-style="dashboard"]` for its tokens and every dashboard-specific override selector, leaving existing pre-dashboard CSS untouched as the classic baseline.

- [ ] **Step 4: Verify the test passes**

Run the command from Task 1. Expected: PASS.

### Task 3: Correct deployment image source

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Replace the GHCR image namespace**

Set the app image to `ghcr.io/andlu155/outlook-email-plus:${IMAGE_TAG:-latest}`.

- [ ] **Step 2: Validate Compose syntax**

Run: `docker compose config`

Expected: exit code 0 and the rendered app image includes `ghcr.io/andlu155/outlook-email-plus`.

### Task 4: Regression verification

**Files:**
- Modify: `tests/browser-extension/ui-style-switcher.test.js`

- [ ] **Step 1: Run the complete JavaScript suite**

Run: `npm test`

Expected: all browser-extension suites pass.

- [ ] **Step 2: Inspect the final diff**

Run: `git diff --check`

Expected: no whitespace errors.

# CF Worker Error Guidance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Cloudflare temporary-mail failures actionable without exposing credentials, and give the temporary-mail settings tab its own save action.

**Architecture:** The CF provider will sanitize only the upstream response body and return it as `error_detail`. The service will attach that field to the existing `TempMailError.data` payload, and the existing error-toast pathway will render targeted CF troubleshooting guidance plus the sanitized detail. The template reuses `saveSettings()` and a small dirty-state helper; no API contract or persistence endpoint changes are needed.

**Tech Stack:** Python 3, Flask, `unittest`, vanilla JavaScript, HTML templates.

---

## File map

- Modify: `outlook_web/services/temp_mail_provider_cf.py` — sanitize CF Worker error body and return `error_detail` for failed mailbox creation.
- Modify: `outlook_web/services/temp_mail_service.py` — propagate sanitized provider details through `TempMailError.data`.
- Modify: `static/js/main.js` — map temporary-mail CF error codes to guidance, render technical detail safely, and track unsaved temporary-mail settings.
- Modify: `templates/index.html` — add the temporary-mail save button and initially hidden dirty hint.
- Modify: `tests/test_temp_mail_provider_cf.py` — provider sanitization and sensitive-data regression coverage.
- Modify: `tests/test_temp_mail_service.py` or the existing temporary-mail API test module — assert `error_detail` reaches the standard error response.
- Modify: `tests/test_settings_tab_refactor_frontend.py` — static contract coverage for the save control and dirty-state wiring.
- Create: `tests/test_cf_worker_error_guidance_frontend.py` — static contract coverage for error-code guidance and safe error-detail rendering.

### Task 1: Provider error-detail contract

**Files:**
- Modify: `tests/test_temp_mail_provider_cf.py`
- Modify: `outlook_web/services/temp_mail_provider_cf.py`

- [ ] **Step 1: Write failing provider tests**

Add tests in `CloudflareTempMailProviderTests` that mock a failed `requests.post` response and assert:

```python
self.assertEqual(result["error_code"], "UPSTREAM_BAD_PAYLOAD")
self.assertEqual(result["error_detail"], "Required field is missing")
self.assertLessEqual(len(result["error_detail"]), 300)
self.assertNotIn("super-secret-admin-pass", repr(result))
self.assertNotIn("x-admin-auth", repr(result).lower())
```

Use a body containing newlines, tabs, a control character, and more than 300 characters. Add a separate `401` case that still returns `UNAUTHORIZED` and the cleaned body.

- [ ] **Step 2: Verify the tests fail before implementation**

Run:

```powershell
python -m unittest tests.test_temp_mail_provider_cf.CloudflareTempMailProviderTests.test_create_mailbox_http_error_returns_sanitized_detail tests.test_temp_mail_provider_cf.CloudflareTempMailProviderTests.test_create_mailbox_http_401_keeps_code_and_detail
```

Expected: FAIL because failed responses do not yet contain `error_detail`.

- [ ] **Step 3: Implement the smallest sanitizer and provider response change**

In `outlook_web/services/temp_mail_provider_cf.py`, add a module helper that converts the body to text, removes C0/DEL control characters except whitespace, collapses whitespace with `" ".join(...)`, and returns at most 300 characters. In the existing non-OK branch of `create_mailbox`, add the value only as:

```python
"error_detail": _sanitize_cf_error_detail(resp.text),
```

Do not include request headers, the request payload, exceptions that contain credentials, or response JSON objects in this field.

- [ ] **Step 4: Verify provider tests pass**

Run the command from Step 2.

Expected: PASS.

- [ ] **Step 5: Commit the provider unit**

```powershell
git add outlook_web/services/temp_mail_provider_cf.py tests/test_temp_mail_provider_cf.py
git commit -m "fix: preserve sanitized CF Worker error details"
```

### Task 2: Standard API error propagation

**Files:**
- Modify: `tests/test_temp_mail_service.py` or the existing temporary-mail API test module containing mailbox creation failures
- Modify: `outlook_web/services/temp_mail_service.py`

- [ ] **Step 1: Write a failing propagation test**

Mock `_create_mailbox` to return:

```python
{
    "success": False,
    "error": "CF Worker 创建邮箱失败 HTTP 400",
    "error_code": "UPSTREAM_BAD_PAYLOAD",
    "error_detail": "Required field is missing",
}
```

Assert the resulting `TempMailError` has `code == "UPSTREAM_BAD_PAYLOAD"`, `status == 502`, and `data == {"error_detail": "Required field is missing"}`. If testing via the HTTP endpoint, also assert the existing trace identifier remains present.

- [ ] **Step 2: Verify the propagation test fails**

Run the single new test with `python -m unittest <module>.<class>.<test_name>`.

Expected: FAIL because `TempMailError.data` is currently unset for this path.

- [ ] **Step 3: Propagate only the optional detail**

In `TempMailService.generate_user_mailbox()`, replace the failure raise with a `data` value that contains `error_detail` only when the provider returned a non-empty string; otherwise retain `None`.

- [ ] **Step 4: Verify propagation passes**

Run the command from Step 2.

Expected: PASS.

- [ ] **Step 5: Commit the service unit**

```powershell
git add outlook_web/services/temp_mail_service.py tests/test_temp_mail_service.py
git commit -m "fix: expose CF Worker failure details to clients"
```

### Task 3: Temporary-mail save affordance and dirty state

**Files:**
- Modify: `tests/test_settings_tab_refactor_frontend.py`
- Modify: `templates/index.html`
- Modify: `static/js/main.js`

- [ ] **Step 1: Write failing frontend contract assertions**

Assert the settings template contains all of:

```text
id="saveTempMailSettingsButton"
onclick="saveSettings()"
id="tempMailSettingsDirtyHint"
```

Assert `static/js/main.js` contains a dirty-state function that toggles the hint and listeners for `tempMailProvider`, `settingsCfWorkerBaseUrl`, `settingsCfWorkerAdminKey`, and `settingsCfWorkerPrefixRules`.

- [ ] **Step 2: Verify the contract fails**

Run:

```powershell
python -m unittest tests.test_settings_tab_refactor_frontend
```

Expected: FAIL because the temporary-mail pane has no dedicated save controls or dirty-state wiring.

- [ ] **Step 3: Add the smallest UI implementation**

At the bottom of `#settings-tab-temp-mail`, after `#pluginManagerCard`, add a hidden hint and button:

```html
<div id="tempMailSettingsDirtyHint" class="form-hint" style="display: none; margin-top: 0.75rem;">修改尚未保存</div>
<button type="button" class="btn btn-primary" id="saveTempMailSettingsButton" onclick="saveSettings()">💾 保存临时邮箱配置</button>
```

In `static/js/main.js`, implement a single helper that toggles the hint and add `change`/`input` listeners after settings DOM initialization. In the success path of existing `saveSettings()`, clear the dirty state without switching tabs.

- [ ] **Step 4: Verify the frontend settings contract passes**

Run the command from Step 2.

Expected: PASS.

- [ ] **Step 5: Commit the UI save unit**

```powershell
git add templates/index.html static/js/main.js tests/test_settings_tab_refactor_frontend.py
git commit -m "fix: add temporary-mail settings save action"
```

### Task 4: CF error guidance and safe technical details

**Files:**
- Create: `tests/test_cf_worker_error_guidance_frontend.py`
- Modify: `static/js/main.js`
- Modify: `templates/partials/modals.html` only if the existing technical-details container has no suitable element

- [ ] **Step 1: Write failing static frontend tests**

Assert the JavaScript source contains all error codes:

```text
UNAUTHORIZED
UPSTREAM_BAD_PAYLOAD
UPSTREAM_RATE_LIMITED
UPSTREAM_SERVER_ERROR
UPSTREAM_TIMEOUT
```

Assert it reads `error_detail`, passes the displayed text through `escapeHtml`, and does not reference `x-admin-auth` or `provider_jwt` in the technical-details rendering function.

- [ ] **Step 2: Verify the test fails**

Run:

```powershell
python -m unittest tests.test_cf_worker_error_guidance_frontend
```

Expected: FAIL because CF-specific guidance and `error_detail` rendering are absent.

- [ ] **Step 3: Implement targeted guidance using existing toast/error-detail UI**

Add a helper in `static/js/main.js` that activates only for temporary-mail errors and returns Chinese guidance:

- `UNAUTHORIZED`: verify the Worker `ADMIN_PASSWORDS` value matches the saved CF Worker Admin password.
- `UPSTREAM_BAD_PAYLOAD`: sync Worker domains, confirm a default domain exists, and verify Worker API compatibility.
- `UPSTREAM_RATE_LIMITED`: retry later.
- `UPSTREAM_SERVER_ERROR`: inspect Worker deployment/runtime status.
- `UPSTREAM_TIMEOUT`: inspect network reachability and Worker response time.

Pass sanitized `error_detail` to the existing technical-detail display by assigning text content or by applying `escapeHtml` before HTML insertion. Do not display credentials, JWT values, headers, or raw response objects.

- [ ] **Step 4: Verify frontend guidance contract passes**

Run the command from Step 2.

Expected: PASS.

- [ ] **Step 5: Commit the guidance unit**

```powershell
git add static/js/main.js templates/partials/modals.html tests/test_cf_worker_error_guidance_frontend.py
git commit -m "fix: guide CF Worker temporary-mail failures"
```

### Task 5: Integrated verification and delivery

**Files:**
- Verify only; no source changes unless a verification identifies a regression.

- [ ] **Step 1: Run focused Python coverage**

```powershell
python -m unittest tests.test_temp_mail_provider_cf tests.test_temp_mail_service tests.test_settings_tab_refactor_frontend tests.test_cf_worker_error_guidance_frontend
```

Expected: PASS.

- [ ] **Step 2: Run project regression checks**

```powershell
python -m compileall outlook_web
python -m unittest discover -s tests -p "test_*.py"
npm test
git diff --check
git status --short
```

Expected: compile/test commands pass, `git diff --check` reports no whitespace errors, and status lists only intentional changes or commits.

- [ ] **Step 3: Commit any verification-only correction if required**

```powershell
git add <affected-files>
git commit -m "test: cover CF Worker error guidance"
```

Expected: no uncommitted implementation changes remain.

- [ ] **Step 4: Push the feature branch after user confirmation**

```powershell
git push -u origin codex/cf-worker-error-guidance
```

Expected: remote tracking branch is created or updated.

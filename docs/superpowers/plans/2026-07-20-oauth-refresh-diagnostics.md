# OAuth 刷新诊断日志 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Microsoft OAuth refresh-token 失败的脱敏诊断数据写入现有刷新日志，并让刷新日志 API 返回关联的 trace ID。

**Architecture:** `graph.py` 将 token endpoint 的失败响应格式化为固定前缀加 JSON 的日志文本，保持现有三元组返回契约，既有刷新路径自动持久化该文本。刷新日志查询通过 `run_id` 左连接 `refresh_runs` 返回 trace ID；普通邮件读取错误路径继续只返回通用错误和 trace ID。

**Tech Stack:** Python 3、Flask、SQLite、unittest、requests。

---

### Task 1: 为 OAuth 失败日志定义脱敏格式

**Files:**
- Modify: `outlook_web/services/graph.py:1-12,263-326`
- Create: `tests/test_oauth_refresh_diagnostics.py`

- [ ] **Step 1: 写失败测试**

```python
def test_refresh_failure_returns_sanitized_structured_diagnostic(self):
    response = Mock(status_code=400)
    response.json.return_value = {"error": "invalid_grant", "error_description": "refresh_token=SECRET_TOKEN was revoked"}
    with patch("outlook_web.services.graph.requests.post", return_value=response):
        ok, error_message, new_token = test_refresh_token_with_rotation("12345678-1234-1234-1234-123456789abc", "SECRET_TOKEN")
    self.assertFalse(ok)
    self.assertIsNone(new_token)
    self.assertTrue(error_message.startswith("oauth_refresh_diagnostic:"))
    diagnostic = json.loads(error_message.split(":", 1)[1])
    self.assertEqual(diagnostic["http_status"], 400)
    self.assertEqual(diagnostic["oauth_error"], "invalid_grant")
    self.assertEqual(diagnostic["tenant"], "common")
    self.assertEqual(diagnostic["client_id_hint"], "12345678...")
    self.assertNotIn("SECRET_TOKEN", error_message)
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python -m unittest tests.test_oauth_refresh_diagnostics.OAuthRefreshDiagnosticsTests.test_refresh_failure_returns_sanitized_structured_diagnostic -v`

Expected: FAIL，因为当前错误文本未结构化。

- [ ] **Step 3: 实现最小诊断格式化函数**

在 `graph.py` 导入 `json` 与 `sanitize_error_details`，并新增：

```python
def _oauth_refresh_diagnostic(*, status: int, payload: Any, tenant: str, client_id: str) -> str:
    parsed = payload if isinstance(payload, dict) else {}
    diagnostic = {
        "http_status": int(status),
        "oauth_error": sanitize_error_details(str(parsed.get("error") or ""))[:120],
        "oauth_error_description": sanitize_error_details(str(parsed.get("error_description") or parsed.get("error") or ""))[:800],
        "tenant": str(tenant or "common")[:64],
        "client_id_hint": f"{str(client_id or '').strip()[:8]}...",
    }
    return "oauth_refresh_diagnostic:" + json.dumps(diagnostic, ensure_ascii=False, separators=(",", ":"))
```

在 `test_refresh_token_with_rotation()` 收到非 200 且非重试 429 时，用上述函数替换原 `error_msg`，传入 `res.status_code`、解析后的响应 JSON、`tenant` 和 `client_id`；保持 `(bool, error_message, new_refresh_token)` 返回形状不变。

- [ ] **Step 4: 运行测试，确认通过**

Run: `python -m unittest tests.test_oauth_refresh_diagnostics -v`

Expected: PASS，且错误日志不含 refresh token。

- [ ] **Step 5: 提交该任务**

```bash
git add outlook_web/services/graph.py tests/test_oauth_refresh_diagnostics.py
git commit -m "feat: log sanitized OAuth refresh diagnostics"
```

### Task 2: 在刷新日志 API 中返回关联 trace ID

**Files:**
- Modify: `outlook_web/controllers/accounts.py:2495-2585`
- Modify: `tests/test_oauth_refresh_diagnostics.py`

- [ ] **Step 1: 写失败测试**

```python
def test_account_refresh_logs_include_trace_id_from_refresh_run(self):
    self._insert_refresh_run(run_id="run-oauth-diagnostic", trace_id="trace-oauth-diagnostic")
    self._insert_refresh_log(run_id="run-oauth-diagnostic", error_message="oauth_refresh_diagnostic:{}")
    response = self.client.get(f"/api/accounts/{self.account_id}/refresh-logs")
    log = response.get_json()["logs"][0]
    self.assertEqual(log["run_id"], "run-oauth-diagnostic")
    self.assertEqual(log["trace_id"], "trace-oauth-diagnostic")
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python -m unittest tests.test_oauth_refresh_diagnostics.OAuthRefreshDiagnosticsTests.test_account_refresh_logs_include_trace_id_from_refresh_run -v`

Expected: FAIL，响应日志缺少 `run_id` 或 `trace_id`。

- [ ] **Step 3: 最小化扩展三条刷新日志查询**

在 `api_get_refresh_logs`、`api_get_account_refresh_logs`、`api_get_failed_refresh_logs` 查询中增加：

```sql
LEFT JOIN refresh_runs r ON r.id = l.run_id
```

每个日志对象增加：

```python
"run_id": row["run_id"],
"trace_id": row["trace_id"],
```

不为 `run_id IS NULL` 的单账号手动刷新创建新记录；其 `trace_id` 保持 `null`。

- [ ] **Step 4: 运行 API 测试，确认通过**

Run: `python -m unittest tests.test_oauth_refresh_diagnostics -v`

Expected: PASS，刷新记录可关联到 trace ID。

- [ ] **Step 5: 提交该任务**

```bash
git add outlook_web/controllers/accounts.py tests/test_oauth_refresh_diagnostics.py
git commit -m "feat: expose refresh log trace IDs"
```

### Task 3: 回归验证通用授权错误不泄露上游描述

**Files:**
- Modify: `tests/test_web_graph_auth_fallback.py`

- [ ] **Step 1: 写隐私回归测试**

```python
def test_auth_expired_response_hides_upstream_oauth_description(self):
    upstream = "oauth_refresh_diagnostic:{\\\"oauth_error_description\\\":\\\"SECRET_DETAIL\\\"}"
    mock_graph_list.return_value = {"success": False, "auth_expired": True, "error": {"details": upstream}}
    response = self.client.get(f"/api/emails/{self.account_id}")
    body = response.get_json()
    self.assertEqual(body["error"]["code"], "ACCOUNT_AUTH_EXPIRED")
    self.assertNotIn("SECRET_DETAIL", response.get_data(as_text=True))
    self.assertTrue(body["trace_id"])
```

- [ ] **Step 2: 运行测试，确认通用错误路径符合契约**

Run: `python -m unittest tests.test_web_graph_auth_fallback.WebGraphAuthFallbackTests.test_auth_expired_response_hides_upstream_oauth_description -v`

Expected: PASS；若失败，仅将 `ACCOUNT_AUTH_EXPIRED` 的 details 固定为 trace ID，不传递上游 error details。

- [ ] **Step 3: 运行针对性回归测试**

Run: `python -m unittest tests.test_oauth_refresh_diagnostics tests.test_refresh_selected_issue45 tests.test_refresh_outlook_only tests.test_web_graph_auth_fallback -v`

Expected: PASS，Token 轮换、SSE 刷新和原三元组 mock 行为不变。

- [ ] **Step 4: 提交测试变更**

```bash
git add tests/test_web_graph_auth_fallback.py tests/test_oauth_refresh_diagnostics.py
git commit -m "test: cover OAuth refresh diagnostic privacy"
```

# OAuth 刷新诊断日志设计

## 目标

在 Outlook OAuth 刷新失败时，将 Microsoft 返回的可诊断信息保存到现有账号刷新日志；普通邮件页面继续使用通用授权失败提示，并仅返回 trace ID。

## 范围与约束

- 复用 `account_refresh_logs.error_message`，不新增表或列。
- 写入 HTTP 状态、OAuth `error`、经截断与脱敏的 `error_description`、tenant、脱敏 client ID 和 trace ID。
- 不写入 refresh token、密码、access token、完整 client ID，且日志内容上限固定。
- 保留现有刷新记录保留期、失败分类及 SSE 进度接口的行为。

## 数据流

1. `graph.test_refresh_token_with_rotation()` 在 Microsoft token endpoint 返回非 200 时解析响应。
2. 该函数返回兼容现有调用方的失败文本，并附带结构化诊断信息供刷新服务使用。
3. 手动、定时、选择账号与重试刷新路径将该诊断信息序列化后写入 `account_refresh_logs.error_message`。
4. 对外邮件读取接口维持 `ACCOUNT_AUTH_EXPIRED` 通用文案；响应详情仅包含 trace ID，不包含上游 OAuth 描述。

## 查询方式

管理者通过现有“刷新记录”接口查看账号的失败日志；日志中以稳定字段名区分 `http_status`、`oauth_error`、`oauth_error_description`、`tenant`、`client_id_hint`、`trace_id`。

## 验证

- 用模拟的 Microsoft 400 响应验证诊断字段被记录。
- 断言记录中不存在 refresh token、password、access token 或完整 client ID。
- 断言账户读取接口仍返回通用授权错误且含 trace ID，不泄露上游描述。

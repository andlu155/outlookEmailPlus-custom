# CF Worker Error Guidance Design

## Goal

让临时邮箱创建失败时保留可诊断的 CF Worker 上游信息，并在统一错误弹窗中展示与错误码对应的处理建议。

## Backend

`CloudflareTempMailProvider.create_mailbox()` 在非 2xx 响应时提取响应正文，去除控制字符、压缩空白并截断为 300 个字符。Provider 返回 `error_detail`，但不返回请求头、Admin 密码、JWT 或完整响应对象。`TempMailService.generate_user_mailbox()` 将该详情传入 `TempMailError.data`，控制器沿用现有统一错误响应结构。

## Frontend

统一错误弹窗识别 `UNAUTHORIZED`、`UPSTREAM_BAD_PAYLOAD`、`UPSTREAM_RATE_LIMITED`、`UPSTREAM_SERVER_ERROR` 和 `UPSTREAM_TIMEOUT`。当错误来自临时邮箱 Provider 时，弹窗显示中文处理建议；若响应带有 `error_detail`，在技术详情区域显示已清洗文本。

临时邮箱标签在 Provider 配置区底部提供独立的“保存临时邮箱配置”按钮，调用既有 `saveSettings()`。任一临时邮箱配置字段变化后显示未保存提示；成功后保留当前标签并提示可继续同步域名或创建邮箱。保存入口不再依赖“基础”标签页。

## Tests

- Provider：400 响应保留已清洗、截断的正文；401/403 映射保持不变；敏感请求头不进入结果。
- Service/API：创建失败响应包含错误码、详情和现有 Trace ID。
- Frontend contract：错误提示代码与 `error_detail` 渲染入口存在。
- Frontend contract：临时邮箱标签存在保存入口和未保存状态提示。

## Scope

仅修改 CF 临时邮箱创建失败链路、统一错误弹窗和临时邮箱设置保存入口；不改变成功响应、Worker 请求格式或其他 Provider 的行为。

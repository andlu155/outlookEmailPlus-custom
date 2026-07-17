# 功能地图 / Feature Map

| 功能 / Capability | 主要入口 / Primary entry point | 核心模块 / Main modules | 测试 / Tests |
| --- | --- | --- | --- |
| 账户与分组 / Accounts and groups | `/api/accounts`, `/api/groups` | `controllers/accounts.py`, `repositories/` | `tests/test_core_features.py` |
| 邮件与验证码 / Mail and verification | `/api/emails`, `/api/external/*` | `controllers/emails.py`, `services/verification_*` | `tests/test_api_extract_verification.py` |
| 临时邮箱与插件 / Temp mail and plugins | `/api/temp-emails`, `/api/plugins` | `services/temp_mail_*` | `tests/test_temp_mail_plugin_*.py` |
| 邮箱池 / Mailbox pool | `/api/pool-admin`, `/api/external/pool/*` | `controllers/pool_admin.py`, `services/pool_*` | `tests/test_pool_*.py` |
| OAuth 工具 / OAuth tooling | `/token-tool`, `/api/token-tool/*` | `controllers/oauth_tool.py`, `services/oauth_tool.py` | `tests/test_oauth_tool.py` |
| 通知与调度 / Notifications and scheduling | Settings and background jobs | `services/telegram_push.py`, `services/scheduler.py` | `tests/test_settings_scheduler_reload.py` |
| 浏览器扩展 / Browser extension | `browser-extension/` | Manifest V3 popup and services | `tests/browser-extension/` |
| 部署与更新 / Deployment and updates | Docker Compose and release workflows | `docker-compose.yml`, `.github/workflows/` | CI workflows |

详细边界见 [架构地图 / Architecture Map](./ARCHITECTURE.md)。

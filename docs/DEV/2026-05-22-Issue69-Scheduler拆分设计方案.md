# Issue #69 — Phase 4: Scheduler 拆分设计方案

> 创建日期: 2026-05-22
> 关联 Issue: https://github.com/ZeroPointSix/outlookEmailPlus/issues/69
> 目标: 从架构上解耦 Web 进程与调度器进程，为多 worker 安全部署铺路
> 状态: 方案 C 已实施（`SCHEDULER_STANDALONE` 可选启用；默认保持单进程兼容）

---

## 1. 当前架构问题

```
┌─────────────────────────────────────┐
│         Docker Container            │
│  ┌───────────────────────────────┐  │
│  │    Gunicorn (master + 1 worker)│ │
│  │  ┌─────────────────────────┐  │  │
│  │  │   Flask App              │  │  │
│  │  │   ├─ HTTP Handler        │  │  │
│  │  │   ├─ BackgroundScheduler │◀─│──│── 6 个 Job 在同一个进程内
│  │  │   │  ├─ heartbeat(60s)   │  │  │
│  │  │   │  ├─ notification     │  │  │
│  │  │   │  ├─ probe_poll(5s)   │  │  │
│  │  │   │  ├─ pool_expire(60s) │  │  │
│  │  │   │  ├─ pool_recover(300s)│  │  │
│  │  │   │  └─ token_refresh    │  │  │
│  │  │   └─────────────────────┘  │  │
│  │  └─────────────────────────┘  │  │
│  └───────────────────────────────┘  │
│              SQLite (WAL)            │
└─────────────────────────────────────┘
```

**核心问题**: `-w 2` 时每个 worker 各自启动一份 BackgroundScheduler → 6 个 job 重复执行。

## 2. 当前 Scheduler Job 清单

| Job ID | 间隔 | 功能 | 关键依赖 | 进程安全 |
|--------|------|------|----------|----------|
| `scheduler_heartbeat` | 60s | 写入 `settings.scheduler_heartbeat` | DB 直连 | ✅ WAL |
| `email_notification_job` | 动态 | 统一通知分发 (Email/Webhook) | Flask app context + DB | ⚠️ 需验证 |
| `external_probe_poll` | 5s | 异步探测 pending、清理过期 probe | Flask app context + DB | ⚠️ 需验证 |
| `pool_expire_stale_claims` | 60s | 回收过期 claimed 账号 | DB 直连 | ✅ WAL |
| `pool_recover_cooldown` | 300s | 恢复 cooldown 账号 | DB 直连 | ✅ WAL |
| `token_refresh` | Cron | 定时刷新 Outlook OAuth token | Flask app context + DB + 外网 | ⚠️ 需分布式锁 |

> 注：`token_refresh` 已有 `distributed_locks` 保护，天然支持多进程。

## 3. 拆分形态方案

### 方案 A：独立 Python 进程 + 进程管理器（推荐）

```
┌─────────────────────────────────────────┐
│           Docker Container               │
│                                          │
│  ┌──────────────┐  ┌──────────────────┐ │
│  │ Gunicorn     │  │ Scheduler 独立   │ │
│  │ -w 2         │  │ Python 进程      │ │
│  │ autostart=   │  │ scheduler_app.py │ │
│  │   false      │  │                  │ │
│  │              │  │ BackgroundSched. │ │
│  │ 请求处理     │  │ - heartbeat      │ │
│  │ 无调度器     │  │ - notification   │ │
│  │              │  │ - probe_poll     │ │
│  └──────────────┘  │ - pool expire    │ │
│                     │ - pool recover   │ │
│                     │ - token refresh  │ │
│                     └──────────────────┘ │
│              SQLite (WAL)                │
└─────────────────────────────────────────┘
```

**实施步骤**：

1. **新增 `scheduler_app.py`**（独立入口）
```python
# 独立调度器进程入口
from dotenv import load_dotenv
load_dotenv()

from outlook_web.app import create_app
from outlook_web.services import graph as graph_service
from outlook_web.services import scheduler as scheduler_service
import signal, time, sys

app = create_app(autostart_scheduler=False)
scheduler_service.init_scheduler(app, graph_service.test_refresh_token_with_rotation)
print("Scheduler standalone running. PID:", os.getpid())

# 阻塞主线程，保持进程存活
stop_event = ...
signal.signal(signal.SIGTERM, lambda *a: stop_event.set())
while not stop_event.is_set():
    time.sleep(1)
```

2. **修改 `web_outlook_app.py`**：Gunicorn 模式下 `autostart_scheduler=False`
3. **Docker**: 使用简单 start script 或 supervisord 管理双进程

**优点**: 改动最小，同一容器，共享 SQLite，distributed_locks 天然保护
**缺点**: 单容器双进程，进程管理器需要引入

### 方案 B：Docker sidecar 容器

- 独立 scheduler 容器
- 共享 volume 挂载 SQLite 文件
- 通过 docker-compose 编排

**优点**: 纯容器编排，不引入进程管理器
**缺点**: 需要挂载 DB 文件卷，部署变更大

### 方案 C：轻量级双进程（无额外依赖）

```dockerfile
# Docker CMD 改为启动脚本
COPY docker-entrypoint.sh /app/
CMD ["/bin/bash", "/app/docker-entrypoint.sh"]
```

```bash
#!/bin/bash
# docker-entrypoint.sh
# 后台启动 scheduler 进程
python scheduler_app.py &
SCHEDULER_PID=$!
# 前台启动 gunicorn
exec gunicorn -w 2 -b 0.0.0.0:5000 --timeout 120 --access-logfile - web_outlook_app:app
```

**优点**: 无额外依赖，纯 shell
**缺点**: 如果 scheduler 崩溃，不会自动重启

**推荐顺序**: 先用方案 C 快速验证，确认稳定后可选方案 A（supervisord）。

## 4. 边界与依赖定义

### 4.1 Web 进程边界

- **不持有** scheduler 实例
- `create_app(autostart_scheduler=False)` 明确禁用
- 通过 `get_scheduler_instance()` 查询调度器状态时返回 `None`
- `/api/system/health` 不再报告 scheduler 心跳（改为查询 DB 中的 `scheduler_heartbeat` 键）

### 4.2 Scheduler 进程边界

- **不绑定** WSGI/HTTP 端口
- 仅持有 Flask app context（用于 settings 读取和 token 刷新）
- 不注册任何 HTTP route
- 通过 `SCHEDULER_STANDALONE=true` 环境变量标识

### 4.3 共享资源

| 资源 | 类型 | 并发控制 |
|------|------|----------|
| SQLite 文件 | 文件 | WAL 模式 + 文件锁 |
| `settings` 表 | DB 行 | SQLite 写锁（INSERT OR REPLACE） |
| `distributed_locks` 表 | DB 行 | `BEGIN IMMEDIATE` + 过期时间 |
| `refresh_runs` 表 | DB 行 | distributed_locks 保护 |
| `.env` 文件 | 配置文件 | 只读（启动时加载） |

### 4.4 Flakss app context 依赖分析

| Job | 需要 app context | 替代方案 |
|-----|-----------------|----------|
| heartbeat | 否（直接 `create_sqlite_connection`） | — |
| notification_dispatch | 是（读 settings） | 可改用 `create_sqlite_connection` |
| probe_poll | 是（`poll_pending_probes(app)`） | 需保留 app context |
| pool_expire | 否（直接 DB） | — |
| pool_recover | 否（直接 DB） | — |
| token_refresh | 是（`test_refresh_token` + settings） | 需保留 app context |

> 结论：scheduler 进程仍需加载 Flask app（`create_app()`），但仅用于提供 context，不绑定 WSGI。

## 5. 多 worker 前置清单

解耦 scheduler 后，多 worker 才是安全的。但还需要复核以下事项：

### 5.1 进程级缓存（需复核）

| 缓存 | 位置 | 影响 | 处理 |
|------|------|------|------|
| `_version_cache` | `system.py:30` | 每 worker 独立的 10 分钟 TTL | ✅ 可接受 |
| `_OVERVIEW_SUMMARY_CACHE` | `overview.py:8` | 每 worker 独立的 30 秒 TTL | ✅ 可接受 |
| `_token_cache_lock` | `imap.py:29` | 每 worker 独立的 threading.Lock | ✅ 单 worker 下安全 |
| `_lock` (channel_capability) | `channel_capability_cache.py:11` | 每 worker 独立 | ✅ 可接受 |

> 结论：当前进程级缓存均为短 TTL 或 worker 级安全，多 worker 不受影响。（但如需全局一致缓存，需引入 Redis/memcached）

### 5.2 模块级状态（需复核）

| 状态 | 位置 | 多 worker 影响 |
|------|------|----------------|
| `_APP_INSTANCE` | `app.py:7` | 每个 worker 独立 `create_app()`，各自持有 ✅ |
| `_scheduler_instance` | `scheduler.py:32` | Web 进程为 None，scheduler 进程持有 ✅ |
| `_HEALTHZ_BOOT_ID` | `system.py:35` | 每个 worker 独立 PID ✅ |

### 5.3 文档假设修正

| 文档 | 原假设 | 修正建议 |
|------|--------|----------|
| `Dockerfile:33` | "单 worker 避免 session 共享问题" | 改为 "scheduler 已拆分，单 worker 为旧注释" |
| `CLAUDE.md` | "多 worker 会重复注册 scheduler jobs" | 改为 "scheduler 独立进程后，多 worker 已安全" |

## 6. 部署迁移与回滚方案

### 6.1 迁移步骤

```
Phase 4a: 开发环境验证
  1. 新增 scheduler_app.py + docker-entrypoint.sh
  2. 本地 docker build + docker run 验证双进程
  3. 确认 scheduler 心跳正常、job 不重复

Phase 4b: Web worker 数增加
  4. gunicorn -w 2 或 -w 4
  5. 验证：首页加载、SSE 流式刷新、健康检查

Phase 4c: 生产灰度
  6. 先在 staging 环境运行 24h
  7. 监控 scheduler_heartbeat 稳定
  8. 确认 refresh_runs 无重复记录
  9. 上线生产
```

### 6.2 回滚方案

若 scheduler 独立进程出现问题：

1. **回滚代码**：恢复 `create_app()` 中 `autostart_scheduler` 为默认行为
2. **回滚 Docker**：恢复 `CMD ["gunicorn", "-w", "1", ...]`
3. **无需数据迁移**：scheduler 状态均在 SQLite 中，无格式变化

### 6.3 风险缓解

| 风险 | 缓解措施 |
|------|----------|
| scheduler 进程崩溃 | Docker HEALTHCHECK 检测 scheduler_heartbeat 更新 |
| 双进程写冲突 | SQLite WAL + distributed_locks 已保护 |
| token_refresh 重复执行 | `acquire_distributed_lock("refresh_all_tokens")` 防并发 |
| 内存增长 | scheduler 进程单独监控 `--max-requests` 或定期重启 |

## 7. 实施文件清单

### 新增文件

| 文件 | 说明 |
|------|------|
| `scheduler_app.py` | 独立调度器进程入口 (~40 行) |
| `docker-entrypoint.sh` | 双进程启动脚本 (~15 行) |

### 修改文件

| 文件 | 改动 |
|------|------|
| `web_outlook_app.py` | `create_app(autostart_scheduler=False)` 在 Gunicorn 模式 |
| `Dockerfile` | 复制 entrypoint 脚本，改用 `CMD ["/bin/bash", "/app/docker-entrypoint.sh"]` |
| `outlook_web/services/scheduler.py` | 新增 `SCHEDULER_STANDALONE` 支持 |
| `CLAUDE.md` | 修正多 worker 约束描述 |
| `docs/TD/2026-04-11-邮件获取性能优化TD.md` | 更新 scheduler 独立部署描述 |

### 不改的文件

| 文件 | 原因 |
|------|------|
| `outlook_web/app.py` | `create_app(autostart_scheduler)` 参数已支持 |
| `outlook_web/config.py` | `SCHEDULER_AUTOSTART` 已支持 |
| 所有 controller/service/repository | 不感知部署拓扑 |
| 所有前端文件 | 不受影响 |

## 8. 验收标准

1. `gunicorn -w 2` 可安全启动，无重复 scheduler job 执行
2. `scheduler_app.py` 独立进程心跳正常（每 60s 更新 `scheduler_heartbeat`）
3. `/api/system/health` 可查询到 scheduler 心跳状态（通过 DB 读取）
4. token_refresh 不出现重复执行（distributed_locks 保护验证）
5. 首页、SSE、静态资源在 `-w 2` 下功能无回归
6. 可通过 `SCHEDULER_STANDALONE=false` 回退到单进程模式

## 9. 附录：关键代码位置

| 文件 | 行号 | 关键内容 |
|------|------|----------|
| `services/scheduler.py:342-368` | — | `init_scheduler()` + `BackgroundScheduler()` |
| `services/scheduler.py:258-339` | — | `configure_scheduler_jobs()` 全量 job 注册 |
| `services/scheduler.py:371-581` | — | `scheduled_refresh_task()` 定时刷新核心逻辑 |
| `app.py:226-237` | — | `create_app()` 中 autostart 控制 |
| `web_outlook_app.py:48` | — | `create_app(autostart_scheduler=...)` 入口 |
| `config.py:62-63` | — | `get_scheduler_autostart_default()` |
| `repositories/distributed_locks.py` | — | SQLite 分布式锁实现 |

# 发布流程规范（Release Playbook）

## 当前发布基线：v3.0.0

`v3.0.0` 包含默认行为与插件安装契约的破坏性调整。发布前必须确认：

- `OAUTH_TOOL_ENABLED`、`CUSTOM_PLUGIN_URL_ENABLED` 的默认关闭行为已在升级说明中明确；
- 需要自定义插件下载的部署已准备 HTTPS URL 与 SHA-256；
- `LOGIN_PASSWORD` 和 `WATCHTOWER_HTTP_API_TOKEN` 已在生产环境显式配置；
- 已执行并记录以下验证：

```bash
python -m compileall -q outlook_web web_outlook_app.py outlook_mail_reader.py start.py tests
python -m unittest tests.test_plugin_download_boundaries tests.test_project_hardening -v
npm test
git diff --check
GITHUB_REF=refs/tags/v3.0.0 python scripts/check_release_version.py
```

本文档用于把 OutlookMail Plus 的发版/发布流程固定下来，确保：
- GitHub Release / Changelog / Docker 镜像版本一致
- 发布可追溯、可复现、可回滚

## 术语与产物

- **代码版本**：以 Git Tag 为准，格式 `vX.Y.Z`（例如 `v1.11.0`）
- **发布说明**：`CHANGELOG.md` 中对应版本段落（`## [vX.Y.Z] - YYYY-MM-DD`）
- **Docker 镜像**：
  - DockerHub：`guangshanshui/outlook-email-plus`（常用：`latest` / `vX.Y.Z`）
  - GHCR：`ghcr.io/zeropointsix/outlook-email-plus`（常用：`latest` / `main` / `vX.Y.Z`）

> 说明：镜像以 GitHub Actions 工作流 `.github/workflows/docker-build-push.yml` 为准。

## 版本号规范

采用语义化版本（SemVer）：
- **Major**（X）：破坏性变更（不兼容）
- **Minor**（Y）：新增功能（兼容）
- **Patch**（Z）：缺陷修复/小改动（兼容）

Tag 统一带 `v` 前缀：`v1.11.0`。

## 自动化发布机制（必须理解）

仓库存在工作流：**Build and Push Docker Image**（`docker-build-push.yml`），触发规则：
- **push 到 `main/master/dev`**：会构建并推送镜像（其中 `main/master` 会推 `latest`）
- **push Tag `v*.*.*`**：会构建并推送以 Tag 命名的镜像（例如 `v1.11.0`）

因此：
- 想要“稳定版本镜像”（`vX.Y.Z`）→ **必须打 Tag 并 push Tag**
- 想要“体验最新代码”（`latest`）→ **push 到 main/master 即可**

## 发布前检查（Release 前置门禁）

在开始发版前，确保以下条件成立：

1. **主分支干净**
   - `git status` 无未提交变更
   - `git pull --ff-only` 已是最新

2. **CI 全绿**
   - `Code Quality`、`Python Tests`、`Build and Push Docker Image` 等工作流通过
   - 注意：`Code Quality` / `Python Tests` / `Build and Push Docker Image` 都带 `paths` 过滤，纯文档或 `WORKSPACE.md` 提交不会自动重跑；发版时必须检查“版本提交 / tag 对应的那次运行”，不能拿后续 docs-only push 的结果替代

3. **变更记录准备完成**
   - `CHANGELOG.md` 已补齐本次版本的变更
   - 如 README 中的 Docker 示例固定展示明确版本号，需同步更新到本次版本（可选但建议）

4. **数据库迁移/破坏性变更已说明**
   - 若涉及 DB schema 版本升级、字段含义变更、默认配置变化，必须在 `CHANGELOG.md` 中写清“升级注意事项/回滚注意事项”。

## 生成发布说明（Release Notes）规则

发布说明以 **上一个版本 Tag** 为起点，收集到 **本次版本 Tag** 为止的所有变更。

推荐命令：

```bash
# 找到最近一次 release tag
git fetch --tags
git tag --sort=-creatordate | head

# 查看从上个 tag 到当前 HEAD 的提交
git log --oneline <prev_tag>..HEAD
```

PR 模板（`.github/PULL_REQUEST_TEMPLATE.md`）里也有同样的“发布日志生成规则”，提交信息要写清楚，便于汇总。

## 标准发版流程（推荐）

以下流程用于发布 `vX.Y.Z`：

1. **切到 main 并拉取最新**

```bash
git checkout main
git pull --ff-only
```

2. **准备版本内容**

- 更新 `outlook_web/__init__.py` 中的 `__version__`，必须与即将发布的 Tag 一致（`vX.Y.Z` → `X.Y.Z`）
- 更新 `CHANGELOG.md`：新增 `## [vX.Y.Z] - YYYY-MM-DD`，写清新功能/修复/兼容性说明
- （可选）更新 README / README.en 的 Docker 示例版本号

本地可预检（模拟 tag 构建门禁）：

```bash
GITHUB_REF=refs/tags/vX.Y.Z python scripts/check_release_version.py
```

3. **提交版本准备**

```bash
git add CHANGELOG.md README.md README.en.md
git commit -m "docs(release): vX.Y.Z"
```

4. **打 Tag 并推送**

```bash
git tag -a vX.Y.Z -m "vX.Y.Z"

git push origin main
git push origin vX.Y.Z
```

5. **监控镜像发布工作流**

在 GitHub Actions 中确认 `Build and Push Docker Image` 成功，且 `build-and-push` job 没有被跳过。

补充说明（当前仓库真实行为）：
- `docker-build-push.yml` 在真正构建镜像前，会先跑 `quality-gate`
- push `v*.*.*` tag 时，`quality-gate` 首先执行 `scripts/check_release_version.py`：要求 `__version__` 与 tag 一致，且 `CHANGELOG.md` 含对应章节
- `quality-gate` 内还包含 `black --check`、`isort --check-only`、`flake8`、`mypy`、`bandit` 与全量 `unittest`
- 其中任一失败，`build-and-push` job 会被跳过，注册表镜像不会发布

6. **验证镜像**

```bash
# 验证稳定版本镜像
docker pull guangshanshui/outlook-email-plus:vX.Y.Z

# 验证 latest（main/master）
docker pull guangshanshui/outlook-email-plus:latest
```

验证点：
- 拉取时间与 Actions 构建时间匹配
- `docker image inspect` 的 digest 与发布时一致（可选）

7. **创建 GitHub Release（自动）**

push `vX.Y.Z` tag 后，会由工作流 `.github/workflows/create-github-release.yml` 自动创建同名 Release，内容从 `CHANGELOG.md` 对应章节提取。
如需补充附件或微调文案，可在 GitHub Releases 页面直接编辑。

注意：`Create GitHub Release` 与 `Build and Push Docker Image` 是两条独立工作流。也就是说，**即使 Docker 发布失败，GitHub Release 仍可能成功创建**；因此发版完成判断必须分别检查“Release 创建状态”和“镜像发布状态”。

## Hotfix（紧急修复）流程

- 从 `main` 分支修复 → 走同样流程发布 `vX.Y.(Z+1)`
- 强烈建议生产始终 pin 到明确版本（`vX.Y.Z`），而不是长期使用 `latest`。

## 回滚策略

- 生产回滚优先使用 **明确版本标签**（例如回滚到 `v1.10.1`）

```bash
docker pull guangshanshui/outlook-email-plus:v1.10.1
# 将部署配置中的镜像标签改回 v1.10.1 并重启
```

- 不建议依赖 `latest` 回滚（`latest` 会随 main 推进而变化）。

## 常见问题排查

### 1）为什么 `latest` 没更新？

按以下顺序排查：
1. GitHub Actions 的 `Build and Push Docker Image` 是否成功（失败时镜像不会更新）
2. `quality-gate` 是否通过（格式化/静态检查/安全门禁/单测失败会阻断 push）
3. 是否配置了 DockerHub 推送所需 Secrets（`DOCKERHUB_USERNAME` / `DOCKERHUB_TOKEN`）
4. 你拉取的镜像仓库是否正确（DockerHub vs GHCR）

### 2）为什么 `vX.Y.Z` 镜像没生成？

- 是否真的 push 了 Tag：`git push origin vX.Y.Z`
- Tag 是否符合触发规则：`v*.*.*`
- Actions 里该 tag 事件的 `Build and Push Docker Image` 是否执行并成功

# GitHub Release v3.0.0 Design

## Goal

将已完成的插件安装安全加固和生产默认配置调整，整理为可公开发布、可持续维护的 `v3.0.0` GitHub 版本。

## Scope

- 保留当前安全改动并作为本版本的破坏性变更。
- 增加贡献、安全、行为准则和 GitHub Issue/PR 协作文件。
- 同步中文与英文 README 的入口、配置安全提示、测试与贡献说明。
- 更新变更日志和发布说明。
- 在验证通过后提交、推送 `main`、创建带注释标签并创建 GitHub Release。

## Repository Governance

根目录提供 `CONTRIBUTING.md`、`SECURITY.md` 和 `CODE_OF_CONDUCT.md`，分别定义本地开发与提交要求、私密漏洞报告途径和协作准则。`.github/` 提供结构化 Bug/功能 Issue 表单及 PR 检查清单，使后续贡献具有统一的最小信息集。

## Documentation Model

README 保持为双语项目入口：定位、功能摘要、最小启动、关键环境变量、验证命令、文档和贡献链接。长篇部署、API 和插件接入内容继续保留在现有专门文档中，避免重复维护。`CHANGELOG.md` 采用 Keep a Changelog 风格新增 `v1.14.0`，`RELEASE.md` 定义从验证到 GitHub Release 的可重复流程。

## Versioning and Delivery

版本号固定为 `v3.0.0`。提交使用 Conventional Commits，发布工作在 `codex/release-v3.0.0` 分支完成；验证通过后合并到 `main`，创建注释标签 `v3.0.0` 并推送 `main` 与标签。GitHub Release 的内容由 `CHANGELOG.md` 对应版本段落生成。

## Verification

- Python：编译、插件安全与配置回归、格式、导入、Flake8、mypy、Bandit 高严重度门禁。
- Node：`npm test`。
- Git：`git diff --check`、提交前状态检查。
- 全量 Python 发现测试作为发布记录的一部分；Windows 控制台编码、执行权限和真实 CF E2E 的既有环境失败须单独列出，不混入本次变更结论。

## Out of Scope

- 不改动与发布治理无关的业务模块。
- 不重写现有 API、部署实现或历史版本变更记录。
- 不修复本次范围外的 Windows 平台和真实外部服务测试问题。

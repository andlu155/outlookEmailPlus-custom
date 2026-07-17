# Contributing

感谢贡献。请先阅读 [功能地图](./docs/FEATURES.md)、[架构地图](./docs/ARCHITECTURE.md) 和 [安全策略](./SECURITY.md)。

## 开发流程

1. 从最新 `main` 创建 `codex/<type>-<topic>` 分支。
2. 每个提交只解决一个可验证问题，使用 Conventional Commits，例如 `fix: validate plugin checksum`。
3. 功能或缺陷修复先添加回归测试；文档变更检查链接。
4. 提交 PR 前运行与改动相关的测试，以及 `black`、`isort`、`flake8` 和 `npm test`。

## Pull Request

- 描述行为变化、兼容性和安全影响。
- 更新 README、架构/功能地图或 CHANGELOG（如适用）。
- 不提交 `.env`、数据库、令牌、日志、运行产物或安装后的插件文件。
- UI 改动附截图；破坏性变更给出升级说明。

## Reporting Bugs

普通缺陷请使用 GitHub Bug Report。涉及凭据、越权、数据暴露或远程执行的内容请遵循 [SECURITY.md](./SECURITY.md)。

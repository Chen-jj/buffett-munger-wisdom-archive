# webui AGENTS.md

## 模块定位

`webui` 负责本地评审 UI 的集成边界，以及生成资产的呈现契约。

## 职责

- 定义静态评审 UI 消费的目录契约。
- 提供或准备本地评审资产，但不持有媒体处理逻辑。
- 呈现年份、场次、章节、视频文件与字幕。
- 浏览器特定关注点与管线模块保持分离。

## 分层规则

- `domain/`：仅放 UI 无关概念（如需要），如视图就绪的目录约束。
- `application/`：prepare-review-site、validate-catalog-contract、resolve-static-assets 用例。
- `infrastructure/`：本地 HTTP 服务、静态文件复制、现有 `webapp/` 集成适配器。
- `interfaces/`：Web DTO、类 JSON schema 契约、面向 CLI 的 serve 命令。

## 技术方向

- 继续用轻量静态 HTML/CSS/JS，除非需求足以引入前端构建栈。
- 评审 UI 静态应用待按路线图重建，`src/webui` 只持有目录契约与本地服务边界。
- 生成的目录 schema 保持稳定且有文档。

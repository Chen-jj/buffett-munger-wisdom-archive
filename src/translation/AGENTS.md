# translation AGENTS.md

## 模块定位

`translation` 负责翻译计划、分批、服务方调用、术语表/风格策略，以及翻译字幕校验。

## 职责

- 翻译字幕文本，同时保持 cue 数量、顺序与时间戳不变。
- 应用巴菲特/芒格领域术语、语气与中文风格规范。
- 安全地分批发起请求，记录提供方/模型/prompt 溯源。
- 在服务方输出成为下游字幕工件之前先校验。

## 分层规则

- `domain/`：翻译单元、术语条目、风格策略、翻译批次、提供方结果等概念。
- `application/`：plan-translation、translate-srt、validate-translation、retry-failed-batches 用例。
- `infrastructure/`：OpenAI 兼容客户端、限速/重试处理、prompt 加载、响应解析。
- `interfaces/`：CLI 处理器、进度事件、面向 orchestration 的翻译摘要。

## 技术方向

- 通过适配器使用 OpenAI 兼容 API，便于日后换本地或备选提供方。
- prompt 保持版本化，并与产出溯源绑定。
- 翻译绝不改变时间轴；只有文本内容可以变。
- 凭据只经配置注入，适配器不得记录或输出 API key。

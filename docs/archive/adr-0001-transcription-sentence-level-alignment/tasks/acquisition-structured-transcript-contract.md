# 技术任务：acquisition 发布结构化官网英文逐字稿

- 任务 ID：`AQ-01`
- 优先级：`P0`
- 影响模块：`acquisition`、`archive_core` 公共 DTO 的消费
- 依赖：`AC-01`
- 被依赖：`TR-04`、`TR-06`
- 对应决策：[ADR-0001](../decision.md) §4.1
- 状态：已实现

## 背景

当前 `chapters.json` 的 paragraph 是裸字符串，CNBC speaker label 仍嵌在
`"WARREN BUFFETT: ..."` 中。transcription 不应理解 CNBC 专用页面格式，也不能把 chapter
标题或 speaker label 当成 spoken words。

## 目标

让站点适配器在采集阶段把官网逐字稿规范化为版本化、来源无关的结构：

```text
chapter metadata
  └── paragraph
        ├── speaker_label: string | null
        └── text: spoken English text
```

## 实现范围

- `CnbcCrawler`/normalizer 从 CNBC paragraph 中分离可靠 speaker label 与 spoken text。
- Generic/其他来源无法可靠识别 speaker 时写 `null`，不得猜测。
- `chapters.json` 使用 `AC-01` 的公共 DTO/schema 和版本号。
- `transcript.txt` 继续作为面向人的归档文本，不作为下游机器契约。
- chapter title、舞台说明和 speaker label 保持为结构化元数据，不混入 spoken text。
- writer 继续执行原子写和 `overwrite=False` 全量预检。

## 非目标

- 不做音频 diarization。
- 不做 ASR、音频时间对齐或句界恢复。
- 不在 transcription 中增加 CNBC 正则兼容层。
- 不自动改写已有 output 资产；存量迁移另行规划。

## 验收标准

- CNBC fixture 产出独立的 `speaker_label` 与 `text`。
- 无 speaker、未知 speaker、多个冒号、姓名缩写和舞台说明有离线边界测试。
- Generic/YouTube 路径不会伪造 speaker；无 transcript 时仍不写 transcript 工件。
- `chapters.json` 通过公共 DTO 往返，`transcript.txt` 仍可供人阅读。
- 当前未版本化结构不会被 transcription 静默误读为新 schema。
- 更新 `src/acquisition/AGENTS.md` 的工件契约。
- `python -m pytest tests/ -q -m "not live"` 全绿。

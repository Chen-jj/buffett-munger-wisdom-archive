# translation AGENTS.md

## 模块定位

`translation` 负责把已验证的 `source_alignment.json` 中完整英文 sentences 翻译为简体中文，
并发布 `translation_result.json` 与 `translation_manifest.json`。请求边界来自可选 sections；
本模块不读取、生成或修改 SRT/cue/时间轴。

## 职责

- 验证 transcription manifest、canonical source alignment 路径、大小、checksum、资产身份和语言。
- sections 非空时按完整 section 串行请求；sections 为空时以全部完整 sentences 形成一次全文请求。
- 渲染版本化 prompt 与可选 glossary，通过 `TranslationProvider` 端口调用 provider。
- 校验响应结构、section 标题规则、sentence ID 覆盖/顺序和非空译文。
- 对临时 provider 错误有限重试；首次失败后 fail-fast，不自动拆分、修复或 fallback。
- 严格校验并复用 request 级 checkpoint；原子发布完整结果/manifest，不发布部分正式结果。
- 记录 source、prompt、glossary、provider/model、生成参数、执行计数与可空 token usage 溯源。

## 非职责

- 不恢复句界，不按固定数量、字符数或 token budget 拆分 sentences/sections。
- 不规划 cue，不解析或生成 SRT，不决定时间、行宽、阅读速度或双语排版。
- 不依据 CNBC/YouTube 等来源分支处理，也不读取 transcription 私有工件。
- 不用启发式中文比例、数字或术语字符串匹配替代人工翻译质量评审。

## 分层规则

- `domain/`：provider-neutral 请求/响应、section/document 规划、glossary、prompt 渲染、响应校验和
  checkpoint cache key；禁止 SDK、文件系统和 UI。
- `application/`：输入门禁、provider port、串行编排、重试、checkpoint 恢复、完整结果组装与发布；
  不 import OpenAI SDK。
- `infrastructure/`：本地 prompt/glossary/checkpoint/artifact I/O、原子发布、时钟/等待适配器，
  OpenAI Responses API 与 Codex CLI ChatGPT adapters，以及严格 provider 配置和唯一 production
  composition。
- `interfaces/`：面向 orchestration/CLI 的 `TranslationCommand`、handler 与稳定 outcome；不暴露
  SDK response，不持有业务规则。

## Checkpoint 与发布契约

- 每个完整 section 或全文 document 是一个 checkpoint；只有 provider 完成且通过全部确定性门禁
  后才能原子保存。
- cache key 绑定 source alignment、当前请求、prompt、glossary、响应 schema 和 provider identity；
  命中时仍须重新校验 checkpoint。
- `overwrite=false` 时，匹配且完整的正式 result/manifest 对直接复用；任何冲突或孤儿工件失败。
- `overwrite=true` 跳过 checkpoint，只有全部请求成功后才原子替换正式工件对。
- manifest/checksum 决定完成状态；文件存在不是完成判据，checkpoint 也不是公共工件或阶段完成证明。

## 技术方向

- application 只依赖可替换的 `TranslationProvider`；生产配置必须显式选择
  `codex-cli-chatgpt` 或 `openai-responses`，构造或执行失败绝不 fallback。
- 仓库配置默认选择 Codex CLI ChatGPT adapter；其 model/reasoning/timeout 固定，并强制 ChatGPT
  登录。OpenAI adapter 与其固定 model/reasoning/max output/store/timeout 完整保留。
- prompt 保持版本化并与产出溯源绑定；正式结果只保存中文标题和中文 sentence，不复制英文原文。
- OpenAI API key 只从 `OPENAI_API_KEY` 环境变量读取，配置、日志、identity 和工件不得保存凭据。
- v1 不支持同一正式结果混用 provider，也不支持并发直接执行同一资产。

## 测试与当前状态

- domain、application、local infrastructure、两种 provider adapter 与显式 composition 均由离线
  fake/mock 测试覆盖；默认 pytest 不访问网络，也不调用 Codex 或 OpenAI。
- TA-10 OpenAI live gate 已被 ADR-0005 取代且未运行。真实验收只通过
  `RUN_CODEX_CLI_TRANSLATION_INTEGRATION=1` 显式开启。
- 截至 2026-10-16，离线实现与 TA-16 Codex CLI live integration 均已完成；真实运行验证了 ChatGPT
  登录、`gpt-5.6-sol` entitlement、两个 section 的标题/句子质量、完整 provenance/checksum 和
  第二次零 provider/process call 的 byte-identical 正式工件复用。

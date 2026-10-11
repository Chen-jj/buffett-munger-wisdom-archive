# 技术任务：transcription 工作流、缓存、manifest 与 integration 验收

- 任务 ID：`TR-06`
- 优先级：`P3`
- 影响模块：`transcription`，与 `media_download`/`acquisition` 仅通过公共工件集成
- 依赖：`MD-01`、`AQ-01`、`TR-01`、`TR-02`、`TR-03`、`TR-04`、`TR-05`
- 被依赖：translation、srt_processing、orchestration 后续阶段
- 对应决策：[ADR-0001](../decisions/0001-transcription-sentence-level-alignment.md) §13～§15
- 状态：已完成——工作流、缓存、manifest、离线测试和 CNBC 真实 integration 均已验收

> 当前范围（2026-10-11）：CNBC 2000 上午场第 3 节样本可从空 `output/` 自动准备，在唯一的
> integration workspace 用真实 WhisperX/pyannote/alignment model 跑通至
> `source_alignment.json`。第二次运行按 manifest 复用全部 transcription 工件。
> reference-based Golden Live 已从 transcription 移除；未来完整跨模块管线由 orchestration
> 集成测试负责。

## 目标

把已验证的 transcription 切片组装为可恢复、manifest 驱动、可用真实 CNBC 输入验证的完整阶段，
并锁定实现期模型版本、参数和 QA 门禁。

## 实现范围

- 实现稳定 command/result 与阶段顺序，不把 provider 细节暴露给 interfaces。
- 按 ADR 建立 audio、VAD/ASR、alignment、fusion 和 sentence 分层 cache key 与 stale 传播。
- 验证 `media_download` manifest/checksum 和可选 acquisition transcript checksum。
- 成功工件先写临时文件，QA 通过后原子发布 canonical 和成功 manifest。
- 失败时保留 `transcription.log`、report 和 failed manifest，不发布/替换 canonical。
- 默认禁止覆盖或删除成功昂贵工件；显式用户授权才允许替换。
- 汇总 CLI-facing 结果，只暴露 WARNING/ERROR 和阶段摘要。
- 提供显式门控的 CNBC live integration；默认测试保持离线。
- 更新根状态和模块指南中因实现完成而变化的事实。

## Live integration 范围

- CNBC 真实视频片段和官网逐字稿；
- fixture preparation 生成 canonical acquisition/media 输入，但不冒充 orchestration 测试；
- 真实 ffmpeg、pyannote、WhisperX ASR、forced alignment、官网融合和句界发布；
- 逐一解析所有 canonical 中间产物；
- 首次运行验证零 transcription cache hit；第二次运行验证六层 cache 全命中。

## 非目标

- 不实现 translation、subtitle cue、SRT 或 rendering。
- 不引入数据库、后台 worker 或云持久化。
- 不在默认离线测试中下载模型或访问网络。
- 不在 transcription 模块维护 reference-based Golden Live 或整条跨模块管线测试。

## 验收标准

- 完整 fake 工作流离线通过 CNBC 有官网与 YouTube 无官网两条路径。
- 修改官网逐字稿只重做 fusion/sentence；修改句界 policy 只重做 sentence/canonical。
- 修改模型、VAD 或 alignment 参数只使正确层及下游 stale。
- cache hit 不重复运行昂贵 provider；文件存在但 manifest/checksum 不合法时不会命中。
- 中途失败后重跑复用所有已验证上游工件。
- 未授权替换、部分写入和坏 checksum 均不会破坏已有成功 canonical。
- `RUN_TRANSCRIPTION_INTEGRATION=1` 从空 `output/` 生成输入及全部 transcription 工件。
- 相同 live 测试再次运行时六层 transcription cache 全命中。
- `.venv/bin/python -m pytest tests/ -q` 全绿，默认跳过 live 测试。

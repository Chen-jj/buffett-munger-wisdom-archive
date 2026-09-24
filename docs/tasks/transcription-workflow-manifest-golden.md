# 技术任务：transcription 工作流组装、缓存、manifest 与 golden 验收

- 任务 ID：`TR-06`
- 优先级：`P3`
- 影响模块：`transcription`，与 `media_download`/`acquisition` 仅通过公共工件集成
- 依赖：`MD-01`、`AQ-01`、`TR-01`、`TR-02`、`TR-03`、`TR-04`、`TR-05`
- 被依赖：translation、srt_processing、orchestration 后续阶段
- 对应决策：[ADR-0001](../decisions/0001-transcription-sentence-level-alignment.md) §13～§15
- 状态：待实现

## 目标

把已验证的 transcription 切片组装为可恢复、manifest 驱动、可真实评测的完整阶段，并锁定
实现期模型版本、参数和 QA 门禁。

## 实现范围

- 实现稳定 command/result 与阶段顺序，不把 provider 细节暴露给 interfaces。
- 按 ADR 建立 audio、VAD/ASR、alignment、fusion 和 sentence 分层 cache key 与 stale 传播。
- 验证 `media_download` manifest/checksum 和可选 acquisition transcript checksum。
- 成功工件先写临时文件，QA 通过后原子发布 canonical 和成功 manifest。
- 失败时保留 `transcription.log`、report 和 failed manifest，不发布/替换 canonical。
- 默认禁止覆盖或删除成功昂贵工件；显式用户授权才允许替换。
- 汇总 CLI-facing 结果，只暴露 WARNING/ERROR 和阶段摘要。
- 建立真实 CNBC/YouTube golden sample 与手工检查记录，锁定版本化 QA policy。
- 更新根状态/模块指南和路线图中因实现完成而变化的事实。

## Golden 样本最低覆盖

- CNBC 清晰单人讲话和多 speaker 问答；
- YouTube 老录音或噪声；
- 人名、公司名、数字、百分比和货币；
- 官网删口头语、ASR 漏词、官网新增或编辑文字；
- 跨 segment 完整句和单 segment 多句。

记录：词时间误差、未对齐/插值比例、融合覆盖、冲突类型、句界人工指标、运行时间、峰值
资源和所用硬件。

## 非目标

- 不实现 translation、subtitle cue、SRT 或 rendering。
- 不引入数据库、后台 worker 或云持久化。
- 不在默认离线测试中下载模型或访问网络。

## 验收标准

- 完整 fake 工作流离线通过 CNBC 有官网与 YouTube 无官网两条路径。
- 修改官网逐字稿只重做 fusion/sentence；修改句界 policy 只重做 sentence/canonical。
- 修改模型、VAD 或 alignment 参数只使正确层及下游 stale。
- cache hit 不重复运行昂贵 provider；文件存在但 manifest/checksum 不合法时不会命中。
- 中途失败后重跑复用所有已验证上游工件。
- 未授权替换、部分写入和坏 checksum 均不会破坏已有成功 canonical。
- 至少一次显式门控的真实 WhisperX golden 运行形成评测记录；默认测试仍完全离线。
- `python -m pytest tests/ -q -m "not live"` 全绿。

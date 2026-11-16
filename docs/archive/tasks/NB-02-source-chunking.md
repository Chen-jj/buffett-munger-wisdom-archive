# NB-02 英文源语 chunking

> 2026-11-17归档说明：初版源语chunking技术交付及本地模型验证归档；旧容量/评分过程保留，当前84/typed修订以ADR-0013为准。 原路径`docs/tasks/NB-02-source-chunking.md`；原状态、历史不commit/push约束及验证结果属于当时记录。后续入口：[NB-12](../../tasks/NB-12-chunking-quality-iteration.md) / [ADR-0013](../../decisions/0013-typed-chunking-quality-and-regression.md)。

- 负责人切片：NB-00；行为唯一依据 ADR-0010；2026-11-05 实施中。
- 假设：权威 words/sentences 已由 source alignment DTO 验证；只消费无辅助编辑符号的英文正文。
- 分层：domain 消费抽象句法结果；Stanza 与模型文件只在 infrastructure；application 管证据、复用、发布。

## 工程冻结

- 英文按 Unicode code point 计数，包括空格和标点；正文用公共 reconstruct_sentence_text，不添加显示换行。
- 仅超过42字符或7000ms的完整句子调用句法分析；其他句子保留且记录未分析。分析失败硬失败，无LLM/标点fallback。
- 已确认保护范围与本地识别保护范围合并。Stanza叶子按精确字符跨度映射回word，收缩词多token仍不得词内切；无法精确映射即失败。
- 成分树 S/SBAR/SINV/SQ 结束、其开始之前（非句首）为强候选；标点后的词间位置为次级；其余已分析的未保护word边界为普通候选。固定边界分值0/1/2，先求全部子块<=42且<=7000ms的方案，再以总边界分值、cue数、完整切点序列字典序择优。不存在完整合法方案则保留整句及warning，不强拆。
- 保护：无子从句的最小NP（冠词/形容词+名词核心、连续专名）；最小PP（介词与短宾语）；aux/否定与紧随动词。带子从句长NP不整棵封锁。模型识别并不保证语义完美，保存分析覆盖和保护来源。
- 第二轮左到右，仅当前超短块可与前/后一个当前邻居合并；过滤四项指标/section/speaker/跨原句gap后，同原句优先、短gap、并前。合并后指针移至合并结果的下一个块，不回首轮，不接受不足834ms的中间合并。
- 预算不改时间：<=500ms、总时长<=7000ms、媒体末尾、下一词开始前留两个实际帧；缺帧证据有后邻词则可借0，末条仍受媒体末尾限制。汉字预算以floor(9*duration/1000)表达，单行16为独立软目标。
- 模型库固定 stanza==1.11.0；模型本地身份清单绑定resources、模型、Transformer目录全部文件SHA256。显式准备命令与运行加载分离；运行设置download_method=None并离线Transformer。

## 验证

针对纯域边界矩阵、假Stanza输出映射、manifest-last与复用测试；轻量本地文件集成归 tests/orchestration/integration/offline。
真实模型准备/推理和样本断点审查另记录实际范围；不把fake测试称作模型质量验证。

## 2026-11-06 实施证据

- 当前模型包：`output/models/stanza-en-1.11.0/`，模型锁 SHA-256
  `91443b88a89229d9affa8216e0dc89b69541df9bda4e8946b01161b64bf76c7d`。
- 三个真实推理例及完整分组、保护跨度、预算和耗时保存在同目录 `validation.json`；
  覆盖条件从句、收缩词、专名、货币数字、纠正限定。非真实源视频全片审读或字幕质量结论。
- 初版定向 23 passed；新版 SRT/rendering/NB02 组合定向 1540 passed / 1 skipped（显式 local_media 默认关闭）。
  真实 full-fresh 由负责人按 NB-08 独立运行。

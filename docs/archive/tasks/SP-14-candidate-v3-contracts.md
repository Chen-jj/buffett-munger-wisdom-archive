# SP-14 — 候选v3：公共profile与跨层QA

- **Status:** accepted（候选契约与跨层技术验收）
- **Owner:** reference_author 子开发agent
- **Depends on:** SP-12；与SP-13冻结profile和报告接口后并行
- **Depended on by:** SP-15

## 范围

- 最小扩展公共profile，显式区分v3的中文软目标与时长软目标；v1/v2精确形状、原序列化与hash保持。
- 7秒/中文16/9CPS不得继续被公共QA或复用校验作为硬失败；必须有可重算finding。若可复用现有通用finding，不无故扩schema。
- 投影仍中文一逻辑行、英文实际1或2行，最多2×42。布局行为未变时不无故改codec序列化身份。
- 检查workflow、复用、fakes、跨层/对抗测试；未知/旧身份冲突、六输出证据、manifest-last、0写复用及输入溯源门禁不弱化。
- 先给精确profile建议，与planner协调，负责人确认后编码。禁止改其所有的domain三文件及对应测试。
- 阅读archive_core/srt_processing指南；不删除、不commit、不覆盖资产，不触碰translation外部改动；模块架构/公开契约变化同步更新模块指南。

## 验证

- v1/v2旧profile round-trip/hash不变；v3缺失、多余、错类型参数受控拒绝。
- >16与>7秒路径的workflow生成、报告重算、三SRT回读、再复用通过；英文超2×42或中文非停顿切分仍拒绝。
- 未经授权的旧资产不被新规则静默复用或覆盖。
- 定向测试后，与SP-13合并工作树跑完整离线pytest，负责人复验；不得声称技术通过即出版质量通过。

## 实施/验收记录

- 负责人已批准精确v3形状：沿v2字段，仅以`chinese_target_half_units=32`及
  `target_duration_ms=7000`替代旧capacity/maximum命名；不加别名/默认字段，也不额外施加
  minimum≤target配置限制。v1/v2形状、序列化与黄金hash往返保持，未知/缺失/多余/错类型拒绝。
- plan/report/manifest schema未升级；codec仍`word-wrap-english-2x42.v2`，分词身份/端口不变。
  workflow已有`analyze_plan`重算和report比较可直接消费新warning，未增加重复业务规则。
  domain负责`reading.chinese_length`及`timing.target_duration`的产生，后者按最终显示时长。
- 核心与codec/workflow/跨层/sample/composition/interfaces定向集成复验为
  **426 passed（1.82s）**。包含中文>16、7001/10001/25000ms仍单cue成功、三SRT实际读回、
  byte/mtime不变复用、严格等于目标不告警、6900ms源时长经gap延长跨7秒后告警、重签hash仍
  不能遗漏warning、英文实际packing不合法失败，以及公共覆盖合法但中文非停顿伪造计划拒绝复用。
- 非停顿伪造测试先用独立工作区重签后的正式alignment/translation DTO验证公共守恒，再验证
  domain拒绝；没有删掉前置检查或以旧fixture SHA失配冒充新边界拒绝。
- archive_core及subtitle_rendering指南已同步v3软目标契约；不修改旧上游/任何版本资产或
  translation/ADR-0002外部工作。SP-13回归收敛后的合并树完整离线已独立复跑：
  **1395 passed / 5 deselected（5.40s）**，diff whitespace检查通过；待负责人最终验收。
- 首次合并树复验的唯一旧runner测试失败，是v3结果被v2硬16验证器拒绝；由SP-15所有者迁移
  该generic测试的fixture后全绿，未放宽冻结v2指标口径或改变生产规则。

### 负责人技术验收（2026-10-23）

已审查严格v3目标字段、v1/v2精确shape/hash兼容及旧codec身份保留；独立复验核心128项，
跨层与v3 runner 56项，最终完整离线 **1395 passed / 5 deselected（5.31s）**，diff check通过。
先前非停顿伪造fixture SHA失配已修复，公共覆盖合法前置检查保留；v2 runner泛化测试改用
同时符合两版约束的小fixture，未把冻结v2硬QA改成软指标。
>16、>7秒（含25秒无新硬帽）、CPS告警、真实投影/回读/复用及重签篡改门禁均通过。
接受SP-15开始真实候选生成；最终文字质量仍需全97句另验。

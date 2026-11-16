# translation AGENTS.md

## 当前验收（2026-11-15，验收后doc-only）

NB-12在新根真实初译4次、双语编辑10次/10窗口首请求结构采纳，发布166 cue权威最终稿及173条实际warning；沿用默认provider、20项术语和既有每批3次额度，不手改稿/改prompt/重置账本。用户明确允许英文/词时/上下文等外发后正常获准运行，不发送视频音频；此前启动前权限拒绝记录保留。
负责人及独立agent全97文本复审，c69每天比源per day提前4042ms，c66/c69将每份8盎司改为8盎司装存在计量精度风险，口语/措辞与原偏好残余另列NB-12；整体语义同步/出版NOT PASSED。JET按canonical源残余保留，不因Ajit Jain词条猜改；s60原say/five与780ms尾片已由本次编辑实际重切修复。现仅交诊断样片供用户复审，未核听；五阶段同/新进程复用0内容请求/0阶段改写。
本段是冻结代码/真实生成/复用验收后的doc-only同步，不改生产.py、测试、prompt、术语表、权威稿或旧账本，不重签已有工件身份。下方NB-09/NB-10为当时历史记录。

## 历史实现（2026-11-08，Asia/Shanghai）

NB-10按用户要求补充默认术语：underlying value→「内在价值」、net worth→「净资产」；
第二轮新增官网全名Ajit Jain→「阿吉特·贾恩」，不添加JET、a JET或Jain别名，不据此改写源稿。
初译和双语编辑共用该表。仅更新术语及离线验证，未重生成NB-09译文或样片，不宣称现有产物已修稿。
用户新增逐cue反馈仍待算法及稿件修正；下文NB-09「整体同档」仅为当时审核判断，不代表本轮逐cue质量通过。

NB-09最终真实下游刷新：初译4批，编辑10批/10请求首采纳，163 cues；全97句负责人及独立agent审读后
整体与独立参考同档，保留177条实际指标warning及措辞精度取舍，未核听/无人类出版签字。编排完整回归及
两种零调用复用已验证。这里是本样本质量结论，不是运行时语义门禁或对所有新视频的质量保证。

已直接切换到 [ADR-0011 初译](../../docs/archive/decisions/0011-contextual-chunk-translation.md) 和
[ADR-0012 后处理](../../docs/archive/decisions/0012-bilingual-translation-postprocessing.md)。旧句级生产
用例和公共 result/manifest 解析已退出，不提供兼容或 provider fallback。完整真实集成及语义/音画
审核以 [ADR-0008](../../docs/archive/decisions/0008-local-orchestration-and-integration-tests.md) 为准；
本模块离线通过不是字幕或出版质量通过。历史句级验收保留于 [历史任务](../../docs/archive/tasks/README.md)。

## 职责与公开入口

- `interfaces.build_translation_handler()` / `TranslationCommand`：核对 `source_alignment`、英文候选块、
  两份上游 manifest 和媒体来源链；逐 chunk 初译。普通批次至多50块，完整句组不可拆，超50的完整句组
  单独发送；不跨 section。只读上下文、未配时的编辑标记、预算和待译正文分别传递。
- 人工维护的 `application/translation_glossary_v1.json` 为默认术语表；只传本批待译正文命中项，
  匹配不区分大小写、遵守词边界，同一起点优先全名，别称仅在独立命中时另传。已覆盖 NB-08 样片中
  的巴菲特、芒格、伯克希尔、巴菲特有限合伙公司、可口可乐和吉列，以及官网拼写 See's Candy。
  英文直/弯撇号等价；不把不确定源词当已证实的专名。
  初译和修订提示词要求按各 cue 的源词保留否定范围、数字与单位及条件和结果，不跨屏搬运含义。
  跨屏从句接续而不重复补主谓；核对数量级、计量口径和比例所指，不把份额擅自改为收益。
  初译 v5 用示例要求数字留在完整表达该数字的源 cue；前屏引出的风险从句保留不确定性，
  但不弱化独立的明确预测；并列分项继承限定和部分否定，不把是否实现改成何时实现。
  财经义 mathematical edge 使用「数学上的优势」。不新增程序语义门禁。
  不因预算超标重译，不改英文、词时或 chunk 边界；非空 section
  标题只在第一批翻译。严格响应后保存按批 checkpoint；全批通过才发布 `translation_result.json`
  与成功 `translation_manifest.json`。
- `interfaces.build_bilingual_postprocessing_handler()` / `BilingualPostprocessingCommand`：全量有界双语编辑生成、统一最终排时。
  从原始初译而不是机械短 gap 合并结果开始；完整句组按 180 个源词、50 个初始 cue 分批，不跨 section，
  单个超限完整句组独立发送。模型给中文及源词范围，不做语义评分或发布裁决。含义与逐屏对应优先，
  其次自然停顿，最后阅读指标；可以保留原有好稿，不为消除空帧告警拆坏语义。
  程序从 canonical words 重建英文及声学锚，源覆盖/来源链/保护跨度/section/speaker/跨句资格不可绕过。
  跨句合并必须覆盖完整原句；未知或未匹配人名、专名和缩写保留源拉丁字形。无自动语义门禁。
- 后处理发布唯一权威 `final_bilingual_draft.json`、`bilingual_postprocessing_report.json`、成功
  `bilingual_postprocessing_manifest.json`。长度、CPS、显示时长及非重叠短/未知帧间隔可带 warning
  正式发布；源覆盖、来源链、越界和实际重叠仍是硬错。SRT/ASS 消费权威稿，不由本模块输出或烧录。

## 复用、额度与持久化

- 初译 checkpoint 绑定源 alignment/chunk 证据、实际批请求、版本化 prompt/schema、术语规则和
  provider 身份。命中仍重验结构；失败不发布部分正式译文。初译仅瞬态 provider 错误有限重试。
- 后处理每个稳定编辑批次最多三次内容请求，先持久化再调用；恢复重构同一请求及历史响应并重算
  覆盖和权限，不能信任账本自报接纳。始终开放本批完整源句的重切权限；格式失败不扩批或重置额度。
  阅读/CPS/长度/时长与非重叠短帧间隔仅如实报告，不作候选拒绝、强行合并或重试条件。
  三次均无结构合格稿则明确记录 retained_initial_draft、partial_unresolved，保留该批原初译和实际告警；
  不是语义通过。该编辑生成直接替换旧的机械触发、固定/重切放权及告警改善门禁，不提供并行旧路径。
  新政策/输入的新生成身份不同于原策略恢复；旧账本仍保留，恢复同一新身份不能重置三次额度。
  全片 PTS 留作本地证据，不发入请求；词记录仅传 ID、原文与现有起止时间，不外发冗余来源链元数据。
- 输出先同文件系统暂存并核对，再按正文/报告、成功 manifest 最后发布；不是多文件事务。
  中断保留残留，旧 manifest 不能签认混合代次。无显式覆盖，冲突即失败，不自动删除或覆盖。
- handler `verify()` 只读重验当前配置、prompt、请求、公开工件和来源链；不构造或探测 provider、不
  写文件。有效正式复用不发内容请求。真实执行记录 provider 调用、已知 token 和未知 usage 条数；
  不将缺失 usage 当作已知零消耗。日志只留允许的元数据，不保存凭据或模型输入输出正文。

## 分层与边界

- `domain/`：分批、匹配、请求/响应和纯机械规则；不依赖 SDK、文件系统或 subprocess。
- `application/`：验证、内容请求、checkpoint、最终稿与发布，只依赖 ports。
- `infrastructure/`：Codex CLI ChatGPT 与 OpenAI Responses、文件、时钟；生产配置明确二选一，
  默认 Codex CLI ChatGPT，强制已登录的 ChatGPT auth，绝不自动 fallback。
- `interfaces/`：薄 command/outcome/public factory；不泄漏 SDK 对象。功能模块不跨调彼此私有实现。

## 验证

- 隔离单元仍在 `tests/translation/`；真实文件、prompt、checkpoint 和 Codex 进程文件协议的离线
  集成在 `tests/orchestration/integration/offline/translation/`，fake 计费调用。
- `tests/orchestration/integration/live/translation/` 为独立 `provider_contract` 场景。显式启用需
  `RUN_ORCHESTRATION_INTEGRATION=1` 与 `ORCHESTRATION_INTEGRATION_SCENARIOS=provider_contract`；
  只验证合成四句/两 section 的真实 provider 协议及复用，不能当 CNBC 或完整样片来源。
- 开发定向 276 passed / 1 skipped（真实 provider 场景默认关闭），详见
  [NB-03/04](../../docs/archive/tasks/NB-03-04-translation.md)。真实全链与质量验收由负责人独立记录。

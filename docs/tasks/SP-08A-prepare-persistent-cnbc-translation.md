# SP-08A — 经用户授权补齐并保留 CNBC 正式译文

- **Status:** accepted
- **Owner:** inputs 子开发 agent；仅负责人标记 accepted
- **Depends on:** SP-07 accepted、现有 CNBC transcription 成功工件
- **Depended on by:** SP-08
- **Authorization:** 2026-10-21 用户明确选择方案2，授权用现有 Codex CLI translation 模块生成并保存译文；无需重跑 transcription。

## 范围与验收

- 先读根及 translation 指南、ADR-0002/0005相关运行约束。只运行现有生产 composition/workflow，不改生产代码、模型/provider/auth/config，不重跑 ASR 或任何上游真实集成测试。
- 规范资产为 cnbc:2000:morning，绝对 output_root 指向仓库 output/transcription-integration；transcription_manifest/source_alignment/video 保持不变。
- 只允许 codex-cli-chatgpt，固定仓库配置 gpt-5.6-sol/high，生产 preflight 证明 ChatGPT 登录；不打印凭据、不传 OPENAI_API_KEY、不 fallback OpenAI。
- 验证现有双 section /97句输入链；无正式译文才首次生成，overwrite=false，冲突先报告，不删除或覆盖资产。
- 正式 translation_result.json / translation_manifest.json 持久化到规范工作区，checkpoint 仅放 gitignored 工作区。不提交生成工件。
- 证明两个完整 section 正式翻译、顺序/覆盖/语言、标题、源指纹与输出证据有效；立即再次运行相同 command，证明正式复用、输出 bytes/mtime 不变，新增 provider/process 翻译调用为0。
- 记录实际 CLI/provider/model 身份、调用/复用计数、两个输出 size/SHA256、上游 before/after 指纹和安全诊断；不得将其等同字幕最终验收。
- 可在 gitignored 工作区保存最小一次性运行/证据脚本，无需新增通用产品 CLI。若必须改生产代码先回负责人，不自行改已验收实现。

## 后续复用说明

后续 srt_processing 样本入口只消费并验证已保留正式输入，不运行 ASR/translation 或其他模块 live tests。
完整离线 pytest 仍是代码改动验收门槛，不会调用真实模型/网络。

## 验证

现有 TranslationWorkflow 生产运行（用户本次显式授权），随后重复 command 验证零生成调用复用。
成功后向负责人交接正式工件及证据，再放行 SP-08。

## 执行交接（2026-10-21）

### 持久工件与证据

规范工作区为 `/Users/drchan/Codebase/buffett-munger-wisdom-archive/output/transcription-integration/cnbc_2000_morning`。

| 工件 | 大小 | SHA-256 |
|---|---:|---|
| `translation_result.json` | 15207 bytes | `0862d8759a3bb0cec59bf2d3531fd2301a37b889d2499135c46ea24a608d1dfb` |
| `translation_manifest.json` | 1300 bytes | `87d7f468301b17ae0682941d681cae1ef334cb8c4d6ab89fbc115f2dc56cd07d` |

- 一次性运行脚本：工作区 `.sp08a/run_translation.py`，只组装现有生产 composition/workflow；
  所有脚本、译文、manifest、checkpoint、运行证据均受 `output/` gitignore 保护，不提交生成资产。
- 成功证据：`.sp08a/evidence-20261021T020043144847Z.json`，含 identity、两次 outcome、逐进程
  安全计数、两输出 before/after 的 size/SHA-256/mtime_ns，以及17份原文件的完整 before/after。
- 初次默认 sandbox 因权限拒绝、未产生模型事件而退出，证据保留在
  `.sp08a/evidence-20261021T020011456619Z.json`；之后经工具 `require_escalated` 授权运行成功。
  没有修改 production、provider/model/auth/config 来绕过限制，也没有 fallback。
- 纯文本审读记录：`.sp08a/quality-review-20261021T020043144847Z.json`。这是 agent 对照审读记录，
  不是人类签字、音频校正或字幕像素验收。

### 真实运行与复用

生产 preflight 确认 ChatGPT 登录；identity 为 `codex-cli-chatgpt`、`gpt-5.6-sol`、high、
`codex-cli 0.154.0`、`translation.codex-cli.v1`，子进程不含 `OPENAI_API_KEY`，使用既有
read-only/ephemeral/structured-output 模式。glossary 为 null，版本化 prompt 由现有 loader 加载。

- `sec1`：`s1..s52` 共52句，单次 provider/exec 成功，51.634秒。
- `sec2`：`s53..s97` 共45句，单次 provider/exec 成功，66.734秒。
- 首次 outcome 为 `succeeded`，manifest execution 为 request_count=2、checkpoint_reuse_count=0、
  attempt_count=2；token usage 为 null，不伪造精确消耗。
- 同一 handler/command 立即再次运行，outcome 为 `reused`、attempt_count=0；新增
  provider/process/translation-exec 均为0；两份正式输出 bytes 与 mtime_ns 完全一致。
- `SourceAlignmentDTO`、`TranslationResultDTO.validate_against_alignment()`、
  `TranslationManifestDTO` 与实际内容 SHA-256/大小均通过；源 alignment 与两处输入指纹相同。
  原工作区17份文件全部保持 size/SHA-256/mtime_ns 不变，包括视频、音频、ASR、alignment、
  transcription manifest/report/log 与既有 acquisition/download 输入。
- 未跑 transcription 或 synthetic translation live 测试；此次之后没有再运行 translation，
  后续字幕验收只消费这两份保留的正式译文。
- 只读完整离线复验：`.venv/bin/python -m pytest tests/ -q -m "not live"`
  → **1220 passed, 5 deselected**。

### 质量审读与非阻断源疑点

对照审读全部97对句子，并在独立质量记录中保存24个代表性样本：

- 两标题分别译为“一年这个周期并没有什么神奇之处”和“我们希望每笔交易都拥有数学优势”，
  与原 section 内容一致。
- `s4..s6` 保留0.5%、35年、24%、48年及接近26%；`s34/s37/s39` 保留70%以上、每天10亿份、
  每份8盎司和8000万份等数量/单位关系。
- `s19..s21`“不可能每天/每周/每个月甚至每年上涨”、`s90`“不一定意味着今年利润比去年高”
  保留否定与限定，未变为正向收益承诺。
- `s58` 的 net present value 译为“净现值”，`s64` 保留原保险与超过十亿美元风险敞口，
  `s67/s76` 的 mathematical edge/moat 分别为“数学优势/护城河”。
- **非阻断源疑点**：`s57` 正式英文已是 `a JET`，译文保留 `JET`；`s85` 正式英文含 `FLM`，
  译文仍为 `FLM`。这些是继承的源 token 疑点，不以推测修正姓名、公司或录音内容。
  未经用户授权不得改 alignment、译文或重跑上游；后续样本评审应明确保留该限制。

本任务只补齐持久翻译输入，不等同 SP-08 字幕计划、投影或 rendering 质量验收。

## 技术负责人验收（2026-10-21）

已核对真实result/manifest文件、SHA256与公开manifest，以及成功运行/立即复用证据 `.sp08a/evidence-20261021T020043144847Z.json`：97句/2 section，2次provider/translation exec；第二次新增provider/process/exec全0、正式bytes/mtime不变，17份原工作区文件未变。result 15207 bytes / SHA256 `0862d8759a3bb0cec59bf2d3531fd2301a37b889d2499135c46ea24a608d1dfb`；manifest 1300 bytes / SHA256 `87d7f468301b17ae0682941d681cae1ef334cb8c4d6ab89fbc115f2dc56cd07d`。初次默认sandbox权限失败已留证，随后按用户授权经工具提权运行成功；未更改production/auth/config/上游。SP-08A accepted，放行SP-08。

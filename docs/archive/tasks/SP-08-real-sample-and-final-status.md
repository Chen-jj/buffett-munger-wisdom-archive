# SP-08 — CNBC正式样本与最终状态

- **Status:** accepted
- **Owner:** 技术负责人验收；文档由planner子agent更新
- **Module:** 验收与状态文档
- **Decision coverage:** ADR-0003 §14.5、§15
- **Depends on:** SP-07、SP-08A（补齐正式译文）
- **Depended on by:** ADR-0003最终验收

## 范围与验收标准

- 技术负责人运行开发agent提供的本地入口，只消费现有正式输入/真实ffprobe；不重跑ASR或翻译，不删除/覆盖现有资产。验证完整输出证据、三份SRT、范围守恒、第二次正式复用bytes不变，留存版本/hash/数量/耗时/告警。

- 人工阅读长短句、未知speaker、语序重排片段，具体cue引用；明确比例非语义/fps与word gap近似，不宣称像素/烧录验收。

- 由文档责任agent更新根AGENTS、模块指南、ADR实现状态与核对时间；rendering只更新plan消费边界，仍为脚手架。不恢复旧路线图/提交生成媒体；不自动git commit。

- 正式输入前置条件已由用户授权的SP-08A解决。完成标准：SP-01..07与SP-08A accepted、完整离线全绿、真实样本硬契约/正式复用验收通过、负责人内容审读完成并如实记录ADR已声明的质量局限、状态文档准确。技术完成不等同语义对齐、出版级字幕、人类签字或视听验收。

## 验证与交接

```bash
.venv/bin/python -m pytest tests/ -q -m "not live"
git diff --check
```

记录实际命令/结果、API与未解决问题，再交负责人复验。先读根与模块AGENTS，保留用户已有ADR/指南修改；不得删除文件/资产，不作无关重构。

## 历史阻断（2026-10-21 09:05 CST）

SP-01..07已全部accepted。负责人运行真实本地样本入口得到precondition_missing（退出2），准确缺少：

- `output/transcription-integration/cnbc_2000_morning/translation_result.json`
- `output/transcription-integration/cnbc_2000_morning/translation_manifest.json`

已有alignment/video不需重跑；transcription集成测试不会生成translation工件。用户先要求记录并继续逻辑编码，现已完成；已再次询问提供正式工件目录或明确授权既有translation补齐，尚未获答复。本轮没有重跑ASR/翻译、弱化证据、合成正式译文或删除资产。真实字幕生成/第二次复用和内容抽检均未执行，不得将本任务或ADR最终验收标为完成。

## 用户授权恢复（2026-10-21）

用户明确选择方案2，授权现有Codex CLI translation流程补齐并保留正式译文，新增前置任务SP-08A。本任务的字幕运行本身仍不调用上游生成；待SP-08A验收后继续。历史缺失记录保留，不代表当前仍无授权。

## 正式输入已补齐

SP-08A已验收，规范工作区译文及manifest持久保留，正式进入真实字幕样本验收。本次字幕入口不会调用ASR或translation。

## 技术负责人真实样本验收（2026-10-21 10:11 CST）

SP-08A经用户明确授权补齐并保留上游正式译文，本任务SRT入口本身未运行ASR/translation。
负责人实际执行：

```bash
PYTHONPATH=src .venv/bin/python -m tests.srt_processing.sample_runner --run \
  --ffprobe-executable /opt/homebrew/opt/ffmpeg-full/bin/ffprobe
```

- 首次新生成：`succeeded → reused`，耗时99.7455s / 0.7465s；输入1564 words / 97 sentences / 2 sections，输出242 cues及六份正式字幕工件。
- 第二次零stage/publish，六份输出bytes/mtime一致，19份现有上游文件未变；两条独立输入链、全部输出size/SHA256、公共DTO/全文覆盖/时间/三投影回读均由入口实测通过。
- 再启动独立Python进程：`reused → reused`，0.7470s / 0.7328s，`generated_now=false`、0写入、byte-identical、上游不变，证明持久文件而非进程内缓存复用。
- 真实probe：ffprobe9.0.1，30/1fps，G=67ms，video/audio/usable均623000ms；pysubs2精确1.8.1。
- summary：7个合并cue、73句被拆分、71个结束延长、2个过短、中文CPS超目标12个、英文CPS超参考95个、未收紧gap0个。185项warning，不是185个不同cue；无硬错误。显示时长721–6838ms，英文计数最大42、中文最大32半单位，延长均不超500ms。
- plan SHA256 `5bdea730b5b57c9668d48fa5686ee2bd9e7434e0d51d1b608c22c3ec8c8284d7`；成功manifest SHA256 `51a4ed518bc2261577d42d4e5788dc06f17c0702d0fb619e6e76f24ca43d9334`。完整路径/size/hash/mtime/工具/样本cue在本地证据保留。
- 实际完整离线复验：`1220 passed, 5 deselected`（3.91s），`git diff --check`通过。全部生成资产仍gitignored，没有删除或提交它们。

持久证据（规范工作区下`.sp08a/`，不提交Git）：

- `srt-acceptance-20261021T020507Z.json`：负责人首次真实生成/立即复用。
- `srt-persisted-reuse-20261021T020926Z.json`：独立进程持久复用。
- `evidence-20261021T020043144847Z.json`：经授权的两section正式翻译/零调用复用。

### 内容审读与验收边界（不可省略）

负责人实际逐项核对长句/短句/null speaker/比例错位，以及数字、否定、金融术语；另有contracts
子agent独立通读97句/两标题并遍历242 cues。此为负责人/agent文本审读，**不是人类签字，
未观看音画，也未做像素/ASS/烧录验收**。未发现需回派的ADR硬契约缺陷，但不宣称语义对齐
或出版级字幕质量合格：

- **c3/c4（s3）**：Moe Spence/Waterloo/Nebraska在两种语言中语序不同，c4英文Nebraska却配中文Moe Spence；整句译文正确且全文守恒，但同cue人物/地名明显错位。
- **c183–185（s74）**：中文语义提前，c183/184切开“风/险”；这是普通字符应急边界/单调比例的已知限制，而非漏字或错配到另一sentence。
- **c142–147（s60，源句19.685s）**：五/十/十五年及经济优势的整句含义保留，六cue硬约束合法；但拆开“——”“认/为”且c146存在片段语义滞后。
- **c12–14、c116/117**：中文栏内英文专名Buffett Limited Partnership与“有价证券”被字符边界拆开，阅读不自然；不应作为出版级质量背书。
- **c105**为721ms、raw_gap20ms<=G，按规则不能延长；存在可消除过短的合并候选，但需增加应急断点，因此D39优先级保留短cue。**c240**780ms且已用满500ms延长额度，均已告警，非未尝试合并或越界bug。
- 译文数字/否定/金融主线未见实质反转；s57 `a JET`、s85 `FLM`是既有源token疑点，译文保留未幻觉改名，本轮不修改上游。

验收结论：按ADR-0003已确认的硬门禁、软警告和“比例不等于语义”的范围，真实技术集成与
负责人内容审读已完成；以上可见质量限制明确保留。若要求不拆汉语词/中文栏英文专名或获得
句内语义对齐，应另行确认决策/算法版本，不能本轮偷偷重译或放宽硬约束。正式成片的内容编辑、
人类复核与视觉验收不在本次技术完成声明之内。

## 最终文档验收

负责人已核对根/ADR/模块指南/任务索引的全部最新事实，历史阻断明确保留为历史，SP-08A授权例外与持久复用方式准确，质量限制及非人类/非出版级验收边界没有隐去。完整离线1220 passed / 5 deselected及diff check通过。SP-08按上述技术范围accepted，SP-01..08（含SP-08A）全部验收完成；不附带语义对齐、成片出版级、人类签字或视听质量通过声明。

# NB-08 负责人逐阶段审核与未验证范围

核对日期：2026-11-06（Asia/Shanghai）。本报告只记录本次真实新工件，不引用已删除旧产物作新验收。

## 首轮启动（历史记录）

- 启动前本人完整离线：`.venv/bin/python -m pytest tests/ -q`，2260 passed / 7 skipped（11.21s）。
- 真实入口：`PATH="$PWD/.venv/bin:/opt/homebrew/opt/ffmpeg-full/bin:$PATH" RUN_ORCHESTRATION_INTEGRATION=1 ORCHESTRATION_INTEGRATION_SCENARIOS=full_fresh .venv/bin/python -m pytest tests/orchestration/integration/live/test_full_fresh_pipeline.py -q -s`。
- 首次前根不存在。持久根：`/Users/drchan/Codebase/buffett-munger-wisdom-archive/output/orchestration-integration/NB08-20261106-fresh-v1`。
- 首轮 run ID `20261105T181558-57a5dbc3148e`（ID 为 UTC）；下列审核基于实际文件。首轮启动时尚无成片/复用/独立回归结果，最终见下文。

## 采集（本人已读）

实际父资产 `cnbc:2000:morning`，路径为上述根的 `cnbc_2000_morning/`。`meta.json`、`media_ref.json` 共同绑定
[CNBC 原视频页](https://buffett.cnbc.com/video/2000/04/29/morning-session---2000-berkshire-hathaway-annual-meeting.html)和视频 ID `105089631`；receipt 表明两次网络请求，输出证据逐个复算一致。

| 工件 | 字节 | SHA-256 |
|---|---:|---|
| acquisition_receipt.json | 1551 | `179c21c9ecbbf9a5065349b5b80646f86df818ea4d8534aa031035644a32bea8` |
| meta.json | 5270 | `5a758c160aa6aecbd6fc538870eadb09d94fadbb17a6e9d963e60b46837b6afd` |
| media_ref.json | 189 | `3fec9c4c4b0f5808a3ac6a353a4e4fd610347613ce71a7366d2f9a31bf5e18ce` |
| chapters.json | 204693 | `85b4386be3bb7e5c7c1a340fe923dbd688b368fbda27959c9afaf044401eb076` |
| transcript.txt | 123964 | `d9bceb92dffe4625bc68537f973409126c31aadab97acc1484e031edd71b83f0` |

`chapters.json` 为23节，第6/7节分别29/25段。另用本地只读HTTP查阅同一官网页的嵌入章节时间（响应 SHA-256
`ad0807ecda533095f65cf0edb5089cb710e77e93205a5dcadd4ac9ad0621f6ea`，原文留在 `/tmp/nb08-source-toc-20261106.html`，不作管线输入）：
第6节 `2101–2430s`，第7节 `2430–2723s`，第8节从 `2723s` 开始。**命令按历史样本窗口取 `2101–2724s`，比官网第7节结束多1秒**。
因此不能称样片严格等于两节官网区间；待核尾秒实际音频及末词是否含下一节，不从整数章节时间推断讲话已对齐。

## 首轮失败与恢复

真实 pytest 首轮 1 failed / 1 warning（1634.28s）：采集、下载、派生、转录、分块成功，初译 `provider_failed`，后继未运行。运行日志 `/tmp/nb08-full-fresh-20261106.log`；初译 handler 仅留受控类别，未据此猜测底层原因。WhisperX 运行见下，不因 torchcodec 系统动态库警告误判实际转录失败。
独立只读重验计划：前五阶段 `verify_reuse`，初译及后继 `execute`。恢复 run `20261106T010202-7f78b9610db4` 已记录前五阶段 `reused`，目前初译执行中。

## 媒体下载、派生（本人已读）

实际父视频 `cnbc_2000_morning/video.mp4`，935,658,650 B，SHA-256 `d29177e2abd6b3ea3fe6e2b6f6bcd6ebcd2212634b21adfa0638502b7106dbaf`；
下载 manifest `c37004e3e0666a456b4bc8192a59bb920d3edc09a7aff71a08f713f0fba14663`，父媒体经生产 yt-dlp 下载而非测试替身。
派生 `cnbc_2000_morning-ch6-7/video.mp4`，73,757,977 B，SHA-256 `d40413eb78d75e42033b4f5a86fd8196fafc0c8c7de2b6e28ed634e2d5271fa6`；
派生 manifest `c9ed9b32c40a9d33605b2ed45cf908bc8a3891ccc12af8306232b0f185c19f8c` 绑定原视频、chapters、命令、父轴2101s→子轴0及选定窗口623s；一次派生编码。不是烧录阶段重编码音频。
独立 ffprobe：父 8297.769611s、子623.000000s；均 H.264 640×360、30fps、AAC 44.1kHz双声道；派生视频/音频均从0起。
`media_boundary.json` (`237f5961d0914ede29bbc6bccff8700b1bb7dd6a65eed45b95e4aa677fb87244`) 有18,690实际帧PTS，首0、末622.966667s。

## 转录和编辑标记（本人已读97句，程序复核全词及标记）

以下均为派生规范目录内文件：

| 工件 | SHA-256 |
|---|---|
| chapters.json | `abaea8aba30f0ca081d2fdead9052090d845dd5b9905c30b790729cf63aceece` |
| audio.wav | `633b9604e040a66bc6466fe8f55b68a96b9da72284ceb30617073db0f96a3eae` |
| vad.json | `21d50ccef711b9db9cf3bcb75f9f641dbbc627d8d19784af0572f2389dea00fa` |
| raw_asr.json | `8291ea91c22297a70d93dbb10c63766cc2db3a55d3193b1a99b41d91ed83c069` |
| aligned_asr.json | `32145857705c06cfe725cfafa85127feadc042855ed0a8726deb711e78eafad8` |
| transcript_fusion.json | `6554b42adf2b153aea57047a7687042ddf469cf2c6bdc6961568f48951f98169` |
| source_alignment.json | `074cbf3709a84c9e20f334f55ac88894c1f428d3068114abfda4fa1a4e22e73e` |
| transcription_manifest.json | `22a90d822f167f66eb3c091967c05105448273eee09c9ff191716fa29bc65623` |
| transcription_report.json | `cd4b3b07cb665d3e2e89bd2b62efb291eb6ed0da6ca0577b0a86192848597968` |
| transcription.log | `6570a032acd0e54eb6769df6478dec5ac4ce2bb58d7bd17625f308697ad09a10` |

读第6/7节全部54段、canonical 97句（section分界s52/s53）；176 VAD regions、22 raw ASR段、1571 forced-aligned words、1569 canonical words（存在融合多对一）；逐ID重算1571 aligned IDs全被保留为canonical来源。
逐个对比1569个fused/canonical词，只有23个词正文删除有官网token证据的U+2014；词ID、顺序、首末时间和所有其他字段完全相同。23个标记均核到官网token含符号、无单独时间；例如 `w139` 的 `go` 后记录 `e1`，`go ahead` 正文连续。新标记数23，不拿旧26处硬作golden。
转录report 148 warnings / 0 errors：52官网词排除、48 ASR-only保留、47 ASR-only沿前section、1归首section。原页修正语如第6节的“I'm sure — well”在该处raw ASR也未出现，不能宣称编辑标记规则删掉或核听排除已证明。
文本质量差异需人工听核：s57/k150 `a JET` 对照官网人名 Ajit Jain；s81/k232 `Seas Candy` 对照 See's Candy；s85/k244 `FLM` 对照 Ethel M；s54对照地名拼写不同。原算法保留声学词，不把官网单方面校正为真值或在后续暗改英文。尾词在620.858s；官方章界换算为622s，后1秒无canonical词，**不能据此证明听不到下一章开头**。

## 英文候选块（本人逐读275块，独立复算）

`source_chunks.json` `ef3495c0d0c8b03f5a748c330ba084546bf2a23e655ecd9016df5d948f1fbe41`；报告
`6c6caacacb29fd9af6bd6e0fdbbbfe6b4c0ff19f972d9e083d9dbc5ee29142f4`；manifest
`d25d7a1136311db29cf3ab3651882c26b5159be7453021b246aa79f6c48c9e91`。
共275块，76句使用锁定Stanza成分分析、338个已知保护span；逐词覆盖恰好一次，无已知span切断、无原词移时。以实际PTS重算所有275条可借量及原/最大中文预算，一致。独立复算告警：124条原始gap不足两帧、119条英文>20CPS、34条<834ms；英文>42字符和基本>7s均0，277警告与报告一致。
断点判断不是全通过：`k58/k59` 把否定助动词和后续动词性表达分屏；`k60–k64` 从句关系及程度限定横跨块；`k180/k181` 将条件表达拆开；`k190/k191` 将让步范围拆开；`k250–k252` 搭配较生硬。`k47` 独立条件、`k24` 连续 `go ahead`、`k269` 独立近似限定较易核对。这里先记初始分块风险，待实际初译及修订对照，不以机械字数或保护span作为语义通过。

## 初译（本人逐对读275块、两标题）

恢复产生 `translation_result.json` `0e733168f1d84883c6bd9e430093976e0b355353a492d34010c0e18f449debcd`、`translation_manifest.json` `786d6c29ba900a77cabcb93845d03b05a2c7fc1fcff1510e552d8f7ca89ee82b`。与6个实际请求checkpoint逐ID逐中文内容对照完全一致；真实 Codex CLI 0.154.0 / ChatGPT / `gpt-5.6-sol` high，6批/6调用，本次无批缓存复用，token usage未知（不能说消费0 token）。
批范围 `k1–48, k49–97, k98–142, k143–187, k188–236, k237–275`；各传完整所属section的52或45原句，首批标题任务仅两次，辅助标记独立传递共23处。术语表SHA `0f4f34ea5224c9e0ed3344f4041fb490dfa6b3a141fd78c729b96af58d2c6612`；两批命中 intrinsic value，初译一致为“内在价值”。其余表项未命中，未送整表；姓名保留拉丁字母是当前prompt策略。

- 关键正例：`k3` 在同块保留姓名及Waterloo/Nebraska；`k24` 连续“不过请讲”，不是机械译破折号；0.5%、24%、48年、近26%、5/10/15年等数字，以及 `k47` 寿命条件、`k256–261` 否定限定/护城河条件保留。
- 初译逐屏风险：`k19/k20` 重复股东身份；`k62–65` 否定范围在“也与……有关”处容易误读；`k118/k119` 把长期限定提前并重复否定；`k149–151` 将 JET 前移、风险后项重复，且源专名本身有疑；`k173–175` 条件和金额次序改变导致局部错屏；`k180/181` 将结果和条件先后调换，组合意思正确但逐屏不同；`k176/177` 例示提前、`k189/190` 一生限定提前。
- `k178` 的“基本保险风险”对 primary insurance risk 不够准确；`k232`、`k244` 延续转录可疑品牌/名称而非凭空修复。`k268/269` 在与官网标记对应的修正处都用了中文破折号，保留了“所有→几乎所有”的意义，但疑有符号随修正保留的呈现，不能称中文无疑似编辑符号回显。等最终稿逐项复核，不能为质量报告删除语义。

## 有界修订、最终稿和 SRT（本人已读）

第一次恢复在第25窗遇到provider失败，保留72条已计费/预记账尝试记录（含失败）。第二次恢复 run `20261106T061006-856441c70bda` 复用下载/ASR/分块/6批正式初译和此前ledger，仅发4次新内容请求。26窗总76次（任何窗≤3），3窗采用候选、23窗保留原有效分组。73次未采用的理由：新机械违规26、明确无解17、覆盖失败16、触发问题未消除11、合并超英文CPS 2、provider失败1。未把模型请求失败当有效译文，也未重置额度。

| 工件 | SHA-256 |
|---|---|
| final_bilingual_draft.json | `d048f95ff8460dfdd9c0cd36f27db556b3e8dd82f35e470a64b420abd54937ea` |
| bilingual_postprocessing_report.json | `efd9705a09bfba7c63929ab26b32bb5c63b40aa95b0501d66fc525c1953f31c3` |
| bilingual_postprocessing_manifest.json | `aa30ad7c50eb13d65d04c4162d8f0cc8ce817674cde2a08b517e7b9530717675` |
| english.srt | `b106b237958d17a4f55afb861080b99296cdac03cca6602d3c2e728083c304a3` |
| chinese.srt | `974bd471c610e0212e7346ed269a35ca538547270e2a0ac67be7c6862ef7afa2` |
| bilingual.srt | `682d47226f06e62a944379ffb9e058d8ee51b3732ef9ad10e6f919daa4063943` |
| srt_processing_report.json | `8b1261d2852f61dceaa5f252aba95f6f6c696fc235cc6a9e8430627885863d2c` |
| srt_processing_manifest.json | `4b205041df09854e064e21b183d75b17755369153d8b647fb9f9266db40ec4f3` |

已将全部275条与逐读的初译对照：268条原范围且双语正文不变，7条属3个采用窗口，均逐条对读。
- c4/c5 将主语与动作归位，1999及后续c6的0.5%仍在；修订把该处 Berkshire Hathaway 改为“伯克希尔·哈撒韦”，与其它保留拉丁文处样式不一致。
- c144/c145 把完整人名与地点分开成两条，比原来的 “My name / is Greg Blevins …” 更完整；中文改用音译，地名仍需核听，未更改源英文。
- c246/c247：程序判定机械改善，但 **“how much money” 与 “try that” 在两屏间对调**。组合译义在，局部同步反而变差；c248 补回 very 的程度。不得称语义通过，不触发自动门禁。
- 上文其余未修正的逐屏问题仍在；c268/c269保留“所有→几乎所有”限定，也保留疑似对应标记的中文破折号，英文未泄漏编辑符号。

独立逐cue复算1569词恰好覆盖、源锚点、已知span不切、实际PTS两帧、借时公式和五类告警，吻合。24条延长，最大500ms，末cue结束620.858s；无重叠/越界。302条告警：实际间隔<2帧121、英文>20CPS 113、中文>9CPS 29、显示<834ms 27、中文>16单位12；英文>42、显示>7s及帧间隔未知均0。完整定位见两份报告，不把告警当通过。
三份 SRT 全部825个事件已逐块独立比对编号、毫秒和正文，完全等于同一稿（双语中文在上）；无重新切分或移时。

该次恢复在渲染前失败：真实声学对齐1571词经融合为1569词，渲染入参错误把两个统计口径当同一个。使用生产输入验证只读复现 `transcription QA summary differs`；待子agent修复后仅重试渲染，保持所有已验证工件。

## 首次真实烧录门禁（故障记录）

子agent将渲染的 aligned/interpolated 数量和比例改为与已验证的融合前声学工件匹配，保留了稿件覆盖及报告验证。我只读复验真实渲染输入成功（275 cues、623.000s）。再次恢复 `20261106T063931-62bcb0b40abb` 前八阶段均复用；烧录未启动，真实排版 `layout_failed`。

我用同一生产字体/字号/分行规则逐条独立尝试275条，唯一失败是 **c115，262.279–265.480s**。中文权威稿的起首为省略号，整行真实测宽 572px，安全宽576px；不是容量/字体缺失，而是当前代码把权威正文原有的行首省略号当作禁用闭合标点，因而没有合法路径。其它274条均完成这一测量层检查；这不是 libass 像素或成片通过。失败报告 `subtitle_rendering_report.json` SHA-256 `46031239bea6cdf1faa59944884b95feeeebe558bc7364d0ab4ad53d8f901ac1`，仍保留。未改最终稿、未改时、未删除/覆盖资产。

已请求确认是否仅允许权威稿本来位于 cue 起点的省略号（仍禁止分行制造起首省略号），并将失败报告原样归档后恢复渲染。独立agent成片回归待真实MP4及本人审核。工具试读派生尾音明确返回 `audio content omitted because you do not support audio input`，核听待验；不以解码/抽帧/文本替代。

用户已确认仅允许原稿自带的中文 cue 起首省略号，不允许视觉换行制造行首省略号，并授权只重跑渲染。失败报告原样移入 `cnbc_2000_morning-ch6-7/pipeline_runs/20261106T063931-62bcb0b40abb/subtitle_rendering_failed_report.json`，SHA-256 与 mtime 均不变。归档前复验渲染前基线的 69 项上游文件及检查点均未变；保留失败 run、暂存和所有正式上游资产。

## 最终发布、复用和本人播放抽查

- 布局身份 `pixel-wrap.v2` 只允许权威中文稿原有的起首 U+2026，仍拒视觉换行生成的行首省略号。首次按授权只渲染时已完成排版、逐cue实际像素预检、编码和媒体校验，但构造成功报告时把 ASS 投影间隙填入原始 cue 定位字段，受契约拒绝。run `20261106T111404-7a7c7becd186`、暂存 MP4/ASS/计划/失败报告均保留。子agent把告警定位改为左 cue 原始范围，投影区间及帧数仍写诊断，判定仍按实际 PTS，不改稿、不改时或降低门禁。
- 最终执行授权锁定 `allowed_actions=('subtitle_rendering',)`、`max_stage_executions=1`。计划验前八阶段均 `verify_reuse`，只有渲染可执行；产物发布 run `20261106T111813-59ffececf426`，前八阶段全复用，渲染编码1次、5个正式渲染文件发布。渲染前已有73项（包括69项上游/检查点和后续失败暂存）内容和 mtime 均未变；归档失败报告也保持原 SHA 和 mtime。
- 同进程 run `20261106T112032-253beb5efa11` 和独立新进程 `20261106T112050-427c550a13f9` 九阶段均 `reused`，昂贵调用及阶段改写全0；78项保护集的字节、大小、mtime和适用链接身份不变。每次22笔运行收据相关写入单列；之后 verify 全快照相同。原始 full-fresh pytest 有记录的 provider 失败，最终是同一新根经恢复完整发布，不冒称一次无故障跑完。

| 实际正式工件（均在派生规范目录内） | 字节 | SHA-256 |
|---|---:|---|
| bilingual.ass | 38,913 | `e7ac0216d8bc8174bae695f5b2c1cb76cbd1bce66df2fc792e46f9d417f6eb39` |
| subtitle_rendering_plan.json | 226,325 | `29540120f78a431083ae8b8d4ca68631d55a3a30ae6f5d4882e8ce96eea3a9ef` |
| subtitle_rendering_report.json | 206,816 | `39a5063651a37642521b0a5c96a859a7d35283fa0375abb5eea198172876df80` |
| subtitle_rendering_manifest.json | 10,531 | `374c274fc934bc6da54ee89e486b79b37237f20b0c6cb95e12b06182fc6217d3` |
| video_中文字幕.mp4 | 73,219,159 | `ac007b4f9b90b77855feb7c815d9b4923a8b6d85654174e50d1668f657ec88a8` |

本人逐个比对275条实际 ASS 的 cue ID、正文（还原视觉换行及可逆控制）、原始毫秒及最近百分秒 half-up 投影，无重叠、改字或改时。报告有275条实际 libass 像素/字体证据，零错误；独立用18,690帧PTS复算 **122条 ASS 投影间隔<2帧**（不同于原稿121；九处分类变化，净增1），告警均准确定位到原始左 cue。渲染总424条=转录之后的302条逻辑告警引用+122条ASS告警，不把重复层数当独立问题数。安全区 [32,158,608,318]；c115原稿262.279–265.480s，投影262.280–265.480s，中文保留原省略号，单行测量572px，实际 libass 像素 [77,264,565,318]。实际精确字体 Hiragino Sans GB W3、TTC face 0，SHA `f887295caf2881cab9554b14c5ab4c9ee624c3895599da152ec37416b5aefae0`。

实际派生输入及烧录输出均为623.000s、640×360 H.264 30fps/18,690帧、AAC 44.1kHz双声道/26,832音频包。对双方完整音频包按 PTS、DTS、时长、大小、内容 SHA 与 side data 序列化复算，相同 SHA `2054b2883159069111f5650c0d3fce852a5f254e2b7512a79ac369d07cfef5e1`；这是音轨保全证据，不是声画语义同步。

本人用 QuickTime 播放正式 MP4 的开头约0–3s、修复处约262–265s及尾部620–623s，确认播放到结束；另定位30s（24%）、86s（But there's）、约263.88s（c115）及尾词画面。补抽实际成片帧58.900s（四行c22）、345.200s（JET被提前）、554.500/557.000s（花费/尝试跨屏）；看见中白英黄、所查帧可读且未遮住讲话者面部，部分字幕覆盖桌上物件，不据抽帧声称全片无闪烁。正式 MP4 尾部声音试读再次返回 `audio content omitted because you do not support audio input`。**未核听、未验证声音对应或章界最后一秒的讲话，未做连续全片视觉审看。** 语义残余仍在，未作出版质量签字。

最终本人完整离线 `.venv/bin/python -m pytest tests/ -q`：2361 passed / 7 skipped（10.79s），`git diff --check` 通过。机器证据为运行根 `integration_evidence.json`，包含首次失败至恢复发布的收据链。绝对成片路径：
`/Users/drchan/Codebase/buffett-munger-wisdom-archive/output/orchestration-integration/NB08-20261106-fresh-v1/cnbc_2000_morning-ch6-7/video_中文字幕.mp4`。

[非作者独立报告](2026-11-06-new-bilingual-pipeline-independent-review.md) 已补成片审核：36个实际画帧、全部ASS/像素记录及两份复用收据和保护快照复验。独立同样未核听、不宣称语义或出版质量通过。

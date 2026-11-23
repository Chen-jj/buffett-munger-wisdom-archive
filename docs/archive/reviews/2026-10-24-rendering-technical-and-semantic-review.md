# Rendering 技术交付与双语语义同步复审

## 结论

- SR-01..06 已由负责人验收；渲染生产实现和持久样片已交付。
- SR-07 的首次编码、逐cue像素、成片媒体、同进程/独立进程零写复用通过。
- 用户实际播放后发现中文与英语讲话的内容不同步，**SR-07 最终验收未通过**。
- 用户后续确认其观察中音轨与英文单词时间准确，当前探索应保留 transcription，聚焦双语语义块对应。
  这不是负责人或 agent 对全片音轨独立核听后得出的声学认证。
- 尚未实施新的语义对齐方案，没有修正版样片；不得把抽帧审图、测试绿色或本报告当作出版签字。

## 技术证据

规范工作区：`output/cue-evaluation/20261023-candidate-v3/workspaces/cnbc_2000_morning/`。

- 样片：`video_中文字幕.mp4`，61,593,537 bytes。
- SHA-256：`c7476e3c0f44b00de6ed07f1372eac19654caacc243f513f0e6768abd8bdb78f`。
- 623.000秒，640×360，30fps，18,690帧，H.264 / yuv420p；AAC 44,100Hz 双声道完整保留。
- 2 sections / 97 sentences / 163 cues；163次真实透明像素预检，41个四行cue，0 rendering error。
- 报告174项warning全部为 `upstream.*` 上下文，不是新增渲染错误。
- 首次 `succeeded → reused → reused`；复用的 stage/publish/mkdir/pixel/content-encode 均0，
  五正式输出 bytes/mtime 与全部受保护上游、历史文件和链接目标不变。
- 负责人另串行运行真实集成 pytest：1 passed（10.97s）；runner离线21 passed；完整离线
  2580 passed / 6 skipped（12.95s）。这些为本轮验收时点结果，不代替提交前重新验证。
- 负责人独立ffprobe/SHA验证与首次证据一致；源/成片音频copy-payload聚合SHA均为
  `9346949f66e8ab2708d0dec9e46bc6047fc89b2db434ab2e2297abb76b4001b3`。

持久证据位于 gitignored `output/subtitle-rendering-integration/`：

- `SR07-20261024-first-v1/protected_before.json` 与 `result.json`：首次生成与复用证据；
- `pytest-31ecfe10410747518ffb5e0bbfdfcc90.json`：负责人独立复用；
- `SR07-20261024-first-v1/frame-index.json`、`frames-v2/contact-sheet-{1,2,3,4}.png`：
  20张实际成片抽帧，负责人已查看；
- `SR07-20261024-first-v1/audio-packet-audit.json`：agent报告26,832个音频packet的内容和时序一致。

抽帧未见裁切/越界/中英视觉行重叠；c6的“实 / 现”视觉断字不自然，S17/S22/S48/S74/S88等
既有语义错位仍然可见。静帧不能证明没有闪烁，也不能代替听音与连续播放。

## 用户人类播放反馈

以下时间来自用户播放器截图的秒级显示，不是假定已精确到帧的标注：

| 大约位置 | 用户观察 |
|---|---|
| 00:23 | 已读 Berkshire Hathaway，中文对应名称仍在下一cue，尚未出现 |
| 00:30 | percent还在读，字幕已消失；尾字/显示边界应单独核对，不能只凭语义重切宣称已解决 |
| 00:36 | you have已经读到，中文对应内容仍未出现 |
| 01:26 | but the已读，字幕尚未出现 |

用户随后定位：中文停顿/整块优先切分，再为其分配英文词区间；中英并非一一对应，比例映射
会把同一语义的中英部分放进不同cue。以s5为例，旧c5英文已含`Berkshire Hathaway has`，
但中文该名称在c6；s6旧c7英文已有`you have had a run`，中文对应内容却到c8才显示。

“英文优先”本身也不是证明：若中文仍按比例分配，或译文有语序交叉，问题仍可存在。
完整方案需比较语义块对齐、上下文感知的分块翻译、联合切分、必要的局部译序调整与独立语言时间窗等选项。
具体架构、约束取舍和是否引入模型工件尚未接受，见[探索prompt](../prompts/bilingual-semantic-alignment-exploration.md)。

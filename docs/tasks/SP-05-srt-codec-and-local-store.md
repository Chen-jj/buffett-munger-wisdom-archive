# SP-05 — pysubs2投影、回读及本地工件适配器

- **Status:** accepted
- **Owner:** contracts 子开发 agent；仅技术负责人标记accepted
- **Module:** srt_processing/infrastructure
- **Decision coverage:** ADR-0003 §10.3、§12、§14.5
- **Depends on:** SP-01、SP-04
- **Depended on by:** SP-06

## 范围与验收标准

- requirements精确锁pysubs2==1.8.1；按SP-04端口实现本地JSON/bytes/hash/store/clock与pysubs2 codec。

- 固定三份投影共享cue/time，中文在上；单语无视觉换行、UTF-8无BOM/LF/结尾换行。必须用pysubs2写出并读回逐cue对照；标签/转义不能静默解释或剥除，不能无损则失败。

- store支持同文件系统暂存/逐文件原子替换/manifest-last；不宣称多文件事务，不删除残留或上游资产。版本/序列化identity供复用绑定。

- 测试标点/转义/HTML或ASS类似正文/长时间码/空事件过滤、投影字节和原子替换故障。仅拥有codec.py、local.py及requirements/对应测试，不动probe/ports/统一exports。

## 验证与交接

```bash
.venv/bin/python -m pytest tests/srt_processing/test_codec.py tests/srt_processing/test_local.py -q -m "not live"
git diff --check
```

记录实际命令/结果、API与未解决问题，再交负责人复验。先读根与模块AGENTS，保留用户已有ADR/指南修改；不得删除文件/资产，不作无关重构。

## 开发交接（2026-10-21）

- 修改仅限 `src/srt_processing/infrastructure/codec.py`、`local.py`、requirements 中的
  `pysubs2==1.8.1`、对应两份测试和本任务记录。未改统一 exports、ports、probe、planner、
  上游工件或其他 agent 文件。模块/根指南由负责人在总验收时统一更新。
- `Pysubs2SrtCodec()` 在构造时核对实际库版本；`.identity` 返回严格公共 `SubtitleCodecDTO`。
  `.encode(plan, language)` 返回 UTF-8 bytes，language 固定 `english/chinese/bilingual`，
  三份共用 cue/time，双语只加中英结构换行。pysubs2 负责写出和读回，逐项比较源 plan。
- `.decode(data)` 返回 `tuple[SrtCue,...]`；编号/分块仅做最小结构门禁（pysubs2 不保留编号），
  时间与正文由库解码。检查 UTF-8、无 BOM、LF、末尾换行、1..N、精确时间码、非空正文、
  无重叠，并将库读回的 plaintext 与原 SRT 正文比较，不能默默解释/剥除标签或转义。
- 错误为 `SubtitleCodecError(ValueError)`，`category="codec_invalid"`。HTML/ASS 标签、
  字面 `\\N/\\n/\\h`、drawing 事件过滤和 >=100h 时间溢出等不能无损时失败，不改写源文。
  库还可能把最后一个双语 cue 的纯数字英文行当编号剥除；本实现检测并失败，没有绕过库兜底。
  安全字面转义、标点、实体串、组合标记和 10h/99h 时间码均有无损测试。
- `LocalSubtitleArtifactStore` 实现 ports 的 `exists/read_bytes/size/sha256`、
  `stage_bytes(target_path,data)->str` 和 `publish(staged_path,target_path,*,overwrite)`。
  stage 只写目标同目录临时文件，不碰正式目标；publish 只接受对应目标的暂存名并逐文件
  `Path.replace`。默认冲突不覆盖（含断链 symlink），覆盖须显式 true。故障保留残留，
  不删除、不回滚；manifest-last 与全套暂存 QA 顺序由 SP-06 负责，不冒充多文件事务。
- `SystemClock.now_utc()->str` 生成显式 Z 时间。`json_bytes(mapping)->bytes` 提供本地适配器
  稳定 JSON（sorted keys、indent2、UTF-8、不允许非有限数、末尾 LF），application 不反向
  import 此 infrastructure helper。

### 实际验证

- `.venv/bin/python -m pytest tests/srt_processing/test_codec.py tests/srt_processing/test_local.py -q -m "not live"`
  → **94 passed**。
- `.venv/bin/python -m pytest tests/ -q -m "not live"` → **984 passed, 5 deselected**。
- `git diff --check` → 通过。
- 测试覆盖写入/替换失败、残留保留和混合代次不是事务；无真实 ffprobe、网络、ASR 或翻译调用。
- 无未解决阻断，未作 Git 提交。

## 技术负责人验收（2026-10-21）

已审查codec/local、精确依赖锁定与真实pysubs2回读反例；独立定向 **94 passed**，完整离线 **984 passed / 5 deselected**，diff check通过。不能无损表示的标签/转义/纯数字末行明确失败而非改写；同FS暂存与单文件替换失败不清理残留。SP-05 accepted，SP-06仍待SP-03验收。

# SP-04 — 双链输入门禁、端口与ffprobe

- **Status:** accepted
- **Owner:** inputs 子开发 agent；仅技术负责人标记accepted
- **Module:** srt_processing/application + infrastructure/probe
- **Decision coverage:** ADR-0003 §5、§9.5、§13、§14.1
- **Depends on:** SP-01
- **Depended on by:** SP-05、SP-06

## 范围与验收标准

- 定义application端口：工件读写/指纹、probe、codec、clock，先交接稳定接口。实现规范工作区及两条独立manifest成功证据链，实际size/hash、公共DTO解析、en->zh-Hans、validate_against_alignment、两处alignment指纹交叉检查。

- 显式验证现有transcription schema/workflow/source_alignment/audio记录及canonical路径；禁止import上游内部或重构上游。video hash匹配成功audio provenance.video_sha256后才probe/planner；可用末尾=min(video,audio)，源词越界硬失败。

- ffprobe adapter通过可注入共享process argv，保留正有理数原始p/q、有效duration、工具版本；无视频/零fps/异常不得猜默认。测试双链每类错误独立失败、同源失败零probe、sections=[]、标题仅验证及fake process。

- 文件所有权仅application/ports.py、inputs.py及infrastructure/probe.py（或等价）与对应测试；不动workflow/codec/local/统一exports。

## 验证与交接

```bash
.venv/bin/python -m pytest tests/srt_processing/test_inputs.py tests/srt_processing/test_probe.py -q -m "not live"
git diff --check
```

记录实际命令/结果、API与未解决问题，再交负责人复验。先读根与模块AGENTS，保留用户已有ADR/指南修改；不得删除文件/资产，不作无关重构。

## 开发交接（2026-10-21）

实现仅涉及 `application/ports.py`、`application/inputs.py`、`infrastructure/probe.py` 及
`tests/srt_processing/test_ports.py`、`test_inputs.py`、`test_probe.py`；未修改统一 exports、
workflow、codec、local store、上游模块或正式工件，未作 Git 提交。

### 固定 API

- `SubtitleArtifactStore`：`exists(path)`、`read_bytes(path)`、`size(path)`、`sha256(path)`；
  `stage_bytes(target_path, data) -> str` 返回同文件系统暂存路径；
  `publish(staged_path, target_path, *, overwrite) -> None` 只原子发布单个已暂存文件。
  workflow 必须先暂存全部正文/报告，完整 QA 后逐个发布，成功 manifest 最后单独暂存发布；
  无多文件事务、自动清理或删除 API。
- `MediaProbe.probe(video_path) -> MediaProbeResult(video_duration_ms, fps_numerator,
  fps_denominator, tool_version)`；正整数有理数保留原分子分母，不约分。
- `SrtCodec.identity -> SubtitleCodecDTO`、`encode(plan, language) -> bytes`，language 固定
  `english/chinese/bilingual`；`decode(data) -> tuple[SrtCue, ...]`，后者字段为
  `index, start_ms, end_ms, text`，不泄漏第三方对象。
- `Clock.now_utc() -> str`。
- `load_subtitle_inputs(*, asset_id, transcription_manifest_path, translation_manifest_path,
  artifacts, probe, output_root="output") -> ValidatedSubtitleInputs`；返回字段为
  `asset, workspace, alignment, translation, evidence, media, probe`。`evidence` 为冻结的五项
  mapping：`transcription_manifest/source_alignment/translation_manifest/translation_result/video`。
  证据路径只存规范 basename；实际读路径统一由工作区构建器和工件名派生。
- `SubtitleInputError.category = "input_invalid"`；`SubtitleMediaError.category = "media_invalid"`。
- `FfprobeMediaProbe(*, executable="ffprobe", process=run_process, timeout=30.0)`；先读取工具
  版本，再以 argv、`v:0` 和固定 show_entries 探测。duration 使用 Decimal 秒向下取整到
  毫秒，避免边界虚增；无默认 fps、逐帧校准或媒体修复。

### 门禁与验证证据

四份输入 JSON 的解析、大小和 SHA-256 使用同一份原始 bytes，避免内容与证明分离；只有
视频通过 store 的流式指纹端口。transcription manifest、成功 audio/source_alignment record
和规范路径显式校验，alignment 当前顶层及 word/sentence/section 字段严格校验后再调用公共
DTO；不读取上游私有 VAD/ASR 文件。translation 公共 DTO 验证及两处 alignment SHA-256
独立核对；视频同源校验失败绝不调用 probe。可用末尾取音视频较早者，越界词硬失败，不截词。

- `.venv/bin/python -m pytest tests/srt_processing/test_inputs.py tests/srt_processing/test_probe.py tests/srt_processing/test_ports.py -q -m "not live"`
  → **141 passed**。
- `.venv/bin/python -m pytest tests/ -q -m "not live"` → **890 passed, 5 deselected**
  （包含同时落盘的 SP-02 测试，2026-10-21 本次运行）。
- `git diff --check` → 通过。
- 反例覆盖每条输入证据链独立失败、未知/旧字段、非规范路径、同长度篡改、缺失/损坏 JSON、
  sections 为空/标题规则、空 alignment、同源失败零 probe、媒体较短与词越界、原有理数及
  向上取整 G、fake process argv/版本/失败/无流/无效 fps/duration/JSON。
- 全部使用内存 store 与 fake probe/process；未运行真实 ffprobe、网络、ASR 或翻译。

当前无未解决阻断；等待技术负责人独立复验，不能据此声称整个字幕模块已实现。

## 技术负责人验收（2026-10-21）

已审查ports/inputs/probe及门禁反例；独立定向 **141 passed**，完整离线 **890 passed / 5 deselected**，diff check通过。双证据链、同bytes解析与指纹、视频同源失败零probe、严格schema及有理数probe符合ADR。SP-04 accepted，放行SP-05。

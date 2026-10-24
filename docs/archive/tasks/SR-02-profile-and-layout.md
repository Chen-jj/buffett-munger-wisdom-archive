# SR-02 — 固定 profile、缩放与纯视觉布局

- **Status:** accepted
- **Owner:** render_contracts 子开发 agent（负责人验收）
- **Depends on:** SR-01 accepted
- **Depended on by:** SR-03、SR-04、SR-05

## 范围

只改rendering/domain、相关测试及config.yaml的旧三个未用样式块（只移除配置字段，不删除文件），按ADR-0006第9–11节替换为subtitle_rendering。建立纯domain模型/measure抽象、half-up缩放、安全矩形、中文grapheme/Latin/数字保护、英文词间空白候选、完整一/两行路径和确定性字典序评分、总行数/高度QA。不重用上游计数充当像素；16/7秒/CPS只属上游warning。

## 验证/交接

覆盖多分辨率half-up、1–4行、无解受控失败、combining/ZWJ/variation、Latin撇号连字符、数字单位、标点禁则、长词、正文/时间守恒、候选枚举扰动稳定。domain禁止文件/外部库/ffmpeg。先交接口给SR-03/04/05；定向测试与完整离线pytest后负责人独立复验。固定样式样本若不可容纳先报，不改字号或正文兜底。

## 已批准接口与实现

- `domain.models.FontMeasurer.measure(text, font_size, outline_width, shadow)` 返回
  `RenderLineMetricsDTO`，包含描边/阴影安全余量；`GraphemeSegmenter.version` 与
  `boundaries(text)` 提供包含 0/len 的严格 code-point offset tuple。
- 完整 Unicode grapheme 由 infrastructure adapter 使用 `regex \X`；已协调 SR-03，
  requirements 显式 pin `regex==2026.7.19`，边界 adapter 版本必须出现在
  `font.measurement_adapter_version`。domain 不 import regex，不冒称上游边界规则等价 UAX。
- 负责人预审补充：stdlib Latin/数字/标点分类还依赖 Python Unicode DB，新增
  `UNICODE_CLASSIFICATION_VERSION=unicode-classification-<unicodedata.unidata_version>`，必须与
  segmenter 版本分别作为 measurement identity 的完整分号 token 绑定；运行时版本变化拒用。
  `pixel-wrap.v1` 固定的是规则与单位表，不谎称冻结运行库的 Unicode 分类表。
- `profile_from_config(block)` 严格消费 ADR 单块配置，映射 `profile -> name` 并填入固定
  `v1/pixel-wrap.v1`，不接纳旧参数或无版本扩展。
- `layout.scale_profile(profile,width,height)` 返回 typed style/safe area；
  `choose_visual_layout(...)` 完整枚举一/两行、按字典序最优；
  `layout_cue(...)` 合并中英并验证总行数/高度；
  `build_render_plan(*,asset_id,inputs,input_media,source_plan,profile,font,tools,measurer,segmenter)`
  发布公共 `SubtitleRenderPlanDTO`，不写文件；
  `validation.validate_render_plan(plan,source_plan,measurer,segmenter)` 重算所有断点/测量/边界。
- `pixel-wrap.v1` 冻结 `NUMERIC_UNIT_RULES_VERSION=numeric-units.v1`、`NUMERIC_UNITS` 与
  Latin/数字保护。只保护固定词表和语法可识别紧密单位，不推断任意中文语义。每个列出单位
  都有参数化回归；连续 decimal、分隔符、科学计数、币种前缀、SI复合后缀、多字符中文单位
  不允许内部断开。
- 负责人确认评分：无断点为0，强/弱/普通边界 penalty=0/1/2；强标点双行可在单行能放下时
  凭宽度胜出，不另加最少行数偏好。中英独立选完后若合并高度无解，失败而不降字号或改正文。

## 开发验证（2026-10-24 00:14 CST，非负责人验收）

```text
.venv/bin/python -m pytest tests/subtitle_rendering/test_layout.py -q
181 passed

.venv/bin/python -m pytest tests/ -q
1773 passed, 5 skipped

git diff --check
passed
```

自有文件：`src/subtitle_rendering/domain/models.py`、`layout.py`、`validation.py`，
`tests/subtitle_rendering/test_layout.py`；仅替换 config.yaml 三个旧样式块，追加已批准的 regex
直接依赖，更新本任务与 rendering 指南。未改根文档/其他 agent 文件、上游或 output，未提交。

测试覆盖首轮发现并修复全宽小数点、日、个百分点和“百分点”的倍率前缀贪婪冲突；保留失败
场景并增加所有冻结单位逐项回归，没有弱化断点保护。真实固定样式是否容纳全部163 cues，
仍须 SR-03 的实际测量和 SR-07 样片验证；本任务不宣称像素或成片通过。

负责人 Unicode 身份预审前的自测为 177 / 全 1769 passed；修复后新增运行时分类版本变化与
伪造子串拒用、普通合法断点、宽度平衡优先及普通同分 offset tie-break 回归，得到上列最新结果。

## 负责人验收（2026-10-24 00:15 CST）

已审纯布局、精确评分、保护边界、固定配置/half-up及重算抗篡改；预审要求补绑定运行时Unicode分类身份，开发agent已修复并加完整token反例。负责人独立复验181 passed、完整1773 passed / 5 skipped（5.94s），diff check通过。SR-02 accepted，放行SR-03/04。

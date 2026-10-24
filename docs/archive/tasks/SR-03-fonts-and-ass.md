# SR-03 — 精确字体、ASS 与真实像素预检

- **Status:** accepted
- **Owner:** render_font_ass 开发agent
- **Depends on:** SR-01、SR-02 accepted
- **Depended on by:** SR-05

## 范围

只拥有rendering/infrastructure/fonts.py、ass.py、pixel.py及对应测试/必要依赖声明（依赖改动先协调）。按ADR第12–14节实现精确文件/hash/TTC face/family/style/glyph门禁、确定性像素测量；pysubs2生成/回读ASS，中文上英文下、受控字号颜色、禁自动换行、正文纯文本安全转义。不得复制系统字体入仓库。

与SR-04协调逐cue透明RGBA内存/pipe预检接口，实际libass字体选择日志必须验证文件/face，无fallback；逐cue非空bbox、安全矩形、无额外行、中英文颜色/字号/顺序检查。默认测试fake，不启动系统字体或ffmpeg。

## 验证/交接

字体缺失/hash/face/glyph/fallback失败；恶意ASS/HTML类似正文、反斜线、大括号、literal\\N/\\h逐cue可无损读回；时间遵循已获用户批准的ADR第12.1节显式百分秒投影，权威毫秒不变。测试ASS字节确定性/样式/行数，像素预检各种失败。开发者定向测试，负责人复跑及diff审查。

## 只读设计预检

- 精确TTC index0的Pillow粗测全部163 cue可放入576px宽两行；仍需合法断点与真实libass像素验收，不提前判passed。
- CoreText日志数字face为-1，但含精确文件和PostScript名`HiraginoSansGB-W3`。负责人批准通过已hash验证TTC name6唯一映射来证明face0；未知/歧义/另face必须拒绝，不把-1本身当通过。
- 字体身份需绑定PostScript名和测量adapter版本；fontTools读取name16/17验证family/style，读取全部face的name6证明唯一face映射，Pillow以精确文件及index测量。不依赖系统family搜索或复制字体。
- libass 0.17.5原生支持`\\{`、`\\}`，但不支持通用反斜线escape。`\\\\N`仍会触发换行；曾提出的反斜线+空override `\\{}N` 方案已撤销，因为实际显示的是`{}N`，不能以pysubs2保留event.text或未换行冒充屏幕保真。
- 用户已批准：每个源反斜线之后插入U+2060 WORD JOINER作为版本化、可逆的模块显示控制，身份为`bilingual-ass.word-joiner.v1`。只读libass内存实验中，安全正文`left \\Q right`与在反斜线后加U+2060的版本alpha逐像素相同；加控制的literal `\\N`不换行。该控制不在字体cmap中，但libass按default-ignorable处理、零像素且不触发fallback。仅模块插入的控制可豁免glyph检查；权威正文的所有code point仍须完整检查。
- ASS回读须使用严格的模块dialect scanner，逐字符移除仅模块产生的控制、重建visual offsets，并与权威正文比较；不能使用会剥除正文类标签的`pysubs2.plaintext`作为保真证明。HTML类似文本保留为普通正文，不做HTML解析。
- SR-04提供每cue独立进程的透明RGBA帧及完整有界fontselect日志；ASS filter读取需要seek，不能把`/dev/stdin`当ASS文件。用户已批准提前仅暂存ASS、不发布，失败保留残留；此任务不自行发布正式工件。
- 像素QA结合严格ASS样式/禁自动换行回读、alpha完整边界、分语言primary-color像素与几何顺序；不能仅数全alpha行带，因为描边/阴影会连接邻行，点状glyph也会将一行分成多个带。实现仍须对无额外行、颜色、字号给出可复验检查，不能只报告bbox。

调查使用的主源：[libass 0.17.5文本解释器](https://github.com/libass/libass/blob/0.17.5/libass/ass_parse.c)。

## 实现与冻结API

- `ExactFontAdapter(spec, texts)`先读取/验证同一份精确字体bytes，随后测量也只从该内存bytes和index加载；`.identity`与`.measure(text,font_size,outline_width,shadow)`供workflow/domain使用。
- `RegexGraphemeSegmenter().boundaries(text)`使用完整`regex \\X`；测量identity精确包含Pillow/fontTools/FreeType/RAQM/HarfBuzz/FriBidi、regex segmentation、stdlib Unicode classification与固定alpha定位规则。新增依赖pin为`fonttools==4.63.0`。
- `Pysubs2AssCodec().encode(plan,source)->bytes`、`.validate(data,plan,source)->None`、`.library_version`。严格canonical bytes、pysubs2结构回读和模块dialect逆解三层检查；保留断点两侧全部原始空白。
- `pixel.preflight(plan,source,ass_path,renderer)->tuple[RenderPixelResultDTO,...]`先验证staged ASS，再独立渲染全部cue；`validate_frame`检查当前frame唯一的`n−1`条强制断行证据、无意外断行、实际fontselect、alpha半开bbox、安全区域、分语言颜色/顺序和测量几何包络。
- 固定ASS派生marginv为`scaled_vertical_margin + outline_width + shadow + 1`；末尾1为实际像素raster余量，不缩放字号、不改profile的42px或安全矩形、不逐cue改变。负责人已批准，identity包含`ass-alpha-inset-outline-shadow-one-pixel.v1`。
- 薄glyph未必有完全不透明的primary RGB内点；实际颜色检查采用受控fill/outline抗锯齿颜色线段与最低可见对比，不把字体边缘灰度误判为错误颜色，也不忽略半透明异色像素。

## 开发者验证（2026-10-24，尚非负责人accepted）

- 定向：`python -m pytest tests/subtitle_rendering/test_fonts.py tests/subtitle_rendering/test_ass.py tests/subtitle_rendering/test_pixel.py -q`：**116 passed**。默认全部使用fake字体bytes/tables/measurer与fake RGBA，不读取系统字体或启动真实工具。
- 同树完整离线：`python -m pytest tests/ -q`：**2022 passed / 5 skipped**；此为开发者自测，负责人仍须独立复验。
- 字体缺失/hash/face/family/style/glyph、同family另一face、PS映射歧义/未知/不同文件、实际fallback与缺日志均受控失败。
- 字节确定性、样式/投影时间/visual offsets、反斜线/大括号/HTML类正文、恶意override、独立libass文本语法模型枚举2401组四字符序列、不同/缺失/重复断行日志、透明空帧/安全边界/异色/样式倒序/错误几何均有回归。
- 实际640×360四行descender scratch：原margin45时alpha半开bbox为`(281,216,349,319)`，增加固定1px后为`(281,215,349,318)`，safe bottom仍318；后者与双行cue通过实际preflight。保留文件：`/private/tmp/sr03-alpha-inset-d8ht4qi5/probe.ass`。
- 实际分辨率scratch：`/private/tmp/sr03-resolution-descenders-ei6d0yb1/{320,640,1280}.ass`，均使用真实字体与FFmpeg/libass；320×180的两cue bottom159/157（safe159）、640×360为317/314（safe318）、1280×720为636/629（safe636）。半开坐标统一，不是inclusive/exclusive误差。
- **实际literal显示对抗证据**：`/private/tmp/sr03-literal-display-proof-2b6hwcsj/literal.ass`、同目录`ffmpeg.log`、`frame.rgba`、`literal-display.png`。源英文为`literal \\N \\n \\h {x} {\\pos(1,2)} <b>text</b> \\\\`；agent已查看实际像素图，literal反斜线、大括号、pos及HTML类正文均可见且保持同一英文行，没有换行/定位/HTML样式注入。实际RGBA SHA-256为`0eb75c1027f0d2a73c3b22ab9b1ebe689cd1049280a79fb717c1dd917e34c5d1`，bbox`(133,264,509,317)`，总两行、实际face与颜色通过。
  复验可直接调用`FfmpegRenderer(executable='/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg').render_transparent_frame(<上述ASS绝对路径>,'/System/Library/Fonts',640,360,660)`；使用libass0.17.5、FFmpeg9.0.1，帧通过pipe返回，不需写图片。
- 真实CNBC源plan全部163cue仅做内存字体/确定性layout可行性检查：41个四行cue、最大测量高度127px、宽575px；工具identity仅为该实验占位，**未发布production plan、未编码样片，不能当真实集成验收**。全163实际像素、正式来源链、成片与零写复用仍由SR-07验收。
- 未写正式output、未复制字体、未删除文件；非正式scratch残留均保留。根/模块状态由负责人最终验收后统一更新。

## 负责人验收（2026-10-24 00:40 CST）

已审精确字体bytes/face/PS唯一映射、版本身份、纯文本scanner/完整ASS回读、逐cue实际pixel QA和固定alpha内缩。负责人查看literal实际图，反斜线/大括号/HTML类似正文显示符合预期；独立复验116 passed、完整2022 passed / 5 skipped（6.23s），diff check通过。SR-03 accepted，放行SR-05；完整样片与全量实际像素仍待SR-07。

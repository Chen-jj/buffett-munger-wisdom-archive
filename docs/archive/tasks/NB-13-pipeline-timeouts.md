# NB-13 全帧 PTS 扫描超时修复

状态：按用户复核收窄范围，已通过离线验收（2026-11-24）。依赖 [ADR-0014](../decisions/0014-pipeline-timeouts.md)。

保留 `media_boundary.py` 的全帧扫描修复及对应离线测试。实现子 agent 审核 `8a487a3` 与工作区差异，恢复上一轮在其他环节改过的时限、配置和测试。在 `tests/orchestration/integration/offline/test_public_facades.py` 保留慢扫描用例，撤回对派生编码时限的变更。

定向执行 `python -m pytest tests/media_download/test_media_boundary.py tests/orchestration/integration/offline/test_public_facades.py -q -m 'not live'`。模拟 301 秒扫描应生成正确的帧时间和哈希，复用原下载。负责人独立运行全套离线测试并确认剩余生产 diff 仅涉及全帧扫描。禁止删除文件、真实联网、模型下载、外发、渲染、提交和推送。

## 验收记录

- 历史证据在本地 `output/cnbc-2020-coco-full-20261117/`。Part1 和 Part2 的 `*-media_download-20261117T051750080408Z.json` 和 `*-media_download-20261117T061347481698Z.json` 分别记录 300 秒超时。后续两阶段回执均记录 `succeeded`、`download_calls: 0` 和一个新增工件。保存的实际帧时间戳分别为 226,698 和 255,943 个。
- [慢扫描离线回归](../../../tests/orchestration/integration/offline/test_public_facades.py)经公开下载入口复现旧实现的 exit 124。修复后模拟耗时 301 秒的扫描仅新增 `media_boundary.json`，校验不等距 PTS、视频哈希以及旧文件的字节和修改时间。负责人另从公开编排入口验证，首次 `media_download` 为 `succeeded` 且下载调用为 0，第二次 `reused` 且无新增子进程调用。
- 收窄后定向 **43 passed**。负责人独立运行 `.venv/bin/python -m pytest tests/ -q -m 'not live'`，结果为 **2874 passed / 1 skipped / 6 deselected**。对照 `8a487a3`，其余超时实现与配置均一致。真实长片、provider 请求和烧录未重跑。

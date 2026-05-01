# Index-TTS 吞字修复计划（A+B+Compose 守卫）

## Summary
- 本轮目标：修复 `Index-TTS` 在 Auto Dubbing 中的“句尾被硬切 / 吞字 / strict 模式尾音丢失”，不改外部 `index-tts-1108` 模型源码。
- 范围锁定为：`A + 修正版 B + compose 前超窗守卫`。
- 先做计划落档和本地 checkpoint，再等用户确认后实施；checkpoint 以当前工作区状态为基线，包含现有未提交的 `Index-TTS` 改动，不包含运行时垃圾文件如 `index_tts_api.pid`。

## Pre-Implementation
- 新建目录 `docs/plans/`，将本计划存档为 `docs/plans/0001-index-tts-timing-fix-2026-05-02.md`。
- 本地 checkpoint commit 在当前分支 `codex/docs-and-ui-sync-20260427` 上创建，基于当前工作区：
  - 纳入：`src/subtitle_maker/backends/index_tts.py`、`tests/test_dubbing_runtime.py` 以及本次新增计划文档。
  - 排除：`index_tts_api.pid` 和其他运行时临时文件。
- checkpoint commit 只作为“回滚锚点”，不包含本轮正式修复实现。

## Key Changes
- `src/subtitle_maker/domains/dubbing/pipeline.py`
  - 将现有仅对 `OmniVoice` 生效的 `fit_timing_skip_tail_preserve` / strict 尾部保护扩展到 `Index-TTS`。
  - 对 `Index-TTS` 单句和 grouped 路径统一采用“阈值内保留自然尾音，不再强制 fit”的策略。
  - 在进入 `compose_vocals_master()` 前增加显式守卫：若候选音频 `actual_duration_sec > effective_target_duration_sec + 0.03s`，不得以 `done` 进入拼轨；改为结构化失败或 `manual_review`，避免后续静默裁尾。
  - 记录结构化观测字段，明确区分原始 TTS 时长、trim 后时长、fit/atempo 后时长、被 compose 守卫拦截的超窗量。
- `src/subtitle_maker/domains/dubbing/alignment.py`
  - `trim_silence_edges()` 的默认 `pad_sec` 从 `0.03` 提升到 `0.08`。
  - 保持 `threshold_db=-35` 不变，第一版先只放宽 padding，不同时改两个灵敏度维度，降低回归风险。
  - 不修改 `fit_audio_to_duration()` / `trim_audio_to_max_duration()` 的主算法，只让它们更少被误触发。
- `src/subtitle_maker/backends/index_tts.py`
  - 显式消费 Index-TTS API 已返回的 `duration_sec`，把它纳入客户端质量反馈。
  - 为 `Index-TTS` 增加内部质量门控：
    - 输出明显短于目标窗口：允许一次重试。
    - 输出明显长于 `effective_target_duration_sec`：允许一次重试；仍超窗则交给上游守卫拦截，不直接放行为 `done`。
  - 质量反馈只用于后端内部决策和日志，不新增前端开关，不改 Web API 入参。

## Public Interfaces / Behavior
- 不新增前端参数，不改 Web 端表单，不改 CLI 对外参数。
- `Index-TTS` 服务端现有 `/synthesize` 响应格式保持兼容；客户端只是开始真正使用已存在的 `duration_sec` 字段。
- 行为变化：
  - `Index-TTS` 在 strict 模式下不再默认对小幅超窗音频做硬 fit。
  - 明显超窗的 `done` 音频不再静默进入 compose 并被二次裁尾。

## Test Plan
- 单元测试：
  - `Index-TTS` 命中 strict 阈值时走“skip tail preserve”，不进入 `fit_audio_to_duration()`。
  - `trim_silence_edges()` 新 padding 下保留轻声首尾，不出现首字/尾字被误裁的回归。
  - `Index-TTS` API 返回的 `duration_sec` 能驱动“过短 / 过长”质量判定与最多一次重试。
  - compose 前超窗守卫会阻止超长候选以 `done` 状态进入拼轨。
- 回归测试：
  - `tests/test_dubbing_runtime.py`
  - `tests/test_index_tts_fastapi_server.py`
  - 与 dubbing pipeline 相关的现有 timing / compose 测试
- 手工验收：
  1. 选择已有会吞尾字的 `Index-TTS` 样本重跑。
  2. 核对日志里 `tts -> trim -> fit/skip -> compose guard` 的完整链路。
  3. 抽听短句、轻声句、最后一句，确认不再被硬切尾。
  4. 确认没有把明显超窗音频错误标成 `done`。

## Assumptions
- 第一版不改外部 `../index-tts-1108/indextts/infer_v2.py`，不使用 `interval_silence` 做“语速控制”。
- 第一版不改 `concat_generated_wavs()` 的拼接策略，边界听感优化留待后续独立处理。
- 若实施前工作区出现新的未提交代码改动，先复核是否应纳入 checkpoint；若与本计划无关，则不混入本轮实现。

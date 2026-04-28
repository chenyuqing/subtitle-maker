# Auto Dubbing V2 OmniVoice 状态

日期：2026-04-28

## 本次结论

当前 `OmniVoice` 链路相较前一版已经明显稳定，最新一次前端实测任务没有出现 `missing`、`manual_review` 或外层脚本秒退。

这次效果改善的主要原因不是单个参数微调，而是接入策略一起收紧了：

- `OmniVoice` 任务会在运行时强制开启短句合并，避免极碎句直接送进模型。
- `OmniVoice` 优先使用更稳的 reference 策略，并对过短 reference 做回退。
- `<1.2s` 的危险目标时长会在 pipeline/backend 两层被拦住，不再白跑一次合成。
- 配音产物在段级落盘前会做统一音量归一，降低忽大忽小的问题。

## 已落地策略

### 1. 短句合并对 OmniVoice 强制生效

- `source` 链路：`tools/dub_pipeline.py::resolve_source_short_merge_policy()`
- `translated` 链路：`tools/dub_long_video.py::resolve_translated_short_merge_policy()`

当前语义是：

- 用户请求态仍保留在 manifest 中，不被运行时策略污染。
- 只要主底座是 `omnivoice`，`effective_*_short_merge_enabled` 就会强制为 `true`。
- 日志会明确记录 `requested/effective/reason=omnivoice_policy`。

### 2. OmniVoice reference 策略改为更保守

- 入口：`tools/dub_pipeline.py::build_backend_reference_selector()`

当前语义是：

- `tts_backend=omnivoice` 时优先走 `shared_reference_preferred_for_omnivoice`。
- 逐句 `subtitle_XXXX_ref.wav` 只有在 reference 时长满足安全阈值时才启用。
- reference 策略和计数会打进 segment 日志，便于排查“到底用了 shared ref 还是 subtitle ref”。

### 3. 过短目标时长会被前置拦截

- backend guard：`src/subtitle_maker/backends/omni_voice.py::_validate_request()`
- pipeline precheck：`src/subtitle_maker/domains/dubbing/pipeline.py::_is_omnivoice_target_duration_unsafe()`

当前语义是：

- 对 `tts_backend=omnivoice`，若 `effective_target_duration_sec < 1.2s`，会直接进入 `manual_review/missing` 协议。
- 逐句路径打 `segment_tts_precheck_rejected`。
- grouped 路径打 `group_tts_precheck_rejected`。
- 专用原因码为 `omnivoice_target_duration_below_safe_floor`，错误码为 `E-TTS-001`。

### 4. 段级音量归一已接入

从最新 segment manifest 和段日志可见，配音产物在最终落地前会记录：

- `audio_leveling_applied`
- `audio_leveling_target_rms`
- `audio_leveling_input_rms`
- `audio_leveling_output_rms`
- `audio_leveling_gain_db`

这层目标是先把“同一批配音忽大忽小”的问题收敛到可控范围。

## 最新实测证据

本次验证任务：

- batch：`outputs/dub_jobs/web_20260428_015019/longdub_20260428_095022`
- segment log：`outputs/dub_jobs/web_20260428_015019/longdub_20260428_095022/segment_jobs/segment_0001/logs/segment_0001.jsonl`
- segment manifest：`outputs/dub_jobs/web_20260428_015019/longdub_20260428_095022/segment_jobs/segment_0001/manifest.json`
- OmniVoice 服务日志：`outputs/omnivoice_api.log`

关键信号：

- `source_layout_rebalanced` 显示 `before_count=26`、`after_count=3`、`short_sentence_merges=11`，并且 `short_merge_effective_reason=omnivoice_policy`。
- `segment_0001` 最终状态是 `done=3 failed=0 manual_review=0`。
- `outputs/omnivoice_api.log` 显示这次真实发起并完成了 3 个合成请求，没有 `failed`。
- 3 条成品都写入了音量归一记录，说明统一音量链路已经参与生产路径。

最终产物已确认存在：

- `final/dubbed_mix_full.wav`
- `final/dubbed_vocals_full.wav`
- `final/dubbed_final_full.srt`
- `final/translated_full.srt`

## 当前仍需继续观察

### 1. 音量上限是否过紧

这次 3 条句子的 `audio_leveling_gain_db` 都打到了 `8.0dB` 上限。说明归一策略已经工作，但也说明原始输出整体偏小，后续还要继续观察：

- 上限是否需要放宽；
- 目标 `RMS` 是否需要继续调；
- 是否会出现“相对一致了，但整体还是偏小”的情况。

### 2. 最终视频封装层

本次 batch 目录已确认生成最终 `wav/srt`，但未在同目录下看到最终 `mp4`。如果前端后续仍在“处理中”或没有视频成品，下一步应排查：

- batch 收尾导出；
- 前端任务状态刷新；
- 最终视频路径回写。

### 3. OmniVoice 听感仍需持续回归

这次日志说明“稳定性”已经比之前好，但日志本身不能证明语义内容完全正确。后续仍要继续听感回归这几类句子：

- 高密度长句；
- 跨语言 voice clone；
- reference 本身语气起伏大的句子；
- 借了较长 `borrowed_gap_sec` 才落进安全区的句子。

## 当前判断

现在的 OmniVoice 问题，已经从“经常 missing、经常秒退”转成了“推理较慢、听感还要继续优化、收尾视频导出层待确认”。这说明主问题已经不再是底座接入崩溃，而是进入了质量和产品收尾阶段。

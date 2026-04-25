# 当前架构 Review

日期：2026-04-24

## 总结

当前项目已经从“字幕生成工具”演进到“字幕 + 翻译 + 自动配音 + 长视频批处理 + Review/Redub”的产品形态，但代码组织仍主要是脚本式增长。

主要风险不是某个函数写得不好，而是产品域边界不清：Web API、任务状态、字幕处理、媒体处理、配音合成、manifest、前端状态混在少数大文件中。

## 现状依据

| 结论 | 代码依据 |
|---|---|
| 单段配音 pipeline 是多职责大文件 | `tools/dub_pipeline.py`，`load_or_transcribe_subtitles()`、`rebalance_source_subtitles()`、`translate_batch_with_budget()`、`synthesize_segments()`、`build_manifest()`、`main()` 分别承担字幕、翻译、TTS、manifest、CLI 主流程。 |
| 长视频编排和合并耦合 | `tools/dub_long_video.py`，`run_segment_job()` 负责子任务，`build_full_timeline_vocals()` / `merge_srt_files()` / `main()` 同时负责最终合并和 batch manifest。 |
| Auto Dubbing API 混合任务状态、CLI、artifact、review | `src/subtitle_maker/dubbing_cli_api.py`，`_tasks` / `_run_cli_task()` / `_complete_task_from_manifest()` / `_collect_review_lines()` / `_rerun_segment_with_translated_srt()` 位于同一文件。 |
| 普通 Web API 也承担过多职责 | `src/subtitle_maker/web.py`，`transcribe_task()`、`/translate`、`/export`、`/model/*`、`/project/reset`、`/segment` 混在主 app 文件。 |
| 前端状态集中在单文件 | `src/subtitle_maker/static/app.js`，上传、播放器、字幕、翻译、Auto Dubbing V1/V2、review、sidebar 状态都在一个脚本里。 |
| 依赖没有区分 Web 和模型运行时 | `pyproject.toml` 同时包含 FastAPI、OpenAI client、torch、torchaudio、qwen-asr、demucs、onnxruntime。 |

## 主要问题

### 1. Manifest 和参数协议分散

相关位置：

- `tools/dub_pipeline.py`：`build_manifest()`、`build_failure_manifest()`、`parse_args()`。
- `tools/dub_long_video.py`：`parse_args()`、`run_segment_job()`、`main()`。
- `src/subtitle_maker/dubbing_cli_api.py`：`_complete_task_from_manifest()`、`_run_cli_task()`、`_rerun_segment_with_translated_srt()`。

风险：

- 字段默认值不一致。
- 历史 batch load 后丢配置。
- save-and-redub 可能不保留原始 pipeline 语义。
- 新增参数需要同时改多个入口，容易漏。

改进方向：

- 定义 `PipelineOptions`。
- 定义 typed manifest schema。
- 所有 CLI 参数通过 `CommandBuilder` 生成。

### 2. 任务状态不可恢复

相关位置：

- `src/subtitle_maker/dubbing_cli_api.py`：全局 `_tasks` / `_lock`。
- `src/subtitle_maker/web.py`：普通转写任务使用独立任务状态。
- `src/subtitle_maker/streaming_asr.py`：streaming session 又是一套独立状态。

风险：

- 服务重启后运行态丢失。
- 多 worker 不可用。
- 失败恢复依赖扫描文件夹和 manifest。
- 不同任务类型的 cancel/status 语义不一致。

改进方向：

- 引入 `Job` / `Project` / `Artifact`。
- 第一版使用本地 SQLite 或 JSON store。
- 旧 API 兼容 `task_id`，内部映射到新 job。

### 3. 字幕能力没有形成独立领域

相关位置：

- `src/subtitle_maker/transcriber.py`：`format_srt()`、`parse_srt()`、`merge_subtitles()`。
- `tools/dub_pipeline.py`：`split_text_on_punctuation_boundaries()`、`allocate_text_segment_times()`、`merge_short_source_subtitles()`、`rebalance_source_subtitles()`。

风险：

- 上传 source 字幕和 ASR 字幕容易走不同路径。
- 分句/合并规则容易只在某个入口生效。
- 时间戳重估逻辑难复用、难测试。

改进方向：

- 抽 `domains/subtitles/srt.py`。
- 抽 `sentence_split.py`、`short_merge.py`、`timeline.py`。
- 所有 source.srt 都经过同一套 layout pipeline。

### 4. 配音主链路和 TTS backend 耦合

相关位置：

- `tools/dub_pipeline.py`：`load_index_tts_model()`、`synthesize_via_index_tts_api()`、`synthesize_text_once()`、`synthesize_segments()`。
- `tools/index_tts_fastapi_server.py`：Index-TTS 独立服务。

风险：

- 接 OmniVoice 会继续扩大主 pipeline。
- backend 失败和业务失败难区分。
- fallback 规则无法集中管理。

改进方向：

- 定义 `TtsBackend` 接口。
- Index-TTS 和 OmniVoice 以 adapter 接入。
- 主 pipeline 只关心逐句输入、参考音频、输出音频和错误码。

### 5. 前端缺少模块边界

相关位置：

- `src/subtitle_maker/templates/index.html`：多个 panel 共存。
- `src/subtitle_maker/static/app.js`：所有状态和事件在一个文件。
- `src/subtitle_maker/static/style.css`：播放器、sidebar、Auto Dubbing、review 样式混合。

风险：

- UI 改动容易影响其它 panel。
- polling loop、localStorage、上传状态容易互相干扰。
- Agent 入口如果继续塞进 `app.js`，复杂度会继续上升。

改进方向：

- 第一版 Agent 可以先小范围接入。
- 后续拆 `apiClient.js`、`player.js`、`dubbingPanel.js`、`agentDrawer.js`。

## 重构优先级

| 优先级 | 改动 | 理由 |
|---|---|---|
| P0 | 文档和 review | 先统一目标，避免大范围返工。 |
| P1 | Contract/golden tests | 冻结当前行为，保护主链路。 |
| P1 | Manifest / PipelineOptions / CommandBuilder | 解决最容易继续产生回归的字段散落问题。 |
| P1 | Agent V1 | 降低真实使用时的排查成本。 |
| P2 | Subtitle Domain | 直接影响字幕质量和后续配音效率。 |
| P2 | Dubbing Backend 接口 | 为 OmniVoice 备胎和后续模型切换打地基。 |
| P3 | 前端模块拆分 | 降低后续 UI 维护成本。 |

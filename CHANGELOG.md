# Changelog

## [Unreleased] - 2026-04-27

### Fixed
- **Step 2/3 面板可见性回归**: 修复 `#panel-transcribe` 与 `#panel-results` 在样式覆盖下同时显示的问题，恢复为仅激活面板可见（`.active` 约束）。
- **Step 2/3 面板滚动与宽度体验**: 面板改为内部滚动且保持播放器/侧栏固定，并将宽度调整为自适应居中留白（不再贴边）。

## [Unreleased] - 2026-04-19

### Added
- **Auto Dubbing V2 独立入口**: 左侧新增 Step 6「Auto Dubbing V2」，前端状态与轮询逻辑与 V1 隔离，支持并行调试。
- **V2 主链路开关**: `/dubbing/auto/start` 新增 `pipeline_version`，V2 透传 `--v2-mode` 到后端链路。
- **V2 翻译改写开关**: V2 面板新增 `Rewrite translation for timing fit`（默认开启），支持按任务控制是否允许改写以贴时长。
- **Markdown 时间稿字幕支持**: Auto Dubbing 上传字幕新增 `.md`，支持 `[MM:SS]` / `[HH:MM:SS]` 格式并自动转换为 `.srt`。
- **历史结果恢复增强**: 新增 `/dubbing/auto/batches` + `/dubbing/auto/load-batch`，支持下拉选择 `longdub_*` 目录并一键恢复结果。
- **历史结果回载原视频**: 加载批次时回传 `input_media_url`，播放器可直接恢复原视频画面。

### Fixed
- **V2 音轨切换被重置**: 修复 V1/V2 双实例共享音轨选择器时互相覆盖的问题，V2 可正常切换到 dubbed 音轨。
- **区间模式 final 混音缺失 BGM**: 段内未导出 `dubbed_mix` 时，最终合成改为用 `dubbed_vocals + source_bgm` 在线重建 mix，避免听感近似纯人声。
- **V2 全量 manual_review 误报失败**: 在存在可用候选语音时接受最佳折中结果，并记录评分，避免整批直接失败。
- **New Project 上传清理策略**: `uploads/dubbing` 改为保留最新 3 个视频任务目录，其余自动清理。

## [Unreleased] - 2026-04-18

### Added
- **Auto Dubbing 可选字幕文件输入**: Step 5 新增可选 `.srt` 上传；上传后后端自动跳过 ASR，直接进入翻译与配音流程。
- **Auto Dubbing 时间区间复用 Step 2 交互**: Step 5 新增与 Step 2 一致的时间区间输入组件（MM:SS 添加/删除/使用当前时间）。
- **时间区间全时轴替换**: 指定区间配音时，最终 `final` 音频保持完整原视频时长，仅替换选中区间，区间外保持原声。

### Fixed
- **区间配音 final 音频丢失**: 修复全时轴合成时采样率不一致导致区间音频被跳过的问题，改为自动重采样后覆盖。
- **Auto Dubbing 过度压缩导致漏音**: 时长对齐改为“先借后续静音再压缩”；当下一句前存在静音间隔时，优先扩展可用时长，仅在仍超窗时才做变速拟合，降低尾音被压掉的概率。

## [1.2.0] - 2026-02-02

### Added
- **One-Click Auto Dubbing (Step 5)**: A fully automated pipeline that handles Transcription -> Translation -> Dubbing (Source Separation + Voice Cloning + Mixing) in a single action.
- **Auto Dubbing Progress Tracker**: Real-time status polling with stage highlights (Transcribe, Translate, Dub).
- **Manual Model Memory Cleanup**: Added `/model/all/release` endpoint and `clean-model.sh` utility to force unload ASR and TTS models from memory.
- **Port Release Safety**: Improved `stop-dub.sh` to poll and wait until the port is freed, preventing "Address already in use" errors on restart.

### Fixed
- **NameError in web.py**: Fixed missing `get_dubbing_manager` definition after refactor.
- **Language Selector Sync**: Synced "Source Language" options in Auto Dubbing to match the comprehensive list in Step 2 (Cantonese, Italian, Portuguese, etc.).
- **Console Logging**: Reconfigured `start-dub.sh` to output logs directly to terminal for better visibility.
- **Auto Dubbing ASR Cleanup**: Automatically unloads the ASR model after the transcription stage to free up memory for the TTS stage.

### [Unreleased] - 2026-02-01

### Added
- **Standalone SRT Upload Panel**: Separated SRT upload into a dedicated "Import SRT" panel (Step 4) to avoid confusion with video uploads.
- **Player Subtitle Loader**: Added a "Load Subtitles" (📂) button in the video controls bar to instantly overlay local SRT files onto the video.
- **Custom System Prompt**: Added a text area in the translation panel to allow users to provide custom system prompts for the translation model (e.g., "Translate to Cantonese").
- **Local Model Integration**: Added support for `Sakura-14b` local model via `llama.cpp` using the `local_sakura` provider option.
- **State Persistence**: Enhanced `localStorage` implementation to persist original and translated subtitles. Data now survives page refreshes even if the backend restarts.
- **Time Range Selection for ASR**: Added support to specify multiple time ranges for transcription. Users can now select specific segments to transcribe instead of the entire video. Features include: overlap detection, boundary validation, "Use Current" button to quickly add ranges from playback position.

### Fixed
- **Upload Click/Drag Issues**: Resolved event bubbling conflicts in the upload area that prevented clicking or dragging files after the first attempt.
- **Video Placeholder Visibility**: Fixed an issue where the "Select a video" placeholder remained visible after loading a video or SRT file.
- **Local Translation Error Handling**: Updated `translator.py` to return full exception details (e.g., Connection Refused) to the frontend instead of a generic "[Translation Error]" message.
- **Overlay Positioning**: Adjusted subtitle overlay position to prevent blocking the video progress bar.
- **Fullscreen Subtitles**: Fixed Z-Index issue where video covered subtitles in fullscreen mode.
- **Concurrency Safety**: Added server-side thread locking to prevent race conditions during model loading.
- **Non-Blocking Translation**: Moved translation logic to a threadpool to prevent blocking the main event loop.
- **UI State**: Fixed issue where old subtitles persisted after uploading a new video.
- **Export Reliability**: Fixed "400 Bad Request" on export by allowing the frontend to send subtitle data directly if the backend session has expired or restarted.
- **Translation Stability**: Implemented batch processing (chunk size 30) to prevent API timeouts or empty results on long videos.
- **Filename Preservation**: Fixed issue where exported files used internal UUIDs instead of the original video filename.
- **Subtitle Parsing**: Fixed issue where multi-line SRTs were parsed as single lines.
- **UI Adjustments**: 
    - Implemented dynamic subtitle positioning (20px -> 50px on hover).
    - Added "Top/Bottom" position selector in video controls (10px from top).
    - Changed "Fullscreen" button behavior to **Web Page Fullscreen** (expands player to window size) to ensure subtitles remain visible (fixes native fullscreen z-index issues).
- **Player Controls**: Fixed unresponsive "Load Subtitles" button.

### Changed
- **UI Layout**: Split the "Upload" panel into "Upload Video" (Panel 1) and "Import SRT" (Panel 4).
- **Backend**: `/translate` endpoint now accepts `system_prompt` and `model_provider` parameters.

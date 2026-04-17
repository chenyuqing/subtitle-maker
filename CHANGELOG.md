# Changelog

## [Unreleased] - 2026-04-18

### Added
- **Auto Dubbing 可选字幕文件输入**: Step 5 新增可选 `.srt` 上传；上传后后端自动跳过 ASR，直接进入翻译与配音流程。
- **Auto Dubbing 时间区间复用 Step 2 交互**: Step 5 新增与 Step 2 一致的时间区间输入组件（MM:SS 添加/删除/使用当前时间）。
- **时间区间全时轴替换**: 指定区间配音时，最终 `final` 音频保持完整原视频时长，仅替换选中区间，区间外保持原声。

### Fixed
- **区间配音 final 音频丢失**: 修复全时轴合成时采样率不一致导致区间音频被跳过的问题，改为自动重采样后覆盖。

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

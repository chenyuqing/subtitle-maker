# Changelog

## [Unreleased] - 2026-02-01

### Added
- **Standalone SRT Upload Panel**: Separated SRT upload into a dedicated "Import SRT" panel (Step 4) to avoid confusion with video uploads.
- **Custom System Prompt**: Added a text area in the translation panel to allow users to provide custom system prompts for the translation model (e.g., "Translate to Cantonese").
- **Local Model Integration**: Added support for `Sakura-14b` local model via `llama.cpp` using the `local_sakura` provider option.
- **State Persistence**: Enhanced `localStorage` implementation to persist original and translated subtitles. Data now survives page refreshes even if the backend restarts.

### Fixed
- **Upload Click/Drag Issues**: Resolved event bubbling conflicts in the upload area that prevented clicking or dragging files after the first attempt.
- **Video Placeholder Visibility**: Fixed an issue where the "Select a video" placeholder remained visible after loading a video or SRT file.
- **Local Translation Error Handling**: Updated `translator.py` to return full exception details (e.g., Connection Refused) to the frontend instead of a generic "[Translation Error]" message.
- **Overlay Positioning**: Adjusted subtitle overlay position to prevent blocking the video progress bar.
- **Fullscreen Subtitles**: Fixed Z-Index issue where video covered subtitles in fullscreen mode.
- **Concurrency Safety**: Added server-side thread locking to prevent race conditions during model loading.
- **Non-Blocking Translation**: Moved translation logic to a threadpool to prevent blocking the main event loop.
- **UI State**: Fixed issue where old subtitles persisted after uploading a new video.
- **SRT Upload Workflow**: Fixed "Translate" and "Export" buttons remaining disabled after direct SRT upload.

### Changed
- **UI Layout**: Split the "Upload" panel into "Upload Video" (Panel 1) and "Import SRT" (Panel 4).
- **Backend**: `/translate` endpoint now accepts `system_prompt` and `model_provider` parameters.

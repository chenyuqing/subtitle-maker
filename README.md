# Subtitle Maker (Local AI)

一个基于 Qwen3-ASR 和 DeepSeek API 的本地视频字幕生成与翻译工具。专为 Mac (Apple Silicon) 优化，支持实时预览、双语字幕导出和内存自动管理。

## ✨ 主要功能

*   **本地转写**: 使用 `Qwen3-ASR` 模型进行高精度语音识别，无需上传音频，保护隐私。
*   **Mac 优化**: 支持 MPS (Metal Performance Shaders) 加速，在 Mac 上运行高效。
*   **长视频支持**: 采用分块处理机制，支持长视频转写，内存占用稳定。
*   **AI 翻译**: 集成 DeepSeek API，支持将字幕翻译为多种语言。
*   **灵活导出**: 支持导出 SRT 字幕文件，可选原文、译文或双语对照格式。
*   **实时预览**:
    *   转写过程中实时显示生成字幕。
    *   视频播放器支持叠加层切换：原文、译文、双语（原+译 / 译+原）。
*   **内存安全**: 任务结束后自动释放 AI 模型内存，防止系统卡顿。

## 🛠️ 环境要求

*   **OS**: macOS (推荐 M1/M2/M3/M4 芯片)
*   **Python**: 3.10+ (推荐使用 `uv` 管理)
*   **FFmpeg**: 用于音频处理
*   **内存**: 建议 16GB RAM 或以上

## 🚀 快速开始

### 1. 安装依赖工具

```bash
# 安装 uv (Python 包管理器)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 安装 ffmpeg
brew install ffmpeg
```

### 2. 初始化项目

```bash
# 进入项目目录
cd subtitle-maker

# 安装项目依赖
uv sync
```

### 3. 运行服务

使用一键启动脚本：

```bash
./start.sh
```

脚本会自动：
1.  检查环境依赖。
2.  启动 Web 服务 (端口 8000)。
3.  自动在浏览器打开 `http://localhost:8000`。
4.  如果端口被占用，会提示是否清理。

### 4. 停止服务

```bash
./stop.sh
```

## 📂 模型文件

项目默认使用以下模型（需自行下载放置在 `models/` 目录）：
*   `models/Qwen3-ASR-0.6B`
*   `models/Qwen3-ForcedAligner-0.6B`

## 💡 使用指南

1.  **上传视频**: 在首页上传需要制作字幕的视频文件。
2.  **开始转写**: 点击 Transcribe，等待本地模型处理。
3.  **字幕预览**: 
    *   转写完成后，字幕会自动显示。
    *   使用视频下方的 **Overlay** 下拉菜单切换显示模式（如：`Original + Translation`）。
4.  **翻译 (可选)**:
    *   输入 DeepSeek API Key。
    *   选择目标语言，点击 Translate。
5.  **导出**:
    *   选择需要的格式（如 Bilingual），点击 Export 下载 `.srt` 文件。

## ⚠️ 注意事项

*   首次运行时会加载模型，可能需要几秒钟。
*   转写和翻译任务结束后，内存会自动释放。如果再次操作，模型会重新加载。

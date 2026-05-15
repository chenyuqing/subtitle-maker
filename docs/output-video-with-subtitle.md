# FFmpeg 烧录 ASS 字幕到 MP4

本文记录项目当前使用的 ASS 烧录方式，以及 5 号面板 final 结果的相关产物。

## 1. 基本命令

```bash
ffmpeg -i input.mp4 -vf "ass='subtitles.ass'" -c:v libx264 -crf 16 -preset slow -c:a copy output.mp4
```

项目里 5 号面板 final 的 Python 封装本质上就是执行这条命令，另外会补上 `-y` 和 `-movflags +faststart`。

## 2. 先检查 ffmpeg 是否支持 ass 过滤器

```bash
ffmpeg -filters | grep ass
```

如果能看到 `ass` filter，说明当前 ffmpeg 构建包含 `libass`，可以直接烧录 ASS 字幕。

## 3. 如果当前 ffmpeg 不支持 ass

- macOS：`brew install homebrew-ffmpeg/ffmpeg/ffmpeg`
- Ubuntu：先安装 `libass-dev`，再重新编译 ffmpeg
- Windows：下载包含 `libass` 的静态构建版本

## 4. 参数说明

- `-vf`：给视频流挂滤镜。
- `ass='subtitles.ass'`：使用 libass 渲染 ASS 字幕。
- `-c:v libx264`：视频重新编码为 H.264。
- `-crf 16`：恒定质量模式，数值越小画质越高、文件越大。
- `-preset slow`：编码更慢，但压缩效率更高。
- `-c:a copy`：音频直接拷贝，不重新编码。

## 5. 如何调整 ASS 字体大小

在 ASS 文件的 `[V4+ Styles]` 段中修改 `Fontsize` 字段即可。

项目当前固定样式示例：

```ini
Style: Default,PingFang SC,80,&H00FFFFFF,&H000000FF,&H00000000,&H99000000,-1,0,0,0,100,100,0,0,4,0,0,2,80,80,80,1
```

建议：

- 1080p 视频常用范围是 `72-84`
- 项目当前 5 号面板 final 样式固定使用 `80`

## 6. libx264 与 Mac VideoToolbox 的取舍

`libx264` 优点：

- 画质更稳
- 参数可控性高
- 烧录字幕后的兼容性更好

`libx264` 缺点：

- 速度通常慢于硬件编码

`h264_videotoolbox` 优点：

- 在 Mac 上通常更快
- 更省 CPU

`h264_videotoolbox` 缺点：

- 同码率下画质通常不如 `libx264`
- 某些素材上参数细粒度不如软件编码

如果只是追求稳定和最终质量，项目当前优先使用 `libx264`。如果后续要做更快的预览型输出，可以再评估 `h264_videotoolbox`。

## 7. 完整示例流程

假设你有 `lecture.mp4` 和 `lecture.ass`：

1. 先检查 `ass` 过滤器是否可用

```bash
ffmpeg -filters | grep ass
```

2. 打开 `lecture.ass`，把 `Fontsize` 改成 `80`

3. 执行烧录

```bash
ffmpeg -i lecture.mp4 -vf "ass='lecture.ass'" -c:v libx264 -crf 16 -preset slow -c:a copy lecture_burned.mp4
```

4. 播放 `lecture_burned.mp4` 检查效果

## 8. 项目里的 final 产物

5 号面板任务完成后，`final/` 目录当前会生成：

- `dubbed_final_full.srt`
- `dubbed_final_full-styled.ass`
- `dubbed_video_full.mp4`
- `dubbed_video_full_burned.mp4`

其中：

- `dubbed_video_full.mp4` 是替换配音音轨后的成片
- `dubbed_video_full_burned.mp4` 是在上一步基础上烧录 ASS 字幕后的成片

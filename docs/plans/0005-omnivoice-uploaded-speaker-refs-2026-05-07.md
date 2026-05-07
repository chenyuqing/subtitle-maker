# OmniVoice 上传 speaker 参考音方案

## Summary
- 保留 `4. Auto Dubbing` 现有 `index-tts` 链路不动。
- `5. Auto Dub Omnivoice` 改为 strict 多 speaker 参考音上传模式。
- speaker 归属继续直接来自当前项目字幕中的 `speaker_id / Speaker X:`。
- 每个 speaker 的参考音由用户上传，统一绑定固定参考文本：
  - `你好，这是我的声音音色，很高兴为你进行配音服务。`

## Key Changes
- 前端
  - 5 号面板新增 speaker 参考音上传区。
  - 自动根据当前项目字幕渲染 speaker 列表与上传槽位。
  - 启动请求新增 `speaker_ref_files[]` 和 `speaker_ref_speaker_ids_json`。
  - strict 校验：检测到几个 speaker，就必须上传几份参考音。

- 后端
  - `/omnivoice/auto/start-from-project` 接收上传参考音列表和 speaker id 列表。
  - 保存上传文件，构造 `speaker_id -> {ref_audio, ref_text}` 映射。
  - 生成阶段优先使用上传参考音，不再把“自动聚合原视频 speaker refs”作为默认主路径。
  - 第一版 strict 模式下，缺任一 speaker 参考音直接报错，不静默回退。

- 可观测性
  - `speaker_ref_map.json` 增加 `reference_mode=uploaded_strict`。
  - manifest / task 输出保留 speaker ids 和参考音路径，便于回放定位。

## Test Plan
- `node --check src/subtitle_maker/static/js/omnivoiceDubbingPanel.js`
- `uv run python -m py_compile src/subtitle_maker/omnivoice_dub_api.py`
- 前端验证：
  - 5 号面板根据字幕显示 speaker 上传列表
  - 少传任一 speaker 时阻止启动
- 后端验证：
  - 上传参考音后输出目录落下 `speaker_ref_map.json`
  - 生成链路使用上传参考音路径

## Assumptions
- 第一版不允许部分 speaker 上传、部分自动聚合混用。
- 固定 `ref_text` 对所有上传 speaker 一致，不在前端暴露可编辑输入。
- 当前轮只改 5 号 OmniVoice，不改 4 号 `index-tts`。

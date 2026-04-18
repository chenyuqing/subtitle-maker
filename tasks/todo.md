# TODO

- [x] 明确现状与不回归边界（默认单人）
- [x] Auto Dubbing 前端新增 Speaker Mode 开关（默认 single-speaker）
- [x] /dubbing/auto/start 接口透传 speaker_mode 到 CLI
- [x] dub_pipeline 放开 speaker_mode 硬报错并保持单人默认行为
- [x] 任务状态与结果中记录 speaker_mode 便于排查
- [x] 语法校验与最小回归检查

## Review
- 2026-04-16：已完成多人模式“增量开关”接入，默认单人链路保持不变。
- 前端可选 single-speaker / auto / per-speaker；第一阶段曾采用降级保护，后续已切到非单人真实执行（预览策略）。
- 已通过 `py_compile`（`dubbing_cli_api.py`、`dub_pipeline.py`）与 `node --check`（`app.js`）校验。
- 2026-04-16（继续）：已实现非单人模式真实执行路径（不再统一降级），采用“多参考音色 + 时间分桶分配”策略，默认单人路径不变。
- 非单人当前为预览能力：默认抽取 2 个参考音色并按字幕时间段分配；无额外 diarization 模型依赖。
- 2026-04-16（修正）：已移除主流程中的强制单人回落，`speaker_mode=auto/per-speaker` 现在会进入预览多人策略执行。
- 2026-04-16（剃刀化）：非单人改为“每条字幕直接切原人声音频作为克隆+情绪参考”，并在段落结束后删除 `_tmp_ref/*.wav`，避免磁盘累积。
- 2026-04-16（继续）：已接入简易 diarization（MFCC + KMeans）输出 speaker_id + time range，并将字幕按时间重叠绑定到 speaker，再按 speaker 参考音色逐句合成。

## 2026-04-16 多人说话人分离升级（调研 -> 方案 -> 实施）

- [x] 现状审计：定位当前算法与失败根因（带代码出处）
- [x] 在线调研：对比 pyannote / WhisperX / NeMo 方案
- [x] 方案确认：给出最小影响接入路径与回退策略（等确认）
- [x] 实施：接入 diarization provider（默认 simple，不破坏旧功能）
- [x] 验证：用 `test-0003-multi-person.mp4` 产出可核对日志与结果
- [x] 收尾：更新任务 review 与 lessons

## Review（2026-04-16 diarization 升级）
- 已将多人模式默认 diarization 路径改为 `pyannote/speaker-diarization-community-1`，并保留 `simple` 自动回退。
- 已在 `dubbing_cli_api.py` 的 Web 命令拼装中默认透传 `--diarization-provider auto --pyannote-model ...`。
- 已新增本地模型来源解析：优先绝对路径，其次本地 HF cache，再回退模型 ID。
- 已新增“外部 Python 隔离执行 pyannote”路径（`--pyannote-python-bin`），用于规避主项目 `torchaudio==2.3.1` 与 community-1 的版本冲突。
- 校验证据：`uv run python -m py_compile tools/dub_pipeline.py src/subtitle_maker/dubbing_cli_api.py` 通过。
- 校验证据：`uv run python tools/dub_pipeline.py --help` 已显示新增参数（provider/model/token/device）。
- 校验证据：`tools/pyannote_diarize_worker.py` 在 `index-tts-1108/.venv` 下对 `test-0003-multi-person.mp4` 抽取音频后输出 `17` 个 diarization 段、2 个 speaker（见 `outputs/diag_test/pyannote_segments.json`）。

## 2026-04-16 community-1 单模验证（不做集成）

- [x] 单独运行 `pyannote/speaker-diarization-community-1`
- [x] 验证其原始输出是否为“按句切割”
- [x] 对比字幕时间戳，判断是否可映射到“一人一句”
- [x] 记录结论与限制

## Review（2026-04-16 community-1 单测）
- 单独运行 `community-1` 于 `test-0003-multi-person.mp4` 抽出的 `outputs/diag_test/test3.wav`，得到 `17` 个 speaker turn、`2` 个 speaker。
- 原始输出不是“句子切割”，而是“说话人时间段切割”；`regular` 与 `exclusive` 在该样本上段数相同。
- 将现有 `source.srt` 合并为 `9` 句后，按时间重叠映射 speaker，可得到“每句一个 speaker”的稳定结果：第 1 句为 `SPEAKER_00`（置信约 `0.79`），其余 8 句为 `SPEAKER_01`（置信 `1.00`）。
- 结论：`community-1` 单独不能直接输出“一人一句”的句级切割；但配合句子时间戳后，可以给每句分配稳定 speaker。

## 2026-04-17 配音语音对齐重构（strict + balanced）

- [x] 完成第一性原理分析并确认目标函数（可懂度与语速稳定优先）
- [x] 在 `dub_pipeline` 新增 `--timing-mode`，默认 `strict` 保持兼容
- [x] 新增 `balanced` 组内均衡分配（文本负载 + 最小时长约束）
- [x] grouped 分支接入 `balanced` 切片合成，保留 `strict` 原行为
- [x] Web `/dubbing/auto/start` 透传 `timing_mode`（默认 strict）
- [x] 增加接口单测并完成语法与回归验证

## Review（2026-04-17 对齐重构）
- 已在 `tools/dub_pipeline.py` 增加参数：`--timing-mode strict|balanced`（默认 strict）、`--balanced-max-tempo-shift`、`--balanced-min-line-sec`。
- `strict` 路径保持原逻辑；`balanced` 仅在 grouped 合成路径启用“组内均衡切分”，降低逐句硬贴时长导致的语速波动。
- `balanced` 新增三项核心函数：`estimate_line_speech_weight`、`allocate_balanced_durations`、`apply_short_fade_edges`；用于负载估计、时长分配与切点平滑。
- `src/subtitle_maker/dubbing_cli_api.py` 已支持 `timing_mode` 入参并透传到 CLI，默认仍为 `strict`，不影响现有调用。
- `tests/test_dubbing_cli_api.py` 已新增 `timing_mode` 相关断言与非法参数用例。
- 校验通过：`uv run python -m py_compile tools/dub_pipeline.py src/subtitle_maker/dubbing_cli_api.py tests/test_dubbing_cli_api.py`。
- 校验通过：`uv run python -m unittest tests/test_dubbing_cli_api.py`，`Ran 12 tests ... OK`。
- 已在前端 `panel-auto-dub` 增加 `Timing Mode` 下拉，默认 `Balanced`，并在 `app.js` 启动请求中透传 `timing_mode`。
- 前端语法校验通过：`node --check src/subtitle_maker/static/app.js`。

## 2026-04-17 Auto Dubbing 句级重构（禁止 1-2 秒碎片）

- [x] 句组构建改为“句子优先 + speaker 切换强制断开”
- [x] 多人模式最小时长提升（默认至少 3s）并合并过短相邻组
- [x] 移除 balanced 的组内二次切片，统一整句组落盘
- [x] 多人检测到单 speaker 时自动回退单人链路并显式记录日志
- [x] 逐句 TTS 增加无效音频门禁（过短/静音重试）
- [x] 完成 py_compile + unittest 验证

## Review（2026-04-17 句级重构）
- 已将 `build_synthesis_groups` 升级为句级+speaker 感知分组，不再按字幕行细碎合成。
- 多人模式若 diarization 最终仅识别出 1 个 speaker，会自动回退到单人参考流程并记录 `single_speaker_detected_in_multi_mode`。
- `synthesize_segments_grouped` 取消 balanced 的“组内切片分发”，统一按整句组作为合成单元，避免 1-2 秒片段。
- `synthesize_segments` 增加 `validate_audio` 检查：静音或过短音频会触发重试并标记 `E-TTS-002`。
- 校验通过：`uv run python -m py_compile tools/dub_pipeline.py src/subtitle_maker/dubbing_cli_api.py tests/test_dubbing_cli_api.py`。
- 校验通过：`node --check src/subtitle_maker/static/app.js`。
- 校验通过：`uv run python -m unittest tests/test_dubbing_cli_api.py`，`Ran 12 tests ... OK`。

## 2026-04-17 停用 pyannote，改为逐句原音频参考

- [x] 停用多说话人 pyannote/simple diarization 路径
- [x] 多人模式改为“按字幕时间窗逐句提取原音频参考”
- [x] 每句参考同时作为克隆参考与情绪参考（index-tts）
- [x] 多人模式强制关闭 grouped，保持句级参考映射
- [x] 完成 py_compile + unittest 验证

## Review（2026-04-17 逐句原音频参考）
- 在 `tools/dub_pipeline.py` 新增 `build_subtitle_reference_map`，按 `source_audio` 字幕时间窗提取 `refs/subtitles/subtitle_XXXX_ref.wav`。
- 多人模式主流程不再调用 pyannote/simple 分离，`diarization_provider_effective` 固定记录为 `disabled`，并输出 `sentence_reference_mode_enabled` 日志事件。
- `synthesize_segments` 中，`speaker_mode != single-speaker` 时将对应句子参考同时用于 `spk_audio_prompt` 与 `emo_audio_prompt`。
- 多人模式下关闭 grouped synthesis，避免句组打乱“一句一参考”映射关系。
- 校验通过：`uv run python -m py_compile tools/dub_pipeline.py src/subtitle_maker/dubbing_cli_api.py tests/test_dubbing_cli_api.py`。
- 校验通过：`uv run python -m unittest tests/test_dubbing_cli_api.py`，`Ran 12 tests ... OK`。

## 2026-04-17 命名可读化（去随机串）

- [x] `dubbing_cli_api` 任务 ID 去掉 UUID，改为时间戳+序号
- [x] `dub_pipeline` job_id 去掉随机串，改为时间戳+序号
- [x] `dub_long_video` batch_id 去掉随机串，改为时间戳+序号
- [x] 完成 py_compile + unittest 验证

## Review（2026-04-17 命名可读化）
- `src/subtitle_maker/dubbing_cli_api.py` 新增 `_build_readable_task_id`，任务 ID 示例：`20260417_102758`、冲突时 `20260417_102758_02`。
- `tools/dub_pipeline.py` 新增 `build_readable_run_id`，目录名不再包含随机哈希尾巴。
- `tools/dub_long_video.py` 新增 `build_readable_batch_id`，`longdub_` 批次目录采用时间戳+序号。
- 校验通过：`uv run python -m py_compile tools/dub_pipeline.py tools/dub_long_video.py src/subtitle_maker/dubbing_cli_api.py tests/test_dubbing_cli_api.py`。
- 校验通过：`uv run python -m unittest tests/test_dubbing_cli_api.py`，`Ran 12 tests ... OK`。

## 2026-04-17 长视频段内字幕错位根因修复（静音识别 + 时间戳守卫）

- [x] Spec-1 现状分析：确认错误起点与链路污染路径（带代码出处）
- [x] Spec-2 功能点：静音识别策略与时间戳正确性约束
- [x] Spec-3 风险与决策：兼容性、回退与验证口径
- [x] 实施 A：前导静音识别与裁剪（ASR 前）
- [x] 实施 B：字幕时间戳守卫（零时长/逆序/重叠修正）
- [x] 实施 C：异常重试与失败降级（确保不会输出坏 SRT）
- [ ] 验证：py_compile + unittest + 样例长视频链路复核

## Review（2026-04-17 长视频段内字幕错位修复进行中）
- `tools/dub_pipeline.py` 已改为“先基于 `source_audio` 识别字幕，再做人声分离”，避免分离音频影响 ASR 时间轴。
- 已新增前导静音裁剪：`trim_leading_silence_for_asr`，并在日志写入 `asr_input_prepared` 事件。
- 已新增时间戳健康分析与守卫：`analyze_subtitle_timestamps` + `enforce_subtitle_timestamps`，并写入 `asr_timestamp_health` 事件。
- 已新增坏 `source.srt` 拒绝复用机制：`source_subtitle_rejected`，检测到零时长/逆序会自动重生成。
- 校验通过：`uv run python -m py_compile tools/dub_pipeline.py src/subtitle_maker/dubbing_cli_api.py tests/test_dubbing_cli_api.py`。
- 校验通过：`uv run python -m unittest tests/test_dubbing_cli_api.py`，`Ran 13 tests ... OK`。

## 2026-04-17 Auto Dubbing 接入 Time Ranges（手动+自动）

- [x] `dubbing_cli_api` 新增 `time_ranges`、`auto_pick_ranges` 入参并透传 CLI
- [x] `dub_long_video` 支持全局区间策略并映射到分段局部区间
- [x] `dub_pipeline` 支持区间过滤字幕与自动语音区间检测
- [x] 区间为空时输出静音 vocals 兜底，避免流程中断
- [x] 前端 Auto Dubbing 面板增加自动区间开关与手动区间 JSON 输入
- [x] 新增 API 单测并完成语法与回归验证

## Review（2026-04-17 Time Ranges 接入）
- `src/subtitle_maker/dubbing_cli_api.py` 新增 `_parse_time_ranges_form` 与布尔解析，支持 `time_ranges` JSON 与 `auto_pick_ranges` 参数校验。
- `tools/dub_long_video.py` 新增全局区间解析/自动检测/分段映射（`map_global_ranges_to_segment`），每段透传局部 `--time-ranges-json`。
- `tools/dub_pipeline.py` 新增区间函数：`parse_time_ranges_json`、`detect_speech_time_ranges`、`filter_subtitles_by_time_ranges`，并把 `range_strategy/requested/effective` 写入 manifest。
- `tools/dub_pipeline.py` 在“无可配音字幕”场景输出与源人声等长静音轨，保证混音与导出链路不中断。
- `src/subtitle_maker/templates/index.html` 与 `src/subtitle_maker/static/app.js` 已增加 Auto Dubbing 区间配置入口并透传后端。
- 校验通过：`uv run python -m py_compile tools/dub_pipeline.py tools/dub_long_video.py src/subtitle_maker/dubbing_cli_api.py tests/test_dubbing_cli_api.py`。
- 校验通过：`uv run python -m unittest tests/test_dubbing_cli_api.py`，`Ran 15 tests ... OK`。
- 校验通过：`node --check src/subtitle_maker/static/app.js`。

## 2026-04-18 Auto Dubbing 支持上传字幕并跳过 ASR

- [x] 扩展 API 接收可选字幕文件
- [x] 长视频按分段裁剪输入字幕并透传到 `dub_pipeline`
- [x] 前端新增字幕上传控件并透传
- [x] 补充测试并执行回归验证

## Review（2026-04-18 上传字幕跳过 ASR）
- `src/subtitle_maker/dubbing_cli_api.py` 的 `/dubbing/auto/start` 新增可选 `subtitle_file`，上传后会透传 `--input-srt`。
- `tools/dub_long_video.py` 新增 `--input-srt`，并在每个分段生成局部 `_input_segment.srt`（时间轴归零到段内），实现“分段时自动裁字幕”。
- `tools/dub_long_video.py` 在指定 `--input-srt` 时禁用旧任务复用，避免误用历史 ASR 结果。
- `src/subtitle_maker/templates/index.html` 与 `src/subtitle_maker/static/app.js` 已增加 Auto Dubbing 可选 SRT 上传控件与提交流程。
- 新增单测：`tests/test_dubbing_cli_api.py::test_start_auto_dubbing_accepts_optional_subtitle_file`。
- 校验通过：`uv run python -m py_compile src/subtitle_maker/dubbing_cli_api.py tools/dub_long_video.py tools/dub_pipeline.py tests/test_dubbing_cli_api.py`。
- 校验通过：`uv run python -m unittest tests/test_dubbing_cli_api.py`，`Ran 17 tests ... OK`。
- 校验通过：`node --check src/subtitle_maker/static/app.js`。

## 2026-04-18 Auto Dubbing 稳定性修复收口（翻译字幕链路）

- [x] 修复 auto ranges 被隐式开启导致碎片分段
- [x] New Project 禁止误触发 segment resume in-place
- [x] 上传翻译字幕统一清洗 `<b>`、`[]`、`{}`
- [x] 上传翻译字幕改为句级 start 对齐（end 自然收尾）
- [x] 上传翻译字幕禁用重试改写，保留用户文本
- [x] 清理逐句重试中间文件 `seg_xxxx_a*.wav`
- [x] New Project 清理 `uploads/dubbing` 但保留 `outputs/dub_jobs`
- [x] `longdub` 目录命名改为纯时间戳（无 `-001`）
- [x] 增加“上传字幕时强制关闭 auto-pick”单测
- [x] 完成 py_compile + unittest 回归验证

## Review（2026-04-18 稳定性修复收口）
- `src/subtitle_maker/static/app.js` 修复 `autoPickRanges` 缺省值为 `false`，并与模板默认取消勾选一致。
- `src/subtitle_maker/dubbing_cli_api.py` 上传字幕时强制关闭 `auto_pick_ranges`，避免未显式开启却自动碎片分段。
- `tools/dub_long_video.py` 修复 New Project 场景误打印/误使用 `resume in-place`，并保持 `segment_jobs/segment_xxxx` 一一对应。
- `tools/dub_pipeline.py` 新增字幕清洗（HTML 标签、括号说明），并接入上传字幕/复用字幕/翻译字幕跳过翻译主链路。
- `tools/dub_pipeline.py` 上传翻译字幕时强制逐句合成、关闭硬性 end 拟合、关闭改写重翻，保障“start 严格对齐 + 文案不改写”。
- `tools/dub_pipeline.py` 增加逐句中间文件清理，消除 `seg_xxxx_a0/a1/a3.wav` 残留干扰。
- `src/subtitle_maker/web.py` 调整 `/project/reset`：清理 `uploads/dubbing`，保留 `outputs/dub_jobs` 历史结果。
- `tools/dub_long_video.py` 批次命名改为 `longdub_YYYYMMDD_HHMMSS`（无序号后缀）。
- `tests/test_dubbing_cli_api.py` 新增上传字幕时 `auto_pick_ranges=true` 仍被强制关掉的回归测试。
- 校验通过：`uv run python -m py_compile src/subtitle_maker/web.py src/subtitle_maker/dubbing_cli_api.py tools/dub_long_video.py tools/dub_pipeline.py`。
- 校验通过：`uv run python -m unittest tests/test_dubbing_cli_api.py`，`Ran 20 tests ... OK`。

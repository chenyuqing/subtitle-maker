# TODO

## 163. 2026-06-06 5 号面板无参考音时优先使用预设声音库（性别识别）
- [x] 现状分析
  - [x] 完全没上传参考音时，`_run_omnivoice_job` 直接走 `_build_speaker_reference_map()`，从原视频人声轨提取聚合参考音，未经过性别识别和预设声音库
  - [x] 性别识别（`_infer_missing_speaker_gender_hints`）和预设库选音（`_pick_preset_ref_voices_for_missing_speakers`）仅在"上传了部分 speaker 参考音但有缺失"时才触发
- [x] 功能点设计
  - [x] 完全未上传参考音时，先检查 `ref-voices/<target_lang>/` 预设声音库是否存在
  - [x] 预设库存在 → 对所有 detected speakers 做性别识别 → 按性别从预设库选参考音（`reference_mode = "preset_gender"`）
  - [x] 预设库不存在，或选音抛出异常 → fallback 回 `_build_speaker_reference_map()`（`reference_mode = "auto_aggregate"`）
  - [x] 只修改 5 号面板（`omnivoice_dub_api.py`），不触碰其他面板
- [x] 验证
  - [x] 语法检查通过（`uv run python -c "import ast; ast.parse(...)"` ✅）

### Review
- [x] [src/subtitle_maker/omnivoice_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/omnivoice_dub_api.py) `_run_omnivoice_job()` 的 `else` 分支（无上传）已改为：先调 `_resolve_ref_voices_dir()` 检查预设库 → 有则性别识别 + 预设库选音，无则人声提取

## 162. 2026-05-31 4 号面板 Index-TTS 按 speaker_id 拆分原音参考链路
- [x] 现状分析
  - [x] [src/subtitle_maker/static/js/dubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/dubbingPanel.js) `buildCurrentProjectRequest()` 当前会把 `subtitles_json` 直接送去 `/dubbing/auto/start-from-project`，没有单独声明“按 speaker 切原音参考”的前端合同
  - [x] [src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py) Current Project 启动链路已经会落 `_input_project.speakers.json`，说明 4 号面板并不是没有 speaker 数据，而是后续是否正确利用它要继续核对
  - [x] [tools/dub_pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_pipeline.py) 当前单人模式 `dubbing_mode == "single"` 会直接 `extract_reference_audio_from_first_subtitle(...)`，多人模式若没有上传的 `speaker_ref_map_json`，则退回 `build_subtitle_reference_map(...)` 自动抽原音参考
  - [x] [src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py) `build_speaker_aware_synthesis_groups()` 已具备“先按同一 speaker 连续 run 分组”的底层能力
- [ ] 功能点设计
  - [ ] 4 号面板不引入 5/6 号那种“上传 speaker 参考音”工作流
  - [ ] 4 号面板继续沿用“从原视频人声音轨自动裁原音参考”的模式，但要在前段严格按 `speaker_id` 做分组与参考音选择
  - [ ] 目标是避免不同 speaker 的原音落进同一组，导致一个人的音色说两个人的话
- [ ] 风险与决策
  - [ ] 必须先确认问题发生在 `dubbing_mode` 推导、`grouped_synthesis` 分组、还是 `build_subtitle_reference_map(...)` 的参考音选择层，不能直接打补丁
  - [ ] 若 4 号面板当前被误推成 `single`，即使字幕里有 `speaker_id`，后续也会走共享参考音路径

## 161. 2026-05-26 Web 默认端口从 8000 切到不常用端口
- [x] 现状分析
  - [x] [src/subtitle_maker/web.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/web.py) `start()` 当前默认 `port=8000`
  - [x] [start.sh](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/start.sh) 当前用 `http://localhost:8000` 做启动探活并自动打开浏览器
  - [x] [start-dub.sh](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/start-dub.sh)、[stop.sh](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/stop.sh)、[stop-dub.sh](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/stop-dub.sh)、[clean-model.sh](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/clean-model.sh) 也都把 `8000` 写死成当前 Web 端口
- [x] 功能点设计
  - [x] 统一把项目 Web 默认端口改成一个不常用端口
  - [x] 启动、停止、清理脚本与 Python 默认启动入口都改为同一端口
  - [x] 脚本侧统一支持 `SUBTITLE_MAKER_PORT` 环境变量覆盖，避免以后再次分裂
- [x] 验证
  - [x] `bash -n` 验证相关 shell 脚本语法
  - [x] `./.venv/bin/python -m py_compile src/subtitle_maker/web.py`

### Review
- [x] [src/subtitle_maker/web.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/web.py) 已把默认 Web 端口改为 `17493`，并允许通过 `SUBTITLE_MAKER_PORT` 覆盖
- [x] [start.sh](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/start.sh)、[start-dub.sh](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/start-dub.sh)、[stop.sh](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/stop.sh)、[stop-dub.sh](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/stop-dub.sh)、[clean-model.sh](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/clean-model.sh) 已统一切到同一端口变量，不再写死 `8000`
- [x] 已通过 `bash -n start.sh start-dub.sh stop.sh stop-dub.sh clean-model.sh restart.sh`
- [x] 已通过 `./.venv/bin/python -m py_compile src/subtitle_maker/web.py`

## 160. 2026-05-26 5 号面板上传了参考音却静默退回 auto_aggregate
- [x] 现状分析
  - [x] 当前运行批次 `outputs/dub_jobs/omnivoice_20260526_022415/manifest.json` 明确显示 `speaker_reference_mode = auto_aggregate`
  - [x] 同批次不存在 `uploaded_speaker_refs/`，而 `speaker_ref_map.json` 里 `Speaker 1.ref_text` 竟然是 `>> [音乐] [音乐] ...`，说明这轮根本没使用用户上传参考音，而是静默退回自动聚合参考音
  - [x] 当前后端 `src/subtitle_maker/omnivoice_dub_api.py::start_omnivoice_from_project()` 里，如果 `uploaded_speaker_ref_map` 为空，会直接进入 `auto_aggregate`，没有区分“用户没上传”还是“用户上传了但绑定失败”
- [x] 功能点设计
  - [x] 只改 5 号面板后端上传参考音绑定逻辑
  - [x] 若请求里带了 `speaker_ref_files`，但 `speaker_ref_speaker_ids_json` 为空，且当前只检测到 1 个 speaker，则自动把该文件绑定到唯一 speaker
  - [x] 若请求里带了 `speaker_ref_files`，但最终一个都没绑定成功，直接报错，禁止静默回退到 `auto_aggregate`
- [x] 验证
  - [x] 增加回归测试，覆盖单 speaker 上传文件但未显式传 speaker ids 时，后端仍能绑定成功
  - [x] 增加回归测试，覆盖“上传了文件却未绑定”时会直接失败而不是静默 auto_aggregate

### Review
- [x] [src/subtitle_maker/omnivoice_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/omnivoice_dub_api.py) 已新增 `_has_uploaded_file_selection()`，并在 `start_omnivoice_from_project()` 里把“有上传文件但 ids 为空”的单 speaker 场景自动绑定到唯一 `Speaker 1`
- [x] 同一入口现在会在“上传了文件但无法唯一推断 speaker”时直接返回 `400`，不再静默回退 `auto_aggregate`
- [x] [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 已新增 2 个回归测试，覆盖自动绑定成功与无法绑定时报错
- [x] 已通过 `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_start_omnivoice_from_project_auto_binds_single_uploaded_ref_without_speaker_ids tests.test_dubbing_cli_api.DubbingCliApiTests.test_start_omnivoice_from_project_rejects_uploaded_refs_without_bindable_speaker_ids tests.test_dubbing_cli_api.DubbingCliApiTests.test_start_omnivoice_from_project_rejects_partial_cantonese_refs_when_preset_pool_empty`
- [x] 已通过 `./.venv/bin/python -m py_compile src/subtitle_maker/omnivoice_dub_api.py tests/test_dubbing_cli_api.py`

## 159. 2026-05-26 5 号面板 prepared 状态被并发门禁误判为活任务
- [x] 现状分析
  - [x] 5 号面板 `Prepare selected_subtitles.srt` 现在会把 batch 写成 `status=prepared`
  - [x] `src/subtitle_maker/jobs/store.py::TaskStore.list_active_ids()` 当前只把 `completed/failed/cancelled` 视为终态
  - [x] 因此 `prepared` 会被当成“仍在运行中的活任务”，导致 5 号面板再次点击开始配音或 resume 时被拦成 `Another OmniVoice job is already running`
- [x] 功能点设计
  - [x] 只修改 `TaskStore.list_active_ids()` 的默认终态集合
  - [x] 把 `prepared` 视为非活跃终态，允许其后续进入真正的 `start/resume`
  - [x] 不改 queued/running 的并发保护
- [x] 验证
  - [x] 回归测试覆盖 `prepared` 不应出现在 `list_active_ids()` 结果中
  - [x] 静态验证 `prepared` 终态已纳入并发门禁的终态集合

### Review
- [x] [src/subtitle_maker/jobs/store.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/jobs/store.py) 已把 `prepared` 纳入 `TaskStore.list_active_ids()` 的默认终态集合，不再把“已准备好字幕但未开始配音”的 batch 误当成活任务
- [x] [tests/test_task_store.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_task_store.py) 已新增 `test_prepared_status_is_not_treated_as_active`
- [x] 已通过 `./.venv/bin/python -m py_compile src/subtitle_maker/jobs/store.py tests/test_task_store.py`
- [x] 已通过 2 个定向测试：
  - [x] `tests.test_task_store.TaskStoreTests.test_update_and_active_listing_respect_terminal_status`
  - [x] `tests.test_task_store.TaskStoreTests.test_prepared_status_is_not_treated_as_active`

## 158. 2026-05-26 梳理并固化 speaker ID 识别逻辑文档
- [x] 现状分析
  - [x] 已收集 speaker ID 识别链路的核心出处：`src/subtitle_maker/domains/subtitles/speakers.py`、`src/subtitle_maker/static/app.js`、`src/subtitle_maker/static/js/omnivoiceDubbingPanel.js`、`src/subtitle_maker/static/js/voxcpmDubbingPanel.js`、`src/subtitle_maker/omnivoice_dub_api.py`、`src/subtitle_maker/voxcpm_dub_api.py`
  - [x] 已确认当前系统至少存在 4 层 speaker 语义：字幕导入标准化、前端项目上下文消费、面板级上传参考音 UI、后端启动/恢复时的 speaker 补齐
  - [x] 已确认 5 号面板与 6 号面板当前合同并不一致：5 号面板前端近期被收紧为只信任显式 `speaker_id`，6 号面板仍会在前端把无 speaker 场景展示为默认单 speaker
- [x] 功能点设计
  - [x] 产出一份单独逻辑文档，明确“当前实现”与“推荐合同”分开写
  - [x] 文档必须为每个结论标注具体文件路径 + 函数名，避免后续再靠印象改
  - [x] 文档必须明确回答：何时识别 `Speaker N:`、何时保留 sidecar `speaker_id`、何时默认单 speaker、何时写入 `selected_subtitles_with_speakers.srt`、恢复时从哪份文件还原
- [ ] 验证
  - [ ] 文档已写入仓库，后续可作为 speaker 相关改动的单一依据

## 157. 2026-05-26 5 号面板无 speaker 时默认单 speaker 上传参考音
- [x] 现状分析
  - [x] 当前 `src/subtitle_maker/static/js/omnivoiceDubbingPanel.js::getDetectedSpeakerIds()` 已收敛为只信任显式 `speaker_id`
  - [x] 这虽然避免了垃圾 speaker，但在“全文没有任何 speaker 标注”的正常单人场景下，会让 5 号面板错误显示为“没有 speaker 信息”，无法上传单 speaker 参考音
  - [x] 后端 `src/subtitle_maker/omnivoice_dub_api.py::start_omnivoice_from_project()` 本来就会把无 speaker 的字幕补成 `Speaker 1`，所以前端合同应与后端保持一致
- [x] 功能点设计
  - [x] 只改 5 号面板前端 speaker 列表推导
  - [x] 若存在显式 `speaker_id`，继续按显式 speaker 列表渲染
  - [x] 若整份有效字幕非空但没有任何显式 `speaker_id`，前端默认返回 `["Speaker 1"]`，允许上传单人参考音
  - [x] 若字幕为空，仍显示“没有 speaker 信息”
- [x] 验证
  - [x] 静态验证 5 号面板 JS 语法正常
  - [x] 自检无 speaker 字幕场景会生成 `Speaker 1` 上传槽位

### Review
- [x] [src/subtitle_maker/static/js/omnivoiceDubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/omnivoiceDubbingPanel.js) 已把 5 号面板前端合同补齐：当有效字幕非空但没有任何显式 `speaker_id` 时，`getDetectedSpeakerIds()` 默认返回 `["Speaker 1"]`
- [x] `renderSpeakerReferenceInputs()` 与 `renderSpeakerRefHint()` 已同步改为单 speaker 文案，不再把这种场景错误提示成“没有 speaker 信息”
- [x] 已通过 `node --check src/subtitle_maker/static/js/omnivoiceDubbingPanel.js`

## 156. 2026-05-26 5 号面板 speaker 被误识别成英文正文片段
- [x] 现状分析
  - [x] `src/subtitle_maker/domains/subtitles/speakers.py::SPEAKER_PREFIX_RE` 当前允许 `(?:[^:：\n]{1,80})` 作为 speaker 名，因此任何“冒号前一段普通文本”都有机会被误识别成 `speaker_id`
  - [x] 这会让普通英文句子、标题或说明文本中的冒号前半句被写进 `speaker_id`，出现用户看到的 `layers using a 1` 这类垃圾 speaker
  - [x] 我上一版把 5 号面板前端 speaker fallback 改成读取 `sourceSubtitles` 时间轴后，等于把这个底层脏 speaker 更直接地暴露到了 UI
- [x] 功能点设计
  - [x] 只收窄底层 speaker 前缀识别：默认只接受明确的 `Speaker ...:` 这一类前缀，不再把普通冒号句子当 speaker
  - [x] 回退 5 号面板前端那套“按 source 时间轴补 speaker”的改动，恢复为只基于显式 `speaker_id`
  - [x] 不改 6 号面板，不改真正的配音路由后端
- [x] 验证
  - [x] 增加回归测试，覆盖普通英文冒号句子不会再被识别成 speaker
  - [x] 静态验证 5 号面板前端 speaker 列表不再从 source 文本里捏造 speaker

### Review
- [x] [src/subtitle_maker/domains/subtitles/speakers.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/subtitles/speakers.py) 已把 `SPEAKER_PREFIX_RE` 收窄为只接受明确的 `Speaker ...:` 前缀，不再把普通英文冒号句子误识别成 `speaker_id`
- [x] [src/subtitle_maker/static/js/omnivoiceDubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/omnivoiceDubbingPanel.js) 已回退前一版“按 source 时间轴补 speaker”的前端逻辑，恢复为只基于显式 `speaker_id` 渲染 speaker 上传槽位，避免把脏 source 数据直接扩散到 UI
- [x] [tests/test_subtitle_speakers.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_subtitle_speakers.py) 已新增回归：`Ideas are everywhere: they're worthless.` 不会再被识别成 speaker
- [x] 已通过 `./.venv/bin/python -m unittest tests.test_subtitle_speakers.SubtitleSpeakerTests.test_strip_speaker_prefix_extracts_speaker_and_text tests.test_subtitle_speakers.SubtitleSpeakerTests.test_strip_speaker_prefix_does_not_treat_normal_english_colon_text_as_speaker`
- [x] 已通过 `./.venv/bin/python -m py_compile src/subtitle_maker/domains/subtitles/speakers.py tests/test_subtitle_speakers.py`
- [x] 已通过 `node --check src/subtitle_maker/static/js/omnivoiceDubbingPanel.js`

## 155. 2026-05-26 5 号面板 prepared batch 被误显示为“已完成配音”
- [x] 现状分析
  - [x] `src/subtitle_maker/omnivoice_dub_api.py::prepare_omnivoice_selected_subtitles_from_project()` 当前在“只生成 selected_subtitles.srt”后，把任务和 manifest 直接写成 `status=completed`
  - [x] `src/subtitle_maker/static/js/omnivoiceDubbingPanel.js::renderResumeAction()` 只要看到 `resume_stage === completed` 就显示“该批次已完成”
  - [x] 用户场景里虽然实际上只是 prepared，但因为后端 manifest 状态语义写错，Restore/Resume UI 被误导成“完成配音”
- [x] 功能点设计
  - [x] 只修改 5 号面板 prepared batch 的状态语义，不改真正 final 完成批次
  - [x] Prepare 产出的 batch 应明确标记为 `status=prepared`，`stage=prepared:selected_subtitles`
  - [x] 继续沿用 `_infer_resume_state()` 的 `resume_stage=prepared` 判定，让 Resume 按钮显示“跳过翻译继续配音”
- [x] 验证
  - [x] 回归测试覆盖 prepared batch 加载后仍为 `resumable=true`、`resume_stage=prepared`
  - [x] 回归测试覆盖 prepare 接口返回和 manifest 落盘都使用 `status=prepared`

### Review
- [x] [src/subtitle_maker/omnivoice_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/omnivoice_dub_api.py) 已把 `prepare_omnivoice_selected_subtitles_from_project()` 的状态语义从 `completed` 改为 `prepared`，stage 仍保持 `prepared:selected_subtitles`
- [x] 这意味着 5 号面板 Restore/Resume 读取 prepared batch 时，将继续由 `_infer_resume_state()` 正确推导成 `resume_stage=prepared`，不再被 UI 误显示为“该批次已完成”
- [x] 已通过 `./.venv/bin/python -m py_compile src/subtitle_maker/omnivoice_dub_api.py tests/test_dubbing_cli_api.py`
- [x] 已通过 2 个定向测试：
  - [x] `tests.test_dubbing_cli_api.DubbingCliApiTests.test_load_omnivoice_batch_marks_prepared_batch_resumable`
  - [x] `tests.test_dubbing_cli_api.DubbingCliApiTests.test_prepare_omnivoice_selected_subtitles_returns_prepared_status`

## 154. 2026-05-26 5 号面板上传参考音时报 unknown speaker_id
- [x] 现状分析
  - [x] 前端 `src/subtitle_maker/static/js/omnivoiceDubbingPanel.js::getDetectedSpeakerIds()` 当前基于 `getEffectiveSubtitleRows()` 直接做“上一行优先、最后 Speaker 1”的本地补齐
  - [x] 后端 `src/subtitle_maker/omnivoice_dub_api.py::start_omnivoice_from_project()` 会对 `translated_rows/source_rows` 再执行 `_ensure_speaker_ids(..., fallback_rows=source_rows, force_align_by_time=True)`，按源字幕时间轴重对齐真实 speaker
  - [x] 当前前后端 speaker 推导规则不一致，会导致前端上传 `Speaker 1`，但后端本轮真实 speaker 集合里并没有这个 id，进而在 `start_omnivoice_from_project()` 触发 `unknown speaker_id in uploaded OmniVoice references`
- [x] 功能点设计
  - [x] 只修改 5 号面板前端 speaker 探测逻辑，不改 6 号面板，不改 OmniVoice 合成逻辑
  - [x] 前端按和后端一致的规则，为当前 `subtitle_mode` 的有效字幕补齐 speaker：优先按 source 时间窗重对齐，无命中时再回退上一行/`Speaker 1`
  - [x] 上传参考音槽位、提示文案、`speaker_ref_speaker_ids_json` 都统一使用这套对齐后的 speaker 列表
- [x] 验证
  - [x] 自检前端 `speaker_ref_speaker_ids_json` 生成路径已改为使用时间轴对齐后的 speaker 列表
  - [x] 运行静态验证，确认不会再把仅存在于前端默认补位的 `Speaker 1` 传给后端

### Review
- [x] [src/subtitle_maker/static/js/omnivoiceDubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/omnivoiceDubbingPanel.js) 已新增前端版时间轴 speaker 对齐逻辑：`buildSpeakerFallbackCandidates()`、`pickSpeakerIdByTime()`、`normalizeSpeakerIdsForPanelRows(rows, fallbackRows)`，现在与后端 `src/subtitle_maker/omnivoice_dub_api.py::_ensure_speaker_ids(..., force_align_by_time=True)` 的匹配顺序一致
- [x] `getDetectedSpeakerIds()` 已改为用 `sourceSubtitles` 作为 fallback 时间轴，因此上传参考音槽位、提示文案、`speaker_ref_speaker_ids_json` 不会再因为译文缺失 speaker 而被前端错误补成统一的 `Speaker 1`
- [x] 已通过 `node --check src/subtitle_maker/static/js/omnivoiceDubbingPanel.js`
- [x] 已通过 `./.venv/bin/python -m py_compile src/subtitle_maker/translator.py src/subtitle_maker/omnivoice_dub_api.py src/subtitle_maker/voxcpm_dub_api.py tests/test_dubbing_cli_api.py`

## 153. 2026-05-25 final 输出文件名跟随上传视频文件名
- [x] 现状分析
  - [x] 5 号面板 final 输出文件名当前在 `src/subtitle_maker/omnivoice_dub_api.py` 多处写死为 `dubbed_final_full.srt`、`dubbed_mix_full.wav`、`dubbed_video_full.mp4` 等
  - [x] 6 号面板 final 输出文件名当前在 `src/subtitle_maker/voxcpm_dub_api.py` 也写死为 `dubbed_final_full.srt`、`dubbed_video_full.mp4` 等
  - [x] 当前任务上下文里已经有上传视频原始文件名可用：`project_filename` / `original_filename`
- [ ] 功能点设计
  - [ ] final 目录下输出文件改为基于上传视频文件名的 stem 命名
  - [ ] 只替换最终产物命名，不改中间产物目录结构，不改 artifact key
  - [ ] 对无视频或仅字幕场景，回退到现有默认命名，避免空文件名
- [ ] 风险与决策
  - [ ] 风险 1：manifest / artifact / restore / download 依赖当前固定路径，必须统一从实际生成路径回填，不能只改文件名常量
  - [ ] 风险 2：同一 batch 内可能同时存在不同规格视频、副产物 ASS/SRT/WAV，命名规则要稳定且可预测
- [ ] 验证
  - [ ] 增加定向测试，覆盖上传 `demo.mp4` 后 final 产物名带 `demo`
  - [ ] 验证旧 artifact key 仍可下载到新文件路径

## 152. 2026-05-25 5 号面板去掉简繁字符表后处理，改为 LLM 二次审校粤语译文
- [x] 现状分析
  - [x] `src/subtitle_maker/omnivoice_dub_api.py::_translate_subtitles_if_needed()` 在 5 号面板 source->粤语时，主翻译、缺失行补译、latin-dominant repair 完成后，会进入 `_sanitize_translated_rows_for_target(...)`
  - [x] `src/subtitle_maker/omnivoice_dub_api.py::_sanitize_translated_rows_for_target()` 与同文件后续粤语分支，当前都会调用 `convert_chinese_script_text(..., "traditional")`
  - [x] `src/subtitle_maker/domains/subtitles/zh_script.py::convert_chinese_script_text()` 当前环境下 `zhconv` 未加载成功，会退回 `GPT-SoVITS/.../char_convert.py` 的字符映射表
  - [x] 已实测该 fallback 会产出不适合字幕/TTS 的异体字或冷僻字，例如：`这是 -> 這昰`、`为 -> 爲`、`后台 -> 后颱`
- [ ] 功能点设计
  - [x] 5 号面板粤语链路不再做字符级“简转繁”后处理；已移除 `convert_chinese_script_text(..., "traditional")` 在 OmniVoice 粤语路径上的调用
  - [x] 新增一个基于现有 Translation API 的 LLM 审校步骤，只在 `target_lang in {Cantonese, Cantonese-Mainland}` 时启用
  - [x] 审校输入为已翻译的逐行字幕文本，要求模型只做：
    - [x] 保留原意，不摘要、不删句、不扩写
    - [x] 修正为自然粤语
    - [x] 统一输出现代常用繁体字
    - [x] 每行一一对应返回，保留行数
  - [x] 审校放在 5 号面板翻译完成、空行回退与 latin-dominant repair 之后，`selected_subtitles.srt` 落盘之前，避免影响上游对齐与补译
- [ ] 风险与决策
  - [ ] 风险 1：二次 LLM 审校会增加一次 API 成本与耗时，但能替代错误的字符表转换
  - [ ] 风险 2：如果整批审校仍发生漏行，必须复用 `Translator.translate_batch()` 现有的 split/missing retry 机制，不能自己写一套脆弱 parser
  - [ ] 风险 3：需要把审校 prompt 和“普通翻译 prompt”职责分开，避免再触发摘要化或截断
- [ ] 验证
  - [x] 增加回归测试，覆盖“简体粤语译文 -> 审校后变成常用繁体，且不出现 `這昰/爲/后颱` 这类异常字形”
  - [x] 增加回归测试，覆盖审校步骤不会把 `My name is Matt Berman.` 这类译文再裁成 `我叫`

### Review
- [x] [src/subtitle_maker/translator.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/translator.py) 已新增 `build_cantonese_review_system_prompt()` 与 `Translator.review_batch()`，复用原有编号解析、missing-line retry、split retry 机制执行粤语二次审校
- [x] [src/subtitle_maker/omnivoice_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/omnivoice_dub_api.py) 已删除 5 号面板粤语链路里的 `convert_chinese_script_text(..., "traditional")`，改为 `_review_cantonese_rows_with_llm()` 在翻译后、落盘前做 LLM 审校
- [x] 已通过 `./.venv/bin/python -m py_compile src/subtitle_maker/translator.py src/subtitle_maker/omnivoice_dub_api.py tests/test_dubbing_cli_api.py`
- [x] 已通过 4 个定向测试：
  - [x] `test_translate_subtitles_if_needed_restores_empty_rows_from_source_for_omnivoice`
  - [x] `test_translate_subtitles_if_needed_retries_latin_rows_after_empty_fallback`
  - [x] `test_omnivoice_cantonese_review_replaces_abnormal_script_forms`
  - [x] `test_omnivoice_cantonese_review_keeps_full_sentence_meaning`

## 151. 2026-05-24 5 号面板 OmniVoice 粤语翻译强制全量繁体落盘
- [x] 现状分析
  - [x] 用户要求：5 号面板只要目标语是 `Cantonese` / `Cantonese-Mainland`，落盘到 `selected_subtitles.srt` 的粤语结果必须全部转成繁体字，不能混入简体，否则 OmniVoice 可能按普通话习惯配音
  - [x] 代码现状已存在繁体转换接入点：`src/subtitle_maker/omnivoice_dub_api.py::_sanitize_translated_rows_for_target()` 与 `src/subtitle_maker/omnivoice_dub_api.py::_translate_subtitles_if_needed()` 的粤语后处理分支
  - [x] 共享翻译层仍需继续核对：`src/subtitle_maker/translator.py::translate_batch()` 默认仍会做通用清洗，必须确认不会在 5 号面板粤语链路里把正文裁断或改坏
- [ ] 功能点设计
  - [ ] 锁定 5 号面板合同：`Cantonese` / `Cantonese-Mainland` 的译文，无论来源是主翻译批次、缺失行补译、latin-dominant repair，最终写入 `selected_subtitles.srt` / `selected_subtitles_with_speakers.srt` 时都必须是繁体
  - [ ] 增加回归测试，覆盖“简体粤语输入 -> 5 号面板最终 selected 输出为全量繁体”的合同
  - [ ] 把“繁体转换”和“正文不被截断/摘要化”拆开验证，避免把两类问题混在一起判断
- [ ] 风险与决策
  - [ ] 风险 1：如果繁体转换放在过早阶段，可能影响缺失行补译与正文比对；优先在 5 号面板最终后处理/落盘前收口
  - [ ] 风险 2：当前 5 号面板历史上还出现过 `我叫 / 我系 / 同埋` 这类残句，必须单独证明这是翻译/清洗问题还是后续 selected 优化问题，不能再靠猜
- [ ] 验证
  - [ ] 用 5 号面板英文 source -> 粤语目标语跑一次，核对 `selected_subtitles.srt` 是否为全量繁体
  - [ ] 核对问题样本中是否还存在“繁体正确但正文被截断”的情况，分开记账

## 150. 2026-05-22 5 号面板 OmniVoice 配音语速不均修复（CPS timing rebalance）
- 问题：`selected_subtitles.srt` 存在极端 CPS 方差（1.1～60.7，中位 5.6），导致配音交替极慢/极快
- 根因：TTS 合成始终 `speed=1.0` 不随文本密度调整；后处理变速阈值过窄（≤1.25）超出则硬截断；时间再分配只覆盖极端相邻对
- 参考 OmniVoice-Studio-main 三层方案（LLM 文本裁剪 + TTS speed + 后生成变速），跳过 LLM 层（太贵），用增强的前处理 + TTS speed + 后处理替代
- [x] 修复 1：Per-segment TTS speed 参数
  - [x] 在 [src/subtitle_maker/omnivoice_dub_api.py] 新增 `_OMNIVOICE_TARGET_CPS` 表（Chinese=6.0, English=15.0 等）和 `_compute_tts_speed_for_segment()` 函数
  - [x] 合成循环根据 `text_units / target_cps / slot_duration` 计算 speed [0.8, 1.4]，传入 `_call_remote_generate(speed=...)`
  - [x] segment manifest 新增 `tts_speed` 字段用于诊断
- [x] 修复 2：扩大后处理变速范围
  - [x] `_normalize_generated_segment_audio()` 变速阈值从 `ratio <= 1.25` 扩到 `ratio <= 1.5`，减少硬截断
  - [x] 新增音频过短（< 85% 目标时长）时的减速拉长处理
- [x] 修复 3：CPS 均衡化预处理
  - [x] 新增 `_equalize_cps_across_neighbors()`：同 speaker 相邻行 CPS 比值 > 2.0 时按文本长度重分时间，最多迭代 3 轮
  - [x] 接入主合成管线（`_rebalance` 之后）
- [x] 修复 4：Speaker upload 路径补齐
  - [x] `prepare_omnivoice_speaker_upload_dubbing` 漏调了 `_rebalance_omnivoice_synthesis_rows` 和 `_equalize_cps_across_neighbors`，已补上
- [x] 验证
  - [x] 316 测试通过，0 新增失败（3 个为预存问题）
  - [x] `_compute_tts_speed_for_segment` 手动验证：密集中文 2s 窗 → speed=1.4，稀疏中文 5s 窗 → speed=0.8，正常文本 → speed 在合理范围
  - [x] `_equalize_cps_across_neighbors` 手动验证：20 字 vs 2 字相邻行正确按文本比例重分时间

## 149. 2026-05-22 4 号面板 Index-TTS 翻译链路检查——无需修改
- [x] 检查结论
  - [x] 4 号面板架构与 5/6 号面板不同：翻译由 web route `translation.py:translate()` / `subtitles.py` 处理，无 `_translate_subtitles_if_needed()`，无 `selected_mode` 概念
  - [x] 翻译结果直接 `zip(subtitles, translated_texts)` 拼回，无后处理链路（无 sanitize→fallback→retry→optimize 复杂流程）
  - [x] `translate_batch()` 保持默认 `sanitize_outputs=True`，对 4 号面板是正确的——翻译结果供用户预览/编辑，`sanitize_translation_text()` 清洗 LLM 废话是有用的
  - [x] 不存在 mode 错标、sanitize 执行顺序、空行回退等 5/6 号面板的问题
- [x] 结论：4 号面板无需修改

## 148. 2026-05-22 6 号面板 VoxCPM 翻译链路 selected_mode 记账错误修复
- [x] 根因分析
  - [x] `voxcpm_dub_api.py::_translate_subtitles_if_needed()` L968 翻译完成后返回 `"source"` 而非 `"translated"`，与 5 号面板 #146 同类 bug
  - [x] VoxCPM 的 `selected_mode` 只写入 task 元数据，不影响下游优化分支（与 5 号面板不同，无行为影响，仅记账错误）
  - [x] `sanitize_outputs=False` 和清洗策略已正确：6 号面板默认保留整段正文，只在检测到脏输出时才回退激进清洗
- [x] 修复
  - [x] `voxcpm_dub_api.py` L968：翻译完成后返回 `"translated"` 而非 `"source"`
  - [x] 更新 3 个测试断言：`preserves_speaker_ids`、`retries_latin_dominant`、`keeps_full_cantonese_paragraph`

### Review
- [x] 5 个 VoxCPM 翻译测试全部通过（含 2 个同语种直通测试确认仍返回 `"source"`）
- [x] 全量 `tests.test_dubbing_cli_api` 151 个测试：0 新增 FAIL/ERROR

## 146. 2026-05-22 5 号面板翻译链路 selected_mode 错误标记 + sanitize 执行顺序修复
- [x] 根因分析
  - [x] `_translate_subtitles_if_needed()` 在 `subtitles_mode="source"` + 翻译实际执行后，`selected_mode` 仍返回 `"source"` 而非 `"translated"`
  - [x] 这导致 `_optimize_omnivoice_selected_rows(subtitle_mode="source")` 走直通分支（不合并相邻短 cue），674 条逐 cue 翻译的粤语碎片原样保留
  - [x] manifest 记账 `selected_subtitle_mode=source` 但 `selected_subtitles.srt` 内容为粤语——记账与实际内容不一致
- [x] 修复 1：翻译完成后 selected_mode 设为 "translated"
  - [x] `omnivoice_dub_api.py` L2229：`translator.translate_batch()` 返回后立即设置 `selected_mode = "translated"`
  - [x] 使 `_optimize_omnivoice_selected_rows()` 走完整优化路径（合并相邻短 cue + 超长段切分），不再保留 674 个碎片
- [x] 修复 2：OmniVoice 翻译调用禁用内置 sanitize
  - [x] 三处 `translator.translate_batch()` 调用均传 `sanitize_outputs=False`
  - [x] 避免 `sanitize_translation_text()` 的候选片段评分逻辑在翻译器层面就裁断正常粤语正文
  - [x] 由 `_sanitize_translated_rows_for_target()` 在后处理统一接管
- [x] 修复 3：空行回退 vs sanitize 执行顺序
  - [x] 原流程：sanitize（丢弃空行）→ 空行回退（永远不触发）→ 重译
  - [x] 修复后：空行回退 → 重译 → sanitize → drop_empty
  - [x] 确保空行回退能正确触发，重译结果也能被 sanitize 处理

### Review
- [x] 三个直接相关测试（restore_empty_rows / retries_latin_dominant / retries_latin_rows_after_empty_fallback）全部通过
- [x] 全量 `tests.test_dubbing_cli_api` 151 个测试：0 新增 FAIL，剩余 1 FAIL + 3 ERROR 均为预先存在的问题（git stash 验证）
- [x] 全量 `tests.test_web_routes_legacy` 11 个测试：全部通过
- [x] 端到端验证 `omnivoice_20260522_135724/selected_subtitles.srt`：
  - [x] manifest `selected_subtitle_mode` 正确显示 `"translated"`（旧值错误显示 `"source"`）
  - [x] 674 条原始 source cue 翻译后合并为 344 条完整粤语句（旧版 674 条碎片不合并）
  - [x] 粤语翻译完整可读："我叫 Matt Berman"、"我系 Ford Future 嘅 CEO" 等（旧版 "我叫"、"我系"、"同埋" 各占一条）

## 147. 2026-05-22 翻译 batch size 过大导致 API 调用爆炸
- [x] 根因分析
  - [x] `DEFAULT_TRANSLATION_BATCH_SIZE=300`，LLM 对 300 行编号列表精度差，丢行率 ~15%
  - [x] `MAX_TRANSLATION_MISSING_RETRY_COUNT=8` + `MAX_TRANSLATION_MISSING_RETRY_RATIO=0.05` 太严格，46 行缺失直接跳过局部补译，走 split retry
  - [x] 实际观察：1 个 batch 本来 1 次 API 调用，因递归拆分变成 8 次（300→150+150→75+75+150，每层再补译）
  - [x] 674 行翻译预计 20+ 次 API 调用，浪费 token 和时间
- [x] 修复
  - [x] `DEFAULT_TRANSLATION_BATCH_SIZE` 300→100：LLM 处理 100 行编号列表精度高很多，674 行变 7 批
  - [x] `MAX_TRANSLATION_MISSING_RETRY_COUNT` 8→15：100 行里丢 10 行也能直接局部补译
  - [x] `MAX_TRANSLATION_MISSING_RETRY_RATIO` 0.05→0.15：放宽门槛，优先走便宜的局部补译而非 split retry
  - [x] `MIN_TRANSLATION_RETRY_CHUNK_SIZE` 60→30：万一还要拆，拆得更小更精准

### Review
- [x] `py_compile` 验证通过
- [x] 预期效果：674 行翻译从 ~20 次 API 调用降到 7-9 次（7 批各 1 次 + 偶尔 1-2 次局部补译）

## 145. 2026-05-22 1 号面板 source SRT 上传不应激进优化
- [x] 现状分析
  - [x] 核对 [src/subtitle_maker/app/routes/subtitles.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/app/routes/subtitles.py) `::upload_srt()`，确认 source/translated 两种上传都统一调用了 `optimize_srt_import_subtitles(...)`
  - [x] 用原始文件 `~/Downloads/2026-05-22-125013-YTDown_YouTube_Beyond-the-keynote-with-Sundar-Pichai_Media_9C20esBUf-Q_001_1080p.srt` 取证，确认 1 号面板上传链路会把 `674` 行压成 `423` 行
  - [x] 用 [outputs/dub_jobs/omnivoice_20260522_123518/manifest.json](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/outputs/dub_jobs/omnivoice_20260522_123518/manifest.json:1) 取证，确认 `source_subtitles_count=423`，说明 5 号面板读取到的 source 已经是上传阶段被改写后的版本
- [x] 功能点设计
  - [x] 只修改 1 号面板 SRT 上传入口，不改 Deepgram JSON、不改 5/6 号面板后端翻译逻辑
  - [x] `subtitle_kind=source` 时保留原始 cue 边界，只做 `normalize_subtitles_with_speakers(...)` 和必要的基础清洗
  - [x] `subtitle_kind=translated` 保留现有导入优化，继续服务“直接上传译文稿”的收敛场景
- [x] 风险与决策
  - [x] 风险 1：上传后 source 行数回升，会影响依赖 Current Project 的 4/5/6 号面板，但这是期望行为，因为用户要的是原始 source 真值
  - [x] 风险 2：如果 translated 上传仍走优化、source 上传不走，前端需继续清楚区分两种语义
- [x] 待确认
  - [x] 确认后按“source 上传保原始 cue”实现

### Review
- [x] [src/subtitle_maker/app/routes/subtitles.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/app/routes/subtitles.py) 的 `upload_srt()` 现已按 `subtitle_kind` 分流：`source` 只做 `normalize_subtitles_with_speakers(...)`，不再跑 `optimize_srt_import_subtitles(...)`
- [x] `translated` 上传仍保留原有导入优化，因此不会影响“直接上传译文稿后对齐/收敛”的旧行为
- [x] 已通过 `tests/test_web_routes_legacy.py` 四个定向用例与 `py_compile` 验证，锁住 source 上传保原始 cue、translated 上传仍可收敛两条语义

## 144. 2026-05-22 1 号面板 source 状态被 4 号面板结果污染修复
- [x] 现状分析
  - [x] 核对 [src/subtitle_maker/static/app.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js) `::handleSrtUpload()` 与 `::applyImportedSubtitleResponse()`，确认 1 号面板上传 `subtitle_kind=source` 时会把英文 SRT 写入 `originalSubtitlesData`
  - [x] 核对 [src/subtitle_maker/static/js/dubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/dubbingPanel.js) `::autoLoadAutoDubSubtitles()`，确认 4 号面板加载结果后会调用 [src/subtitle_maker/static/app.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js) `::applyAutoDubSubtitleItems()`，把结果字幕回写到 `originalSubtitlesData`
  - [x] 确认 [src/subtitle_maker/static/app.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js) `::saveState()` 会把被污染后的 `originalSubtitlesData` 持久化到 `sm_originalSubtitles`，导致刷新后 5 号面板仍读到错误 source
- [x] 功能点设计
  - [x] 只修改前端状态管理，不改 5 号面板后端翻译/配音逻辑
  - [x] 4 号面板加载历史结果或自动加载配音结果时，只更新播放器字幕预览，不再改写 `Current Project` 的 `originalSubtitlesData / translatedSubtitlesData`
  - [x] 保留 1 号面板上传 source/translated SRT 时对 `Current Project` 的真值写入语义
- [x] 风险与决策
  - [x] 风险 1：4 号面板结果预览仍要可见，不能因为去掉全局回写而失去播放器字幕显示
  - [x] 风险 2：localStorage 中旧的污染值可能仍存在；至少要确保新一轮结果加载不再继续覆盖
- [x] 待确认
  - [x] 确认后按“结果预览状态”和“Current Project 真值状态”分离的方案落地

### Review
- [x] [src/subtitle_maker/static/app.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js) 新增 `applySubtitlePreviewItems()` 与 `window.applyAutoDubPreviewSubtitles()`，把“字幕预览注入播放器”从“Current Project 真值写回”里拆开
- [x] [src/subtitle_maker/static/js/dubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/dubbingPanel.js) `::autoLoadAutoDubSubtitles()` 现优先走 `window.applyAutoDubPreviewSubtitles()`，因此 4 号面板加载历史结果时不再覆盖 1 号面板英文 source
- [x] 当前验证已完成 diff 级自检；原计划的 `node --check` 在本机失败，根因是系统 `node` 缺少动态库 `libsimdjson.29.dylib`，不是本次 JS 改动本身的语法错误

## 143. 2026-05-22 5 号面板 source 直通链路吞字修复
- [x] 现状分析
  - [x] 核对 [src/subtitle_maker/omnivoice_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/omnivoice_dub_api.py) `::_run_omnivoice_job()` 与 [src/subtitle_maker/omnivoice_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/omnivoice_dub_api.py) `::_optimize_omnivoice_source_rows()`，确认 5 号面板在 `subtitle_mode=source` 时会先把原始字幕送进 `optimize_srt_import_subtitles(...)`，再进入 selected 后处理
  - [x] 核对 [src/subtitle_maker/domains/subtitles/srt_import.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/subtitles/srt_import.py) `::optimize_srt_import_subtitles()`，确认当前 source 导入优化会按 speaker block + 句末标点 + 碎片修补重组 cue，存在把 `And / today / I am super excited...` 这类原始相邻 cue 合并坏的风险
  - [x] 用 [outputs/dub_jobs/omnivoice_20260522_112753/manifest.json](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/outputs/dub_jobs/omnivoice_20260522_112753/manifest.json) 取证，确认该批次 `subtitle_mode=source`、`selected_subtitle_mode=source`、`translated_subtitles_count=0`，因此 `selected_subtitles.srt` 的问题不是翻译层压缩导致，而是 source 直通链路本身吞字
  - [x] 取证结论：原始 source 674 行经 `_optimize_omnivoice_source_rows(...)` 后压成 336 行，随后 `_optimize_omnivoice_selected_rows(...)` 又把已被压坏的块继续切碎；根因在 source 导入优化，而不是翻译 provider
- [x] 功能点设计
  - [x] 只修改 5 号面板 source 直通链路，不改翻译 provider、不改 6 号面板、不改 final rebuild
  - [x] 给 `_optimize_omnivoice_source_rows()` 增加更保守的 source 模式分支：
    - [x] 对原始英文 SRT，禁止把 `Speaker X:` 前缀残留和后续正文跨 cue 吞并成一条
    - [x] 对明显短尾 cue（例如 `And`、`today`）不再做激进跨 cue 合并，优先保留原始时间窗与文字内容
    - [x] 只保留清洗和“单条超长 cue 内部切分”的最小处理，不做大范围句块重构
  - [x] 给 `_optimize_omnivoice_selected_rows()` 在 source 模式下增加更保守约束：
    - [x] source 直通结果只做规整与必要的单条超长切分，不再按长窗做二次重切
    - [x] 保证 `selected_subtitles.srt` 与原始 source 的文字内容尽量一一对应，优先保字义完整而不是压缩行数
  - [x] 产出合同保持不变：
    - [x] 仍输出 `selected_subtitles.srt`
    - [x] 仍输出 `selected_subtitles_with_speakers.srt`
    - [x] 不新增前端开关，不新增中间文件
- [x] 风险与决策
  - [x] 风险 1：source 直通结果行数可能回升，导致后续 TTS 句数变多；但这是接受的，因为当前优先级是“不吞字、不漏义”
  - [x] 风险 2：如果过度放宽 source 合并，可能再次出现超长句；因此改成只允许单条超长 cue 内部切分，不再做激进跨 cue 合并
  - [x] 风险 3：speaker_id 仍必须保留，后续恢复/重启不能丢 speaker 标签
  - [x] 验证必须覆盖原始坏例子，至少对 `And / today / I am super excited... / has been leading Google...` 这类 source cue 进行回归
- [x] 待确认
  - [x] 你确认后，我再开始实现这条 Spec，只收口 5 号面板 source 直通链路

### Review
- [x] [src/subtitle_maker/omnivoice_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/omnivoice_dub_api.py) 已为 5 号面板新增 source 模式保守直通分支：`subtitle_mode/source` 与 `selected_mode/source` 不再走跨 cue 合并，只做文本规整和单条超长 cue 内部切分
- [x] [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 已补回归，锁住 `Which is right for Google? / Is it ... / is just too good ... / is the more iterative ...` 与 `And / today / I am super excited ... / Sundar Pichai.` 不会再被压坏
- [x] 用原始 SRT `~/Downloads/2026-05-22-125013-YTDown_YouTube_Beyond-the-keynote-with-Sundar-Pichai_Media_9C20esBUf-Q_001_1080p.srt` 复现后，当前 source 直通结果已从历史的 `674 -> 336 -> 591` 收敛为 `674 -> 674 -> 674`，不再出现用户点名的半句长窗问题

## 132. 2026-05-22 5 号面板仅替换有字幕说话段，其余时间保留原音
- [ ] 现状分析
  - [ ] 核对 5 号面板当前 final 音频/视频拼接逻辑，确认无字幕时段是否保留原音
  - [ ] 明确现有实现与用户目标的差异，并给出代码出处
- [ ] 功能点设计
  - [ ] 设计“仅处理 selected_subtitles 命中的说话段，其余区间直接使用原音”的高效拼接方案
  - [ ] 评估对开启/关闭人声分离、带/不带 BGM、resume 的影响范围
- [ ] 风险与决策
  - [ ] 确认是否需要新增开关，还是保持 5 号面板默认行为升级
  - [ ] 确认 final SRT、ASS、视频换轨、烧录字幕是否仍复用同一时间轴合同
- [ ] 实施
  - [ ] 严格按确认后的 Spec 落地
- [ ] 验证
  - [ ] 增加覆盖“长静音/无字幕区保留原音”的测试
  - [ ] 提供可验证证据

## 130. 2026-05-21 5 号面板 OmniVoice 按钮异常置灰修复
- [x] 调研
  - [x] 确认前端置灰由 `src/subtitle_maker/static/js/omnivoiceDubbingPanel.js` 的 `syncStartButtonState()` 控制
  - [x] 确认后端 `/omnivoice/auto/backend-status` 依赖 `src/subtitle_maker/omnivoice_dub_api.py::_ensure_omnivoice_backend_ready(...)`
  - [x] 确认 OmniVoice 探活仍直接走 `urllib.request.urlopen(...)`，与 6 号面板此前的本地代理误判模式一致
- [x] 实施
  - [x] 只修改 5 号面板 OmniVoice 本机探活链路，不改按钮前端逻辑
  - [x] 让本机 `127.0.0.1/localhost` OmniVoice health/model status 检查显式绕过系统代理
- [x] 验证
  - [x] `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_omnivoice_health_checks_bypass_proxy_for_local_backend`
  - [x] `./.venv/bin/python -m py_compile src/subtitle_maker/omnivoice_dub_api.py tests/test_dubbing_cli_api.py`
- [x] Review
  - [x] 根因已确认是 5 号面板 OmniVoice 本机探活错误走了系统代理，导致 `/omnivoice/auto/backend-status` 返回 `ready=false`，前端把“生成译文 / 开始配音”一起置灰
  - [x] 已在 `src/subtitle_maker/omnivoice_dub_api.py` 对本机 OmniVoice health/model status 检查显式禁用代理，并补 `tests/test_dubbing_cli_api.py::test_omnivoice_health_checks_bypass_proxy_for_local_backend`

## 131. 2026-05-21 5 号面板 OmniVoice /generate 请求仍走代理修复
- [x] 调研
  - [x] 确认失败日志来自 `src/subtitle_maker/omnivoice_dub_api.py::_call_remote_generate(...)`
  - [x] 确认 `_call_remote_generate(...)` 仍使用 `requests.post(...)` 默认代理环境，未复用本机直连策略
- [x] 实施
  - [x] 只修改 5 号面板 OmniVoice `/generate` 本机请求链路，不影响远端 URL
  - [x] 让本机 `127.0.0.1/localhost` 的 `requests` 调用显式关闭环境代理
- [x] 验证
  - [x] `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_omnivoice_generate_bypasses_proxy_for_local_backend tests.test_dubbing_cli_api.DubbingCliApiTests.test_omnivoice_health_checks_bypass_proxy_for_local_backend`
  - [x] `./.venv/bin/python -m py_compile src/subtitle_maker/omnivoice_dub_api.py tests/test_dubbing_cli_api.py`
- [x] Review
  - [x] 根因已确认是 5 号面板只修了本机探活，未修正式 `/generate` 请求，导致 `requests` 仍读取系统代理并把流量转发到 `127.0.0.1:1082`
  - [x] 已在 `src/subtitle_maker/omnivoice_dub_api.py` 为本机 OmniVoice `requests.Session()` 显式设置 `trust_env=False` 且清空 `proxies`
  - [x] 已补 `tests/test_dubbing_cli_api.py::test_omnivoice_generate_bypasses_proxy_for_local_backend`

## 126. 2026-05-21 新增一键重启脚本 restart.sh
- [x] 调研
  - [x] 确认现有 `start.sh` / `stop.sh` 的职责与执行方式
- [x] 实施
  - [x] 新增复用 `stop.sh` + `start.sh` 的 `restart.sh`
- [x] 验证
  - [x] 语法校验 `bash -n restart.sh`
- [x] Review
  - [x] `restart.sh` 不重复实现服务管理，只串联现有停启脚本

## 127. 2026-05-21 6 号面板 VoxCPM unstable 自动拆小重试
- [x] 现状分析
  - [x] 确认报错发生在 6 号面板 `_call_voxcpm_tts(...)` 单句合成阶段
  - [x] 确认当前 pre-TTS 拆句后，仍存在少量句子会触发 VoxCPM `Please shorten the text or try again`
- [x] 实施
  - [x] 只修改 6 号面板链路，不影响 5 号面板
  - [x] 新增针对 VoxCPM unstable 500 的自动拆小重试逻辑
  - [x] 子句级重试成功后，在后端内拼回单段音频，避免整批任务直接失败
- [x] 验证
  - [x] `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_voxcpm_tts_unstable_error_retries_with_smaller_chunks`
  - [x] `./.venv/bin/python -m py_compile src/subtitle_maker/voxcpm_dub_api.py tests/test_dubbing_cli_api.py`
- [x] Review
  - [x] VoxCPM 现在遇到明确的 unstable/please shorten 报错时，会自动按更小语义单元重试，而不是直接让整批失败

## 128. 2026-05-21 6 号面板清理污染的 segment 目录
- [x] 现状分析
  - [x] 确认失败批次中 `manifest.selected_subtitles_tts_rows[101]` 与 `segments/segment_0101/manifest.json` 文本不一致
  - [x] 确认当前批次目录可能残留旧 run / 旧 resume 的 segment 结果，导致编号与文本漂移
- [x] 实施
  - [x] 新任务非 resume 时，进入 `_run_voxcpm_job(...)` 前清空旧生成产物，但保留 `uploaded_speaker_refs/`
  - [x] resume 时只保留“当前字幕仍匹配且被判定可复用”的 segment，删除其余脏目录
- [x] 验证
  - [x] `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_reset_voxcpm_output_for_fresh_run_preserves_uploaded_refs tests.test_dubbing_cli_api.DubbingCliApiTests.test_prune_voxcpm_resume_segments_removes_stale_dirs`
  - [x] `./.venv/bin/python -m py_compile src/subtitle_maker/voxcpm_dub_api.py tests/test_dubbing_cli_api.py`
- [x] Review
  - [x] 6 号面板现在不会再把旧 segment 残留和当前 selected_subtitles_tts_rows 混在同一个 batch 目录里

## 129. 2026-05-21 6 号面板剥离 Markdown 样式标记
- [x] 现状分析
  - [x] 确认失败批次 `selected_subtitles_rebuild.srt` 中存在 `**世界...`、纯 `**` 这类 Markdown 残留
  - [x] 确认这类文本会直接流入 `selected_subtitles_tts_rows`
- [x] 实施
  - [x] 在 6 号面板内部字幕归一化阶段剥离 `**`、`__`、反引号等 Markdown 样式标记
  - [x] 过滤掉仅剩样式符号的空行，避免生成纯 `**` 字幕段
- [x] 验证
  - [x] `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_normalize_voxcpm_internal_rows_strips_markdown_emphasis_and_drops_empty_marker_rows`
  - [x] `./.venv/bin/python -m py_compile src/subtitle_maker/voxcpm_dub_api.py tests/test_dubbing_cli_api.py`
- [x] Review
  - [x] 6 号面板 rebuild/TTS 不再吃到 Markdown 加粗残留，像 `**世界...` 会还原成正常正文，纯 `**` 行会被丢弃

## 125. 2026-05-21 6 号面板 Start 按钮异常置灰修复
- [x] 现状分析
  - [x] 复现 6 号面板开始按钮置灰条件，并确认前端唯一控制点
  - [x] 对比 `/voxcpm/auto/backend-status` 与 `http://127.0.0.1:7860/api/health` 的真实返回差异
  - [x] 定位是前端锁死、后端探活误判，还是本机自动拉起链路异常
- [x] 实施
  - [x] 只修 6 号面板 backend ready 判定链路，不影响 5 号面板
  - [x] 让本机 VoxCPM health check 对冷启动/瞬时断连更稳，避免按钮被误灰
- [x] 验证
  - [ ] 通过本地接口验证 `/voxcpm/auto/backend-status` 能恢复 `ready=true`
  - [ ] 验证 6 号面板开始按钮恢复可点击
- [x] Review
  - [x] 记录根因、改动点与验证证据
  - [x] 根因已确认是 6 号面板后端探活错误走了本地代理，`curl http://127.0.0.1:7860/api/health` 成功，而旧版 Python `urllib` 请求失败
  - [x] 已在 `src/subtitle_maker/voxcpm_dub_api.py` 对本机地址显式禁用代理，并补 `tests/test_dubbing_cli_api.py::test_voxcpm_http_json_bypasses_proxy_for_local_backend`

## 124. 2026-05-20 6 号面板播客脚本真值字幕与粤语翻译解耦修复
- [x] 功能点确认
  - [x] 只修改 6 号面板链路，不影响 5 号面板
  - [x] 播客脚本解析后的源内容必须完整保留，并与原播客脚本文字内容一致
  - [x] `selected_subtitles.srt` 继续作为解析后源内容真值，不能再被粤语翻译结果覆盖或裁断
  - [x] 任何目标语翻译都必须基于这份完整真值执行，翻译结果与后续配音消费的数据使用独立副本，不反向污染 `selected_subtitles.srt`
  - [x] 必须额外落盘 `selected_subtitles_translated.srt` 作为翻译后的证据文件，供用户直接核对翻译结果
  - [x] 对 `Chinese -> Chinese` 继续保持直通，不调用翻译 API
- [x] 风险与决策
  - [x] 把 6 号面板的“源真值字幕”与“翻译/配音工作字幕”拆成两份独立文件合同
  - [x] 只在明显 `[Error] / 更正说明` 型脏输出时启用激进翻译清洗，正常长粤语段落整段保留
  - [x] resume / manifest / artifact 全部继续围绕 TTS 工作副本恢复，但对用户暴露源真值与翻译真值两份证据文件
  - [x] 把 final 阶段的 `rebuild` 短句拆分前移到翻译前，让翻译工作副本先按完整句切短，再逐句翻译回填
  - [x] 保留现有 final rebuild 给剪辑使用；翻译前 rebuild 单独实现“完整句优先”规则，不再复用 final rebuild 的 20 字硬拆语义
- [x] 实施
  - [x] 在 `src/subtitle_maker/voxcpm_dub_api.py` 新增 `selected_subtitles_translated.srt` 落盘、manifest 路径与 artifact 暴露
  - [x] 在 `src/subtitle_maker/voxcpm_dub_api.py` 新增 `selected_subtitles_rebuild.srt` 落盘，并让翻译输入优先消费这份短句工作副本
  - [x] 调整 `_translate_subtitles_if_needed(...)` 返回“源真值 rows + 翻译 rows + mode”
  - [x] 调整 6 号面板翻译清洗逻辑，避免长粤语整段被截成单句
  - [x] 调整 `_run_voxcpm_job(...)`，让 `selected_subtitles.srt` 固定保留源真值，TTS 只消费翻译副本或源真值副本
- [x] 验证
  - [x] `./.venv/bin/python -m py_compile src/subtitle_maker/voxcpm_dub_api.py tests/test_dubbing_cli_api.py`
  - [x] `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_voxcpm_translate_subtitles_if_needed_preserves_speaker_ids tests.test_dubbing_cli_api.DubbingCliApiTests.test_voxcpm_translate_subtitles_if_needed_sanitizes_reused_translated_rows tests.test_dubbing_cli_api.DubbingCliApiTests.test_voxcpm_translate_subtitles_if_needed_retries_latin_dominant_rows_for_cantonese_target tests.test_dubbing_cli_api.DubbingCliApiTests.test_voxcpm_translate_subtitles_if_needed_keeps_full_cantonese_paragraph tests.test_dubbing_cli_api.DubbingCliApiTests.test_voxcpm_translate_subtitles_if_needed_skips_translation_for_chinese_source_to_chinese tests.test_dubbing_cli_api.DubbingCliApiTests.test_voxcpm_translate_subtitles_if_needed_skips_translation_for_cantonese_source_to_cantonese tests.test_dubbing_cli_api.DubbingCliApiTests.test_voxcpm_selected_subtitles_stays_original_while_tts_copy_splits tests.test_dubbing_cli_api.DubbingCliApiTests.test_voxcpm_run_job_writes_translated_selected_subtitles_separately tests.test_dubbing_cli_api.DubbingCliApiTests.test_run_voxcpm_job_subtitle_only_builds_natural_srt_and_black_video tests.test_dubbing_cli_api.DubbingCliApiTests.test_run_voxcpm_job_splits_long_rows_before_tts_and_keeps_speaker_ids`
- [x] Review
  - [x] 6 号面板现在固定输出 `selected_subtitles.srt` 作为解析后源真值，发生翻译时额外输出 `selected_subtitles_translated.srt`
  - [x] 6 号面板长粤语整段翻译不再被清洗器截成一句，配音使用翻译副本或其 TTS 工作副本，不再污染源真值字幕
  - [x] 6 号面板翻译前 `selected_subtitles_rebuild.srt` 已改为“完整句优先 + 相邻短句可合并”的工作副本，不再复用 final 阶段 20 字硬拆

## 123. 2026-05-20 6 号面板新增 1080x1440 (3:4) 字幕视频规格
- [x] 现状分析
  - [x] 确认后端 `VOXCPM_SUBTITLE_VIDEO_LAYOUTS` / `_normalize_voxcpm_subtitle_video_preset(...)` 当前仅支持 3 个规格
  - [x] 确认前端下拉与 Video Variants 列表都需要显式新增 1080x1440 选项
- [x] 实施
  - [x] 在 6 号面板后端新增 `1080x1440` layout 参数
  - [x] 扩展 6 号面板 video preset 归一逻辑，识别 `1080x1440 / 3:4`
  - [x] 更新前端下拉和 Video Variants 列表
- [x] 验证
  - [x] `./.venv/bin/python -m py_compile src/subtitle_maker/voxcpm_dub_api.py tests/test_dubbing_cli_api.py`
  - [x] `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_build_voxcpm_centered_ass_from_rows_supports_three_four_layout tests.test_dubbing_cli_api.DubbingCliApiTests.test_build_voxcpm_centered_ass_from_rows_supports_portrait_layout tests.test_dubbing_cli_api.DubbingCliApiTests.test_build_voxcpm_centered_ass_from_rows_supports_four_three_layout`
- [x] Review
  - [x] 6 号面板初始生成与 Video Variants 补生成都能选择 `1080x1440 (3:4)`

## 122. 2026-05-20 6 号面板 selected_subtitles 还原为原始播客解析内容
- [x] 现状分析
  - [x] 确认 `selected_subtitles.srt` 当前主链路写的是原始选中字字幕，但 restore / 视频补生成链路仍残留旧中间文件语义
  - [x] 确认 resume / load-batch / artifact 已改为以 manifest 内的 `selected_subtitles_tts_rows` 作为 TTS 工作副本来源
  - [x] 确认长句拆分里残留 `strip()` 会吞英文句间空格，破坏“仅分段，不改文本内容”合同
- [x] 实施
  - [x] 把 `selected_subtitles.srt` 固定为原始解析/翻译后的选中字字幕，不再承载 TTS 工作副本
  - [x] 把 TTS 长句拆分结果仅保留在内存和 manifest 的 `selected_subtitles_tts_rows`
  - [x] 清理 6 号面板 manifest / restore / 视频补生成中残留的 `selected_subtitles_pre_tts` / `selected_subtitles_tts` 文件路径依赖
  - [x] 去掉 pre-TTS 拆分链路会改写文本的 `strip()`，确保分段拼回原文逐字一致
- [x] 验证
  - [x] `./.venv/bin/python -m py_compile src/subtitle_maker/voxcpm_dub_api.py tests/test_dubbing_cli_api.py`
  - [x] `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_voxcpm_podcast_script_content_survives_pre_tts_split tests.test_dubbing_cli_api.DubbingCliApiTests.test_split_voxcpm_long_text_before_tts_keeps_spaces_inside_english_phrases tests.test_dubbing_cli_api.DubbingCliApiTests.test_split_voxcpm_long_podcast_row_groups_complete_sentences_only tests.test_dubbing_cli_api.DubbingCliApiTests.test_run_voxcpm_job_splits_long_rows_before_tts_and_keeps_speaker_ids tests.test_dubbing_cli_api.DubbingCliApiTests.test_voxcpm_selected_subtitles_stays_original_while_tts_copy_splits`
- [x] Review
  - [x] 6 号面板现在保证 `selected_subtitles.srt` 保留原始播客解析内容，实际配音文本只做无损分段，拼回去与原文逐字一致

## 121. 2026-05-20 6 号面板 selected_subtitles 语义纠正
- [x] 实施
  - [x] 把 `selected_subtitles.srt` 改回“原始选中字字幕”语义，不再回写 pre-TTS 拆分结果
  - [x] 新增 `selected_subtitles_tts.srt` 作为 VoxCPM TTS 工作副本，承载长句拆分后的内容
  - [x] 让 manifest/artifacts/download/resume 全部优先消费 `selected_subtitles_tts.srt`
- [x] 验证
  - [x] `./.venv/bin/python -m py_compile src/subtitle_maker/voxcpm_dub_api.py tests/test_dubbing_cli_api.py`
  - [x] `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_run_voxcpm_job_splits_long_rows_before_tts_and_keeps_speaker_ids tests.test_dubbing_cli_api.DubbingCliApiTests.test_voxcpm_selected_subtitles_stays_original_while_tts_copy_splits tests.test_dubbing_cli_api.DubbingCliApiTests.test_load_voxcpm_batch_marks_failed_batch_resumable_from_selected_subtitles tests.test_dubbing_cli_api.DubbingCliApiTests.test_resume_voxcpm_task_requeues_failed_batch`
- [x] Review
  - 用户现在看到的 `selected_subtitles.srt` 不会再是“二创后的 TTS 中间文件”
  - 内部配音继续使用 `selected_subtitles_tts.srt`，不影响已有长句拆分策略

## 120. 2026-05-19 6 号面板播客字幕内容一致性审计
- [x] 调研
  - [x] 直接解析 `/Users/tim/Downloads/podcast-/哈佛iLab四个U框架-单人播客.md`，确认解析器当前保留“我今天想聊...”等开头正文
  - [x] 对比历史 `selected_subtitles.srt`，确认用户反馈的是文字内容缺失，不是格式/时间戳差异
- [x] 实施
  - [x] 在 6 号面板输出目录新增 `selected_subtitles_pre_tts.srt`，记录翻译/直通后、pre-TTS 拆分前的选中字幕真值
  - [x] 在 manifest/artifacts/download 映射中暴露 `selected_srt_pre_tts`
  - [x] 修正 pre-TTS 完整句重组时英文句末接中文缺空格的问题
- [x] 验证
  - [x] `./.venv/bin/python -m py_compile src/subtitle_maker/voxcpm_dub_api.py tests/test_dubbing_cli_api.py`
  - [x] `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_run_voxcpm_job_splits_long_rows_before_tts_and_keeps_speaker_ids tests.test_dubbing_cli_api.DubbingCliApiTests.test_voxcpm_podcast_script_content_survives_pre_tts_split tests.test_dubbing_cli_api.DubbingCliApiTests.test_split_voxcpm_long_text_before_tts_keeps_spaces_inside_english_phrases tests.test_dubbing_cli_api.DubbingCliApiTests.test_split_voxcpm_long_podcast_row_groups_complete_sentences_only`
- [x] Review
  - 当前后端用该 md 复现为 `parsed=8`、`split=33`，split 第 1 条仍包含“我今天想聊一个可能会让很多创业者不舒服的事实”
  - 新批次可直接检查 `selected_subtitles_pre_tts.srt` 判断内容是否在 pre-TTS 拆分前已经缺失

## 119. 2026-05-19 6 号面板播客脚本长字幕行拆分纠偏
- [x] 实施
  - [x] 将 6 号面板 pre-TTS 拆分从“显示换行/长度硬切”纠正为“播客脚本长字幕行的完整句分段”
  - [x] 拆分只允许落在完整句边界：中文 `。！？；`，英文 `.?!;`
  - [x] 禁止按逗号、顿号、连接词或长度在句子内部硬切，保留英文词间空格
  - [x] 相邻短完整句允许合并，降低 VoxCPM TTS API 调用次数
- [x] 验证
  - [x] `./.venv/bin/python -m py_compile src/subtitle_maker/voxcpm_dub_api.py tests/test_dubbing_cli_api.py`
  - [x] `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_run_voxcpm_job_splits_long_rows_before_tts_and_keeps_speaker_ids tests.test_dubbing_cli_api.DubbingCliApiTests.test_split_voxcpm_long_text_before_tts_keeps_spaces_inside_english_phrases tests.test_dubbing_cli_api.DubbingCliApiTests.test_split_voxcpm_long_text_before_tts_prefers_punctuation_boundaries tests.test_dubbing_cli_api.DubbingCliApiTests.test_split_voxcpm_mixed_text_breaks_on_english_period_before_chinese tests.test_dubbing_cli_api.DubbingCliApiTests.test_split_voxcpm_long_podcast_row_groups_complete_sentences_only`
- [x] Review
  - 6 号面板现在会先把播客脚本长行按“完整句”拆成较少的 TTS 段，再把这些段写回 `selected_subtitles.srt`
  - `Ideas are everywhere. They're worthless.` 这类短完整句组不会再被按连接词或字数切碎
  - `因为交税无可避免，所以会计行业、QuickBooks、TurboTax全都是从这里衍生出来的。` 会保持为一整句，不会再出现 `从这 / 里衍生出来的`

## 118. 2026-05-19 Speaker 前缀支持全角冒号
- [x] 实施
  - [x] 在 [src/subtitle_maker/domains/subtitles/speakers.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/subtitles/speakers.py) 扩展 `strip_speaker_prefix()` 的正则，让 `Speaker 1:` 和 `Speaker 1：` 都能被剥离
  - [x] 在 [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 补回归测试，锁住全角冒号前缀也不会被喂进 6 号面板 TTS
- [x] 验证
  - [x] `./.venv/bin/python -m py_compile src/subtitle_maker/domains/subtitles/speakers.py tests/test_dubbing_cli_api.py` 通过
  - [x] `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_start_voxcpm_from_project_strips_fullwidth_speaker_prefix_before_passthrough` 通过（1 test, OK）
- [x] Review
  - [src/subtitle_maker/domains/subtitles/speakers.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/subtitles/speakers.py) 的 speaker 前缀正则现在同时支持半角 `:` 和全角 `：`
  - 这意味着 6 号面板无论字幕正文写成 `Speaker 1: ...` 还是 `Speaker 1：...`，都会先剥掉标签，再把净正文送进 TTS
  - [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 已锁住全角冒号场景，避免后续再回归

## 117. 2026-05-19 6 号面板直通时先剥离 Speaker 前缀
- [x] 实施
  - [x] 在 [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 让 `source_subtitles_json` / `translated_subtitles_json` 在进入 6 号面板主链路前先经过 `normalize_subtitles_with_speakers(...)`
  - [x] 确保“同语种直通跳过翻译”时，也不会把正文里的 `Speaker 1:` 标签直接喂给 TTS
  - [x] 在 [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 补回归测试，锁住 `Speaker 1:` 会被剥掉但 `speaker_id` 仍然保留
- [x] 验证
  - [x] `./.venv/bin/python -m py_compile src/subtitle_maker/voxcpm_dub_api.py tests/test_dubbing_cli_api.py` 通过
  - [x] `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_start_voxcpm_from_project_strips_speaker_prefix_before_passthrough tests.test_dubbing_cli_api.DubbingCliApiTests.test_voxcpm_translate_subtitles_if_needed_skips_translation_for_cantonese_source_to_cantonese` 通过（2 tests, OK）
- [x] Review
  - [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 现在会在 6 号面板接收项目字幕 JSON 后，先统一剥离正文里的 `Speaker N:` 前缀，再进入 speaker 检测、跳过翻译和配音链路
  - 这意味着即使你把 `Source Language` 明确设成 `Cantonese`，走“同语种直通”不翻译，TTS 也不会再把 `Speaker 1:` 读出来
  - [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 已锁住这个直通场景，避免后续再回归

## 116. 2026-05-19 6 号面板字幕改回白字
- [x] 实施
  - [x] 在 [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 把 6 号面板 ASS 的 `PrimaryColour` 从黑色改回白色，保留 `Outline=4`
  - [x] 在 [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 更新样式断言，锁住白字 + `Outline=4`
- [x] 验证
  - [x] `./.venv/bin/python -m py_compile src/subtitle_maker/voxcpm_dub_api.py tests/test_dubbing_cli_api.py` 通过
  - [x] `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_build_voxcpm_centered_ass_from_rows_wraps_lines_and_uses_typewriter_dialogues` 通过（1 test, OK）
- [x] Review
  - [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 的 6 号面板字幕已改回白字 `&H00FFFFFF`
  - `Outline=4`、黑色描边和半透明青色底条都保持不变，因此当前组合是“白字 + 粗黑描边 + 透明青色底条”
  - [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 已锁住白字颜色值和 `,4,4,0,5,` 样式片段

## 115. 2026-05-19 6 号面板去掉 Source Language 的 Auto
- [x] 实施
  - [x] 在 [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html) 删除 6 号面板 `Source Language` 的 `Auto Detect` 选项
  - [x] 在 [src/subtitle_maker/static/js/voxcpmDubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/voxcpmDubbingPanel.js) 把 `source_lang` 的前端默认回退从 `auto` 改成明确语言值
  - [x] 在 [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 把 6 号面板接口的 `source_lang` 默认值从 `auto` 改成明确语言值，和前端保持一致
- [x] 验证
  - [x] `./.venv/bin/python -m py_compile src/subtitle_maker/voxcpm_dub_api.py` 通过
- [x] Review
  - [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html) 的 6 号面板 `Source Language` 已去掉 `Auto Detect`，现在首项就是 `Chinese`
  - [src/subtitle_maker/static/js/voxcpmDubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/voxcpmDubbingPanel.js) 与 [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 的默认值也同步改成了明确语言，避免前端没选值时又回退成 `auto`
  - 这次只改 6 号面板，没有动 5 号面板

## 114. 2026-05-19 6 号面板字幕改回黑字并加粗描边
- [x] 实施
  - [x] 在 [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 把 6 号面板 ASS 的 `PrimaryColour` 改回黑色，并把 `Outline` 从 `2` 调成 `4`
  - [x] 在 [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 更新样式断言，锁住黑字 + `Outline=4`
- [x] 验证
  - [x] `./.venv/bin/python -m py_compile src/subtitle_maker/voxcpm_dub_api.py tests/test_dubbing_cli_api.py` 通过
  - [x] `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_build_voxcpm_centered_ass_from_rows_wraps_lines_and_uses_typewriter_dialogues` 通过（1 test, OK）
- [x] Review
  - [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 的 6 号面板字幕现在改成黑字 `&H00000000`，并把描边粗细提升到 `Outline=4`
  - 半透明青色底条 `&HEEFFFF00` 保持不变，因此当前组合是“黑字 + 粗黑描边 + 透明青色底条”
  - [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 已锁住样式片段 `,4,4,0,5,` 与黑字颜色值

## 113. 2026-05-19 6 号面板字幕字体加黑色描边
- [x] 实施
  - [x] 在 [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 把 6 号面板 ASS 的 `Outline` 从 `0` 调成 `2`，保留现有黑色 `OutlineColour`
  - [x] 在 [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 更新样式断言，锁住描边粗细
- [x] 验证
  - [x] `./.venv/bin/python -m py_compile src/subtitle_maker/voxcpm_dub_api.py tests/test_dubbing_cli_api.py` 通过
  - [x] `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_build_voxcpm_centered_ass_from_rows_wraps_lines_and_uses_typewriter_dialogues` 通过（1 test, OK）
- [x] Review
  - [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 的 6 号面板字幕样式现在是橘色字 `&H0033A5FF` + 黑色描边 `OutlineColour=&H00000000` + 半透明青色底条 `&HEEFFFF00`
  - 描边粗细已设为 `Outline=2`，不改布局、字号和打字机效果
  - [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 已锁住样式片段 `,4,2,0,5,`，避免后续回退成无描边版本

## 112. 2026-05-19 5/6 号面板统一同语种跳过翻译
- [x] 实施
  - [x] 在 [src/subtitle_maker/translator.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/translator.py) 新增统一语言归一 helper，把 `Chinese/Cantonese/English/Japanese/Spanish/...` 规整成稳定语言标签
  - [x] 在 [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 把跳过翻译规则收敛成“明确同语种直通”；仅 `Chinese <- auto` 继续保留中文文本启发式，`Cantonese <- auto` 不再误跳过
  - [x] 在 [src/subtitle_maker/omnivoice_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/omnivoice_dub_api.py) 接入同样的同语种直通逻辑
  - [x] 在 [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 补 5/6 号面板的 `English -> English` 回归测试，锁住非中文语种也不会再重复计费翻译
- [x] 验证
  - [x] `./.venv/bin/python -m py_compile src/subtitle_maker/translator.py src/subtitle_maker/voxcpm_dub_api.py src/subtitle_maker/omnivoice_dub_api.py tests/test_dubbing_cli_api.py` 通过
  - [x] `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_voxcpm_translate_subtitles_if_needed_skips_translation_for_english_source_to_english tests.test_dubbing_cli_api.DubbingCliApiTests.test_omnivoice_translate_subtitles_if_needed_skips_translation_for_english_source_to_english tests.test_dubbing_cli_api.DubbingCliApiTests.test_voxcpm_translate_subtitles_if_needed_skips_translation_for_cantonese_source_to_cantonese` 通过（3 tests, OK）
- [x] Review
  - [src/subtitle_maker/translator.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/translator.py) 现在提供统一语言归一 helper，把 UI/接口里的 `Chinese/Cantonese/Cantonese-Mainland/English/...` 收敛成稳定 tag，供后端复用
  - [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 与 [src/subtitle_maker/omnivoice_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/omnivoice_dub_api.py) 现在都支持“明确同语种直通”：`English -> English`、`Cantonese -> Cantonese`、`Chinese -> Chinese` 等都不会再走翻译 API
  - 只有 `source_lang=auto` 时，当前仍只对 `target_lang=Chinese` 保留“中文文本启发式直通”；这避免了 `target=Cantonese` 但 source 实际是普通话文本时被误判成无需翻译

## 111. 2026-05-19 粤语 source 字幕配粤语时跳过翻译计费
- [x] 实施
  - [x] 在 [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 扩展 `_should_passthrough_source_rows_without_translation(...)`，让 `Cantonese/Cantonese-Mainland` 目标语在 source 已是粤语时直接复用原文，不再调用翻译 API
  - [x] 保持这条直通仍会经过 6 号面板现有的字幕清洗与 speaker 保留逻辑，只跳过外部翻译计费
  - [x] 在 [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 补回归测试，锁住 `source_lang=粤语, target_lang=Cantonese` 不会实例化 Translator
- [x] 验证
  - [x] `./.venv/bin/python -m py_compile src/subtitle_maker/voxcpm_dub_api.py tests/test_dubbing_cli_api.py` 通过
  - [x] `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_voxcpm_translate_subtitles_if_needed_skips_translation_for_cantonese_source_to_cantonese` 通过（1 test, OK）
- [x] Review
  - [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 现在支持“同语种直通”：当 source 明确是粤语，target 是 `Cantonese/Cantonese-Mainland` 时，6 号面板会直接复用原文，不再走翻译 API
  - 这条直通只跳过外部翻译计费，不会绕过现有的字幕清洗、speaker 保留和后续配音链路
  - [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 已锁住粤语 source -> 粤语 target 不应实例化 `Translator`

## 110. 2026-05-19 6 号面板字幕字体改为橘色
- [x] 实施
  - [x] 在 [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 把 6 号面板 ASS 的 `PrimaryColour` 从白色改成橘色
  - [x] 在 [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 更新样式断言，锁住新的字体颜色值
- [x] 验证
  - [x] `./.venv/bin/python -m py_compile src/subtitle_maker/voxcpm_dub_api.py tests/test_dubbing_cli_api.py` 通过
  - [x] `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_build_voxcpm_centered_ass_from_rows_wraps_lines_and_uses_typewriter_dialogues` 通过（1 test, OK）
- [x] Review
  - [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 的 6 号面板 ASS 主字幕颜色现在从 `&H00FFFFFF` 改成了橘色 `&H0033A5FF`
  - 底条仍保持更透明的青色 `&HEEFFFF00`，只改字体颜色，不动字号、布局和打字机效果
  - [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 已锁住橘色字体值，避免后续回退

## 109. 2026-05-19 6 号面板 final 带 speaker SRT 时间戳全 0 修复
- [x] 实施
  - [x] 在 [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 修复 `_build_speaker_prefixed_rows(...)` 对 `start_sec/end_sec` manifest 的兼容，避免 final 带 speaker SRT 回退成全 0 时间戳
  - [x] 同文件把 `_compose_natural_sequence_mix(...)` 产出的 `final_rows` 补上 `speaker_id`，并让 `dubbed_final_full_with_speakers.srt` 直接复用 final 重建后的时间轴，而不是继续吃 segment 原始窗
  - [x] 在 [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 补断言，锁住 `dubbed_final_full_with_speakers.srt` 的时间戳应与 final SRT 一致递增
- [x] 验证
  - [x] `./.venv/bin/python -m py_compile src/subtitle_maker/voxcpm_dub_api.py tests/test_dubbing_cli_api.py` 通过
  - [x] `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_run_voxcpm_job_subtitle_only_builds_natural_srt_and_black_video` 通过（1 test, OK）
- [x] Review
  - [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 现在会在 final 自然拼接阶段把 `speaker_id` 一起带进重建后的 `final_rows`
  - 同文件导出 `dubbed_final_full_with_speakers.srt` 时，已改为直接对 `final_rows_for_output` 加 speaker 前缀，因此时间戳会与 `dubbed_final_full.srt` 保持一致，不再出现全 0 或回落到 segment 原始窗
  - [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 已锁住 final 带 speaker SRT 与主 final SRT 的时间轴一致性

## 108. 2026-05-19 6 号面板字幕 bar 透明度继续下调
- [x] 实施
  - [x] 在 [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 把 6 号面板 ASS 底条 `BackColour` 调成更透明的青色
  - [x] 在 [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 更新样式断言，锁住新的 alpha 值
- [x] 验证
  - [x] `./.venv/bin/python -m py_compile src/subtitle_maker/voxcpm_dub_api.py tests/test_dubbing_cli_api.py` 通过
  - [x] `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_build_voxcpm_centered_ass_from_rows_wraps_lines_and_uses_typewriter_dialogues` 通过（1 test, OK）
- [x] Review
  - [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 的 6 号面板 ASS 底条现在从 `&HCCFFFF00` 调成了 `&HEEFFFF00`
  - 这次改动的本质是把 ASS alpha 提高到 `EE`，按 ASS 语义会比之前更透明，不再像上一次那样偏实
  - [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 已锁住新值，避免再回退

## 107. 2026-05-19 翻译 API 连接失败不再伪造 Error 字幕
- [x] 实施
  - [x] 在 [src/subtitle_maker/translator.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/translator.py) 去掉 `translate_batch(...)` 的 `[Error] 原文` 伪字幕回退，改为抛出明确的翻译 provider 异常
  - [x] 保持 6 号面板翻译阶段在 provider 不可用时直接失败，让前端显示真实错误，而不是继续产出带 `[Error]` 的 `selected_subtitles.srt`
  - [x] 在 [tests/test_dubbing_runtime.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_runtime.py) 补运行时回归测试，锁住连接失败会抛错而不是返回假字幕
- [x] 验证
  - [x] `./.venv/bin/python -m py_compile src/subtitle_maker/translator.py tests/test_dubbing_runtime.py` 通过
  - [x] `./.venv/bin/python -m unittest tests.test_dubbing_runtime.DubbingPipelineTests.test_translator_translate_batch_raises_provider_error_instead_of_error_subtitles` 通过（1 test, OK）
- [x] Review
  - [src/subtitle_maker/translator.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/translator.py) 现在在翻译 provider 请求失败时会抛出 `TranslationProviderError`，不再把异常吞掉并伪造 `[Error] 原文` 结果
  - 这意味着 6 号面板如果翻译 API 连接失败、超时或上游异常，会直接进入失败态并显示真实错误，而不会再把错误文本写进 `selected_subtitles.srt`
  - [tests/test_dubbing_runtime.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_runtime.py) 已锁住“连接失败 -> 抛明确 provider 错误”的行为，避免后续又回退成假字幕

## 106. 2026-05-19 6 号面板粤语 selected_subtitles 英文残留兜底修复
- [x] 实施
  - [x] 在 [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 为 6 号面板 source->translate 链路补上英文主导译文二次重译，避免 `[Error] ...` 或整句英文直接写入 `selected_subtitles.srt`
  - [x] 统一 6 号面板直接复用 `translated` 字幕时的目标语后处理，确保粤语复用态和新翻译态都走同一套清洗/规整
  - [x] 在 [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 补回归测试，锁住 Cantonese 目标语下英文残留行会被重试替换
- [x] 验证
  - [x] `./.venv/bin/python -m py_compile src/subtitle_maker/voxcpm_dub_api.py tests/test_dubbing_cli_api.py` 通过
  - [x] `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_voxcpm_translate_subtitles_if_needed_retries_latin_dominant_rows_for_cantonese_target tests.test_dubbing_cli_api.DubbingCliApiTests.test_voxcpm_translate_subtitles_if_needed_sanitizes_reused_translated_rows` 通过（2 tests, OK）
- [x] Review
  - [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 现在会把 6 号面板中文目标语翻译结果中的“英文主导漏译行”识别出来，并做一次更严格的定向重译；像 `[Error] During sex...` 这类结果不会再直接写进 `selected_subtitles.srt`
  - 同文件新增了 6 号面板统一字幕后处理 helper，因此不论是“直接复用 translated 字幕”还是“source->translate 新翻译”，都会走同一套 `sanitize + 粤语口语规整`，避免恢复态和新任务行为漂移
  - [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 已锁住 Cantonese 目标语下“首次返回英文错误行、二次重试返回粤语”的回归场景，后续再回退会直接测出来

## 105. 2026-05-19 6 号面板黑底字幕视频改为半透明青色 bar
- [x] 实施
  - [x] 在 [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 的 `_build_voxcpm_centered_ass_from_rows(...)` 把 6 号面板 ASS 样式改为白字 + 半透明青色底条
  - [x] 使用 `BorderStyle=4` 启用底条盒子，并把 `BackColour` 改成半透明青色，保持视频底色仍为黑色
  - [x] 在 [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 补最小断言，锁住新样式值
- [x] 验证
  - `./.venv/bin/python -m py_compile src/subtitle_maker/voxcpm_dub_api.py tests/test_dubbing_cli_api.py` 通过
  - `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_build_voxcpm_centered_ass_from_rows_wraps_lines_and_uses_typewriter_dialogues tests.test_dubbing_cli_api.DubbingCliApiTests.test_run_voxcpm_job_simplified_variant_converts_cantonese_final_outputs` 通过（2 tests, OK）
- [x] Review
  - [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 现在会把 6 号面板字幕视频 ASS 样式写成“黑底视频 + 白字 + 更淡的半透明青色底条”，并保留现有中间打字机效果
  - 这次只改了 6 号面板 ASS 模板，不改视频底色、不新增前端控件；因此初次生成和后续补生成的视频规格都会自动套用同一套半透明青色 bar 样式
  - [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 已锁住 `BackColour=&HCCFFFF00` 与 `BorderStyle=4` 这两个关键样式值，避免后续回退成无底条版本

## 104. 2026-05-19 6 号面板 final 额外导出 20 字限长的 rebuild SRT
- [x] 实施
  - [x] 在 [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 的 final 阶段新增 `dubbed_final_full-rebuild.srt`
  - [x] 复用 [src/subtitle_maker/omnivoice_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/omnivoice_dub_api.py) 的 final SRT 重构算法，并在 6 号面板固定 `max_chars=20`
  - [x] 把 `dubbed_final_full-rebuild.srt` 接入 manifest 路径与 `srt_rebuild` artifact
- [x] 验证
  - `./.venv/bin/python -m py_compile src/subtitle_maker/voxcpm_dub_api.py tests/test_dubbing_cli_api.py` 通过
  - `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_run_voxcpm_job_subtitle_only_builds_natural_srt_and_black_video tests.test_dubbing_cli_api.DubbingCliApiTests.test_load_voxcpm_batch_restores_task_view` 通过（2 tests, OK）
- [x] Review
  - [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 现在会在生成 `dubbed_final_full.srt` 后，额外生成 `dubbed_final_full-rebuild.srt`；它复用了 5 号面板的 final SRT 重构算法，把长句拆到每条最多 20 个字，并按文本长度重新估算更细的时间戳
  - 同文件的 manifest / artifact 合同已新增 `dubbed_final_srt_rebuild` 路径和 `srt_rebuild` 下载项，因此 6 号面板结果区与 `load-batch` 都能看到并恢复这份新字幕文件
  - [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 已锁住 rebuild 文件生成、20 字限长、时间戳单调递增和 manifest 暴露新路径这几个关键合同

## 103. 2026-05-19 播客脚本解析跳过括号包裹的一句话总结标记
- [x] 实施
  - [x] 在 [src/subtitle_maker/domains/subtitles/podcast_script.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/subtitles/podcast_script.py) 扩展跳过规则，让 `(**一句话总结：**)` 与 `（**一句话总结：**）` 这类包裹形式也被视为非配音标记
  - [x] 在 [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 新增回归测试，锁住这类标记不会混入解析结果
- [x] 验证
  - `./.venv/bin/python -m py_compile src/subtitle_maker/domains/subtitles/podcast_script.py tests/test_dubbing_cli_api.py` 通过
  - `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_parse_voxcpm_podcast_script_skips_parenthesized_one_line_summary_marker tests.test_dubbing_cli_api.DubbingCliApiTests.test_parse_voxcpm_podcast_script_supports_multi_speaker_markdown tests.test_dubbing_cli_api.DubbingCliApiTests.test_parse_voxcpm_podcast_script_supports_role_header_and_body_on_next_line` 通过（3 tests, OK）
- [x] Review
  - [src/subtitle_maker/domains/subtitles/podcast_script.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/subtitles/podcast_script.py) 现在会把 `(**一句话总结：**)` 和 `（**一句话总结：**）` 视为非正文块，和原来的 `**一句话总结：**` 一样直接跳过
  - [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 已锁住这条格式，不会再把“一句话总结”标记混进 6 号面板的解析预览或后续配音正文

## 101. 2026-05-19 6 号面板中文播客脚本配中文时跳过翻译计费
- [x] 实施
  - [x] 在 [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 的 `_translate_subtitles_if_needed(...)` 增加“中文 source -> Chinese target”直通逻辑，并把判断放在翻译 API key 校验之前
  - [x] 增加保守中文文本启发式；当 `source_lang=Chinese` 时直接直通，`source_lang=auto` 时仅在字幕文本明显以中文为主时才跳过翻译
  - [x] 在 [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 补定向测试，锁住“中文播客脚本配中文不应调用翻译 API”
- [x] 验证
  - `./.venv/bin/python -m py_compile src/subtitle_maker/voxcpm_dub_api.py tests/test_dubbing_cli_api.py` 通过
  - `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_voxcpm_translate_subtitles_if_needed_skips_translation_for_chinese_source_to_chinese tests.test_dubbing_cli_api.DubbingCliApiTests.test_voxcpm_translate_subtitles_if_needed_preserves_speaker_ids tests.test_dubbing_cli_api.DubbingCliApiTests.test_voxcpm_translate_subtitles_if_needed_sanitizes_reused_translated_rows` 通过（3 tests, OK）
- [x] Review
  - [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 现在会在 6 号面板 `source` 模式下优先判断“是否中文 source -> Chinese target”；命中时直接复用原文字幕，不再调用翻译 API，也不会再要求翻译 key
  - 同文件的直通分支只做原文 `strip()`，不会误套译文清洗规则，因此原有中文标点和像 `AI` 这样的字母词会被完整保留
  - [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 已锁住这条合同，避免后续回退成“中文播客脚本配中文仍然走翻译计费”

## 102. 2026-05-19 6 号面板完成后支持补生成其他字幕视频规格
- [x] 实施
  - [x] 在 [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 扩展 manifest / artifact 合同，持久化 `subtitle_video_variants`、`generated_subtitle_video_presets` 与 `preferred_video_artifact_key`
  - [x] 新增 `POST /voxcpm/auto/render-video-variant`，对已完成批次按指定 preset 只重做 ASS 与黑底字幕视频，不重跑配音
  - [x] 在 [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html) 与 [src/subtitle_maker/static/js/voxcpmDubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/voxcpmDubbingPanel.js) 新增 `Video Variants` 区，已生成规格置灰，未生成规格可点击补生成
- [x] 验证
  - `./.venv/bin/python -m py_compile src/subtitle_maker/voxcpm_dub_api.py tests/test_dubbing_cli_api.py` 通过
  - `node --check src/subtitle_maker/static/js/voxcpmDubbingPanel.js` 通过
  - `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_load_voxcpm_batch_restores_task_view tests.test_dubbing_cli_api.DubbingCliApiTests.test_render_voxcpm_video_variant_generates_new_preset_without_rerunning_tts tests.test_dubbing_cli_api.DubbingCliApiTests.test_render_voxcpm_video_variant_skips_existing_preset` 通过（3 tests, OK）
- [x] Review
  - [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 现在把 6 号面板字幕视频规格当成一组独立后处理产物来管理：主规格继续保留默认 `dubbed_video_full.mp4` / `dubbed_final_full-styled.ass`，补生成规格则写成 `dubbed_video_full-{preset}.mp4` / `dubbed_final_full-styled-{preset}.ass`，不会覆盖原产物
  - 同文件新增 `render-video-variant` 接口，只读取已完成批次的 final SRT + final mix 重新生成 ASS/黑底视频，不重跑翻译、不重跑配音；已存在规格会直接返回当前状态，不重复生成
  - manifest 现在会持久化 `subtitle_video_variants`、`generated_subtitle_video_presets` 与 `preferred_video_artifact_key`，因此 `load-batch` 后前端能稳定知道哪些规格已生成、哪个视频应优先播放
  - [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html)、[src/subtitle_maker/static/js/voxcpmDubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/voxcpmDubbingPanel.js)、[src/subtitle_maker/static/style.css](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/style.css) 已新增 `Video Variants` 结果区：已生成规格置灰，不可重复点；新补生成成功后下载列表和上方播放器会立即刷新到该规格

## 96. 2026-05-19 6 号面板新增播客脚本上传与解析
- [x] 现状
  - [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html) 的 6 号面板目前只有 `Current Project / Setup / Speaker Refs / Restore / Run` 五块，没有单独的“播客脚本上传”控件；当前入口假设字幕已经存在于项目态里
  - [src/subtitle_maker/static/js/voxcpmDubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/voxcpmDubbingPanel.js) 的 `renderProjectSummary()`、`getEffectiveSubtitleRows()`、`buildCurrentProjectRequest()` 当前只会从 `getProjectDubbingContext()` 里读取 `sourceSubtitles / translatedSubtitles`，再把它们透传成 `source_subtitles_json / translated_subtitles_json`
  - [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 的 `start_voxcpm_from_project(...)` 只接受已经结构化好的 `source_subtitles_json / translated_subtitles_json`，没有接收“播客脚本原文件”或“播客脚本文本”的后端入口
  - 6 号面板当前的 speaker 检测逻辑来自 [src/subtitle_maker/static/js/voxcpmDubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/voxcpmDubbingPanel.js) 的 `normalizeSpeakerIdsForPanelRows()` / `getDetectedSpeakerIds()`，它要求上游已经有 `speaker_id` 或至少能从现有字幕顺序继承 speaker；因此如果播客脚本不能先解析成带 `speaker_id` 的字幕行，后面的 Speaker Refs UI 就不会正常工作
  - 现有字幕解析主能力集中在 [src/subtitle_maker/transcriber.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/transcriber.py) 的 `parse_srt(...)` 和 [src/subtitle_maker/app/routes/subtitles.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/app/routes/subtitles.py) 的上传字幕路由，当前是面向 SRT / JSON 字幕，不是面向 Markdown 播客脚本
  - `/Users/tim/Downloads/podcast-/OpenAI超级应用与AGI起飞-播客脚本.md` 是双人播客格式：有标题、素材来源、章节标题、音乐/情绪舞台提示，以及正文角色行 `**Larei:**【情绪=...】...` / `**Tensor:**【情绪=...】...`
  - `/Users/tim/Downloads/podcast-/OpenAI超级应用与AGI起飞-单人播客.md` 与 `/Users/tim/Downloads/podcast-/哈佛iLab四个U框架-单人播客.md` 是单人播客格式：同样有标题、元信息、音乐提示、制作备注表，但正文基本只有 `**Larei:**【情绪=...】...`
  - 这 3 个样例共同特征是：真正要进配音链路的内容都在 `**角色名:**【情绪=...】正文` 这种行里；像 `# 标题`、`> 素材来源`、`---`、`## 章节`、`（音乐...）`、`(**顿悟预告：**)`、`## 制作备注`、Markdown 表格都属于应跳过的非配音内容
- [x] 功能点
  - 在 [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html) 的 6 号面板新增一个独立的 `Podcast Script` 卡片，不和 `Current Project` 绑死。
  - 该卡片至少要有：
    - 一个上传 `.md / .txt` 播客脚本文件的控件
    - 一个解析按钮
    - 一个简短预览区，展示解析到的 speaker 数和台词行数
    - 一个状态提示，告诉用户当前是“优先使用项目字幕”还是“优先使用播客脚本解析结果”
  - 解析目标不是生成带时间戳的 SRT，而是先生成 6 号面板可直接消费的“结构化字幕行草稿”：
    - `text`
    - `speaker_id`
    - 可选保留 `emotion` / `stage_direction` 作为 sidecar 元数据，供后续调试或 prompt 使用
    - `start / end` 先不要求真实时间轴；6 号面板本来就走自然时长重建 final timeline
  - 解析规则按样例收敛：
    - 匹配 `**角色名:**【情绪=...】正文`
    - 匹配 `**角色名:** 正文`
    - 允许同一角色正文跨多行续写，直到遇到下一个角色头或明显的非正文块
    - 跳过标题、素材来源、章节标题、分隔线、音乐提示、顿悟预告、制作备注表格等非配音内容
    - 单人播客默认解析成单一 `speaker_id`
    - 双人播客按脚本里的角色名稳定映射到 speaker
  - 6 号面板解析完成后，应把结果灌进当前面板自己的“临时字幕上下文”，这样后续已有链路可以继续复用：
    - Speaker Refs 根据解析出的 `speaker_id` 刷新上传槽位
    - `Start VoxCPM Dubbing` 可以直接把解析结果作为 `source_subtitles_json`
    - 若当前项目里已经有 `translatedSubtitles`，需要明确优先级，避免脚本结果被静默覆盖
  - 推荐优先级合同：
    - 若用户已成功解析播客脚本，则 6 号面板优先使用脚本解析结果
    - 若没有脚本解析结果，才回退 `Current Project` 的 `translatedSubtitles / sourceSubtitles`
    - 不要把脚本解析结果全局写回其他面板；先限定在 6 号面板本地状态
  - 后端需要新增一个轻量解析入口，接收播客脚本文本并返回结构化台词行，而不是要求前端自己做复杂 Markdown 解析。
  - 返回合同建议至少包括：
    - `rows`
    - `speaker_ids`
    - `detected_mode`：`single` / `multi`
    - `title`
    - `source_label`
    - `skipped_blocks_count`
  - 改动边界：
    - 本轮只解决“上传并解析播客脚本进入 6 号面板”
    - 不要求给播客脚本自动生成真实时间戳
    - 不要求修改 1 号、4 号、5 号面板
    - 不要求把情绪标签真正接入 VoxCPM 推理参数，先解析保留即可
- [x] 风险与决策
  - 风险 1：如果把播客脚本解析放在前端做，Markdown 规则一旦扩展，状态机会散落在 [src/subtitle_maker/static/js/voxcpmDubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/voxcpmDubbingPanel.js) 里，后续测试和恢复都会很难做。
    - 推荐：解析主逻辑放后端，前端只负责上传、触发和展示结果。
  - 风险 2：如果把解析结果直接写回全局 `Current Project` 字幕状态，会影响 1/4/5 号面板，并让“播客脚本”与“项目字幕”语义混在一起。
    - 推荐：先限定为 6 号面板本地状态，只在 6 号面板启动请求里透传。
  - 风险 3：如果强行给播客脚本伪造时间戳，会制造一种“像字幕但不是真字幕”的假象，后续所有按时间处理的逻辑都会被污染。
    - 推荐：本轮完全不生成真实时间轴；6 号面板继续沿用“自然时长生成后再重建 final timeline”的现有合同。
  - 风险 4：样例里的情绪标签、音乐提示、顿悟预告都属于脚本语义，但并不等于应该朗读的文本；如果不明确边界，容易把舞台说明念出来。
    - 推荐：只朗读角色台词行；音乐提示、章节标题、制作备注等全部跳过；情绪标签只保留成 sidecar，不进 `text`。
  - 风险 5：双人稿和单人稿混用同一套解析时，如果 speaker 识别不稳定，会直接影响 Speaker Refs 上传槽位和最终多 speaker 配音。
    - 推荐：角色名作为权威 speaker 键，不再二次猜测；例如 `Larei`、`Tensor` 原样映射到 `speaker_id`。
  - 风险 6：如果 6 号面板同时存在“项目字幕”和“脚本解析结果”，但优先级不明确，用户会看到解析成功却实际没被用上。
    - 推荐：显式规则固定为“脚本解析结果优先，项目字幕兜底”，并在 UI 提示当前实际使用源。
  - 关键决策 1：解析入口放哪里
    - 选项 A：前端 JS 直接解析 Markdown
    - 选项 B：后端新增解析接口
    - 推荐：选项 B
    - 理由：更容易测试、复用和维护，也符合现有 6 号面板“前端只组装状态，后端做核心处理”的结构。
  - 关键决策 2：解析结果的生命周期
    - 选项 A：写回全局项目态
    - 选项 B：只保留在 6 号面板本地态
    - 推荐：选项 B
    - 理由：最小化影响范围，避免把“播客脚本”误当成通用字幕格式污染其他面板。
  - 关键决策 3：speaker_id 的命名
    - 选项 A：保留原角色名，如 `Larei / Tensor`
    - 选项 B：统一改写成 `Speaker 1 / Speaker 2`
    - 推荐：选项 A
    - 理由：Speaker Refs 界面直接显示角色名更可读，也能减少双人播客里“谁是谁”的映射心智负担。
  - 关键决策 4：情绪标签的处理
    - 选项 A：直接拼进要朗读的正文
    - 选项 B：只做 sidecar 元数据保留
    - 推荐：选项 B
    - 理由：当前 6 号面板没有稳定消费情绪标签的 TTS 合同，先保留结构，不污染正文。
  - 关键决策 5：启动链路如何复用现有实现
    - 选项 A：为播客脚本另起一套 start API
    - 选项 B：解析完成后仍走现有 `start-from-project`，只是把脚本结果填进 `source_subtitles_json`
    - 推荐：选项 B
    - 理由：可以最大限度复用 6 号面板已有 Speaker Refs、resume、results、final render 链路。
  - 推荐实现方案
    - 后端新增一个播客脚本解析 helper 和 `/voxcpm/auto/parse-podcast-script` 接口
    - 前端 6 号面板新增 `Podcast Script` 卡片，支持上传、解析、预览、清空
    - 前端维护 6 号面板本地 `parsedPodcastRows / parsedPodcastSpeakerIds / parsedPodcastMeta`
    - `buildCurrentProjectRequest()` 优先发送脚本解析结果；若为空再回退当前项目字幕
    - Speaker Refs 检测逻辑改成优先读脚本解析结果，再读项目字幕
    - 增加定向测试，锁住双人/单人脚本解析、非正文块跳过、角色名 speaker 保留，以及 6 号面板启动优先级合同
- [x] 实施
  - [x] 新增 [src/subtitle_maker/domains/subtitles/podcast_script.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/subtitles/podcast_script.py)，实现播客脚本 Markdown 解析 helper，并导出到 [src/subtitle_maker/domains/subtitles/__init__.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/subtitles/__init__.py)
  - [x] 在 [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 新增 `/voxcpm/auto/parse-podcast-script` 接口，接收 `.md/.txt` 脚本并返回结构化台词行
  - [x] 在 [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html) 的 6 号面板新增 `Podcast Script` 卡片和上传/解析/清空控件
  - [x] 在 [src/subtitle_maker/static/js/voxcpmDubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/voxcpmDubbingPanel.js) 增加本地 `parsedPodcastRows / parsedPodcastSpeakerIds / parsedPodcastMeta` 状态，并把启动优先级改成“脚本解析结果优先，项目字幕兜底”
  - [x] 让 Speaker Refs 与 6 号面板概览区优先读取脚本解析结果，从而直接按 `Larei / Tensor` 这类角色名刷新上传槽位
- [x] 验证
  - `node --check src/subtitle_maker/static/js/voxcpmDubbingPanel.js` 通过
  - `./.venv/bin/python -m py_compile src/subtitle_maker/domains/subtitles/podcast_script.py src/subtitle_maker/domains/subtitles/__init__.py src/subtitle_maker/voxcpm_dub_api.py tests/test_dubbing_cli_api.py` 通过
  - `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_parse_voxcpm_podcast_script_supports_multi_speaker_markdown tests.test_dubbing_cli_api.DubbingCliApiTests.test_parse_voxcpm_podcast_script_supports_single_speaker_markdown tests.test_dubbing_cli_api.DubbingCliApiTests.test_start_voxcpm_from_project_accepts_parsed_podcast_rows tests.test_dubbing_cli_api.DubbingCliApiTests.test_start_voxcpm_from_project_allows_zero_uploaded_speaker_refs` 通过（4 tests, OK）
- [x] Review
  - [src/subtitle_maker/domains/subtitles/podcast_script.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/subtitles/podcast_script.py) 现在会只抽取 `**角色名:**【情绪=...】正文` 这类台词行，跳过标题、章节、音乐提示、顿悟预告和制作备注表格；双人稿保留角色名作为 `speaker_id`，单人稿则稳定输出单 speaker
  - 同文件会为每条播客脚本台词生成一段“估算朗读时长”，只供 6 号面板自然配音入口使用；这不是对外承诺的真实字幕时间轴
  - [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 新增 `parse-podcast-script` 接口，前端不需要自己解析 Markdown
  - [src/subtitle_maker/static/js/voxcpmDubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/voxcpmDubbingPanel.js) 增加了播客脚本本地状态、解析摘要展示和清空逻辑；一旦解析成功，`buildCurrentProjectRequest()` 会优先把脚本结果作为 `source_subtitles_json` 送进现有 6 号面板启动链路
  - [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html) 的 6 号面板新增独立 `Podcast Script` 卡片，和 `Current Project` 分离，符合“只在 6 号面板本地生效”的边界
  - [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html)、[src/subtitle_maker/static/js/voxcpmDubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/voxcpmDubbingPanel.js)、[src/subtitle_maker/static/style.css](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/style.css) 已补紧凑预览区：解析成功后默认展示前 4 条台词，可展开查看全部，固定高度滚动，不再出现“解析成功但看不到解析后文本”的问题

## 95. 2026-05-19 翻译结果混入模型说明性废话清洗
- [x] 现状
  - [src/subtitle_maker/translator.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/translator.py) 的 `_is_translation_noise_line(...)` 只会过滤“独立成行”的说明文字，但如果模型把解释、自我纠正和最终译文混在同一行里，当前不会被剥掉
  - [src/subtitle_maker/translator.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/translator.py) 的 `translate_batch(...)` 当前只做编号解析和粤语规整，没有做“正文级脏译文清洗”
  - [src/subtitle_maker/omnivoice_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/omnivoice_dub_api.py) 与 [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 在“直接复用 translated 字幕”分支会原样吃已有译文，历史脏行会直接流进最终配音
- [x] 功能点
  - 在共享翻译层新增“译文正文清洗” helper，优先去掉 `But Chinese output only`、`Let's correct in final` 这类模型说明性废话
  - 对中文目标语种增加一个保守的候选提取规则：当同一条输出里混入外语说明和中文候选时，优先保留更像最终中文译文的片段
  - 让 `translate_batch(...)` 在落结果前统一经过该清洗
  - 让 5/6 号面板在“直接复用 translated 字幕”时也再过一遍同样的清洗，避免历史脏译文绕过翻译层
- [x] 风险与决策
  - 决策 1：规则只瞄准明显的模型自言自语和英文说明，不做激进的全局删词，避免误伤正常混排字幕
  - 决策 2：先放在共享翻译层，再由 5/6 号复用译文入口补一道兜底，保证“新翻译”和“历史已翻译字幕”都能受益
  - 决策 3：本轮不改字幕行数、不动时间戳，只清洗单行正文文本
- [x] 实施
  - [x] 在 [src/subtitle_maker/translator.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/translator.py) 新增 `sanitize_translation_text(...)`，清洗 `But Chinese output only`、`Let's correct in final` 这类模型说明尾巴，并在中文目标语下优先提取更像最终译文的中文片段
  - [x] 让 `Translator.translate_batch(...)` 在批量翻译结果落盘前统一经过 `sanitize_translation_text(...)`
  - [x] 在 [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 的“直接复用 translated 字幕”分支和 source->translate 分支都接入同一清洗
  - [x] 在 [src/subtitle_maker/omnivoice_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/omnivoice_dub_api.py) 新增 `_sanitize_translated_rows_for_target(...)`，让 5 号面板直接复用历史译文时也会剥离模型说明性废话
  - [x] 补共享翻译层与 6 号面板译文复用回归测试
- [x] 验证
  - `./.venv/bin/python -m py_compile src/subtitle_maker/translator.py src/subtitle_maker/voxcpm_dub_api.py src/subtitle_maker/omnivoice_dub_api.py tests/test_dubbing_runtime.py tests/test_dubbing_cli_api.py` 通过
  - `./.venv/bin/python -m unittest tests.test_dubbing_runtime.DubbingPipelineTests.test_translator_translate_batch_sanitizes_inline_model_explanations tests.test_dubbing_runtime.DubbingPipelineTests.test_translator_parse_translated_lines_ignores_noise_lines_without_index_shift tests.test_dubbing_cli_api.DubbingCliApiTests.test_voxcpm_translate_subtitles_if_needed_sanitizes_reused_translated_rows tests.test_dubbing_cli_api.DubbingCliApiTests.test_voxcpm_translate_subtitles_if_needed_preserves_speaker_ids tests.test_dubbing_cli_api.DubbingCliApiTests.test_translate_subtitles_if_needed_retries_latin_dominant_rows_for_chinese_target` 通过（5 tests, OK）
- [x] Review
  - [src/subtitle_maker/translator.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/translator.py) 现在会对翻译正文做二次清洗：先去掉显式英文说明尾巴，再在中文目标语场景下，从混合候选里优先挑出真正的中文译文片段
  - 同文件的 `translate_batch(...)` 已统一接入该清洗，所以新发起的翻译批次不会再把这类模型自言自语直接写进译文结果
  - [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 即使直接复用已有 `translated` 字幕，也会先清洗单行正文，再进入 6 号面板配音
  - [src/subtitle_maker/omnivoice_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/omnivoice_dub_api.py) 同样补了历史译文兜底清洗，避免 5 号面板 restore / 复用旧译文时把脏行原样带进最终结果

## 88. 2026-05-17 5 号面板新增 Cantonese-Mainland 目标语
- [x] 现状
  - [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html) 的 5 号面板 `#omnivoice-target` 当前只有 `Chinese / Cantonese / English / ...`，没有“广东式口语 + 简体粤语”目标语选项
  - [src/subtitle_maker/translator.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/translator.py) 的 `_is_cantonese_target_lang()` 与 `_cantonese_prompt_constraints()` 当前把所有粤语目标语统一成“港式口语 + 繁体”约束
  - [src/subtitle_maker/omnivoice_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/omnivoice_dub_api.py) 的 `_normalize_omnivoice_language_pair()` 当前仅支持 `Cantonese -> yue`，没有保留“港式/广东式”两档展示值
  - [src/subtitle_maker/static/js/omnivoiceDubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/omnivoiceDubbingPanel.js) 当前前端提示只区分“是不是粤语”，没有区分港式繁体和广东式简体
- [x] 功能点
  - 在 [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html) 的 5 号面板 `Target Language` 中新增 `Cantonese-Mainland`
  - 在 [src/subtitle_maker/translator.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/translator.py) 中把粤语翻译约束拆成两档：`Cantonese=港式口语+繁体`，`Cantonese-Mainland=广东式口语+简体`
  - 在 [src/subtitle_maker/omnivoice_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/omnivoice_dub_api.py) 中保留展示值 `Cantonese/Cantonese-Mainland`，但 runtime 统一映射到 `yue`
  - 保持 `ref-voices/Cantonese` 作为两种粤语目标语共用的预置参考音目录，不新增 `ref-voices/Cantonese-Mainland`
  - 在 [src/subtitle_maker/static/js/omnivoiceDubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/omnivoiceDubbingPanel.js) 中补两档粤语的前端提示文案
- [x] 风险与决策
  - 决策 1：本次只拆“翻译风格”和“展示值”，不拆 OmniVoice runtime 语言码；两档都继续走 `yue`
  - 决策 2：speaker ref 固定文案本轮仍共用同一条粤语参考句，不扩成港式/广东式两套录音文案
  - 决策 3：`Cantonese-Mainland` 复用 `ref-voices/Cantonese`，避免把翻译风格需求扩大成新的参考音目录合同
- [ ] 实施
  - [x] 更新 5 号面板目标语选项与粤语提示文案
  - [x] 更新翻译 prompt 约束与 OmniVoice 语言规范化
  - [x] 补 `Cantonese-Mainland` 的恢复链路与回归测试
- [x] 验证
  - `node --check src/subtitle_maker/static/js/omnivoiceDubbingPanel.js` 通过
  - `./.venv/bin/python -m py_compile src/subtitle_maker/translator.py src/subtitle_maker/omnivoice_dub_api.py tests/test_dubbing_cli_api.py` 通过
  - `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_translator_build_prompt_distinguishes_two_cantonese_styles tests.test_dubbing_cli_api.DubbingCliApiTests.test_omnivoice_preset_ref_voices_supports_cantonese_mainland_alias tests.test_dubbing_cli_api.DubbingCliApiTests.test_load_omnivoice_batch_preserves_cantonese_mainland_display_lang tests.test_dubbing_cli_api.DubbingCliApiTests.test_run_omnivoice_job_normalizes_cantonese_mainland_to_yue_for_generation tests.test_dubbing_cli_api.DubbingCliApiTests.test_run_omnivoice_job_normalizes_cantonese_to_yue_for_generation` 通过（5 tests, OK）
- [x] Review
  - [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html) 的 5 号面板 `Target Language` 新增 `Cantonese-Mainland`，并明确说明它与 `Cantonese` 的差别只在翻译风格：前者广东式口语 + 简体，后者港式口语 + 繁体
  - [src/subtitle_maker/static/js/omnivoiceDubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/omnivoiceDubbingPanel.js) 新增 `isMainlandCantoneseLanguage(...)` 与粤语风格提示；`load-batch` 会把 `target_lang/source_lang` 回填到 5 号面板表单，避免 restore 后丢失 `Cantonese-Mainland`
  - [src/subtitle_maker/translator.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/translator.py) 把粤语翻译约束拆成两档：`Cantonese=Hong Kong style + Traditional`，`Cantonese-Mainland=Guangdong/Mainland style + Simplified`
  - [src/subtitle_maker/omnivoice_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/omnivoice_dub_api.py) 现在会保留展示值 `Cantonese/Cantonese-Mainland`，但 runtime 统一映射到 `yue`；`Cantonese-Mainland` 仍复用 `ref-voices/Cantonese`
  - [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 新增 `Cantonese-Mainland` 的 prompt/runtime/load-batch/ref-voices 回归，锁住本次合同

## 89. 2026-05-17 粤语翻译 prompt 强化地道词汇与语气约束
- [x] 现状
  - [src/subtitle_maker/translator.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/translator.py) 的 `_cantonese_prompt_constraints(...)` 目前只限制“港式/广东式 + 繁简体 + 避免书面语”，对地道词汇和语气助词约束还不够硬
  - [src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py) 仍保留旧版单一粤语约束，只支持 `Cantonese`，未同步 `Cantonese-Mainland`
  - 如果只改 `translator.py`，会出现“5 号主翻译更地道，但 review redub / 时长改写又退回旧 prompt”的状态裂缝
- [x] 功能点
  - 强化 [src/subtitle_maker/translator.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/translator.py) 的粤语约束，明确要求优先使用地道粤语词汇，如 `嘢 / 唔係 / 咩 / 搞掂 / 呢個 / 咁 / 返工 / 食飯`
  - 在两档粤语约束里都显式写入“绝对禁止书面语或生硬直译”
  - 在两档粤语约束里都显式要求语气自然，允许适量使用 `㗎 / 啫 / 啦 / 呢 / 呀 / 咩`
  - 同步升级 [src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py) 的粤语约束，并补 `Cantonese-Mainland` 识别
- [x] 风险与决策
  - 决策 1：本次只强化 prompt 约束，不做词典级后处理，先以最小改动提高模型输出口味
  - 决策 2：`translator.py` 与 `pipeline.py` 两处约束同步收紧，避免主翻译和改写链路口径漂移
  - 决策 3：示例词汇作为“强偏好”写入 prompt，但不做逐词替换规则，避免误伤语义
- [ ] 实施
  - [x] 更新 `translator.py` 的港式/广东式粤语约束
  - [x] 更新 `pipeline.py` 的粤语识别与改写约束
  - [x] 补定向测试，锁住地道词汇/语气助词/禁书面语约束
- [x] 验证
  - `./.venv/bin/python -m py_compile src/subtitle_maker/translator.py src/subtitle_maker/domains/dubbing/pipeline.py tests/test_dubbing_cli_api.py` 通过
  - `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_cantonese_prompt_enforces_authentic_vocabulary_and_particles tests.test_dubbing_cli_api.DubbingCliApiTests.test_pipeline_cantonese_constraints_distinguish_two_styles tests.test_dubbing_cli_api.DubbingCliApiTests.test_translator_build_prompt_distinguishes_two_cantonese_styles` 通过（3 tests, OK）
- [x] Review
  - [src/subtitle_maker/translator.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/translator.py) 的两档粤语翻译约束已收紧：明确要求优先使用 `嘢 / 唔係 / 咩 / 搞掂 / 呢個(呢个) / 咁 / 返工 / 食飯(食饭)` 等地道粤语词汇，允许自然加入 `㗎 / 啫 / 啦 / 呢 / 呀 / 咩`，并显式禁止书面语和生硬直译
  - [src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py) 已同步升级改写/时长改写链路的粤语约束，并补 `Cantonese-Mainland` 识别，避免 4 号/重写链路回退到旧 prompt
  - [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 新增两组定向断言，锁住两处 prompt 源都包含“地道词汇 / 语气助词 / 禁书面语直译”的硬限制

## 90. 2026-05-17 粤语译文后处理规整
- [x] 现状
  - 仅靠 prompt 约束仍会在 [outputs/dub_jobs/omnivoice_20260517_144446/selected_subtitles.srt](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/outputs/dub_jobs/omnivoice_20260517_144446/selected_subtitles.srt) 里残留大量普通话结构，例如 `了 / 把 / 被 / 这样 / 里 / 给 / 让 / 像 / 着`
  - [src/subtitle_maker/translator.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/translator.py) 与 [src/subtitle_maker/omnivoice_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/omnivoice_dub_api.py) 在翻译结果落盘前都没有粤语专用文本规整层
  - [src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py) 的改写链路也可能把已经口语化的粤语再拉回普通话残留
- [x] 功能点
  - 在 [src/subtitle_maker/translator.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/translator.py) 新增 `normalize_cantonese_translation_text(...)`，专门规整粤语译文中的高频普通话残留
  - 在 [src/subtitle_maker/omnivoice_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/omnivoice_dub_api.py) 的 5 号翻译结果落盘前应用同一规整层
  - 在 [src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py) 的时长改写链路也应用同一规整层，避免后续重写再把粤语拉回书面语
  - 覆盖用户点名的高频模式：`了->咗`、`把->将`、`被->俾`、`这/这样/这里->呢/咁样/呢度`、`里->入面`、`给->俾`、`让->令/等`、`像->好似`、`着->住`
- [x] 风险与决策
  - 决策 1：后处理只改表面文本，不改时间戳、不改 speaker、不改句子数
  - 决策 2：规整层只在粤语目标语生效，不碰中文/英文结果
  - 决策 3：规则先覆盖高频稳定模式，不做过度激进的全局词典替换，避免误伤语义
- [x] 实施
  - [x] 新增粤语译文规整 helper，并接入 `Translator.translate_batch(...)`
  - [x] 接入 5 号面板翻译落盘前规整
  - [x] 接入 4 号面板改写链路规整
  - [x] 补定向测试，锁住常见普通话残留的替换结果
- [x] 验证
  - `./.venv/bin/python -m py_compile src/subtitle_maker/translator.py src/subtitle_maker/domains/dubbing/pipeline.py src/subtitle_maker/omnivoice_dub_api.py tests/test_dubbing_cli_api.py` 通过
  - `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_cantonese_translation_normalizer_rewrites_common_mandarin_residue tests.test_dubbing_cli_api.DubbingCliApiTests.test_cantonese_translation_normalizer_leaves_non_cantonese_unchanged tests.test_dubbing_cli_api.DubbingCliApiTests.test_pipeline_cantonese_constraints_distinguish_two_styles` 通过（3 tests, OK）
- [x] Review
  - [src/subtitle_maker/translator.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/translator.py) 现在会在粤语翻译后做确定性口语规整，优先压掉 `了 / 把 / 被 / 这样 / 里 / 给 / 让 / 像 / 着` 这类普通话结构残留
  - [src/subtitle_maker/omnivoice_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/omnivoice_dub_api.py) 的 5 号字幕落盘会复用同一层规整，确保 `selected_subtitles.srt` 不再直接保留明显的半普半粤形态
  - [src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py) 的改写结果也会走同一层规整，避免后续重写阶段把口语化结果重新拉回书面语

## 91. 2026-05-17 粤语后处理白名单再扩展
- [ ] 现状
  - 现有 [src/subtitle_maker/translator.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/translator.py) 的粤语规整层已经覆盖一批高频普通话残留，但用户最新样本里仍能看到 `断语 / 阅历 / 不好以为 / 可系 / 把孩子送进 / 被年轻嘅领导边缘化` 这类不够口语化的表达
  - 目前测试只覆盖了少量基础替换，还没有把这批新残留锁进回归
- [ ] 功能点
  - 继续扩展 `normalize_cantonese_translation_text(...)` 的白名单规则，优先覆盖用户最近点名的高频不地道表达
  - 补充定向测试，验证港式繁体与广东式简体两档都能吃到这批规整，但不会改动非粤语目标语
- [ ] 风险与决策
  - 决策 1：继续只做文本表面规整，不碰时间戳 / speaker / 句子结构
  - 决策 2：仍然只覆盖高频稳定模式，不做激进全局词典重写，避免误伤语义
- [ ] 实施
  - [x] 扩展 `normalize_cantonese_translation_text(...)` 的高频白名单
  - [x] 补粤语规整定向测试
- [ ] 验证

- [ ] 追加观察
  - 这批新增规则要继续保持“短语级替换优先”，不要把 `也 / 与 / 这种` 直接改成全局字符替换，否则会误伤正常粤语句子

## 92. 2026-05-18 Cantonese-Mainland 改为繁体输出
- [ ] 现状
  - [src/subtitle_maker/translator.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/translator.py) 当前把 `Cantonese-Mainland` 明确约束为 `Prefer Simplified Chinese characters`
  - [src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py) 的粤语重写约束也沿用“广东式口语 + 简体”
  - [src/subtitle_maker/static/js/omnivoiceDubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/omnivoiceDubbingPanel.js) 与 [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html) 对 `Cantonese-Mainland` 的文案仍写成“广东式口语 + 简体粤语”
- [ ] 功能点
  - 把 `Cantonese-Mainland` 的输出字形从简体改为繁体，但保持“广东式口语 / Mainland style”这一档风格语义
  - 同步调整粤语后处理的字形收尾，避免 `呢个 / 食饭` 这类简体字形继续落盘
  - 同步更新 5 号面板文案与测试断言
- [ ] 风险与决策
  - 决策 1：保留 `Cantonese-Mainland` 这个展示值与 `yue` runtime，不改恢复/底座合同
  - 决策 2：本次只收口“字形策略”，不删除 Mainland 风格分档本身
- [ ] 实施
  - [x] 把 `translator.py` / `pipeline.py` 的 Mainland 粤语约束改成繁体输出
  - [x] 把 Mainland 粤语后处理的字形收尾改成繁体落盘
  - [x] 更新 5 号面板文案与测试断言
- [x] 验证
  - `./.venv/bin/python -m py_compile src/subtitle_maker/translator.py src/subtitle_maker/domains/dubbing/pipeline.py src/subtitle_maker/omnivoice_dub_api.py tests/test_dubbing_cli_api.py` 通过
  - `node --check src/subtitle_maker/static/js/omnivoiceDubbingPanel.js` 通过
  - `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_translator_build_prompt_distinguishes_two_cantonese_styles tests.test_dubbing_cli_api.DubbingCliApiTests.test_cantonese_prompt_enforces_authentic_vocabulary_and_particles tests.test_dubbing_cli_api.DubbingCliApiTests.test_pipeline_cantonese_constraints_distinguish_two_styles tests.test_dubbing_cli_api.DubbingCliApiTests.test_cantonese_translation_normalizer_rewrites_common_mandarin_residue tests.test_dubbing_cli_api.DubbingCliApiTests.test_run_omnivoice_job_normalizes_cantonese_mainland_to_yue_for_generation tests.test_dubbing_cli_api.DubbingCliApiTests.test_load_omnivoice_batch_preserves_cantonese_mainland_display_lang` 通过（6 tests, OK）
- [x] Review
  - [src/subtitle_maker/translator.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/translator.py) 现在把 `Cantonese-Mainland` 收口为“广东式口语 + 繁体输出”，不再强制简体示例词和简体 function words
  - [src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py) 的改写/时长重写链路也同步改成繁体，避免主翻译和后续重写口径漂移
  - [src/subtitle_maker/static/js/omnivoiceDubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/omnivoiceDubbingPanel.js) 与 [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html) 已把 Mainland 档文案从“简体粤语”改成“繁体粤语”

## 93. 2026-05-19 6 号面板粤语字幕脚本默认繁体、可切简体
- [x] 现状
  - [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html) 的 6 号面板已经有 `Subtitle Script` 相关控件，但当前语义需要收紧到“只在粤语时显示”
  - [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 里 final 字幕脚本转换逻辑原本对所有中文都可能生效，需要只在 `target_lang = Cantonese` 时启用
  - [src/subtitle_maker/static/js/voxcpmDubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/voxcpmDubbingPanel.js) 需要按目标语切换控件显隐，避免 Chinese 也受这个脚本开关影响
- [x] 功能点
  - 6 号面板默认输出繁体粤语，只有手动切到简体时才把最终字幕做繁转简
  - `Chinese` 目标语不显示这个开关，也不走这条转换
  - 最终输出统一从 final render 阶段派生，保持 SRT / ASS / 视频一致
- [x] 风险与决策
  - 决策 1：脚本开关只作用于粤语目标语，不扩散到中文普通话
  - 决策 2：默认值固定繁体，减少粤语结果被普通话式简体污染
  - 决策 3：转换只发生在 final render，避免干扰翻译和配音链路
- [x] 实施
  - [x] 前端仅在粤语目标语下显示 `Cantonese Subtitle Script`
  - [x] 后端仅在粤语 final 渲染时根据开关决定是否繁转简
  - [x] 补粤语繁体/简体转换回归测试
- [x] 验证
  - `node --check src/subtitle_maker/static/js/voxcpmDubbingPanel.js` 通过
  - `./.venv/bin/python -m py_compile src/subtitle_maker/voxcpm_dub_api.py src/subtitle_maker/domains/subtitles/zh_script.py tests/test_dubbing_cli_api.py` 通过
  - `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_convert_chinese_script_rows_supports_cantonese_traditional_and_simplified tests.test_dubbing_cli_api.DubbingCliApiTests.test_run_voxcpm_job_simplified_variant_converts_cantonese_final_outputs` 通过（2 tests, OK）

## 94. 2026-05-19 6 号面板字幕视频支持 16:9 / 9:16 / 4:3
- [x] 现状
  - [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 的 `_build_voxcpm_centered_ass_from_rows()` 当前把 ASS `PlayResX/PlayResY` 写死为 `1920/1080`，样式也固定 `Fontsize=120`、`MarginL/R=140`、`MarginV=80`
  - 同文件的 `_wrap_voxcpm_ass_text_lines()` 当前固定 `max_units_per_line=24`，`_chunk_voxcpm_wrapped_lines()` 固定 `max_lines_per_page=4`，没有按画幅动态调整
  - [src/subtitle_maker/domains/media/compose.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/media/compose.py) 的 `build_black_video_with_ass_subtitles()` 默认 `width=1920`、`height=1080`
  - [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html) 的 6 号面板 Setup 当前没有“字幕视频比例/分辨率”下拉
  - [src/subtitle_maker/static/js/voxcpmDubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/voxcpmDubbingPanel.js) 启动请求也还没有透传输出画幅参数
- [x] 功能点
  - 在 6 号面板新增字幕视频画幅下拉，至少支持：
    - `1920x1080 (16:9)`，保持当前横屏默认
    - `1080x1920 (9:16)`，竖屏
    - `1440x1080 (4:3)`
  - 让 [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 根据所选画幅动态生成 ASS 布局参数，包括但不限于：
    - `PlayResX/PlayResY`
    - `Fontsize`
    - `MarginL/MarginR/MarginV`
    - 每行允许宽度
    - 每页最大行数
  - 让 `build_black_video_with_ass_subtitles()` 吃到对应宽高，输出真正匹配画幅的黑底字幕视频
  - 保证三种画幅下字幕都不会横向越界，也不会因为纵向页数/打字机分页不合理而看不全
  - 恢复 / load-batch / manifest 需要保留该字段，避免历史批次重载后画幅丢失
- [x] 风险与决策
  - 决策 1：不要只改 ffmpeg 输出尺寸，ASS 排版参数必须跟着画幅联动，否则 9:16 和 4:3 仍会出现超界或最后几行看不全
  - 决策 2：三种画幅应共用一套“布局配置表”而不是散落常量，避免后续加新比例时再次复制逻辑
  - 决策 3：默认值保持 `1920x1080 (16:9)`，避免破坏现有用户习惯
- [x] 实施
  - [x] 在 [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html) 的 6 号面板 Setup 新增 `Subtitle Video Aspect` 下拉，支持 `1920x1080 / 1080x1920 / 1440x1080`
  - [x] 在 [src/subtitle_maker/static/js/voxcpmDubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/voxcpmDubbingPanel.js) 启动请求透传 `subtitle_video_preset`，并在 load-batch / status 返回后回填当前选项
  - [x] 在 [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 新增 `VOXCPM_SUBTITLE_VIDEO_LAYOUTS` 统一配置表，并让 ASS 布局、换行宽度、分页行数、黑底视频宽高都按画幅联动
  - [x] 把 `subtitle_video_preset` 接入 6 号面板任务 payload、manifest、load-batch、resume_context 和 resume 重入链路
  - [x] 补三种画幅的 ASS / manifest / 黑底视频宽高定向测试
- [x] 验证
  - `node --check src/subtitle_maker/static/js/voxcpmDubbingPanel.js` 通过
  - `./.venv/bin/python -m py_compile src/subtitle_maker/voxcpm_dub_api.py tests/test_dubbing_cli_api.py` 通过
  - `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_load_voxcpm_batch_restores_task_view tests.test_dubbing_cli_api.DubbingCliApiTests.test_resume_voxcpm_task_requeues_failed_batch tests.test_dubbing_cli_api.DubbingCliApiTests.test_build_voxcpm_centered_ass_from_rows_wraps_lines_and_uses_typewriter_dialogues tests.test_dubbing_cli_api.DubbingCliApiTests.test_build_voxcpm_centered_ass_from_rows_supports_portrait_layout tests.test_dubbing_cli_api.DubbingCliApiTests.test_build_voxcpm_centered_ass_from_rows_supports_four_three_layout tests.test_dubbing_cli_api.DubbingCliApiTests.test_build_voxcpm_centered_ass_from_rows_keeps_full_long_subtitle_visible_before_end tests.test_dubbing_cli_api.DubbingCliApiTests.test_run_voxcpm_job_passes_selected_video_preset_to_black_video_builder` 通过（7 tests, OK）
- [x] Review
  - [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 新增 `DEFAULT_VOXCPM_SUBTITLE_VIDEO_PRESET`、`VOXCPM_SUBTITLE_VIDEO_LAYOUTS`、`_normalize_voxcpm_subtitle_video_preset(...)`、`_get_voxcpm_subtitle_video_layout(...)`，把字幕视频尺寸、字号、边距、每行宽度、每页最大行数集中在一处
  - 同文件的 `_build_voxcpm_centered_ass_from_rows(...)` 不再写死 `1920x1080 / 120`，而是按画幅动态生成 `PlayResX/PlayResY`、`Fontsize`、`MarginL/R/V`；`_build_voxcpm_typewriter_dialogues_with_layout(...)` 负责把换行和分页规则也跟着画幅联动
  - 同文件的 `_run_voxcpm_job(...)` 现在会把所选画幅一路写进 manifest，并在最终 `build_black_video_with_ass_subtitles(...)` 时传入真实 `width/height`，保证黑底视频和 ASS 布局一致
  - [src/subtitle_maker/static/js/voxcpmDubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/voxcpmDubbingPanel.js) 现在会在启动时提交 `subtitle_video_preset`，在加载历史批次或轮询状态时回填当前画幅下拉，避免 restore 后 UI 丢状态
  - [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 新增竖屏 / 4:3 ASS 断言、load-batch / resume 保留画幅字段断言，以及黑底视频构建器收到 `1080x1920` 宽高的断言，锁住本次合同


## 87. 2026-05-17 5 号面板接入粤语配音链路
- [ ] 现状
  - 5 号面板前端已经提供 `Cantonese` 的源语言和目标语言选项，见 [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html) 和 [src/subtitle_maker/static/js/omnivoiceDubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/omnivoiceDubbingPanel.js)
  - OmniVoice 底座明确支持粤语：`Cantonese -> yue`，见 [/Users/tim/Documents/vibe-coding/MVP/OmniVoice/omnivoice/utils/lang_map.py](/Users/tim/Documents/vibe-coding/MVP/OmniVoice/omnivoice/utils/lang_map.py) 与 [/Users/tim/Documents/vibe-coding/MVP/OmniVoice/omnivoice/models/omnivoice.py](/Users/tim/Documents/vibe-coding/MVP/OmniVoice/omnivoice/models/omnivoice.py)
  - 5 号面板当前真正参与 OmniVoice 合成的是 `target_lang`，在 [src/subtitle_maker/omnivoice_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/omnivoice_dub_api.py) 的 `_call_remote_generate(...)` 调用链里以 `language=target_lang` 透传到底座
  - `source_lang` 当前在 5 号面板链路里主要被写入任务 payload / manifest，并未显式接入字幕翻译策略、参考音选择或 OmniVoice 生成参数，见 [src/subtitle_maker/omnivoice_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/omnivoice_dub_api.py) 的 `start_omnivoice_from_project(...)`、`prepare_omnivoice_subtitles_from_project(...)`、`_create_task_payload(...)`
  - 译文翻译层已经有粤语专用约束，会提示输出港式口语、避免普通话书面语，见 [src/subtitle_maker/translator.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/translator.py) 的 `_is_cantonese_target_lang(...)`、`_cantonese_prompt_constraints(...)`、`Translator._build_prompt(...)`
  - 5 号面板缺 speaker 时会按 `ref-voices/<target_lang>/` 自动补预置参考音，见 [src/subtitle_maker/omnivoice_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/omnivoice_dub_api.py) 的 `_resolve_ref_voices_dir(...)` 与 `_pick_preset_ref_voices_for_missing_speakers(...)`
  - 当前仓库本地只有 `/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/ref-voices/Chinese`，没有 `ref-voices/Cantonese`，因此粤语任务若依赖“缺失 speaker 自动补预置参考音”，会因为目录缺失而失败
  - 当前测试覆盖了 OmniVoice 预置参考音填充、prepare/start/resume 等主合同，但还没有“5 号面板粤语链路”专项合同，见 [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py)
- [ ] 功能点
  - 在 [src/subtitle_maker/omnivoice_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/omnivoice_dub_api.py) 新增一层粤语语言规范化 helper，把 `Cantonese / 粤语 / 廣東話 / yue` 统一收敛成同一内部表示，避免 `prepare_omnivoice_subtitles_from_project(...)`、`start_omnivoice_from_project(...)`、`resume_omnivoice_task(...)` 三个入口出现语言写法漂移
  - 让规范化后的目标语言继续沿着现有 `_call_remote_generate(..., language=target_lang)` 路径传到底座，确保 OmniVoice 真正吃到 `yue`
  - 让 `source_lang` 继续作为任务/manifest 的稳定元数据保留，并在恢复任务时原样回放，避免重启后语言语义丢失
  - 保持翻译层现有的粤语专用 prompt 约束，只把目标语言规范化，不额外削弱翻译阶段的港式口语与繁体偏好
  - 对 `ref-voices/<target_lang>/` 的缺失保持显式失败，不做静默跨语种回退；如果任务缺 speaker 且没有粤语预置参考音目录，就直接报出清晰错误，提示用户上传完整 speaker refs 或补齐目录
  - 补一组专项回归测试，锁住 `Cantonese -> yue` 的入口规范化、resume 保持语言语义、以及缺失 `ref-voices/Cantonese` 时的明确报错合同
- [ ] 风险与决策
  - 决策 1：内部规范化只做“语言表示统一”，不改用户 UI 选项文本，避免前端和后端出现两个概念
  - 决策 2：不把粤语自动降级到 `Chinese` 预置参考音池，否则会让参考音语义和目标语种混淆，后续听感问题更难排查
  - 决策 3：`source_lang` 先只做稳定传递与恢复，不在本次改造里强行把它接进 ASR 或重分段逻辑，避免把“粤语输出支持”扩成另一条大改造链路
- [x] 验证
  - `./.venv/bin/python -m py_compile src/subtitle_maker/omnivoice_dub_api.py tests/test_dubbing_cli_api.py` 通过
  - `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_omnivoice_preset_ref_voices_supports_cantonese_alias tests.test_dubbing_cli_api.DubbingCliApiTests.test_run_omnivoice_job_normalizes_cantonese_to_yue_for_generation tests.test_dubbing_cli_api.DubbingCliApiTests.test_build_manifest_includes_styled_ass_artifact_and_path` 通过（3 tests, OK）
  - `node --check src/subtitle_maker/static/js/omnivoiceDubbingPanel.js` 通过
  - `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_validate_preset_ref_voices_available_rejects_empty_cantonese_dir tests.test_dubbing_cli_api.DubbingCliApiTests.test_start_omnivoice_from_project_rejects_partial_cantonese_refs_when_preset_pool_empty` 通过（2 tests, OK）
  - `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_speaker_ref_text_switches_by_target_lang` 通过（1 test, OK）
- [x] Review
  - [src/subtitle_maker/omnivoice_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/omnivoice_dub_api.py) 新增粤语语言规范化 helper：`_normalize_omnivoice_language_pair(...)`、`_is_cantonese_language_variant(...)`、`_resolve_omnivoice_ref_voice_candidates(...)`
  - 5 号面板的 `target_lang` 现在会拆成展示值和运行值，`Cantonese` 会在底座调用时稳定落到 `yue`
  - `source_lang` 继续作为任务/manifest 元数据保留，并在恢复时原样回放，避免重启后语义丢失
  - 缺失 speaker 的预置参考音目录现在支持 `yue` / `Cantonese` 别名解析；不存在对应目录时仍会明确报错，不会静默回退到其他语种
  - [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 新增粤语专项回归：粤语别名参考音目录、`Cantonese -> yue` 合成调用、manifest runtime 字段恢复
  - [src/subtitle_maker/static/js/omnivoiceDubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/omnivoiceDubbingPanel.js) 补充粤语前端提示：目标语选粤语时，会明确提示 `yue` 映射、建议上传粤语参考音，以及缺失 `ref-voices/Cantonese` 时自动补位的依赖条件
  - 5 号面板 partial upload 现在会在启动前校验预置参考音池是否可用，空的 `ref-voices/Cantonese` 不再拖到后台阶段才失败
  - Speaker Refs 的默认参考文本现在会随 `Target Language` 切换：`Chinese` 用普通话文案，`Cantonese` 用粤语文案；前端显示与后端写入保持一致

## 86. 2026-05-16 5 号面板统一支持翻译复用与配音断点续跑
- [x] 现状
  - 5 号面板当前只有 `prepared_batch_id` 级别的窄复用能力，本质是复用 `selected_subtitles.srt`
  - `load-batch` 只能恢复结果视图，不能恢复执行态
  - `_run_omnivoice_job(...)` 每次都从第 1 条字幕整批重跑，不会复用已落盘的 `segment_jobs/segment_XXXX/seg_XXXX.wav`
- [x] 目标
  - 把“翻译复用”和“配音中断续跑”统一为 5 号面板同一套 `resume` 能力
  - 恢复时优先复用已存在的 `selected_subtitles.srt`、speaker refs、stems 和已完成 segment
  - 前端加载 batch 后明确提示是否可从断点继续，而不是只允许查看结果
- [x] 计划
  - 后端新增 OmniVoice `resume` 入口与 checkpoint 探测 helper
  - 扩展 manifest / load-batch 返回合同，暴露 `resumable`、`resume_stage`、`completed_segments`
  - 前端增加“从断点继续配音”入口并接入新接口
  - 补 5 号面板恢复相关定向测试
- [x] 验证
  - 仅有 `selected_subtitles.srt` 的 prepared batch 可直接跳过翻译继续
  - 部分 `seg_XXXX.wav + manifest.json` 已存在时，只继续未完成 segment
  - 已完成任务不会错误显示可恢复
- [x] Review
  - [src/subtitle_maker/omnivoice_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/omnivoice_dub_api.py) 新增 OmniVoice resume 合同：`_infer_resume_state(...)`、`_build_resume_context(...)`、`/omnivoice/auto/resume/{task_id}`，并让 `_run_omnivoice_job(...)` 支持复用 `selected_subtitles`、stems、speaker refs 与已完成 segment
  - [src/subtitle_maker/static/js/omnivoiceDubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/omnivoiceDubbingPanel.js) 在 load-batch 后新增“从断点继续配音 / 跳过翻译继续配音”入口，并根据 `resumable/resume_stage/processed_segments` 动态提示
  - [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html) 的 5 号 Restore 区新增 resume 按钮
  - [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 新增 5 号面板恢复相关回归测试：prepared 可恢复、resume 入队、segment 级跳过已完成条目
  - 验证结果：`./.venv/bin/python -m py_compile src/subtitle_maker/omnivoice_dub_api.py tests/test_dubbing_cli_api.py` 通过；`node --check src/subtitle_maker/static/js/omnivoiceDubbingPanel.js` 通过；`./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_load_omnivoice_batch_marks_prepared_batch_resumable tests.test_dubbing_cli_api.DubbingCliApiTests.test_resume_omnivoice_task_requeues_batch_with_resume_context tests.test_dubbing_cli_api.DubbingCliApiTests.test_run_omnivoice_job_resume_skips_completed_segments tests.test_dubbing_cli_api.DubbingCliApiTests.test_start_omnivoice_from_project_reuses_prepared_selected_subtitles` 通过（4 tests, OK）

## 85. 2026-05-16 5 号面板支持重启后复用已准备好的 selected_subtitles 直接配音
- [x] 现状
  - `preparedBatchId` 只存在 5 号面板前端内存里，页面或后端重启后会丢失
  - 现有 `start-from-project` 依赖前端再次把 `prepared_batch_id` 传回来，否则会重新走翻译/字幕选择流程
  - 用户已经处理完译文后，如果后台断开，再重启时无法直接跳过这一步开始配音
- [x] 目标
  - 允许用户在重启后复用之前已经生成的 `selected_subtitles.srt`
  - 启动配音时优先复用 prepared batch，直接进入 speaker 参考音和配音阶段
  - 如果 prepared batch 已不存在或不匹配当前项目，自动降级为普通启动，避免阻塞
- [x] 计划
  - 前端把 prepared batch 状态持久化到本地存储，并在页面恢复时自动回填
  - 后端继续支持 `prepared_batch_id` 复用已有 `selected_subtitles.srt`
  - 增加“prepared batch 失效自动回退”的回归测试
- [x] 验证
  - 页面重启后仍可恢复之前的 prepared batch
  - 直接点击开始配音时会沿用已准备好的 `selected_subtitles.srt`
  - prepared batch 失效时会自动回退到普通启动，而不是报死错
- [x] Review
  - [src/subtitle_maker/static/js/omnivoiceDubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/omnivoiceDubbingPanel.js) 新增 prepared batch 本地持久化与恢复逻辑，重启后可直接复用前一次已生成的 `selected_subtitles.srt`
  - [src/subtitle_maker/omnivoice_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/omnivoice_dub_api.py) 的 `start-from-project` 继续支持 `prepared_batch_id` 复用；任务 payload 也会记录 `enable_source_separation`
  - 当 prepared batch 失效时，前端会自动清掉缓存并回退一次普通启动，避免用户卡死在旧批次上
  - 验证结果：`node --check src/subtitle_maker/static/js/omnivoiceDubbingPanel.js` 通过；`./.venv/bin/python -m py_compile src/subtitle_maker/omnivoice_dub_api.py tests/test_dubbing_cli_api.py` 通过；`./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_start_omnivoice_from_project_reuses_prepared_selected_subtitles tests.test_dubbing_cli_api.DubbingCliApiTests.test_start_omnivoice_from_project_can_disable_source_separation tests.test_dubbing_cli_api.DubbingCliApiTests.test_prepare_omnivoice_source_stems_passthrough_uses_source_audio_as_vocals` 通过（3 tests, OK）

## 84. 2026-05-16 5 号面板支持手动关闭人声分离
- [x] 现状
  - 5 号面板当前默认且强制先做人声分离，前端没有显式开关
  - `src/subtitle_maker/omnivoice_dub_api.py::_run_omnivoice_job(...)` 会无条件调用 `_prepare_omnivoice_source_stems(...)`
  - 但后续 speaker 参考音、配音和 final 合成链路其实已经支持 `has_bgm_track=False` 的纯 vocals-only 运行方式
- [x] 目标
  - 默认保持开启人声分离
  - 允许用户在 5 号面板手动关闭人声分离，适用于纯人声、无背景音乐素材
  - 关闭后直接把 `source_audio.wav` 作为 `source_vocals.wav`，并明确禁用 BGM 回混
- [x] 计划
  - 前端新增开关并透传 `enable_source_separation`
  - 后端启动接口与任务链路接住该布尔值
  - 新增 passthrough helper 与最小回归测试
- [x] 验证
  - 默认不传时，仍保持现有 separation 主路径
  - 显式 `enable_source_separation=false` 时，会走 passthrough vocals-only 语义
  - `separation_report.json` 能明确区分“主动跳过”与“分离失败降级”
- [x] Review
  - [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html) 的 5 号面板新增“开启人声分离（默认）”开关
  - [src/subtitle_maker/static/js/omnivoiceDubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/omnivoiceDubbingPanel.js) 启动请求新增 `enable_source_separation`
  - [src/subtitle_maker/omnivoice_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/omnivoice_dub_api.py) 新增 `_prepare_omnivoice_source_stems_passthrough(...)`，并把 `enable_source_separation` 接到 `start-from-project`、任务 payload 和 `_run_omnivoice_job(...)`
  - 验证结果：`./.venv/bin/python -m py_compile src/subtitle_maker/omnivoice_dub_api.py tests/test_dubbing_cli_api.py` 通过；`./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_prepare_omnivoice_source_stems_passthrough_uses_source_audio_as_vocals tests.test_dubbing_cli_api.DubbingCliApiTests.test_start_omnivoice_from_project_can_disable_source_separation tests.test_dubbing_cli_api.DubbingCliApiTests.test_prepare_omnivoice_source_stems_dispatches_to_chunked_for_long_video` 通过（3 tests, OK）

## 83. 2026-05-16 翻译漏行重试改为“优先只补缺失编号行”以降低 API 成本
- [x] 现状
  - `src/subtitle_maker/translator.py::_translate_batch_with_split_retry(...)` 当前在单批漏行时直接递归二分重试
  - 该策略能恢复行数，但会重复请求已成功的行，导致异常批次 API 调用次数明显增多
  - 最新实测日志中，`300 -> 299` 的轻微漏行也触发了 `150/75` 级联重试，存在成本冗余
- [x] 目标
  - 保留当前“先保证译文完整度”的收益
  - 对轻微漏行场景优先只重试缺失编号行，避免整半批重翻
  - 仅在缺失过多或补齐失败时，才回退到现有二分重试路径
- [x] 计划
  - 明确“缺失行比例/数量”的阈值，决定走“缺失行补译”还是“二分重试”
  - 设计缺失行补译的编号映射与结果回填逻辑
  - 补回归测试，验证“成本下降 + 完整度不退化”
- [x] 验证
  - 轻微漏行时优先触发缺失编号局部补译
  - 局部补译会把结果按原索引回填，不打乱整批顺序
  - 局部补译不适用或补不齐时，仍会回退到现有二分重试
- [x] Review
  - [src/subtitle_maker/translator.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/translator.py) 新增缺失编号补译相关 helper：`_find_missing_translation_indexes(...)`、`_should_retry_missing_only(...)`、`_build_missing_translation_retry_prompt(...)`、`_retry_missing_lines_with_context(...)`
  - 当前策略变为：默认 `300` 行批量；轻微漏行时优先只补缺失编号行，并携带前后各 1 行上下文；局部补译失败或缺失过多时，才回退到原有二分重试
  - 回归测试已覆盖“优先局部补译”和“必要时回退二分”两种路径，见 [tests/test_dubbing_runtime.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_runtime.py)
  - 验证结果：`./.venv/bin/python -m py_compile src/subtitle_maker/translator.py tests/test_dubbing_runtime.py` 通过；`./.venv/bin/python -m unittest tests.test_dubbing_runtime.DubbingPipelineTests.test_translator_translate_batch_merges_default_and_custom_system_prompt tests.test_dubbing_runtime.DubbingPipelineTests.test_translator_translate_batch_flattens_internal_newlines_in_one_cue tests.test_dubbing_runtime.DubbingPipelineTests.test_translator_translate_batch_uses_default_chunk_size_300 tests.test_dubbing_runtime.DubbingPipelineTests.test_translator_translate_batch_retries_incomplete_batch_by_splitting tests.test_dubbing_runtime.DubbingPipelineTests.test_translator_translate_batch_retries_missing_lines_only_before_split tests.test_dubbing_runtime.DubbingPipelineTests.test_translator_parse_translated_lines_merges_multiline_numbered_blocks tests.test_dubbing_runtime.DubbingPipelineTests.test_translator_parse_translated_lines_ignores_noise_lines_without_index_shift` 通过（7 tests, OK）

## 82. 2026-05-16 字幕翻译批量改为 300 且漏行批自动拆分重试
- [x] 现状
  - `src/subtitle_maker/translator.py::Translator.translate_batch(...)` 当前默认按 `500` 行分批请求翻译接口
  - `src/subtitle_maker/translator.py::_parse_translated_lines(...)` 在编号块解析少于期望行数时，只会记录 warning，并把缺失槽位保留为空字符串
  - `src/subtitle_maker/omnivoice_dub_api.py::_translate_subtitles_if_needed(...)` 后续会把空译文回退成 source 原文，再对英文主导行做小批量补救重译
  - 最新实测日志已出现 `500 -> 483`、`500 -> 498`、`500 -> 499`，说明 500 行批量会显著增加漏行与回退原文概率
- [x] 目标
  - 把默认翻译批量从 500 调整到更稳的 300
  - 对单批 `parsed < expected` 的情况，不直接把缺失行留给后续 source fallback，而是在翻译层先自动拆小重试
  - 保持现有 OmniVoice 后处理兜底仍然存在，作为最后保护而不是主修复路径
- [x] 计划
  - 先明确“漏行批”的检测信号和返回合同
  - 再决定拆分重试策略是固定二分、递归二分还是阶梯降批
  - 最后补翻译层回归测试，锁住“默认 300 + 漏行批自动重试”行为
- [x] 验证
  - `Translator.translate_batch(...)` 默认批量已改为 300
  - 单批编号块解析漏行时，会先在翻译层递归二分重试
  - 拆到最小阈值仍漏行时，仍保留现有后续兜底路径
- [x] Review
  - [src/subtitle_maker/translator.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/translator.py) 新增 `_translate_one_batch(...)` 与 `_translate_batch_with_split_retry(...)`，把“请求、解析、漏行重试”前移到翻译器层
  - `translate_batch(...)` 默认批量从 `500` 调整到 `300`，并在漏行批上递归二分重试，最小自动重试阈值为 `60`
  - [src/subtitle_maker/omnivoice_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/omnivoice_dub_api.py) 的现有空译文回填与 latin-dominant 重试仍保留，语义变成最后兜底而不是主修复路径
  - 验证结果：`./.venv/bin/python -m py_compile src/subtitle_maker/translator.py tests/test_dubbing_runtime.py` 通过；`./.venv/bin/python -m unittest tests.test_dubbing_runtime.DubbingPipelineTests.test_translator_translate_batch_merges_default_and_custom_system_prompt tests.test_dubbing_runtime.DubbingPipelineTests.test_translator_translate_batch_flattens_internal_newlines_in_one_cue tests.test_dubbing_runtime.DubbingPipelineTests.test_translator_translate_batch_uses_default_chunk_size_300 tests.test_dubbing_runtime.DubbingPipelineTests.test_translator_translate_batch_retries_incomplete_batch_by_splitting tests.test_dubbing_runtime.DubbingPipelineTests.test_translator_parse_translated_lines_merges_multiline_numbered_blocks tests.test_dubbing_runtime.DubbingPipelineTests.test_translator_parse_translated_lines_ignores_noise_lines_without_index_shift` 通过（6 tests, OK）

## 81. 2026-05-16 5 号面板长视频分段改为 40 分钟附近灵活切分
- [x] 现状
  - `src/subtitle_maker/omnivoice_dub_api.py::_build_omnivoice_chunk_ranges(...)` 当前只支持按固定块长硬切，默认参数来自 `OMNIVOICE_LONG_VIDEO_CHUNKED_SEPARATION_CHUNK_SEC`
  - `src/subtitle_maker/omnivoice_dub_api.py::_prepare_omnivoice_source_stems_chunked(...)` 会严格使用这些 range 做抽音和 Demucs 分离，不会再根据语音活动调整边界
  - `src/subtitle_maker/domains/media/compose.py::compose_vocals_master(...)` 当前只是按时间轴把各块结果直接写回，没有 overlap/crossfade 边界融合
  - 因此如果切点落在人声连续段中间，边界附近的分离质量和后续 speaker reference 质量都可能受影响
- [x] 目标
  - 保持“超过 90 分钟才走分段 separation”的阈值不变
  - 保持“40 分钟是目标块长”这个性能方向，但切点允许在目标附近灵活调整
  - 优先把切点避开正在说话的连续活跃区，降低边界截断对后续配音质量的影响
- [x] 计划
  - 先确认现有代码里哪些输入可用于切点搜索，以及搜索应放在哪个函数
  - 再定义“40 分钟附近”的可调整窗口、静音优先级和兜底规则
  - 最后决定是否只做智能切点，还是同时引入轻量 overlap
- [x] 验证
  - 长视频分段仍保持 `> 90 分钟` 才进入 chunked separation
  - 默认目标块长改为 `40 分钟`，但实际切点允许在窗口内偏移
  - 切点优先级为“静音/低能量 > 字幕边界 > speaker 切换点”
- [x] Review
  - [src/subtitle_maker/omnivoice_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/omnivoice_dub_api.py) 新增智能切块 helper：`_build_omnivoice_cut_hint_points(...)`、`_analyze_omnivoice_split_window(...)`、`_pick_omnivoice_adaptive_split_point(...)`、`_build_omnivoice_chunk_plan(...)`
  - 5 号面板 chunked separation 现在会基于 `source_audio.wav` 在目标切点前后搜索静音/低能量位置，再尽量吸附到附近字幕边界；`speaker_id` 只作为字幕边界并列决胜条件，不再当主锚点
  - `separation_report.json` 的 `ranges[]` 现已包含 `target_end_sec`、`actual_end_sec`、`split_reason`、`snapped_to_boundary`、`snapped_to_speaker_change`
  - 验证结果：`./.venv/bin/python -m py_compile src/subtitle_maker/omnivoice_dub_api.py tests/test_dubbing_cli_api.py` 通过；`./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_build_omnivoice_chunk_ranges_splits_only_when_over_threshold tests.test_dubbing_cli_api.DubbingCliApiTests.test_build_omnivoice_chunk_plan_prefers_silence_and_snaps_to_subtitle_boundary tests.test_dubbing_cli_api.DubbingCliApiTests.test_prepare_omnivoice_source_stems_dispatches_to_chunked_for_long_video tests.test_dubbing_cli_api.DubbingCliApiTests.test_prepare_omnivoice_source_stems_keeps_single_pass_at_90_minutes tests.test_dubbing_cli_api.DubbingCliApiTests.test_prepare_omnivoice_source_stems_chunked_degrades_only_failed_chunk` 通过（5 tests, OK）

## 80. 2026-05-16 5 号面板长视频分段时长从 20 分钟调到 40 分钟
- [x] 现状
  - `src/subtitle_maker/omnivoice_dub_api.py::_build_omnivoice_chunk_ranges(...)` 当前默认读取 `OMNIVOICE_LONG_VIDEO_CHUNKED_SEPARATION_CHUNK_SEC`
  - 该常量现在是 `20 * 60` 秒，是上一轮长视频分段 separation 第一版的保守默认值
  - 你最新实测反馈是“20 分钟素材约 2 分钟跑完、CPU 约 68%”，说明当前切块偏小，存在 Demucs 调度和切块管理开销
- [x] 目标
  - 保持“超过 90 分钟才分段”的阈值不变
  - 仅把 5 号面板长视频预分离的默认切块时长从 20 分钟调整到 40 分钟
  - 同步回归测试，确保切块合同和阈值合同仍然成立
- [x] 计划
  - 修改 `OMNIVOICE_LONG_VIDEO_CHUNKED_SEPARATION_CHUNK_SEC`
  - 更新切块范围单测的期望值
  - 跑 `py_compile + unittest` 定向验证
- [ ] 验证
  - 长视频默认切块时长已变为 40 分钟
  - 90 分钟阈值逻辑不变

## 79. 2026-05-16 5 号面板超过 90 分钟视频改为分段人声分离
- [x] 现状
  - 5 号面板当前整段预分离集中在 `src/subtitle_maker/omnivoice_dub_api.py::_prepare_omnivoice_source_stems(...)`
  - 这条链路会先抽整条 `source_audio.wav`，再把整条音频一次性送进 `demucs.separate`
  - 4 号面板 `tools/dub_pipeline.py::separate_audio(...)` 当前也仍是整段 separation，只是失败时会退化为 vocals-only
  - 项目里已有按时间范围抽音并分离的局部实现：`src/subtitle_maker/speaker_voice_api.py::_separate_range_vocals_or_fail(...)`
- [x] 目标
  - 当输入视频总时长超过 90 分钟时，5 号面板改走分段人声分离
  - 保持 90 分钟及以下视频继续走现有整段 separation，避免扩大回归面
  - 分段 separation 完成后仍向后续 OmniVoice 参考音抽取、配音和 final 合成提供统一的 `full_source_vocals.wav` / `full_source_bgm.wav`
- [x] 计划
  - 先明确长视频分段 separation 的切块规则、落盘结构和 manifest / report 合同
  - 再决定复用 `speaker_voice_api` 的 range 抽音思路，还是在 `omnivoice_dub_api.py` 内新增专用 helper
  - 最后补长视频阈值与分段兜底的回归测试
- [x] 功能点（Spec 第 2 段）
  - `src/subtitle_maker/omnivoice_dub_api.py::_prepare_omnivoice_source_stems(...)` 增加总时长判断；当 `ffprobe_duration(input_media_path) > 5400s` 时切到 chunked separation
  - chunked separation 仍先产出统一的 `stems/source_audio.wav`，但实际分离按时间块生成 `stems/range_0001/range_audio.wav`、`stems/range_0001/range_vocals.wav`、可选 `range_bgm.wav`
  - 每个 range 的抽音方式参考 `src/subtitle_maker/speaker_voice_api.py::_separate_range_vocals_or_fail(...)`，但返回结果要服务于 5 号面板整片链路，而不是单次 speaker 提取任务
  - range 级分离完成后，拼接生成统一的 `stems/full_source_vocals.wav` 与 `stems/full_source_bgm.wav`，供后续 `source_vocals_path`、参考音抽取和 final mix 继续复用
  - `separation_report.json` 从“单次 attempts”扩展成“顶层 status + ranges[] + attempts[]”，保留每个分段的起止时间、状态、使用模型和是否降级
  - 失败语义分两层：单个 range 失败时优先对该 range 退化为 vocals-only；全部 range 完成后整任务继续，而不是因为单块失败整体中止
  - 90 分钟及以下视频保持旧的整段 separation 路径，避免改动短视频稳定链路
  - 测试落点优先放在 `tests/test_dubbing_cli_api.py`，新增“超过阈值走 chunked”“未超过阈值走旧链路”“单个 chunk 双失败时只降级该 chunk”三类合同
- [x] 风险与决策（Spec 第 3 段）
  - 决策 1：阈值固定为“严格大于 90 分钟才切 chunked”，即 `duration_sec > 5400`；`5400` 秒整不切，减少边界回归
  - 决策 2：chunk 时长优先定为 20 分钟，不直接复用 4 号面板 `segment_minutes`
  - 原因：4 号的 `segment_minutes` 是 TTS 批处理参数，定义位置在 `src/subtitle_maker/dubbing_cli_api.py`；它不服务于 stem separation，直接复用会混淆语义
  - 决策 3：chunk 之间先不加 overlap，也不做 crossfade；第一版按无重叠硬拼接实现
  - 依据：当前整片回填工具 `src/subtitle_maker/domains/media/compose.py::build_full_timeline_vocals(...)` 与 `build_full_timeline_bgm(...)` 本身就是按固定时间窗直接写入，没有 crossfade 设施
  - 决策 4：拼接方式优先做“按绝对时间轴写回整片 master”，而不是简单 `concat_wav_files(...)`
  - 依据：`concat_wav_files(...)` 只适合顺序拼接；而 chunked separation 需要严格保持整片绝对时间轴，缺块或单块降级时也不能把后续时间轴前移
  - 决策 5：单个 chunk 的抽音方式优先复用 `src/subtitle_maker/speaker_voice_api.py::_extract_audio_segment(...)` 的 `ffmpeg -ss/-t` 方案，避免先整片抽音再二次裁切带来的额外 IO
  - 决策 6：单个 chunk 若 `htdemucs` 和 `mdx_extra_q` 都失败，只降级该 chunk 为 vocals-only，并在 `separation_report.json` 的 `ranges[]` 中标记 `failed_fallback_vocals_only`
  - 风险 1：无 overlap 拼接在 chunk 边界可能出现轻微断点或底噪突变
  - 风险应对：第一版优先解决“2 小时+ 长视频直接失败”，边界听感问题留到下一轮再评估是否引入 `0.5s-1.0s` overlap + crossfade
  - 风险 2：如果某些 chunk 有 BGM、某些 chunk 降级为 vocals-only，最终 `full_source_bgm.wav` 会出现局部缺失
  - 风险应对：允许 `has_bgm_track` 按整片降级为 `False`，即只要任一 chunk 缺失可用 BGM，final mix 退化为纯 dubbed vocals，避免混出局部双人声
  - 风险 3：长视频 chunk 数增多后，`separation_report.json` 与 `stems/range_*` 目录会变大
  - 风险应对：接受这部分调试开销，优先保留可恢复和可审计性，不在第一版做清理压缩
- [x] 验证
  - 超过 90 分钟视频会进入分段 separation
  - 90 分钟及以下视频继续走旧链路
- [x] Review
  - 已在 `src/subtitle_maker/omnivoice_dub_api.py` 增加 long-video separation dispatcher：`> 5400s` 走 chunked，`<= 5400s` 保持 single-pass
  - chunked separation 当前固定按 20 分钟切块，按绝对时间轴回并 `full_source_vocals.wav`；只要任一 chunk 缺失可靠 BGM，整片 `has_bgm_track` 会退化为 `False`
  - `separation_report.json` 已扩展支持 `mode=chunked`、`ranges[]` 和 `partial_fallback_vocals_only`
  - 验证结果：`./.venv/bin/python -m py_compile src/subtitle_maker/omnivoice_dub_api.py tests/test_dubbing_cli_api.py` 通过；`./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_build_omnivoice_chunk_ranges_splits_only_when_over_threshold tests.test_dubbing_cli_api.DubbingCliApiTests.test_prepare_omnivoice_source_stems_dispatches_to_chunked_for_long_video tests.test_dubbing_cli_api.DubbingCliApiTests.test_prepare_omnivoice_source_stems_keeps_single_pass_at_90_minutes tests.test_dubbing_cli_api.DubbingCliApiTests.test_prepare_omnivoice_source_stems_chunked_degrades_only_failed_chunk` 通过（4 tests, OK）

## 78. 2026-05-16 5 号面板长视频 pre-separation failed 兜底修复
- [x] 现状
  - 最新 5 号面板任务 `omnivoice_20260516_011511` 在预分离阶段失败，前端报错 `Failed: OmniVoice pre-separation failed`
  - `separation_report.json` 显示 `htdemucs` 对超长音频失败，`mdx_extra_q` 又因为本机未安装 `diffq` 失败
- [x] 目标
  - 避免 Demucs 双失败时整条 OmniVoice 任务直接终止
  - 对齐 4 号面板现有策略：分离失败时退化为 vocals-only，继续后续配音链路
- [x] 计划
  - 把 5 号面板的人声分离逻辑抽成 helper，集中处理成功、降级和报告写盘
  - 两个分离模型都失败时，复制 `source_audio.wav` 作为 `full_source_vocals.wav`，不再抛出致命错误
  - 补回归测试，锁住 `failed_fallback_vocals_only` 合同
- [x] 验证
  - Demucs 双失败时任务不会因 `pre-separation failed` 中止
  - `separation_report.json` 会记录降级状态
- [x] Review
  - 根因确认：`omnivoice_20260516_011511` 的 `htdemucs` 对 7781s 长音频失败，`mdx_extra_q` 又因缺 `diffq` 失败，旧逻辑因此直接抛 `OmniVoice pre-separation failed`
  - 修复后 5 号面板会在双失败时退化为 `failed_fallback_vocals_only`，继续后续 OmniVoice 配音链路，只是不再保留独立 BGM
  - 验证结果：`./.venv/bin/python -m py_compile src/subtitle_maker/omnivoice_dub_api.py tests/test_dubbing_cli_api.py` 通过；`./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_prepare_omnivoice_source_stems_falls_back_to_vocals_only_when_demucs_fails tests.test_dubbing_cli_api.DubbingCliApiTests.test_burn_ass_subtitles_into_video_uses_expected_ffmpeg_args tests.test_dubbing_cli_api.DubbingCliApiTests.test_build_manifest_includes_styled_ass_artifact_and_path` 通过（3 tests, OK）

## 77. 2026-05-15 文档同步并推送 GitHub
- [x] 现状
  - 5 号面板的 styled ASS 导出与 burned MP4 已经实现并完成端到端验证
  - 现有 README / CHANGELOG / FFmpeg 说明文档还没有同步这些结果
- [x] 目标
  - 更新用户可见文档，说明 5 号面板 final 现在会产出 `styled ASS` 和烧录字幕视频
  - 记录这次交付的 ffmpeg 参数与结果合同
  - 提交并推送当前分支到 GitHub
- [x] 计划
  - 更新 `README.md`、`CHANGELOG.md` 和 `docs/output-video-with-subtitle.md`
  - 只提交与这次功能和文档同步相关的文件，避免把本地未追踪的大目录一起推送
  - 做最小校验后提交并推送
- [x] 验证
  - 文档内容与当前实现一致
  - Git 提交与推送成功
- [x] Review
  - `README.md` 已补充 5 号面板 final 的 styled ASS / burned MP4 输出说明
  - `CHANGELOG.md` 已记录 speaker 补齐、styled ASS 导出与 burned 视频交付
  - `docs/output-video-with-subtitle.md` 已整理成可执行的 FFmpeg 烧录说明，并补上项目 final 产物约定
  - 相关改动已提交为 `96efe6b feat: export omnivoice burned video artifacts` 并推送到 `origin/codex/omnivoice-speaker-upload-milestone-20260507`

## 76. 2026-05-15 5 号面板 final 视频新增 ASS 烧录输出
- [x] 现状
  - 5 号面板 final 当前会输出 `dubbed_video_full.mp4`，但只是替换配音音轨，不会烧录 ASS 字幕
  - 现有 styled ASS 已能生成，但还没有接入 final 视频导出链路
- [x] 目标
  - 在 5 号面板 final 结果中新增一个烧录 styled ASS 的 MP4 输出
  - 把烧录视频纳入 manifest / artifact 下载列表
  - 同时整理一份可执行的 FFmpeg 命令说明，包含用户要求的检查、安装、参数解释和完整流程
  - ASS 样式里的 `Fontsize` 统一固定为 `80`
- [x] 计划
  - 复用现有 final 视频生成链路，增加 ASS burn 分支
  - 明确命名、artifact key 和下载合同
  - 补最小回归测试与 FFmpeg 命令说明
- [x] 验证
  - final 目录出现带 ASS 烧录的新 MP4
  - artifact 列表可下载烧录视频
  - 定向测试覆盖 manifest / artifact 合同
- [x] Review
  - 5 号面板 final 结果现在保留原 `dubbed_video_full.mp4`，同时新增 `dubbed_video_full_burned.mp4`
  - 烧录实现固定使用 `ass=` filter、`libx264`、`crf=16`、`preset=slow`、`-c:a copy`
  - manifest `paths`、artifact 列表和下载路由已新增 `video_burned`
  - 验证结果：`./.venv/bin/python -m py_compile src/subtitle_maker/domains/media/compose.py src/subtitle_maker/domains/media/__init__.py src/subtitle_maker/omnivoice_dub_api.py tests/test_dubbing_cli_api.py` 通过；`./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_burn_ass_subtitles_into_video_uses_expected_ffmpeg_args tests.test_dubbing_cli_api.DubbingCliApiTests.test_build_manifest_includes_styled_ass_artifact_and_path tests.test_dubbing_cli_api.DubbingCliApiTests.test_build_styled_ass_from_rows_uses_fixed_template_and_dialogue_format` 通过（3 tests, OK）

## 75. 2026-05-15 5 号面板最终字幕新增 styled ASS 导出
- [x] 现状
  - 5 号面板最终字幕当前只写出 `final/dubbed_final_full.srt`
  - OmniVoice artifact 列表和下载路由目前只暴露 SRT，没有 ASS 产物
- [x] 目标
  - 在 5 号面板最终结果链路中，基于最终 SRT 同步生成一个 styled ASS 文件
  - 输出命名参考 `*-styled.ass`，并把它纳入 5 号面板 artifact 下载列表
- [x] 计划
  - 明确 ASS 样式合同与 SRT->ASS 转换落点
  - 在 5 号 OmniVoice 最终产物阶段新增 ASS 写盘
  - 补 artifact 映射、下载接口和最小回归测试
- [x] 验证
  - 结果目录同时包含 `.srt` 与 `.ass`
  - artifact 下载能拿到 styled ASS
- [x] Review
  - 5 号面板最终结果现在会在 `dubbed_final_full.srt` 旁边同步生成 `dubbed_final_full-styled.ass`
  - ASS 模板严格复用了用户给定样例的固定样式参数：`PingFang SC`、字号 `80`、`BorderStyle=4`、`Alignment=2`、`MarginL/R/V=80`、`PlayRes=1920x1080`
  - manifest `paths` 与 artifact 列表已新增 `ass`，下载路由也补了 `.ass` MIME
  - 验证结果：`./.venv/bin/python -m py_compile src/subtitle_maker/omnivoice_dub_api.py tests/test_dubbing_cli_api.py` 通过；`./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_build_styled_ass_from_rows_uses_fixed_template_and_dialogue_format tests.test_dubbing_cli_api.DubbingCliApiTests.test_build_manifest_includes_styled_ass_artifact_and_path tests.test_dubbing_cli_api.DubbingCliApiTests.test_prepare_omnivoice_subtitles_from_project_writes_speaker_copy_artifact` 通过（3 tests, OK）

## 74. 2026-05-14 5 号面板无 speaker 行默认补齐顺序调整
- [x] 现状
  - 5 号面板前端统计 speaker 上传槽位时，空 `speaker_id` 当前直接回退为 `Speaker 1`
  - 5 号面板后端 `_ensure_speaker_ids(...)` 已经是“优先按时间对齐，其次上一条 speaker，最后 `Speaker 1`”
- [x] 目标
  - 把“无 speaker 行”的默认补齐顺序统一成：先补为上一行的 speaker，补不出来再归为 `Speaker 1`
  - 保持 5 号面板前后端行为一致，避免上传槽位统计与实际配音 speaker 路由不一致
- [x] 计划
  - 调整 5 号面板前端 `getDetectedSpeakerIds(...)` 的空 speaker 归并逻辑
  - 评估是否需要把同一规则下沉为共享 helper，避免前后端语义继续漂移
  - 补最小回归验证，覆盖“首行为空”和“中间行为空”两类情况
- [x] 验证
  - 前端静态检查通过
  - 后端/测试能证明补齐顺序符合“上一行优先，最后 Speaker 1”
- [x] Review
  - 5 号面板前端 speaker 槽位统计已改为“上一行优先，最后 `Speaker 1`”，不再把每个空 speaker 立即算成 `Speaker 1`
  - 后端 `_ensure_speaker_ids(...)` 原有顺序保持不变，并补了两条单测锁住“首行空 / 中间空”合同
  - 验证结果：`node --check src/subtitle_maker/static/js/omnivoiceDubbingPanel.js` 通过；`python3 -m unittest ...` 返回 `OK (skipped=4)`，当前环境下这组 API 测试因缺依赖被跳过，未做更深集成回归

## 73. 2026-05-10 OmniVoice SRT 极端时长错配修复（无效声音）
- [x] 目标
  - 修复 source SRT 导致的“短字长时窗 / 长字短时窗”异常，减少 OmniVoice 无效声音
  - 仅改 5 号 OmniVoice 结果链路，不影响 4 号 Auto Dubbing
- [x] 实现
  - 在 `src/subtitle_maker/omnivoice_dub_api.py` 增加 `_rebalance_omnivoice_synthesis_rows(...)`
  - 合成前按相邻字幕文本负载与时长密度（cps）检测极端对并重分配时间窗
  - 仅对同 speaker、相邻时间窗口、极端失配对生效，最小化影响
- [x] 测试
  - 新增 `test_omnivoice_synthesis_rebalance_fixes_extreme_adjacent_timing_pairs`
  - 保留 `test_omnivoice_final_srt_rebalance_limits_line_width_and_keeps_monotonic_timing` 回归
- [x] 验证
  - `uv run python -m py_compile src/subtitle_maker/omnivoice_dub_api.py tests/test_dubbing_cli_api.py`
  - `uv run python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_omnivoice_synthesis_rebalance_fixes_extreme_adjacent_timing_pairs tests.test_dubbing_cli_api.DubbingCliApiTests.test_omnivoice_final_srt_rebalance_limits_line_width_and_keeps_monotonic_timing`
- [x] Review
  - 最新 batch `omnivoice_20260510_050427` 可复现 231/232、233/234 这类极端失配；新规则可命中并修正。

## 72. 2026-05-10 OmniVoice source 翻译纯标点行修复
- [x] 目标
  - 修复 OmniVoice source->translate 路径里偶发的“译文仅 `。`”问题
  - 仅改翻译回填后处理，不改 speaker-first 逻辑和配音主链路
- [x] 实现
  - 在 `src/subtitle_maker/omnivoice_dub_api.py` 增加纯标点检测与二次翻译修复
  - 对“源文本可读 + 译文纯标点”的行执行定向重试
  - 若重试仍异常，回退该行 source 文本，避免 `。` 直接落盘
- [x] 测试
  - 新增 `test_omnivoice_translate_subtitles_repairs_punctuation_only_lines`
  - 保留 `test_omnivoice_final_srt_rebalance_limits_line_width_and_keeps_monotonic_timing` 回归通过
- [x] 验证
  - `uv run python -m py_compile src/subtitle_maker/omnivoice_dub_api.py tests/test_dubbing_cli_api.py`
  - `uv run python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_omnivoice_translate_subtitles_repairs_punctuation_only_lines tests.test_dubbing_cli_api.DubbingCliApiTests.test_omnivoice_final_srt_rebalance_limits_line_width_and_keeps_monotonic_timing`
  - `uv run python -m unittest tests.test_dubbing_runtime.DubbingPipelineTests.test_repair_punctuation_only_translations_inherits_merged_system_prompt tests.test_dubbing_runtime.DubbingPipelineTests.test_translator_parse_translated_lines_merges_multiline_numbered_blocks tests.test_dubbing_runtime.DubbingPipelineTests.test_translator_parse_translated_lines_ignores_noise_lines_without_index_shift`
- [x] Review
  - 根因是 OmniVoice 路由未接入 `punct-only` 翻译修复，导致 `。` 这类异常行未被兜底。
  - 修复后 OmniVoice source 翻译会先重试，再回退 source，保证不会再把纯标点行直接写入结果字幕。

## 71. 2026-05-09 OmniVoice Source 翻译回填错位修复（Speaker 优先保持不变）
- [x] 目标
  - 仅修复翻译输出解析/回填错位，不改 speaker-first 分层逻辑
  - 保持 `translate_batch()` 输入输出合同不变（输入 N 条，返回 N 条）
  - 不改 `optimize_srt_import_subtitles(...)`、`deepgram_json_to_subtitles(...)` 和 OmniVoice 配音链路
- [x] 实现
  - `translator._parse_translated_lines()` 改为“编号块优先解析”
  - 同一编号下多行译文自动聚合，避免逐行追加导致后续错位
  - 过滤编号块内常见噪声行（说明行、注释行、空行）
  - 当未识别到编号块时，回退到旧的逐行解析策略
- [x] 测试
  - 新增 `test_translator_parse_translated_lines_merges_multiline_numbered_blocks`
  - 新增 `test_translator_parse_translated_lines_ignores_noise_lines_without_index_shift`
  - 保留并回归 `test_translator_translate_batch_flattens_internal_newlines_in_one_cue`
- [x] 验证
  - `uv run python -m py_compile src/subtitle_maker/translator.py tests/test_dubbing_runtime.py`
  - `uv run python -m unittest tests.test_dubbing_runtime.DubbingPipelineTests.test_translator_parse_translated_lines_merges_multiline_numbered_blocks`
  - `uv run python -m unittest tests.test_dubbing_runtime.DubbingPipelineTests.test_translator_parse_translated_lines_ignores_noise_lines_without_index_shift`
  - `uv run python -m unittest tests.test_dubbing_runtime.DubbingPipelineTests.test_translator_translate_batch_flattens_internal_newlines_in_one_cue`
  - `uv run python -m unittest tests.test_dubbing_runtime.DubbingPipelineTests.test_translator_translate_batch_merges_default_and_custom_system_prompt tests.test_dubbing_runtime.DubbingPipelineTests.test_translate_batch_with_budget_lazy_initializes_translator_client`
- [x] Review
  - 修复只落在 translator 解析层，speaker-first 导入与 OmniVoice 配音主链路未改动。
  - 新解析优先按编号块回填，能防止模型输出换行/说明行导致的整批错位。
  - 当回复没有编号结构时自动回退旧逻辑，兼容现有翻译返回格式。

## 70. 2026-05-08 Translation API 连通性测试
- [x] 目标
  - 在侧栏底部的 `Translation API / OpenAI-compatible 配置` 卡片中增加“测试连通性”功能
  - 复用现有 `OpenAI-compatible` 配置，不改翻译主流程
  - 明确返回 API key / base URL / model 这组配置是否可实际完成一次最小请求
- [x] 后端
  - 新增一个独立的翻译连通性测试接口，优先复用现有 OpenAI-compatible client
  - 测试请求应尽量轻量，避免影响正式翻译任务
  - 只返回是否可用与失败原因，不回显 key 或其它敏感配置
- [x] 前端
  - 在侧栏翻译配置卡片中增加一个测试按钮
  - 点击后展示成功或失败状态，不影响当前保存态
  - 保持卡片折叠/展开与现有保存逻辑不变
- [x] 验证
  - `node --check src/subtitle_maker/static/app.js`
  - `uv run python -m py_compile src/subtitle_maker/app/routes/translation.py src/subtitle_maker/core/llm_client.py src/subtitle_maker/translator.py`
  - 浏览器里实际点一次测试按钮，确认成功/失败提示可见
- [x] Review
  - 新增的 `/translation/test` 复用了现有 OpenAI-compatible 配置解析，不会污染正式 `/translate` 路径
  - 侧栏测试入口放在卡片头部，避免正文区因为高度不足把按钮挤出首屏
  - 浏览器实测可见按钮状态切换，成功时会显示 provider host 和 model，失败时会直接回显后端错误摘要

## 69. 2026-05-08 OmniVoice 5 号结果态直接播放成片
- [x] 目标
  - 5 号面板加载结果时优先直接播放 `final/dubbed_video_full.mp4`
  - 同时读取 `final/dubbed_final_full.srt` 作为结果字幕预览
  - 保持 2 号面板原字幕 / 译文显示链路不变
- [x] 前端
  - 结果态加载逻辑优先挂载成片视频，必要时再回退源视频
  - 继续支持原字幕 / 翻译字幕 overlay 切换
- [x] 验证
  - 5 号面板加载结果后播放器直接播成片
  - 5 号面板字幕叠加正常显示翻译结果
  - 2 号面板字幕显示不受影响
- [x] Review
  - 结果态现在优先直接加载 `final/dubbed_video_full.mp4`，不再靠单独音轨切换去拼成片
  - overlay 仍然沿用全局原字幕 + 5 号本地译文预览，所以原字幕和翻译字幕都能切
  - 2 号面板没有写入 5 号本地预览状态，显示链路没有被污染
  - 当当前项目没有原字幕时，`Original Only` 在 5 号结果预览下会自动回退显示结果字幕，避免用户看到空字幕误以为没加载成功
  - 结果文件夹切换时会保留当前选中的 batch，并显式刷新结果区附件，避免“视频已切换但下载链接仍停留在旧 batch”的假失败

## 68. 2026-05-08 Deepgram JSON 导入到 4/5 配音链路
- [x] 目标
  - 在 1 号面板新增 Deepgram JSON 上传入口
  - 把 Deepgram diarization 的原始 JSON 规范化成 speaker-aware SRT，再写回当前项目状态
  - 4 号和 5 号面板继续直接消费当前项目字幕，不改配音主链路
- [x] 后端
  - 新增 `POST /upload_deepgram_json`
  - Deepgram JSON 先优先按 `results.channels[0].alternatives[0].paragraphs.paragraphs` 转换，再在必要时 fallback 到 `words[]`
  - Deepgram speaker 按首次出现顺序映射成 `Speaker 1 / Speaker 2 / ...`
  - 导入结果只保留转换后的 SRT，不保留原始 JSON 产物
- [x] 前端
  - 1 号面板新增 `.json` 上传控件
  - `.srt` 和 `.json` 两条导入路径共用同一个“写回当前项目状态”函数
  - 导入后保持当前项目状态、localStorage 和 results 面板同步
- [x] 验证
  - 新增转换单测，覆盖 paragraphs 和 words 两条路径
  - 新增接口测试，覆盖 `/upload_deepgram_json` 与 `/status/{task_id}` 的任务合同
  - `node --check src/subtitle_maker/static/app.js`
  - `uv run python -m py_compile src/subtitle_maker/domains/subtitles/deepgram.py src/subtitle_maker/domains/subtitles/__init__.py src/subtitle_maker/app/routes/subtitles.py tests/test_subtitle_speakers.py tests/test_web_routes_legacy.py`
  - `uv run python -m unittest tests.test_subtitle_speakers tests.test_web_routes_legacy`
- [x] Review
  - 这次 Deepgram 导入沿用了现有字幕写回合同，没有把原始 JSON 留进项目态
  - 为避免 `loadState()` 把导入文件误判成媒体，后端返回了派生的 `.srt` 文件名
  - 4 号和 5 号面板没有改配音逻辑，只是多了一条更适合 speaker-aware 输入的上游入口

## 67. 2026-05-08 OmniVoice 5 号长视频分段/并发优化
- [ ] 现状
  - 5 号 `Auto Dub Omnivoice` 当前是逐句串行调用 OmniVoice，长视频会因为字幕行数多而明显变慢
  - 目前没有复用 4 号 `Auto Dubbing` 的 grouped synthesis 分段编排
- [ ] 目标
  - 为 5 号面板补上真正的分段/分组处理能力，减少长视频的总 TTS 调用成本
  - 保持 speaker 映射、手工上传参考音和最终结果目录结构不变
- [ ] 计划
  - 对齐 4 号 grouped synthesis 的分组策略，优先复用现有 grouping / segment 机制
  - 评估是否需要有限并发，避免单线程逐句阻塞
  - 保持每句结果可追踪，避免破坏 manifest / artifact 恢复
- [ ] 验证
  - 长视频任务的总体耗时显著下降
  - 5 号结果仍可正常恢复、下载和回放

## 66. 2026-05-07 OmniVoice 输出目录并入 dub_jobs
- [x] 目标
  - 5 号 `Auto Dub Omnivoice` 的结果目录从 `outputs/omnivoice_dub_jobs/` 迁移到 `outputs/dub_jobs/`
  - 保持 4 号和 5 号都在同一个 `dub_jobs` 根目录下，但目录名前缀区分，避免串台
- [x] 目录约定
  - 4 号继续使用 `outputs/dub_jobs/web_<task_id>/...`
  - 5 号改为 `outputs/dub_jobs/omnivoice_<task_id>/...`
  - 兼容旧的 `outputs/omnivoice_dub_jobs/` 历史结果用于恢复和下载
- [x] 验证
  - 新任务的 manifest / artifact / load-batch 都能正常工作
  - 旧任务仍能被列表和恢复接口识别
- [x] Review
  - 新任务输出现在统一落到 `outputs/dub_jobs/omnivoice_<task_id>/...`
  - 旧的 `outputs/omnivoice_dub_jobs/` 仍可恢复，不影响历史结果

## 65. 2026-05-07 New Project 保留 outputs 配音结果
- [ ] 目标
  - 左下角 `New Project` 只清当前项目状态、上传文件和任务态
  - 不删除 `outputs/` 下已经生成的配音结果、manifest、视频和可恢复批次
- [ ] 后端
  - `/project/reset` 不再清空整个 `outputs/` 目录
  - 保留 `outputs/dub_jobs`、`outputs/omnivoice_dub_jobs` 等结果目录
- [ ] 前端
  - 更新确认文案，明确 `New Project` 不会删除已生成的配音内容
- [ ] 验证
  - `New Project` 后当前项目状态清空，但 `outputs/` 中旧配音结果仍可加载/下载

## 64. 2026-05-07 OmniVoice 空翻译句兜底
- [x] 目标
  - 解决 source 字幕翻译后，最后一条或个别句子被翻成空字符串，进而触发 OmniVoice 422 `body.text` 缺失
- [x] 修复
  - `_normalize_translation_result()` 保留原始翻译结果，不再回填原文
  - 新增空字幕过滤：空翻译行会直接从配音链路里跳过，不会送进 OmniVoice
- [x] 验证
  - `uv run python -m py_compile src/subtitle_maker/omnivoice_dub_api.py`
  - 模拟翻译结果最后一条为空时，归一化后会被过滤掉，不再保留空文本
- [x] Review
  - 这次 422 的根因不是 OmniVoice 接口本身，而是翻译输出里出现了空句
  - 以后只要发现翻译结果有空行，优先直接过滤，不要回填原文去污染目标语言

## 63. 2026-05-07 复制 4 号面板 Custom System Prompt 行为到 5 号 OmniVoice
- [x] 目标
  - 让 5 号 `Auto Dub Omnivoice` 的 `Custom System Prompt (Optional)` 行为与 4 号面板对齐
  - 翻译仍复用全局 OpenAI-compatible API，不影响配音主链路
- [x] 前端行为
  - 5 号面板优先读取自己的 `omnivoice-translate-system-prompt`
  - 若 5 号输入为空，回退读取旧的 `system-prompt`，和 4 号面板保持一致的兼容行为
  - 空 prompt 时不向后端传参，避免污染翻译请求
- [x] 验证
  - `node --check src/subtitle_maker/static/js/omnivoiceDubbingPanel.js`
  - source 字幕继续走翻译，translated 字幕继续跳过翻译，不影响配音主链路
- [x] Review
  - 5 号 OmniVoice 的翻译系统提示词现在与 4 号面板的兼容行为对齐
  - 只改 `translate_system_prompt` 的读取回退逻辑，没有碰 speaker 映射或生成链路

## 62. 2026-05-07 OmniVoice strict speaker 参考音上传
- [x] 目标
  - 5 号 `Auto Dub Omnivoice` 不再默认依赖“从原视频自动聚合参考音”作为主路径
  - 改为按当前项目字幕里的 `speaker_id` 自动识别 speaker，再由用户逐个上传参考音频
  - 每个上传参考音统一绑定固定 `ref_text`：`你好，这是我的声音音色，很高兴为你进行配音服务。`
- [x] 前端
  - 在 `panel-auto-dub-omnivoice` 增加 speaker 参考音上传区
  - 自动根据当前项目字幕渲染 `Speaker 1 / Speaker 2 / ...` 上传槽位
  - 启动前严格校验：有几个 speaker，就必须上传几份参考音
- [x] 后端
  - `omnivoice_dub_api.py` 的 `/start-from-project` 接收 `speaker_ref_files` 和 `speaker_ref_speaker_ids_json`
  - 保存上传参考音并构造 `speaker_id -> {ref_audio, ref_text}` 映射
  - 生成阶段优先使用上传参考音；第一版 strict 模式下不自动 fallback 到原视频聚合
- [x] 可观测性与验证
  - `speaker_ref_map.json` 明确记录本次使用的是上传参考音
  - `py_compile` / `node --check` 通过
  - 实际发起一次 OmniVoice 任务，确认输出目录能看到上传参考音映射
- [x] Review
  - `node --check src/subtitle_maker/static/js/omnivoiceDubbingPanel.js` 通过
  - `uv run python -m py_compile src/subtitle_maker/omnivoice_dub_api.py` 通过
  - 路由级验证：两份上传参考音能创建任务并把文件落到 `outputs/omnivoice_dub_jobs/.../uploaded_speaker_refs/`
  - strict 负例验证：缺 `Speaker 2` 参考音时，后端返回 `HTTP 400` 和明确缺失 speaker 提示

## 61. 2026-05-07 OmniVoice 3900 自动拉起
- [x] 5 号 `Auto Dub Omnivoice` 的后端状态轮询会自动拉起本机 3900 服务
- [x] 3900 不再依赖手工启动，页面打开后会在后台自动变为 ready
- [x] `stop.sh` 已补 3900 清理，避免灰按钮对应的后台常驻进程残留
- [x] 验证：`/omnivoice/auto/backend-status` 从 loading 变成 ready，`/model/status` 返回本地 checkpoints

## 60. 2026-05-07 OmniVoice 本地 checkpoints + 去 HF
- [ ] 目标
  - 保留 5 号 `Auto Dub Omnivoice` 的翻译功能
  - 翻译继续复用全局 OpenAI-compatible API，不新增独立翻译服务
  - OmniVoice TTS 只读本地 `omnivoice/checkpoints`，不再通过 HuggingFace cache / remote repo 拉模型
- [ ] 本地模型加载
  - `OmniVoice.from_pretrained()` 仅接受本地 checkpoint 路径
  - `model_manager.py` 默认 checkpoint 改成本地目录
  - 删除 `snapshot_download`、`model_info`、HF cache 相关预热逻辑
- [ ] 5 号链路裁剪
  - 移除 5 号启动路径里不需要的 ASR 加载
  - 不把 diarization 接回 5 号链路
  - 保留 speaker 字幕路由与翻译兜底，不碰用户上传字幕的 speaker 语义
- [ ] 配置与展示
  - `system` / `model status` 中展示本地 checkpoint 路径
  - 删除 3900 启动时对 HF cache 的环境变量依赖
  - 让“就绪状态”只取决于本地模型文件与进程状态
- [ ] 验证
  - `py_compile` / `node --check` 通过
  - 3900 后端用本地 checkpoints 启动成功
  - 5 号面板能直接发起配音，翻译仍走全局 OpenAI-compatible API

## 59. 2026-05-07 独立 OmniVoice 链路重建
- [ ] 目标
  - 保留 `4. Auto Dubbing` 现有 `index-tts` 主链路，不再共享底座模型切换状态
  - 新增 `5. Auto Dub Omnivoice`，作为一条独立的字幕驱动配音链路
- [ ] 前端拆分
  - 移除侧边栏底部的 `底座模型` 控件和对应的全局 backend 状态
  - `Auto Dubbing` 面板固定使用 `index-tts`
  - 新增独立的 `Auto Dub Omnivoice` 导航项、面板和 JS 模块
- [ ] 后端桥接
  - 新增独立 OmniVoice 路由与任务命名空间
  - 任务仅复用当前项目媒体、字幕、speaker 元数据
  - 输出目录、状态轮询、artifact 下载、batch 恢复都使用独立前缀
- [ ] 运行链路
  - 参考 `OmniVoice-Studio-main` 的 dubbing 结构，实现“字幕驱动 + speaker 路由参考音 + per-segment 合成 + final mix”
  - 不把 ASR/diarization 接回主路径
  - 保持与 `index-tts` 完全隔离，不共享 localStorage / 请求状态 / 结果状态
- [ ] 验证
  - 前端确认 4/5 面板互不串台
  - 后端确认新 OmniVoice 路由能完成 start/status/artifact 的完整闭环
  - 验证 `index-tts` 回归不受影响

## 52-58. 2026-05-06 翻译 Provider 收口总览
- [x] 目标
  - 把翻译链路从 `DeepSeek 专用` 收口为 `OpenAI-compatible` 通用能力
  - 保留默认实现值与 legacy 兼容，不破坏现有部署和 `index-tts` 链路
- [x] 已完成范围
  - 后端翻译入口统一支持 `translate_base_url / translate_model`
  - API key 解析优先级统一为：显式 `api_key` > `TRANSLATE_API_KEY` > `DEEPSEEK_API_KEY`
  - 运行摘要、错误提示、前端 UI 文案统一改成 `Translation API / OpenAI-compatible`
  - 翻译调用计数主字段统一为 `translate_request_count`
  - 默认翻译供应商配置已在后端 `translator.py` 与前端 `app.js` 各自抽成单一入口
  - 模板 placeholder 与无业务价值的 `DeepSeek` 命名/测试注释已清理
- [x] 兼容保留
  - 默认 `base_url=https://api.deepseek.com`
  - 默认 `model=deepseek-v4-flash`
  - 继续兼容 `DEEPSEEK_API_KEY`
  - 继续兼容旧任务里的 `deepseek_request_count` 读取，但状态接口不再公开该字段
- [x] 关键文件
  - `src/subtitle_maker/translator.py`
  - `src/subtitle_maker/core/llm_client.py`
  - `src/subtitle_maker/dubbing_cli_api.py`
  - `src/subtitle_maker/static/app.js`
  - `src/subtitle_maker/static/js/dubbingPanel.js`
  - `src/subtitle_maker/templates/index.html`
  - `tools/dub_pipeline.py`
  - `tools/repair_bad_segments.py`
- [x] 验证结论
  - `python3 -m py_compile` 已覆盖翻译入口、CLI、runtime 与相关测试模块
  - `node --check` 已覆盖前端 `app.js` 与 `dubbingPanel.js`
  - `uv run python -m unittest` 已覆盖 `tests.test_dubbing_runtime`、`tests.test_dubbing_cli_api`、`tests.test_web_routes_legacy`、`tests.test_simple_web_legacy`、`tests.test_agent_api`
  - 当前结论：默认值保持不变，但前后端、运行日志、状态接口和 UI 语义都已完成 provider-neutral 收口

## 49-51. 2026-05-06 字幕输入与翻译编排优化总览
- [x] 目标
  - 让上传 `source.srt` 的链路跳过 ASR/source-layout 重排，直接进入纯字幕预处理
  - 统一翻译默认 prompt 与前端自定义 prompt 的合并逻辑
  - 让 Auto Dubbing 启动日志直接展示翻译策略，便于判断是否翻译、如何翻译
- [x] 已完成范围
  - 上传 `source.srt` 现在走独立的非 ASR 预处理路径，只保留清洗、时间戳校正和可选 short merge
  - 后端翻译统一使用 `DEFAULT_TRANSLATION_SYSTEM_PROMPT + 用户自定义 prompt` 合并策略
  - `runtime_brief` 已新增 `translation` 字段，直接显示 `run/skip + prompt 状态 + provider`
- [x] 关键文件
  - `tools/dub_pipeline.py`
  - `src/subtitle_maker/translator.py`
  - `src/subtitle_maker/dubbing_cli_api.py`
  - `tools/repair_bad_segments.py`
  - `tests/test_dub_pipeline_asr_layout.py`
  - `tests/test_dubbing_runtime.py`
  - `tests/test_dubbing_cli_api.py`
- [x] 验证结论
  - `python3 -m py_compile` 与 `uv run python -m unittest` 已覆盖 uploaded source subtitles、translation prompt merge、runtime brief 三条主合同
  - 当前结论：上传 `source.srt` 不再被 ASR/source-layout 阻塞；翻译 prompt 来源已统一；启动日志可直接观察翻译策略

## 47-48. 2026-05-06 Auto Dubbing 主合同收口总览
- [x] 目标
  - 收掉前端单人/多人手选模式，改为按字幕 speaker 自动推断
  - 把 `index-tts` 默认策略稳定回用户实测更优的 `grouped synthesis + token=40`
- [x] 已完成范围
  - 前端已删除 `Mode` 下拉和单人参考音上传区
  - 是否显示 speaker 上传参考音控件，改为按 `speaker_id / Speaker N:` 自动判断
  - 有 speaker 时只允许 `0 上传` 或 `全上传`；部分上传前后端都会拒绝
  - 后端 `dubbing_mode` 已改为按字幕 speaker 自动推断，旧表单值只保留兼容校验
  - `index-tts` 已恢复默认 grouped 合成，`index_max_text_tokens` 已统一回退到 `40`
- [x] 关键文件
  - `src/subtitle_maker/static/js/dubbingPanel.js`
  - `src/subtitle_maker/dubbing_cli_api.py`
  - `src/subtitle_maker/jobs/command_builder.py`
  - `tools/dub_pipeline.py`
  - `tools/dub_long_video.py`
  - `tests/test_dubbing_cli_api.py`
  - `tests/test_command_builder.py`
  - `tests/test_job_recovery.py`
  - `tests/test_manifest_contracts.py`
- [x] 验证结论
  - `node --check` 已覆盖前端面板脚本
  - `python -m py_compile` 与 `uv run python -m unittest` 已覆盖 speaker 自动推断、参考音上传约束、grouped synthesis 和 `token=40` 主合同
  - 当前结论：Auto Dubbing 模式选择已从手选收口为字幕驱动；`index-tts` 执行策略已回退到当前最稳的默认组合

## 45-46. 2026-05-06 范围选择与字幕短句策略总览
- [x] 目标
  - 删除 `Auto pick dubbing ranges` 全链路，统一收口到 `manual / all` 两种范围策略
  - 让 `Merge short source lines` 在存在 speaker 信息时严格禁止跨 speaker 合并
- [x] 已完成范围
  - 前端已物理删除 `Auto pick dubbing ranges` 复选框，启动请求不再发送 `auto_pick_ranges`
  - `dubbing_cli_api`、任务快照、命令构建、manifest/recovery 与 `dub_pipeline.py` / `dub_long_video.py` 已移除 `auto` 范围策略
  - `source short merge` 现在会先归一化 `speaker_id / Speaker N:`，只要检测到 speaker 信息就自动切到 speaker-aware short merge
  - 缺失 speaker 的行会形成独立边界，禁止跨边界并句
- [x] 关键文件
  - `src/subtitle_maker/static/js/dubbingPanel.js`
  - `src/subtitle_maker/dubbing_cli_api.py`
  - `src/subtitle_maker/jobs/command_builder.py`
  - `src/subtitle_maker/jobs/models.py`
  - `src/subtitle_maker/jobs/recovery.py`
  - `src/subtitle_maker/manifests/schema.py`
  - `src/subtitle_maker/manifests/readwrite.py`
  - `tools/dub_pipeline.py`
  - `tools/dub_long_video.py`
  - `tests/test_command_builder.py`
  - `tests/test_job_recovery.py`
  - `tests/test_manifest_contracts.py`
  - `tests/test_dubbing_cli_api.py`
  - `tests/test_dub_pipeline_asr_layout.py`
- [x] 验证结论
  - `node --check` 已覆盖前端面板脚本
  - `python -m py_compile` 与 `uv run python -m unittest` 已覆盖范围策略收口、speaker-aware short merge 与相关 manifest/recovery 主合同
  - 当前结论：自动配音范围选择已简化为 `manual / all`；source short merge 已禁止跨 speaker 合并

## 44. 2026-05-06 index-tts 单 worker 提效（降内存优先）
- [x] 现状分析
  - 单 worker 已吃满 16GB，`segment` 多 worker 并发不现实；提效必须集中在单 worker 内部
  - `tools/dub_pipeline.py`
    - strict `speaker_ref_map_json` 多人模式下，仍会先构建 `subtitle_ref_map`，存在多余逐句参考音切片
  - `src/subtitle_maker/backends/index_tts.py`
    - API 模式带 `target_duration_sec` 时会最多做 2 轮整句质量尝试；每个 chunk 还可能经历 3 次 API 重试，短句实际开销偏高
    - chunk 已返回 `duration_sec` 时，仍会再对整句输出做 `audio_duration(...)` 探测
  - `src/subtitle_maker/domains/dubbing/pipeline.py`
    - grouped / per-line 最终保留音频默认都会进入 `edge fade + normalize_speech_audio_level(...)`
    - 极短句也会走同样后处理，存在额外整句读写
- [x] 实施计划
  - `tools/dub_pipeline.py`
    - strict speaker 模式直接使用上传映射，跳过 `build_subtitle_reference_map(...)`
    - 把多人 strict speaker 参考音选择逻辑抽成独立 helper，便于回归测试
  - `src/subtitle_maker/backends/index_tts.py`
    - 收紧第二轮整句质量重试：仅长句/长目标时长保留
    - 当 chunk 已返回有效 `duration_sec` 时，跳过额外整句输出时长 probe
  - `src/subtitle_maker/domains/dubbing/pipeline.py`
    - 为 `index-tts` 极短句增加句级后处理短路：跳过非必要 edge fade / leveling
    - 保持现有时长对齐、resume、missing 占位和 single-output invariant 不变
  - 测试
    - 补 strict speaker 快路径单测
    - 补 Index-TTS 长句重试 / 短句不重试单测
    - 补极短句跳过 leveling/edge fade 单测
- [x] 验证
  - `uv run python -m py_compile tools/dub_pipeline.py src/subtitle_maker/backends/index_tts.py src/subtitle_maker/domains/dubbing/pipeline.py tests/test_dub_pipeline_references.py tests/test_dubbing_runtime.py`
  - `uv run python -m unittest -v tests.test_dub_pipeline_references tests.test_dubbing_runtime`
  - 实际结果
    - [x] `uv run python -m py_compile tools/dub_pipeline.py src/subtitle_maker/backends/index_tts.py src/subtitle_maker/domains/dubbing/pipeline.py tests/test_dub_pipeline_references.py tests/test_dubbing_runtime.py`
    - [x] `uv run python -m unittest -v tests.test_dub_pipeline_references`
    - [x] `uv run python -m unittest -v tests.test_dubbing_runtime`
  - review
    - `index-tts + multi + speaker_ref_map_json` 已改成 strict speaker 直通：多人 strict 路径不再构建 `subtitle_ref_map`，直接用上传的 `speaker_ref_map` 选参考音
    - `IndexTtsBackend` 现在只对长句保留第二轮整句质量重试；短句即使偏短/偏长，也不再放大成双倍整句调用
    - 当 chunk API 已返回有效 `duration_sec` 时，backend 不再额外 probe 整句输出时长，减少一次文件探测
    - `index-tts` 极短句现在会跳过句级 `edge fade` 和 `normalize_speech_audio_level(...)`，避免非必要整句读写
    - 现有 `resume`、`compose window guard`、`translated subtitles`、`single output invariant` 相关回归未被破坏

## 43. 2026-05-05 自动配音只保留 index-tts，删除 OmniVoice / VoxCPM 底座链路
- [x] 现状分析（仅围绕 Auto Dubbing）
  - 前端仍暴露多底座入口
    - [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html) 仍有 `global-tts-backend` 下拉，包含 `index-tts` / `omnivoice`
    - [src/subtitle_maker/static/js/dubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/dubbingPanel.js) 仍有大量 `omnivoice` 条件分支、参考音 UI、多人 refs 处理
  - Auto Dubbing API 仍维护 OmniVoice 运行参数与服务管理
    - [src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py) 仍包含：
      - OmniVoice 参数读取 `_read_omnivoice_runtime_from_request_or_env(...)`
      - OmniVoice 服务健康检查 / 自动启动 / 停止
      - `tts_backend` 校验仍接受 `omnivoice`
  - 命令构建仍透传 OmniVoice / fallback 参数
    - [src/subtitle_maker/jobs/command_builder.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/jobs/command_builder.py)
      - `AutoDubbingCommandConfig` / `SegmentRedubCommandConfig` 仍保留 `fallback_tts_backend`、`omnivoice_*`
      - `build_auto_dubbing_command()` / `build_segment_redub_command()` 仍会追加 `--omnivoice-*`
  - 运行 pipeline 仍保留 OmniVoice / VoxCPM 分支
    - [tools/dub_pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_pipeline.py) 仍支持 `--tts-backend` 为 `index-tts` / `omnivoice` / `voxcpm-omnivoice`
    - [src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py) 仍保留大量 OmniVoice/VoxCPM 逻辑
    - [src/subtitle_maker/backends/omni_voice.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/backends/omni_voice.py)、[src/subtitle_maker/backends/voxcpm_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/backends/voxcpm_api.py)、[tools/omnivoice_fastapi_server.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/omnivoice_fastapi_server.py) 仍在仓库中
  - 测试仍覆盖 OmniVoice / VoxCPM
    - [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py)
    - [tests/test_command_builder.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_command_builder.py)
    - [tests/test_dubbing_runtime.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_runtime.py)
- [x] 实施计划
  - 前端层
    - 删除 Auto Dubbing 中与 OmniVoice 相关的参考音上传 / reference text / 多人 refs UI
    - 全局 TTS 底座选择改为固定 `index-tts`，或直接移除 Auto Dubbing 对多底座切换的依赖
  - API / 命令层
    - `dubbing_cli_api.py` 将 `tts_backend` 固定为 `index-tts`
    - 删除 Auto Dubbing 请求里的 `fallback_tts_backend`、`omnivoice_*`、`voxcpm_api_url`
    - `command_builder.py` 删除 OmniVoice/fallback 字段与 CLI flag 透传
  - Pipeline / Backend 层
    - `tools/dub_pipeline.py` 的 Auto Dubbing 入口只保留 `index-tts`
    - `src/subtitle_maker/domains/dubbing/pipeline.py` 删除 OmniVoice / VoxCPM 特化分支，仅保留 `index-tts` 主链路
    - 删除不再使用的 [src/subtitle_maker/backends/omni_voice.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/backends/omni_voice.py)、[src/subtitle_maker/backends/voxcpm_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/backends/voxcpm_api.py)、[tools/omnivoice_fastapi_server.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/omnivoice_fastapi_server.py) 及相关启动脚本
  - 测试层
    - 删除或改写所有 Auto Dubbing 的 OmniVoice / VoxCPM 测试
    - 保留并强化 `index-tts` 主链路测试
- [x] 风险与决策
  - 风险 1：`global-tts-backend` 可能不只被 Auto Dubbing 使用，直接删 UI 可能影响别的页面逻辑
    - 决策：先确认它在当前仓库是否只服务 Auto Dubbing；若不是，只对 Auto Dubbing 固定为 `index-tts`
  - 风险 2：`src/subtitle_maker/domains/dubbing/pipeline.py` 现在是共享运行时，粗暴删除 OmniVoice 分支可能误伤 review/save-redub
    - 决策：只保留 Auto Dubbing 仍会实际调用的 `index-tts` 路径；删除前先确认调用入口
  - 风险 3：测试当前已混入历史 OmniVoice/VoxCPM 断言，清理时容易把与 `index-tts` 无关的坏测试一起带走
    - 决策：按文件逐个删改，只保留 `index-tts` 主合同
- [x] 验证计划
  - `node --check src/subtitle_maker/static/js/dubbingPanel.js`
  - `uv run python -m py_compile` 覆盖 `dubbing_cli_api.py`、`jobs/command_builder.py`、`domains/dubbing/pipeline.py`、`tools/dub_pipeline.py`
  - 运行 `tests/test_dubbing_cli_api.py`、`tests/test_command_builder.py`、`tests/test_dubbing_runtime.py` 中保留下来的 `index-tts` 用例
  - 实际结果
    - [x] `node --check src/subtitle_maker/static/js/dubbingPanel.js`
    - [x] `uv run python -m py_compile src/subtitle_maker/jobs/command_builder.py src/subtitle_maker/dubbing_cli_api.py tools/dub_pipeline.py tests/test_command_builder.py tests/test_dubbing_cli_api.py tests/test_dubbing_runtime.py`
    - [x] `uv run python -m unittest -v tests.test_command_builder tests.test_dubbing_cli_api tests.test_manifest_contracts tests.test_job_recovery`
    - [x] `uv run python -m unittest tests.test_dubbing_runtime -v`
  - review
    - Auto Dubbing 的前端、API、命令构建和 CLI 入口已经固定收口到 `index-tts`
    - 旧的 OmniVoice / VoxCPM 深层运行时代码与历史测试仍有残留，但已不在 Auto Dubbing 主入口合同内；这次没有继续激进去删，目的是避免误伤现有 `index-tts`
    - 第二阶段已继续收口 `src/subtitle_maker/dubbing_cli_api.py` 与 `src/subtitle_maker/domains/dubbing/review.py`
    - `start/start-from-project` 不再声明 OmniVoice / VoxCPM 表单参数，review redub 运行时也统一强制 `index-tts`
    - 已补跑 `tests.test_dubbing_cli_api`、`tests.test_dubbing_runtime`、`tests.test_command_builder`、`tests.test_manifest_contracts`、`tests.test_job_recovery`
    - 第三阶段已完成 manifest / recovery / load-batch 合同清理：`BatchReplayOptions`、任务快照与 interrupted-batch 推断都不再携带 `fallback_tts_backend`、`omnivoice_*`、`voxcpm_api_url`，历史 batch 读取时统一归一到 `tts_backend=index-tts`
    - 第四阶段已完成长视频编排壳层清理：`tools/dub_long_video.py` 不再解析 `fallback_tts_backend`、`omnivoice_*`、`voxcpm_api_url` 等旧参数，执行期固定 `tts_backend=index-tts`；相关 `test_dub_long_video` 已同步改成 index-tts 主合同 / 旧请求归一化断言
    - 第五阶段已修复 `tools/dub_pipeline.py` 入口 stale args 缺陷：parser 只保留 `index-tts` 后，`main()` 也不再读取已移除的 `args.fallback_tts_backend` / `args.omnivoice_*` / `args.voxcpm_api_url`；新增源码级回归测试防止再次出现 parser 与 main 脱节
    - 第六阶段已收紧共享运行时 fallback 链路：`src/subtitle_maker/domains/dubbing/pipeline.py` 的 `synthesize_text_once()` 现在直接拒绝 `fallback_tts_backend!=none`，并移除了 grouped / per-line 两处 `fallback_tts_after_invalid_audio` 活分支；相关 runtime 测试已改为断言“拒绝 fallback 配置”而不是“自动切到 OmniVoice”
    - 第七阶段已删除共享运行时里剩余的 `voxcpm-omnivoice` 宽松验收活分支：`pipeline.py` 的 relaxed timing 只再允许独立 `omnivoice` 命中，相关 `group_voxcpm_omnivoice_relaxed_timing_accept` / `voxcpm_omnivoice_relaxed_timing_accept` 测试与 grouped 包装层 `voxcpm_api_url` 透传坏测试已移除
    - 已补跑 `uv run python -m py_compile src/subtitle_maker/domains/dubbing/pipeline.py tests/test_dubbing_runtime.py tests/test_dub_pipeline_references.py`
    - 已补跑 `uv run python -m unittest -v tests.test_dubbing_runtime tests.test_dub_pipeline_references`
    - 第八阶段计划：继续删除 Auto Dubbing 已不可达的 OmniVoice / VoxCPM 深层残留
      - 先删 `voxcpm_api_url` 透传、`src/subtitle_maker/backends/voxcpm_api.py` 和相关导出/测试残留
      - 再删 `tools/omnivoice_fastapi_server.py`、`start_omnivoice_api.sh`、`stop_omnivoice_api.sh`、`tests/test_omnivoice_fastapi_server.py` 以及 `start.sh` / `stop.sh` 中的本地 OmniVoice 服务文案与清理逻辑
      - 同步清掉 `tools/dub_pipeline.py` 中 parser 已经封死、但源码仍残留的 OmniVoice 专用参考音/分组合成分支与空参数透传
      - 保留 `index-tts` 主链验证：`tests.test_command_builder`、`tests.test_dubbing_cli_api`、`tests.test_dub_long_video`、`tests.test_dub_pipeline_references`、`tests.test_dubbing_runtime`

## 42. 2026-05-05 修复 OmniVoice 单人 seg_0005~seg_0010 句首吞字/乱音
- [x] 现状证据确认（只看 `omnivoice + single`）
  - `outputs/dub_jobs/web_20260505_113045/longdub_20260505_193050/segment_jobs/segment_0001/manifest.json`
    - `seg_0005/0006/0008` 走 `target_retry + fit_timing`
    - `seg_0007/0009/0010` 走 `natural accept`
    - 说明问题同时存在于“自然保留”和“带 duration 重试”两条路径，不是单一 `fit_timing` 问题
  - `src/subtitle_maker/domains/dubbing/pipeline.py:2385`
    - 当前 `OmniVoice + single` 明确跳过 `trim_silence_edges()`
    - 注释是“避免误裁句首辅音”，但副作用是 API 产出的前导脏音也被完整保留
  - 实际 wav 头部检测
    - `seg_0007.wav`、`seg_0009.wav` 开头约 `0.47s` 低能量/静音
    - `seg_0005.wav`、`seg_0006.wav`、`seg_0008.wav` 也有明显前导静音/低能量段
    - 这与用户听到的“前面吞字/乱读音”一致
- [ ] 实施计划（待确认后编码）
  - `src/subtitle_maker/domains/dubbing/alignment.py`
    - 新增“仅清理句首异常前导”的保守裁剪函数
    - 规则：只裁前导静音/脏音，不裁句尾；保留 pad；限制最大裁剪长度，避免误伤低能量首字
  - `src/subtitle_maker/domains/dubbing/pipeline.py`
    - 仅在 `OmniVoice + single` 路径启用这个“句首保守清理”
    - 保留现有自然生成优先、超差再 `duration retry` 的策略
    - 不改 `index-tts`、不改 grouped、多说话人链路不动
  - `tests/test_dubbing_runtime.py`
    - 新增单测覆盖“只裁前导、不裁句尾、且仅对 `OmniVoice + single` 生效”
- [ ] 验证
  - `uv run python -m py_compile src/subtitle_maker/domains/dubbing/alignment.py src/subtitle_maker/domains/dubbing/pipeline.py tests/test_dubbing_runtime.py`
  - `uv run python -m unittest tests.test_dubbing_runtime -v`
  - 如有必要，对问题段做一次本地重跑，确认 `seg_0005~seg_0010` 的前导静音显著下降

## 41. 2026-05-05 修复 OmniVoice 单人“单条配音混音/糊音”根因链路
- [x] 根因证据确认（非猜测）
  - `outputs/dub_jobs/web_20260505_051329/longdub_20260505_131335/batch_manifest.json`
    - `tts_backend=omnivoice`
    - `dubbing_mode=single`
    - `grouped_synthesis=true`（此前仍在分组合成）
    - `paths.preferred_audio` 指向 `dubbed_mix_full.wav`（默认播放混合轨）
  - `segment_0001/logs/segment_0001.jsonl`
    - 多次 `group_tts_started`（说明并非逐句原子链路）
    - 每组都 `edge_fade_applied=true`（会压低句首瞬态）
  - `outputs/omnivoice_api.log`
    - API 请求 `text_preview` 是组文本，不是 `ref_text`
    - 证实 API 没把 `ref_text` 直接当正文念（当前实现重点问题不在这里）
- [x] 只改 OmniVoice 单人链路（不影响 index-tts）
  - `src/subtitle_maker/dubbing_cli_api.py`
    - `omnivoice+single` 启动命令默认 `merge_track=vocals`
  - `tools/dub_pipeline.py`
    - `omnivoice` 一律强制逐句（`grouped_synthesis=false`）
  - `src/subtitle_maker/domains/dubbing/pipeline.py`
    - `omnivoice` 单/多人都禁用最终 `edge_fade`
  - `tools/repair_bad_segments.py`
    - 批次重建时 `omnivoice+single` 的 `preferred_audio` 优先 `vocals`
  - `src/subtitle_maker/static/js/dubbingPanel.js`
    - 前端在 `omnivoice+single` 下优先选 `vocals` 音轨回放
- [ ] 验证
  - [x] `node --check src/subtitle_maker/static/js/dubbingPanel.js`
  - [x] `uv run python -m py_compile src/subtitle_maker/dubbing_cli_api.py src/subtitle_maker/domains/dubbing/pipeline.py tools/dub_pipeline.py tools/repair_bad_segments.py`
  - [ ] 端到端跑一轮 `omnivoice+single`，确认：
    - `grouped_synthesis=false`
    - `segment_audio_leveled.data.edge_fade_applied=false`
    - `paths.preferred_audio` 指向 `dubbed_vocals_full.wav`

## 40. 2026-05-05 Auto Dubbing 的 Optional dubbing windows 升级为 HH:MM:SS
- [x] 模板输入框升级
  - `src/subtitle_maker/templates/index.html`
    - `auto-dub-range-start-*` / `auto-dub-range-end-*` 新增小时位 `HH`
    - 从 `MM:SS` 改为 `HH:MM:SS`
- [x] 前端绑定升级
  - `src/subtitle_maker/static/js/dubbingPanel.js`
    - 为 Auto Dubbing ranges controller 透传 `startHEl/endHEl`
    - 继续复用统一 `createTimeRangesController` 与 `timeToSeconds` 三参逻辑
- [x] 最小验证
  - `node --check src/subtitle_maker/static/js/dubbingPanel.js src/subtitle_maker/templates/index.html`

## 39. 2026-05-05 3号面板升级为 Video & Voice Slice（新增视频切片 + HH:MM:SS 区间）
- [x] 面板文案与结构
  - `src/subtitle_maker/templates/index.html`
    - 导航名：`Get Speaker Voice` -> `Video & Voice Slice`
    - 标题：`🎤 Get Speaker Voice` -> `🎬 Video & Voice Slice`
    - 在 `Extract vocals for selected ranges` 右侧新增 `Extract video for selected ranges` 卡片和按钮
    - 区间输入升级为 `HH:MM:SS`（start/end 都新增 `HH` 输入框）
- [x] 前端交互
  - `src/subtitle_maker/static/js/timeRanges.js`
    - 控制器支持三段时间输入（`startHEl/endHEl`）
    - `Use Current` 与 `clearInputs` 同步支持小时位
    - `timeToSeconds` 调用改为三参
  - `src/subtitle_maker/static/js/speakerVoicePanel.js`
    - 新增视频切片按钮事件，调用 `/speaker-voice/start-video-from-project`
    - 复用同一套 ranges
    - 轮询完成/失败时统一恢复两个按钮状态
  - `src/subtitle_maker/static/app.js`
    - `timeToSeconds` 升级兼容 `HH:MM:SS`（同时兼容旧两参调用）
    - `secondsToDisplay` 升级为 `HH:MM:SS`
- [x] 后端接口
  - `src/subtitle_maker/speaker_voice_api.py`
    - 新增视频切片任务执行器 `_run_speaker_video_task`
    - 新增任务入口 `/speaker-voice/start-video-from-project`
    - 新增视频任务队列 `_queue_video_task`
    - 下载接口支持 `video_range_*` 对应 `video_slice_*.mp4`
- [x] 最小验证
  - `node --check src/subtitle_maker/static/js/timeRanges.js src/subtitle_maker/static/js/speakerVoicePanel.js src/subtitle_maker/static/app.js`
  - `uv run python -m py_compile src/subtitle_maker/speaker_voice_api.py tests/test_speaker_voice_api.py`
  - `uv run python -m unittest tests.test_speaker_voice_api.SpeakerVoiceApiTests.test_start_video_from_project_creates_video_slice_task -v`

## 38. 2026-05-05 OmniVoice 收口为“仅单人 + 强制手动参考音”
- [x] 后端硬限制
  - `src/subtitle_maker/dubbing_cli_api.py`
    - `tts_backend=omnivoice` 时强制 `dubbing_mode=single`
    - 若请求显式传 `dubbing_mode=multi`，直接 400：`omnivoice only supports single mode now; multi mode is disabled`
    - 保留单人强校验：必须提供 `single_ref_audio`
    - 删除/停用 OmniVoice multi 的 `speaker_ref_map` 校验分支（不再走多人链路）
- [x] 前端限制
  - `src/subtitle_maker/static/js/dubbingPanel.js`
    - OmniVoice 模式下强制 `dubbing_mode=single`
    - Mode 下拉在 OmniVoice 时禁用并提示“仅支持单人模式”
    - 不再显示 OmniVoice 多人参考音区域
    - 提交时 OmniVoice 一律发送 `dubbing_mode=single`
- [x] 验证
  - `node --check src/subtitle_maker/static/js/dubbingPanel.js`
  - `uv run python -m py_compile src/subtitle_maker/dubbing_cli_api.py tests/test_dubbing_cli_api.py`
  - `uv run python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_start_auto_dubbing_requires_manual_reference_for_single_omnivoice -v`
  - `uv run python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_start_auto_dubbing_rejects_multi_mode_for_omnivoice -v`
  - `uv run python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_start_from_project_omnivoice_forces_single_mode_even_with_multi_speaker_subtitles -v`

## 37. 2026-05-05 修复 Auto Dubbing 自定义翻译 Prompt 在布局重排阶段丢失
- [x] 根因定位
  - `tools/dub_pipeline.py` 的 `reflow_cluster_with_llm()` 之前写死了 system prompt：
    - `"You are a subtitle layout editor for dubbing."`
  - 即使前面翻译阶段已经使用了 `translate_system_prompt`，重排阶段仍可能二次覆盖术语/人名策略
- [x] 实施修复
  - `tools/dub_pipeline.py`
    - `reflow_cluster_with_llm(...)` 新增 `system_prompt` 参数，并优先使用用户传入值
    - `smart_layout_translated_lines(...)` 新增 `system_prompt` 参数并透传给 `reflow_cluster_with_llm(...)`
    - `main()` 调用 `smart_layout_translated_lines(...)` 时传入 `args.translate_system_prompt`
- [x] 回归测试
  - `tests/test_dub_pipeline_asr_layout.py`
    - 新增 `test_reflow_cluster_with_llm_uses_custom_translate_system_prompt`
    - 断言重排 LLM 调用的 system message 等于用户自定义 prompt
- [x] 验证
  - `uv run python -m py_compile tools/dub_pipeline.py tests/test_dub_pipeline_asr_layout.py`
  - `uv run python -m unittest tests.test_dub_pipeline_asr_layout.DubPipelineAsrLayoutTests.test_reflow_cluster_with_llm_uses_custom_translate_system_prompt -v`
  - `uv run python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_start_from_project_passes_translate_system_prompt_into_command -v`
  - `uv run python -m unittest tests.test_web_routes_legacy.WebLegacyRouteTests.test_index_upload_and_stream_keep_working -v`

## 35. 2026-05-05 Auto Dubbing 增加翻译自定义 Prompt（Current Project/Standalone 共用）
- [x] 前端 UI
  - `src/subtitle_maker/templates/index.html` 的 Auto Dubbing 配置区新增 `Custom System Prompt (Optional)` 输入框
  - 文案明确：仅 source 字幕需翻译时生效，translated 字幕会跳过翻译
- [x] 前端提交流程
  - `src/subtitle_maker/static/js/dubbingPanel.js` 在启动请求里追加 `translate_system_prompt`（非空时）
- [x] 后端参数链打通
  - `src/subtitle_maker/dubbing_cli_api.py`：
    - `start` / `start-from-project` 接收 `translate_system_prompt`
    - `_normalize_auto_dubbing_request` 归一化并写入 options
    - 任务快照持久化该字段
    - `resume` 回放参数时继续携带该字段
    - `load-batch` 的中断批次字段推断保留该字段
- [x] 命令透传
  - `src/subtitle_maker/jobs/command_builder.py`：
    - `AutoDubbingCommandConfig` 增加 `translate_system_prompt`
    - 非空时追加 `--translate-system-prompt`
- [x] Manifest / recovery 回放兼容
  - `src/subtitle_maker/manifests/schema.py`、`readwrite.py`、`src/subtitle_maker/jobs/recovery.py` 增加 `translate_system_prompt` 读写
- [ ] 验证
  - [x] `uv run python -m unittest tests.test_command_builder -v`
  - [x] `uv run python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_start_from_project_passes_translate_system_prompt_into_command -v`
  - [x] `node --check src/subtitle_maker/static/js/dubbingPanel.js`
  - [x] `uv run python -m py_compile src/subtitle_maker/dubbing_cli_api.py src/subtitle_maker/jobs/command_builder.py src/subtitle_maker/manifests/readwrite.py src/subtitle_maker/jobs/recovery.py src/subtitle_maker/manifests/schema.py`

## 36. 2026-05-05 修复 Auto Dubbing custom prompt 未生效（前端字段丢失）
- [x] 根因定位
  - `src/subtitle_maker/templates/index.html` 的输入框 id 是 `auto-dub-translate-system-prompt`
  - `src/subtitle_maker/static/js/dubbingPanel.js` 读取的是 `auto-dub-translate-system-prompt` 的简写后缀 `translate-system-prompt`（拼接后实际查找 `auto-dub-translate-system-prompt`）
  - 同时兼容修复：当用户习惯在翻译面板 `#system-prompt` 填写时，Auto Dubbing 请求此前不会读取该值
- [x] 实施修复
  - `src/subtitle_maker/static/js/dubbingPanel.js`
    - `buildCommonStartFormData()` 中 `translate_system_prompt` 读取逻辑改为：
      1) 先读 Auto Dubbing 面板输入框
      2) 若为空，回退读取翻译面板 `#system-prompt`
    - 非空才追加 `translate_system_prompt`
- [x] 回归测试
  - `tests/test_web_routes_legacy.py` 增加首页断言：`id="auto-dub-translate-system-prompt"` 必须存在，防止模板回退时再丢字段
- [x] 验证
  - `node --check src/subtitle_maker/static/js/dubbingPanel.js`
  - `uv run python -m unittest tests.test_command_builder.CommandBuilderTests.test_build_auto_dubbing_command_keeps_optional_replay_flags -v`
  - `uv run python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_start_from_project_passes_translate_system_prompt_into_command -v`
  - `uv run python -m unittest tests.test_web_routes_legacy.WebLegacyRouteTests.test_index_upload_and_stream_keep_working -v`

## 33. 2026-05-05 修复 OmniVoice 多人首句超时长与句首发糊
- [ ] 根因确认
  - `seg_0001` 目标 14s，实际 17s；manifest 显示 `synthesis_duration_control=natural` 且命中 `voxcpm_omnivoice_relaxed_timing_accept`
  - 说明当前多人链路未向 OmniVoice 传入时长目标，并且超时长仍被“宽松放行”
- [ ] 代码修复（仅 `OmniVoice + multi`）
  - 长句启用 `target_duration_sec`（短句保留自然时长）
  - 关闭 `relaxed_timing_accept` 宽松放行
  - 关闭最终 `edge_fade`，避免句首进一步被淡入压低
- [ ] 最小验证
  - `tests/test_dubbing_runtime.py` 相关用例通过
  - 不改 `index-tts` 逻辑与测试合同

## 34. 2026-05-05 增强 start.sh 启动后的 Auto Dubbing 运行日志（TTS底座+分组策略）
- [x] 运行时日志增强
  - `src/subtitle_maker/dubbing_cli_api.py` 在 `[auto-dubbing]` 摘要中新增 `runtime_brief`
  - 新增字段：`tts_base`、`dubbing_mode`、`grouping`、`timing_mode`、`merge`、`range`、`segment`
  - `OmniVoice + multi` 分组摘要明确显示 `speaker-aware-rebuild+per-line` 及 `grouped/force_fit` 生效值
- [x] 任务快照补充
  - 任务状态中新增 `grouped_synthesis_effective`、`force_fit_timing_effective`、`effective_range_strategy`
  - 创建任务时即计算并保存 `runtime_brief`，并触发一次额外日志输出
- [x] 启动脚本文案
  - `start.sh` 增加提示：Auto Dubbing 日志会打印底座、分组、时长、merge、范围策略等快照
- [x] 验证
  - `python3 -m py_compile src/subtitle_maker/dubbing_cli_api.py src/subtitle_maker/jobs/command_builder.py` 通过
  - `python3 -m unittest tests.test_dubbing_cli_api -v` 本地因缺依赖全量 skip（无失败）

## 32. 2026-05-05 修正 OmniVoice 多人 source 链路未生效的字幕重构合并
- [x] 根因核对
  - 生产批次 `web_20260504_152356/longdub_20260504_232401` 为 `input_srt_kind=source`
  - 历史实现只在 `translated` 分支做 speaker-aware 合并，导致 source 主链路未触发
- [x] 实施修复
  - `tools/dub_pipeline.py` 新增 `merge_short_source_subtitles_speaker_aware(...)`
  - 在 `main()` 中 `tts_backend=omnivoice && dubbing_mode=multi && input_srt_kind=source` 时，
    在翻译前执行真实重构并落盘 `source.srt`
  - 保留 strict：任一行缺 `speaker_id` 直接失败
- [x] 回归验证
  - `PYTHONPATH=src python3 -m unittest tests.test_dub_pipeline_references tests.test_dub_long_video -v` 通过（23 tests）
  - 新增用例：`test_main_omnivoice_multi_source_applies_speaker_aware_source_merge`

### Review（2026-05-05 修正 source 链路未生效）
- 结论：
  - 之前你说“没重构”是对的：source 主链路没有用到这套逻辑；
  - 现在已接入 source 主链路，合并后是新字幕行（行数会下降，时间戳按首尾重建）。
- 风险边界：
  - 只影响 `OmniVoice + multi + source`；
  - `index-tts` 与其他分支不变。

## 31. 2026-05-04 OmniVoice 多人模式 speaker-aware 字幕重构合并
- [x] 仅在 `OmniVoice + multi + translated` 启用 speaker-aware 重构合并
  - `tools/dub_long_video.py` 新增 `maybe_merge_translated_input_subtitles_speaker_aware(...)`
  - 先按 `speaker_id + gap` 切 run，再在 run 内复用 `merge_short_source_subtitles(...)`
  - 产出真实重构后的字幕行（减少行数、更新时间戳、保留 `speaker_id`）
- [x] strict 合同
  - OmniVoice 多人下任一行缺 `speaker_id` 直接报错
  - 不拼回 `Speaker N:` 前缀，正文保持纯文本
- [x] 作用范围保护
  - 只改 `OmniVoice + multi` 分支
  - `index-tts` / `single` / 其他链路不变
- [x] 日志增强
  - translated merge 日志新增 `speaker_run_count`
- [x] 测试与回归
  - 新增 4 条 speaker-aware 专项测试（不跨 speaker、同 speaker 合并并重构时间戳、缺 `speaker_id` 失败、文本无前缀）
  - `PYTHONPATH=src python3 -m unittest tests.test_dub_long_video tests.test_dub_pipeline_references -v` 全部通过（22 tests）

### Review（2026-05-04 OmniVoice speaker-aware merge）
- 根因与修复：
  - 旧逻辑只按时间窗并句，可能把不同 speaker 的短句拼入同一合成上下文；
  - 新逻辑先按 speaker 重构 run，再在 run 内并句，避免跨 speaker 污染。
- 结果：
  - 多人 OmniVoice 的 segment 输入字幕会先真实重构（非仅组内组合）；
  - `speaker_id` 元数据全程保留，用于后续严格 reference 映射。
- 回归结论：
  - `tests.test_dub_long_video` 与 `tests.test_dub_pipeline_references` 均通过；
  - `index-tts` 相关测试未出现行为回退。

## 30. 2026-05-04 修复 translating 阶段的 Translator 懒初始化
- [x] 修复翻译调用点
  - `tools/dub_pipeline.py` / `src/subtitle_maker/domains/dubbing/pipeline.py` 改为先 `_ensure_client()` 再发起 LLM 请求
  - 避免 `translator.client` 为空时直接触发 `NoneType.chat`
- [x] 回归测试
  - 新增 `translate_batch_with_budget` 的懒初始化测试
- [x] 验证
  - `PYTHONPATH=src python3 -m py_compile tools/dub_pipeline.py src/subtitle_maker/domains/dubbing/pipeline.py tests/test_dubbing_runtime.py`
  - `.venv/bin/python -m unittest tests.test_dubbing_runtime.DubbingPipelineTests.test_translate_batch_with_budget_lazy_initializes_translator_client -v`

### Review（2026-05-04 修复 Translator 懒初始化）
- 已完成：
  - 所有直接访问 `translator.client.chat` 的翻译/重写点已改为先 `_ensure_client()`
  - `Translator.client=None` 时也能正常进入翻译流程
- 影响范围：
  - 仅修复 LLM client 初始化方式
  - 不改 `index-tts` / OmniVoice 参考音策略

## 29. 2026-05-04 修复 start-from-project 的 speaker sidecar 早于多人校验
- [x] 修复 long-video 入口
  - `tools/dub_long_video.py` 新增 `--speaker-metadata-path`
  - 在多人模式校验前先把 `speaker_id` sidecar 合回字幕
  - 允许 `start-from-project` 只靠 sidecar 维持多 speaker 语义
- [x] 回归测试
  - 新增纯文本字幕 + sidecar 的多人模式测试
- [x] 验证
  - `PYTHONPATH=src python3 -m py_compile tools/dub_long_video.py tests/test_dub_long_video.py`
  - `PYTHONPATH=src python3 -m unittest tests.test_dub_long_video.DubLongVideoTests.test_main_multi_mode_accepts_sidecar_speaker_metadata_without_text_prefixes -v`

### Review（2026-05-04 修复 start-from-project speaker sidecar）
- 已完成：
  - `tools/dub_long_video.py`
    - 接收 `--speaker-metadata-path`
    - 在 `multi` 校验前先把 sidecar 合回输入字幕
    - 多人模式不再只认正文里的 `Speaker 1:` 前缀
  - `tests/test_dub_long_video.py`
    - 新增纯文本字幕 + sidecar 的回归测试
- 未影响：
  - `index-tts` 的逐句参考音链路
  - OmniVoice 手动参考音输入合同

## 28. 2026-05-04 插入 3.Get Speaker Voice 功能
- [x] 独立后端接口
  - 新增 `/speaker-voice/start`
  - 新增 `/speaker-voice/start-from-project`
  - 新增 `/speaker-voice/status/{task_id}`
  - 新增 `/speaker-voice/artifact/{task_id}/{artifact}`
- [x] 前端导航与面板
  - 左侧菜单插入 `3. Get Speaker Voice`
  - `Auto Dubbing` 顺延为第 `4` 项
  - 新增 `Current Project` + `Standalone Upload` 双模式面板
- [x] `Ranges` 复用
  - 抽出共享 `timeRanges.js`
  - `Auto Dubbing` 改走共享 ranges 控制器
  - `Get Speaker Voice` 复用同一套区间交互与校验
- [x] 导出合同
  - 每个 range 单独导出一个 wav
  - 结果写入 `outputs/speaker_voice/web_<task_id>/...`
  - 人声分离失败直接任务失败，不回退原混音
- [ ] 验证
  - `node --check src/subtitle_maker/static/app.js`
  - `node --check src/subtitle_maker/static/js/dubbingPanel.js`
  - `node --check src/subtitle_maker/static/js/speakerVoicePanel.js`
  - `node --check src/subtitle_maker/static/js/timeRanges.js`
  - `PYTHONPATH=src python3 -m py_compile src/subtitle_maker/speaker_voice_api.py src/subtitle_maker/app/main.py`
  - `PYTHONPATH=src python3 -m unittest tests.test_speaker_voice_api -v`

### Review（2026-05-04 Get Speaker Voice）
- 已完成：
  - 新增独立 `speaker_voice_api`，与 Auto Dubbing 任务流分离
  - 新增 `Get Speaker Voice` 主菜单与面板
  - 抽出共享 `timeRanges.js`，避免 ranges 逻辑在两个面板漂移
  - 导出结果按每个 range 一段 wav 落到独立 `outputs/speaker_voice` 目录
- 约束保持：
  - 不依赖字幕
  - 不进入翻译 / 配音 / speaker 识别逻辑
  - `index-tts` / `omnivoice` 现有链路不应受影响

## 27. 2026-05-04 修复 start_auto_dubbing 里的过期 voxcpm_api_url 传参崩溃
- [x] 复核 `500` traceback 对应代码路径
  - `src/subtitle_maker/dubbing_cli_api.py::_queue_auto_dubbing_task`
  - `AutoDubbingCommandConfig.__init__()` 已不再接受 `voxcpm_api_url`
- [x] 修复真实运行时调用链
  - Auto Dubbing 启动命令不再给 `AutoDubbingCommandConfig` 传 `voxcpm_api_url`
  - review/save-and-redub 路径不再给 `_switch_tts_runtime_on_demand` 和 `SegmentRedubCommandConfig` 传过期字段
  - 保留 `DEFAULT_VOXCPM_API_URL` 常量仅作历史 task/manifest 兼容读取，避免旧恢复路径直接 `NameError`
- [ ] 验证
  - `PYTHONPATH=src python3 -m py_compile src/subtitle_maker/dubbing_cli_api.py`
  - `./stop.sh && ./start.sh`

### Review（2026-05-04 修复过期 voxcpm_api_url 崩溃）
- 根因：
  - `src/subtitle_maker/jobs/command_builder.py` 里的 `AutoDubbingCommandConfig` / `SegmentRedubCommandConfig` 已删掉 `voxcpm_api_url`
  - 但 `src/subtitle_maker/dubbing_cli_api.py` 的启动与 redub 路径还在继续传这个字段，导致运行时 `TypeError`
- 本次收口：
  - 只清理会进入真实执行路径的过期传参
  - 不大拆历史 manifest / task 字段，避免旧批次读取时再引入新回归

## 26. 2026-05-04 OmniVoice 按字幕自动判单/多人，并强制手动参考音
- [x] 前端交互收口
  - `tts_backend=omnivoice` 时，不再依赖用户手动切 `single/multi`
  - 根据当前字幕是否存在多个 `speaker_id` / `Speaker N:` 自动判定模式
  - 单人显示单参考音上传区；多人列出每个 speaker 的参考音上传控件
  - 删除 OmniVoice 文案中的“默认自动截取”描述，明确为“必须手动上传”
- [x] 后端合同收口
  - `tts_backend=omnivoice` 时，根据解析出的 `detected_speaker_ids` 自动推断 `dubbing_mode`
  - 单人必须有 `single_ref_audio`
  - 多人必须每个 speaker 都有手动上传参考音
  - 不再允许 OmniVoice 走自动截取参考音兜底
- [x] 保持 `index-tts` 不受影响
  - `index-tts` 仍保留原来的手动 `single/multi` 选择
  - `index-tts` 仍保留自动截取参考音逻辑
- [x] 验证
  - `node --check src/subtitle_maker/static/js/dubbingPanel.js`
  - `PYTHONPATH=src python3 -m py_compile src/subtitle_maker/dubbing_cli_api.py`

### Review（2026-05-04 OmniVoice 自动判单/多人 + 强制手动参考音）
- 已完成：
  - `src/subtitle_maker/static/js/dubbingPanel.js`
    - `omnivoice` 选中时，根据字幕里的 `speaker_id` / `Speaker N:` 自动把模式切成 `single` 或 `multi`
    - 多人时会自动渲染每个 speaker 的参考音上传控件
    - `omnivoice` 文案已删除“自动截取参考音”描述，统一改为“必须手动上传”
  - `src/subtitle_maker/templates/index.html`
    - 单人 / 多人 OmniVoice 参考音标题与提示已改成强制手动上传语义
  - `src/subtitle_maker/dubbing_cli_api.py`
    - `tts_backend=omnivoice` 时，后端按 `detected_speaker_ids` 自动推断 `dubbing_mode`
    - 检测到多 speaker 时，不再允许落回单人参考音逻辑
- 未影响：
  - `index-tts` 的手动 `single/multi` 选择仍保留
  - `index-tts` 的自动截取参考音逻辑未动
- 已验证：
  - `node --check src/subtitle_maker/static/js/dubbingPanel.js`
  - `PYTHONPATH=src python3 -m py_compile src/subtitle_maker/dubbing_cli_api.py`

## 25. 2026-05-04 删除 voxcpm-omnivoice 链路
- [x] 收口产品入口
  - 左侧 TTS 下拉删除 `VoxCPM + OmniVoice`
  - Auto Dubbing 前端不再出现 `voxcpm-omnivoice` 分支文案与提交流程
- [x] 收口后端主合同
  - `tts_backend` 白名单移除 `voxcpm-omnivoice`
  - API normalize / runtime lazy-start / command builder 不再处理 `voxcpm_api_url`
  - `pipeline.py` 不再保留 `voxcpm-omnivoice` 合成分支
- [x] 保留历史兼容最小化
  - manifest/schema/readwrite 中旧 `voxcpm_api_url` 字段先不强拆，避免历史任务读取崩溃
  - 但新任务不再生成、不再使用这条链路
- [x] 验证
  - `node --check src/subtitle_maker/static/app.js`
  - `node --check src/subtitle_maker/static/js/dubbingPanel.js`
  - `PYTHONPATH=src python3 -m py_compile src/subtitle_maker/dubbing_cli_api.py src/subtitle_maker/domains/dubbing/pipeline.py src/subtitle_maker/jobs/command_builder.py`

### Review（2026-05-04 删除 voxcpm-omnivoice 链路）
- 已完成：
  - `src/subtitle_maker/templates/index.html`
    - 左侧 TTS 下拉已删除 `VoxCPM + OmniVoice`
  - `src/subtitle_maker/static/app.js`
    - 全局 TTS 归一化只保留 `index-tts` / `omnivoice`
  - `src/subtitle_maker/static/js/dubbingPanel.js`
    - 删除 `voxcpm-omnivoice` UI 分支、提示文案、禁用逻辑和提交流程特判
  - `src/subtitle_maker/dubbing_cli_api.py`
    - `tts_backend` 白名单移除 `voxcpm-omnivoice`
    - 移除 VoxCPM 自动探活 / 自启动 / 停止逻辑
    - `start` / `start-from-project` 不再按 `voxcpm-omnivoice` 特判上传参考音
  - `src/subtitle_maker/domains/dubbing/pipeline.py`
    - 删除 `synthesize_text_once()` 中 `voxcpm-omnivoice` 分支
    - 运行时不再构造 anchor-only 特判
  - `src/subtitle_maker/jobs/command_builder.py`
    - 不再构造 `--voxcpm-api-url`
    - 不再识别 `voxcpm-omnivoice` 特判
  - `start.sh` / `stop.sh`
    - 日志与停服脚本不再提及/管理 VoxCPM
- 保留但未强拆：
  - manifest/schema/models/recovery/readwrite 中旧 `voxcpm_api_url` 字段仍保留，只为避免历史任务读取崩溃
  - 测试文件和 `tasks/todo.md` 的历史记录里仍有旧 `voxcpm-omnivoice` 文本
- 已验证：
  - `node --check src/subtitle_maker/static/app.js`
  - `node --check src/subtitle_maker/static/js/dubbingPanel.js`
  - `PYTHONPATH=src python3 -m py_compile src/subtitle_maker/dubbing_cli_api.py src/subtitle_maker/domains/dubbing/pipeline.py src/subtitle_maker/jobs/command_builder.py`

## 24. 2026-05-04 VoxCPM+OmniVoice 直出 anchor，停掉劣化的二段 OmniVoice 重配
- [x] 复核最新 `web_20260504_040928/longdub_20260504_120934` 产物与代码链路
  - 确认 `group_*_anchor.wav` 是 VoxCPM 正常产物
  - 确认 `group_*_raw.wav` / `group_*_trim.wav` 的劣化发生在第二段 OmniVoice 重配
- [x] 修改 `src/subtitle_maker/domains/dubbing/pipeline.py`
  - `voxcpm-omnivoice` 改为直接使用 VoxCPM 产出的 `anchor` 作为正式输出
  - 停止把 `anchor` 再送入 OmniVoice 做二次重配
  - 保留既有 `anchor_ref_path` / `anchor_text` manifest 语义，方便追溯
- [x] 更新 `tests/test_dubbing_runtime.py`
  - `synthesize_text_once()` 对 `voxcpm-omnivoice` 只调用 VoxCPM，不再调用 OmniVoice
  - grouped/runtime 测试按新直出语义校正
- [x] 验证
  - `PYTHONPATH=src python3 -m py_compile src/subtitle_maker/domains/dubbing/pipeline.py tests/test_dubbing_runtime.py`
  - `PYTHONPATH=src python3 -m unittest tests.test_dubbing_runtime -v`

### Review（2026-05-04 VoxCPM+OmniVoice 直出 anchor）
- 结论：
  - 最新批次 `web_20260504_040928/longdub_20260504_120934` 里，`group_*_anchor.wav` 是 VoxCPM 产出的正常语音；
  - `group_*_raw.wav` / `group_*_trim.wav` 的“垃圾感”来自第二段 OmniVoice 把已正确的 anchor 再重配一次，不是 trim 本身导致。
- 已完成：
  - `src/subtitle_maker/domains/dubbing/pipeline.py`
    - `voxcpm-omnivoice` 现在只跑 VoxCPM anchor 生成
    - 生成完成后直接把 `anchor` 复制为正式 `output_path`
    - `final_backend` 改为 `voxcpm`
  - `tests/test_dubbing_runtime.py`
    - 原“VoxCPM 后继续调用 OmniVoice”的断言已改为“不再调用 OmniVoice”
    - 保留 `anchor_ref_path` / `anchor_text` 合同校验
- 已验证：
  - `PYTHONPATH=src python3 -m py_compile src/subtitle_maker/domains/dubbing/pipeline.py tests/test_dubbing_runtime.py`
  - `PYTHONPATH=src python3 -m unittest tests.test_dubbing_runtime.DubbingPipelineTests.test_synthesize_text_once_voxcpm_omnivoice_uses_anchor_as_final_output tests.test_dubbing_runtime.DubbingPipelineTests.test_synthesize_text_once_voxcpm_omnivoice_uses_reference_prompt_only_for_voxcpm tests.test_dubbing_runtime.DubbingPipelineTests.test_synthesize_segments_grouped_voxcpm_omnivoice_passes_anchor_output_path -v`
    - 本机因缺 `soundfile`，3 条显式 `skipped`

## 22. 2026-05-04 共享 OmniVoice API 同时兼容 omnivoice 与 voxcpm-omnivoice
- [x] 核对共享 OmniVoice API 的当前实现与两条调用链：
  - `tools/omnivoice_fastapi_server.py::ServerState.synthesize`
  - `src/subtitle_maker/backends/omni_voice.py::OmniVoiceBackend._synthesize_via_api`
  - `src/subtitle_maker/domains/dubbing/pipeline.py::synthesize_text_once`
- [x] 修正共享 API 逻辑：
  - `omnivoice` 直连时不再把 `ref_text` 混入正式 `text`
  - `voxcpm-omnivoice` 走同一 API 时保持 anchor 语义正确
- [x] 补服务端定向测试：
  - 有 `ref_audio/ref_text` 时通过 `create_voice_clone_prompt()` 构造克隆提示
  - `generate()` 只吃正式 `text` + `voice_clone_prompt`
  - 不再把 `ref_audio/ref_text` 直接透传给 `generate()`
- [x] 跑定向编译与单测：
  - `py_compile`
  - `tests.test_omnivoice_fastapi_server`
  - 必要时补跑 `tests.test_dubbing_runtime`

### Review（2026-05-04 共享 OmniVoice API 双兼容）
- 结论：
  - 共享 `tools/omnivoice_fastapi_server.py` 现在按“先 `create_voice_clone_prompt()`，清空 `voice_clone_prompt.ref_text`，再 `generate(text=正式正文, voice_clone_prompt=...)`”工作。
  - 关键根因：OmniVoice 本体会把 `voice_clone_prompt.ref_text + text` 放进文本条件；只是不直接传 `ref_text` 参数还不够，必须清掉 prompt 内部的 `ref_text`。
  - 这能同时支持两种上游：
    - `omnivoice`：`ref_audio=手动参考音`，`ref_text=参考音真实文本`
    - `voxcpm-omnivoice`：`ref_audio=VoxCPM 产出的 anchor`，`ref_text=anchor 实际文本`
- 已补测试：
  - `tests/test_omnivoice_fastapi_server.py`
    - 覆盖“有参考音时只把 `ref_text` 用于构造 clone prompt，不进入正式 `text`”
    - 覆盖“传给 `generate()` 的 `voice_clone_prompt.ref_text` 已清空”
    - 覆盖“无参考音时不构造 clone prompt”
    - 同时把测试改成缺 `numpy/soundfile/torch` 时类级别 skip，避免导入期假失败
- 已验证：
  - `PYTHONPATH=src python3 -m py_compile tools/omnivoice_fastapi_server.py tests/test_omnivoice_fastapi_server.py`
  - `PYTHONPATH=src python3 -m unittest tests.test_omnivoice_fastapi_server -v`
    - 本机因缺 `numpy/soundfile/torch`，`4` 条显式 `skipped`
  - `PYTHONPATH=src python3 -m unittest tests.test_dubbing_runtime -v`
    - 本机因缺 `soundfile`，`47` 条显式 `skipped`

## 23. 2026-05-04 OmniVoice 短字幕与时长偏差不再丢内容
- [x] 复核最新失败批次：
  - `web_20260504_034718/longdub_20260504_114723`
  - 16 条字幕被合成成 7 个 TTS group
  - `seg_0016` 因 1.12s 低于 1.2s 安全线被写成 missing
- [x] 修改 plain `omnivoice` 策略：
  - 有可发音文本时不再因目标时长低于 1.2s 直接写 `_missing.wav`
  - `synthesize_text_once()` 对 plain `omnivoice` 打开 relaxed validation，避免后端二次拦截短句
  - plain `omnivoice` 也复用 OmniVoice family 宽松时长接受策略
- [x] 更新测试语义：
  - 短句应尝试 TTS
  - grouped 短句应尝试 TTS
  - 有音频时不写 missing
- [x] 验证：
  - `PYTHONPATH=src python3 -m py_compile src/subtitle_maker/domains/dubbing/pipeline.py tests/test_dubbing_runtime.py`
  - `PYTHONPATH=src python3 -m unittest tests.test_dubbing_runtime.DubbingPipelineTests.test_synthesize_segments_omnivoice_short_text_still_attempts_tts tests.test_dubbing_runtime.DubbingPipelineTests.test_synthesize_segments_grouped_omnivoice_short_group_still_attempts_tts -v`
    - 本机因缺 `soundfile`，2 条显式 `skipped`

## 21. 2026-05-04 OmniVoice / VoxCPM+OmniVoice 语义收口与首句预热
- [x] 收口 API 上传入口：
  - `voxcpm-omnivoice` 不再接收/落盘手动 `single_ref_audio_file`
  - `voxcpm-omnivoice` 不再接收/落盘手动 `speaker_ref_files`
- [x] 收口命令与恢复合同：
  - `voxcpm-omnivoice` 不再透传 `single_ref_audio/single_ref_text/speaker_ref_map`
  - manifest / recovery / replay 保持同一语义
- [x] 收口 CLI 运行时语义：
  - `omnivoice` 的 `ref_text` 仅表示手动参考音频真实文本
  - `voxcpm-omnivoice` 只走自动截取参考音
- [x] 在 runtime TTS 调用层补 `omnivoice` 首句预热双跑：
  - 首条真实语音句先预热一次
  - 正式只保留第二次结果
- [x] 补定向测试并验证：
  - API
  - command builder
  - runtime

### Review（2026-05-04 OmniVoice / VoxCPM+OmniVoice 语义收口）
- 已完成：
  - `src/subtitle_maker/dubbing_cli_api.py`
    - `start/start-from-project` 在 `tts_backend=voxcpm-omnivoice` 时，不再落盘手动 single / multi 参考音上传
    - `normalize` 仍保持最终兜底：组合链路统一清空 `single_ref_audio/single_ref_text/speaker_ref_map`
  - `src/subtitle_maker/jobs/command_builder.py`
    - `voxcpm-omnivoice` 不再构造 `--single-speaker-ref` / `--single-ref-text` / `--speaker-ref-map-json`
    - 仅保留 `--voxcpm-api-url` 与 OmniVoice runtime 参数
  - `tools/dub_pipeline.py`
    - manifest replay 对 `voxcpm-omnivoice` 不再写回手动参考音字段
    - 真实运行时 `multi` 分支对 `voxcpm-omnivoice` 显式忽略手动 speaker refs
  - `src/subtitle_maker/domains/dubbing/pipeline.py`
    - 独立 `omnivoice` 新增首条真实语音句预热双跑
    - 预热只发生一次，且只记录 `omnivoice_warmup` attempt，正式输出只取第二次
- 已验证：
  - `PYTHONPATH=src python3 -m py_compile src/subtitle_maker/dubbing_cli_api.py src/subtitle_maker/jobs/command_builder.py src/subtitle_maker/domains/dubbing/pipeline.py tools/dub_pipeline.py tests/test_dubbing_cli_api.py tests/test_command_builder.py tests/test_dubbing_runtime.py`
  - `node --check src/subtitle_maker/static/js/dubbingPanel.js`
  - `PYTHONPATH=src python3 -m unittest tests.test_command_builder tests.test_dubbing_cli_api tests.test_dubbing_runtime -v`
    - `Ran 75 tests ... OK`
    - 其中 `66` 条因本机缺 `ffmpeg/soundfile` 被显式 `skipped`

## 20. 2026-05-04 新增独立 OmniVoice 模式（强制手动参考音 + 文字 prompt）
- [x] 现状分析：梳理前端 TTS 选项、后端白名单、CLI 参数与 OmniVoice 现有 reference_text 语义
- [x] Spec 2/3：定义新模式的前端输入契约与后端字段契约
- [x] Spec 3/3：风险、关键决策、推荐实现路径
- [x] HARD-GATE 后再编码
- [x] 前端新增第三个 `omnivoice` 选项，并补单人 / 多人 prompt 输入控件
- [x] API / CLI / command builder 放开 `omnivoice` 白名单并新增 `single_ref_text` / `speaker_ref_texts_json`
- [x] manifest / recovery / review-redub 持久化 `ref_text`，保证 restore / resume / 重跑不丢 prompt
- [x] 底层运行时收紧 `omnivoice` 语义：必须显式 ref_text，不再偷偷回退 source_text
- [x] 补充并跑通定向测试：前端参数归一化、命令构造、CLI 校验、manifest/recovery

### Review（2026-05-04 独立 OmniVoice 模式）
- 目标方向：
  - 在 `index-tts` 和 `VoxCPM + OmniVoice` 之间新增单独 `OmniVoice` 选项
  - 该模式不走自动截取参考音
  - 必须手动上传参考音频
  - 必须提供与参考音频一一对应的文字 prompt
- 已完成：
  - 左侧全局 TTS 下拉新增 `omnivoice`
  - `Auto Dubbing` 单人模式新增 `single_ref_text`
  - 多人模式每个 speaker 新增 `ref_text` 输入，并通过 `speaker_ref_texts_json` 透传
  - 后端/API/CLI/manifest/recovery 已支持 `single_ref_text` 与 `speaker_ref_map[].ref_text`
  - 独立 `omnivoice` 已收紧成“必须手动 ref 音频 + prompt”，不再回退字幕正文
  - `voxcpm-omnivoice` 与 `index-tts` 保持默认自动截取参考音的原语义
- 验证：
  - `PYTHONPATH=src python3 -m py_compile src/subtitle_maker/dubbing_cli_api.py src/subtitle_maker/domains/dubbing/pipeline.py src/subtitle_maker/jobs/command_builder.py src/subtitle_maker/manifests/readwrite.py src/subtitle_maker/manifests/schema.py src/subtitle_maker/jobs/recovery.py src/subtitle_maker/domains/subtitles/__init__.py src/subtitle_maker/domains/subtitles/speakers.py tools/dub_pipeline.py`
  - `node --check src/subtitle_maker/static/app.js`
  - `node --check src/subtitle_maker/static/js/dubbingPanel.js`
  - `PYTHONPATH=src python3 -m unittest tests.test_command_builder tests.test_dubbing_cli_api tests.test_manifest_contracts -v`
    - 通过
    - 其中 `19` 条因本机缺 `ffmpeg` / `soundfile` 被显式 `skipped`

## 19. 2026-05-04 启停脚本收敛到懒汉式 TTS 运行时
- [x] 复核 `start.sh/stop.sh` 与 `dubbing_cli_api.py` 的自动拉起/释放语义是否一致
- [x] 修改 `start.sh`：默认不预热 `voxcpm` / `omnivoice`，只保留 Web 服务启动
- [x] 修改 `stop.sh`：补齐 `voxcpm` 停止脚本、pid、端口和进程模式清理
- [x] 跑脚本语法检查与关键 Python 测试，确认没有把现有懒汉式运行时打坏

### Review（2026-05-04 启停脚本收敛）
- 目标改动：
  - 脚本层与后端运行时层统一成同一套懒汉式心智
  - `index-tts`、`voxcpm`、`omnivoice` 都只在实际使用时自动拉起
  - `stop.sh` 一次性释放相关本地服务
- 已完成：
  - `start.sh`
    - 删除旧的 `TTS_BACKEND=index-tts/omnivoice/qwen` 预热分支
    - 明确改成“只启动 Web，TTS 由后端按需拉起”
  - `stop.sh`
    - 新增 `VOXCPM_ROOT` / `VOXCPM_STOP_SCRIPT`
    - 新增 `voxcpm_api.pid` 清理
    - 新增 `tools/voxcpm_api_server.py` 进程特征清理
    - 新增 `8030` 端口兜底清理
- 说明：
  - `src/subtitle_maker/dubbing_cli_api.py` 里原本就有懒汉式 `_switch_tts_runtime_on_demand()`：
    - `index-tts`：先停 `omnivoice`
    - `voxcpm-omnivoice`：先停 `index-tts`，再按需拉起 `voxcpm` 和 `omnivoice`
  - 这次主要是把脚本层收口到和后端一致，不再出现“脚本预热一套、后端懒启动另一套”的双重语义
- 验证：
  - `bash -n start.sh stop.sh`
  - `PYTHONPATH=src python3 -m py_compile src/subtitle_maker/dubbing_cli_api.py`
  - `PYTHONPATH=src python3 -m unittest tests.test_dubbing_cli_api -v`
    - `12` 条因本机缺 `ffmpeg` 被显式 `skipped`

## 18. 2026-05-04 参考音默认自动截取，手动上传保留为覆盖选项
- [x] 复核当前 single / multi 参考音生成链路的默认值和校验点
- [x] 改后端默认策略为自动截取参考音：
  - single 模式默认从首条字幕开始后截 10 秒
  - multi 模式默认按每条字幕自动截对应原音频
- [x] 保留手动上传入口，但语义改成“覆盖默认自动参考音”
- [x] 更新前端文案与交互提示，避免用户误以为手动上传是必填
- [x] 补充单人 / 多人参考音默认策略的定向测试
- [x] 跑编译与定向单测验证默认自动截取行为

### Review（2026-05-04 参考音默认自动截取）
- 目标改动：
  - 默认不再要求用户先上传参考音
  - 手动上传只作为覆盖默认截取结果的可选项
  - 单人和多人分别采用不同的自动截取策略
- 已完成：
  - `src/subtitle_maker/dubbing_cli_api.py`
    - multi 模式不再要求 `speaker_ref_map` 全量必填
    - 仍保留已上传 speaker ref 的存在性和 speaker_id 合法性校验
  - `src/subtitle_maker/domains/dubbing/references.py`
    - 新增 `extract_reference_audio_from_first_subtitle()`
  - `tools/dub_pipeline.py`
    - single 模式默认从首条字幕起点自动截取共享参考音
    - multi 模式默认按每条字幕自动截参考音，手动 `speaker_ref_map` 只覆盖对应 speaker
  - `src/subtitle_maker/static/js/dubbingPanel.js`
    - 去掉多人模式“必须逐个上传参考音”的前端阻断
    - 表单仅在用户真的上传覆盖参考音时才提交 speaker ref 字段
  - `src/subtitle_maker/templates/index.html`
    - 单人 / 多人参考音文案已改成“默认自动截取，可手动覆盖”
- 验证：
  - `PYTHONPATH=src python3 -m py_compile src/subtitle_maker/dubbing_cli_api.py src/subtitle_maker/domains/dubbing/__init__.py src/subtitle_maker/domains/dubbing/references.py tools/dub_pipeline.py tests/test_dubbing_cli_api.py tests/test_dub_pipeline_references.py`
  - `PYTHONPATH=src python3 -m unittest tests.test_dub_pipeline_references -v`
    - `Ran 5 tests ... OK`
  - `PYTHONPATH=src python3 -m unittest tests.test_dubbing_cli_api -v`
    - `12` 条因本机缺 `torch` 被显式 `skipped`

## 17. 2026-05-04 第三轮收口：彻底移除 long-video 历史版本残留
- [x] 删除 `src/subtitle_maker/dubbing_cli_api.py` 中无主链路引用的 ASD 自启动/停止残留：
  - `ASD_PIPELINE_ROOT`
  - `ASD_PIPELINE_START_SCRIPT`
  - `ASD_PIPELINE_STOP_SCRIPT`
  - `_check_asd_pipeline_service()`
  - `_auto_start_local_asd_pipeline()`
  - `_ensure_asd_pipeline_service()`
  - `_stop_asd_pipeline_service_if_local()`
- [x] 删除 `tools/dub_long_video.py` 中历史 V3/V4 编排 helper：
  - `transcribe_source_subtitles_for_v3()`
  - `resolve_v3_input_subtitles()`
  - `prepare_v3_speaker_segment_subtitles()`
  - `prepare_v4_speaker_diarization_subtitles()`
  - 移除独立 `omnivoice` 的 translated merge 特判
- [x] 重写 `tests/test_dub_long_video.py` 为当前主合同测试：
  - `filter_segment_extra_args()` 仅过滤 long-video 专属字段
  - `clip_subtitles_for_segment()` 保留 `speaker_id`
  - 多人模式缺失 `speaker_ref_map` 时拒绝启动
  - 多人模式正确透传 `speaker_ref_map_json` 与 `speaker metadata`
  - batch manifest 写出 `pipeline_version=auto-dubbing`
- [ ] 跑编译与定向单测验证本轮收口

### Review（2026-05-04 第三轮收口）
- 已完成：
  - `src/subtitle_maker/dubbing_cli_api.py`
    - 删除已经失效的 `asd-pipeline` 自动启停壳，避免 API 层继续保留错误心智
  - `tools/dub_long_video.py`
    - 物理移除 `V3/V4` helper 与 `omnivoice_policy`
    - `clip_subtitles_for_segment()` 注释改成当前 `speaker_id` 语义
  - `tests/test_dub_long_video.py`
    - 从历史 `v3/v4/asd/fluidaudio` 大杂烩，重写成当前 `single/multi + index-tts/voxcpm-omnivoice` 主合同
- 待验证：
  - `py_compile`
  - `tests.test_dub_long_video`
  - 与上一轮已通过的新合同测试集合联跑

## 16. 2026-05-04 第二轮收口：旧后端壳与历史测试清理
- [x] 清理 review/redub 的旧版本语义：
  - `src/subtitle_maker/domains/dubbing/review.py` 删除 `pipeline_version` 运行时依赖
  - `src/subtitle_maker/dubbing_cli_api.py` 的 `_execute_review_redub/_rerun_segment_with_translated_srt` 不再透传 `pipeline_version`
- [x] 清理 manifest replay 构造残留：
  - `tools/dub_pipeline.py` 的 `_build_manifest_replay_options()` 改为写入 `dubbing_mode/single_ref_audio/speaker_ref_map/tts_model_path`
  - 删除其中 `diarization_backend/fluidaudio_*` 空壳字段
  - `tools/dub_long_video.py` 的 batch manifest 构造改为写入 `dubbing_mode/single_ref_audio/speaker_ref_map/tts_model_path`
  - 删除其中 `v3_asd_api_url/v3_speaker_segment_mode/diarization_backend/fluidaudio_*` 空壳字段
- [x] 重写关键测试到新主合同：
  - `tests/test_job_recovery.py`
  - `tests/test_manifest_contracts.py`
  - `tests/test_dubbing_cli_api.py`
  - `tests/test_dubbing_runtime.py` 中 review redub runtime 断言同步更新
- [x] 为缺少本机重依赖的测试补显式 skip：
  - `soundfile` 缺失时跳过 `tests/test_manifest_contracts.py` / `tests/test_dubbing_runtime.py`
  - `torch` 缺失时跳过 `tests/test_dubbing_cli_api.py`
- [x] 继续物理删除旧功能文件与调用链：
  - `src/subtitle_maker/domains/dubbing/diarization.py`
  - `src/subtitle_maker/domains/dubbing/speaker_segments.py`
  - `tools/pyannote_diarize_worker.py`
  - `tools/dub_long_video.py` 中未引用但仍在文件内的 `resolve_v3_input_subtitles/prepare_v3_speaker_segment_subtitles/prepare_v4_speaker_diarization_subtitles`

### Review（2026-05-04 第二轮收口）
- 已完成：
  - `src/subtitle_maker/domains/dubbing/review.py`
    - `SegmentRedubRuntimeOptions` 不再保存 `pipeline_version`
    - `resolve_segment_redub_runtime_options()` 不再接受 `fallback_pipeline_version`
  - `src/subtitle_maker/dubbing_cli_api.py`
    - review/redub 主路径彻底改成只依赖当前 auto dubbing 合同
    - `SegmentRedubCommandConfig` 不再注入旧版本字段
  - `tools/dub_pipeline.py` / `tools/dub_long_video.py`
    - 新写入 manifest 已统一成 `auto-dubbing + single/multi + speaker refs`
    - 停止把 `diarization/fluidaudio/v3/v4` 空壳字段写入 manifest
  - `tests/test_job_recovery.py`
    - 改为断言 `dubbing_mode/speaker_ref_map/voxcpm-omnivoice`
  - `tests/test_manifest_contracts.py`
    - 改为断言 `pipeline_version=auto-dubbing` 与新 replay 字段
  - `tests/test_dubbing_cli_api.py`
    - 改为覆盖当前主能力：single/multi、speaker ref、load/resume、review/redub
- 已验证：
  - `PYTHONPATH=src python3 -m py_compile src/subtitle_maker/dubbing_cli_api.py src/subtitle_maker/domains/dubbing/review.py src/subtitle_maker/jobs/recovery.py src/subtitle_maker/manifests/readwrite.py src/subtitle_maker/manifests/schema.py tools/dub_pipeline.py tools/dub_long_video.py`
  - `PYTHONPATH=src python3 -m unittest tests.test_command_builder tests.test_subtitle_speakers tests.test_job_recovery tests.test_manifest_contracts tests.test_dubbing_runtime tests.test_dubbing_cli_api -v`
    - `Ran 72 tests ... OK`
    - `59` 条因本机缺 `soundfile/torch` 被显式 `skipped`
- 当前仍未收口：
  - `tools/dub_long_video.py` 文件内仍保留旧 V3/V4 helper 实现，虽然已不再写入新 manifest，但还没物理删除
  - `src/subtitle_maker/domains/dubbing/__init__.py` 仍导出 `diarization/speaker_segments` 相关符号
  - 旧 `tests/test_dub_long_video.py` 仍保留大量 V3/V4 历史断言，尚未重写

## 15. 2026-05-04 Subtitle-Maker 收敛重构：翻译 + 配音（单人 / 多人）
- [x] 收缩前端主菜单与 Auto Dubbing 面板：
  - 左侧顶部只保留 `Upload Videos & SRT` / `Subtitles & Translation` / `Auto Dubbing`
  - 删除 `Auto Dubbing V2/V3` 导航与面板心智
  - `TTS` 下拉只保留 `index-tts` 与 `VoxCPM + OmniVoice`
- [x] 收缩 Auto Dubbing 请求契约：
  - 统一为 `mode=single|multi`
  - 统一为 `tts_backend=index-tts|voxcpm-omnivoice`
  - 增加 `single_ref_audio` / `speaker_ref_map`
  - 删除 `pipeline_version`、`v3/v4`、`asd/diarization/qwen3` 相关字段
- [x] 重构字幕 speaker 解析与配音主链路：
  - 解析 `Speaker N:` 前缀并保留 `speaker_id`
  - 单人模式统一使用单参考音
  - 多人模式严格按 `speaker_id -> ref_audio` 路由
  - 多人模式缺映射时直接拒绝启动
- [ ] 删除废弃链路与项目内引用：
  - 移除 ASD tracked / FluidAudio / pyannote / Qwen3 ASR / ForcedAligner / 独立 OmniVoice 主底座
  - 删除相关代码、测试、manifest 字段与默认模型路径
  - 删除项目内 `models/Qwen3-ASR-0.6B` 与 `models/Qwen3-ForcedAligner-0.6B`
- [ ] 补回归测试并验证：
  - `Speaker N:` 解析
  - single/multi 模式校验
  - 两条 TTS 在 single/multi 下的路由
  - API / command / manifest 不再出现旧 `v3/v4/diarization/qwen3` 参数
- [x] 更新 `tasks/lessons.md`，沉淀这次收敛重构的教训

### Review（2026-05-04 Subtitle-Maker 收敛重构：第一轮收口）
- 已完成：
  - `src/subtitle_maker/dubbing_cli_api.py`
    - `start/start-from-project` 改为新主契约：`dubbing_mode`、`single_ref_audio_file`、`speaker_ref_files + speaker_ref_speaker_ids_json`
    - 后端会落盘单人/多人参考音文件，并在多人模式下做 `speaker_id -> ref_audio_path` 显式映射校验
    - `_queue_auto_dubbing_task()` 不再构建旧 `pipeline_version/v3/v4/diarization/fluidaudio` 主链路参数
    - `resume/load-batch` 已切到 `dubbing_mode/single_ref_audio/speaker_ref_map` 主字段
  - `src/subtitle_maker/manifests/schema.py` / `src/subtitle_maker/manifests/readwrite.py`
    - manifest 主读取/写入保留 `pipeline_version=auto-dubbing` 兼容壳
    - 新主字段为 `dubbing_mode/single_ref_audio/speaker_ref_map`
    - 不再把 `v3_asd/diarization/fluidaudio` 写入新 manifest
  - `src/subtitle_maker/static/app.js`
    - 全局 TTS 只保留 `index-tts` / `voxcpm-omnivoice`
    - Auto Dubbing 面板集合收缩为单面板
    - `switchTab()` 改为支持按 panelId 切换，避免菜单数量变更后错位
  - `src/subtitle_maker/static/js/dubbingPanel.js`
    - 停止初始化历史 V2/V3 面板
    - 新增 `single/multi` 模式切换
    - 单人模式支持上传一个参考音
    - 多人模式从字幕中提取 `Speaker N:` 列表，为每个 speaker 渲染参考音上传槽
    - 表单提交改为新字段，不再提交 `pipeline_version`
  - `src/subtitle_maker/templates/index.html`
    - 左侧顶部主菜单已固定为 3 个
    - 全局 TTS 下拉已收缩
    - 历史 `panel-auto-dub-v2/panel-auto-dub-v3` 整块 DOM 已删除
    - `panel-auto-dub` 已加入 single/multi 参考音配置区
  - 新增：
    - `tests/test_subtitle_speakers.py`
- 已验证：
  - `PYTHONPATH=src python3 -m py_compile src/subtitle_maker/dubbing_cli_api.py src/subtitle_maker/jobs/command_builder.py src/subtitle_maker/jobs/recovery.py src/subtitle_maker/manifests/schema.py src/subtitle_maker/manifests/readwrite.py tools/dub_pipeline.py tools/dub_long_video.py`
  - `node --check src/subtitle_maker/static/app.js`
  - `node --check src/subtitle_maker/static/js/dubbingPanel.js`
  - `PYTHONPATH=src python3 -m unittest tests.test_command_builder tests.test_subtitle_speakers -v`
    - `Ran 11 tests ... OK`
- 当前未收口：
  - 旧 `test_dubbing_cli_api.py` / `test_manifest_contracts.py` / `test_dub_long_video.py` 中仍有大量 V2/V3/V4 历史断言，尚未整体迁移到新产品合同
  - `review/redub` 内部恢复逻辑仍保留 `pipeline_version` 兼容壳，但不再影响新主启动流程
  - 项目内历史 diarization / qwen3 / fluidaudio 残留文件和测试还未做第二轮物理清理

## 14. 2026-05-03 V4 Speaker Diarization 实施收尾
- [x] 新增 `src/subtitle_maker/domains/dubbing/diarization.py`，落地 V4 diarization domain：
  - `run_diarization_cli`
  - `load_diarization_turns`
  - `align_subtitles_to_speakers`
  - `merge_adjacent_subtitles_by_speaker`
  - `extract_speaker_reference_audio`
  - `prepare_v4_diarization_artifacts`
- [x] 打通 V4 参数链路：
  - `src/subtitle_maker/dubbing_cli_api.py`
  - `src/subtitle_maker/jobs/command_builder.py`
  - `src/subtitle_maker/jobs/models.py`
  - `src/subtitle_maker/jobs/recovery.py`
  - `src/subtitle_maker/manifests/schema.py`
  - `src/subtitle_maker/manifests/readwrite.py`
- [x] 打通 long-video V4 编排：
  - `tools/dub_long_video.py` 新增 `v4_mode`
  - 批次级写出 `speaker_turns.json`
  - 批次级写出 `subtitle_segments_by_speaker.json`
  - 批次级写出 `speaker_inventory.json`
  - segment 级写出 `subtitles/_input_segment.speakers.json`
- [x] 打通 segment 级 speaker metadata 回灌：
  - `tools/dub_pipeline.py` 支持 `--speaker-metadata-path`
  - 字幕 sidecar 合并回 subtitle items
  - 参考音复用主键升级为优先 `speaker_id`，兼容回退 `speaker_track_id/track_id`
- [x] 补齐 V4 最小测试覆盖：
  - `tests/test_command_builder.py`
  - `tests/test_dub_pipeline_references.py`
  - `tests/test_dubbing_cli_api.py`
  - `tests/test_dub_long_video.py`
- [x] 收尾 `tests.test_dub_long_video` 最后一个失败用例：
  - `test_main_v3_with_time_ranges_only_runs_windowed_asr_and_asd`
  - 补齐 `build_full_timeline_bgm/build_full_timeline_mix` 测试桩，避免误落到真实媒体读取
- [x] 核对 `FluidAudio process --output` 真实输出契约，并修正 V4 适配层：
  - 官方输出是 `ProcessingResult` 包装对象
  - 实际 speaker 段字段是 `segments[].speakerId/startTimeSeconds/endTimeSeconds`
  - 不是先前假设的 `turns[].speaker_id/start_sec/end_sec`
- [x] 增强 `fluidaudio_root` 路径解析：
  - 允许直接指向 `FluidAudio` 源码仓库根目录
  - 自动解析 `.build/release/fluidaudiocli`
  - 自动解析 `.build/arm64-apple-macosx/release/fluidaudiocli`
- [x] 重新稳定落一本地 `FluidAudio` 源码目录，并保留可复用 CLI 路径：
  - 源码目录：`/Users/tim/Documents/vibe-coding/MVP/FluidAudio-src`
  - 可执行文件：`/Users/tim/Documents/vibe-coding/MVP/FluidAudio-src/.build/arm64-apple-macosx/release/fluidaudiocli`
- [x] 真实接通本机 `FluidAudio CLI` 做一次 smoke，确认第三方输出契约与当前适配层一致
- [ ] 用真实离线视频跑一条 V4 端到端，确认 `speaker_id -> reference -> TTS` 主链路可用
- [ ] 视 smoke 结果决定是否补 `speaker_inventory` 质量阈值与 `needs_review` 标记

### Review
- 已验证：
  - `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_dub_long_video.DubLongVideoTests.test_main_v3_with_time_ranges_only_runs_windowed_asr_and_asd -v`
  - `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_command_builder tests.test_dub_pipeline_references tests.test_dubbing_cli_api tests.test_dub_long_video -v`
  - `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_diarization -v`
  - `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_command_builder tests.test_dubbing_cli_api tests.test_dub_long_video -v`
  - `swift build -c release --product fluidaudiocli` in `/Users/tim/Documents/vibe-coding/MVP/FluidAudio-src`
  - `ffmpeg -y -i test-0003-multi-person-17s.mp4 -vn -ac 1 -ar 16000 tmp/fluidaudio_smoke/test-0003-17s.wav`
  - `/Users/tim/Documents/vibe-coding/MVP/FluidAudio-src/.build/arm64-apple-macosx/release/fluidaudiocli process /Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tmp/fluidaudio_smoke/test-0003-17s.wav --mode offline --threshold 0.6 --output /Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tmp/fluidaudio_smoke/result.json`
- 验证结果：
  - V4 参数透传通过
  - V4 批次 manifest 能写出 `speaker_turns/subtitle_segments_by_speaker/speaker_inventory`
  - segment 目录能写出 `_input_segment.speakers.json`
  - `FluidAudio process --output` 新契约字段兼容通过
  - `fluidaudio_root` 指向源码仓库时的 CLI 自动解析通过
  - `FluidAudio` 本机 offline diarization 实跑成功，17.02s 音频处理耗时约 `1.26s`，`RTFx≈13.54x`
  - `tmp/fluidaudio_smoke/result.json` 能被 `load_diarization_turns()` 正确解析为 `4` 个 speaker turns
  - 最小回归共 `94` 条测试通过
- 当前剩余风险：
  - 还没做真实视频端到端验证
  - 当前 smoke 样例 `test-0003-multi-person-17s.wav` 只分出了 `1` 个 speaker，说明“能跑通”和“分人质量满足业务目标”还不是一回事
  - 还需要用真正的 V4 批处理主链路跑一条端到端，验证 `speaker_id -> reference -> TTS`

## Spec-11（2026-05-03 V4 Speaker Diarization 主链路）1/3 现状分析
- 目标：把当前 `Auto Dubbing V3` 从“可见说话人 focus 驱动的配音”收敛成真正服务最终目标的链路：
  - 先得到整条视频里稳定的 `speaker_id`
  - 再让每个 `speaker_id` 绑定自己的参考音 / 音色
  - 最终完成“不同的人用到自己的音色，然后把翻译内容配音”
- 用户真实目标不是“当前谁在说话的框”，而是“整条视频里谁是谁，并且同一个人始终用同一个音色”。这意味着主真值必须是 `speaker diarization`，不是 `active speaker focus`。

- 现状 1：当前 V3 的主分人输入仍然是 `asd-pipeline /run-tracked` 的 focus 结果，不是全局 speaker diarization。
  - 依据：
    - [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 顶部直接引入：
      - `call_tracked_asd_api`
      - `load_focus_predictions_from_response`
      - `assign_speakers_to_subtitles`
      - `merge_assigned_subtitles_to_speaker_segments`
    - [src/subtitle_maker/domains/dubbing/speaker_segments.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/speaker_segments.py) 中：
      - `call_tracked_asd_api()` 直接请求 `asd-pipeline /run-tracked`
      - `load_focus_predictions_from_response()` 读取 `focus_predictions.json`
      - `assign_speakers_to_subtitles()` 是把 focus 轨迹覆盖回字幕时间窗
  - 结论：
    - 当前 V3 的“speaker segment”本质是“focus 轨迹驱动的可见说话人切段”，不是音频主导的全局 diarization。

- 现状 2：当前 `speaker_track_id` 是窗口级/轨迹级 ID，不是可跨整条视频复用的稳定人物身份。
  - 依据：
    - [src/subtitle_maker/domains/dubbing/speaker_segments.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/speaker_segments.py) 里的 `SpeakerSegment.speaker_track_id` 只保存 `track_xxxx`
    - `assign_speakers_to_subtitles()` 的判定逻辑只看某个字幕窗内哪条 `track_id` 覆盖最多
    - `merge_assigned_subtitles_to_speaker_segments()` 也只是把相邻同 `speaker_track_id` 的字幕合并
  - 结论：
    - 当前 ID 语义是“这段窗口里的一条视觉 track”，不是“这个人是全片的 Speaker 1 / Speaker 2”
    - 对“同一个人整条片子始终绑定同一音色”这个目标不够用

- 现状 3：当前 V3 仍然把视觉可见性当作主前提，画面无人脸时只能继承上一条 track，不能给出可靠 speaker identity。
  - 依据：
    - [src/subtitle_maker/domains/dubbing/speaker_segments.py::assign_speakers_to_subtitles()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/speaker_segments.py)：
      - 只基于 `focus_predictions` 的时间覆盖做 speaker 归属
      - 没有音频 embedding / speaker clustering
      - 无脸时仅通过 `last_confirmed_speaker_track_id` 延续上一位
  - 结论：
    - 这条逻辑只能缓解“断脸切碎”，不能建立真正的多人 speaker identity
    - 一旦离脸、转场、旁白、背身、插画、无脸镜头变长，就会失去可靠 speaker 真值

- 现状 4：当前 TTS 参考音链路是“按 segment/group 找参考音”，不是“按全局 speaker_id 固定音色”。
  - 依据：
    - 当前实现和测试都围绕 `ref_audio_path` / `ref_text` 组织，而不是 `speaker_id -> voice_profile`
    - [tests/test_dubbing_runtime.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_runtime.py) 多处断言：
      - `ref_audio_path`
      - `ref_text`
      - `voxcpm-omnivoice` 先生成 anchor，再把 anchor 交给 OmniVoice
    - [tools/repair_bad_segments.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/repair_bad_segments.py) 仍以 `refs/single_speaker_ref.wav` 这类 segment/job 级参考音为核心
  - 结论：
    - 当前系统本质上还是“这句/这组字幕找一段参考音来配”
    - 不是“先把全片 speaker 归一，再让每个 speaker 用自己的固定 voice profile”

- 现状 5：当前工程里已有 diarization 相关历史尝试，但没有成为当前主链路，而且历史 refactor 可信度不足。
  - 依据：
    - `/Users/tim/.codex/memories/MEMORY.md` 已记录：
      - `speaker-routing refactor looks present but is untrustworthy`
      - `do not claim success until speaker-route wiring is verified`
  - 结论：
    - 不能在现有 V3 上继续堆 patch 假装得到 diarization
    - 应当把 diarization 明确抬升成新的主编排阶段，重新定义输入输出契约

- 现状 6：从产品目标倒推，当前 V3/ASD 路线最多只能当“视觉辅助”，不能当“多人配音主路由器”。
  - 依据：
    - `run-tracked` 产物聚焦的是 `focus_predictions` / `focus_overlay`
    - 它解决的是“当前该看谁”
    - 它没有给出“整片稳定 speaker inventory + per-speaker reference bank + subtitle-to-speaker global alignment”
  - 结论：
    - 当前 V3/ASD 继续修下去，最多得到“框更稳”
    - 但不会自然演化成“不同的人始终使用自己的音色”的最终方案

- 现状 7：对当前用户目标，最合理的新主链路应是“ASR -> diarization -> subtitle/speaker alignment -> per-speaker refs -> TTS”，而不是“ASD -> focus -> subtitle mapping -> TTS”。
  - 依据：
    - 当前 [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 已具备：
      - 抽音频
      - 生成/复用 `source.srt`
      - 分段编排
      - 调用不同 TTS backend
    - 缺的不是“再画一个框”，而是“在进入 TTS 前先确定谁是谁”
- 结论：
    - V4 应把 diarization 提到主编排层
    - ASD 只保留为辅助能力：映射屏幕人物、挑更干净参考音、修正同框开口归属

## Spec-11（2026-05-03 V4 Speaker Diarization 主链路）2/3 功能点与改动边界
- 设计目标：把当前 `Auto Dubbing V3` 的主分人逻辑从 `ASD focus` 切换为 `speaker diarization`，让后续 TTS 的核心语义变成：
  - 先确定整条视频有哪些 `speaker_id`
  - 再让每个 `speaker_id` 绑定固定参考音/固定音色
  - 最后所有字幕都按 `speaker_id` 路由到对应音色

- 推荐主方案：接入 `FluidAudio` 的 `offline diarization pipeline`，而不是继续以 `run-tracked` 为主。
  - 依据：
    - `FluidAudio` README 明确提供 `Offline Speaker Diarization Pipeline`，并说明“Use this for most use cases”；
    - CLI 入口就是 `swift run fluidaudiocli process path/to/audio.wav`；
    - benchmark 文档明确写 `Both offline and online versions use the community-1 model`，但 offline 是主推默认路线；
    - `pyannote community-1` 提供 `exclusive_speaker_diarization`，官方明确说它就是为了更容易和 transcription timestamps 对齐。
  - 结论：
    - 对 `Apple + 离线视频 + 后续配音` 这个场景，`FluidAudio offline community-1` 是最贴合的新主链路底座。

- 功能点 1：在 long-video 编排层新增独立的 `speaker diarization` 阶段，位置放在“拿到 source subtitles 之后、进入 TTS 之前”。
  - 目标顺序：
    1. 抽取窗口音频 / 全片音频
    2. 生成或复用 `source.srt`
    3. 跑 `speaker diarization`
    4. 把字幕对齐到 `speaker_id`
    5. 为每个 `speaker_id` 提取参考音
    6. 按 `speaker_id` 进入 TTS
  - 接入点：
    - [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py)
  - 边界：
    - 不重写 segment 级 TTS/mix 主流程
    - 先改 batch/long-video orchestration

- 功能点 2：新增“speaker diarization 结果产物层”，它要成为后续所有 speaker 路由的唯一真值。
  - 最小新增产物建议：
    - `speaker_turns.json`
    - `subtitle_segments_by_speaker.json`
    - `speaker_refs/speaker_001.wav`
    - `speaker_refs/speaker_002.wav`
    - `speaker_inventory.json`
  - 语义：
    - `speaker_turns.json`：原始 diarization 时间段
    - `subtitle_segments_by_speaker.json`：字幕和 `speaker_id` 的对齐结果
    - `speaker_refs/*`：每个 speaker 的参考音集合或最终首选参考音
    - `speaker_inventory.json`：`speaker_id -> ref_audio -> 统计信息`
  - 接入点：
    - [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py)
    - [src/subtitle_maker/manifests/](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/manifests/)

- 功能点 3：新增一个独立的 `speaker diarization domain`，不要把它继续塞在当前 `speaker_segments.py` 的 ASD 语义里。
  - 推荐新增模块职责：
    - `run_diarization(...)`
    - `load_diarization_turns(...)`
    - `align_subtitles_to_speakers(...)`
    - `merge_adjacent_subtitles_by_speaker(...)`
    - `extract_speaker_reference_audio(...)`
  - 推荐目录：
    - `src/subtitle_maker/domains/dubbing/diarization.py`
    - 或拆成：
      - `domains/dubbing/diarization_runtime.py`
      - `domains/dubbing/diarization_alignment.py`
      - `domains/dubbing/diarization_refs.py`
  - 边界：
    - 现有 [speaker_segments.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/speaker_segments.py) 保留给 V3/ASD 辅助路径
    - 不强行把 diarization 逻辑混进 focus 语义文件

- 功能点 4：把现有 TTS 请求的主键从“当前 group 的 ref”升级成“全局 speaker_id 的 voice profile”。
  - 目标行为：
    - 对每个字幕段，先确定 `speaker_id`
    - 再由 `speaker_id` 查到：
      - `preferred_ref_audio`
      - `preferred_ref_text`（若底座需要）
      - `tts_backend runtime hints`
    - `voxcpm-omnivoice` / `omnivoice` / `index-tts` 只消费统一的 speaker profile
  - 接入点：
    - [src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py)
    - [src/subtitle_maker/backends/](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/backends/)
  - 边界：
    - 首轮不追求“同 speaker 跨多 segment 的 embedding 自适应更新”
    - 先做到“同一批次内 speaker_id 稳定绑定固定 ref”

- 功能点 5：为 `FluidAudio` 新增本地运行入口，但先以“离线单文件命令调用”方式接入，不先做复杂服务化。
  - 推荐首轮接法：
    - Python 在 `dub_long_video.py` 里调用一个本地 CLI/脚本
    - 输入：音频路径
    - 输出：JSON 结果文件
  - 推荐原因：
    - `FluidAudio` 本体是 Swift SDK / macOS CLI
    - 先走 CLI 子进程是最小侵入接法
    - 比先搭一个 Swift HTTP 服务风险更低
  - 二阶段可选：
    - 稳定后再做 `FluidAudio diarization API service`

- 功能点 6：字幕和 diarization 的对齐策略优先走“exclusive speaker diarization -> subtitle window overlap”，而不是重新发明对齐算法。
  - 依据：
    - `community-1` 官方明确提供 `exclusive_speaker_diarization`
    - 目标就是简化 diarization 与 transcription timestamps 的 reconciliation
  - 目标行为：
    - 每条字幕先按时间窗和 exclusive speaker turn 做 overlap
    - 必要时允许相邻同 speaker 合并为更大段
    - 无法可靠归属时显式标记 `needs_review`
  - 边界：
    - 首轮不做复杂的词级强制对齐 + speaker jointly optimize
    - 先用“字幕窗 -> speaker turn”映射跑通主链路

- 功能点 7：参考音提取从“当前句附近找一段音频”升级成“按 speaker_id 维护 reference bank，再选首选 ref”。
  - 目标行为：
    - 每个 `speaker_id` 收集若干候选 reference clips
    - 根据时长、纯净度、是否单人、是否非静音等规则选出 `preferred_ref_audio`
    - 所有属于该 `speaker_id` 的后续 TTS 默认复用同一音色
  - 接入点：
    - [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py)
    - [src/subtitle_maker/domains/media/](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/media/)
  - 边界：
    - 首轮先做“每 speaker 一个首选 ref”
    - 不做更复杂的 multi-ref blending

- 功能点 8：前端/UI 第一轮不需要新增复杂交互，只需要在现有 Auto Dubbing 面板暴露“speaker diarization backend / 开关 / 结果查看”最小入口。
  - 目标行为：
    - 允许选择：
      - `speaker_routing_mode = asd_v3 | diarization_v4`
      - `diarization_backend = fluidaudio-community1`
    - 允许查看产物：
      - `speaker_turns.json`
      - `speaker_inventory.json`
  - 接入点：
    - [src/subtitle_maker/static/js/dubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/dubbingPanel.js)
    - [src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py)
  - 边界：
    - 第一轮不做新页面
    - 不做 speaker 可视化编辑器

- 明确不做：
  - 不继续把 `focus_overlay.mp4` 修到主链路可用再作为最终分人方案
  - 不把 `FluidInference/diar-streaming-sortformer-coreml` 作为主后端
  - 不先做 Swift HTTP 服务
  - 不先做“跨整部视频的人脸身份库 + 音频 speaker 自动绑定人物头像”的重系统
  - 不在首轮引入云端 pyannote API；优先本机离线

- 推荐改动范围（首轮）：
  - orchestration：
    - [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py)
  - domain：
    - `src/subtitle_maker/domains/dubbing/diarization*.py`（新增）
    - [src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py)
  - API/参数：
    - [src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py)
    - [src/subtitle_maker/jobs/command_builder.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/jobs/command_builder.py)
  - manifest：
    - `src/subtitle_maker/manifests/*`
- UI：
    - [src/subtitle_maker/static/js/dubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/dubbingPanel.js)

## Spec-11（2026-05-03 V4 Speaker Diarization 主链路）3/3 风险、关键决策与推荐方案
- 核心决策 1：主分人方案选 `FluidAudio offline community-1`，不选当前 `ASD focus`，也不选 `streaming sortformer`。
  - 原因：
    - 当前用户目标是“离线视频里不同的人绑定自己的音色配音”，核心是稳定 `speaker_id`
    - `ASD focus` 解决的是“当前该看谁”，不是“全片谁是谁”
    - `streaming sortformer` 的优势在实时低延迟，不在离线视频配音质量
    - `community-1` 的 `exclusive speaker diarization` 更适合和 `source.srt` 时间戳对齐
  - 推荐结论：
    - V4 主链路以 `FluidAudio offline community-1` 为准
    - `ASD` 仅保留为辅助，不再承担主路由职责

- 核心决策 2：首轮接入方式选本地 CLI 子进程，不先做 Swift HTTP 服务。
  - 原因：
    - 当前主工程是 Python
    - `FluidAudio` 本体是 Swift SDK / Apple 侧运行时
    - CLI 子进程是最小侵入接法，最容易先跑通一条完整链路
  - 推荐结论：
    - 第一阶段只要求：
      - Python 调本地 `fluidaudiocli`
      - 输入音频文件
      - 输出 diarization JSON
    - 等产物契约稳定后，再考虑二阶段服务化

- 核心决策 3：首轮先做“稳定 speaker_id + 固定音色绑定”，不追求“人物画面身份一致性”。
  - 原因：
    - 用户当前目标是配音音色一致，不是人物可视化追踪
    - 如果一开始把“人脸身份库 / 画面人物映射 / 可视化编辑”一并纳入，会显著放大实现面
  - 推荐结论：
    - V4 第一阶段只保证：
      - 同一 speaker 在整条批次里稳定使用同一音色
      - 字幕段被正确分配到 speaker
    - 画面人物映射放到后续增强阶段

- 风险 1：`FluidAudio` 实际输出契约未必和 `subtitle-maker` 当前假设一致。
  - 风险点：
    - CLI 输出字段名、时间单位、speaker 命名规则、是否直接给 exclusive turns，都可能和当前 Python 侧预期不同
  - 对策：
    - 第一刀先做一个“结果适配层”，不要在 orchestration 里直接硬编码第三方 JSON
    - 约束内部统一产物为：
      - `speaker_turns.json`
      - `speaker_inventory.json`
      - `subtitle_segments_by_speaker.json`

- 风险 2：字幕和 diarization 的时间对齐会有边界误差，导致一条字幕跨两个 speaker。
  - 风险点：
    - ASR 句子边界和 diarization turn 边界天然不会完全一致
    - 特别是抢话、插话、句中切 speaker 时，简单 overlap 可能误归属
  - 对策：
    - 首轮明确采用“字幕窗对 exclusive speaker turn 的 overlap”作为主规则
    - 对低覆盖度或冲突窗显式打 `needs_review`
    - 不在第一轮做复杂词级重对齐

- 风险 3：参考音提取容易再次把“英语原声污染 / 多人混音 / 无脸段”带回 TTS。
  - 风险点：
    - 即便 speaker diarization 正确，如果 reference bank 建得脏，最终音色仍会漂
  - 对策：
    - 第一轮 reference 规则要单独定义：
      - 最小时长
      - 最大时长
      - 单 speaker 纯净度优先
      - 非静音 / 非过强背景音
    - 先输出候选列表和首选 ref，便于后验检查

- 风险 4：当前 repo 里已有 V3/ASD、omnivoice、voxcpm-omnivoice、review/redub 等多条路径，容易把新逻辑掺进旧逻辑导致回归。
  - 风险点：
    - 如果直接在现有 `speaker_segments.py` / V3 参数里继续叠 patch，很容易出现模式语义漂移
  - 对策：
    - 新能力明确命名成 `V4 diarization route`
    - 参数、产物、manifest 字段和 V3 分开
    - V3 继续可用，但不和 V4 共享主语义

- 风险 5：本机 Apple 离线跑 `FluidAudio` 虽然方向对，但工程化第一步可能卡在环境、编译或模型准备。
  - 风险点：
    - Swift toolchain、CoreML 运行环境、模型下载位置、CLI 参数形态可能需要一次性打通
  - 对策：
    - 在真正改 `subtitle-maker` 之前，先单独跑通：
      - 输入一段 wav
      - 输出 diarization JSON
    - 只有这个基础验证通过，再进入主工程接线

- 推荐实施顺序：
  1. 先在本机单独验证 `FluidAudio offline community-1` 能对单个 wav 输出可用 diarization 结果
  2. 定义 `subtitle-maker` 内部统一 diarization JSON 契约
  3. 在 `dub_long_video.py` 中接入新阶段：`source.srt -> diarization -> subtitle/speaker alignment`
  4. 增加 `speaker_refs` 生成与 `speaker_inventory` 产物
  5. 改 TTS 路由，让 `speaker_id` 成为固定音色主键
  6. 最后再补最小 UI 参数透传和结果查看

- 首轮验证标准：
  - 给定一条离线视频，能产出：
    - `source.srt`
    - `speaker_turns.json`
    - `subtitle_segments_by_speaker.json`
    - `speaker_inventory.json`
    - 至少一个 `speaker_refs/speaker_xxx.wav`
  - 同一 `speaker_id` 的多条字幕在最终 manifest 中使用同一参考音/同一 voice profile
  - 不要求首轮就解决“画面里谁是谁”的可视化问题

- 推荐方案结论：
  - 停止把当前 V3/ASD 路线继续当最终方向修补
  - 以 `FluidAudio offline community-1` 为新主分人方案
  - 以 `CLI 子进程 + 内部契约适配层 + per-speaker reference bank` 为第一阶段实现路线
  - 等 V4 主链路稳定后，再决定是否保留 `ASD` 作为人物映射辅助模块

## 12. 2026-05-03 start.sh 日志可观测性优化
- [ ] 定位 `./start.sh` 启动后 `/dubbing/auto/status/{task_id}` 刷屏日志来源
- [ ] 过滤高频轮询 access log，避免控制台被重复 `200 OK` 淹没
- [ ] 增加 Auto Dubbing 任务状态/阶段变化摘要日志，让运行中阶段可见
- [ ] 验证：启动 Web 后轮询 `/dubbing/auto/status/{task_id}` 不再刷屏
- [ ] 验证：真实任务运行时控制台能看到阶段推进日志

## 13. 2026-05-03 V3 ASD focus_predictions 契约兼容修复
- [x] 定位 `focus_predictions.json must be a list` 根因
- [x] 兼容 `asd-pipeline /run-tracked` 新版 `focus_predictions.json`（顶层 dict + predictions）
- [x] 把新版逐帧 focus 结构归一化为 speaker assignment 可消费的时间窗
- [ ] 验证：`01.mp4 120-180s` 这类 V3 任务不再因 `focus_predictions.json` 结构报错
- [x] 验证：`speaker_segments` 对新版 focus 数据能产出非空说话人映射

## 11. 2026-05-03 Qwen3-TTS 清理与 V3 时间窗口修正
- [x] 删除 `qwen-omnivoice / qwen-tts / qwen3-tts` 相关生产代码入口，保留 `index-tts / omnivoice / voxcpm-omnivoice`
- [x] 删除 `src/subtitle_maker/qwen_tts/` 目录
- [x] 修正 `tools/dub_long_video.py` 的 V3 编排顺序：先计算 `effective_ranges`，再按窗口做 source subtitles / tracked ASD
- [x] 新增 V3 回归测试：`time_ranges_json=[{\"start_sec\":120,\"end_sec\":180}]` 时，只对窗口做 ASR/ASD
- [x] 同步修正 `tests/test_dubbing_runtime.py`、`tests/test_command_builder.py`、`tests/test_manifest_contracts.py`、`tests/test_dubbing_cli_api.py`、`tests/test_dub_pipeline_references.py`
- [x] 验证：`PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_dubbing_runtime -v` 通过
- [x] 验证：`PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_command_builder tests.test_manifest_contracts tests.test_dub_pipeline_references -v` 通过
- [ ] 验证：`tests.test_dub_long_video` 仅剩 `test_main_v3_with_time_ranges_only_runs_windowed_asr_and_asd` 的测试 stub 收尾


## Spec-10（2026-05-03 V3 默认 ASD 正确修法）1/3 现状分析
- 目标：修正当前 `Auto Dubbing V3` 的编排语义，让 V3 不再依赖“必须先有外部输入字幕文件”才触发 ASD，而是按正确顺序执行：
  - 先拿媒体生成或复用 source subtitles
  - 再调用 tracked ASD
  - 再把字幕映射到 speaker segments
  - 最后进入现有 TTS 链路
- 直接问题证据：
  - 最新批次 [batch_manifest.json](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/outputs/dub_jobs/web_20260503_114219/longdub_20260503_194227/batch_manifest.json) 显示：
    - `pipeline_version = v3`
    - `tts_backend = voxcpm-omnivoice`
    - `v3_asd_api_url = http://127.0.0.1:8001`
    - `input_srt_kind = source`
    - 但同时 `input_srt = None`
  - 同批次 [web_cli_stdout.log](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/outputs/dub_jobs/web_20260503_114219/web_cli_stdout.log) 没有出现 `Step V3/0: call tracked ASD and build speaker segments`；
  - 最终 segment 日志 [segment_0001.jsonl](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/outputs/dub_jobs/web_20260503_114219/longdub_20260503_194227/segment_jobs/segment_0001/logs/segment_0001.jsonl) 走的是：
    - `asr_started`
    - `translation_started`
    - `sentence_reference_mode_enabled`
    - `group_tts_started`
    - 没有任何 `speaker_segments` / ASD 映射痕迹。
- 现状 1：`dub_long_video.py` 当前把 V3/ASD 绑定在 `v3_mode and input_subtitles`，而不是绑定在 `v3_mode`。
  - 依据：
    - [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 中：
      - `input_subtitles` 只在 `args.input_srt` 存在时由 `parse_srt(...)` 初始化；
      - 只有 `if v3_mode and input_subtitles:` 才会执行 `call_tracked_asd_api(...)`、`assign_speakers_to_subtitles(...)`、`merge_assigned_subtitles_to_speaker_segments(...)`。
  - 结论：
    - 只要 `--input-srt` 没传进来，即使 `pipeline_version = v3`，ASD 也完全不会跑。
- 现状 2：Current Project 模式下，前端和 API 已支持把当前项目字幕落成 `input_srt`，但这条链路并不可靠，不能作为 V3/ASD 的唯一前提。
  - 依据：
    - 前端 [dubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/dubbingPanel.js) `buildCurrentProjectRequest()` 会在 `requestedMode == source/translated` 时传 `subtitles_json`；
    - 后端 [dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py) 的 `_write_subtitles_json_to_srt()` 会把 `subtitles_json` 落为 `project_source.srt / project_translated.srt`；
    - 但这次实际上传目录 [uploads/dubbing/20260503_114219](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/uploads/dubbing/20260503_114219) 只有视频，没有任何 `project_source.srt`，说明这条链路在真实运行中可能为空、失效或不稳定。
  - 结论：
    - V3 不能依赖“前端必须先把字幕喂进来”这个脆弱前置条件。
- 现状 3：当前 V3 speaker segmentation 的后处理是建立在“已有字幕时间窗”之上的，而不是直接从 ASD 输出生成完整文本。
  - 依据：
    - [src/subtitle_maker/domains/dubbing/speaker_segments.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/speaker_segments.py)：
      - `call_tracked_asd_api()` 只拿 focus 结果；
      - `assign_speakers_to_subtitles()` 需要 `subtitles` 输入；
      - `merge_assigned_subtitles_to_speaker_segments()` 也是按字幕窗合并 speaker；
      - `build_subtitles_from_speaker_segments()` 最终仍输出标准字幕结构给后续配音链路。
  - 结论：
    - 正确顺序必须是“先有 source subtitles，再跑 ASD 映射”，而不是相反。
- 现状 4：当前 long-video 主流程已经能在没有 `input_srt` 的情况下正常生成 source subtitles，因此 V3 正确修法不需要重写 ASR。
  - 依据：
    - 同批次日志已证明 segment 内层 [dub_pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_pipeline.py) 能稳定跑 `ASR -> translation -> TTS`；
    - `segment_0001/subtitles/source.srt` 已实际生成。
  - 结论：
    - 需要调整的是 V3 的编排时机，不是新增另一套字幕生成能力。
- 现状 5：当前“很零散”并不是 ASD 分人造成，而是因为没走 ASD 后退化成了 sentence grouping。
  - 依据：
    - [segment_0001.jsonl](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/outputs/dub_jobs/web_20260503_114219/longdub_20260503_194227/segment_jobs/segment_0001/logs/segment_0001.jsonl) 显示：
      - `after_count = 16`
      - `sentence_blocks = 14`
      - `short_merge_effective = false`
    - 结果是 60 秒被切成 16 条字幕、14 个 group，导致 TTS 路径很碎。
  - 结论：
    - 若 V3 正确命中 ASD speaker segments，这个“很碎”的主症状本身就应先明显改善。

## Spec-10（2026-05-03 V3 默认 ASD 正确修法）2/3 功能点与改动边界
- 设计目标：让 `pipeline_version = v3` 的 long-video 编排不再依赖外部 `input_srt` 才能调用 ASD，而是始终在“拿到 source subtitles 之后”执行 tracked ASD 和 speaker segmentation。
- 推荐执行顺序：
  1. 先确定 source subtitles 来源
  2. 若已有 `input_srt_kind=source`，可直接复用
  3. 若没有 source subtitles，则先从媒体生成 source subtitles
  4. 再统一调用 tracked ASD
  5. 再把 source subtitles 映射为 speaker segments
  6. 再按 speaker segments 驱动分段 TTS
- 功能点 1：V3 触发条件从 `v3_mode and input_subtitles` 改为“V3 且能拿到 source subtitles”。
  - 目标行为：
    - `pipeline_version=v3` 时，不再把 ASD 绑定在“必须传入 `--input-srt`”这个前置条件上；
    - 只要能在 long-video 编排层拿到 source subtitles，就应该跑 ASD；
    - Current Project / Standalone Upload / 无字幕上传 三种入口都遵循同一套 V3 语义。
  - 依据：
    - [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 当前问题点就在 `if v3_mode and input_subtitles:`
    - 这条条件把“V3 speaker segmentation 能力”错误降格成了“附属可选优化”。
- 功能点 2：为 V3 引入“source subtitles 获取阶段”，但不重写 segment 内层 ASR/TTS。
  - 目标行为：
    - 若 batch 入口已提供 `input_srt_kind=source`，直接作为 V3 映射输入；
    - 若 batch 入口没有 source subtitles，则在 long-video 层先产一份 source subtitles，再交给 ASD；
    - segment 级 `dub_pipeline.py` 仍沿用现有 TTS 和混音逻辑，不另造第二套 segment pipeline。
  - 依据：
    - [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 已经负责分段编排、字幕切片和产物 merge；
    - `speaker_segments.py` 的输入天然就是字幕列表，最小正确修法应发生在 long-video 编排层。
- 功能点 3：V3 speaker segments 应在 batch 层落盘并成为后续 segment 切片的主输入。
  - 目标行为：
    - 保留并强化当前 `speaker_segments.json` 落盘；
    - `input_subtitles` 在进入 segment 切片前应被重写为 `build_subtitles_from_speaker_segments(...)` 的结果；
    - segment 级 `_input_segment.srt` 应来自 speaker segments 重写后的字幕，而不是原始 sentence blocks。
  - 依据：
    - 当前 [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 已有这套落盘和重写骨架，只是触发时机不对。
- 功能点 4：manifest / task 记录要能区分“请求的 V3”和“实际命中的 V3 speaker segmentation”。
  - 目标行为：
    - batch manifest 除了保留 `pipeline_version=v3`，还应明确记录：
      - 是否实际跑了 tracked ASD
      - source subtitles 来源（external source srt / generated source srt）
      - `speaker_segments.json` 路径
      - 生成后的 `speaker_segments_total`
    - 避免再次出现“请求层是 V3，但运行结果看起来像 V1”的黑盒状态。
  - 依据：
    - 当前批次 manifest 只有 `pipeline_version=v3`，但 `input_srt=None`，无法直观看出“为何没进 ASD”。
- 功能点 5：Current Project 模式的 `subtitles_json` 仍保留，但不再作为 V3 的单点前提。
  - 目标行为：
    - 现有 `_write_subtitles_json_to_srt()` 链路继续保留；
    - 若它成功，V3 可直接用已有 source subtitles，减少额外 ASR 成本；
    - 若它失败或为空，V3 仍应继续执行，通过先生成 source subtitles 再跑 ASD，而不是直接退化成 V1 句子分组。
  - 依据：
    - 当前这次真实批次已经证明 project subtitle 传入链路并不稳定，不能成为唯一入口。
- 计划改动文件边界：
  - 核心必改：
    - [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py)
  - 配套可能改：
    - [src/subtitle_maker/manifests/readwrite.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/manifests/readwrite.py)
    - [src/subtitle_maker/manifests/schema.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/manifests/schema.py)
    - [tests/test_dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dub_long_video.py)
    - 如需 API 状态补充，再改 [src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py)
- 本轮明确不做：
  - 不改 `speaker_segments.py` 的核心分配算法
  - 不改 `asd-pipeline` 服务端协议
  - 不改 `voxcpm-omnivoice` / `omnivoice` / `index-tts` 的 TTS 合成算法
  - 不顺手优化 `seg_0005_missing.wav` 的 TTS 质量门控逻辑

## Spec-10（2026-05-03 V3 默认 ASD 正确修法）3/3 风险、关键决策与推荐方案
- 风险 1：如果直接把 “先产 source subtitles” 硬塞进 segment 内层，而不是 batch 编排层，会把现有 `dub_pipeline.py` 的职责搞乱。
  - 依据：
    - [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 当前负责 batch 级分段、切片、字幕输入裁剪、manifest 汇总；
    - [tools/dub_pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_pipeline.py) 当前负责单段 `ASR -> 翻译 -> TTS -> review` 执行；
    - [src/subtitle_maker/domains/dubbing/speaker_segments.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/speaker_segments.py) 依赖的输入就是“已有字幕 + ASD focus”，不是单独生成文本。
  - 风险结论：
    - 若把 V3 修法下沉到 segment 层，会导致“谁负责准备 source subtitles、谁负责调用 ASD、谁负责重写 segment 输入”边界混乱，后续恢复跑批也更难对齐。
- 风险 2：如果只把 `if v3_mode and input_subtitles` 改成 `if v3_mode`，但不补“source subtitles 获取阶段”，会把 V3 从“完全不跑 ASD”变成“拿空字幕去跑 ASD 映射”。
  - 依据：
    - [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 第 `991-1006` 行附近当前直接把 `input_subtitles` 送进 `assign_speakers_to_subtitles(...)`；
    - 该函数的输入前提在 [speaker_segments.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/speaker_segments.py) 中就是已有字幕列表。
  - 风险结论：
    - 正确修法不是简单放宽条件，而是补一段显式的“source subtitles resolved”步骤。
- 风险 3：如果实现后仍不把“V3 是否实际命中 ASD”写入 manifest，会继续出现“请求是 V3，运行结果像 V1，但用户看不出来为什么”的黑盒问题。
  - 依据：
    - 当前真实批次 [batch_manifest.json](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/outputs/dub_jobs/web_20260503_114219/longdub_20260503_194227/batch_manifest.json) 虽有 `pipeline_version=v3`、`v3_asd_api_url`，但没有任何 “asd actually executed” 或 “source subtitles source” 字段；
    - 现有 schema [schema.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/manifests/schema.py) 与读写 [readwrite.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/manifests/readwrite.py) 当前只持久化配置，不持久化 V3 运行命中状态。
  - 风险结论：
    - 这次 bug 的排查成本高，核心原因之一就是 manifest 只能看到“请求意图”，看不到“实际运行路径”。
- 关键决策 1：V3 的触发语义定义为“只要 batch 层拿到 source subtitles，就必须跑 tracked ASD”，而不是“只有外部 `input_srt` 存在才跑”。
  - 推荐原因：
    - 这和 [speaker_segments.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/speaker_segments.py) 的真实数据依赖一致；
    - 也和用户对 `V3` 的产品预期一致：选了 V3 就应该优先走 speaker segmentation，而不是静默退化成句子分组。
- 关键决策 2：首选最小正确修法放在 `tools/dub_long_video.py`，不重构 `speaker_segments.py`，也不重写 `dub_pipeline.py`。
  - 推荐原因：
    - 根因就在 [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 的 V3 触发条件和编排顺序；
    - 现有测试 [tests/test_dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dub_long_video.py) 也已经覆盖了 “V3 重写输入字幕后再进入 segment run” 的骨架，扩展这一层成本最低。
- 关键决策 3：Current Project 的 `subtitles_json -> project_source.srt` 继续保留，但只视为 source subtitles 的一个可选来源，不再作为 V3 唯一依赖。
  - 推荐原因：
    - [dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py) 的 `_write_subtitles_json_to_srt()` 仍然有价值，成功时可以省一次 batch 级 source subtitle 生成；
    - 但真实上传目录 [uploads/dubbing/20260503_114219](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/uploads/dubbing/20260503_114219) 已证明这条链路并不稳定。
- 验证方案：
  1. 单测补齐 “V3 + 有 `input_srt`” 与 “V3 + 无 `input_srt`” 两条路径。
  2. 验证 `input_srt=None` 时，`tools/dub_long_video.py` 仍会先解析或生成 source subtitles，再调用 `call_tracked_asd_api(...)`。
  3. 验证生成的 batch manifest 会显式记录：
     - `pipeline_version = v3`
     - `v3_asd_applied = true/false`
     - `v3_source_subtitles_origin`
     - `speaker_segments_total`
     - `paths.speaker_segments`
  4. 验证 segment 输入 `_input_segment.srt` 已来自重写后的 speaker segments，而不是原始 sentence blocks。
  5. 用真实批次命令做 smoke：
     - 目标场景就是这次失败的 `Current Project + pipeline_version=v3 + voxcpm-omnivoice + 无外部 input_srt`
     - 期望看到 `web_cli_stdout.log` 出现 `Step V3/0: call tracked ASD and build speaker segments`
     - 期望 `batch_manifest.json` 不再出现“请求是 V3 但 `input_srt=None` 且无 ASD 痕迹”的状态。
- 推荐实施顺序：
  1. 先改 [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py)，抽出 “解析或生成 source subtitles” 的 batch 级步骤。
  2. 再把 V3 分支改成基于 “resolved source subtitles” 触发 tracked ASD 和 speaker segments 重写。
  3. 再补 [tests/test_dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dub_long_video.py) 的无 `input_srt` 回归。
  4. 最后按需补 manifest schema/readwrite，让运行命中状态可观测。
- 推荐方案：
  - 采用“batch 层先拿 source subtitles，再统一跑 ASD，再重写 segment 输入”的最小闭环修法；
  - 不接受“简单放宽 if 条件”这种半修；
  - 不接受“把问题丢给前端一定要传 `subtitles_json`”这种脆弱修法；
  - 只有这样，`V3` 才能真正变成一个稳定语义，而不是偶然命中的分支。

## Review（2026-05-03 V3 默认 ASD 正确修法）
- 根因确认：
  - [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 原先把 `V3` 绑定在 `if v3_mode and input_subtitles:`；
  - 这导致 `pipeline_version=v3` 但 `input_srt=None` 时，tracked ASD 根本不会执行，整批静默退化成 sentence grouping。
- 已实现：
  - [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 新增 batch 级 `resolve_v3_input_subtitles()` 与 `transcribe_source_subtitles_for_v3()`；
  - `V3` 现在会先统一拿到 batch 级字幕输入：
    - 有 source `input_srt` 时复用并规整；
    - 无 `input_srt` 时直接在 long-video 层先生成一份 `v3_source_input.srt`；
  - 之后再统一调用 tracked ASD，并把重写后的 speaker subtitles 送进 segment run；
  - batch manifest 新增：
    - `v3_asd_applied`
    - `v3_source_subtitles_origin`
  - 现有 `input_srt` 字段也会在 V3 无外部字幕时指向 batch 内实际生成的 `v3_source_input.srt`，避免 manifest 继续显示 `None` 黑盒状态。
- 验证证据：
  - 定向回归：
    - `PYTHONPATH=src python3 -m unittest tests.test_dub_long_video.DubLongVideoTests.test_main_v3_rewrites_input_subtitles_by_speaker_segments_before_segment_run tests.test_dub_long_video.DubLongVideoTests.test_main_v3_without_input_srt_generates_source_subtitles_before_asd -v`
    - 结果：`2 tests OK`
  - 全量 long-video 单测：
    - `PYTHONPATH=src python3 -m unittest tests.test_dub_long_video -v`
    - 结果：`Ran 11 tests ... OK`
- 当前边界：
  - 这一步只修正 `V3` 编排语义和可观测性；
  - 没有顺手改 `speaker_segments.py` 归属算法；
  - 没有处理 `seg_0005_missing.wav` 这类纯 TTS 质量门控问题。

## 0. Review（2026-05-03 修复 voxcpm-omnivoice grouped 包装层漏参）
- 问题：
  - 最新失败批次 `web_20260503_104033` 在进入 TTS grouped 路径后立刻报错：
  - `synthesize_segments_grouped() got an unexpected keyword argument 'voxcpm_api_url'`
- 根因：
  - `tools/dub_pipeline.py` 已经把 `--voxcpm-api-url` 解析并传给 `synthesize_segments_grouped(...)`
  - 但 `tools/dub_pipeline.py` 里的兼容包装函数 `synthesize_segments_grouped()` 自己的函数签名漏了 `voxcpm_api_url`
  - 结果是命令行参数到达编排层后，在包装层直接抛 `TypeError`，还没真正进入新实现
- 已完成：
  - [x] 给 [tools/dub_pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_pipeline.py) 的 grouped 兼容包装层补上 `voxcpm_api_url`
  - [x] 补回归测试 [tests/test_dub_pipeline_references.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dub_pipeline_references.py)
  - [x] 用原失败命令对 `segment_0001` 做真实复现验证
- 验证证据：
  - 单测：
    - `test_grouped_wrapper_forwards_voxcpm_api_url ... ok`
    - `test_synthesize_text_once_voxcpm_omnivoice_generates_anchor_then_calls_omnivoice ... ok`
  - 真实复现：
    - 同一批次日志已从原先的 `unexpected keyword argument` 越过，进入：
      - `group_0001` 合成成功
      - `group_0002` 合成成功
      - 当前继续跑到 `group_0003`
  - 关键日志文件：
    - [segment_0001.jsonl](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/outputs/dub_jobs/web_20260503_104033/longdub_20260503_184038/segment_jobs/segment_0001/logs/segment_0001.jsonl)

## 1. Review（2026-05-03 VoxCPM API 落地与真实组合 smoke）
- 已完成：
  - [x] 在 `/Users/tim/Documents/vibe-coding/MVP/VoxCPM` 新增精简服务 `tools/voxcpm_api_server.py`
  - [x] 新增 `start_api.sh` / `stop_api.sh`
  - [x] 新增最小回归 `tests/test_voxcpm_api_server.py`
  - [x] 验证 `subtitle-maker` 侧 `voxcpm-omnivoice` 关键单测
  - [x] 验证真实 `VoxCPM -> OmniVoice` 两跳组合 smoke
- 验证证据：
  - `VoxCPM` 最小接口单测：`/Users/tim/Documents/vibe-coding/MVP/VoxCPM/tests/test_voxcpm_api_server.py`
    - 结果：`3 passed`
  - `VoxCPM` 真实接口输出：
    - anchor 文件：[anchor.wav](/Users/tim/Documents/vibe-coding/MVP/VoxCPM/outputs/api_smoke/anchor.wav)
    - 请求返回：`ok=true duration_sec=1.92 sample_rate=44100`
  - `subtitle-maker` 关键链路测试：
    - `PYTHONPATH=src .venv/bin/python -m unittest ...`
    - 结果：`22 tests OK`
  - 真实组合 smoke 输出：
    - 最终文件：[final.wav](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/outputs/voxcpm_omnivoice_smoke/final.wav)
    - `OmniVoice` 服务日志显示：
      - `target_duration_sec=3.0`
      - `actual_duration_sec=3.15`
      - `duration_ratio=1.05`
- 当前结论：
  - `VoxCPM` 作为中文 anchor 生成服务已经落地并真实可调；
  - `subtitle-maker` 中 `voxcpm-omnivoice` 接线与关键恢复/manifest/command 链路已通过回归；
  - 在真实服务条件下，`VoxCPM -> OmniVoice` 两跳组合已成功生成最终 wav。

## Spec-9（2026-05-03 VoxCPM + OmniVoice 切换）1/3 现状分析
- 目标：放弃当前 `Qwen3-TTS + OmniVoice` 作为优先试验路线，改为 `VoxCPM + OmniVoice`，原因是 `Qwen3-TTS` 在真实运行中作为中文 anchor 生成器明显过慢。
- 直接现状证据：
  - 最新运行批次 `outputs/dub_jobs/web_20260503_092700` 已经顺利通过 `ASR -> 翻译 -> reference 提取`，但长时间停在 `tts:group_tts_started - synthesizing group_0001`；
  - `segment_0001` 日志停在 [segment_0001.jsonl](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/outputs/dub_jobs/web_20260503_092700/longdub_20260503_172706/segment_jobs/segment_0001/logs/segment_0001.jsonl)，没有继续写入 `group_0001` 完成或失败事件；
  - `sample 52459` 显示热点卡在本地 `Qwen3-TTS` 的 `torch scaled_dot_product_attention` / MPS 路径，说明当前瓶颈在 Qwen anchor 生成，不在翻译，也不在 OmniVoice API。
- 现状 1：`subtitle-maker` 当前已经正式接入 `qwen-omnivoice` 作为组合 backend，但这条链路的第一跳就是本地加载并运行 `Qwen3-TTS`。
  - 依据：
    - [src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py) 的 `_normalize_auto_dubbing_request()` 已接受 `tts_backend in {"index-tts", "qwen", "omnivoice", "qwen-omnivoice"}`；
    - [tools/dub_pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_pipeline.py) 在 `args.tts_backend in {"qwen", "qwen-omnivoice"}` 时会走 `load_tts_model(...)` 加载本地 Qwen 模型；
    - [src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py) 的 `synthesize_text_once()` 在 `normalized == "qwen-omnivoice"` 分支里，先 `_synthesize_qwen_anchor(...)`，后才调用 `OmniVoiceBackend.synthesize(...)`。
- 现状 2：当前系统里还没有任何 `voxcpm` backend 接线，`VoxCPM` 仍然只是外部仓库，不是 `subtitle-maker` 的可选底座。
  - 依据：
    - [src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py) 当前白名单里没有 `voxcpm` 或 `voxcpm-omnivoice`；
    - [src/subtitle_maker/jobs/command_builder.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/jobs/command_builder.py) 的 `_needs_qwen_runtime()` / `_needs_omnivoice_runtime()` 只识别 `qwen`、`qwen-omnivoice`、`omnivoice`；
    - 当前仓库 `src/`、`tools/`、`tests/` 下没有已接入的 `voxcpm` runtime 分支。
- 现状 3：现有主链路已经具备“组合 backend”所需的大部分骨架，因此切到 `VoxCPM + OmniVoice` 不需要重做整条自动配音流程。
  - 依据：
    - [src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py) 的 `synthesize_text_once()` 已经是统一单次合成入口；
    - 同文件逐句与 grouped 路径都通过 `synthesize_text_once()` 发起真正 TTS；
    - [src/subtitle_maker/backends/omni_voice.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/backends/omni_voice.py) 已经稳定承担“最终控时合成”职责。
- 现状 4：`VoxCPM` 更适合作为“中文 anchor 生成器”，而不是直接替代 `OmniVoice` 的控时职责。
  - 依据：
    - 你当前要求是“换掉过慢的 Qwen anchor 生成”，不是放弃 `OmniVoice` 的句级时长控制；
    - 当前项目里真正把 `target_duration_sec` 透传进最终生成阶段的是 `OmniVoiceBackend.synthesize()`，不是 `Qwen3-TTS` 路径。
- 现状 5：当前最自然的切换方式，不是把 `VoxCPM` 做成 `fallback_tts_backend`，而是新增 `tts_backend=voxcpm-omnivoice`。
  - 依据：
    - `fallback_tts_backend` 在当前系统中的语义仍是“主 backend 失败后的备胎”，见 [src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py) 与 [src/subtitle_maker/manifests/schema.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/manifests/schema.py)；
    - `qwen-omnivoice` 已证明组合语义适合作为新的主 backend 标识，而不是滥用 fallback 字段。

## TODO（2026-05-03 VoxCPM + OmniVoice 切换）
- [x] 完成 Spec 2/3：功能点与改动边界
- [x] 完成 Spec 3/3：风险、关键决策与推荐方案
- [x] HARD-GATE：等待你确认后再开始编码
- [x] 在 `VoxCPM` 仓库新增精简 TTS API 服务，只保留 `/health` 与 `/tts`
- [x] 在 `subtitle-maker` 接入 `tts_backend=voxcpm-omnivoice`
- [x] 为 `voxcpm-omnivoice` 补 reference text / anchor 记录链路
- [x] 补最小测试与语法验证

## Spec-9（2026-05-03 VoxCPM + OmniVoice 切换）2/3 功能点与改动边界
- 设计目标：新增 `voxcpm-omnivoice` 组合 backend，用 `VoxCPM` 替换当前过慢的 `Qwen3-TTS` anchor 生成步骤，再继续复用 `OmniVoice` 做最终句级控时合成。
- 推荐能力边界：
  - 输入仍沿用现有自动配音请求参数、批次结构、review 流程和长视频编排；
  - 输出仍是当前 segment/job manifest、review 面板、最终成片与中间产物目录；
  - 新增的是一个新的主 backend 模式，不新增独立产品入口，不改 V1/V2/V3 工作流语义。
- 功能点 1：新增 `tts_backend=voxcpm-omnivoice`，打通 Web / CLI / runtime / manifest 白名单。
  - 目标行为：
    - 前端底座下拉可选择 `VoxCPM + OmniVoice`；
    - API 归一化、命令拼装、manifest 存取、review redub 恢复都能识别这个 backend；
    - 不滥用 `fallback_tts_backend` 表达组合语义。
  - 依据：
    - [src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py) 当前 `tts_backend` 白名单已扩到 `qwen-omnivoice`，说明主 backend 扩展是现成模式；
    - [src/subtitle_maker/jobs/command_builder.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/jobs/command_builder.py) 已围绕 `tts_backend` / `fallback_tts_backend` 构建 CLI；
    - [src/subtitle_maker/manifests/schema.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/manifests/schema.py) 与 [src/subtitle_maker/manifests/readwrite.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/manifests/readwrite.py) 已持久化这些字段。
- 功能点 2：新增 `VoxCPM` anchor 生成步骤，但只在 `voxcpm-omnivoice` 模式生效。
  - 目标行为：
    - 对每个待合成单元，先用当前 `ref_audio_path` 和对应 `ref_text` 调 `VoxCPM` 生成一段中文 anchor；
    - 再把生成出的中文 anchor 作为 `OmniVoice` 的 `ref_audio_path` 做最终合成；
    - `target_duration_sec` 只约束最终 `OmniVoice` 阶段，不要求 `VoxCPM` 先精确控时。
  - 依据：
    - [src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py) 的 `synthesize_text_once()` 已经是组合 backend 最适合收敛的位置；
    - [VoxCPM README](/Users/tim/Documents/vibe-coding/MVP/VoxCPM/README.md) 与 [VoxCPM app.py](/Users/tim/Documents/vibe-coding/MVP/VoxCPM/app.py) 都表明 `VoxCPM.generate(text=..., prompt_wav_path=..., prompt_text=...)` 是标准克隆入口。
- 功能点 3：`VoxCPM` 必须消费“参考音频 + 参考文本”成对输入，不能像当前 Qwen 一样只吃音频 embedding。
  - 目标行为：
    - 组合 backend 在挑选 `ref_audio_path` 的同时，需要为 `VoxCPM` 提供同一段参考音对应的 `prompt_text`；
    - 若缺少可靠 `prompt_text`，要么回退到该字幕原文，要么直接记为 `manual_review`，不能静默传空。
  - 依据：
    - [VoxCPM app.py](/Users/tim/Documents/vibe-coding/MVP/VoxCPM/app.py) 的 `/api/tts` 明确要求 `prompt_audio` 存在时必须同时提供 `prompt_text`；
    - [src/voxcpm/core.py](/Users/tim/Documents/vibe-coding/MVP/VoxCPM/src/voxcpm/core.py) 明确要求 `prompt_wav_path` 和 `prompt_text` 成对出现，否则报错。
- 功能点 4：首版优先复用 `VoxCPM` 现有 API 风格，而不是直接把整套模型硬塞进 `subtitle-maker` 进程内。
  - 目标行为：
    - 在 `/Users/tim/Documents/vibe-coding/MVP/VoxCPM` 侧补一个轻量 TTS API，协议尽量向 `subtitle-maker` 友好；
    - `subtitle-maker` 通过 HTTP 调用该服务生成 anchor；
    - 不把 `voxcpm` 的模型加载、依赖和 ASR/denoise 逻辑直接并入当前 web/API 进程。
  - 依据：
    - 当前 `Qwen3-TTS` 是直接进 `subtitle-maker` 进程，已经暴露出速度和资源占用问题；
    - [VoxCPM app.py](/Users/tim/Documents/vibe-coding/MVP/VoxCPM/app.py) 本身已有 Flask 服务骨架与 `/api/tts` 风格入口，说明走 API 化复用最自然；
    - `OmniVoice` 在本项目中也是通过 API/CLI 运行时隔离接入，现有模式可复用。
- 功能点 5：保留当前 reference selector 和 `speaker_track_id` 逻辑，不在本轮重写 speaker segmentation。
  - 目标行为：
    - `voxcpm-omnivoice` 直接消费当前主链路已经选出的 `ref_audio_path`；
    - V3 若已有更干净的 `speaker_track_id` 参考音，新的组合 backend 自动继承；
    - 不在本轮顺手改 ASD、track continuity、字幕切句或前端预览。
  - 依据：
    - [tools/dub_pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_pipeline.py) 当前 `build_backend_reference_selector()` 已是统一 reference 入口；
    - 当前 V3 已经把 `speaker_track_id` 贯穿到后续 reference 复用链路。
- 功能点 6：运行记录必须显式标记 `voice_ref_path -> voxcpm_anchor_path -> final_backend=omnivoice`。
  - 目标行为：
    - 每个成功/失败 record 至少写出：
      - 原始 `voice_ref_path`
      - `anchor_ref_path`
      - `anchor_backend=voxcpm`
      - `final_backend=omnivoice`
      - 如失败，区分是 `voxcpm anchor` 失败还是 `omnivoice` 最终合成失败
  - 依据：
    - 当前 `qwen-omnivoice` 已在 [src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py) 记录 `anchor_ref_path` / `final_backend`；
    - 这套结构可以直接复制到 `voxcpm-omnivoice`，避免排障又回到黑盒状态。
- 功能点 7：前端只新增一个 backend 选项，不新增复杂参数面板。
  - 目标行为：
    - 底座模型下拉增加 `VoxCPM + OmniVoice`；
    - 继续复用当前 OmniVoice 运行参数；
    - VoxCPM 的模型路径、API URL、timesteps 等首版先走后端默认值或环境变量，不先暴露给前端。
  - 依据：
    - 用户当前诉求是“换底座”，不是做一套 VoxCPM 调参工作台；
    - 当前前端已经因为多模型配置复杂度偏高，首版应控制变量。
- 本轮明确不做：
  - 不继续优化 `Qwen3-TTS + OmniVoice` 的速度；
  - 不让 `VoxCPM` 直接替代 `OmniVoice` 的最终控时；
- 不改 V3 的 speaker segmentation、ASD tracked API 或前端产品结构；
- 不顺手做多底座自动基准测试平台。

## Spec-9（2026-05-03 VoxCPM + OmniVoice 切换）3/3 风险、关键决策与推荐方案
- 风险 1：`VoxCPM` 和当前 Qwen 路径最大的不同，是它不能只吃参考音频，必须同时有匹配的 `prompt_text`。
  - 依据：
    - [VoxCPM app.py](/Users/tim/Documents/vibe-coding/MVP/VoxCPM/app.py) 的 `/api/tts` 明确要求 `prompt_audio` 存在时必须同时提供 `prompt_text`；
    - [src/voxcpm/core.py](/Users/tim/Documents/vibe-coding/MVP/VoxCPM/src/voxcpm/core.py) 直接在 runtime 中校验：`prompt_wav_path` 和 `prompt_text` 必须成对出现。
  - 影响：
    - 当前 `subtitle-maker` 的 reference selector 主要产出的是 `Path`，不是“音频+转写”对；
    - 如果把错的字幕文本配给参考音，VoxCPM 可能会学到错误内容或质量明显下降。
  - 结论：
    - 首版必须同时建立 `reference audio -> reference text` 选择策略，不能只复用现有音频 selector。
- 风险 2：如果直接把 `VoxCPM` 模型嵌进 `subtitle-maker` 主进程，可能只是把当前 Qwen 的资源问题换一个模型重演。
  - 依据：
    - 当前 `Qwen3-TTS` 直接嵌入 `subtitle-maker` 后，真实运行已经暴露出卡在本地推理的问题；
    - [src/voxcpm/core.py](/Users/tim/Documents/vibe-coding/MVP/VoxCPM/src/voxcpm/core.py) 初始化时默认会 warm-up，而且推理侧也包含 prompt cache、可选 denoise 等额外逻辑。
  - 影响：
    - 主进程内存、启动时间、模型切换和异常隔离都会变差；
    - 出问题时更难区分是 `subtitle-maker` orchestration 问题还是 `VoxCPM` runtime 问题。
  - 结论：
    - 推荐走独立 API 服务，不走 in-process 嵌入。
- 风险 3：如果直接复用 `VoxCPM/app.py` 当前 WebUI 接口，不做瘦身，依赖面会过大。
  - 依据：
    - [VoxCPM/app.py](/Users/tim/Documents/vibe-coding/MVP/VoxCPM/app.py) 当前不仅做 TTS，还带有 ASR、audiobook、上传、WebUI 等逻辑；
    - `subtitle-maker` 当前需要的只是一个稳定的 “text + prompt_audio + prompt_text -> wav” 能力。
  - 影响：
    - 接口语义过宽，后续排障会混入无关路径；
    - 自动启动、健康检查、release 语义也不如 `OmniVoice` 当前这套轻服务模式清晰。
  - 结论：
    - 应在 `VoxCPM` 仓库侧单独做一个精简 API 服务，而不是直接拿现有 WebUI 服务硬接。
- 风险 4：若 `voxcpm-omnivoice` 的 runtime 配置直接暴露给前端，UI 复杂度会继续膨胀。
  - 影响：
    - 用户现在只是要求“换底座”，不是要管理另一套模型的细粒度推理参数；
    - 一旦前端暴露过多 `model_path / api_url / timesteps / cfg`，很快又会回到配置混乱状态。
  - 结论：
    - 首版只暴露 `tts_backend=voxcpm-omnivoice` 这个选择，VoxCPM 参数走后端默认值或环境变量。
- 风险 5：如果新的 anchor 链路不进 manifest / record，后续一样没法解释“英文原声为什么还混进来”。
  - 影响：
    - 你看到的还是“成片坏了”，但无法区分是原始 ref 脏、reference text 配错、VoxCPM anchor 脏，还是 OmniVoice 最终阶段出问题；
    - review redub 也无法做定向重跑。
  - 结论：
    - `voice_ref_path / reference_text / anchor_ref_path / anchor_backend / final_backend` 必须都落盘。

- 关键决策 1：组合模式命名
  - 选项 A：`tts_backend=voxcpm-omnivoice`
  - 选项 B：保留 `tts_backend=omnivoice`，再加布尔开关 `use_voxcpm_anchor=true`
  - 推荐：选 A
  - 原因：
    - 和现有 `qwen-omnivoice` 一致，语义明确；
    - manifest、恢复和 review 重跑更容易看懂；
    - 避免把 `omnivoice` 这个已有 backend 悄悄改成另一条链路。

- 关键决策 2：VoxCPM 接入方式
  - 选项 A：直接在 `subtitle-maker` 进程内 import `voxcpm`
  - 选项 B：在 `VoxCPM` 仓库内补一个轻量 API 服务，由 `subtitle-maker` 调用
  - 推荐：选 B
  - 原因：
    - 隔离模型依赖、启动时间和异常；
    - 复用当前 `OmniVoice` 的服务化经验；
    - 避免把主进程进一步做重。

- 关键决策 3：reference text 来源
  - 选项 A：优先使用参考音频对应的原文字幕文本
  - 选项 B：直接用当前待配音的中文译文作为 `prompt_text`
  - 推荐：首版采用 A
  - 原因：
    - `prompt_text` 语义本来就是“参考音频对应文本”；
    - 用错文本会破坏 voice cloning 对齐；
    - 当前待配音译文更适合作为 `target text`，不是 `prompt_text`。

- 关键决策 4：验证顺序
  - 选项 A：直接接全链路，跑长视频 V3
  - 选项 B：先做单段 `60s` 定向样本验证，再接回 V3
  - 推荐：选 B
  - 原因：
    - 当前最大不确定性在 `VoxCPM anchor` 的速度和质量，不在 orchestration；
    - 先缩小到单段验证，更容易比较：
      - 生成速度
      - 英文泄漏是否下降
      - 时长控制是否仍由 OmniVoice 保住

- 推荐方案（实施顺序）：
  - 第 1 步：在 `/Users/tim/Documents/vibe-coding/MVP/VoxCPM` 增加一个精简 TTS API 服务，只保留：
    - `/health`
    - `/tts`
    - 输入：`text`, `prompt_audio`, `prompt_text`
    - 输出：wav 文件路径或音频文件
  - 第 2 步：在 `subtitle-maker` 增加 `tts_backend=voxcpm-omnivoice` 白名单，打通前端、API normalize、command builder、manifest、review redub 恢复。
  - 第 3 步：在 `synthesize_text_once()` 新增 `voxcpm-omnivoice` 分支：
    - 先调 `VoxCPM API` 生成 anchor；
    - 再调 `OmniVoiceBackend` 做最终控时合成。
  - 第 4 步：补 reference text 选择与 anchor 落盘：
    - 为 reference selector 增加对应文本来源；
    - 在 record/attempt/manifest 写入 `reference_text`、`anchor_ref_path`、`anchor_backend=voxcpm`。
  - 第 5 步：先拿单段样本做 smoke test，只比较三件事：
    - 比 `qwen-omnivoice` 快多少；
    - 英文原声泄漏是否减少；
    - 最终配音是否仍卡进字幕时间窗。

## Review（2026-05-03 VoxCPM + OmniVoice 切换 Spec）
- 已完成：
  - [x] Spec 1/3：现状分析
  - [x] Spec 2/3：功能点与改动边界
  - [x] Spec 3/3：风险、关键决策与推荐方案
- 当前状态：
  - 方案阶段已完成，尚未开始编码；
  - 按仓库 HARD-GATE 规则，下一步必须等你确认后才能实施。

## Review（2026-05-03 Qwen3-TTS + OmniVoice 真实运行复盘）
- 结论：
  - `qwen-omnivoice` 语义链路已接通，但真实运行速度不可接受；
  - 当前主要瓶颈不是 `OmniVoice API`，而是 `Qwen3-TTS` 生成中文 anchor 的首跳推理。
- 证据：
  - 批次目录： [outputs/dub_jobs/web_20260503_092700](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/outputs/dub_jobs/web_20260503_092700)
  - 运行日志： [web_cli_stdout.log](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/outputs/dub_jobs/web_20260503_092700/web_cli_stdout.log)
  - Segment 日志： [segment_0001.jsonl](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/outputs/dub_jobs/web_20260503_092700/longdub_20260503_172706/segment_jobs/segment_0001/logs/segment_0001.jsonl)

## Spec-8（2026-05-03 Qwen3-TTS + OmniVoice 组合底座）1/3 现状分析
- 目标：在 `subtitle-maker` 中优先试验 `Qwen3-TTS + OmniVoice` 组合底座，用 `Qwen3-TTS` 解决零样本中文音色锚点问题，再由 `OmniVoice` 负责句级时长控制。
- 目标语义：
  - 先从英文参考音频生成一段更干净的中文 anchor；
  - 再把该中文 anchor 作为 `OmniVoice` 的参考音频；
  - 最终仍输出落在字幕时间窗内的句级中文配音。
- 现状 1：当前项目已经内置本地 `Qwen3-TTS` 推理链路，但它现在是直接作为主 TTS backend 出声，不是“先生成 anchor，再交给别的 backend”。
  - 依据：
    - `[tools/dub_pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_pipeline.py)` 中 `load_tts_model()` 会加载 `Qwen3-TTS`；
    - 同文件当前 `args.tts_backend == "qwen"` 时，会先 `create_voice_clone_prompt(...)`，后续直接走 `generate_voice_clone(...)`。
- 现状 2：当前项目里 `Qwen3-TTS` 的 clone 模式是 `x_vector_only_mode=True`，即只抽说话人嵌入，不依赖 `ref_text`。
  - 依据：
    - `[tools/dub_pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_pipeline.py)` 构造 prompt 时显式传入 `ref_text=None, x_vector_only_mode=True`；
    - `[src/subtitle_maker/qwen_tts/inference/qwen3_tts_model.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/qwen_tts/inference/qwen3_tts_model.py)` 的 `create_voice_clone_prompt()` 明确说明 `x_vector_only_mode=True` 时只使用 speaker embedding。
- 现状 3：当前项目的 `Qwen3-TTS` 路径没有直接消费 `target_duration_sec`，因此它不适合单独承担严格卡时长职责。
  - 依据：
    - `[src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py)` 的 `_synthesize_text_to_audio()` 虽然统一构建了含 `target_duration_sec` 的 `TtsSynthesisRequest`；
    - 但 `normalized == "qwen"` 分支里实际只调用 `tts_qwen.generate_voice_clone(...)`，没有把 `target_duration_sec` 传进 Qwen 路径。
- 现状 4：当前项目里真正负责“按目标时长生成”的是 `OmniVoiceBackend`，它已经稳定接入 API/CLI 双路径。
  - 依据：
    - `[src/subtitle_maker/backends/base.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/backends/base.py)` 的 `TtsSynthesisRequest` 已定义 `target_duration_sec`；
    - `[src/subtitle_maker/backends/omni_voice.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/backends/omni_voice.py)` 在 `synthesize()` 中会把 `request.target_duration_sec` 显式透传为 `--duration`。
- 现状 5：当前后端参数与前端表单都只支持“单主 backend + 可选备胎 backend”，没有“组合 backend”这个一等公民概念。
  - 依据：
    - `[src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py)` 只接受 `tts_backend in {"index-tts", "qwen", "omnivoice"}`，`fallback_tts_backend in {"none", "omnivoice"}`；
    - `[src/subtitle_maker/jobs/command_builder.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/jobs/command_builder.py)` 也是围绕这两个字段拼装 CLI；
    - `[src/subtitle_maker/static/js/dubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/dubbingPanel.js)` 前端状态也是按单主底座组织。
- 现状 6：从现有架构看，`Qwen3-TTS + OmniVoice` 最自然的落点不是新增第四个平行 backend，而是新增一个“组合 backend / 组合模式”。
  - 推论依据：
    - `Qwen3-TTS` 负责“生成中文音色锚点”；
    - `OmniVoice` 负责“按句级目标时长生成最终中文配音”；
    - 两者职责不重叠，属于前后串联，而不是二选一替换关系。

## TODO（2026-05-03 Qwen3-TTS + OmniVoice 组合底座）
- [ ] 完成 Spec 2/3：功能点与改动边界
- [ ] 完成 Spec 3/3：风险、关键决策与推荐方案
- [ ] HARD-GATE：等待你确认后再开始编码

## Spec-8（2026-05-03 Qwen3-TTS + OmniVoice 组合底座）2/3 功能点与改动边界
- 设计目标：把 `Qwen3-TTS` 从“直接最终出声的主 backend”改造成“中文 anchor 生成器”，再把生成出的 anchor 交给 `OmniVoice` 做最终控时合成。
- 推荐能力边界：
  - 输入仍沿用现有自动配音参数，不新增新的上传入口、任务类型或独立页面；
  - 输出仍沿用现有批次目录结构、segment manifest、review 面板和最终成片产物；
  - 新增的是一种 backend 运行模式，而不是新增一套平行工作流。
- 功能点 1：新增一个组合 backend 标识，供 Web / CLI / runtime 统一识别。
  - 建议形态：新增 `tts_backend=qwen-omnivoice`，而不是把它塞进 `fallback_tts_backend`。
  - 依据：
    - `[src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py)` 的 `_normalize_auto_dubbing_request()` 当前只接受 `index-tts/qwen/omnivoice` 三个主 backend；
    - `[src/subtitle_maker/jobs/command_builder.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/jobs/command_builder.py)` 的 `build_auto_dubbing_command()` 直接透传 `--tts-backend`，说明 backend 标识是贯穿前后端的一级参数；
    - `fallback_tts_backend` 当前语义是“主 backend 失败时切换备胎”，不适合表达“先 Qwen 后 OmniVoice”的串联流程。
- 功能点 2：在句级/组级合成前增加“anchor 参考音生成”步骤，但只在 `qwen-omnivoice` 模式生效。
  - 目标行为：
    - 对每个待配音单元先根据当前 `ref_audio_path` 生成一段中文 anchor；
    - 再以这段 anchor 作为 `OmniVoice` 的 `ref_audio_path` 去做最终合成；
    - `target_duration_sec` 只作用于最终 `OmniVoice` 合成，不要求 Qwen anchor 先控时。
  - 依据：
    - `[src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py)` 的 `synthesize_text_once()` 已经是单次合成的统一入口，当前在函数内部按 backend 分支；
    - 同文件 `run_sentence_synthesis_loop()` / `run_grouped_synthesis_loop()` 都通过 `synthesize_text_once()` 发起真正 TTS，因此组合逻辑应尽量收敛在该入口附近，而不是散到各个上层循环里。
- 功能点 3：新增 anchor 缓存，避免同一参考音反复调用 Qwen 生成相同中文 anchor。
  - 目标行为：
    - 缓存 key 以当前参考音路径为主，必要时附带 `speaker_track_id` 或字幕索引；
    - 同一 track / 同一参考音命中缓存时直接复用 anchor，不重复生成；
    - anchor 文件作为中间产物落到 batch/segment 目录，便于排障。
  - 依据：
    - `[src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py)` 的 `run_sentence_synthesis_loop()` 当前已经维护 `ref_fp_cache`，说明运行时已经接受“按参考音做缓存”这类局部缓存模式；
    - `[tools/dub_pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_pipeline.py)` 的 `build_backend_reference_selector()` 已支持按 `speaker_track_id` 选择/复用参考音，组合 backend 可以直接站在现有 reference selector 之上。
- 功能点 4：保留现有 reference selector 逻辑，不重写 ASD / clean ref / speaker track 流程。
  - 目标行为：
    - `qwen-omnivoice` 直接消费当前主链路选出来的 `ref_audio_path`；
    - V3 若已产出 `speaker_track_id` 并命中 track-level clean ref，则组合 backend 自动继承这套更干净的参考音；
    - 不在本轮顺手改 speaker segmentation、ASD API、前端播放器或 review 机制。
  - 依据：
    - `[tools/dub_pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_pipeline.py)` 的 `build_backend_reference_selector()` 已是 reference 选择的统一出口；
    - `[src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py)` 的句级/组级循环都统一通过 `ref_audio_selector` 拿到 `seg_ref_audio_path / group_ref_audio_path`。
- 功能点 5：前端只新增一个可选 backend，不新增新的复杂表单。
  - 目标行为：
    - 底座模型下拉中增加 `Qwen3-TTS + OmniVoice`；
    - 继续复用现有 OmniVoice runtime 参数区；
    - 不新增第二套“Qwen anchor 参数面板”，首版固定使用当前项目已验证的 `x_vector_only_mode=True`。
  - 依据：
    - `[src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html)` 当前已有统一的 backend 下拉；
    - `[src/subtitle_maker/static/js/dubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/dubbingPanel.js)` 在提交时统一写入 `tts_backend`；
    - `[src/subtitle_maker/static/app.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js)` 已有 backend 名称归一化逻辑，需要一并扩展，但不需要新交互模型。
- 功能点 6：运行日志与 manifest 需要显式标记“原参考音 -> Qwen anchor -> OmniVoice 最终配音”的链路，便于排查英文原声混入问题。
  - 目标行为：
    - segment 级 record 至少记录：
      - 原始 `voice_ref_path`
      - 生成后的 `anchor_ref_path`
      - `anchor_backend=qwen`
      - `final_backend=omnivoice`
    - 如果 anchor 生成失败，要能区分是“Qwen anchor 失败”还是“OmniVoice 最终合成失败”。
  - 依据：
    - `[src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py)` 当前逐句记录里已经保存 `voice_ref_path`、失败码、attempts 等信息，扩展这层记录最顺手。
- 本轮明确不做：
  - 不引入 `VoxCPM`；
  - 不改 `ASD` 服务与 tracked speaker 逻辑；
  - 不顺手重做前端；
- 不尝试让 `Qwen3-TTS` 直接控时；
- 不新增新的独立 API 服务进程，优先复用现有本地 `Qwen3-TTS` 模型加载方式与现有 `OmniVoice` 服务。

## Spec-8（2026-05-03 Qwen3-TTS + OmniVoice 组合底座）3/3 风险、关键决策与推荐方案
- 风险 1：anchor 也是模型生成音，不是真人原声，因此无法从架构上保证一定比当前直接英文 ref 更干净。
  - 影响：
    - 如果 `Qwen3-TTS` 生成的中文 anchor 自身带不稳定停顿、气口或音色漂移，`OmniVoice` 会继续学习这些误差；
    - 所以这条路线解决的是“参考音语言不匹配”问题，不是自动消灭全部脏 ref 问题。
  - 结论：
    - 这不是否决项，但必须把产物链路暴露出来，让我们能区分“原始 ref 脏”还是“Qwen anchor 脏”。
- 风险 2：运行耗时和显存压力会上升，因为组合 backend 至少多了一跳生成。
  - 依据：
    - 当前本地 `Qwen3-TTS` 是在 `tools/dub_pipeline.py` 中直接加载模型并本地推理；
    - `OmniVoice` 又是另一套本地运行时 / API 服务。
  - 影响：
    - 若按“每句都即时生成 anchor”做，长视频会明显变慢；
    - 若不做缓存，成本会高到不可用。
  - 结论：
    - anchor 缓存不是优化项，而是首版必须项。
- 风险 3：如果组合语义硬塞到 `fallback_tts_backend`，后续 manifest、恢复、review redub、前端展示都会语义错乱。
  - 依据：
    - `[src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py)` 当前把 `fallback_tts_backend` 当作失败备胎；
    - `[src/subtitle_maker/manifests/schema.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/manifests/schema.py)` 与 `[src/subtitle_maker/manifests/readwrite.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/manifests/readwrite.py)` 都按这个语义存取；
    - 相关单测也都围绕“备胎”语义写死，如 [tests/test_command_builder.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_command_builder.py)。
  - 结论：
    - 必须把 `qwen-omnivoice` 作为新的主 backend 标识，不要滥用 fallback 字段。
- 风险 4：前端全局 backend 下拉当前只接受 `omnivoice` 和默认值，若不一起改归一化逻辑，会出现 UI 选了新值但请求被前端 silently 改回默认。
  - 依据：
    - `[src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html)` 当前下拉只有 `index-tts` / `omnivoice`；
    - `[src/subtitle_maker/static/app.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js)` 的 `normalizeGlobalTtsBackend()` 目前只有 `omnivoice` 显式白名单，其他值会退回默认。
  - 结论：
    - 前端不是可选项，至少要同步加 backend 选项与归一化白名单。
- 风险 5：如果 anchor 文件不进 manifest / record，后续很难解释“为什么这句还是混进英文原声”。
  - 影响：
    - 用户看到的只有最终配音坏了，但不知道坏在原始 ref、Qwen anchor、还是 OmniVoice；
    - review redub 也无法有针对性地重跑或比对。
  - 结论：
    - manifest / attempts / segment records 必须保留 anchor 路径与 backend 链路字段。

- 关键决策 1：组合模式命名
  - 选项 A：`tts_backend=qwen-omnivoice`
  - 选项 B：保留 `tts_backend=qwen`，再加布尔开关 `use_omnivoice_refit=true`
  - 推荐：选 A
  - 原因：
    - 语义清晰；
    - manifest/replay/review 更容易看懂；
    - 避免 `qwen` 这个既有 backend 语义被悄悄改变。

- 关键决策 2：anchor 生成粒度
  - 选项 A：每句生成一个 anchor
  - 选项 B：按参考音 / track 复用 anchor
  - 推荐：首版采用 B
  - 原因：
    - 长视频成本可控；
    - 与现有 `speaker_track_id` / reference selector 路径自然兼容；
    - 更符合“同一个人一段内音色一致”的目标。

- 关键决策 3：Qwen anchor 文本来源
  - 选项 A：直接用当前待配音的中文译文生成 anchor
  - 选项 B：固定短中文模板句生成 anchor
  - 推荐：首版采用 A
  - 原因：
    - 不需要新增模板管理；
    - 生成出的 anchor 语言、发音风格更贴近最终句子；
    - 如果后面发现 anchor 太长导致不稳，再收敛为短模板句是可逆优化。

- 关键决策 4：首版验证范围
  - 选项 A：直接接进 V1/V2/V3 全链路并默认可用
  - 选项 B：先接成一个可选 backend，只做定向样本验证
  - 推荐：选 B
  - 原因：
    - 这是新组合链路，风险主要在实际音频质量，不在语法层；
    - 应先验证 `Qwen anchor -> OmniVoice` 是否真的减少英文泄漏，再决定是否扩大默认使用面。

- 推荐方案（实施顺序）：
  - 第 1 步：新增 `qwen-omnivoice` 主 backend 标识，打通前端下拉、API 归一化、CLI 参数校验、manifest 存取、command builder。
  - 第 2 步：在 `synthesize_text_once()` 附近收敛组合逻辑：
    - 先用当前 `ref_audio_path` 生成中文 anchor；
    - 再把 anchor 交给 `OmniVoiceBackend`，并继续传 `target_duration_sec`。
  - 第 3 步：增加 anchor 缓存与中间产物落盘，并把 `voice_ref_path` / `anchor_ref_path` / `final_backend` 写入 record。
  - 第 4 步：补最小测试：
    - backend 值校验；
    - command builder 透传；
    - manifest round-trip；
    - 组合模式下的 runtime 行为单测。
  - 第 5 步：只拿你当前问题样本做 smoke test，对比：
    - 原 `omnivoice`
    - 新 `qwen-omnivoice`
    - 关注点只看三项：英文原声是否减少、音色一致性、时长是否仍卡住。

## Review（2026-05-03 Qwen3-TTS + OmniVoice 组合底座 Spec）
- 已完成：
  - [x] Spec 1/3：现状分析
  - [x] Spec 2/3：功能点与改动边界
  - [x] Spec 3/3：风险、关键决策与推荐方案
- 当前状态：
  - 已完成方案阶段，尚未开始编码；
  - 按仓库 HARD-GATE 规则，下一步必须等确认后才能实施。

## Spec-7（2026-05-03 VoxCPM + OmniVoice 第三底座）1/3 现状分析
- 目标：在 `subtitle-maker` 中新增第三个 TTS 底座选项 `VoxCPM + OmniVoice`。
- 目标语义：
  - 先用 `/Users/tim/Documents/vibe-coding/MVP/VoxCPM` 做零样本中文音色锚点生成；
  - 再把该中文锚点音频作为 OmniVoice 的参考音频，让 OmniVoice 负责句级时长控制；
  - 最终作为现有 `tts_backend` 的第三个可选项接入前后端与任务编排。
- 现状 1：`subtitle-maker` 当前只接受 `index-tts` / `qwen` / `omnivoice` 三个主底座。
  - 依据：`[src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py)` 中参数归一化逻辑明确校验 `tts_backend in {"index-tts", "qwen", "omnivoice"}`。
- 现状 2：OmniVoice 已有完整的本地 API 服务化接入，协议与自动拉起链路都在 `subtitle-maker` 内部。
  - 依据：
    - `[tools/omnivoice_fastapi_server.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/omnivoice_fastapi_server.py)` 已提供 `/health` / `/synthesize` / `/release` 风格的 HTTP 服务；
    - `[src/subtitle_maker/backends/omni_voice.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/backends/omni_voice.py)` 已封装 API/CLI 双路径、质量重试与本地服务恢复；
    - `[src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py)` 已有 OmniVoice runtime 参数透传与自动启动脚本配置。
- 现状 3：前端当前“底座模型”控件也只围绕 `index-tts` / `omnivoice` / `qwen` 组织。
  - 依据：`[src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html)` 与 `[src/subtitle_maker/static/js/dubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/dubbingPanel.js)` 中 `tts_backend` 相关选项和表单提交逻辑。
- 现状 4：`VoxCPM` 仓库目前有可直接复用的推理入口，但它不是现成的 `subtitle-maker` API 兼容服务。
  - 依据：
    - `[VoxCPM/app.py](/Users/tim/Documents/vibe-coding/MVP/VoxCPM/app.py)` 是 Flask WebUI/接口风格实现，不是 `subtitle-maker` 当前 OmniVoice 那种轻量 TTS API；
    - `[VoxCPM/launch_wrapper.py](/Users/tim/Documents/vibe-coding/MVP/VoxCPM/launch_wrapper.py)` 只是启动 Flask app；
    - `[VoxCPM/README.md](/Users/tim/Documents/vibe-coding/MVP/VoxCPM/README.md)` 公开了 `voxcpm.VoxCPM.generate(...)` 的直接 Python 调用方式，说明最稳的复用层是“新增一个 subtitle-maker 风格的 VoxCPM API 服务”。
- 现状 5：现有 dubbing 主链路对“参考音频”这一抽象已经有明确入口，新增第三底座不需要推翻整条配音流水线。
  - 依据：
    - `[src/subtitle_maker/backends/base.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/backends/base.py)` 的 `TtsSynthesisRequest` 已包含 `ref_audio_path` / `ref_text` / `target_duration_sec` 等关键字段；
    - `[src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py)` 现有句级/组级合成都通过 backend 抽象进入，不要求前端理解底层细节。
- 现状 6：本需求不是“替换 OmniVoice”，而是“在 OmniVoice 前增加一层 VoxCPM 中文锚点生成”，所以它更像新增一个组合 backend，而不是单独再加一个平行底座。
  - 推论依据：
    - OmniVoice 现有职责已经是“句级生成 + 时长控制”；
    - VoxCPM 更适合承担“零样本中文音色锚点生成”；
    - 因此最自然的实现边界是：新增 `voxcpm-omnivoice` 组合 backend，内部先调 VoxCPM，再调 OmniVoice。

## TODO（2026-05-03 VoxCPM + OmniVoice 第三底座）
- [ ] 完成 Spec 2/3：功能点与改动边界
- [ ] 完成 Spec 3/3：风险、关键决策与推荐方案
- [ ] HARD-GATE：等待你确认后再开始编码

## TODO（2026-05-03 V3 track-level clean ref）
- [x] 长视频分段裁剪时保留 `speaker_track_id` 元数据，不在 segment 层丢失
- [x] OmniVoice 参考音选择层接入 `speaker_track_id`，同一 track 复用首个合格 ref
- [x] 补轻量回归测试，覆盖 segment 保字段与 track ref 复用

## Review（2026-05-03 V3 track-level clean ref）
- 已实现：
  - [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 的 `clip_subtitles_for_segment()` 现在会保留除 `start/end/text` 之外的元数据，`speaker_track_id` 不会在 segment 层被裁掉；
  - [tools/dub_pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_pipeline.py) 的 `build_backend_reference_selector()` 现在会在 `tts_backend=omnivoice` 时优先按 `speaker_track_id` 复用同一 track 的首个合格 ref，减少每条字幕都各吃自己英文时间窗 ref 的概率；
  - 统计字段新增 `track_reference_count`，便于直接从 reference strategy 结果看是否发生了 track 级复用。
- 已验证：
  - [tests/test_dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dub_long_video.py) 新增 `test_clip_subtitles_for_segment_preserves_speaker_track_id_metadata`；
  - [tests/test_dub_pipeline_references.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dub_pipeline_references.py) 新增 `test_build_backend_reference_selector_reuses_first_track_reference_for_same_speaker`，并把旧的 vocals-stem 检查收敛为当前主链路源码断言；
  - `PYTHONPATH=src python3 -m unittest tests.test_dub_pipeline_references`：`Ran 2 tests ... OK`
  - `PYTHONPATH=src python3 -m unittest tests.test_dub_long_video.DubLongVideoTests.test_clip_subtitles_for_segment_preserves_speaker_track_id_metadata`：`Ran 1 test ... OK`
  - `python3 -m py_compile src/subtitle_maker/domains/dubbing/speaker_segments.py tools/dub_long_video.py tools/dub_pipeline.py tests/test_speaker_segments.py tests/test_dub_long_video.py tests/test_dub_pipeline_references.py`
- 边界：
  - 这一步仍然不是完整的“clean ref 提取器”，只是先做到“同一 track 不要反复吃各自字幕窗 ref”；
  - 下一步真实验证重点是：`group_0003/0004` 这种断脸场景里，英文泄漏是否明显下降。

## TODO（2026-05-03 V3 断脸继承 speaker track）
- [x] V3 `assign_speakers_to_subtitles()` 在无人脸/无 track 字幕窗里继承上一个 `speaker_track_id`
- [x] V3 重写后的字幕结构保留 `speaker_track_id`，为后续 track-level ref 铺路
- [x] 补回归测试，覆盖断脸继承与字幕结构保留

## Review（2026-05-03 V3 断脸继承 speaker track）
- 已实现：
  - [src/subtitle_maker/domains/dubbing/speaker_segments.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/speaker_segments.py) 的 `assign_speakers_to_subtitles()` 现在会在当前字幕窗完全没有可见 `speaker_track_id` 时，继承上一位已确认说话人的 `speaker_track_id`，避免短暂断脸把 speaker segment 切碎；
  - 同文件 `build_subtitles_from_speaker_segments()` 现在会把 `speaker_track_id` 保留到重写后的字幕结构里，给后续 track-level reference 选择提供输入。
- 验证：
  - [tests/test_speaker_segments.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_speaker_segments.py) 新增“无人脸时继承上一 track”用例；
  - 同时更新“重写字幕结构保留 `speaker_track_id`”断言；
  - `PYTHONPATH=src python3 -m unittest tests.test_speaker_segments`：`Ran 5 tests ... OK`
- 边界：
  - 这一步只解决 speaker continuity，不直接解决英文原声混入；
  - 下一步仍需要基于保留下来的 `speaker_track_id` 做 track-level clean ref，才能真正减少脏 ref 导致的英文泄漏。

## TODO（2026-05-03 Auto Dubbing V3）
- [x] 新建 `docs/plans/0002-auto-dubbing-v3-2026-05-03.md` 并落档 V3 计划书
- [x] 创建本地 checkpoint commit，作为 V3 实现前可回滚锚点
- [x] 左侧栏新增 `Auto Dubbing V3` 与 `panel-auto-dub-v3`
- [x] 后端允许 `pipeline_version=v3`，并透传 V3 CLI 参数
- [x] 接入 `asd-pipeline /run-tracked`，生成 `speaker_segments.json`
- [x] 复用现有长视频链路，将 speaker segment 重写后的字幕送入后续配音流程
- [x] V3 默认本地 `asd-pipeline` 服务增加自动探活与自动启动
- [ ] 补测试并验证 V1/V2 不回归

## Review（2026-05-03 Auto Dubbing V3）
- 已实现：
  - [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html) 新增 `Auto Dubbing V3` 菜单与 `panel-auto-dub-v3`；
  - [src/subtitle_maker/static/js/dubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/dubbingPanel.js) 新增第三套 `setupAutoDubbing()` 实例，提交 `pipeline_version=v3`；
  - [src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py) 接受 `v3`，并透传 `v3_asd_api_url` / `v3_speaker_segment_mode`；
  - [src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py) 现已在 `pipeline_version=v3` 时先探活 `asd-pipeline`，默认本地地址失败会自动调用 `/Users/tim/Documents/vibe-coding/huayang/asd-pipeline/start.sh`；
  - [src/subtitle_maker/jobs/command_builder.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/jobs/command_builder.py) 增加 `--v3-mode`、`--v3-asd-api-url`、`--v3-speaker-segment-mode`；
  - [src/subtitle_maker/domains/dubbing/speaker_segments.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/speaker_segments.py) 新增 tracked ASD 调用、focus 归属、speaker segment 合并，以及把 speaker segment 重写为后续配音字幕的逻辑；
  - [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 在 V3 模式下先调用 ASD，生成 `speaker_segments.json`，并把按 speaker segment 重写后的字幕送入现有长视频配音链路。
- 失败复盘与修复：
  - 真实运行 `web_20260503_050151 / longdub_20260503_130157` 失败的根因，不是 `segment_0001` 内部没写 manifest，而是 `dub_long_video.py` 把 `--v3-mode` / `--v3-asd-api-url` / `--v3-speaker-segment-mode` 原样透传给了 [tools/dub_pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_pipeline.py)；
  - `dub_pipeline.py` 不认识这些参数，`Segment 01` 启动即报 `unrecognized arguments` 并退出，随后 `dub_long_video.py` 才在读取 `segment_jobs/segment_0001/manifest.json` 时抛出 `missing manifest`；
  - 已在 [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 新增 `filter_segment_extra_args()`，把只属于 long-video V3 编排层的参数过滤掉，不再传给 `dub_pipeline.py`。
- 已验证：
  - `python3 -m py_compile src/subtitle_maker/domains/dubbing/speaker_segments.py tools/dub_long_video.py tests/test_speaker_segments.py tests/test_dub_long_video.py`
  - `PYTHONPATH=src python3 -m unittest tests.test_speaker_segments`：`Ran 4 tests ... OK`
  - `python3 -m py_compile tools/dub_long_video.py tests/test_dub_long_video.py`
  - `python3 -m py_compile src/subtitle_maker/dubbing_cli_api.py tests/test_dubbing_cli_api.py`
  - `node --check src/subtitle_maker/static/js/dubbingPanel.js && node --check src/subtitle_maker/static/app.js`
- 当前阻塞：
  - `python3 -m unittest tests.test_dub_long_video` 在当前环境因缺少 `soundfile` 无法导入 `tools/dub_long_video.py`，属于环境缺包，不是本轮新增逻辑的语法错误。
  - `PYTHONPATH=src python3 -m unittest tests.test_dubbing_cli_api...` 在当前环境因缺少 `torch` 无法导入 `subtitle_maker.transcriber`，因此本轮新增的 ASD 自动启动测试未能在该环境实际执行。

## TODO（2026-05-02 Index-TTS 吞字修复）
- [x] 新建 `docs/plans/0001-index-tts-timing-fix-2026-05-02.md` 并落档本轮实施计划
- [x] 创建本地 checkpoint commit，纳入当前 `Index-TTS` 相关未提交改动，作为回滚锚点
- [x] 扩展 `Index-TTS` strict 尾部保护，避免阈值内强制 fit 导致句尾被截断
- [x] 放宽 `trim_silence_edges()` 的默认 padding，减少轻声首尾被误裁
- [x] 使用 `Index-TTS` API 返回的 `duration_sec` 建立过短/过长质量反馈与重试
- [x] 在进入 `compose_vocals_master()` 前增加超窗守卫，阻止会被二次裁尾的 `done` 片段
- [x] 补单测与回归验证，覆盖 strict 尾部保护、trim padding、duration 反馈、compose 守卫

## Review（2026-05-02 Index-TTS 吞字修复）
- 计划与回滚锚点：
  - 新增 [docs/plans/0001-index-tts-timing-fix-2026-05-02.md](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/docs/plans/0001-index-tts-timing-fix-2026-05-02.md)；
  - 本地 checkpoint commit：`355d7e0 chore: checkpoint index tts timing fix plan`。
- 后端修复：
  - [src/subtitle_maker/backends/index_tts.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/backends/index_tts.py) 现在会消费 API `duration_sec`，对明显偏短/偏长结果做一次内部质量重试，并保留 `last_synthesis_meta` 供排障；
  - [src/subtitle_maker/domains/dubbing/alignment.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/alignment.py) 把 `trim_silence_edges()` 默认 `pad_sec` 从 `0.03` 提到 `0.08`；
  - [src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py) 将 strict 尾部保护扩到 `Index-TTS`，并新增仅对 `Index-TTS` 生效的 compose 超窗守卫，超出 `effective_target + 0.03s` 的候选会转 `manual_review`，不再静默进入拼轨。
- 验证证据：
  - `uv run python -m py_compile src/subtitle_maker/backends/index_tts.py src/subtitle_maker/domains/dubbing/alignment.py src/subtitle_maker/domains/dubbing/pipeline.py tests/test_dubbing_runtime.py`
  - `uv run python -m unittest tests.test_dubbing_runtime tests.test_index_tts_fastapi_server`

## TODO（2026-04-30 Sidebar Logo 重做 + 上传入口合并）
- [x] 左侧栏 Logo 区改为导航式左对齐（图标左 + `Subtitle/Maker` 两行右），移除 96x96 方块占位
- [x] 折叠态宽度收敛到数字导航同级（约 64px），仅保留小图标与紧凑折叠按钮
- [x] 基于 `assets/logo.png` 做浅底抠除，重生透明版 `static/logo/logo.png`
- [x] 同步重生 favicon 全套（ico/png/apple/android/webmanifest）并保持模板版本参数防缓存
- [x] 合并 `1.Upload Video` 与 `4.Import SRT`：菜单改为 `Upload Video & SRT`，Panel 1 内双上传控件左右并排
- [x] 前端增加 SRT 导入守卫：未上传视频/音频时阻断并提示，避免孤立字幕任务
- [x] 最小验证：`node --check`（`app.js` / `dubbingPanel.js`）通过，静态图格式与尺寸校验通过

## Review（2026-04-30 Sidebar Logo 重做 + 上传入口合并）
- Logo 布局与折叠态：
  - [src/subtitle_maker/static/style.css](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/style.css) 将 Logo 头部改为左对齐紧凑导航样式；
  - 折叠宽度使用 `--sidebar-collapsed-width` 新参数（约 64px），折叠图标 22px、按钮 28px，避免“展开态尺寸牵连折叠态”。
- Logo/Favicon 资源：
  - 透明化输出 [src/subtitle_maker/static/logo/logo.png](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/logo/logo.png)；
  - 新增 [src/subtitle_maker/static/favicon/](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/favicon/) 全套图标与 manifest；
  - 模板 [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html) 保持 favicon/logo 版本参数，避免浏览器读到旧缓存。
- 上传入口合并：
  - [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html) 移除 `panel-srt`，Panel 1 合并“视频必选 + SRT 可选”双区块；
  - [src/subtitle_maker/static/style.css](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/style.css) 新增 `upload-dual-grid`，桌面左右并排、窄屏自动单列；
  - [src/subtitle_maker/static/app.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js) `handleSrtUploadWrapper()` 增加“先有媒体再传 SRT”守卫。
- 验证证据：
  - `node --check src/subtitle_maker/static/app.js`
  - `node --check src/subtitle_maker/static/js/dubbingPanel.js`
  - `file`/Pillow 检查 `logo.png` 与 `favicon` 全套为 RGBA + 目标尺寸。

## TODO（2026-04-27 上传 translated.srt 后强制重配 missing 行）
- [x] 现状确认：上传 `translated.srt` 时后端跳过翻译并关闭 rewrite，`missing` 仅由 TTS 失败产生
- [x] 后端新增“保持译文不变，强制重配指定 review 行”的入口，覆盖 `manual_review/missing` 补跑
- [x] 前端接 review 面板动作，支持不改字幕文本直接触发重配
- [x] OmniVoice API 增加逐请求日志，记录输入/输出/耗时/异常，便于排查中途掉线
- [x] 定向验证：语法检查 + review/OmniVoice 相关单测

## Review（2026-04-27 上传 translated.srt 后强制重配 missing 行）
- 现状确认：
  - Web 入口 [src/subtitle_maker/dubbing_cli_api.py::start_auto_dubbing()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py:1759) 在上传字幕文件时会把 `input_srt_kind` 透传为 `translated`；
  - 运行日志 [segment_0001.jsonl](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/outputs/dub_jobs/web_20260427_135229/longdub_20260427_215234/segment_jobs/segment_0001/logs/segment_0001.jsonl) 已确认 `translation_skipped_input_translated_srt` 与 `translation_rewrite_disabled`，因此这类任务里的 `missing` 不是翻译链路问题，而是 TTS 失败后留下的产物。
- 修复：
  - [src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py)
    - 新增 `_segment_row_needs_force_redub()`、`_collect_force_redub_review_indices()`，从 segment manifest 中识别 `*_missing.wav` / 失败态候选；
    - 新增 `_execute_review_redub()`，统一“改字幕重配”和“保持字幕不变强制重配”两类事务，避免重复维护 segment rerun 逻辑；
    - 新增 `POST /dubbing/auto/review/{task_id}/redub-failed`，支持不改 `translated.srt` 直接补跑失败句；
    - 顺手修复 `save-and-redub` / `redub-failed` 在 `no_changes` / `no_candidates` 时误把任务状态留在 `running` 的问题。
  - [src/subtitle_maker/static/js/dubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/dubbingPanel.js) 与 [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html)
    - review 工具栏新增“重配失败句”按钮，直接调用新后端入口，不要求用户先改字幕文本。
  - [tools/omnivoice_fastapi_server.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/omnivoice_fastapi_server.py)
    - 新增结构化服务端日志：`server_started`、`model_loading_started/finished`、`synthesize_started/finished/failed`、`model_released`；
    - 日志包含 `request_id/output_path/text_length/text_preview/duration/elapsed_ms/error`，后续排查中途断联可直接看 `outputs/omnivoice_api.log`。
- 回归测试：
  - [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py)
    - 新增 `test_review_redub_failed_reuses_existing_translated_text`
    - 新增 `test_review_redub_failed_no_candidates_keeps_task_completed`
    - 追加 `save-and-redub no_changes` 场景的状态保持断言
- 验证证据：
  - `uv run python -m py_compile src/subtitle_maker/dubbing_cli_api.py tools/omnivoice_fastapi_server.py tests/test_dubbing_cli_api.py`：通过
  - `node --check src/subtitle_maker/static/js/dubbingPanel.js`：通过
  - `uv run python -m unittest tests.test_dubbing_cli_api`：`Ran 61 tests ... OK`

## TODO（2026-04-27 Auto Dubbing 断点续传）
- [x] 后端新增 `POST /dubbing/auto/resume/{task_id}`，支持失败/取消任务从既有 `longdub_*` 批次续跑
- [x] 命令拼装支持 `--resume-batch-dir` 透传，保证 Web 续跑可复用 CLI 现有 resume 语义
- [x] 前端 V1/V2 增加“从失败处继续”按钮，并在失败状态展示、续跑后自动轮询新任务
- [x] 补单测覆盖：续跑成功、状态拦截（非 failed/cancelled）、批次目录缺失
- [x] 执行最小验证（语法检查 + 相关单测）并回填 Review

## Review（2026-04-27 Auto Dubbing 断点续传）
- 后端续跑入口：
  - [src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py) 新增 `POST /dubbing/auto/resume/{task_id}`。
  - 仅允许 `failed/cancelled` 任务续跑；若已有其他活跃任务则返回 `409`。
  - 续跑会自动解析原 `longdub_*` 目录、原输入媒体路径与历史参数，并创建新任务继续轮询。
- 命令透传：
  - [src/subtitle_maker/jobs/command_builder.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/jobs/command_builder.py) 的 `AutoDubbingCommandConfig` 新增 `resume_batch_dir`，并在命令中追加 `--resume-batch-dir`。
  - 续跑路径由 Web 直接复用 `tools/dub_long_video.py` 已有的 resume 语义，不重造分段逻辑。
- 前端交互：
  - [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html) 为 V1/V2 各新增“从失败处继续”按钮。
  - [src/subtitle_maker/static/js/dubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/dubbingPanel.js) 新增失败态按钮显隐、`/resume/{task_id}` 调用、续跑后自动切换到新 task 继续 poll。
  - [src/subtitle_maker/static/style.css](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/style.css) 增加按钮布局样式。
- 兼容补充：
  - [src/subtitle_maker/jobs/recovery.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/jobs/recovery.py) 回填 `segment_minutes/min_segment_minutes` 到任务状态，便于历史任务续跑参数回放。
  - [src/subtitle_maker/jobs/models.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/jobs/models.py) 同步新增对应字段类型。
- 验证结果：
  - `uv run python -m py_compile src/subtitle_maker/dubbing_cli_api.py src/subtitle_maker/jobs/command_builder.py src/subtitle_maker/jobs/recovery.py src/subtitle_maker/jobs/models.py tests/test_dubbing_cli_api.py tests/test_command_builder.py` 通过。
  - `node --check src/subtitle_maker/static/js/dubbingPanel.js && node --check src/subtitle_maker/static/app.js` 通过。
  - `uv run python -m unittest tests.test_command_builder tests.test_dubbing_cli_api`：`Ran 60 tests ... OK`。

## TODO（2026-04-27 中断批次可见性修复）
- [x] `batches` 列表从“仅 manifest”改为“longdub 目录全量可见”，包含中断批次
- [x] `load-batch` 支持加载无 `batch_manifest.json` 的中断目录（作为 failed 可续跑任务）
- [x] 前端 Restore 区补“已检测到 N 个结果文件夹/未检测到可加载结果”提示
- [x] 回归测试覆盖中断批次列表与加载后续跑

## Review（2026-04-27 中断批次可见性修复）
- 根因：
  - [src/subtitle_maker/jobs/recovery.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/jobs/recovery.py) 的 `list_available_batches()` 之前只扫描 `batch_manifest.json`，中断任务目录被直接过滤。
- 修复点：
  - `list_available_batches()` 改为扫描 `web_*/longdub_*` 目录，并返回 `has_manifest/status(incomplete|completed)`。
  - 新增 `find_batch_dir_by_name()`，供无 manifest 的目录回查。
  - [src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py) 的 `/dubbing/auto/load-batch` 在 manifest 缺失时改为“加载为 failed 中断任务”，并注入 `resume_batch_dir`，可直接走“从失败处继续”。
  - [src/subtitle_maker/static/js/dubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/dubbingPanel.js) 增加 Restore 列表状态提示，避免“空白无反馈”。
- 验证：
  - `uv run python -m py_compile src/subtitle_maker/jobs/recovery.py src/subtitle_maker/jobs/__init__.py src/subtitle_maker/dubbing_cli_api.py tests/test_dubbing_cli_api.py` 通过。
  - `node --check src/subtitle_maker/static/js/dubbingPanel.js` 通过。
  - `uv run python -m unittest tests.test_dubbing_cli_api tests.test_command_builder`：`Ran 62 tests ... OK`。

## TODO（2026-04-27 OmniVoice 自动启动超时修复）
- [x] 定位前端切换 index-tts -> OmniVoice 时 `auto-start failed` 的根因
- [x] 修复后端 OmniVoice 自动启动等待策略（避免 120s 超时误杀）
- [x] 修复 `start_omnivoice_api.sh` 健康检查超时控制，避免单次请求卡死
- [x] 补回归测试并执行最小验证（单测 + 语法检查）

## Review（2026-04-27 OmniVoice 自动启动超时修复）
- 根因确认：
  - 自动切换链路由 [src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py) 的 `_auto_start_local_omnivoice()` 调用 `start_omnivoice_api.sh`。
  - 该链路之前使用固定 `120s` 等待；当 OmniVoice 启动偏慢或 health 探活卡住时，会出现父进程等待窗口耗尽，脚本非 0 返回并在 stderr 出现 `Terminated: 15 nohup ...`，前端收到 `omnivoice auto-start failed`。
- 修复点：
  - [src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py)：
    - 自动启动超时改为可配置 `OMNIVOICE_AUTO_START_TIMEOUT_SEC`（默认 420s，范围 60~1800）。
    - 脚本返回非 0 或触发超时后，追加一次健康探活；若服务已就绪则视为成功，不再误报失败。
    - 向脚本透传 `OMNIVOICE_START_WAIT_SEC`，让脚本等待窗口与后端超时一致。
  - [start_omnivoice_api.sh](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/start_omnivoice_api.sh)：
    - 新增 `OMNIVOICE_START_WAIT_SEC`（默认 180）与 `OMNIVOICE_CURL_TIMEOUT_SEC`（默认 2）；
    - health 探活 `curl` 增加 `--max-time`；
    - 启动轮询由固定 45 次改为按 `OMNIVOICE_START_WAIT_SEC` 可配置循环。
  - [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py)：
    - 新增 2 条回归：`_auto_start_local_omnivoice` 在“脚本非 0但服务已就绪”与“脚本超时但服务已就绪”两种场景不应失败。
- 验证结果：
  - `bash -n start_omnivoice_api.sh`：通过
  - `uv run python -m py_compile src/subtitle_maker/dubbing_cli_api.py tests/test_dubbing_cli_api.py`：通过
  - `uv run python -m unittest tests.test_dubbing_cli_api`：`Ran 52 tests ... OK`

## 2026-04-27 OmniVoice 时长压缩丢尾字修复

- [x] 记录问题：OmniVoice 句子超时后压缩到时间线时会丢掉句尾几个字
- [x] 定位根因：OmniVoice 链路未透传目标时长，且 `force_fit_timing` 在阈值内仍强制 `fit_audio_to_duration(atrim)`，导致句尾更易被截断
- [x] 修复：OmniVoice 增加 `duration` 透传（API/CLI），并在阈值内跳过二次 fit，优先保留原始尾音
- [ ] 验证：复测粤语样例，检查超时句不再丢尾字（待你本地听感回归）

## Review（2026-04-27 OmniVoice 时长压缩丢尾字修复）
- 代码修复点：
  - [src/subtitle_maker/backends/base.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/backends/base.py)：`TtsSynthesisRequest` 新增 `target_duration_sec`。
  - [src/subtitle_maker/backends/omni_voice.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/backends/omni_voice.py)：OmniVoice API/CLI 透传 `duration`。
  - [src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py)：逐句/分组合成都透传目标时长；OmniVoice 在 `force_fit_timing` 且已在阈值内时跳过二次 fit（`fit_timing_skip_tail_preserve`）。
  - [tools/dub_pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_pipeline.py)：兼容层 `synthesize_text_once` 同步透传 `target_duration_sec`。
- 测试与校验：
  - `uv run python -m compileall -q src/subtitle_maker tools tests` 通过。
  - `uv run python -m unittest tests.test_dubbing_runtime` 通过（`Ran 12 tests ... OK`）。
  - 新增回归覆盖：
    - OmniVoice 请求包含 `target_duration_sec -> duration`。
    - OmniVoice + `force_fit_timing=true` + 阈值内时不再调用 `fit_audio_to_duration`。

## 2026-04-27 OmniVoice seg_0001_missing.wav 修复

- [x] 定位 V2 任务失败根因（从 job/segment 日志提取 `E-TTS-001`）
- [x] 修正 OmniVoice 启动默认模型为本地 checkpoints，避免依赖 HF 在线下载
- [x] 兜底：`omnivoice_fastapi_server.py` 默认模型同步改为本地 checkpoints
- [x] 实机验证：后台脚本启动 + `/synthesize` 成功产出 wav

## Review（2026-04-27 OmniVoice seg_0001_missing.wav 修复）
- 失败根因已确认：`segment_0001.jsonl` 报错 `E-TTS-001 omnivoice api http 500`，detail 为“无法连接 huggingface.co 且本地无缓存”，导致每句回退 `manual_review` 并生成 `seg_0001_missing.wav` 占位文件。
- 修复文件：
  - [start_omnivoice_api.sh](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/start_omnivoice_api.sh)：`OMNIVOICE_MODEL` 默认值从 `k2-fsa/OmniVoice` 改为 `$OMNIVOICE_ROOT/omnivoice/checkpoints`。
  - [tools/omnivoice_fastapi_server.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/omnivoice_fastapi_server.py)：`DEFAULT_OMNIVOICE_MODEL` 改为本地 checkpoints 绝对路径。
- 验证结果：
  - `start_omnivoice_api.sh` 启动后 `/health` 返回 `model=/Users/tim/Documents/vibe-coding/MVP/OmniVoice/omnivoice/checkpoints`。
  - 后台脚本模式 `/synthesize` 成功，产物 `/tmp/omnivoice_api_smoke2.wav` 存在且大小正常（`412880` bytes）。

## 2026-04-27 TTS 懒汉式切换（单模型驻留）

- [x] `start.sh` 默认模式改为懒启动：不预热 index-tts/OmniVoice
- [x] 新增 `stop_omnivoice_api.sh`，提供与 index-tts 对称的停服脚本
- [x] `dubbing_cli_api` 启动前改为“先停旧模型，再起新模型”
- [x] review redub 链路复用同一套懒切换逻辑
- [x] 脚本语法 + Python 语法校验

## Review（2026-04-27 TTS 懒汉式切换）
- `src/subtitle_maker/dubbing_cli_api.py` 新增 `_switch_tts_runtime_on_demand()`：`index-tts` 与 `omnivoice` 互切时会先停止对侧本地服务，再启动当前主后端服务，避免双模型常驻内存。
- `src/subtitle_maker/dubbing_cli_api.py` 的 Auto Dubbing 启动参数归一化与 review redub 都已调用该函数，保证正式任务与重配任务行为一致。
- 新增脚本 [stop_omnivoice_api.sh](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/stop_omnivoice_api.sh)，并通过 `dubbing_cli_api` 在需要切换时由后端 CLI 调起。
- `start.sh` 默认 `TTS_BACKEND=auto` 已改为懒启动（`INDEX_TTS_AUTO_START=0`、`OMNIVOICE_AUTO_START=0`），不再首启预热两套模型。

## 2026-04-27 start.sh OmniVoice 测试启动链路

- [x] `start.sh` 新增 `TTS_BACKEND` 启动档位（`index-tts` / `omnivoice` / `qwen`）
- [x] `TTS_BACKEND=omnivoice` 时默认自动拉起 OmniVoice（8020），并默认关闭 index-tts 自动拉起，避免测试混淆
- [x] `stop.sh` 同步补充 OmniVoice 进程与端口清理，避免测试后残留
- [x] 脚本语法校验与端口探活验证

## Review（2026-04-27 start.sh OmniVoice 测试启动链路）
- `start.sh` 已支持通过环境变量切换启动档位：`TTS_BACKEND=omnivoice ./start.sh` 会优先保证 8020 服务可用，不再默认拉起 8010。
- `start.sh` 仍保留显式覆盖能力：`INDEX_TTS_AUTO_START` 与 `OMNIVOICE_AUTO_START` 可单独强制开/关，兼容原有调试习惯。
- `stop.sh` 已新增 OmniVoice 停止逻辑：匹配 `tools/omnivoice_fastapi_server.py`、清理 `:8020` 占用并删除 `omnivoice_api.pid`。

## 2026-04-27 start.sh 交互体验修正（前端自由切换）

- [x] `start.sh` 默认档位改为 `TTS_BACKEND=auto`，默认同时准备 index-tts 与 OmniVoice
- [x] 保留显式档位：`index-tts` / `omnivoice` / `qwen`，用于定向压测
- [x] 脚本语法校验

## Review（2026-04-27 start.sh 交互体验修正）
- 现在直接执行 `./start.sh` 会默认启动两套本地 TTS 服务（8010/8020），前端切换底座无需再手动补启动。
- 如需单底座测试，仍可使用 `TTS_BACKEND=omnivoice ./start.sh` 或 `TTS_BACKEND=index-tts ./start.sh`。

## 2026-04-27 OmniVoice 底座接入（自动拉起 + API 透传）

- [x] 对齐 `start.sh` / `start_index_tts_api.sh` 启动模式，补 `start_omnivoice_api.sh` 作为本地 OmniVoice 启动入口
- [x] 新增 `tools/omnivoice_fastapi_server.py`（`/health`、`/synthesize`、`/model/release`）
- [x] `dubbing_cli_api` 增加 OmniVoice 健康检查、默认 URL 自动启动与失败回传
- [x] `dubbing_cli_api` 增加 `omnivoice_via_api` / `omnivoice_api_url` 表单参数解析与任务状态透传
- [x] `command_builder -> dub_pipeline -> manifest -> review redub` 全链路透传 `omnivoice_via_api` / `omnivoice_api_url`
- [x] 补单测与回归：命令拼装、manifest 合约、runtime 解析、API 自动启动
- [x] 前端侧边栏新增 OmniVoice 运行参数（API URL / via_api）并透传到 Auto Dubbing V1/V2 启动请求
- [x] 增加保护：fallback=omnivoice 不触发自动拉起，仅 `tts_backend=omnivoice` 触发
- [x] 侧边栏布局优化：TTS 底座模型从 DeepSeek 卡片拆分为独立控件
- [x] DeepSeek API 卡片支持折叠（默认收起）并持久化折叠状态
- [x] 交互简化：隐藏 OmniVoice API URL/via_api 前端控件，保持与 index-tts 一致的默认体验

## Review（2026-04-27 OmniVoice 底座接入）
- `src/subtitle_maker/dubbing_cli_api.py` 已新增 `DEFAULT_OMNIVOICE_API_URL`、`_check_omnivoice_service()`、`_auto_start_local_omnivoice()`、`_ensure_omnivoice_service()`；当 `tts_backend=omnivoice` 且 `omnivoice_via_api=true` 时会先探活，不可用则自动调用 `./start_omnivoice_api.sh`。
- `src/subtitle_maker/dubbing_cli_api.py` 的 `/dubbing/auto/start` 与 `/dubbing/auto/start-from-project` 已新增表单字段 `omnivoice_via_api`、`omnivoice_api_url`，并写入任务状态和 CLI 命令。
- `src/subtitle_maker/manifests/schema.py`、`src/subtitle_maker/manifests/readwrite.py`、`src/subtitle_maker/domains/dubbing/review.py` 已补齐 `omnivoice_via_api`、`omnivoice_api_url`，保证 load-batch 与 review redub 不丢参数。
- `tools/dub_pipeline.py` 与 `tools/dub_long_video.py` 已把 `omnivoice_via_api`、`omnivoice_api_url` 写入/回放 manifest，和 `jobs/command_builder.py` 的新 flags 对齐。
- `tests/test_command_builder.py`、`tests/test_dubbing_cli_api.py`、`tests/test_dubbing_runtime.py`、`tests/test_manifest_contracts.py` 已新增/更新断言，覆盖新字段和自动启动路径。
- `src/subtitle_maker/templates/index.html`、`src/subtitle_maker/static/app.js`、`src/subtitle_maker/static/js/dubbingPanel.js` 已新增全局 OmniVoice 参数控件与请求透传：仅当侧边栏底座选择 OmniVoice 时显示并提交 `omnivoice_via_api` / `omnivoice_api_url`。
- `src/subtitle_maker/templates/index.html` 与 `src/subtitle_maker/static/style.css` 已将 `TTS 底座模型` 从 DeepSeek 区块拆出为独立 `sidebar-tts-card`，避免配置混在同一卡片里。
- `src/subtitle_maker/static/app.js` 已新增 DeepSeek 卡片折叠状态管理（`sm_deepseekCollapsed`），默认收起并支持本地持久化。
- `src/subtitle_maker/templates/index.html`、`src/subtitle_maker/static/app.js`、`src/subtitle_maker/static/js/dubbingPanel.js` 已移除 OmniVoice API URL 与 via_api 的前端可见配置；前端只传 `tts_backend=omnivoice`，其余走后端默认值与环境变量。
- `tests/test_dubbing_cli_api.py` 新增“主后端 omnivoice + via_api=false 可启动”与“fallback omnivoice 不自动拉起”断言，锁定触发边界。
- 校验通过：`uv run python -m py_compile src/subtitle_maker/dubbing_cli_api.py src/subtitle_maker/domains/dubbing/review.py src/subtitle_maker/manifests/schema.py src/subtitle_maker/manifests/readwrite.py src/subtitle_maker/jobs/models.py src/subtitle_maker/jobs/recovery.py tools/dub_pipeline.py tools/dub_long_video.py tests/test_command_builder.py tests/test_dubbing_cli_api.py tests/test_dubbing_runtime.py tests/test_manifest_contracts.py`。
- 校验通过：`node --check src/subtitle_maker/static/app.js`、`node --check src/subtitle_maker/static/js/dubbingPanel.js`。
- 回归通过：`uv run python -m unittest tests.test_command_builder tests.test_dubbing_runtime tests.test_manifest_contracts tests.test_dubbing_cli_api`，`Ran 69 tests ... OK`。

## 2026-04-20 ASR 智能分句（DeepSeek hybrid）

- [x] Spec-1：审计 DeepSeek 可复用能力与 ASR 断句接入点（带代码出处）
- [x] Spec-2：确认功能点与精确改动范围
- [x] Spec-3：风险与决策（成本、回退、时延、验收）
- [x] HARD-GATE：等用户确认后实施
- [x] 实施：接入 DeepSeek 智能分句
- [x] 验证：坏样例 + 回归测试

## Review（2026-04-20 ASR 智能分句）
- `tools/dub_pipeline.py` 已新增 `source-layout-mode=hybrid` 默认策略；只作用于 ASR 生成字幕路径，不影响上传 `input_srt`。
- source layout 现为“规则优先 + LLM 兜底”：先跑现有句级规则分句，再仅对疑难长句块调用 DeepSeek 规划 cue 区间；LLM 只输出分组计划，不改写 source 文本。
- 已新增本地校验与评分：LLM 计划必须连续覆盖全部 cue、无重叠、无遗漏；若结果非法、调用失败或评分不优于规则版，则自动回退规则分句。
- `main` 已新增懒加载 `Translator` 复用逻辑，source layout 与后续翻译共用同一个 DeepSeek 客户端，避免重复初始化。
- `tests/test_dub_pipeline_asr_layout.py` 已扩展到 4 条测试，覆盖：规则版碎片收敛、大停顿不跨簇、合法 LLM 计划覆盖规则切点、非法 LLM 计划强制回退。
- 语法校验通过：`uv run python -m py_compile tools/dub_pipeline.py tests/test_dub_pipeline_asr_layout.py src/subtitle_maker/dubbing_cli_api.py tools/dub_long_video.py tests/test_dubbing_cli_api.py`。
- 回归通过：`uv run python -m unittest tests/test_dub_pipeline_asr_layout.py`（`Ran 4 tests ... OK`）、`uv run python -m unittest tests/test_dubbing_cli_api.py`（`Ran 35 tests ... OK`）。

## 2026-04-20 ASR 字幕断句优化（尽量一句话一行）

- [x] Spec-1：审计样例碎片字幕与当前断句/合并链路（带代码出处）
- [x] Spec-2：确认优化目标与精确改动范围
- [x] Spec-3：风险与决策（英文长句、时长上限、回归验证）
- [x] HARD-GATE：等用户确认后实施
- [x] 实施：优化 ASR 字幕尽量按整句输出
- [x] 验证：样例 SRT 对比 + 语法/测试回归

## Review（2026-04-20 ASR 字幕断句优化）
- `tools/dub_pipeline.py` 的 `load_or_transcribe_subtitles` 现已把 `max_width` 透传给 `rebalance_source_subtitles`，仅影响 ASR 生成字幕路径，不影响上传 `input_srt` 分支。
- `rebalance_source_subtitles` 已从“仅在原 cue 数内重排文本”改为“短停顿聚类 -> 句末优先合并 -> 超长句按软停顿/原 cue 边界再拆”，并保持所有输出边界都落在原始 ASR cue 时间点上。
- 坏样例 `outputs/dub_jobs/web_20260420_125747/longdub_20260420_205751/segment_jobs/segment_0001/subtitles/source.srt` 经新逻辑从 `19` 行收敛到 `6` 行，`clear`、`won.` 这类孤儿行不再单独存在。
- 已新增 `tests/test_dub_pipeline_asr_layout.py`，覆盖碎片英文样例收敛与“大停顿不跨簇合并”两个纯函数场景。
- 语法校验通过：`uv run python -m py_compile tools/dub_pipeline.py tests/test_dub_pipeline_asr_layout.py src/subtitle_maker/dubbing_cli_api.py tools/dub_long_video.py tests/test_dubbing_cli_api.py`。
- 回归通过：`uv run python -m unittest tests/test_dub_pipeline_asr_layout.py`（`Ran 2 tests ... OK`）、`uv run python -m unittest tests/test_dubbing_cli_api.py`（`Ran 35 tests ... OK`）。

## 2026-04-20 ASR 标点优先断句修正（句号优先，过长再逗号）

- [x] 明确新规则：优先句号，句内超长时才允许逗号切分
- [x] 实施：把标点拆分接入 `source.srt` 的 rule/hybrid 分句链路
- [x] 实施：放宽“标点后连接词起句”的惩罚，避免压制逗号切分
- [x] 验证：单测 + 真实坏样例复核

## Review（2026-04-20 ASR 标点优先断句修正）
- `tools/dub_pipeline.py` 现已把标点拆分正式接入 `split_oversized_asr_sentence_block`：先只补句号/问号/感叹号边界；仅当单句仍超长时，才补逗号/分号等软停顿边界。
- `split_text_on_punctuation_boundaries`、`split_subtitle_item_by_punctuation`、`expand_block_with_punctuation_splits` 已改成显式区分 `include_soft_breaks`，避免一上来就按逗号打碎所有句子。
- `choose_asr_sentence_split_index`、`score_source_layout_groups`、`count_source_layout_connector_issues`、`should_try_llm_source_layout` 已统一改为：若上一行本来就以显式标点结尾，则不再把下一行以 `but/and/...` 起头视为坏切点。
- `tests/test_dub_pipeline_asr_layout.py` 已更新断言：坏样例第一句现在稳定切成 `...jagged,` / `but ...`；同时保留 1 条 `refine_source_layout_with_llm` 的正向覆盖用例，确保 hybrid 仍可在规则较弱时生效。
- 校验通过：`uv run python -m py_compile tools/dub_pipeline.py tests/test_dub_pipeline_asr_layout.py`。
- 校验通过：`uv run python -m unittest tests/test_dub_pipeline_asr_layout.py`，`Ran 5 tests ... OK`。
- 校验通过：`uv run python -m unittest tests/test_dubbing_cli_api.py`，`Ran 35 tests ... OK`。
- 真实样例复核：`outputs/dub_jobs/web_20260420_133735/longdub_20260420_213738/segment_jobs/segment_0001/subtitles/source.srt` 经过新规则重排后，前两行已变为 `...jagged,` 与 `but that the the floor ...`，切点落在 `8.710s`。

## 2026-04-20 上传 source.srt 复用同一套分句

- [x] 现状确认：仅 ASR 路径会把分句结果落盘到 `source.srt`
- [x] 实施：`input_srt_kind=source` 时也复用 `rebalance_source_subtitles`
- [x] 验证：新增单测 + 语法/回归

## Review（2026-04-20 上传 source.srt 复用同一套分句）
- `tools/dub_pipeline.py` 的 `load_or_transcribe_subtitles()` 现已在 `input_srt != None` 且 `persist_input_srt_to_source=True` 时，复用与 ASR 完全一致的 `rebalance_source_subtitles(...)` 链路；因此上传 `source.srt` 后，本地落盘的 `source.srt` 就是分句后的结果。
- `input_srt_kind=translated` 的链路保持不变：由于该分支传入的是 `persist_input_srt_to_source=False`，不会触发这次新增的 source-layout 重排，避免污染译文直通和 review redub 场景。
- 新增入口级回归 `tests/test_dub_pipeline_asr_layout.py`：直接调用 `load_or_transcribe_subtitles(input_srt=...)`，断言返回值与落盘 `source.srt` 都已经变成 `...jagged,` / `but ...` 的分句结果。
- 校验通过：`uv run python -m py_compile tools/dub_pipeline.py tests/test_dub_pipeline_asr_layout.py`。
- 校验通过：`uv run python -m unittest tests/test_dub_pipeline_asr_layout.py`，`Ran 6 tests ... OK`。
- 校验通过：`uv run python -m unittest tests/test_dubbing_cli_api.py`，`Ran 35 tests ... OK`。

## 2026-04-20 source.srt 断句规则再收紧（句尾必须落在显式标点）

- [x] Spec-1：现状分析与冲突点定位（带代码出处）
- [x] Spec-2：确认新规则与精确改动范围
- [x] Spec-3：风险与决策（无标点长句、时间重估、回归口径）
- [x] HARD-GATE：等用户确认后实施
- [x] 实施：改成“句号优先，过长按逗号拆，句尾必须是显式标点”
- [x] 验证：单测 + 样例 `source.srt` 复核

## Review（2026-04-20 source.srt 断句规则再收紧）
- `tools/dub_pipeline.py` 已新增 `split_cluster_into_punctuation_blocks()` 与 `has_internal_explicit_break_boundary()`，把显式标点边界从“评分偏好”提升为实际切分约束。
- `split_oversized_asr_sentence_block()` 现改为两级策略：先只按句号/问号/感叹号拆；若单句超过 soft 条件（英文默认 `7.2s` 或 `soft_source_layout_text_limit()`）且内部存在逗号边界，再允许按逗号拆，并复用 `allocate_text_segment_times()` 重估拆分后的时间戳。
- `choose_asr_sentence_split_index()` 已新增 `require_explicit_break` 参数：soft-split 场景只允许在显式标点边界上切；hard-split 场景仍可回退到非标点边界，避免无标点长句卡死。
- `tests/test_dub_pipeline_asr_layout.py` 已更新：碎片英文样例现在从 `6` 行变为 `7` 行，其中 OpenAI 句稳定切成 `... launched ChatGPT,` 与 `and I remember ... won.`；并新增“所有输出句尾都落在显式标点上”的断言。
- 上传 `source.srt` 的入口级回归也已同步更新，确认本地最终落盘的 `source.srt` 同样遵守新规则。
- 校验通过：`uv run python -m py_compile tools/dub_pipeline.py tests/test_dub_pipeline_asr_layout.py`。
- 校验通过：`uv run python -m unittest tests/test_dub_pipeline_asr_layout.py`，`Ran 6 tests ... OK`。
- 校验通过：`uv run python -m unittest tests/test_dubbing_cli_api.py`，`Ran 35 tests ... OK`。

## 2026-04-20 短句合并阈值前端控件

- [x] Spec-1：现状分析（前端控件位置 / Web 接口 / CLI 参数入口）
- [x] Spec-2：确认字段命名、默认值、校验边界与精确改动范围
- [x] Spec-3：确认风险与验证口径
- [x] HARD-GATE：等用户确认后实施
- [x] 实施：新增前端控件并透传到后端/CLI
- [x] 验证：前端最小检查 + 后端单测回归
- [x] 规则约束：短句阶段只允许合并，不允许为凑阈值反向拆句

## Review（2026-04-21 短句合并阈值前端控件）
- `tools/dub_pipeline.py` 已新增 `--source-short-merge-threshold`（默认 `50`，范围 `30~80`），并把 `rebalance_source_subtitles()` 扩展为“两阶段”：先做既有标点优先分句，再做 `merge_short_source_subtitles()` 短句合并。
- 短句阶段只允许合并已有相邻句块，不会再次拆句；约束为：相邻 gap `<= asr_balance_gap_sec`、合并后时长 `<= 9.0s`、文本负载不超过 `threshold + 10` 与原有 `asr_sentence_text_limit()`。
- `tools/dub_pipeline.py` 的 job manifest 与 `tools/dub_long_video.py` 的 batch manifest 都已记录 `source_short_merge_threshold`，方便后续复盘 source layout 结果。
- `src/subtitle_maker/dubbing_cli_api.py` 已新增 `short_merge_threshold` 表单字段校验，并透传为 CLI 参数 `--source-short-merge-threshold`；任务状态也会返回该值。
- `src/subtitle_maker/templates/index.html` 与 `src/subtitle_maker/static/app.js` 已为 V1/V2 面板新增数值控件，默认 `50`，前端和后端都做了 `30~80` 边界校验。
- 历史 batch 加载时，前端现在会自动回填当前面板的 `target_lang / subtitle_mode / grouping_strategy / short_merge_threshold / auto_pick_ranges`，V2 额外回填 `rewrite_translation`，避免加载结果后 UI 仍停留在默认值。
- `tests/test_dub_pipeline_asr_layout.py` 已新增 3 条回归：链式合并、阈值可调、超过窗口上限不强并；`tests/test_dubbing_cli_api.py` 已新增默认值/自定义值透传与非法阈值拒绝断言。
- 校验通过：`uv run python -m py_compile src/subtitle_maker/dubbing_cli_api.py tools/dub_pipeline.py tools/dub_long_video.py tests/test_dubbing_cli_api.py tests/test_dub_pipeline_asr_layout.py`。
- 校验通过：`node --check src/subtitle_maker/static/app.js`。
- 回归通过：`uv run python -m unittest tests/test_dub_pipeline_asr_layout.py`，`Ran 9 tests ... OK`。
- 回归通过：`uv run python -m unittest tests/test_dubbing_cli_api.py`，`Ran 37 tests ... OK`。

## 2026-04-21 短句合并增加“避免跨说话人合并”开关

- [x] Spec-1：现状分析与可复用音频特征入口（带代码出处）
- [x] Spec-2：改为用户手动控制短句合并，默认关闭；开启后才显示阈值控件，并明确文案“按字数计算”
- [x] Spec-3：确认风险与验证口径（默认关闭兼容、历史 batch 回填、仅按字数提示、测试覆盖）
- [x] HARD-GATE：已确认实施
- [x] 实施：短句合并改为显式开关控制，默认不开启
- [x] 实施：前端新增开关并仅在开启时显示阈值控件/说明文案
- [x] 实施：后端/CLI/manifest 透传 enable 开关并兼容历史 batch 回填
- [x] 验证：纯函数单测 + Web 接口回归 + 最小语法检查

## Review（2026-04-21 短句合并改为手动开关）
- `src/subtitle_maker/templates/index.html` 的 V1/V2 面板已把短句合并改为显式 checkbox，默认关闭；只有开启后才显示阈值输入框。
- `src/subtitle_maker/static/app.js` 已新增短句合并开关状态同步与 batch 回填逻辑；提交 `/dubbing/auto/start` 时会透传 `short_merge_enabled`，并在关闭时隐藏阈值面板。
- `src/subtitle_maker/dubbing_cli_api.py` 已新增 `short_merge_enabled` 表单字段解析与校验，任务状态和 load-batch payload 会返回 `source_short_merge_enabled`。
- `tools/dub_pipeline.py` 已新增 `--source-short-merge-enabled`，默认 `false`；`rebalance_source_subtitles()` 仅在该开关为真时才进入第二阶段 `merge_short_source_subtitles()`。
- `tools/dub_pipeline.py` 的成功/失败 manifest 与 `tools/dub_long_video.py` 的 batch manifest 已持久化 `source_short_merge_enabled`，旧 batch 缺字段时默认按 `false` 回填。
- `tests/test_dub_pipeline_asr_layout.py` 已新增“默认关闭不合并”的回归；`tests/test_dubbing_cli_api.py` 已覆盖默认关闭、显式开启、关闭时忽略阈值越界，以及 load-batch 回填。
- 校验通过：`uv run python -m py_compile src/subtitle_maker/dubbing_cli_api.py tools/dub_pipeline.py tools/dub_long_video.py tests/test_dubbing_cli_api.py tests/test_dub_pipeline_asr_layout.py`。
- 校验通过：`node --check src/subtitle_maker/static/app.js`。
- 回归通过：`uv run python -m unittest tests/test_dub_pipeline_asr_layout.py`，`Ran 10 tests ... OK`。
- 回归通过：`uv run python -m unittest tests/test_dubbing_cli_api.py`，`Ran 38 tests ... OK`。

## 2026-04-21 Auto Dubbing 表单区布局优化（播放器下方）

- [x] Spec-1：审计当前 Auto Dubbing 表单区结构、样式与交互约束（带代码出处）
- [x] Spec-2：确认新的视觉方向、控件分组与精确改动范围
- [x] Spec-3：确认响应式、交互与验证口径
- [x] HARD-GATE：已确认实施
- [x] 实施：重构 Auto Dubbing 表单区布局与样式
- [x] 实施：必要的前端交互微调，保持现有功能不变
- [x] 验证：前端语法检查 + 关键交互自查

## Review（2026-04-21 Auto Dubbing 表单区布局优化）
- `src/subtitle_maker/templates/index.html` 已把 V1/V2 Auto Dubbing 面板重构为统一的 workbench 布局：输入区、配置区、执行区、范围区、恢复区、状态区、结果区分层明确，不再是长竖排字段堆叠。
- 媒体上传与字幕上传现在并列成首屏输入区；`Source/Target/Grouping` 被收拢为主配置网格；`Start` 与 API key 被集中到独立执行卡片，主操作层级更清楚。
- 时间区间与历史 batch 加载被下沉为次级工具卡片，默认仍可见，但视觉权重低于“上传 + 配置 + 启动”主流程。
- `src/subtitle_maker/static/style.css` 已新增 Auto Dubbing 专属布局类，使用 grid 和 section-card 控制密度与层级；同时补了 `1120px` 与 `768px` 两档响应式，避免平板宽度下控件拥挤。
- 本轮保持了所有现有表单控件 `id` 不变，因此 `src/subtitle_maker/static/app.js` 的 `setupAutoDubbing()` 绑定逻辑无需改动。
- 校验通过：`node --check src/subtitle_maker/static/app.js`。
- 校验通过：`uv run python` 调用 `html.parser` 解析 `src/subtitle_maker/templates/index.html`，输出 `html_parse_ok`。

## 2026-04-20 Python 依赖清理（审计 -> 确认 -> 实施）

- [x] Spec-1：审计 `pyproject.toml` 依赖与仓库真实导入（带代码出处）
- [x] Spec-2：确认清理范围（直接删除 / 保留 / 转 optional）
- [x] Spec-3：风险与决策（运行时隐式依赖、回归范围、验证方式）
- [x] HARD-GATE：已确认实施
- [x] 实施：清理不必要的 Python 依赖
- [x] 验证：锁文件更新 + 语法/测试回归

## Review（2026-04-20 Python 依赖清理）
- 已从 `pyproject.toml` 删除 3 个确认清理项：`requests`、`tiktoken`、`onnx`；保留 `accelerate`、`aiofiles`、`numba`，避免误伤隐式运行时依赖。
- `uv lock && uv sync` 已执行；环境中实际移除了 `onnx==1.20.1`、`tiktoken==0.12.0`，并连带清掉孤儿传递依赖 `ml-dtypes==0.5.4`。
- `uv.lock` 未产生 diff，说明当前锁文件内容已与清理后的顶层依赖集合一致；无需手动改锁文件。
- `requests` 仍在 `uv.lock` 中保留，但已不再是项目顶层依赖，而是其他包的传递依赖；这符合预期，不属于残留清理失败。
- 语法校验通过：`uv run python -m py_compile src/subtitle_maker/web.py src/subtitle_maker/dubbing_cli_api.py tools/dub_pipeline.py tools/dub_long_video.py tests/test_dubbing_cli_api.py`。
- 主链路加载校验通过：`uv run python tools/dub_pipeline.py --help` 正常输出帮助信息。
- 回归通过：`uv run python -m unittest tests/test_dubbing_cli_api.py`，`Ran 35 tests ... OK`。

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

## 2026-04-27 Panel 2/3 布局与内部滚动修复（#panel-transcribe / #panel-results）

- [x] 定位布局根因：`dynamic-content-section` 统一 padding + `.panel` 统一 max-width 造成顶部缝隙与宽度锁定
- [x] 实施：为 2/3 面板新增 `panel-internal-scroll-active` 布局状态
- [x] 实施：切换到 2/3 面板时启用“父容器固定 + 面板内部滚动”
- [x] 实施：移除 2/3 面板固定宽度约束并保持 flex 自适应
- [x] 验证：`node --check src/subtitle_maker/static/app.js`

## Review（2026-04-27 Panel 2/3 布局修复）
- `src/subtitle_maker/static/app.js` 新增 `PANEL_INTERNAL_SCROLL_IDS`，并在 `syncFloatingUiForActivePanel()` 中切换 `body.panel-internal-scroll-active`。
- `src/subtitle_maker/static/style.css` 在该 body 状态下为 2/3 面板启用独立滚动链路：`.dynamic-content-section` 固定、`#panel-transcribe/#panel-results` 占满可用空间、`.card` 内部 `overflow-y:auto`。
- 2/3 面板宽度改为弹性填充：取消 `max-width: 900px` 的影响（仅对该场景覆写为 `max-width:none`，并保留 `min-width:0` 防止 flex 挤压异常）。
- 顶部贴合通过 `padding-top:0`（仅在 2/3 面板激活时）实现，不改动播放器和侧边栏固定区。

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

## 2026-04-19 Auto Dubbing V2 前端独立入口（复用既有代码）

- [x] Spec-1 现状分析（菜单/面板/事件绑定代码出处）
- [x] Spec-2 功能点拆分（新增左侧菜单“6 Auto Dubbing V2”与独立面板）
- [x] Spec-3 风险与决策（复用边界、状态隔离、回归范围）
- [x] HARD-GATE：等待用户确认后实施
- [x] 实施：新增 `panel-auto-dub-v2` 与对应 nav item
- [x] 实施：复用旧逻辑抽成可复用初始化函数，绑定 V2 独立 DOM 前缀
- [x] 实施：V2 独立状态渲染与任务轮询（不影响 V1）
- [x] 验证：`node --check` + 后端单测最小回归

## Review（2026-04-19 Auto Dubbing V2）
- 前端新增左侧第 6 项菜单与独立面板 `panel-auto-dub-v2`，并采用 `auto-dub-v2-*` 独立 DOM 前缀。
- `app.js` 的 Auto Dubbing 初始化改为实例化函数 `setupAutoDubbing(config)`，V1/V2 共用逻辑但状态隔离。
- `/dubbing/auto/start` 新增 `pipeline_version` 入参，V2 会透传 `--v2-mode true` 到下游链路。
- `dub_pipeline.py` 新增 `--v2-mode`，并在 V2 下默认逐句主链路、禁用硬性 end fit、禁用翻译改写、限制变速区间、最少 3 候选尝试。
- 新增句单元标准化函数 `normalize_subtitle_sentence_units`，在 V2 翻译/TTS 前做 start/end 规整。
- `dub_long_video.py` 在 V2 模式下新增全局字幕时间规整后再分段裁剪，降低跨段断裂。
- 校验通过：`node --check src/subtitle_maker/static/app.js`。
- 校验通过：`uv run python -m py_compile src/subtitle_maker/dubbing_cli_api.py tools/dub_pipeline.py tests/test_dubbing_cli_api.py`。
- 校验通过：`uv run python -m unittest tests/test_dubbing_cli_api.py`（24 tests, OK）。

## 2026-04-20 清理无效 speaker_mode 后端入参

- [x] Spec-1 现状分析（带代码出处）
- [x] Spec-2 功能点与精确改动范围
- [x] Spec-3 风险与决策
- [x] HARD-GATE：等用户确认后实施
- [x] 实施：移除 Web start 接口中的 `speaker_mode` 入参、校验与任务字段
- [x] 实施：移除 Web 到 CLI 的 `--speaker-mode` / `--diarization-provider` / `--pyannote-*` 透传
- [x] 实施：移除批次/任务状态里仅为兼容保留的 `speaker_mode` 显示字段
- [x] 实施：清理 `dub_long_video.py` 对 `--speaker-mode` 的采集
- [x] 验证：py_compile + unittest

## Review（2026-04-20 清理无效 speaker_mode 后端入参）
- `src/subtitle_maker/dubbing_cli_api.py` 已移除 Auto Dubbing Web `/start` 接口中的 `speaker_mode` 入参、校验、任务状态字段，以及 `--speaker-mode` / `--diarization-provider` / `--pyannote-*` CLI 透传。
- `src/subtitle_maker/dubbing_cli_api.py` 的 `load-batch` / `_complete_task_from_manifest` 不再把历史 manifest 里的 `speaker_mode` 回显到任务 payload；旧 batch 仍可加载，但新 Web 返回契约已不再暴露这个无效字段。
- `tools/dub_long_video.py` 不再从 extra args 采集 `--speaker-mode`，也不再把 `speaker_mode` 写入新的 `batch_manifest.json`。
- `tests/test_dubbing_cli_api.py` 已同步更新：`load-batch` 用例不再断言 `payload["speaker_mode"]` 存在。
- 校验通过：`uv run python -m py_compile src/subtitle_maker/dubbing_cli_api.py tools/dub_long_video.py tests/test_dubbing_cli_api.py`。
- 校验通过：`uv run python -m unittest tests/test_dubbing_cli_api.py`（`Ran 35 tests ... OK`）。

## 2026-04-20 彻底清理 speaker_mode 历史痕迹（先 2 后 1）

- [x] Task-2 Spec-1：审计前端与返回类型残留（带代码出处）
- [x] Task-2 Spec-2：确认前端与返回类型已无残留，无需继续实施
- [x] Task-2 Spec-3：风险与决策（保持 no-op，避免重复改动）
- [x] Task-2 HARD-GATE：已确认，结论为 no-op
- [x] Task-2 实施：无代码变更
- [x] Task-1 Spec-1：审计 `dub_pipeline.py` 中的历史死参数/死代码（带代码出处）
- [x] Task-1 Spec-2：精确改动范围
- [x] Task-1 Spec-3：风险与决策
- [x] Task-1 HARD-GATE：已确认
- [x] Task-1 实施：清理 `dub_pipeline.py` 的历史 speaker/diarization 死参数与死代码
- [x] 验证：py_compile + unittest

## Review（2026-04-20 彻底清理 speaker_mode 历史痕迹）
- Task-2 结论：前端请求、模板与 Web 返回契约里的 `speaker_mode` 残留此前已清理干净，本轮无需继续改代码。
- `tools/dub_pipeline.py` 已删除残留的多人/diarization 死代码：`extract_multi_speaker_references()`、`build_time_bucket_ref_selector()`、`--speaker-mode`、`--diarization-provider`、`--pyannote-*` 参数，以及对应 manifest 字段与 fallback 逻辑。
- `tools/dub_pipeline.py` 的 grouped/逐句主链路已统一到当前真实语义：固定按字幕时间窗提取逐句原音频参考，不再携带伪 `speaker_mode`/`subtitle_speakers` 分支。
- 残留检查通过：`rg -n "speaker_mode|diarization_provider|pyannote|extract_multi_speaker_references|build_time_bucket_ref_selector" tools/dub_pipeline.py` 无结果；`uv run python tools/dub_pipeline.py --help | rg -n "speaker-mode|diarization|pyannote"` 无结果。
- 校验通过：`uv run python -m py_compile tools/dub_pipeline.py src/subtitle_maker/dubbing_cli_api.py tools/dub_long_video.py tests/test_dubbing_cli_api.py`。
- 校验通过：`uv run python -m unittest tests/test_dubbing_cli_api.py`（`Ran 35 tests ... OK`）。

## 2026-04-19 审阅后局部重配 500 修复（进行中）

- [x] 现状定位：`save-and-redub` 调用链与失败出口梳理
- [x] Spec-1：根因分析与最小修复面确认（等待你确认）
- [x] Spec-2：修复点实现（错误提取、命令参数、状态回写）
- [x] Spec-3：验证（单测 + 最小集成复现）
- [x] Review：记录证据与回归结果

## Review（2026-04-19 审阅后局部重配 500 修复）
- 根因确认：`tools/dub_pipeline.py` 在逐句合成分支会提前构造 `Translator(...)`，即使 `--input-srt-kind translated`（应跳过翻译）也会触发 DeepSeek Key 校验失败。
- 修复：改为按 `allow_rewrite_translation` 惰性初始化 Translator；上传翻译字幕的局部重配不再依赖 DeepSeek Key。
- 可观测性修复：`src/subtitle_maker/dubbing_cli_api.py` 新增 `_compact_process_error_output`，合并 stdout/stderr 并过滤 `flash-attn` 噪音，错误返回真实尾部日志。
- 状态修复：`save-and-redub` 异常时显式 `_set_task(... status=failed ...)`，避免前端“无反应/一直转圈”。
- 回归通过：`uv run python -m py_compile tools/dub_pipeline.py src/subtitle_maker/dubbing_cli_api.py tests/test_dubbing_cli_api.py`。
- 回归通过：`uv run python -m unittest tests/test_dubbing_cli_api.py`（`Ran 32 tests ... OK`）。
- 复现实证：同一条 `--resume-job-dir + --input-srt-kind translated` 命令在无 DeepSeek Key 环境下已从 `exit 1` 变为成功完成（`summary.done=2`）。

## 2026-04-20 Auto Dubbing 审阅问题修复收口

- [x] 恢复并持久化 batch/segment 的关键 pipeline 元数据，避免 load-batch 与 review redub 丢失语义
- [x] 将 save-and-redub 改为可回滚流程，失败时恢复字幕与 manifest，避免字幕先于音频漂移
- [x] 保留原始 segment 合成模式重跑，处理 grouped/V1 的整段重配与参数继承
- [x] 修复 translated 输入、speaker_mode、V2 prosody fallback 与 grouped manual_review 统计问题
- [x] 补充回归测试并执行 py_compile + unittest 验证

## Review（2026-04-20 审阅问题修复收口）
- 已在 `src/subtitle_maker/dubbing_cli_api.py` 恢复 `target_lang`、`pipeline_version`、`rewrite_translation`、`timing_mode`、`grouping_strategy`、`speaker_mode` 等 batch 元数据，load-batch 后的 review redub 不再默认回退到 `Chinese + v1`。
- `save-and-redub` 改为事务式流程：先备份受影响 segment 与 `batch_manifest.json`，只在段内重配和 batch 重拼全部成功后刷新最终字幕；失败时回滚 segment/manifest 并重建 batch 产物。
- `_rerun_segment_with_translated_srt()` 现在会读取 segment manifest 的原始模式；历史 grouped 片段会通过 `group_id/skip_compose` 自动识别，并强制整段重跑，保留原 `grouped_synthesis/force_fit_timing` 语义。
- `tools/dub_pipeline.py` 修复 translated 输入污染 `source.srt`：translated 字幕仅作为时间轴与 TTS 文本，不再覆盖真实源字幕；无源字幕时自动禁用双语输出，避免生成错误的 source/bilingual 产物。
- `tools/dub_pipeline.py` 现在对 `speaker_mode=auto/per-speaker` 显式回退到 `single-speaker` 并记录 requested/effective，避免 API 表面承诺与实际执行不一致。
- V2 逐句候选在参考音频回退到共享 ref 后会刷新 prosody fingerprint，避免继续拿旧参考做候选打分。
- grouped 合成的超阈值/静音失败现在会把整组字幕都标为 `manual_review`，并为每一行写入 `manual_review` 记录，避免 UI 和统计漏报兄弟行。
- 新增回归：`load-batch` 元数据恢复、`save-and-redub` 失败回滚、grouped 片段按原模式整段重跑。
- 校验通过：`uv run python -m py_compile src/subtitle_maker/dubbing_cli_api.py tools/dub_pipeline.py tools/dub_long_video.py tests/test_dubbing_cli_api.py`。
- 校验通过：`uv run python -m unittest tests/test_dubbing_cli_api.py`（`Ran 35 tests ... OK`）。
- [x] 收紧 auto dubbing 表单区布局，去掉固定宽度，确认 Run/Ranges 互换


## Review（2026-04-21 Auto Dubbing 表单区继续压缩）
- `src/subtitle_maker/templates/index.html` 已保持 V1/V2 一致：`Ranges` 位于主配置区右侧，`Run` 下沉到下方支持区左侧，顺序按最新要求互换。
- `src/subtitle_maker/static/style.css` 已去掉 Auto Dubbing 表单区的固定像素列宽与多个硬性最小宽度，改为纯比例伸缩与内容自适应，外层卡片不再被固定宽度撑大。
- 同时压缩了卡片 padding、grid gap、阴影、输入块宽度与范围输入尺寸，目标是降低视觉体积，不增加额外层级。
- 校验通过：`node --check src/subtitle_maker/static/app.js`。
- 校验通过：`uv run python` + `html.parser` 解析 `src/subtitle_maker/templates/index.html`，输出 `html_parse_ok`。

## 2026-04-21 Sidebar 可收起功能

- [x] Spec-1：审计侧边栏结构、主内容联动与响应式约束（带代码出处）
- [x] Spec-2：确认交互方案、状态持久化与精确改动范围
- [x] Spec-3：确认风险、回归点与验证方式
- [x] HARD-GATE：等用户确认后实施
- [x] 实施：添加侧边栏收起/展开
- [x] 验证：前端语法检查 + 关键交互自查


## Review（2026-04-21 Sidebar 可收起功能）
- `src/subtitle_maker/templates/index.html` 已在侧边栏头部加入 `sidebar-toggle-btn`，并把导航文字包成 `nav-label`，这样桌面收起态和现有移动端紧凑态都能稳定控制文字显隐。
- `src/subtitle_maker/static/style.css` 已新增桌面端 `app-layout.sidebar-collapsed` 收起态：侧边栏宽度缩到 `72px`，隐藏 logo 文案、导航文字和 footer；同时保留 `<=768px` 的现有移动端 `60px` 规则。
- `src/subtitle_maker/static/app.js` 已新增 `SIDEBAR_COLLAPSED_KEY` 与 `applySidebarCollapsed()`，通过 `localStorage` 记住用户上次选择，并同步更新 toggle 的 `aria-expanded` / `aria-label`。
- 现有导航主链路未改动：`navButtons -> panel` 切换逻辑保持原样，仅新增侧边栏外观状态。
- 校验通过：`node --check src/subtitle_maker/static/app.js`。
- 校验通过：`uv run python` + `html.parser` 解析 `src/subtitle_maker/templates/index.html`，输出 `html_parse_ok`。

## 2026-04-21 合并短句按时间窗实现

- [x] Spec-1：阅读文档并审计第2步合并短句现状、失效原因与代码出处
- [x] Spec-2：确认按时间窗合并的规则、参数和精确改动范围
- [x] Spec-3：确认风险、边界和验证方式
- [x] HARD-GATE：等用户确认后实施
- [x] 实施：将第2步合并短句改为按时间窗估算
- [x] 验证：语法检查 + 单测/样例回归

## Review（2026-04-21 合并短句按时间窗实现）
- `tools/dub_pipeline.py` 已把第 2 步短句合并从“按字数阈值”改成“按时间窗目标”执行：`source_short_merge_tolerance_seconds()` 按文档公式计算 `round(target / 3)`，`merge_short_source_subtitles()` 统一用毫秒比较目标窗口、相邻 gap 与长字幕硬边界。
- 新合并逻辑严格遵守文档约束：只从当前字幕向后连续吸收相邻句；单条时长 `> target` 直接保留；遇到相邻 gap `> 1.5s` 强制断开；候选选择顺序为“合法窗口优先、句尾更自然、离目标更近、同分略偏短”。
- `rebalance_source_subtitles()` 现在把第 2 步视为独立时间窗合并阶段，只在 `source_short_merge_enabled=true` 时执行，并固定使用 `DEFAULT_SOURCE_SHORT_MERGE_GAP_SEC=1.5`，不再错误复用第 1 步的 `asr_balance_gap_sec`。
- 上传 `source.srt` 与 ASR 识别两条入口已统一复用同一套时间窗合并链路；`src/subtitle_maker/dubbing_cli_api.py`、`src/subtitle_maker/static/app.js`、`src/subtitle_maker/templates/index.html`、`tools/dub_long_video.py` 也已同步把 `short_merge_threshold` 的语义改为“target seconds”，默认 `15`，并持久化 `source_short_merge_threshold_mode=\"seconds\"` 以兼容历史 batch。
- 历史 batch 兼容已补上：`_normalize_short_merge_target_seconds_for_display()` 会把旧字符阈值（例如 `50/64`）识别为旧语义并在 UI 中回退到默认 `15s`，避免加载旧批次后显示异常秒数。
- 新增/更新回归覆盖：
  `tests/test_dub_pipeline_asr_layout.py` 覆盖自然断点优先、跨 1.0s 停顿仍可合并、`>1.5s` 强制断开、长字幕硬边界、默认关闭不合并、上传 `source.srt` 复用时间窗合并；
  `tests/test_dubbing_cli_api.py` 覆盖默认值、自定义秒数透传、非法秒数拒绝、旧 batch 阈值回退。
- 校验通过：`node --check src/subtitle_maker/static/app.js`。
- 校验通过：`uv run python -m py_compile src/subtitle_maker/dubbing_cli_api.py tools/dub_pipeline.py tools/dub_long_video.py tests/test_dub_pipeline_asr_layout.py tests/test_dubbing_cli_api.py`。
- 回归通过：`uv run python -m unittest tests/test_dub_pipeline_asr_layout.py`（`Ran 11 tests ... OK`）。
- 回归通过：`uv run python -m unittest tests/test_dubbing_cli_api.py`（`Ran 39 tests ... OK`）。

## 2026-04-21 配音稳定性优化（同一人音色/语气一致）

- [x] Spec-1：审计当前参考音频、候选筛选、翻译改写、时长拟合链路，定位稳定性漂移来源（带代码出处）
- [ ] Spec-2：确认稳定性优化策略与最小改动范围
- [ ] Spec-3：确认风险、开关和验证方式
- [ ] HARD-GATE：等用户确认后实施
- [ ] 实施：按确认方案优化同一人跨句稳定性
- [ ] 验证：语法检查 + 定向回归 + 样例复核

## 2026-04-21 TTS 底座横向调研（Index-TTS / Qwen3-TTS / VoxCPM / OmniVoice）

- [x] 审阅本地 Index-TTS、Qwen3-TTS、VoxCPM、OmniVoice 仓库说明与当前项目接入现状
- [x] 提炼各模型在音色稳定、情绪控制、时长控制、克隆方式、推理速度上的关键差异
- [x] 结合当前自动配音目标，给出适配度排序与下一步建议

## Review（2026-04-21 TTS 底座横向调研）
- 已新增决策记录文档 [docs/tts-backend-selection-20260421.md](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/docs/tts-backend-selection-20260421.md)，集中记录当前项目实际接入现状、四个底座的横向比较、排序与最终结论。
- 结论已固定：`Index-TTS` 继续作为主底座，`OmniVoice` 作为第二备胎，`Qwen3-TTS` 暂不进入当前主线，`VoxCPM` 不适合当前自动配音目标。
- 已在 [docs/dubbing_pipeline_prd_v0.md](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/docs/dubbing_pipeline_prd_v0.md) 第 0 节补充跳转说明，避免后续只看 PRD 时遗漏这次选型结论。

## 2026-04-21 OmniVoice 第二备胎接入（隔离 backend）

- [x] Spec-1：审计当前 TTS 接线点、失败回退点、OmniVoice 依赖约束与可接入边界（带代码出处）
- [x] Spec-2：确认“第二备胎”的触发规则、隔离形态与精确改动范围
- [x] Spec-3：确认风险、兼容性、验证方式与回退策略
- [x] HARD-GATE：等用户确认后实施
- [x] 实施：接入 OmniVoice 作为第二备胎
- [x] 验证：语法检查 + 定向回归 + 备胎触发样例复核
- [x] 过程约束：实现进行中同步更新 `todo/lessons`，按阶段记录，不后补

## Review（2026-04-21 OmniVoice 第二备胎接入 Spec-2）
- 触发规则已收敛：第一版只把 `OmniVoice` 作为 `index-tts` 的“硬失败备胎”，即仅在 `index-tts` 最终抛出 `E-TTS-001` 或产出无效音频时触发；纯时长偏差、manual_review、候选打分偏弱都不切到备胎，避免把主链路音色稳定性主动让给更弱约束的模型。
- 隔离形态已固定：不把 `OmniVoice` 直接 import 进主工程，而是通过外部 Python 进程执行 `python -m omnivoice.cli.infer`；原因是主工程锁 `torch/torchaudio 2.3.1`，而 `OmniVoice` 锁 `torch/torchaudio 2.8.* + transformers 5.3.0`，同进程不可接受。
- 最小实现范围已固定：
  `tools/dub_pipeline.py` 增加 `fallback_tts_backend=none|omnivoice` 与 `omnivoice_root / omnivoice_python_bin / omnivoice_model / omnivoice_device` 参数，新增 `synthesize_via_omnivoice_cli()`，并在 `synthesize_text_once()` 与逐句合成回路中把源字幕文本作为 `ref_text` 传给 `OmniVoice`，避免备胎内部再跑 ASR。
- 透传与持久化范围已固定：
  `src/subtitle_maker/dubbing_cli_api.py` 的启动任务、load-batch、save-and-redub 都要恢复并透传 `tts_backend / fallback_tts_backend / omnivoice_*` 元数据；
  `tools/dub_long_video.py` 的 batch manifest 也要写入同一组字段，保证历史任务回放和 review redub 不丢备胎配置。
- 第一版明确不做：
  不新增前端 backend 选择控件；
  不放开当前 Web 的 `index-tts` 语种拦截；
  不改 `repair_bad_segments.py` 的 TTS 逻辑；
  先把备胎能力收敛在主自动配音与 review redub 两条主链路。

## Review（2026-04-21 OmniVoice 第二备胎接入 Spec-3）
- 第一版接受的风险已固定：`OmniVoice` 通过外部 CLI 进程调用时，每次 fallback 都会重新加载模型，单次延迟明显高于主链路；但由于触发条件被限定为 `index-tts` 的硬失败备胎，这个额外时延是可接受的，不为此提前做常驻服务化。
- 第一版不接受的风险已固定：不能因为接入备胎破坏现有失败口径。`tools/dub_pipeline.py` 现有逐句门禁会把“静音/过短音频”记成 `E-TTS-002` 并继续现有重试/人工复核路径；`build_failure_manifest()` 与 `dubbing_cli_api._complete_task_from_manifest()` 也已经约定了“全量 manual_review 视为失败”的状态恢复规则，备胎必须复用这套语义，不能私自吞错或把失败伪装成完成。
- 参考文本策略已固定：调用 `OmniVoice` 时必须显式传入当前句的源字幕文本作为 `ref_text`。因为 `OmniVoice` 在缺失 `ref_text` 时会自行转录 `ref_audio`，这会把备胎链路重新暴露给 ASR 漂移；第一版不接受这种额外不确定性。
- 兼容性边界已固定：Web 启动链路仍会先做 `index-tts` 健康检查和当前语种拦截，因此第一版备胎只解决“运行中 TTS 硬失败”，不解决“启动前 index 服务未就绪”或“非中英文目标语种被前端拦截”的问题；这两个问题若要放开，必须单独立项。
- 默认回退策略已固定：新增字段默认都应保持关闭，即 `fallback_tts_backend=none`；未配置 `omnivoice_python_bin` / `omnivoice_root` / `omnivoice_model` 时，不做隐式猜测启动，不做自动安装，也不退化到其它未知 backend。
- 错误展示策略已固定：若 `index-tts` 失败后 `OmniVoice` 也失败，最终错误信息必须同时保留主失败与备胎失败摘要，便于 review redub 和 batch 回放定位真实原因，而不是只剩最后一次外部进程报错。
- 验证口径已固定：
  1) `tests/test_dubbing_cli_api.py` 增加启动参数透传、load-batch 元数据恢复、save-and-redub 保留 fallback 配置的断言；
  2) 为 `tools/dub_pipeline.py` 增加定向单测，覆盖“主 backend 失败后触发 OmniVoice”、“无效音频触发备胎”、“非硬失败不触发备胎”、“备胎再次失败时错误聚合”；
  3) 保持现有 `py_compile` 与 `tests/test_dubbing_cli_api.py` 回归口径不退化；
  4) 最后做 1 条手工 smoke：使用可控坏输入或 mock forcing，让 `index-tts` 失败一次，确认 segment manifest / batch manifest / review redub 都能观测到备胎生效。

## Review（2026-04-27 OmniVoice 第二备胎接入实施）
- `src/subtitle_maker/backends/omni_voice.py` 已从占位实现升级为可运行 backend：通过外部 Python 进程执行 `python -m omnivoice.cli.infer`，支持 `model / ref_audio / ref_text / language / device` 参数，并统一报错为 `E-TTS-001` 语义。
- `src/subtitle_maker/domains/dubbing/pipeline.py` 已接入主备调度：`synthesize_text_once()` 先跑主 backend，失败后按 `fallback_tts_backend` 切 `omnivoice`；若主备都失败会聚合错误摘要。逐句链路新增“无效音频后直切备胎一次”逻辑，grouped 链路在静音重试阶段会优先改用备胎 backend。
- `tools/dub_pipeline.py` 已新增并校验参数：`--fallback-tts-backend`、`--omnivoice-root`、`--omnivoice-python-bin`、`--omnivoice-model`、`--omnivoice-device`；当 fallback=omnivoice 时会校验必填路径/模型。
- `src/subtitle_maker/jobs/command_builder.py`、`src/subtitle_maker/dubbing_cli_api.py`、`src/subtitle_maker/domains/dubbing/review.py` 已打通启动与 review-redub 透传，`load-batch` 回填后可继续保持相同 fallback 配置。
- `src/subtitle_maker/manifests/schema.py` 与 `src/subtitle_maker/manifests/readwrite.py` 已扩展 replay 字段：`fallback_tts_backend` + `omnivoice_*`，并在 batch/segment 成功与失败 manifest 都持久化。
- `tools/dub_long_video.py` 已移除 `tts_backend="index-tts"` 硬编码，改为从透传参数写入 batch manifest（含 fallback 配置）。
- 验证通过：
  - `uv run python -m compileall -q src/subtitle_maker tools tests`
  - `uv run python -m unittest tests.test_command_builder tests.test_manifest_contracts tests.test_dubbing_runtime tests.test_dubbing_cli_api`（`Ran 63 tests ... OK`）

## 2026-04-21 长视频上传字幕空分段崩溃修复

- [x] 定位 `dub_long_video.py exited with code 1` 的真实根因
- [x] 实施：空字幕分段跳过 + 全时轴合并回退
- [x] 验证：定向单测 + 现有 API 回归

## Review（2026-04-21 长视频上传字幕空分段崩溃修复）
- 根因已定位：上传 `input_srt` 时，`tools/dub_long_video.py` 会先按 segment 裁字幕；若某个 segment 没有任何重叠字幕，仍会把空 `_input_segment.srt` 传给 `tools/dub_pipeline.py`，后者在 `load_or_transcribe_subtitles()` 后直接抛出 `E-ASR-001 no subtitles produced`，最终表现为整批 `dub_long_video.py exited with code 1`。
- `tools/dub_long_video.py` 现在对这类 segment 直接写入最小 `manifest.json` 并标记 `status=skipped`，不再调用 `run_segment_job()`；同时会清空该 segment 旧目录，避免历史残留的 `source.srt / translated.srt / dubbed_vocals.wav` 被后续 merge 误收。
- 全量模式下的最终合并也已加回退：如果不是每个 segment 都有完整产物，不再硬要求 `len(all_vocals) == len(results)` 才能出最终音频，而是自动退回 `build_full_timeline_vocals()/build_full_timeline_bgm()`，让空字幕段在整轨中保持静音空洞，不再整批失败。
- 双语字幕合并条件已放宽为“译文输入数 == 原文输入数”，不再错误要求必须等于 segment 总数；因此上传字幕只覆盖部分视频时，仍然能得到正确的 `source_full.srt / translated_full.srt / dubbed_final_full.srt`。
- 校验通过：`uv run python -m py_compile tools/dub_long_video.py tests/test_dub_long_video.py src/subtitle_maker/dubbing_cli_api.py tests/test_dubbing_cli_api.py`。
- 回归通过：`uv run python -m unittest tests.test_dub_long_video`（`Ran 1 test ... OK`）。
- 回归通过：`uv run python -m unittest tests.test_dubbing_cli_api`（`Ran 39 tests ... OK`）。

## 2026-04-24 产品化重构文档 Phase 0

- [x] 创建 `docs/refactor/00-product-principles.md`
- [x] 创建 `docs/refactor/01-current-architecture-review.md`
- [x] 创建 `docs/refactor/02-mvp-scope.md`
- [x] 创建 `docs/refactor/03-target-architecture.md`
- [x] 创建 `docs/refactor/04-data-contracts.md`
- [x] 创建 `docs/refactor/05-migration-roadmap.md`
- [x] 创建 `docs/refactor/06-agent-entry-v1.md`
- [x] Review 1：确认产品原则和 MVP 范围
- [x] Review 2：确认目标架构和数据协议
- [x] Review 3：确认迁移路线和 Agent V1
- [x] 最终确认后进入代码实现阶段

## 2026-04-24 Agent V1 实现

- [x] 新增 OpenAI-compatible LLM client
- [x] 新增 `/api/agent/chat` 后端接口
- [x] Web app include Agent router
- [x] 新增右下角 Agent 浮动抽屉
- [x] 新增 Agent 前端交互逻辑
- [x] 新增 Agent API 单测
- [x] 验证：py_compile
- [x] 验证：Agent API 单测
- [x] 验证：现有 Auto Dubbing API 回归

## Review（2026-04-24 Agent V1 实现）
- 已新增 `src/subtitle_maker/core/llm_client.py`，提供 OpenAI-compatible chat client；API key 只在内存使用，缺失/401/超时/provider 错误映射为 `E-AGENT-*`。
- 已新增 `src/subtitle_maker/agent_api.py` 并在 `src/subtitle_maker/web.py` include `/api/agent/chat`；Agent V1 只提供使用帮助和错误解释，不读取本地 manifest，不执行项目操作。
- 已在 `src/subtitle_maker/templates/index.html`、`src/subtitle_maker/static/app.js`、`src/subtitle_maker/static/style.css` 添加右下角 Agent 浮动抽屉，前端状态使用 `agent-*` 前缀隔离，API key 不写入 localStorage/sessionStorage。
- 已新增 `tests/test_agent_api.py`，覆盖空消息、缺 key、正常 JSON 回复、禁止执行 prompt 边界和 provider 401 映射。
- 校验通过：本次修改文件 `py_compile`。
- 校验通过：`node --check src/subtitle_maker/static/app.js`。
- 校验通过：`html.parser` 解析 `src/subtitle_maker/templates/index.html`，输出 `html_parse_ok`。
- 回归通过：`uv run python -m unittest tests.test_agent_api`（`Ran 5 tests ... OK`）。
- 回归通过：`uv run python -m unittest tests.test_dubbing_cli_api`（`Ran 39 tests ... OK`）。
- 回归通过：`uv run python -m unittest tests.test_dub_pipeline_asr_layout`（`Ran 11 tests ... OK`）。
- 回归通过：`uv run python -m unittest tests.test_dub_long_video`（`Ran 1 test ... OK`）。
- 完整 `compileall` 未作为完成标准：它被既有 `src/subtitle_maker/simple_web.py` 语法错误阻断（`endswith(.srt)`），本次未顺手修改旧入口。

## 2026-04-24 Contract / Golden Tests 补强

- [x] 新增 manifest contract 单测
- [x] 补强 batch manifest replay 字段断言
- [x] 验证：新增 contract tests
- [x] 验证：长视频回归

## 2026-04-24 协议层收口（Manifest Reader + Command Builder）

- [x] 实施：新增统一 manifest 读取层并兼容历史字段
- [x] 实施：`dubbing_cli_api.py` load-batch / review redub 切到统一 manifest reader
- [x] 实施：抽离 Auto Dubbing 启动与 review redub 的 command builder
- [x] 实施：`dub_long_video.py` 的 batch/skipped manifest 读写切到统一 manifests 模块
- [x] 实施：`dub_pipeline.py` 的 success/failure segment manifest 切到统一 manifests 模块
- [x] 实施：新增 `TaskStore` 薄层并把 auto dubbing 任务访问切到 store
- [x] 验证：manifest reader 回归 + CLI 参数回归

## Review（2026-04-24 Contract / Golden Tests 补强）
- 已新增 `tests/test_manifest_contracts.py`，冻结 `tools/dub_pipeline.py` 的成功 manifest、失败 manifest，以及 `tools/dub_long_video.py` 的 skipped segment manifest 关键合约，重点覆盖 `target_lang`、`pipeline_version`、short merge、grouped/force-fit、time ranges、paths、stats` 等 replay 关键字段。
- 已补强 `tests/test_dub_long_video.py`，额外锁定 batch manifest 中的 `pipeline_version`、`source_short_merge_threshold_mode`、`grouped_synthesis`、`force_fit_timing` 等字段，防止后续抽 schema/command builder 时悄悄漂移。
- 校验通过：`uv run python -m py_compile tests/test_manifest_contracts.py tests/test_dub_long_video.py`。
- 回归通过：`uv run python -m unittest tests.test_manifest_contracts`（`Ran 3 tests ... OK`）。
- 回归通过：`uv run python -m unittest tests.test_dub_long_video`（`Ran 1 test ... OK`）。

## Review（2026-04-24 协议层收口：Manifest Reader + Command Builder）
- 已新增 `src/subtitle_maker/manifests/schema.py` 与 `src/subtitle_maker/manifests/readwrite.py`，把 batch/segment manifest 的 replay 配置统一收口为 `BatchReplayOptions`，并兼容历史 `target_lang / pipeline_version / source_short_merge_* / grouped_synthesis / force_fit_timing / time_ranges` 字段缺失或旧格式。
- `src/subtitle_maker/dubbing_cli_api.py` 的 load-batch、artifact 解析、review lines 收集、save-and-redub、segment re-dub 已切到统一 manifest reader，不再各处手写 `json.loads(...).get(...)` 默认值。
- 已新增 `src/subtitle_maker/jobs/command_builder.py`，统一生成 Auto Dubbing 启动命令和 review redub 命令；`dubbing_cli_api.py` 不再直接拼长串 `cmd.extend(...)`，后续接 `PipelineOptions` / fallback backend 时改动面会更小。
- 单段重配命令现在会优先恢复 segment manifest 中记录的 `tts_backend` 与 `index_tts_api_url`；若历史 manifest 没有字段，仍回退到当前入参，兼容旧批次。
- `tools/dub_long_video.py` 的 skipped segment manifest 和 batch manifest 现在统一通过 `src/subtitle_maker/manifests/readwrite.py` 构建/落盘；同时 segment manifest 的复用扫描、结果回收也切到 `load_segment_manifest()`，减少裸 `json.loads(...)`。
- batch manifest 现在同时写出旧字段 `requested_ranges / effective_ranges` 和标准化字段 `requested_time_ranges / effective_time_ranges`，为后续完全切到 typed schema 留兼容桥。
- 已新增 `tests/test_command_builder.py`，覆盖 V2 参数、time ranges、grouped/full rerun、局部 redub line indices 等 command builder 关键行为；`tests/test_dubbing_cli_api.py` 也新增了 segment manifest backend/url 恢复断言。
- 校验通过：`uv run python -m py_compile src/subtitle_maker/jobs/__init__.py src/subtitle_maker/jobs/command_builder.py src/subtitle_maker/dubbing_cli_api.py tests/test_command_builder.py tests/test_dubbing_cli_api.py`。
- 回归通过：`uv run python -m unittest tests.test_command_builder`（`Ran 3 tests ... OK`）。
- 回归通过：`uv run python -m unittest tests.test_dubbing_cli_api`（`Ran 40 tests ... OK`）。
- 回归通过：`uv run python -m unittest tests.test_manifest_contracts`（`Ran 5 tests ... OK`）。
- 继续回归通过：`uv run python -m py_compile src/subtitle_maker/manifests/__init__.py src/subtitle_maker/manifests/readwrite.py tools/dub_long_video.py tests/test_dub_long_video.py tests/test_manifest_contracts.py`。
- 继续回归通过：`uv run python -m unittest tests.test_dub_long_video`（`Ran 1 test ... OK`）。
- 继续回归通过：`uv run python -m unittest tests.test_manifest_contracts`（`Ran 6 tests ... OK`）。
- `tools/dub_pipeline.py` 的 `build_manifest()` / `build_failure_manifest()` 现已变成薄封装，底层统一调用 `src/subtitle_maker/manifests/readwrite.py` 的 segment manifest builder；`resume_job_dir` 读取旧 manifest 也切到 `load_segment_manifest()`，不再直接 `json.loads(...)`。
- 本轮中途捕获并修复了一次真实协议回归：最初迁移时漏掉了 segment manifest 的 `range_strategy` 字段，`tests/test_manifest_contracts.py` 立即报错；已在统一 builder 中补回，说明 contract tests 的护栏有效。
- 再次校验通过：`uv run python -m py_compile src/subtitle_maker/manifests/__init__.py src/subtitle_maker/manifests/readwrite.py tools/dub_pipeline.py tests/test_manifest_contracts.py tests/test_dubbing_cli_api.py`。
- 再次回归通过：`uv run python -m unittest tests.test_manifest_contracts`（`Ran 6 tests ... OK`）。
- 再次回归通过：`uv run python -m unittest tests.test_dubbing_cli_api`（`Ran 40 tests ... OK`）。
- 再次回归通过：`uv run python -m unittest tests.test_dub_long_video`（`Ran 1 test ... OK`）。
- 已新增 `src/subtitle_maker/jobs/store.py` 与 `src/subtitle_maker/jobs/models.py`，先以 `RLock + in-memory dict` 形式提供 `TaskStore` 薄层，不改变当前内存存储语义，但把“创建/查询/更新/活跃任务扫描”从 `dubbing_cli_api.py` 的裸 `_tasks` 访问中抽出来。
- `src/subtitle_maker/dubbing_cli_api.py` 现已通过 `TaskStore` 处理任务 ID 冲突检查、任务创建、状态读取、stdout tail 累积、活跃任务扫描等高频路径；同时保留 `_tasks` 兼容别名，避免现有测试和少量旧代码立即断裂。
- 新增 `tests/test_task_store.py`，覆盖 `create/get/get_copy`、终态过滤、snapshot 拷贝语义。
- 继续校验通过：`uv run python -m py_compile src/subtitle_maker/jobs/models.py src/subtitle_maker/jobs/store.py src/subtitle_maker/jobs/__init__.py src/subtitle_maker/dubbing_cli_api.py tests/test_task_store.py tests/test_dubbing_cli_api.py`。
- 继续回归通过：`uv run python -m unittest tests.test_task_store`（`Ran 3 tests ... OK`）。
- 继续回归通过：`uv run python -m unittest tests.test_dubbing_cli_api`（`Ran 40 tests ... OK`）。

## Review（2026-04-24 产品化重构文档 Phase 0）
- 已按计划新增 `docs/refactor/` 分阶段文档，先覆盖产品原则、当前架构审计、MVP 范围、目标架构、数据协议、迁移路线和 Agent V1。
- 当前阶段只落文档，不改业务代码、不实现 Agent，符合“先写文档，review 几次后再实现”的要求。
- 后续应先逐份 review 文档，再进入 contract tests 和 Agent V1 实现。

## Review（2026-04-24 产品化重构文档 Review 1）
- 已审阅并更新 `docs/refactor/00-product-principles.md`：补充第一阶段产品成功指标和决策门槛，避免重构滑向纯工程洁癖。
- 已审阅并更新 `docs/refactor/02-mvp-scope.md`：补充用户卡住时的 Agent 辅助链路、关键用户场景、Agent V1 必须覆盖的常见问题。
- Review 1 结论：第一阶段只优化“完成一次自动配音”的闭环体验；账号、收费、多租户、自动说话人识别、前端框架迁移不进入第一阶段。

## Review（2026-04-24 产品化重构文档 Review 2）
- 已审阅并更新 `docs/refactor/03-target-architecture.md`：补充数据流和所有权、编排边界、兼容层策略，明确协议优先于拆文件。
- 已审阅并更新 `docs/refactor/04-data-contracts.md`：将 `PipelineOptions` 拆为 `SubtitleLayoutOptions / TranslationOptions / DubbingOptions / TtsOptions / TimeRange`，覆盖会影响重跑语义的字段。
- Review 2 结论：`target_lang`、`pipeline_version`、字幕 layout、翻译配置、合成模式、TTS backend、time ranges 都属于可重放配置，必须进入 typed options 或 manifest，不能继续依赖当前默认值。

## Review（2026-04-24 产品化重构文档 Review 3）
- 已审阅并更新 `docs/refactor/05-migration-roadmap.md`：把 Agent V1 提前到文档 review 后的第一批实现阶段，再进入 contract/golden tests 和协议层重构。
- 已审阅并更新 `docs/refactor/06-agent-entry-v1.md`：明确第一版实现位置为 `src/subtitle_maker/agent_api.py` + `core/llm_client.py`，前端以 `agent-*` 前缀隔离，后续再迁到 `app/routes/agent.py`。
- Review 3 结论：Agent V1 是独立、低风险、直接提升自用体验的产品增量；第一版只提供使用帮助和错误解释，不读取本地 manifest，不执行任务，不改变上传/翻译/配音主链路。

## 2026-04-24 产品化重构 Phase 5（Subtitle Domain）

- [x] Spec-1：审计当前字幕领域链路、可抽取边界与代码出处
- [x] Spec-2：确认 `domains/subtitles/*` 模块划分、迁移顺序与精确改动范围
- [x] Spec-3：确认风险、兼容层、验证方式与回退策略
- [x] HARD-GATE：等用户确认后实施
- [x] 实施：抽 Subtitle Domain 并接入旧入口
- [x] 验证：语法检查 + golden/回归测试

## Review（2026-04-24 产品化重构 Phase 5 Spec-1）
- 当前 source 字幕入口仍集中在 `tools/dub_pipeline.py::load_or_transcribe_subtitles()`：它统一处理 ASR 与上传 `input_srt`，并在 `persist_input_srt_to_source=True` 时把上传 `source.srt` 也送进 `rebalance_source_subtitles()`，说明“ASR 与上传 source 同链路”这个产品约束已经在单一入口成立。
- 字幕时间重估与标点拆分能力已在 `tools/dub_pipeline.py::allocate_text_segment_times()`、`split_text_on_punctuation_boundaries()`、`split_subtitle_item_by_punctuation()`、`split_cluster_into_punctuation_blocks()` 中成型；这些函数只依赖字幕文本/时间数据，不依赖 TTS、ffmpeg 或 Web 状态，适合优先下沉为纯字幕领域模块。
- 句级分句主规则目前集中在 `tools/dub_pipeline.py::split_oversized_asr_sentence_block()`：策略已固定为“先句号/问号/感叹号，再在句子偏长时允许逗号软切”，并通过 `choose_asr_sentence_split_index()`、`has_internal_explicit_break_boundary()` 保证切点仍落在原 cue 边界。
- 第 2 步短句合并已在 `tools/dub_pipeline.py::merge_short_source_subtitles()` 独立成“仅向后连续吸收相邻短句”的时间窗算法；`source_short_merge_tolerance_seconds()` 固化了文档公式 `round(target / 3)`，这部分也适合单独抽成 `short_merge.py`。
- 当前顶层编排仍收束在 `tools/dub_pipeline.py::rebalance_source_subtitles()`：它负责 gap clustering、句块拆分、LLM 兜底、短句合并与最终 `source.srt` 重建。这说明 Phase 5 最合理的切法不是重写入口，而是先把纯规则函数迁到 `domains/subtitles/`，再让 `rebalance_source_subtitles()` 变成薄编排层。
- 现有 contract/golden 护栏已具备：`tests/test_dub_pipeline_asr_layout.py` 锁定了 ASR 分句、上传 source 字幕复用、短句合并与非法 LLM 计划回退；因此 Phase 5 可以以“不改行为、只搬实现”为主目标推进。

## Review（2026-04-24 产品化重构 Phase 5 Spec-2）
- 第一轮模块划分收敛为 5 个文件，但只实现其中 4 个纯规则模块，暂不新建 `asr.py`：
  `src/subtitle_maker/domains/subtitles/timeline.py` 负责 `allocate_text_segment_times()` 这类时间重估；
  `sentence_split.py` 负责标点拆分、gap clustering、句块切分、超长句二次拆分；
  `short_merge.py` 负责 `source_short_merge_tolerance_seconds()`、`merge_short_source_subtitles()` 和候选评分；
  `srt.py` 第一轮只提供轻量类型/重建辅助（如 `build_rebalanced_subtitle()` 一类与字幕项重建直接相关的纯函数）；
  `asr.py` 暂不落地，因为当前 `load_or_transcribe_subtitles()` 同时依赖 `SubtitleGenerator`、音频时长、时间戳修复与 logger，第一轮强拆会把“字幕领域拆分”扩大成 ASR 编排重构。
- 迁移顺序固定为：
  1) 先抽 `timeline.py` 与 `sentence_split.py`；
  2) 再抽 `short_merge.py`；
  3) 最后在 `tools/dub_pipeline.py::rebalance_source_subtitles()` 中改为调用新模块；
  保持 `tools/dub_pipeline.py::load_or_transcribe_subtitles()` 入口和参数签名不变。这样能把风险限制在“函数搬家 + import 切换”，不碰 ASR/上传字幕入口行为。
- 首轮精确改动范围固定如下：
  `tools/dub_pipeline.py` 只允许做三类修改：导入新模块、删除被迁走的纯函数定义、保留 `rebalance_source_subtitles()` / `load_or_transcribe_subtitles()` 作为旧入口薄层；
  新增目录 `src/subtitle_maker/domains/subtitles/` 及其 `__init__.py`；
  `tests/test_dub_pipeline_asr_layout.py` 仅在必要时补充 import 路径或新增对外 contract 断言，不重写已有 case。
- 明确不进入首轮范围的内容：
  不改 `load_or_transcribe_subtitles()` 的职责；
  不新建 typed subtitle dataclass；
  不调整 LLM hybrid 触发策略；
  不把 translated layout reflow（`smart_layout_translated_lines()`）并入本轮 Subtitle Domain；
  因为这些要么涉及翻译/TTS 语义，要么会放大迁移面，不符合“旧入口先调用新模块”的路线。
- 对外 contract 继续以现有 4 个稳定入口为准：
  `tools/dub_pipeline.py::load_or_transcribe_subtitles()`、
  `rebalance_source_subtitles()`、
  `merge_short_source_subtitles()`、
  `split_oversized_asr_sentence_block()`；
  其中后 3 个已被 `tests/test_dub_pipeline_asr_layout.py` 直接调用，说明第一轮迁移后仍需在 `tools/dub_pipeline.py` 保留这些兼容导出，避免测试和旧调用方立刻断裂。

## Review（2026-04-24 产品化重构 Phase 5 Spec-3）
- 第一风险是“搬家时行为微漂移”，尤其集中在 3 类规则：
  1) `tools/dub_pipeline.py::split_oversized_asr_sentence_block()` 的“句号优先，过长再逗号软切”；
  2) `tools/dub_pipeline.py::merge_short_source_subtitles()` 的“仅向后连续吸收，不反向拆句”；
  3) `tools/dub_pipeline.py::load_or_transcribe_subtitles()` 对上传 `source.srt` 与 ASR 共用 `rebalance_source_subtitles()`；
  因此第一轮迁移不得改参数默认值、不得改函数签名、不得顺手改评分逻辑，只允许把实现移动到新模块后由旧函数转调。
- 第二风险是循环依赖与工具脚本可执行性：
  `tools/dub_pipeline.py` 目前是脚本入口，若新模块反向 import `dub_pipeline.py` 或依赖其中的重对象，就会把简单“领域下沉”演变成启动时循环依赖；
  因此新 `domains/subtitles/*` 只能接收基础字幕数据、纯标量配置和必要 helper，不能反向依赖 CLI 主流程、logger 实例工厂、TTS/翻译实现。
- 第三风险是测试护栏只锁住了主行为，没有锁住所有导出路径；
  所以首轮验证必须同时覆盖：
  `uv run python -m py_compile src/subtitle_maker/domains/subtitles/__init__.py src/subtitle_maker/domains/subtitles/*.py tools/dub_pipeline.py tests/test_dub_pipeline_asr_layout.py`
  `uv run python -m unittest tests.test_dub_pipeline_asr_layout`
  如有必要，再补 `tests.test_dubbing_cli_api` 最小回归，确认上传 `source.srt` 入口未被 import 迁移误伤。
- 兼容层策略固定为“双层保留”：
  新模块承接真实实现；
  `tools/dub_pipeline.py` 保留原函数名作为兼容 facade；
  这样即使后续还未全量切到 `domains/subtitles/*`，现有测试、脚本入口和其他旧调用方也不需要同轮批量改 import。
- 回退策略固定为“函数级回退”，不是全仓回退：
  若某个新模块接线后出现行为漂移，只回退 `tools/dub_pipeline.py` 对该模块的调用，恢复原地实现；
  不动已验证通过的其他模块迁移，避免把 Subtitle Domain 拆分重新打回起点。
- HARD-GATE 前的结论：
  这轮实现应被视为“协议层之后的第一批纯规则下沉”，目标是减薄 `tools/dub_pipeline.py`，不是引入新能力；
  只有在你明确确认后，才进入代码实现。

## Review（2026-04-24 产品化重构 Phase 5 实施）
- 已新增 `src/subtitle_maker/domains/subtitles/`，首轮落地 4 个纯规则模块：`srt.py`、`timeline.py`、`sentence_split.py`、`short_merge.py`；其中 `srt.py` 承接字幕组文本/时长/句末判断等轻量 helper，避免新模块反向依赖 `tools/dub_pipeline.py`。
- `tools/dub_pipeline.py` 现已把 `allocate_text_segment_times()`、`split_text_on_punctuation_boundaries()`、`split_subtitle_item_by_punctuation()`、`build_asr_gap_clusters()`、`split_oversized_asr_sentence_block()`、`merge_short_source_subtitles()`、`source_short_merge_tolerance_seconds()` 等函数改为兼容 facade，旧函数名、参数签名和测试入口保持不变。
- `rebalance_source_subtitles()` 与 `load_or_transcribe_subtitles()` 仍保留在 `tools/dub_pipeline.py` 作为旧入口薄层，没有改职责，也没有顺手迁移 ASR 编排、translated layout 或 LLM hybrid 策略，符合本轮“只下沉纯规则”的约束。
- 新模块没有反向 import `dub_pipeline.py`、`Translator`、`JsonlLogger` 或 TTS/ffmpeg 逻辑；当前领域层仍然只接收基础字幕数据和标量配置，避免循环依赖。
- 校验通过：`uv run python -m py_compile src/subtitle_maker/domains/__init__.py src/subtitle_maker/domains/subtitles/__init__.py src/subtitle_maker/domains/subtitles/srt.py src/subtitle_maker/domains/subtitles/timeline.py src/subtitle_maker/domains/subtitles/sentence_split.py src/subtitle_maker/domains/subtitles/short_merge.py tools/dub_pipeline.py tests/test_dub_pipeline_asr_layout.py`。
- 回归通过：`uv run python -m unittest tests.test_dub_pipeline_asr_layout`（`Ran 11 tests ... OK`）。
- 最小 API 回归通过：`uv run python -m unittest tests.test_dubbing_cli_api`（`Ran 40 tests ... OK`）。

## 2026-04-24 产品化重构 Phase 6（Media Domain）

- [x] Spec-1：审计当前媒体处理链路、重复实现与代码出处
- [x] Spec-2：确认 `core/ffmpeg.py` 与 `domains/media/*` 模块划分、迁移顺序与精确改动范围
- [x] Spec-3：确认风险、兼容层、验证方式与回退策略
- [x] HARD-GATE：等用户确认后实施
- [x] 实施：抽 Media Domain 并接入旧入口
- [x] 验证：语法检查 + 长视频/修复链路回归

## Review（2026-04-24 产品化重构 Phase 6 Spec-1）
- 当前媒体层最重的实现集中在 `tools/dub_long_video.py`：`ffprobe_duration()` 负责 probe，`extract_source_audio()` / `cut_audio_segment()` 负责抽音频和切片，`detect_silence_endpoints()` / `choose_boundaries()` / `detect_speech_time_ranges()` 负责分段与时间窗决策，`concat_wav_files()` / `mix_vocals_with_bgm()` / `build_full_timeline_vocals()` / `build_full_timeline_mix()` / `build_full_timeline_bgm()` / `merge_srt_files()` 负责段内结果拼接回全时轴。
- `tools/dub_pipeline.py` 内也有一套媒体能力：`audio_duration()`、`extract_audio()`、`compose_vocals_master()`、`mix_with_bgm()`、`concat_generated_wavs()`；`tools/repair_bad_segments.py` 还重复保留了 `audio_duration()`、`compose_vocals_master()`、`mix_with_bgm()`、`concat_wav_files()`。这说明 Media Domain 的首要价值不是“新增功能”，而是消掉三处脚本里的 ffmpeg/拼接重复实现。
- 当前“长视频部分字幕不会整批失败”的关键护栏主要落在 `tools/dub_long_video.py`：空字幕 segment 会写 skipped manifest，最终 `build_full_timeline_*()` 只把存在产物的 segment 回填到全时轴，因此 skipped segment 不会直接污染整批最终结果；这正对应重构文档对 Phase 6 的验收要求。
- 现阶段媒体逻辑仍明显分成两层：
  1) 通用外壳：执行 ffmpeg/ffprobe、读取音频、重采样、拼接 wav、mux/export；
  2) 业务编排：按 segment 起止时间回填全时轴、根据 silence/speech 规则选边界、决定区间外是静音还是保留原音；
  这意味着第一轮最适合先抽通用外壳和“纯媒体处理函数”，而不是直接重写长视频编排主流程。
- 现有护栏主要是 `tests/test_dub_long_video.py` 与 manifest contract：它已经锁住空字幕 segment skip 和 batch manifest 的关键字段，但还没有单独冻结“compose/mix/helper”级函数行为；因此 Phase 6 的首轮实现必须继续以“旧入口保留、内部转调新模块”为主，而不是大改 `dub_long_video.py` 的控制流。

## Review（2026-04-24 产品化重构 Phase 6 Spec-2）
- 第一轮模块划分固定为 5 个文件，但只先落其中 4 个可复用壳层与纯处理模块：
  `src/subtitle_maker/core/ffmpeg.py` 负责 `run_cmd / run_cmd_checked / ffprobe / ffmpeg` 这类统一进程执行与错误包装；
  `src/subtitle_maker/domains/media/probe.py` 负责 `audio_duration / ffprobe_duration / _load_mono_audio / _resample_mono_audio` 一类 probe 与音频载入辅助；
  `src/subtitle_maker/domains/media/segment.py` 负责 `detect_silence_endpoints()`、`choose_boundaries()`、`detect_speech_time_ranges()`、`cut_audio_segment()`、`map_global_ranges_to_segment()` 等“切段与区间映射”逻辑；
  `src/subtitle_maker/domains/media/compose.py` 负责 `concat_wav_files()`、`mix_vocals_with_bgm()`、`compose_vocals_master()`、`build_full_timeline_vocals()`、`build_full_timeline_mix()`、`build_full_timeline_bgm()`；
  `export.py` 首轮暂不落地，因为当前真正的视频 mux/export 仍零散分布且未形成稳定重复面，强行抽会把范围扩展到 Web 导出与 CLI export 控制流。
- 迁移顺序固定为：
  1) 先抽 `core/ffmpeg.py` 与 `domains/media/probe.py`，把命令执行、probe、读写音频底座统一；
  2) 再抽 `domains/media/compose.py`，优先消除 `dub_pipeline.py` 与 `repair_bad_segments.py` 的重复 compose/mix/concat 实现；
  3) 最后抽 `domains/media/segment.py`，并先只让 `tools/dub_long_video.py` 内部转调新模块；
  这样能先吃掉重复实现最严重的部分，同时避免一上来就重写长视频主控制流。
- 首轮精确改动范围固定如下：
  `tools/dub_pipeline.py` 与 `tools/repair_bad_segments.py` 只允许把 `audio_duration / compose_vocals_master / mix_with_bgm / concat_generated_wavs 或 concat_wav_files` 改成兼容 facade；
  `tools/dub_long_video.py` 只允许把 `ffprobe_duration / extract_source_audio / detect_silence_endpoints / choose_boundaries / detect_speech_time_ranges / cut_audio_segment / build_full_timeline_* / merge_srt_files` 改为转调新模块；
  不改 `main()` 的编排顺序、segment skip 策略、manifest 写入时机、resume 复用扫描逻辑。
- 明确不进入首轮范围的内容：
  不改 `run_segment_job()` 的 subprocess 编排；
  不改 batch manifest / segment manifest schema；
  不改 Web `/segment_audio` 或字幕导出接口；
  不把 TTS 时长拟合、fade、trim 等对齐逻辑并入 Media Domain；
  因为这些分别属于 orchestration、协议层、Web route、Dubbing Domain，不应在 Phase 6 一次揉在一起。
- 对外兼容口首轮继续保持在旧脚本：
  `tools/dub_long_video.py`、`tools/dub_pipeline.py`、`tools/repair_bad_segments.py` 仍导出原函数名；
  新模块承接真实实现，旧函数做 facade；
  这样 `tests/test_dub_long_video.py` 与现有脚本调用路径不需要同步大改。

## Review（2026-04-24 产品化重构 Phase 6 Spec-3）
- 第一风险是“模块拆分后长视频整批失败保护失效”。当前 `tools/dub_long_video.py` 的关键产品约束是：空字幕 segment 写 skipped manifest，最终 `build_full_timeline_*()` 只回填存在产物的分段，因此单段失败或空段不会直接拖垮整批；首轮迁移不得改变这一行为，也不能把 skipped segment 重新混进最终 vocals/mix/bgm。
- 第二风险是 ffmpeg/ffprobe 错误语义漂移。现在三处脚本对命令失败的报错格式并不完全一致，但上层至少依赖“抛异常即失败”；因此 `core/ffmpeg.py` 第一轮只能统一执行和包装，不得随手重命名错误码、吞掉 stderr、改返回值形态，否则会让现有 CLI / unittest 的失败判断失真。
- 第三风险是音频拼接 helper 的采样率/时间轴细节被改坏。`tools/dub_long_video.py::build_full_timeline_vocals()`、`build_full_timeline_mix()`、`build_full_timeline_bgm()` 与 `tools/dub_pipeline.py::compose_vocals_master()` 都依赖“按 sample 精确落位、必要时重采样、段间覆盖规则稳定”；首轮迁移不能改这些函数的覆盖优先级、裁剪窗口和 peak normalize 规则。
- 第四风险是把“通用媒体壳层”和“业务编排层”混在一起。新 `domains/media/*` 可以接收文件路径、音频数组、时间区间和基础标量配置，但不能反向依赖 manifest reader、job store、TTS backend、Web request 或 segment orchestration；否则 Phase 6 会膨胀成跨层重写，偏离 `/docs/refactor/05-migration-roadmap.md` 的阶段目标。
- 首轮验证固定为三层：
  1) 语法：`uv run python -m py_compile src/subtitle_maker/core/ffmpeg.py src/subtitle_maker/domains/media/*.py tools/dub_long_video.py tools/dub_pipeline.py tools/repair_bad_segments.py tests/test_dub_long_video.py`
  2) 长视频主护栏：`uv run python -m unittest tests.test_dub_long_video`
  3) 如 compose/mix facade 改动触达 `dub_pipeline.py`，再补 `uv run python -m unittest tests.test_dubbing_cli_api` 作为最小 API 回归。
- 兼容层策略固定为“双层保留”：
  新媒体模块承接真实实现；
  旧脚本函数保留原名 facade；
  这样即使本轮只完成 `ffmpeg/probe/compose` 的下沉，`dub_long_video.py` / `dub_pipeline.py` / `repair_bad_segments.py` 仍能保持现有调用面不变。
- 回退策略固定为“按模块回退，不整阶段回退”：
  如果 `compose.py` 迁移后行为漂移，就只回退 facade 到旧实现，不影响已验证通过的 `ffmpeg.py` 或 `probe.py`；
  如果 `segment.py` 迁移影响长视频边界选择，只回退 `dub_long_video.py` 对 segment 模块的转调；
  避免把已完成的 Media Domain 下沉整体推翻。
- HARD-GATE 前的结论：
  这轮 Media Domain 实现目标是“统一执行壳层和重复 helper”，不是改长视频策略；
  只有在你明确确认后，才进入代码实现。

## Review（2026-04-24 产品化重构 Phase 6 实施）
- 已新增 `src/subtitle_maker/core/ffmpeg.py`，统一收口 `run_cmd()`、`run_cmd_checked()`、`run_cmd_stream()` 三类外部命令执行壳层；`tools/dub_long_video.py`、`tools/dub_pipeline.py`、`tools/repair_bad_segments.py` 现都通过兼容 facade 复用这层，不再各自维护 subprocess 模板。
- 已新增 `src/subtitle_maker/domains/media/probe.py`、`segment.py`、`compose.py` 与 `domains/media/__init__.py`：
  `probe.py` 收口 `audio_duration / ffprobe_duration / load_mono_audio / resample_mono_audio`；
  `segment.py` 收口 `extract_source_audio / detect_silence_endpoints / choose_boundaries / detect_speech_time_ranges / map_global_ranges_to_segment / cut_audio_segment`；
  `compose.py` 收口 `compose_vocals_master / concat_wav_files / concat_generated_wavs / mix_with_bgm / mix_vocals_with_bgm / build_full_timeline_* / merge_srt_files / merge_bilingual_srt_files`。
- `tools/dub_long_video.py` 现已把 `ffprobe_duration()`、`extract_source_audio()`、`detect_silence_endpoints()`、`choose_boundaries()`、`detect_speech_time_ranges()`、`map_global_ranges_to_segment()`、`cut_audio_segment()`、`build_full_timeline_*()`、`merge_srt_files()`、`merge_bilingual_srt_files()` 改为 facade；`main()` 的分段编排、segment skip、resume 复用和 manifest 写入顺序保持不变。
- `tools/dub_pipeline.py` 与 `tools/repair_bad_segments.py` 现已把 `audio_duration()`、`compose_vocals_master()`、`mix_with_bgm()`、`concat_generated_wavs()` / `concat_wav_files()`、`merge_srt_files()`、`merge_bilingual_srt_files()` 切到新媒体模块；原函数名和参数签名保持不变，因此现有脚本调用面和测试入口未变。
- 本轮没有进入 `/docs/refactor/` 之外的范围：
  未改 `run_segment_job()` 子进程编排；
  未改 manifest schema；
  未改 Web route；
  未把对齐/trim/fade 等 Dubbing 逻辑揉进 Media Domain。
- 校验通过：`uv run python -m py_compile src/subtitle_maker/core/ffmpeg.py src/subtitle_maker/domains/media/__init__.py src/subtitle_maker/domains/media/probe.py src/subtitle_maker/domains/media/segment.py src/subtitle_maker/domains/media/compose.py tools/dub_long_video.py tools/dub_pipeline.py tools/repair_bad_segments.py tests/test_dub_long_video.py`。
- 回归通过：`uv run python -m unittest tests.test_dub_long_video`（`Ran 1 test ... OK`）。
- 最小 API 回归通过：`uv run python -m unittest tests.test_dubbing_cli_api`（`Ran 40 tests ... OK`）。

## 2026-04-24 产品化重构 Phase 7（Dubbing Domain and TTS Backend）

- [x] Spec-1：审计当前配音编排、参考音频、对齐、review/redub 与 TTS backend 接线点
- [x] Spec-2：确认 `domains/dubbing/*` 与 `backends/*` 模块划分、迁移顺序与精确改动范围
- [x] Spec-3：确认风险、兼容层、验证方式与回退策略
- [x] HARD-GATE：等用户确认后实施
- [x] 实施：抽 Dubbing Domain 与 TTS Backend
- [x] 验证：语法检查 + 配音/review 回归

## Review（2026-04-24 产品化重构 Phase 7 Spec-1）
- 当前“参考音频”能力仍完全堆在 `tools/dub_pipeline.py`：`extract_reference_audio()`、`extract_reference_audio_from_offset()`、`extract_reference_audio_from_window()`、`build_subtitle_reference_map()` 负责单人默认参考、按偏移抽参考、按字幕窗口逐句抽参考，以及逐句参考映射。这说明 `domains/dubbing/references.py` 的首要来源已经很清楚，且目前仍直接依赖本地音频文件与 `soundfile`，还没有独立领域层。
- 当前“对齐/时长拟合”能力也分散在 `tools/dub_pipeline.py` 与 `tools/repair_bad_segments.py` 两处：`build_atempo_filter_chain()`、`trim_silence_edges()`、`fit_audio_to_duration()`、`trim_audio_to_max_duration()`、`compute_effective_target_duration()` 共同决定借静音、裁边、变速拟合和超时长硬裁剪；`repair_bad_segments.py` 中还保留了一套重复实现，说明 `domains/dubbing/alignment.py` 的价值和媒体层类似，先收口重复 helper，而不是先改策略。
- 当前主配音编排实际已经分成两条路径，但都还留在 `tools/dub_pipeline.py`：`synthesize_text_once()` 是底层单次 TTS 调用分发；`synthesize_segments()` 是逐句配音主循环，负责候选评分、静音检测、重试、rewrite、force-fit 与 V2 评分；另有 grouped 路径（同文件中围绕 `build_synthesis_groups()`、group 级时长拟合和 group silence retry 的那段逻辑）负责 legacy/grouped synthesis。也就是说 `domains/dubbing/pipeline.py` 首轮更像是把现有两条主链路搬出脚本，而不是重新设计配音算法。
- 当前 TTS backend 还没有真正抽象成接口。`tools/dub_pipeline.py::synthesize_text_once()` 仍直接 `if tts_backend == "qwen" / "index-tts"` 分支；参数校验里也只接受这两个 backend（同文件参数校验处）；`tools/repair_bad_segments.py` 甚至还有自己的一套 `check_index_tts_service()` / `synthesize_via_index_tts_api()` 调用。说明 `/docs/refactor/05-migration-roadmap.md` 里的 `backends/base.py`、`backends/index_tts.py` 目前在代码里还不存在，`OmniVoice` 也仍停留在计划与配置层，没有进入主运行时分发。
- review/redub 语义恢复目前主要落在 `src/subtitle_maker/dubbing_cli_api.py::_rerun_segment_with_translated_srt()`：它会从 segment manifest 读回 `grouped_synthesis`、`force_fit_timing`、`tts_backend`、`index_tts_api_url`，再通过 `build_segment_redub_command()` 触发局部重配。这说明 `domains/dubbing/review.py` 首轮必须以“保留 review redub 语义恢复”为硬边界，不能因为抽模块就把重配语义重新绑回当前默认值。
- 数据协议层已经为 Phase 7 准备好了边界，但实现尚未对齐：`docs/refactor/04-data-contracts.md` 已把 `DubbingOptions`、`TtsOptions` 拆开，并明确 `grouped_synthesis`、`force_fit_timing`、`translated_input_preserve_synthesis_mode`、`backend`、`fallback_backend` 是可重放配置；`src/subtitle_maker/manifests/readwrite.py` 也已在 batch/segment manifest 中持久化 `tts_backend`、`index_tts_api_url`、`grouped_synthesis`、`force_fit_timing`。这意味着 Phase 7 首轮不需要再发明新协议，重点是把现有运行时代码对齐到这些已冻结的字段上。

## Review（2026-04-24 产品化重构 Phase 7 Spec-2）
- 第一轮模块划分固定为 7 个文件，但只先完整落其中 5 个运行时模块，另外 2 个保持延后或薄占位：
  `src/subtitle_maker/domains/dubbing/references.py` 负责 `extract_reference_audio*()` 与 `build_subtitle_reference_map()`；
  `alignment.py` 负责 `build_atempo_filter_chain()`、`trim_silence_edges()`、`fit_audio_to_duration()`、`trim_audio_to_max_duration()`、`compute_effective_target_duration()`、`apply_short_fade_edges()` 以及 balanced 时长分配 helper；
  `pipeline.py` 负责 `build_synthesis_groups()`、`synthesize_segments()`、`synthesize_segments_grouped()` 这两条主配音编排路径及候选评分/重试逻辑；
  `backends/base.py` 定义 `TtsBackend` 最小接口；
  `backends/index_tts.py` 承接当前 `index-tts` 的 API / local infer 分发与文本分片；
  `review.py` 首轮只允许承接运行时侧的局部重配辅助，不接管 `dubbing_cli_api.py` 的 HTTP / 事务编排；
  `backends/omni_voice.py` 首轮暂不做真实运行时接线，只允许保留占位或延后到下一轮，因为当前主代码路径还没有可执行的 OmniVoice 分发与测试护栏。
- 迁移顺序固定为：
  1) 先抽 `references.py` 与 `alignment.py`，优先消除 `tools/dub_pipeline.py` / `tools/repair_bad_segments.py` 的重复 helper；
  2) 再抽 `backends/base.py` 与 `backends/index_tts.py`，把 `synthesize_text_once()` 里的 index-tts 分支搬出；
  3) 最后抽 `pipeline.py`，让 `tools/dub_pipeline.py` 的逐句/分组配音主循环内部转调新模块；
  4) `review.py` 仅在不扩大 Web 编排面的前提下收 runtime-side redub helper；
  这样能先把“重复 helper + backend 分发”拆出来，再处理最重的主编排循环，避免一上来就把 API route、事务回滚和运行时逻辑一起重写。
- 首轮精确改动范围固定如下：
  `tools/dub_pipeline.py` 只允许把参考音频、对齐 helper、`synthesize_text_once()`、`synthesize_segments()`、`synthesize_segments_grouped()` 改为 facade 或薄编排层；
  `tools/repair_bad_segments.py` 只允许复用 `alignment.py` 与 `backends/index_tts.py` 的 helper，不改其 repair 流程和 batch 回写逻辑；
  `src/subtitle_maker/dubbing_cli_api.py` 只允许继续从 manifest 恢复 `grouped_synthesis / force_fit_timing / tts_backend / index_tts_api_url` 并透传给 command builder，不把 HTTP route 自身迁入本轮新模块。
- 明确不进入首轮范围的内容：
  不改 `jobs/command_builder.py` 的命令协议；
  不改 manifest schema；
  不放开新的 Web backend 选择控件；
  不把 `OmniVoice` 真正接入主运行时分发；
  不重写 review save-and-redub 的事务回滚与文件快照逻辑；
  因为这些分别属于协议层、前端、后续 backend 扩展、API orchestration，不应在 Phase 7 第一轮揉在一起。
- 对外兼容口首轮继续保持在旧入口：
  `tools/dub_pipeline.py` 仍保留原函数名和 CLI 参数面；
  `tools/repair_bad_segments.py` 仍保留现有命令入口；
  `src/subtitle_maker/dubbing_cli_api.py` 仍保留当前 review/redub 调用面；
  新模块承接真实实现，旧入口做 facade，这样 `tests/test_dubbing_cli_api.py`、`tests/test_command_builder.py`、`tests/test_manifest_contracts.py` 的现有护栏不需要同步重写。

## Review（2026-04-24 产品化重构 Phase 7 Spec-3）
- 第一风险是“review redub 语义恢复被拆坏”。当前 `src/subtitle_maker/dubbing_cli_api.py::_rerun_segment_with_translated_srt()` 会从 segment manifest 恢复 `grouped_synthesis`、`force_fit_timing`、`tts_backend`、`index_tts_api_url`，并依赖 `build_segment_redub_command()` 在 grouped 场景禁止 `--redub-line-indices-json`；这套语义已经被 `tests/test_dubbing_cli_api.py` 与 `tests/test_command_builder.py` 锁住，所以首轮迁移不得改这些字段的恢复来源、默认值或命令拼装规则。
- 第二风险是“逐句/分组两条配音主链路行为漂移”。`tools/dub_pipeline.py::synthesize_segments()` 现在承载逐句模式下的参考音回退、静音检测、invalid audio 检测、retry、rewrite、force-fit 与 V2 候选评分；`synthesize_segments_grouped()` 承载 grouped/legacy 路径下的 group silence retry、balanced/strict/sentence 三套时长拟合分支。首轮下沉到 `domains/dubbing/pipeline.py` 时，不得改变候选评分权重、retry 次数、静音判定门槛、grouped 与 non-grouped 的切换条件。
- 第三风险是 backend 抽象后错误语义变形。当前 `tools/dub_pipeline.py::synthesize_text_once()` 与 `tools/repair_bad_segments.py::synthesize_via_index_tts_api()` 都把 TTS 硬失败统一映射为 `E-TTS-001` 或 `E-TTS-002`；而 CLI 主流程与 review redub 都默认“抛异常即失败”。因此 `backends/base.py` / `backends/index_tts.py` 首轮只能把分发搬走，不能顺手重写错误码、吞掉底层异常，或把失败改成静默返回空结果。
- 第四风险是把 `OmniVoice` 过早拉进主链路。根据 `/docs/refactor/05-migration-roadmap.md` 与当前代码现状，`OmniVoice` 还没有可执行运行时分发与测试护栏；如果在首轮就接入主 backend 选择，等于把“Dubbing Domain 重构”混成“新 backend 上线”。所以首轮必须坚持 `index-tts` 为默认唯一稳定 backend，`OmniVoice` 只允许保留占位或延后，不能进入 `tools/dub_pipeline.py` 的真实运行时分支。
- 第五风险是对齐 helper 下沉时破坏已有节奏策略。`build_atempo_filter_chain()`、`trim_silence_edges()`、`fit_audio_to_duration()`、`trim_audio_to_max_duration()`、`compute_effective_target_duration()` 同时影响“借静音”“最后一句可借到媒体尾部”“strict/balanced/sentence 不同模式的拟合与裁剪”。这些 helper 在 `tools/dub_pipeline.py` 和 `tools/repair_bad_segments.py` 中都被复用，所以首轮迁移不得更改公式、阈值和 fallback 先后顺序。
- 首轮验证固定为四层：
  1) 语法：`uv run python -m py_compile src/subtitle_maker/domains/dubbing/*.py src/subtitle_maker/backends/*.py tools/dub_pipeline.py tools/repair_bad_segments.py src/subtitle_maker/dubbing_cli_api.py`
  2) API / review 主护栏：`uv run python -m unittest tests.test_dubbing_cli_api`
  3) 命令与协议护栏：`uv run python -m unittest tests.test_command_builder tests.test_manifest_contracts`
  4) 如本轮实际抽出纯 runtime helper，则应补一组新的 dubbing runtime 单测，至少覆盖 `grouped_synthesis` 禁止局部行重跑、`force_fit_timing` 恢复、`tts_backend` 分发和 reference fallback；在未补前，不允许声称已冻结这些运行时细节。
- 兼容层策略固定为“三处旧入口保留”：
  `tools/dub_pipeline.py` 保留 CLI 参数面和原函数名；
  `tools/repair_bad_segments.py` 保留 repair 命令入口；
  `src/subtitle_maker/dubbing_cli_api.py` 保留 review/redub 的 HTTP 编排与事务回滚；
  新模块承接真实实现，旧入口做 facade，这样 Phase 7 第一轮不会同时触发 CLI、repair 脚本、Web route 三处大范围改动。
- 回退策略固定为“按子域回退，不整阶段回退”：
  若 `references.py` 或 `alignment.py` 下沉后行为漂移，只回退对应 facade 到 `tools/dub_pipeline.py` / `tools/repair_bad_segments.py` 原实现；
  若 `backends/index_tts.py` 抽离后导致 API 调用异常语义变化，只回退 `synthesize_text_once()` 的 backend 分支；
  若 `pipeline.py` 下沉后影响 grouped / non-grouped 结果，只回退主循环转调，不回退已验证通过的 helper 与 backend 模块。
- HARD-GATE 前的结论：
  这轮 Phase 7 的实现目标是“抽出配音运行时与 backend 分发”，不是改产品层 TTS 能力范围；
  只有在你明确确认后，才进入代码实现。

## Review（2026-04-24 产品化重构 Phase 7 实施）
- 已新增 `src/subtitle_maker/backends/base.py`、`index_tts.py`、`omni_voice.py` 与 `backends/__init__.py`：`base.py` 定义 `TtsBackend` / `TtsSynthesisRequest` 最小接口，`index_tts.py` 收口 `_http_json_request()`、`check_index_tts_service()`、`release_index_tts_api_model()`、`synthesize_via_index_tts_api()`、`split_text_for_index_tts()` 和 `IndexTtsBackend`，`omni_voice.py` 仅保留占位 adapter，明确不进入主运行时。
- 已新增 `src/subtitle_maker/domains/dubbing/references.py`、`alignment.py`、`pipeline.py`、`review.py` 与 `domains/dubbing/__init__.py`：`references.py` 收口 `extract_reference_audio*()` 与 `build_subtitle_reference_map()`；`alignment.py` 收口 `build_atempo_filter_chain()`、`apply_atempo()`、`trim_silence_edges()`、`fit_audio_to_duration()`、`trim_audio_to_max_duration()`、`compute_effective_target_duration()` 以及 balanced 时长分配 helper；`pipeline.py` 首轮承接 `build_synthesis_groups()` 与 `synthesize_text_once()`；`review.py` 承接 redub manifest 运行时参数恢复 helper。
- `tools/dub_pipeline.py` 现已把参考音频 helper、对齐 helper、`build_synthesis_groups()`、`synthesize_text_once()` 改成 facade，`synthesize_segments()` / `synthesize_segments_grouped()` 主循环仍保留在旧脚本中，继续作为首轮兼容编排层；这样没有改 CLI 参数面、retry 逻辑和 grouped/non-grouped 主流程。
- `tools/repair_bad_segments.py` 现已把 `check_index_tts_service()`、`synthesize_via_index_tts_api()`、`build_atempo_filter_chain()`、`fit_audio_to_duration()`、`compute_effective_target_duration()`、`trim_silence_edges()` 切到新 backend / dubbing 模块；repair 流程本身未改。
- `src/subtitle_maker/dubbing_cli_api.py::_rerun_segment_with_translated_srt()` 现通过 `domains/dubbing/review.py::resolve_segment_redub_runtime_options()` 恢复 `pipeline_version / rewrite_translation / grouped_synthesis / force_fit_timing / tts_backend / index_tts_api_url`，HTTP route 与事务回滚逻辑保持不变。
- 已补 `tests/test_dubbing_runtime.py` 作为 Phase 7 首轮 runtime 单测，覆盖 `build_atempo_filter_chain()`、`compute_effective_target_duration()`、`build_synthesis_groups()`、`synthesize_text_once()` 的 backend 分发，以及 redub 运行时参数恢复。
- 本轮仍未进入 `/docs/refactor/` 之外的范围：未改 manifest schema、未改 command builder 协议、未把 OmniVoice 接入主 backend 选择、未重写 review save-and-redub 事务编排，也未改 `tools/dub_pipeline.py` 的逐句/分组主循环策略。
- 校验通过：`uv run python -m py_compile src/subtitle_maker/backends/__init__.py src/subtitle_maker/backends/base.py src/subtitle_maker/backends/index_tts.py src/subtitle_maker/backends/omni_voice.py src/subtitle_maker/domains/dubbing/__init__.py src/subtitle_maker/domains/dubbing/references.py src/subtitle_maker/domains/dubbing/alignment.py src/subtitle_maker/domains/dubbing/pipeline.py src/subtitle_maker/domains/dubbing/review.py src/subtitle_maker/dubbing_cli_api.py tools/dub_pipeline.py tools/repair_bad_segments.py tests/test_dubbing_runtime.py`。
- 回归通过：`uv run python -m unittest tests.test_dubbing_cli_api`（`Ran 40 tests ... OK`）。
- 协议与 runtime 回归通过：`uv run python -m unittest tests.test_command_builder tests.test_manifest_contracts tests.test_dubbing_runtime`（`Ran 15 tests ... OK`）。

### Phase 7 续做（Pipeline 主循环下沉）

- [x] 把 `tools/dub_pipeline.py::synthesize_segments()` 下沉到 `src/subtitle_maker/domains/dubbing/pipeline.py`
- [x] 把 `tools/dub_pipeline.py::synthesize_segments_grouped()` 下沉到 `src/subtitle_maker/domains/dubbing/pipeline.py`
- [x] 将 `tools/dub_pipeline.py` 保持为 facade，并补续做 review 记录
- [x] 续做验证：`py_compile` + `tests.test_dubbing_cli_api` + `tests.test_dubbing_runtime`

## Review（2026-04-24 产品化重构 Phase 7 续做：Pipeline 主循环下沉）
- 已把 `tools/dub_pipeline.py::synthesize_segments()` 与 `tools/dub_pipeline.py::synthesize_segments_grouped()` 下沉到 `src/subtitle_maker/domains/dubbing/pipeline.py`，并在 `src/subtitle_maker/domains/dubbing/__init__.py` 暴露新的运行时入口，保证后续 Phase 7/8 不再继续把主循环逻辑留在旧脚本里。
- `tools/dub_pipeline.py` 现已进一步收口为 facade：参考音频 helper、对齐 helper、`build_synthesis_groups()`、`synthesize_text_once()`、`synthesize_segments()`、`synthesize_segments_grouped()` 都转调到 `domains/dubbing/*` 或 `backends/*` 新模块，CLI 参数面和旧调用函数名保持不变。
- 本轮续做没有扩散到 `/docs/refactor/` 之外的范围：未改 manifest schema、未改 `jobs/command_builder.py` 协议、未把 OmniVoice 接入主运行时，也未重写 `dubbing_cli_api.py` 的 HTTP / 事务编排。
- 已补强 `tests/test_dubbing_runtime.py`，覆盖主循环下沉后的两条关键运行时路径：非重配行直接复用既有音频，以及 grouped 非语音分组生成静音占位；这样主循环迁移后不再只依赖 API 级回归兜底。
- 校验通过：`uv run python -m py_compile src/subtitle_maker/domains/dubbing/pipeline.py src/subtitle_maker/domains/dubbing/__init__.py tools/dub_pipeline.py tests/test_dubbing_runtime.py`。
- 回归通过：`uv run python -m unittest tests.test_dubbing_runtime`（`Ran 8 tests ... OK`）。
- API 回归通过：`uv run python -m unittest tests.test_dubbing_cli_api`（`Ran 40 tests ... OK`）。
- 协议护栏回归通过：`uv run python -m unittest tests.test_command_builder tests.test_manifest_contracts`（`Ran 9 tests ... OK`）。

## 2026-04-24 产品化重构 Phase 8（Job Store）

- [x] Spec-1：审计当前任务状态、恢复路径与存储边界
- [x] Spec-2：确认 `jobs/models.py / store.py / recovery.py` 的模块划分、迁移顺序与最小改动范围
- [x] Spec-3：确认风险、兼容层、验证方式与回退策略
- [x] HARD-GATE：等用户确认后实施
- [x] 实施：重构 Job Store 并接入旧入口
- [x] 验证：语法检查 + store/API 回归

## Review（2026-04-24 产品化重构 Phase 8 Spec-1）
- `src/subtitle_maker/jobs/store.py::TaskStore` 当前仍只是 `RLock + in-memory dict` 薄层，真实能力只有 `create()`、`get()`、`get_copy()`、`update()`、`items_snapshot()`、`list_active_ids()`；它没有批次索引、磁盘恢复、状态历史，也不拥有 manifest 反查逻辑，所以还谈不上 `/docs/refactor/05-migration-roadmap.md` 里“统一任务状态和恢复”的完整 Job Store。
- `src/subtitle_maker/jobs/models.py::DubbingTaskRecord` 现在只定义了少量 Auto Dubbing 公共字段，而 `TaskPayload = Dict[str, Any]` 仍是主承载结构；这说明当前 store 的数据契约还没有真正 typed 化，`Project / Job / JobError` 这类 Phase 4 路线图里提到的模型并未进入运行时主路径。
- `src/subtitle_maker/dubbing_cli_api.py::start_auto_dubbing()` 与 `src/subtitle_maker/dubbing_cli_api.py::load_auto_dubbing_batch()` 都是直接手拼 task dict 后调用 `TaskStore.create()`；而历史任务恢复真正依赖的是 `src/subtitle_maker/dubbing_cli_api.py::_complete_task_from_manifest()` 和 `load_batch_manifest()`。也就是说，“任务创建”和“批次恢复”现在还分散在 API 层，Store 自己并不掌握恢复入口。
- `src/subtitle_maker/dubbing_cli_api.py::_run_cli_task()`、`get_auto_dubbing_status()`、`cancel_auto_dubbing()`、`cancel_active_dubbing()` 已经依赖 `TaskStore` 处理 Auto Dubbing 任务生命周期；但 `src/subtitle_maker/dubbing_cli_api.py` 仍保留 `_tasks = _task_store.items` 兼容别名，说明旧的“直接字典访问”表面还没真正封口。
- 这种兼容面在测试里仍然存在：`tests/test_dubbing_cli_api.py::test_completed_task_exposes_artifacts_and_download()` 和 `tests/test_dubbing_cli_api.py::test_cancel_auto_dubbing_marks_task_and_kills_process_group()` 还是直接写 `dubbing_cli_api._tasks[task_id] = {...}`。这说明第二轮 Job Store 重构如果直接移除 `_tasks`，会先打碎现有测试护栏和少量旧调用面。
- 任务状态目前并没有全站统一。`src/subtitle_maker/web.py::transcribe_task()`、`transcribe()`、`cancel_task()`、`get_status()` 仍在操作另一个全局 `tasks: Dict[str, dict]`；`src/subtitle_maker/web.py::release_all_models()` 再通过 `cancel_active_transcriptions()` 和从 `dubbing_cli_api` 导入的 `cancel_active_dubbing()` 跨两个存储做收敛。这说明 Phase 8 真正要收的是“任务状态所有权”，不是只继续给 Auto Dubbing 包一层 dict helper。
- 当前“恢复”能力也只覆盖 Auto Dubbing 且仍停在 API 层。`src/subtitle_maker/dubbing_cli_api.py::load_auto_dubbing_batch()` 会新建一个内存 task，再调用 `_complete_task_from_manifest()` 从 batch manifest 回填 artifacts、review 数量和最终状态；而 `src/subtitle_maker/web.py` 的普通转写任务并没有对应的恢复机制。这意味着首轮 Job Store 更适合先统一 Auto Dubbing 的恢复原语，再决定是否把转写任务一并纳入。
- 现有测试护栏也偏薄。`tests/test_task_store.py::test_create_get_and_copy_keep_behavior_consistent()`、`test_update_and_active_listing_respect_terminal_status()`、`test_items_snapshot_returns_task_copies()` 只冻结了最基础的 CRUD/snapshot 语义，还没有覆盖 manifest 恢复、任务公共视图、跨入口统一状态或旧 `_tasks` 兼容层的行为。

## Review（2026-04-24 产品化重构 Phase 8 Spec-2）
- 第一轮 Job Store 模块划分固定为 3 个文件：`src/subtitle_maker/jobs/models.py`、`store.py`、`recovery.py`。其中 `models.py` 负责把当前松散的 `TaskPayload` 向 `Job / JobError / Artifact` 靠拢，但首轮只补最小 typed 结构，不强推全量 dataclass；`store.py` 负责内存态任务的创建、更新、公共视图和兼容访问；`recovery.py` 负责 batch manifest 反查、artifact 列表生成、从 manifest 回填任务记录。这样能把当前散在 `src/subtitle_maker/dubbing_cli_api.py::_public_task()`、`_find_batch_manifest_by_name()`、`_list_available_batches()`、`_build_artifacts()`、`_complete_task_from_manifest()` 的 Job Store 职责抽出去，而不碰字幕/配音算法。
- `jobs/models.py` 第一轮只补“能冻结 API 契约”的最小模型：保留现有 `TaskStatus`，新增 Auto Dubbing 侧可直接复用的 `JobArtifact`、`JobErrorPayload`、`JobRecord/PublicJobRecord` 一类 typed dict 或等价轻量结构，用来承接当前 `src/subtitle_maker/dubbing_cli_api.py::start_auto_dubbing()` 和 `load_auto_dubbing_batch()` 手拼出来的字段集合。`docs/refactor/04-data-contracts.md` 里定义的完整 `Project` 暂不强落，因为当前运行时还没有稳定的项目根目录所有权模型。
- `jobs/store.py` 第一轮会从“纯 dict 容器”升级为“任务状态服务”，但仍保持内存存储：除了保留 `create/get/update/list_active_ids`，还应吸收当前 API 层的公共任务视图与高频状态助手，例如 `to_public()`、`append_stdout()`、`set_stage()` 或等价接口，避免 `src/subtitle_maker/dubbing_cli_api.py::_public_task()`、`_append_stdout()`、`_bump_stage()` 长期留在 route 文件里。这里的目标是收口状态所有权，不是立刻引入持久化数据库。
- `jobs/recovery.py` 首轮只承接 Auto Dubbing 的历史批次恢复，不管普通转写：它负责基于 `src/subtitle_maker/manifests/readwrite.py::load_batch_manifest()` 生成可回填的 Job 记录、构建 artifact 列表、列出可加载 batch、按 `batch_id` 反查 manifest。这样 `src/subtitle_maker/dubbing_cli_api.py::load_auto_dubbing_batch()` 可以退化成“调用 recovery + store”，而不是自己同时做文件扫描、manifest 解析和任务状态写入。
- 迁移顺序固定为：
  1. 先扩 `jobs/models.py`，把 Auto Dubbing 当前返回字段收成最小 typed 结构；
  2. 再扩 `jobs/store.py`，把公共视图、stdout tail、stage/progress 更新 helper 收进去；
  3. 最后新增 `jobs/recovery.py`，把 batch 恢复与 artifact 构建从 `dubbing_cli_api.py` 挪走；
  4. `src/subtitle_maker/dubbing_cli_api.py` 只改成 facade；
  这样可以先稳定任务内存记录格式，再搬恢复逻辑，避免一上来同时改模型、API、manifest 恢复三层。
- 第一轮明确不做：
  - 不把 `src/subtitle_maker/web.py` 的普通转写 `tasks` 全局字典并入 Job Store；
  - 不新增 `jobs/runner.py`；
  - 不引入磁盘级持久化任务索引；
  - 不改 `load_batch_manifest()` / segment manifest schema；
  - 不改前端轮询协议和返回字段名；
  因为这些分别属于全站任务统一、编排层重构、持久化设计、协议层和前端契约，不应在 Phase 8 第一刀混做。
- 兼容策略保持和前几个 phase 一致：`src/subtitle_maker/dubbing_cli_api.py` 继续保留 `_task_store`，并暂时保留 `_tasks = _task_store.items` 兼容别名；`tests/test_dubbing_cli_api.py` 这一轮不用同步重写为全 typed store API。等 Job Store 新接口稳定并有足够测试后，再考虑去掉 `_tasks` 直写口。
- 首轮精确改动范围也固定了：只允许改 `src/subtitle_maker/jobs/models.py`、`store.py`、新增 `recovery.py`、以及 `src/subtitle_maker/dubbing_cli_api.py` 中与 Auto Dubbing 状态/恢复直接相关的 helper 和 route；`src/subtitle_maker/web.py`、`tools/dub_long_video.py`、`tools/dub_pipeline.py` 都不进入本轮实现面。

## Review（2026-04-24 产品化重构 Phase 8 Spec-3）
- 第一风险是把 `load-batch` 的恢复语义拆坏。当前 `src/subtitle_maker/dubbing_cli_api.py::load_auto_dubbing_batch()` 依赖 `src/subtitle_maker/dubbing_cli_api.py::_complete_task_from_manifest()` 和 `src/subtitle_maker/manifests/readwrite.py::load_batch_manifest()` 恢复 `target_lang`、`pipeline_version`、`rewrite_translation`、`timing_mode`、`grouping_strategy`、short merge、`tts_backend`、`index_tts_api_url` 等字段，而 `tests/test_dubbing_cli_api.py::test_load_auto_dubbing_batch_falls_back_from_legacy_short_merge_units()` 已锁住历史 short-merge 兼容语义。首轮迁移不得改变这些字段的恢复来源，也不得把 legacy fallback 悄悄挪到 API 层默认值。
- 第二风险是把公开任务视图的返回面改坏。当前 `src/subtitle_maker/dubbing_cli_api.py::_public_task()` 会显式隐藏 `process`、`input_path`、`out_root`、`upload_dir` 这类本地敏感字段，同时保留 `artifacts`、`stdout_tail`、`target_lang`、`pipeline_version` 等前端轮询所需字段；`tests/test_dubbing_cli_api.py::test_start_auto_dubbing_creates_isolated_task()`、`test_completed_task_exposes_artifacts_and_download()` 都在消费这套返回形态。`jobs/store.py` 吸收公共视图时，不能顺手改字段名、删字段，或把本地路径重新暴露到 API 返回。
- 第三风险是 `_tasks` 兼容层被过早删除。当前 `src/subtitle_maker/dubbing_cli_api.py` 还保留 `_tasks = _task_store.items`，而 `tests/test_dubbing_cli_api.py::test_completed_task_exposes_artifacts_and_download()`、`test_cancel_auto_dubbing_marks_task_and_kills_process_group()` 仍直接写 `_tasks[task_id]`。因此本轮 Job Store 重构不能把“收口状态所有权”误做成“立刻删除兼容入口”，否则会先打碎现有测试和少量旧代码。
- 第四风险是把 `TaskStore` 从“线程安全内存态”改成“行为漂移的状态机”。当前 `src/subtitle_maker/jobs/store.py::TaskStore` 的核心语义很简单：`get()` 返回原引用，`get_copy()` 和 `items_snapshot()` 返回浅拷贝，`list_active_ids()` 只按终态集合过滤；这些都被 `tests/test_task_store.py` 直接锁住。首轮增强 `store.py` 时，必须保留这些既有语义，再在其上叠加 `to_public()`、stdout/stage helper，而不是重写为全新对象模型。
- 第五风险是把 Job Store 重构扩散成全站任务统一。`src/subtitle_maker/web.py::transcribe_task()`、`transcribe()`、`get_status()` 仍操作另一套 `tasks: Dict[str, dict]`，`src/subtitle_maker/web.py::release_all_models()` 只是跨 `cancel_active_transcriptions()` 和 `cancel_active_dubbing()` 做收口。若本轮顺手把普通转写也并进 Job Store，会把 Auto Dubbing 恢复重构扩成整个 Web 生命周期改造，超出当前 Spec 边界。
- 第六风险是把 manifest 恢复和状态更新耦合反了。`jobs/recovery.py` 首轮只应该根据 manifest 生成可回填的 Job 记录与 artifacts，不应该反向改写 manifest 或发明新 schema；否则会冲撞已经由 `tests/test_manifest_contracts.py` 冻住的 manifest 合约，尤其是 replay 字段和 legacy fallback。
- 首轮验证固定为四层：
  1. 语法：`uv run python -m py_compile src/subtitle_maker/jobs/models.py src/subtitle_maker/jobs/store.py src/subtitle_maker/jobs/recovery.py src/subtitle_maker/dubbing_cli_api.py tests/test_task_store.py tests/test_dubbing_cli_api.py`
  2. Store 主护栏：`uv run python -m unittest tests.test_task_store`
  3. Auto Dubbing API 回归：`uv run python -m unittest tests.test_dubbing_cli_api`
  4. manifest 恢复契约护栏：`uv run python -m unittest tests.test_manifest_contracts`
- 回退策略固定为“按职责块回退，不整 phase 回退”：
  - 若 `jobs/models.py` 的 typed 结构引发 API 返回漂移，只回退模型映射层，保留已验证通过的 `store.py`/`recovery.py`；
  - 若 `jobs/store.py` 的公共视图/状态 helper 引发 status 或 cancel 行为异常，只回退 store facade 到当前 `dubbing_cli_api.py` helper；
  - 若 `jobs/recovery.py` 引发 `load-batch` 恢复异常，只回退 batch 恢复和 artifact 构建转调，不回退其他 TaskStore 收口。
- HARD-GATE 前的结论：
  这轮 Phase 8 的实现目标是“统一 Auto Dubbing 的任务状态与恢复原语”，不是“把整个站点所有任务统一进一个任务中心”；
  只有在你明确确认后，才进入代码实现。

## Review（2026-04-24 产品化重构 Phase 8 实施）
- 已扩展 `src/subtitle_maker/jobs/models.py`：在保留 `TaskStatus` / `DubbingTaskRecord` 兼容名的前提下，新增 `JobArtifact`、`JobErrorPayload`、`JobRecord`、`PublicJobRecord` 最小 typed 结构，用来冻结 Auto Dubbing 当前任务返回面，而不强行把整站任务模型一次性 dataclass 化。
- 已扩展 `src/subtitle_maker/jobs/store.py`：保留原有 `create/get/get_copy/update/list_active_ids` 语义不变，同时新增 `append_stdout()`、`set_stage()`、`to_public()`、`get_public()`，把 `src/subtitle_maker/dubbing_cli_api.py` 里原本散落的 stdout tail、阶段推进、公开视图逻辑收回 Job Store。
- 已新增 `src/subtitle_maker/jobs/recovery.py`：把 batch manifest 反查、可加载 batch 列表、artifact 列表构建、以及从 batch manifest 回填任务字段的逻辑从 `src/subtitle_maker/dubbing_cli_api.py` 中抽离出来；`load-batch` 现在通过 `build_loaded_batch_task()` 直接生成完整内存任务记录。
- `src/subtitle_maker/dubbing_cli_api.py` 当前已收口为 facade：`_append_stdout()`、`_public_task()`、`_bump_stage()`、`_find_batch_manifest_by_name()`、`_list_available_batches()`、`_build_artifacts()`、`_complete_task_from_manifest()` 都转调到 `jobs/store.py` 或 `jobs/recovery.py`，但私有函数名和 `_tasks` 兼容别名仍然保留，避免现有测试与旧代码立即断裂。
- 本轮明确没有扩散到 `/docs/refactor/` 之外的范围：未把 `src/subtitle_maker/web.py` 的普通转写 `tasks` 全局字典并入 Job Store，未新增 `jobs/runner.py`，未改 manifest schema，也未改前端轮询协议和字段名。
- 已补 `tests/test_job_recovery.py`，覆盖 Job Store 恢复层的最小护栏：batch manifest 恢复时 replay 字段保留、artifact 构建、可加载批次扫描、以及 `load-batch` 场景下完整任务记录的生成。
- 已补强 `tests/test_task_store.py`，锁住 `append_stdout()` 的 tail 裁剪语义、`get_public()` 的敏感字段隐藏语义，以及 `set_stage()` 的“只增不减进度”语义。
- 校验通过：`uv run python -m py_compile src/subtitle_maker/jobs/models.py src/subtitle_maker/jobs/store.py src/subtitle_maker/jobs/recovery.py src/subtitle_maker/jobs/__init__.py src/subtitle_maker/dubbing_cli_api.py tests/test_task_store.py tests/test_job_recovery.py tests/test_dubbing_cli_api.py`。
- Store / recovery 回归通过：`uv run python -m unittest tests.test_task_store tests.test_job_recovery`（`Ran 7 tests ... OK`）。
- API / manifest 回归通过：`uv run python -m unittest tests.test_dubbing_cli_api tests.test_manifest_contracts`（`Ran 46 tests ... OK`）。

## 2026-04-24 产品化重构 Phase 9（Web API routes）

- [x] Spec-1：审计 `web.py` 当前剩余路由职责、边界和已拆分现状
- [x] Spec-2：确认 `app/routes/*` 首轮拆分顺序、迁移范围和兼容策略
- [x] Spec-3：确认风险、验证方式与回退策略
- [x] HARD-GATE：等用户确认后实施
- [x] 实施：拆 Web API routes 并让 `web.py` 继续作为初始化 wrapper
- [x] 验证：语法检查 + API 回归

## Review（2026-04-24 产品化重构 Phase 9 Spec-1）
- `src/subtitle_maker/web.py` 已经不是“所有 API 都还在一个文件里”的最初状态：`app.include_router(streaming_router)`、`app.include_router(dubbing_router)`、`app.include_router(agent_router)` 已把流式 ASR、Auto Dubbing、Agent V1 抽到 [streaming_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/streaming_api.py:1)、[dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py:1)、[agent_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/agent_api.py:1)。所以 Phase 9 不该重复拆这三块，而应只处理 `web.py` 里尚未收口的 legacy routes。
- `src/subtitle_maker/web.py::index()`、`upload_video()`、`stream_video()` 这组入口仍直接绑在 app 初始化文件上，负责首页模板、媒体上传和原始视频回放。它们逻辑不复杂，但属于典型的“页面/媒体入口路由”，按目标架构更适合后续迁到 `app/routes/projects.py` 或相近的入口路由模块，而不是继续留在 `web.py` 顶层。
- 当前最重的一组仍是字幕主链路 legacy routes：`upload_srt()`、`transcribe_sync()`、`transcribe()`、`cancel_task()`、`get_status()` 都还在 `src/subtitle_maker/web.py`，并共享全局 `tasks: Dict[str, dict]` 与 `transcribe_task()`。其中 [transcribe_sync()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/web.py:252) 同时承担上传保存、临时任务创建、阻塞转写、可选翻译、文件清理；[transcribe()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/web.py:341) 同时承担表单解析、任务创建和后台调度；这说明它们不只是“路由声明没拆”，而是 request parsing、任务状态和业务调用还混在一起。
- 翻译与导出链路也还停留在 `web.py`：`translate()` 直接 new `Translator` 并读写全局 `tasks`，`export_subtitles()` 直接从任务内存或前端 JSON 回退、拼接双语字幕并落临时文件，`download_file()` 再直接暴露 `outputs/` 文件。也就是说，翻译/export 这两块现在仍是 route + service + 文件 IO 混合体，首轮拆分时应视作一个独立子域，而不是顺手夹在转写 routes 里一起搬。
- [segment_audio()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/web.py:733) 是当前 `web.py` 最不“route 化”的一段：它在单个 endpoint 里完成字幕切段、分句边界判断、短段再平衡、整轨 ffmpeg 转 wav、逐段切片、CSV 生成和 ZIP 打包。这一段的复杂度已经接近独立 service/domain，而不是简单 API 包装；它明显不适合在 Phase 9 第一刀和普通 upload/status 路由一起搬，需要单独看作“导出/切段 legacy endpoint”。
- 模型与项目管理也还绑在 `web.py`：`release_asr_model()`、`release_all_models()`、`get_index_tts_model_status()`、`start_index_tts_model_service()`、`release_index_tts_model_service()`、`stop_index_tts_model_service()`、`reset_project_storage()` 同时碰 ASR、Index-TTS、Auto Dubbing 取消和本地目录清理。尤其 [reset_project_storage()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/web.py:717) 会跨 uploads/outputs 和 dubbing 历史目录做清理，属于明显的项目级管理路由，不应继续和字幕/翻译/export endpoint 共处一层。
- 当前 `web.py` 的核心问题因此不是“装饰器太多”，而是还同时承担了三类职责：1) app 初始化与模板/static 挂载；2) legacy transcription/translation/export/project routes；3) 任务状态与文件系统副作用。根据 [docs/refactor/03-target-architecture.md](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/docs/refactor/03-target-architecture.md:96) 的边界，Phase 9 首轮更应该把 `web.py` 收成 app wrapper，把剩余 legacy routes 迁到 `app/routes/*` 或等价模块，而不是立刻改业务算法本身。
- 因为 `Phase 8` 刚完成的 Job Store 目前只覆盖 Auto Dubbing，`web.py` 里的普通转写 `tasks` 仍是另一套内存状态。所以 Phase 9 的首轮 route 拆分不能假设“所有状态层已经统一”；否则会把“路由搬家”升级成“legacy transcription 状态重构”，超出本阶段第一刀范围。

## Review（2026-04-24 产品化重构 Phase 9 Spec-2）
- 第一轮 route 拆分固定为“app 初始化 + legacy runtime + 5 个 route 模块”，具体文件为：
  - `src/subtitle_maker/app/main.py`
  - `src/subtitle_maker/app/legacy_runtime.py`
  - `src/subtitle_maker/app/routes/projects.py`
  - `src/subtitle_maker/app/routes/subtitles.py`
  - `src/subtitle_maker/app/routes/translation.py`
  - `src/subtitle_maker/app/routes/exports.py`
  - `src/subtitle_maker/app/routes/jobs.py`
  其中 `app/main.py` 负责 FastAPI app 创建、static/templates 挂载和 router include；`legacy_runtime.py` 负责承接当前 `src/subtitle_maker/web.py` 里仍共享的 `tasks`、`generator`、`get_generator()`、`release_generator()`、`transcribe_task()`、`cancel_active_transcriptions()`、目录清理 helper，避免新 route 反向 import `web.py` 形成循环依赖。
- `projects.py` 首轮承接低风险页面/文件入口：`index()`、`upload_video()`、`stream_video()`、`reset_project_storage()`。其中 [reset_project_storage()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/web.py:717) 虽然会触发目录清理和 Auto Dubbing 取消，但职责仍更接近“项目级入口与重置”，比放在 `jobs.py` 更符合目标架构里 `projects.py` 的定位。
- `subtitles.py` 首轮承接 legacy 字幕主链路：`upload_srt()`、`transcribe_sync()`、`transcribe()`。这三条入口都仍直接依赖 `tasks` 和 [transcribe_task()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/web.py:132)，所以应放在同一个 route 模块里，通过 `legacy_runtime.py` 共享状态与转写 helper，而不是拆成多个零碎 router 再横向 import。
- `jobs.py` 首轮承接控制面 endpoint：`cancel_task()`、`get_status()`、`release_asr_model()`、`release_all_models()`、`get_index_tts_model_status()`、`start_index_tts_model_service()`、`release_index_tts_model_service()`、`stop_index_tts_model_service()`。原因是这组接口的共同点不是“字幕内容”，而是运行态控制、状态读取和模型生命周期；同时它们已经和 [dubbing_cli_api.py::cancel_active_dubbing()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py:1668) 形成联动。
- `translation.py` 首轮只承接 [translate()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/web.py:409)，不顺手改 `Translator` 的调用方式，也不改变“任务内存优先，其次前端 JSON 回退”的现有语义。`exports.py` 首轮承接 `export_subtitles()`、`download_file()`、`segment_audio()`，其中 [segment_audio()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/web.py:733) 允许先按 verbatim 迁移，只做函数搬家，不在 Phase 9 第一刀顺手重写它的字幕切段/ffmpeg/ZIP 逻辑。
- 路径兼容策略固定为“文件变、URL 不变”。所有新 route module 第一轮都使用空前缀，保持现有 URL 面完全不变，因为前端 [src/subtitle_maker/static/app.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:555) 到 [src/subtitle_maker/static/app.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:1259) 直接硬编码了 `/project/reset`、`/model/all/release`、`/upload`、`/transcribe`、`/translate`、`/export`、`/segment`、`/upload_srt`。这一轮不能改成 `/api/*`、不能改返回字段名，也不能要求前端同步改 fetch 路径。
- 已拆出去的 `src/subtitle_maker/streaming_api.py`、`dubbing_cli_api.py`、`agent_api.py` 本轮不迁进 `app/routes/*`，只允许由 `app/main.py` 继续 include；否则会把“拆 legacy web routes”升级成“统一全部 router 目录结构”，扩大改动面。`src/subtitle_maker/web.py` 则在首轮实现后退化成 compatibility wrapper：保留 `app` 导出和 `start()` 启动入口，内部从 `app.main` 拿应用实例。
- 迁移顺序固定为：
  1. 先建 `app/main.py` 与 `app/legacy_runtime.py`，把 app 初始化和共享运行态从 `web.py` 中抽出；
  2. 再迁 `projects.py` + `jobs.py` 这组低风险控制面 route；
  3. 再迁 `subtitles.py` 与 `translation.py`；
  4. 最后迁 `exports.py`，其中 `segment_audio()` 只做 verbatim 搬迁；
  5. `web.py` 收成 wrapper；
  这样可以先稳定 app 装配和共享状态，再搬最重的 legacy route，避免一上来同时碰 app 初始化、任务状态和导出/切段逻辑。
- 第一轮明确不做：
  - 不把 `src/subtitle_maker/streaming_api.py`、`dubbing_cli_api.py`、`agent_api.py` 改名迁址；
  - 不统一普通转写 `tasks` 和 Auto Dubbing `TaskStore`；
  - 不重写 `segment_audio()` 算法；
  - 不把 URL 统一改成 `/api/*`；
  - 不改前端 `app.js` 的现有 fetch 协议；
  这些分别属于目录整洁、状态层统一、业务逻辑重构、外部 API 契约和前端配套改造，不进入 Phase 9 第一刀。

## Review（2026-04-24 产品化重构 Phase 9 Spec-3）
- 第一风险是把现有 URL 和返回结构拆坏。当前前端 [src/subtitle_maker/static/app.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:555) 到 [src/subtitle_maker/static/app.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:1259) 直接硬编码了 `/project/reset`、`/model/all/release`、`/upload`、`/transcribe`、`/translate`、`/export`、`/segment`、`/upload_srt`；首轮 route 拆分若改 URL、改字段名，前端会直接失效。因此第一轮必须坚持“文件变、URL 不变、返回结构不变”。
- 第二风险是把 app 启动和测试入口拆坏。当前 `tests/test_agent_api.py`、`tests/test_dubbing_cli_api.py` 都通过 `TestClient(web.app)` 访问应用；如果 `src/subtitle_maker/web.py` 在迁移后不再稳定导出 `app`，或 static/templates 挂载遗漏，测试和手工访问首页都会直接失败。所以 `web.py` 首轮只能退成 compatibility wrapper，不能消失。
- 第三风险是引入 import cycle。`web.py` 现在同时持有 app 初始化、legacy runtime、以及对 `dubbing_cli_api.py` / `agent_api.py` / `streaming_api.py` 的 include；若新 route module 再去反向 import `web.py` 里的 `tasks`、`templates`、`generator` 或 `release_generator()`，很容易形成循环依赖。首轮必须通过 `app/main.py` 和 `app/legacy_runtime.py` 明确切开“装配”和“共享运行态”。
- 第四风险是普通转写 `tasks` 的共享语义漂移。当前 `upload_srt()`、`transcribe_sync()`、`transcribe()`、`cancel_task()`、`get_status()`、`translate()`、`export_subtitles()`、`segment_audio()` 都直接依赖 `src/subtitle_maker/web.py` 里的全局 `tasks` 和 `transcribe_task()`；如果拆 route 时不保持同一个共享对象，而是各模块各自持有一份状态，轮询、取消、翻译和导出就会立刻失配。
- 第五风险是把模型/项目管理联动拆坏。`src/subtitle_maker/web.py::release_all_models()` 当前同时调用 `cancel_active_transcriptions()`、`cancel_active_dubbing()`、`release_generator()`、`release_index_tts_model()`；`reset_project_storage()` 又会跨 uploads/outputs 和 dubbing 历史目录清理。首轮 route 拆分不能改变这些控制面 side effect 的触发顺序和返回字段，否则会影响现有前端按钮和 `tests/test_dubbing_cli_api.py::test_model_all_release_reports_auto_task_count()`。
- 第六风险是把 `segment_audio()` 的业务逻辑在“搬路由”时顺手改坏。它现在在一个 endpoint 里完成字幕重分组、ffmpeg 切片、CSV 生成和 ZIP 打包；Phase 9 第一刀只允许 verbatim 搬迁，不允许借机改分段边界、文件命名、ZIP 内容或错误语义。
- 当前护栏存在明显缺口：现有测试主要覆盖 Agent 和 Auto Dubbing，几乎没有直接冻结 `/upload`、`/upload_srt`、`/transcribe`、`/translate`、`/export`、`/segment` 这些 legacy route 的行为。因此首轮实现时必须补一组新的 web route smoke tests，至少覆盖上传、SRT 上传、普通转写状态轮询、翻译/导出、以及项目重置/模型释放的基础行为；否则不能声称 route 拆分已经被验证。
- 首轮验证固定为四层：
  1. 语法：`uv run python -m py_compile src/subtitle_maker/app/main.py src/subtitle_maker/app/legacy_runtime.py src/subtitle_maker/app/routes/projects.py src/subtitle_maker/app/routes/subtitles.py src/subtitle_maker/app/routes/translation.py src/subtitle_maker/app/routes/exports.py src/subtitle_maker/app/routes/jobs.py src/subtitle_maker/web.py`
  2. 现有 router 护栏：`uv run python -m unittest tests.test_agent_api tests.test_dubbing_cli_api`
  3. 新增 legacy web route smoke tests：`uv run python -m unittest tests.test_web_routes_legacy`
  4. 如 route 拆分触及 legacy tasks/shared runtime，再补最小首页加载/模板挂载 smoke 检查，确保 `/`、`/static/*`、`/stream/{filename}` 仍可访问。
- 回退策略固定为“按 route 组回退，不整阶段回退”：
  - 若 `app/main.py` / `web.py` wrapper 导致启动失败，只回退 app 装配层，保留已迁出的 route 文件内容；
  - 若 `projects.py` / `jobs.py` 控制面拆分引发路径或返回漂移，只回退对应 router include；
  - 若 `subtitles.py` / `translation.py` / `exports.py` 引发 legacy tasks 状态失配，只回退这一组 route 到 `web.py`，不回退已经稳定的 app/main 与 wrapper 结构。
- HARD-GATE 前的结论：
  这轮 Phase 9 的实现目标是“把 `web.py` 收成 app wrapper，并迁出剩余 legacy routes”，不是“同时统一普通转写状态层或重写导出/切段逻辑”；
  只有在你明确确认后，才进入代码实现。

## Review（2026-04-24 产品化重构 Phase 9 实施）
- 已新增 `src/subtitle_maker/app/main.py`、`src/subtitle_maker/app/legacy_runtime.py`、`src/subtitle_maker/app/routes/`，把 FastAPI app 装配、legacy 共享运行态和剩余 legacy routes 分开：`main.py` 负责 app 创建和 router include，`legacy_runtime.py` 承接普通转写 `tasks`、ASR model、`transcribe_task()`、目录清理 helper，`routes/*` 承接剩余 HTTP 路由。
- 已新增 route 模块：
  - `src/subtitle_maker/app/routes/projects.py`
  - `src/subtitle_maker/app/routes/subtitles.py`
  - `src/subtitle_maker/app/routes/translation.py`
  - `src/subtitle_maker/app/routes/exports.py`
  - `src/subtitle_maker/app/routes/jobs.py`
  现有 URL 保持不变，`streaming_api.py`、`dubbing_cli_api.py`、`agent_api.py` 继续由 `app/main.py` 直接 include，没有在这一轮迁址。
- `src/subtitle_maker/web.py` 已收成 compatibility wrapper：继续导出 `app` 和 `start()`，并 re-export 现有测试还会 patch 的旧符号，例如 `cancel_active_transcriptions`、`release_generator`、`get_index_tts_status`、`release_index_tts_model`、`cancel_active_dubbing`、`HTTPException`，避免现有测试和旧入口立刻断掉。
- `src/subtitle_maker/app/routes/jobs.py` 的模型控制 endpoint 通过延迟读取 `subtitle_maker.web` 来调用这些兼容导出，保证 `tests/test_dubbing_cli_api.py` 里对 `web.*` 的 patch 仍然生效；这是当前迁移期为了兼容旧测试刻意保留的一层桥接。
- `src/subtitle_maker/app/routes/exports.py::segment_audio()` 本轮只做 verbatim 搬迁，没有顺手改它的字幕切段、ffmpeg 切片、CSV/ZIP 打包逻辑；普通转写 `tasks` 也仍保留在 `legacy_runtime.py`，没有和 Auto Dubbing `TaskStore` 合并。
- 已新增 `tests/test_web_routes_legacy.py`，补上当前缺失的 legacy web route smoke tests，覆盖首页加载、媒体上传/回放、SRT 上传、普通转写状态轮询、翻译/导出，以及项目重置和 `/segment` 入口存在性。
- 校验通过：`uv run python -m py_compile src/subtitle_maker/app/__init__.py src/subtitle_maker/app/main.py src/subtitle_maker/app/legacy_runtime.py src/subtitle_maker/app/routes/__init__.py src/subtitle_maker/app/routes/projects.py src/subtitle_maker/app/routes/subtitles.py src/subtitle_maker/app/routes/translation.py src/subtitle_maker/app/routes/exports.py src/subtitle_maker/app/routes/jobs.py src/subtitle_maker/web.py tests/test_web_routes_legacy.py`。
- 新增 smoke tests 通过：`uv run python -m unittest tests.test_web_routes_legacy`（`Ran 4 tests ... OK`）。
- 现有 router 护栏通过：`uv run python -m unittest tests.test_agent_api tests.test_dubbing_cli_api`（`Ran 45 tests ... OK`）。

## 2026-04-25 产品化重构 Phase 10（前端 JS 模块拆分）

- [x] Spec-1：审计 `static/app.js` 当前职责、耦合点和首轮可拆边界
- [x] Spec-2：确认首轮模块划分、迁移顺序和兼容策略
- [x] Spec-3：确认风险、验证方式和回退策略
- [x] HARD-GATE：等用户确认后实施
- [x] 实施：拆前端 JS 模块并让 `app.js` 退成入口
- [x] 验证：语法检查 + 前端最小回归

## Review（2026-04-25 产品化重构 Phase 10 Spec-1）
- 当前前端仍是单脚本入口：`src/subtitle_maker/templates/index.html` 只通过 [script 标签](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html:755) 加载 `src/subtitle_maker/static/app.js`，没有第二层前端模块装配。这意味着 `Phase 10` 第一刀必须保留 `/static/app.js` 这个入口，不能要求模板、URL 或 HTML 面板结构同步大改。
- `src/subtitle_maker/static/app.js` 当前约 `2913` 行，顶层同时维护共享页面状态与持久化：例如 [saveState()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:422)、[loadState()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:440)、[clearState()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:544) 直接读写 `currentTaskId`、`currentFilename`、`originalSubtitlesData`、`translatedSubtitlesData`、`transcriptionStartTime`，并把这些字段散落到多个 `localStorage` key。说明当前问题不只是“文件太长”，而是共享状态、恢复逻辑和 UI 事件没有边界。
- legacy 字幕工作流仍紧耦合在一个脚本里：上传入口 [handleMediaUpload()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:725)、普通转写轮询 [pollStatus()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:913)、导出绑定 [bindExportButtons()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:1111)、SRT 导入 [handleSrtUpload()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:1244) 共用同一批全局字幕状态；它们又直接消费 `panel-upload`、`panel-transcribe`、`panel-results`、`panel-srt` 这些 DOM 容器（见 [index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html:124)、[index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html:583)、[index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html:652)、[index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html:137)）。这说明首轮不适合从 legacy 字幕工作流下刀，否则会立刻碰到共享状态和播放器联动。
- Auto Dubbing 已经是当前最接近“独立模块”的前端子域：`DOMContentLoaded` 里两次实例化 [setupAutoDubbing()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:1668)，分别绑定 `panel-auto-dub` 和 `panel-auto-dub-v2`（见 [index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html:150)、[index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html:364)），内部已经自带 review、load-batch、轮询、结果渲染与 API key 持久化。这一块虽然体量大，但边界相对集中，适合作为首轮主拆分对象。
- Agent 抽屉已经天然是独立 UI 岛：[setupAgentDrawer()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:2758) 只依赖 `agent-*` DOM、`sessionStorage` 和 `/api/agent/chat`，对应容器也集中在 [index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html:735) 附近。它对 legacy 字幕状态、播放器和 Auto Dubbing 主循环没有反向依赖，明显适合和 Auto Dubbing 一起优先迁出。
- 当前 `app.js` 里大约有 `22` 处 `fetch(...)` 调用，覆盖 `/upload`、`/transcribe`、`/status/*`、`/translate`、`/export`、`/segment`、`/dubbing/auto/*`、`/api/agent/chat` 等多组接口；但这些调用目前并没有统一 client 层。因此 `Phase 10` 第一刀不应该先从“统一所有 API client”开始，那会把整个文件都一起改动；更合理的是先搬走已相对封闭的 `agentDrawer` 和 `dubbingPanel`，再在第二刀收口共享状态/API helper。
- 现状结论：`Phase 10` 的第一目标不该是“把整个前端一次性拆干净”，而应是让 `src/subtitle_maker/static/app.js` 从“所有逻辑都在里面”退成 bootstrap 入口。首轮最自然的候选模块是：
  - `src/subtitle_maker/static/js/agentDrawer.js`
  - `src/subtitle_maker/static/js/dubbingPanel.js`
  同时保留现有 DOM id、现有 fetch 路径、现有 `window.triggerSrtLoad` 语义和 `/static/app.js` 入口不变。

## Review（2026-04-25 产品化重构 Phase 10 Spec-2）
- 首轮文件划分固定为三块，而不是一上来铺满目标架构里的所有前端模块：
  - `src/subtitle_maker/static/app.js`
  - `src/subtitle_maker/static/js/agentDrawer.js`
  - `src/subtitle_maker/static/js/dubbingPanel.js`
  其中 `app.js` 保留为迁移期入口和共享状态装配层；`agentDrawer.js` 承接 [setupAgentDrawer()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:2758)；`dubbingPanel.js` 承接 [setupAutoDubbing()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:1668) 及其 review/load-batch/轮询子逻辑。这样可以先拆最封闭的两块 UI 岛，不在第一刀同时重写 legacy 上传/翻译/导出链路。
- 脚本装配策略经反向同步后固定为“保留旧 URL + 保留 classic script 入口 + 用原生 `import()` 装配子模块”。原因有两点：第一，[index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html:755) 当前只有一个 `/static/app.js` script 入口，没有 bundler 和第二层装配；第二，保留 classic script 可以继续直接跑 `node --check src/subtitle_maker/static/app.js`，不需要把模板改成 `type=module` 或引入额外构建语义。模板里唯一显式的 inline 依赖仍是 [load-srt 按钮的 `window.triggerSrtLoad`](</Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html:107>)，而 `app.js` 会继续在 [1455 行附近](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:1455) 保留这条桥接，因此不需要改模板入口。
- `agentDrawer.js` 首轮设计为“完全自包含模块”：只接管 `agent-*` DOM、`sessionStorage` 和 `/api/agent/chat` 调用，不读取 legacy 字幕状态，也不改播放器和 Auto Dubbing 的共享变量。因为 [setupAgentDrawer()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:2758) 当前边界已经很干净，所以这块应该第一个迁出，用最小代价验证前端模块装配链路是通的。
- `dubbingPanel.js` 首轮不负责“抽象所有前端通用能力”，只负责承接 Auto Dubbing V1/V2 这一块现有抽象：`app.js` 继续在 `DOMContentLoaded` 中调用两次 `setupAutoDubbing(config, deps)`，分别绑定 `panel-auto-dub` 和 `panel-auto-dub-v2`。新模块通过依赖注入接收它真正需要的共享能力，例如 `videoPlayer`、`videoPlaceholder`、`renderSubtitles()`、`saveState()`、`syncDubbingLanguage()`、`secondsToDisplay()`、`buildAutoDubElapsedLabel()`、`normalizeShortMergeTargetSeconds()`，以及对 `originalSubtitlesData` / `translatedSubtitlesData` 的读写 accessors；而不是在第一轮额外新建一个“大一统 frontend store”。
- `player.js`、`subtitleWorkflow.js`、统一 `apiClient.js`、`reviewPanel.js` 这一轮明确不做。依据是现有 legacy 工作流和播放器共享状态耦合太重：例如 [saveState()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:422)、[loadState()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:440)、[handleMediaUpload()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:725)、[pollStatus()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:913)、[bindExportButtons()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:1111) 还都共用同一批字幕/任务状态。如果第一刀就拆这些模块，会把“文件搬家”升级成“状态层重写”。
- 迁移顺序固定为：
  1. 先让 `src/subtitle_maker/templates/index.html` 继续引用 `/static/app.js`，但把入口切到 ESM 语义；
  2. 先迁 `agentDrawer.js`，验证单模块 import/export、事件绑定和会话存储不回归；
  3. 再迁 `dubbingPanel.js`，保留当前 `setupAutoDubbing()` 的双实例模式；
  4. `app.js` 最后只做 bootstrap、共享 helper、legacy workflow 和 `window.triggerSrtLoad` 桥接。
  这样先验证最独立的 Agent，再处理体量更大的 Auto Dubbing，能把回归面压在最小范围内。
- 当前 [1487 行附近的旧 `dubbing/start` 逻辑](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:1487) 这一轮也不纳入新模块。原因不是它重要，而是它当前已经基本处于“休眠代码”状态：现有 [index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html:1) 里已经没有 `start-dubbing-btn`、`dub-target-lang`、`dubbing-results` 这些 DOM 节点。首轮模块拆分不应顺手把它改写成新模块；这属于后续 `Phase 11` 的旧代码清理范围。
- 兼容策略固定为：
  - 继续保留 `/static/app.js?v={{ app_js_version }}` 入口；
  - 不改现有 DOM id；
  - 不改任何 fetch 路径和返回字段；
  - 不改现有 `localStorage` / `sessionStorage` key；
  - 不新增前端构建步骤，仍由 FastAPI `StaticFiles` 直接服务静态资源。

## Review（2026-04-25 产品化重构 Phase 10 Spec-3）
- 第一风险是 ESM 迁移后把静态资源缓存语义改坏。当前首页只给 [app.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html:755) 带了 `?v={{ app_js_version }}`，这个版本号来自 [projects.py::index()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/app/routes/projects.py:17) 调用 [legacy_runtime._static_version()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/app/legacy_runtime.py:44)。如果首轮改成 ESM 后让 `app.js` 静态 import `static/js/*.js`，子模块 URL 默认不会自动继承这个版本号，浏览器可能继续命中旧缓存。首轮实现必须显式把 `app.js` 当前 URL 上的版本参数透传给子模块导入路径，避免“入口更新了，子模块还是旧代码”的半刷新状态。
- 第二风险是把共享状态拆漂。当前 Auto Dubbing 完成后会直接回写 [originalSubtitlesData](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:29)、[translatedSubtitlesData](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:30)、`saveState()`、`renderSubtitles()`，并驱动播放器 overlay 与结果面板联动；相关写入分散在 [autoLoadAutoDubSubtitles()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:2094)、[renderResults()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:2673) 等位置。如果 `dubbingPanel.js` 首轮复制一份本地状态，而不是经由 getter/setter 或 callback 回写共享状态，页面会立刻出现“结果面板更新了，但播放器字幕/导出还指向旧数据”的失配。
- 第三风险是引入模块循环依赖。`Phase 10` 首轮里 `app.js` 既是入口，又仍持有大量 helper 和 legacy workflow；如果新模块反向 import `app.js` 获取 `saveState()`、`syncDubbingLanguage()`、`renderSubtitles()`，很容易形成循环加载。因此首轮必须坚持单向依赖：`app.js` import 新模块，新模块只消费传入的 `deps`，不反向 import 入口。
- 第四风险是把全局桥接点拆坏。当前模板只有一个明确依赖全局对象的地方：`index.html` 的 [Load Local Subtitles 按钮](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html:107) 通过 `window.triggerSrtLoad()` 触发，而 [app.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:1455) 在 `DOMContentLoaded` 中挂了这个函数。ESM 迁移后模块作用域默认不暴露到 `window`，所以首轮必须显式保留这个桥接点；否则页面不会报编译错，但按钮会在运行时静默失效。
- 第五风险是“拆文件成功，但浏览器行为没人验证”。当前现有测试只覆盖后端路由与 API：`tests.test_web_routes_legacy` 只能证明首页能返回 HTML，不能证明模块脚本真的执行；仓库里也没有前端单测来锁住 Agent 抽屉或 Auto Dubbing 面板。因此首轮不能只做 `node --check` 就宣称完成，必须补上最小浏览器 smoke。
- 首轮验证固定为四层：
  1. 语法：`node --check src/subtitle_maker/static/app.js src/subtitle_maker/static/js/agentDrawer.js src/subtitle_maker/static/js/dubbingPanel.js`
  2. 现有后端护栏：`uv run python -m unittest tests.test_web_routes_legacy tests.test_agent_api tests.test_dubbing_cli_api`
  3. 首页入口护栏：补一个最小 HTML/assertion，确认首页仍引用 `/static/app.js`，且模板没有把入口路径切断
  4. 浏览器 smoke：实际打开首页，至少验证 Agent 抽屉可打开/发送、Auto Dubbing V1/V2 面板可切换且无首屏 JS 报错
- 回退策略固定为“先回退子模块接线，再回退入口语义”：
  - 若 `agentDrawer.js` 迁出导致聊天抽屉失效，只回退 Agent 模块接线；
  - 若 `dubbingPanel.js` 迁出导致 V1/V2 轮询或 review 失效，只回退 Auto Dubbing 模块接线；
  - 只有当 ESM 入口本身导致整页脚本不执行时，才回退 `app.js` 入口语义，保留已迁出的模块文件内容。
- HARD-GATE 前的结论：
  这轮 `Phase 10` 的实现目标是“先把 Agent 抽屉和 Auto Dubbing 从 `app.js` 里迁出去，并让 `app.js` 退成入口”，不是“同时重写前端状态层、播放器、字幕工作流或引入完整前端工程化”；
  只有在你明确确认后，才进入代码实现。

## Review（2026-04-25 产品化重构 Phase 10 实施）
- 已新增前端子模块：
  - [src/subtitle_maker/static/js/agentDrawer.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/agentDrawer.js:1)
  - [src/subtitle_maker/static/js/dubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/dubbingPanel.js:1)
  其中 `agentDrawer.js` 承接原 [setupAgentDrawer()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:1697) 的抽屉交互与会话逻辑，`dubbingPanel.js` 承接 Auto Dubbing V1/V2、review、load-batch、轮询和结果渲染。
- [src/subtitle_maker/static/app.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:1) 已从约 `2913` 行收窄到 `1708` 行，保留为 classic script 入口和 legacy workflow 装配层；首轮没有把模板改成 `type=module`，而是通过 [loadFrontendModule()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:65) 使用浏览器原生 `import()` 动态装配子模块。这是本轮按 `Reverse Sync` 做的实现调整，用来保住 `node --check` 验证链和现有模板入口。
- 为了避免“只改子模块但浏览器继续命中旧缓存”，[src/subtitle_maker/app/legacy_runtime.py::_static_version()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/app/legacy_runtime.py:44) 现在会在 `filename == "app.js"` 时同时考虑 `static/app.js` 与 `static/js/*.js` 的最新 mtime；`app.js` 再把当前版本参数透传给 `agentDrawer.js` 和 `dubbingPanel.js`，保证入口脚本与子模块一起刷新。
- 为了避免 Auto Dubbing 模块复制一份字幕状态，[app.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:1045) 新增 `applyAutoDubSubtitleItems()` 作为共享状态桥接：模块内只把产出的字幕列表回写给这个入口 helper，再由入口统一更新 `originalSubtitlesData`、`translatedSubtitlesData`、overlay mode 和 `localStorage`。
- 兼容边界保持住了：
  - `src/subtitle_maker/templates/index.html` 仍只引用 `/static/app.js?v=...`
  - 现有 DOM id 不变
  - 现有 fetch 路径和返回字段不变
  - 现有 `window.triggerSrtLoad` 桥接仍保留
  - 旧 `dubbing/start` 那段休眠逻辑没有在这轮顺手重写
- 已新增首页入口护栏：[tests/test_web_routes_legacy.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_web_routes_legacy.py:1) 现在会检查首页 HTML 仍包含 `/static/app.js?v=`，避免后续误切断主入口。
- 校验通过：
  - `node --check src/subtitle_maker/static/app.js`
  - `node --check src/subtitle_maker/static/js/agentDrawer.js`
  - `node --check src/subtitle_maker/static/js/dubbingPanel.js`
  - `uv run python -m py_compile src/subtitle_maker/app/legacy_runtime.py tests/test_web_routes_legacy.py`
  - `uv run python -m unittest tests.test_web_routes_legacy tests.test_agent_api tests.test_dubbing_cli_api`（`Ran 49 tests ... OK`）
- 浏览器 smoke 已完成：
  - 通过仓库自带 `start.sh` 拉起本地站点后，首页实际请求到了 `/static/app.js?v=...`、`/static/js/dubbingPanel.js?v=...`、`/static/js/agentDrawer.js?v=...`
  - Chrome 实测可打开 Agent 抽屉并发送消息
  - `Auto Dubbing` 与 `Auto Dubbing V2` 面板可正常切换并渲染首屏控件

## 2026-04-25 产品化重构 Phase 11（清理旧脚本和重复代码）
- [x] Spec-1：审计当前残留旧入口、休眠逻辑和重复 helper，确认首批清理目标
- [x] Spec-2：确认 Phase 11 首轮模块边界、迁移顺序和最小改动范围
- [x] Spec-3：锁定风险、验证方式和回退策略
- [x] HARD-GATE：已确认并开始实现

## Review（2026-04-25 产品化重构 Phase 11 Spec-1）
- [src/subtitle_maker/web.py::start()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/web.py:34) 现在已经是迁移期启动 wrapper：文件本体只继续从 `subtitle_maker.app.main` 引用 `app`，并从 `subtitle_maker.app.legacy_runtime` / `subtitle_maker.dubbing_cli_api` / `subtitle_maker.index_tts_service` 透出旧启动面。这说明 `web.py` 当前更像兼容入口，不是 Phase 11 第一批该清的“重复实现”。
- [tools/dub_pipeline.py::synthesize_segments_grouped()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_pipeline.py:2742) 和 [tools/dub_pipeline.py::synthesize_segments()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_pipeline.py:2818) 已明确标成“兼容旧入口”，前面大量字幕 / 对齐 / backend helper 也都写成 facade。因此 `tools/dub_pipeline.py` 现阶段的主要职责已经是兼容 CLI 与旧调用面，不适合作为 Phase 11 第一刀的大清理对象。
- [tools/repair_bad_segments.py::run_cmd()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/repair_bad_segments.py:55) 起始这一段已经把 `run_cmd()`、`audio_duration()`、`build_atempo_filter_chain()`、`compose_vocals_master()`、`mix_with_bgm()` 等 helper 转成“兼容旧入口” facade，真实实现来自 `subtitle_maker.backends`、`subtitle_maker.core.ffmpeg`、`subtitle_maker.domains.dubbing`、`subtitle_maker.domains.media`。这说明它虽仍是脚本入口，但重复 helper 已大幅收口，优先级低于真正还在独立复制 app/bootstrap 的旧入口。
- [tools/dub_long_video.py::main()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py:705) 仍然真实承载长视频分段编排：参数解析、切段计划、segment job 目录准备、音频提取、silence 边界选择、batch manifest 写入都在这里。它当前更像“仍然有业务所有权的 orchestration script”，不是单纯遗留重复代码；Phase 11 首轮不应把它误当成休眠 wrapper 去清理。
- [src/subtitle_maker/simple_web.py::translate_srt_content()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/simple_web.py:23)、[index()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/simple_web.py:58)、[translate()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/simple_web.py:68)、[download()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/simple_web.py:133)、[start()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/simple_web.py:140) 仍然组成一套完整的独立 FastAPI 应用：自己创建 `FastAPI`、挂 `StaticFiles`、建模板、收上传、落盘输出、启动 `uvicorn`。和已经 wrapper 化的 `src/subtitle_maker/web.py` 相比，它仍是 Phase 11 最明显的旧入口候选。
- [src/subtitle_maker/static/app.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:1521) 里仍保留整段旧 `Dubbing Logic (Step 5)`：`start-dubbing-btn`、`dub-target-lang`、`dubbing-results`、`renderDubbingResults()` 等旧 UI 逻辑仍在脚本中；但当前模板 [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html:1) 已经不再渲染这些 DOM id（本轮通过 `rg` 核对无命中）。这说明它属于“休眠代码”，是 Phase 11 第一批最合适的前端清理目标。
- `Phase 11 Spec-1` 的现状结论已经固定：
  - 首批清理目标优先放在 `src/subtitle_maker/simple_web.py` 和 `src/subtitle_maker/static/app.js` 里的旧 `dubbing/start` 休眠逻辑；
  - `src/subtitle_maker/web.py`、`tools/dub_pipeline.py`、`tools/repair_bad_segments.py` 当前继续保留为兼容入口；
  - `tools/dub_long_video.py` 继续保留为长视频业务编排脚本，不在首轮“旧脚本清理”范围内。
- 本段只完成现状审计与目标收敛，尚未进入实现；下一步应按流程进入 `Spec-2`。

## Review（2026-04-25 产品化重构 Phase 11 Spec-2）
- `Phase 11` 首轮精确改动范围固定为 4 个位置：
  - `src/subtitle_maker/static/app.js`
  - `src/subtitle_maker/simple_web.py`
  - `src/subtitle_maker/app/legacy_simple_app.py`（新增）
  - `tests/test_simple_web_legacy.py`（新增最小护栏）
  其中前两个是直接清理面，后两个只用于把 `simple_web.py` 收成 legacy wrapper 并补最小可运行验证；这一轮不扩散到 `app/main.py`、`dubbing_cli_api.py` 或 `tools/*`。
- 前端侧首轮只删除 [src/subtitle_maker/static/app.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:1521) 里当前模板已不再使用的旧 `Dubbing Logic (Step 5)`，以及与之强绑定的 `start-dubbing-btn` / `dubbing-status-*` / `dubbing-results` / `renderDubbingResults()` 代码。因为当前主配音 API 已经切到 [src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py:39) 的 `/dubbing/auto` 路由，而 `app.js` 里的旧逻辑仍在请求 `/dubbing/start`；现状检索中这个旧路径只剩前端死代码在引用，所以首轮不需要为它保留兼容实现。
- `app.js` 里的语言同步 helper 也只做最小收口：把 [loadState()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:453) 与 [syncDubbingLanguage()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:544) 中的 `dub-target-lang` 从同步列表里移除，只保留当前真实存在的 `auto-dub-target` 和 `auto-dub-v2-target`。除此之外，不触碰 `agentDrawer.js`、`dubbingPanel.js`、播放器、上传/翻译/导出链路。
- `simple_web.py` 首轮不直接删除，也不把它的路由并入主站。原因是 [pyproject.toml](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/pyproject.toml:29) 仍对外发布 `subtitle-maker-simple-web = "subtitle_maker.simple_web:start"`，说明它现在仍是一个可执行兼容入口；但主站启动脚本 [start.sh](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/start.sh:100) 只拉起 `subtitle-maker-web`，目标架构文档 [docs/refactor/03-target-architecture.md](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/docs/refactor/03-target-architecture.md:149) 也只明确要求 `subtitle-maker-web` 保持兼容。因此这轮最稳妥的做法是“保留脚本名，收窄实现面”，而不是贸然删除控制台入口。
- `simple_web.py` 的首轮迁移方式也固定了：
  1. 把真正的 simple FastAPI app 创建、模板/static 挂载、`translate_srt_content()`、`index()`、`translate()`、`download()` 收进新模块 `src/subtitle_maker/app/legacy_simple_app.py`
  2. 让 [src/subtitle_maker/simple_web.py::start()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/simple_web.py:140) 退成 wrapper，只暴露 `app` 和 `start`
  3. `pyproject.toml` 里的 `subtitle-maker-simple-web` 首轮保持不变
  这样可以把“旧 simple app”显式归档为 legacy app，同时不打断当前仍可执行的脚本名。
- 这一轮明确不做：
  - 不把 `simple_web.py` 的 `/translate`、`/download/{filename}` 并到主站 [src/subtitle_maker/app/routes/translation.py::translate()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/app/routes/translation.py:15) 或 [exports.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/app/routes/exports.py:89)
  - 不删除 `subtitle-maker-simple-web` console script
  - 不重写 [src/subtitle_maker/templates/simple_index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/simple_index.html:1) 的 UI
  - 不触碰 `src/subtitle_maker/web.py`、`tools/dub_pipeline.py`、`tools/repair_bad_segments.py`、`tools/dub_long_video.py`
- 首轮迁移顺序固定为：
  1. 先清 `app.js` 里的休眠旧配音逻辑
  2. 再新增 `app/legacy_simple_app.py` 承接 simple legacy app
  3. 最后让 `simple_web.py` 变成 wrapper，并补 `tests/test_simple_web_legacy.py`
- 本段只锁定模块边界和迁移顺序，尚未开始实现；下一步应按流程进入 `Spec-3`。

## Review（2026-04-25 产品化重构 Phase 11 Spec-3）
- 第一风险是 `simple_web.py` 搬家后模板 / static 根目录算错。当前 [src/subtitle_maker/simple_web.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/simple_web.py:15) 直接基于自身文件位置计算 `BASE_DIR / TEMPLATES_DIR / STATIC_DIR`，所以一旦真实 app 下沉到 `src/subtitle_maker/app/legacy_simple_app.py`，如果仍沿用同样的 `__file__` 推导方式，就会把模板目录误算成 `src/subtitle_maker/app/templates`。首轮迁移必须显式复用 `subtitle_maker` 根目录，或直接复用 [src/subtitle_maker/app/legacy_runtime.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/app/legacy_runtime.py:16) 的静态资源根，而不能靠“搬过去之后自然还能找到模板”这种假设。
- 第二风险是打断 `subtitle-maker-simple-web` 的兼容启动面。当前 [pyproject.toml](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/pyproject.toml:30) 仍把 console script 绑定到 `subtitle_maker.simple_web:start`；同时 `simple_web.py` 还直接暴露模块级 `app` 并在 [start()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/simple_web.py:140) 里 `uvicorn.run("subtitle_maker.simple_web:app", ...)`。因此首轮 wrapper 化时，`simple_web.py` 不能只剩一个转发 `start()` 的空壳，必须继续暴露可导入的 `app`，否则 console script 和任何直接引用 `subtitle_maker.simple_web:app` 的启动方式都会失效。
- 第三风险是删 `app.js` 休眠逻辑时误删共享依赖。当前旧 `Dubbing Logic (Step 5)` 代码块位于 [src/subtitle_maker/static/app.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:1521)，而后面的模块装配入口位于 [同文件 1677 行附近](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:1677)。这意味着首轮可以删除旧 block，但必须保证删除边界只覆盖 `start-dubbing-btn`、`dubbing-status-*`、`dubbing-results`、`renderDubbingResults()` 和 `currentDubTaskId`，不能误碰后续的 `subtitle position toggle`、`loadFrontendModule()`、`setupDubbingPanels()`、`setupAgentDrawer()`。
- 第四风险是删完旧 block 之后仍残留无效 DOM / 路由引用。当前检索结果表明：
  - [src/subtitle_maker/static/app.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:1567) 还在请求 `/dubbing/start`
  - [src/subtitle_maker/static/app.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:536) 与 [syncDubbingLanguage()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:544) 仍把 `dub-target-lang` 放进语言同步列表
  - 当前仓库中对 `/dubbing/start` 的检索已只剩这段前端休眠逻辑，而模板里也不再存在这些 DOM
  所以首轮必须把这些残留引用一起清掉，否则代码表面删了主块，实际上仍会保留死 route / 死 DOM 名称。
- 第五风险是把 `simple_web.py` 清理误扩散成“合并旧 simple app 与主站翻译 route”。当前主站翻译入口已经是 [src/subtitle_maker/app/routes/translation.py::translate()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/app/routes/translation.py:15)，但它的输入协议是 `task_id / subtitles_json / api_key`；而 `simple_web.py::translate()` 走的是上传 `.srt` 文件、模板返回、再落盘下载。两者协议和产品形态完全不同，所以这一轮不得借清理名义把它们硬并，否则会把“旧入口归档”变成“翻译产品流程重写”。
- 首轮验证固定为四层：
  1. 前端语法：`node --check src/subtitle_maker/static/app.js`
  2. Python 语法：`uv run python -m py_compile src/subtitle_maker/app/legacy_simple_app.py src/subtitle_maker/simple_web.py`
  3. 路由回归：`uv run python -m unittest tests.test_simple_web_legacy tests.test_web_routes_legacy`
  4. 浏览器最小 smoke：确认首页仍可加载 `app.js`，`Auto Dubbing` / `Auto Dubbing V2` 面板首屏无脚本报错；同时 simple legacy app 至少能返回上传页和下载页
- 回退策略固定为两段式：
  - 若 `legacy_simple_app.py` 下沉后导致模板找不到、console script 启动失败或 simple 下载链路异常，只回退 `simple_web.py` wrapper 化，把 app 实现临时放回原文件；不回退已经确认无关的 `app.js` 清理。
  - 若 `app.js` 删休眠逻辑后影响首页脚本执行或 Auto Dubbing 面板首屏，只回退前端死代码清理；不回退 `simple_web.py` 的 legacy app 收口。
- HARD-GATE 前的结论：
  这轮 `Phase 11` 的实现目标是“清理已失效的旧前端配音逻辑，并把 simple legacy app 显式归档为 wrapper + legacy module”，不是“合并旧 simple app 到主站”或“删除所有兼容入口”；
  只有在你明确确认后，才进入代码实现。

## Review（2026-04-25 产品化重构 Phase 11 实施）
- 已新增 [src/subtitle_maker/app/legacy_simple_app.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/app/legacy_simple_app.py:1)，把旧 simple app 的真实实现收口到单独 legacy 模块中：这里继续承接 `translate_srt_content()`、上传页 `/`、翻译页 `/translate`、下载页 `/download/{filename}`，并且显式基于 `subtitle_maker` 根目录定位模板与静态资源，避免搬家后把路径算到 `src/subtitle_maker/app/*`。
- [src/subtitle_maker/simple_web.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/simple_web.py:1) 现已退成 wrapper：模块级继续暴露 `app`，`start()` 继续保留 `uvicorn.run("subtitle_maker.simple_web:app", ...)`，因此 [pyproject.toml](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/pyproject.toml:30) 里的 `subtitle-maker-simple-web` 没有被打断。
- [src/subtitle_maker/static/app.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:533) 已删掉旧 `Dubbing Logic (Step 5)` 整段休眠逻辑，并同步收口语言同步列表里的 `dub-target-lang` 残留引用；本轮残留检索已确认 `app.js` 与模板中都不再出现 `/dubbing/start`、`start-dubbing-btn`、`dubbing-status-container`、`dubbing-results`、`dub-target-lang`。
- 已新增 [tests/test_simple_web_legacy.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_simple_web_legacy.py:1)，覆盖 legacy simple wrapper 的最小兼容面：
  - 上传页可访问
  - 上传 `.srt` 后可生成下载文件
  - 缺失文件下载会重定向回首页
  这样 `simple_web.py` 的 wrapper 化不再只靠手工验证。
- 本轮没有扩散到 Spec 外：
  - 未改主站 [src/subtitle_maker/app/routes/translation.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/app/routes/translation.py:15)
  - 未删 `subtitle-maker-simple-web`
  - 未动 [src/subtitle_maker/web.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/web.py:1)、[tools/dub_pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_pipeline.py:1)、[tools/repair_bad_segments.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/repair_bad_segments.py:1)、[tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py:705)
- 校验通过：
  - `node --check src/subtitle_maker/static/app.js`
  - `uv run python -m py_compile src/subtitle_maker/app/legacy_simple_app.py src/subtitle_maker/simple_web.py`
  - `uv run python -m unittest tests.test_simple_web_legacy tests.test_web_routes_legacy`（`Ran 7 tests ... OK`）
- 浏览器 smoke 已完成：
  - 通过 `./start.sh` 启动主站后，首页实际加载了 `/static/app.js?v=...`、`/static/js/dubbingPanel.js?v=...`、`/static/js/agentDrawer.js?v=...`
  - Chrome 实测 `Auto Dubbing` 与 `Auto Dubbing V2` 面板都可正常切换并渲染首屏控件
  - `./stop.sh` 已完成清理，启动进程已正常退出

## Review（2026-04-25 产品化重构整线收口）
- `/docs/refactor/05-migration-roadmap.md` 这条 2026-04-24/25 产品化重构主线，当前 Phase 5 到 Phase 11 都已落地完成；本轮没有再发现新的阻塞项。
- 整线更大范围回归已通过：
  - `uv run python -m unittest tests.test_agent_api tests.test_command_builder tests.test_manifest_contracts tests.test_task_store tests.test_job_recovery tests.test_dubbing_runtime tests.test_dub_pipeline_asr_layout tests.test_dub_long_video tests.test_dubbing_cli_api tests.test_web_routes_legacy tests.test_simple_web_legacy`（`Ran 88 tests ... OK`）
  - `node --check src/subtitle_maker/static/app.js src/subtitle_maker/static/js/agentDrawer.js src/subtitle_maker/static/js/dubbingPanel.js`
- 大回归里 `tests.test_dub_long_video` 仍会打印 `flash-attn is not installed` 的环境警告，但测试本身通过，当前语义仍走手工 PyTorch fallback；这不是这轮重构新增问题。
- 当前最合理的下一步已经不再是继续拆 phase，而是整理这整条重构线的未提交改动并准备提交。

## 2026-04-25 前端协同改造（统一 DeepSeek API Key + Auto Dubbing 与主 workflow 配合）
- [x] Spec-1：审计 API key 分散位置、Auto Dubbing 与主 workflow 的状态断层
- [x] Spec-2：确认统一 API key 控件、状态模型与 Auto Dubbing 配合方案
- [x] Spec-3：锁定风险、验证方式和回退策略
- [x] HARD-GATE：已确认并开始实现
- [x] 实现统一侧边栏 DeepSeek 配置，并移除前端重复 key 输入
- [x] 实现 Auto Dubbing `Current Project / Standalone Upload` 双模式与 project-aware 启动接口
- [x] 补测试与最小运行校验

## Review（2026-04-25 前端协同改造 Spec-1）
- DeepSeek API key 当前至少分散在 4 个前端入口：
  - 主翻译面板 [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html:676) 的 `#api-key` + `#save-api-key`，并由 [src/subtitle_maker/static/app.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:1337) 读写 `sm_apiKey` / `sm_saveApiKey`
  - Auto Dubbing V1 [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html:302) 的 `#auto-dub-api-key` + `#auto-dub-save-key`
  - Auto Dubbing V2 [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html:520) 的 `#auto-dub-v2-api-key` + `#auto-dub-v2-save-key`
  - Agent 抽屉 [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html:745) 的 `#agent-api-key`
- 这 4 处不仅是 UI 分散，连本地存储语义也不统一：
  - 主翻译面板在 [app.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:1337) 使用 `sm_apiKey`
  - Auto Dubbing V1/V2 在 [src/subtitle_maker/static/js/dubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/dubbingPanel.js:571) 分别使用 `${keyStoragePrefix}_apiKey`，也就是 `sm_autoDub_v1_apiKey` / `sm_autoDub_v2_apiKey`
  - Agent 抽屉在 [src/subtitle_maker/static/js/agentDrawer.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/agentDrawer.js:105) 每次直接透传 `api_key`，本地不复用主 key，也不落统一存储
- 后端消费面也分成了 3 套：
  - 主翻译 route [src/subtitle_maker/app/routes/translation.py::translate()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/app/routes/translation.py:15) 强制要求 `api_key`
  - Auto Dubbing route [src/subtitle_maker/dubbing_cli_api.py::start_auto_dubbing()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py:700) 接收 `api_key` 表单，并回退到 `DEEPSEEK_API_KEY`
  - Agent route [src/subtitle_maker/agent_api.py::chat_with_agent()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/agent_api.py:81) 直接把 `payload.api_key` 传给 `OpenAICompatibleChatClient`
  这说明“统一 key”不只是把 3 个输入框删成 1 个，还要统一前端状态来源和各 route 的取值约定。
- Auto Dubbing 与主 workflow 的重复，不只是“界面上又出现了一次上传/翻译”，而是已经形成两套独立状态机：
  - 主 workflow 在 [src/subtitle_maker/static/app.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:28) 维护 `currentTaskId`、`originalSubtitlesData`、`translatedSubtitlesData`
  - 上传、转写、轮询、翻译分别走 [handleMediaUpload()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:748)、[pollStatus()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:936)、翻译提交流程 [app.js 1070 行附近](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:1070)
  - Auto Dubbing 面板在 [src/subtitle_maker/static/js/dubbingPanel.js::setupAutoDubbing()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/dubbingPanel.js:31) 内部又维护 `selectedFile`、`selectedSubtitleFile`、`currentAutoDubTaskId`、`reviewLinesCache`
  - 两边唯一已接上的共享点只有 [applyAutoDubSubtitleItems()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:1045)，也就是 Auto Dubbing 完成后把字幕结果回填给主播放器/editor；启动前并没有复用主 workflow 现有状态
- 模板层的重复也很明确：
  - 主流程已经有 `panel-upload`、`panel-transcribe`、`panel-results`、`panel-srt` [index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html:124)
  - Auto Dubbing V1/V2 又各自重新放了一套媒体上传、字幕上传、source/target language、translation key、时间区间、启动区 [index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html:150) 和 [index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html:364)
  因此用户感知到的“前面流程重复”是事实，不只是代码层重复。
- 当前更深的耦合点在后端 contract：Auto Dubbing 启动接口 [src/subtitle_maker/dubbing_cli_api.py::start_auto_dubbing()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py:700) 目前强制入口就是 `video: UploadFile = File(...)`，也就是“重新上传媒体文件”。它支持可选 `subtitle_file`，但不支持“基于主 workflow 现有 `task_id` / `filename` / 已生成字幕直接启动”。这意味着如果要让 Auto Dubbing 真正和主 workflow 接起来，不能只改前端面板顺序，必须一起评估 route contract。
- `Spec-1` 的现状结论先固定为两点：
  - 第一目标应是“统一 DeepSeek API key 的单一前端来源”，最合适的位置是侧边栏全局设置区，而不是继续在 panel 内各放一份输入框
  - 第二目标应是“把 Auto Dubbing 从一套并行 workflow 收成一个附着在主项目状态上的高级操作入口”；也就是说，前端真正需要规划的是“从当前项目启动 dubbing 的几种模式”，而不是继续复制一套上传/翻译表单
- 本段只完成现状审计与方向收敛，尚未进入方案设计；下一步应按流程进入 `Spec-2`。

## Review（2026-04-25 前端协同改造 Spec-2）
- 首轮精确改动范围先固定为 6 个位置：
  - `src/subtitle_maker/templates/index.html`
  - `src/subtitle_maker/static/style.css`
  - `src/subtitle_maker/static/app.js`
  - `src/subtitle_maker/static/js/dubbingPanel.js`
  - `src/subtitle_maker/static/js/agentDrawer.js`
  - `src/subtitle_maker/dubbing_cli_api.py`
  其中前 5 个负责统一前端状态和 UI，`dubbing_cli_api.py` 负责补“从当前项目启动 Auto Dubbing”的后端 contract；这一轮不改 `app/routes/subtitles.py`、`translation.py` 的基本协议，也不触碰 `tools/*`。
- DeepSeek API key 的统一方案固定为“侧边栏单一来源 + 各业务面板只消费、不自存”：
  - 侧边栏位置采用现有 [sidebar-footer](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html:61) 下方，新增一个全局 `DeepSeek` 设置块，包含：
    - `api key` 输入框
    - `save key` 复选框
    - 当前是否使用环境变量 / 本地保存值的状态提示
  - 前端状态统一收口到 `app.js`，只保留一套存储 key，例如 `sm_deepseekApiKey` / `sm_saveDeepseekApiKey`
  - [主翻译流程](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:1070)、[Auto Dubbing V1/V2](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/dubbingPanel.js:571)、[Agent 抽屉](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/agentDrawer.js:105) 全部只通过 `app.js` 暴露的 getter / setter 读取这套统一状态，不再各自维护 localStorage
- 因此 UI 上首轮会移除或降级 3 处局部 key 输入：
  - 主翻译面板 [index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html:676)
  - Auto Dubbing V1/V2 运行区 [index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html:302) / [520](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html:520)
  - Agent 抽屉 [index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html:745)
  其中 Agent 抽屉不再单独接受 key 输入；它直接消费统一的全局 DeepSeek key，并继续保留环境变量回退。
- Auto Dubbing 与主 workflow 的配合方式也先固定为“两种启动模式，但默认主项目优先”：
  1. `Current Project`：默认模式，基于当前主 workflow 已上传的媒体和已有字幕状态启动
  2. `Standalone Upload`：保留现有独立上传模式，作为高级/兜底入口
  这样可以避免用户已经在主 workflow 里上传过视频、做过转写或翻译后，还要在 Auto Dubbing 再重复上传一遍。
- `Current Project` 模式下的前端状态来源固定为：
  - 媒体：`currentFilename` / `currentOriginalFilename`，来源于 [handleMediaUpload()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:748)
  - 原字幕：`originalSubtitlesData`
  - 译文字幕：`translatedSubtitlesData`
  - 当前项目任务：`currentTaskId`
  - 播放器当前位置与时间范围：继续复用现有 `videoPlayer`、时间区间输入和 `Use Current`
  这意味着 Auto Dubbing 前端首轮不再默认显示大块媒体上传卡，而是先显示“当前项目是否可直接启动”的状态摘要。
- 为了让 `Current Project` 模式不重新上传视频，后端 contract 首轮建议采用“新增路由”而不是硬改旧 `/dubbing/auto/start`：
  - 保留现有 [start_auto_dubbing()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py:700) 作为 `Standalone Upload` 路径
  - 新增一个 project-aware 启动入口，例如 `POST /dubbing/auto/start-from-project`
  - 新路由接收：
    - `filename` / `original_filename`
    - 可选 `task_id`
    - `subtitle_mode`
    - `subtitles_json`
    - 其余现有 dubbing 参数（`target_lang`、`grouping_strategy`、`short_merge_*`、`pipeline_version`、`rewrite_translation`、`time_ranges` 等）
  这样旧上传路径和测试不会被直接打碎，同时 Current Project 模式也不用前端把 `/stream/{filename}` 再拉成 blob 重新上传一遍。
- `Current Project` 模式下的字幕策略也固定为 3 档，避免前端重新拼业务规则：
  - 若有 `translatedSubtitlesData`：默认按 `translated` 字幕启动，跳过 ASR 和翻译
  - 否则若有 `originalSubtitlesData`：默认按 `source` 字幕启动，跳过 ASR，但仍翻译
  - 否则：回退为仅用当前项目媒体启动完整流程
  这三档都直接对应当前后端 [subtitle_mode](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py:708) 和“上传 translated/source 字幕”的既有语义，不再在前端发明新的业务含义。
- Auto Dubbing 面板本身首轮不做“大重画”，但布局方向要变：
  - 顶部先显示 `Current Project` 摘要卡：当前媒体、字幕状态、翻译状态、可否直接启动
  - `Standalone Upload` 收进一个次级卡或 disclosure 区域
  - `V1 / V2` 仍保留为两块运行配置，但共享同一套项目上下文，而不是各自再带一遍完整上传流程
  这能把“重复上传/重复翻译”的问题压下去，同时不把 V1/V2 的运行参数合并到看不清的状态。
- 这一轮明确不做：
  - 不统一 OpenAI / DeepSeek / 其他 provider 抽象；本轮只统一 DeepSeek key
  - 不改 [app/routes/translation.py::translate()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/app/routes/translation.py:15) 的 form 协议
  - 不把 Auto Dubbing V1/V2 合成单面板
  - 不删除 `Standalone Upload`
  - 不把 Agent 变成自动执行器
- 首轮迁移顺序固定为：
  1. 先在侧边栏落全局 DeepSeek 设置，并由 `app.js` 托管统一状态
  2. 再让主翻译 / Agent / Auto Dubbing 全部转成消费统一 key
  3. 然后补 `start-from-project` 这条后端入口
  4. 最后把 Auto Dubbing 面板改成“Current Project 优先，Standalone Upload 次级”
- 本段只锁定方案边界和迁移顺序，尚未开始实现；下一步应按流程进入 `Spec-3`。

## Review（2026-04-25 前端协同改造 Spec-3）
- 第一风险是把“全局 DeepSeek key”做成了新的状态污染源。当前 [clearState()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:563) 在 `New Project` 时会清理字幕任务与项目 localStorage，但不会动 `sm_apiKey`；这与“侧边栏里的全局设置”语义是相容的。首轮实现必须坚持这个边界：全局 DeepSeek 设置属于跨项目用户偏好，不应被 `New Project` 清掉；否则统一入口反而比现在更烦。
- 第二风险是把“统一 key”误做成“强制只认本地保存值”。当前三条消费链都保留了环境变量回退：
  - Agent 通过 [OpenAICompatibleChatClient](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/core/llm_client.py:20) 回退 `DEEPSEEK_API_KEY`
  - Auto Dubbing 在 [start_auto_dubbing()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py:772) 回退 `DEEPSEEK_API_KEY`
  - 主翻译虽然前端强传 `api_key`，但产品上也允许用户直接填入
  所以首轮前端统一时，侧边栏状态必须同时表达“已保存本地 key”和“当前依赖环境变量”两种来源，不能因为输入框为空就一律把页面判成不可用。
- 第三风险是 `Current Project` 模式误判“当前项目一定有媒体”。当前 [handleSrtUpload()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:1279) 上传 SRT 后，会把 `currentFilename` 改成 `.srt` 文件名；后端 [upload_srt()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/app/routes/subtitles.py:18) 只在已有视频时把 `video_filename` 存进任务记录。因此首轮实现里，`Current Project` 不能简单依赖 `currentFilename` 判断媒体来源，必须显式区分“项目媒体文件名”和“当前字幕文件名”，否则导入 SRT 后会把一个只有字幕的项目误当成可直接配音的视频项目。
- 第四风险是 `start-from-project` 路由变成任意文件访问入口。现有 [upload_video()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/app/routes/projects.py:24) 和 [stream_video()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/app/routes/projects.py:37) 都只在 `UPLOAD_DIR` 范围内工作。新增 project-aware dubbing 路由时，也必须只接受“当前项目已知文件名”或 `task_id` 能反查到的媒体，不能让前端直接传任意路径，更不能信任本地 localStorage 里伪造的文件名。
- 第五风险是把 Auto Dubbing 与主 workflow 的共享点做成“隐式推断”，导致字幕语义错位。当前主 workflow 的翻译结果在 [translatedSubtitlesData](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js:30)，Auto Dubbing 又支持 `source` / `translated` 两种字幕语义 [dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py:708)。因此 `Current Project` 模式下必须把“使用原字幕继续翻译”与“使用当前译文直接配音”明确显示成可见选项或明确默认规则，不能只凭数组非空就静默切换，否则用户很容易在 review/redub 上下文里拿错字幕版本。
- 第六风险是侧边栏空间与移动端可用性。当前侧边栏 footer 只有 [theme/new project/release models](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html:61)，而 [style.css](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/style.css:87) 里侧边栏是固定宽度 + 收起态。首轮新增全局 DeepSeek 设置时，不能把 footer 撑成一长列导致按钮溢出，尤其不能在收起态保留一个不可用的密码框；实现上要么在收起态隐藏设置内容，只保留入口按钮，要么给侧边栏 footer 做可折叠设置区。
- 首轮验证固定为四层：
  1. 前端语法：`node --check src/subtitle_maker/static/app.js src/subtitle_maker/static/js/dubbingPanel.js src/subtitle_maker/static/js/agentDrawer.js`
  2. Python 语法：`uv run python -m py_compile src/subtitle_maker/dubbing_cli_api.py src/subtitle_maker/app/routes/projects.py src/subtitle_maker/app/routes/subtitles.py`
  3. API / route 回归：`uv run python -m unittest tests.test_dubbing_cli_api tests.test_web_routes_legacy`
  4. 浏览器 smoke：
     - 侧边栏可设置并保存全局 DeepSeek key
     - 主翻译不再单独要求 panel 内 key
     - Agent 抽屉可直接复用全局 key 发起请求
     - `Current Project` 模式下，已有媒体 + 原字幕 / 译文字幕时可直接启动 Auto Dubbing
- 首轮建议新增两类测试护栏：
  - 在 [tests/test_web_routes_legacy.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_web_routes_legacy.py:23) 增加首页 HTML 断言，确认侧边栏全局 DeepSeek 控件存在
  - 在 [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py:47) 增加 `start-from-project` 用例，至少覆盖：
    - 用已上传媒体文件名启动成功
    - 无媒体的 SRT-only 项目被拒绝
    - translated/source 两种字幕模式正确透传
- 回退策略固定为两段式：
  - 若全局 key 统一后影响主翻译 / Agent / Auto Dubbing 任一链路，只回退“前端统一 key 状态”，恢复各面板独立输入框；不回退 `start-from-project` 后端入口
  - 若 `Current Project` 模式引发媒体判定或字幕语义错乱，只回退 project-aware 启动与 UI 默认模式，保留统一全局 key
- HARD-GATE 前的结论：
  这轮实现目标是“统一 DeepSeek API key 来源，并让 Auto Dubbing 默认依附当前项目状态启动”，不是“重写整套项目工作流”；
  只有在你明确确认后，才进入代码实现。

## Review（2026-04-25 前端协同改造实施）
- 统一 DeepSeek key 已落到侧边栏单一入口：
  - [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html) 新增 `global-deepseek-api-key` / `global-deepseek-save-key`
  - [src/subtitle_maker/static/app.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js) 现在统一托管 `sm_deepseekApiKey` / `sm_saveDeepseekApiKey`
  - 主翻译、Auto Dubbing、Agent 都改成只消费这套共享状态，不再各自保存 localStorage
- Auto Dubbing 前端已改成 `Current Project` 优先：
  - [src/subtitle_maker/static/js/dubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/dubbingPanel.js) 新增项目摘要卡、字幕策略选择，以及 `Current Project / Standalone Upload` 模式切换
  - [src/subtitle_maker/static/app.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js) 额外维护“项目媒体文件名”与“当前字幕文件名”的分离状态，避免导入 SRT 后误判成可直接配音的视频项目
- 后端已补 project-aware 启动入口：
  - [src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py) 新增 `POST /dubbing/auto/start-from-project`
  - 新入口只从已知 `UPLOAD_DIR` 与 legacy `task_id` 解析当前项目媒体，并支持把主 workflow 的 `subtitles_json` 直接落成 SRT 后启动
- 验证结果：
  - `node --check src/subtitle_maker/static/app.js src/subtitle_maker/static/js/dubbingPanel.js src/subtitle_maker/static/js/agentDrawer.js`：通过
  - `uv run python -m py_compile src/subtitle_maker/dubbing_cli_api.py src/subtitle_maker/app/routes/projects.py src/subtitle_maker/app/routes/subtitles.py tests/test_dubbing_cli_api.py tests/test_web_routes_legacy.py`：通过
  - `uv run python -m unittest tests.test_web_routes_legacy`：`Ran 4 tests ... OK`
  - `uv run python -m unittest tests.test_dubbing_cli_api`：`Ran 43 tests ... OK`
- 运行侧补充说明：
  - 本地用 `uvicorn subtitle_maker.web:app --host 127.0.0.1 --port 8765` 验证过应用可启动
  - 但当前桌面沙箱里跨命令访问该本地端口不稳定，所以这轮没有把浏览器 smoke 作为完成阻塞项；HTML 与 API 行为由单测和语法校验兜住

## Review（2026-04-25 前端回归修复记录，已判定失败/废弃）
- 状态结论：这轮修复未解决用户真实问题，且后续改动一度引入了 `#panel-transcribe` 与 `#panel-results` 同时显示的回归；该记录仅保留为失败样本，不再作为“当前有效方案”。
- 针对用户反馈“`2. Generate Subtitles` / `3. Subtitles & Translation` 右下区域异常”，已记录两类回归：
  1. [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html) 里 `panel-results` 的 `translated-subtitles` / export 区块不能挂在 `.subtitle-column` 外面，否则右列会形成明显空洞。
  2. [src/subtitle_maker/static/app.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js) 切 panel 时不能使用整页 `scrollIntoView()`；播放器和侧边栏必须保持固定，只允许 `.dynamic-content-section` 自己回顶。
- 追加待修回归：
  - `Auto Dubbing V2` 右下角 restore 区（`#auto-dub-v2-load-batch-select` / `#auto-dub-v2-load-batch-btn`）用户反馈“菜单用不了”，需要下次优先在浏览器里针对 [panel-auto-dub-v2](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html:423) 做真实交互排查，重点看布局遮挡、滚动可视区和 `dubbingPanel.js` 的 V2 restore 事件绑定。
- 当前收敛后的实现边界：
  - 播放器固定在顶部区域，不随 panel 切换整体滚动
  - 侧边栏固定，不因修复 panel 可视区而被带着滚动
  - `panel-results` 恢复为正常两列：右列包含翻译控件、翻译结果和导出区
- 本轮已做的最小验证：
  - `node --check src/subtitle_maker/static/app.js`：通过
  - `uv run python -m unittest tests.test_web_routes_legacy`：`Ran 4 tests ... OK`

## Review（2026-04-27 前端面板修复复盘，当前有效）
- 修复目标：`#panel-transcribe` / `#panel-results` 在 Step 2/3 中保持“仅当前面板可见”，同时实现内部滚动、顶部贴合与非贴边宽度。
- 关键改动：
  - [src/subtitle_maker/static/app.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js) 新增 `PANEL_INTERNAL_SCROLL_IDS`，并在 `syncFloatingUiForActivePanel()` 中只在 Step 2/3 切换 `body.panel-internal-scroll-active` 状态。
  - [src/subtitle_maker/static/style.css](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/style.css) 将布局修复限定到 `.active` 面板：`body.panel-internal-scroll-active #panel-transcribe.active` 与 `#panel-results.active`，避免覆盖 tab 的 `display:none` 机制。
  - 同文件中 `.card` 级滚动也限定为 `.active .card`，确保只给当前面板开启内部滚动，不影响未激活面板。
  - 面板宽度改为“自适应 + 居中留白”：`width:100% + max-width:1180px + margin:0 auto`，不再贴两边。
- 回归修正：
  - 已修复一次错误覆盖：曾经把两面板都强制 `display:flex !important`，导致 2/3 同时显示；现已改回 `.active` 精确选择器。
- 本轮验证：
  - `node --check src/subtitle_maker/static/app.js`：通过
  - 布局与可见性由用户在页面回归验证（Step 2 仅显示 transcribe，Step 3 仅显示 results）。

## Review（2026-04-27 侧边栏 TTS 底座切换）
- 已完成前端入口改造：在左侧 `DeepSeek API` 卡片下方新增 `TTS 底座模型` 下拉框（`index-tts` / `OmniVoice`），默认 `index-tts`。
  - 模板变更： [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html)
  - 样式变更： [src/subtitle_maker/static/style.css](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/style.css)
- 已完成前端全局状态收口：
  - `app.js` 新增 `global-tts-backend` 读取、`sm_globalTtsBackend` 本地持久化、`getGlobalTtsBackend()` 对外 getter。
  - 通过依赖注入把 getter 传入 Auto Dubbing 子模块，避免 V1/V2 各自维护一套状态。
  - 代码位置： [src/subtitle_maker/static/app.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js)
- 已完成 Auto Dubbing 参数透传：
  - `dubbingPanel.js::buildCommonStartFormData()` 统一追加 `tts_backend`，因此 V1/V2 两条启动链路都会带上当前全局底座模型。
  - 代码位置： [src/subtitle_maker/static/js/dubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/dubbingPanel.js)
- 约束说明：
  - 这轮只新增“前端切换与参数透传”，不改 OmniVoice 运行时配置输入；若后端未配置 OmniVoice 所需路径参数，切到 `OmniVoice` 启动任务仍会由后端返回配置错误。

## Review（2026-04-27 OmniVoice 运行参数后端绑定）
- 已完成 `tts_backend=omnivoice` 主后端链路打通：
  - [src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py) 的请求归一化已放开 `omnivoice`，并在主后端或备胎后端任一使用 OmniVoice 时统一校验运行参数。
  - 新增环境变量回退：`OMNIVOICE_ROOT`、`OMNIVOICE_PYTHON_BIN`、`OMNIVOICE_MODEL`、`OMNIVOICE_DEVICE`，用于前端未显式传参时的后端默认绑定。
- 已完成命令透传修复：
  - [src/subtitle_maker/jobs/command_builder.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/jobs/command_builder.py) 改为“主后端或备胎只要有 OmniVoice，就透传 `--omnivoice-*` 参数”，避免 `tts_backend=omnivoice` 时命令缺参。
- 已完成 CLI 运行时对齐：
  - [tools/dub_pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_pipeline.py) 放开 `--tts-backend omnivoice` 校验；
  - 同文件修复加载分支：主后端为 OmniVoice 时不再错误执行 index-tts 健康检查/模型预热。
- 新增回归测试：
  - [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 新增“主后端 OmniVoice + 环境变量绑定”成功用例，以及“缺少运行参数”失败用例。
  - [tests/test_command_builder.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_command_builder.py) 新增“主后端 OmniVoice 仍透传运行参数”用例。
- 验证结果：
  - `uv run python -m py_compile src/subtitle_maker/dubbing_cli_api.py src/subtitle_maker/jobs/command_builder.py tools/dub_pipeline.py tests/test_dubbing_cli_api.py tests/test_command_builder.py`
  - `uv run python -m unittest tests.test_command_builder`：`Ran 4 tests ... OK`
  - `uv run python -m unittest tests.test_dubbing_cli_api`：`Ran 46 tests ... OK`

## TODO（2026-04-27 字幕回写热修）
- [x] 定位“save-and-redub 后 final 字幕仍旧版本”的根因，并给出最小改动修复方案
- [x] 修复 `rebuild_batch_outputs` 的字幕重建条件，确保存在有效输入时就能刷新 `translated_full.srt` / `dubbed_final_full.srt`
- [x] 补一条回归测试：存在跳过 segment 时，review 重配后 final 字幕仍应更新
- [x] 跑最小验证（相关单测 + 语法检查），并回填 Review

## Review（2026-04-27 字幕回写热修）
- 根因 1（后端重建条件过严）：
  - `tools/repair_bad_segments.py::rebuild_batch_outputs()` 之前要求 `translated_srt_inputs/source_srt_inputs` 数量必须等于 `segment_entries` 才重建 full 字幕。
  - 当 batch 中存在“跳过段/空字幕段”时，这个条件永远不成立，导致 review 重配后 `final/translated_full.srt` 不刷新，播放器字幕仍是旧文案。
- 根因 2（路径优先级错误）：
  - 同函数之前优先使用 segment manifest 里的 `paths.translated_srt`/`paths.dubbed_final_srt`。
  - 若这些路径仍指向历史文件且文件存在，会覆盖 `segment/subtitles/*.srt` 的最新文本，重建仍拿旧字幕。
- 修复措施：
  - 字幕重建改为“有有效输入就重建”，不再要求每个 segment 都有字幕输入。
  - 段内字幕路径改为优先读取 `segment/subtitles/source.srt`、`translated.srt`、`dubbed_final.srt`，仅在不存在时回退 manifest 路径。
  - 前端 `autoLoadAutoDubSubtitles()` 增加 cache bust，避免 review 重配后播放器读取到浏览器旧缓存字幕。
- 回归测试：
  - `tests/test_dubbing_cli_api.py::test_rebuild_batch_outputs_updates_final_subtitles_when_some_segments_are_skipped`
  - 覆盖“一个有效 segment + 一个跳过 segment”场景，验证 `translated_full.srt` / `dubbed_final_full.srt` 会更新为新文本。
- 验证证据：
  - `node --check src/subtitle_maker/static/js/dubbingPanel.js`：通过
  - `uv run python -m py_compile tools/repair_bad_segments.py tests/test_dubbing_cli_api.py`：通过
  - `uv run python -m unittest tests.test_dubbing_cli_api`：`Ran 50 tests ... OK`

## TODO（2026-04-27 断点续传覆盖旧音频修复）
- [x] 定位“resume 从第 1 句重配并覆盖 seg_*.wav”的根因分支
- [x] 修复 `synthesize_segments`：普通 resume 默认复用已有有效句子音频，只重配缺失/失败句
- [x] 新增回归测试，确保 `redub_line_indices=None` 时不会再次调用 TTS
- [x] 执行最小验证并记录结果

## Review（2026-04-27 断点续传覆盖旧音频修复）
- 根因：
  - [src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py) 的 `synthesize_segments()` 仅在 `redub_line_indices` 非空且当前行未选中时才复用旧记录。
  - 普通 resume（`redub_line_indices=None`）会跳过复用分支，导致从第 1 句开始重新合成并覆盖原有 `seg_*.wav`。
- 修复：
  - 调整复用条件为：
    - 局部 redub：保持旧语义（未选中行复用）；
    - 普通 resume：若已有记录且音频存在，并且状态是 `done/manual_review`（兼容旧 manifest 缺失状态），则直接复用。
  - 复用时写入 `attempt_history.action=resume_reuse_existing`，便于后续排查是否命中续跑复用。
- 测试：
  - 新增 [tests/test_dubbing_runtime.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_runtime.py) 用例 `test_synthesize_segments_resume_reuses_existing_record_without_redub_indices`，断言 resume 情况下不调用 `synthesize_text_once`。
- 验证证据：
  - `uv run python -m py_compile src/subtitle_maker/domains/dubbing/pipeline.py tests/test_dubbing_runtime.py`：通过
  - `uv run python -m unittest tests.test_dubbing_runtime tests.test_dubbing_cli_api tests.test_command_builder`：`Ran 78 tests ... OK`

## TODO（2026-04-27 本地媒体加载后播放器空白修复）
- [x] 排查主上传链路与播放器 `src` 赋值路径，确认空白场景发生在流地址不可用时无回退
- [x] 修复前端播放器源切换策略：本地 `ObjectURL` 先预览，上传成功后切到 `/stream/...`，失败自动回退本地源
- [x] 增加播放器错误提示与占位恢复，避免黑屏无反馈
- [x] 执行前端语法检查并记录结果

## Review（2026-04-27 本地媒体加载后播放器空白修复）
- 根因：
  - [src/subtitle_maker/static/app.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/app.js) 的 `handleMediaUpload()` 只在上传完成后把播放器切到后端 `/stream/...`，没有可用回退源。
  - 一旦流地址加载失败（服务端临时不可达、浏览器对该容器/编码解析失败等），占位已被隐藏，用户只能看到“空黑播放器”。
- 修复：
  - 新增 `setVideoSourceWithFallback()`：统一设置主源与回退源；
  - 新增 `setupVideoPlaybackFallback()`：监听 `video.error`，优先回退到本地 `ObjectURL`，并显示状态提示；
  - 上传流程改为“先本地预览，再切后端流”，并在每次新上传前释放旧 `ObjectURL` 防止内存泄露。
- 验证证据：
  - `node --check src/subtitle_maker/static/app.js`：通过

## TODO（2026-04-27 load-batch 播放器误载 segment 音频修复）
- [x] 定位 `input_media` 解析链路，确认 `batch_manifest.input_media_path` 被写成 `segments/segment_0001.wav` 时会导致播放器只加载 8 分钟音频
- [x] 修复 `resume` 输入媒体选择：优先回溯 `uploads/dubbing/<task_id>/` 原视频，分段音频仅作兜底
- [x] 修复 `artifact/input_media` 下载解析：同样优先原视频，避免 load-batch 预览拿到 segment 音频
- [x] 补回归测试并跑通 `tests.test_dubbing_cli_api`

## Review（2026-04-27 load-batch 播放器误载 segment 音频修复）
- 根因：
  - 某些中断/续跑批次会把 `batch_manifest.input_media_path` 记录成 `segments/segment_0001.wav`。
  - 前端 load-batch 的播放器依赖 `input_media_url`（后端 artifact `input_media`），因此会加载“仅 segment-1 的音频”而不是原视频。
- 修复：
  - [src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py) 新增批次输入媒体优先级解析：
    - 优先 `uploads/dubbing/<web任务id>/` 下的原始上传视频；
    - 再用 manifest 中的 `input_media_path`；
    - 分段音频只在无其他候选时兜底。
  - 同步应用到 `resume`（`_resolve_resume_input_media`）和 artifact 下载（`_resolve_artifact` 的 `input_media`）。
  - 中断批次参数推断（`_infer_incomplete_batch_task_fields`）也改为优先填充原视频路径。
- 回归测试：
  - [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 新增：
    - `test_load_incomplete_batch_prefers_uploaded_video_over_segment_audio`
    - `test_input_media_artifact_prefers_uploaded_video_when_manifest_points_segment_audio`
- 验证证据：
  - `uv run python -m py_compile src/subtitle_maker/dubbing_cli_api.py tests/test_dubbing_cli_api.py`：通过
  - `uv run python -m unittest tests.test_dubbing_cli_api`：`Ran 59 tests ... OK`

## TODO（2026-04-27 恢复任务误用 missing 音频修复）
- [x] 定位“同一 seg 同时存在 `seg_xxxx.wav` 与 `seg_xxxx_missing.wav`，合并却选 missing”的路径
- [x] 修复逐句复用逻辑：恢复时优先选 `seg_xxxx.wav`，避免 manifest 旧路径指向 missing
- [x] 修复合并逻辑：`compose_vocals_master` 也优先选同 ID 正常 wav，防止 missing 抢占
- [x] 补回归测试并跑相关单测

## Review（2026-04-27 恢复任务误用 missing 音频修复）
- 根因：
  - 恢复时 `existing_records_by_id` 从旧 manifest 读取 `tts_audio_path`，若该字段已是 `seg_xxxx_missing.wav`，即便同目录存在 `seg_xxxx.wav`，复用仍会命中 missing。
  - 混音阶段此前直接读取 `segment["tts_audio_path"]`，不会自动回退到同 ID 的正常 wav，导致最终合并继续吃 missing。
- 修复：
  - [src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py)
    - 新增 `resolve_existing_audio_path()`，恢复复用时优先 `seg_xxxx.wav`；
    - 当本轮 TTS 全失败（`best is None`）但历史有可用 `seg_xxxx.wav` 时，兜底复用旧音频，不再直接产出 missing 覆盖混音输入。
    - 新增 `persist_single_segment_output()`，强制同一 `seg_id` 最终仅保留一种文件（`seg_xxxx.wav` 或 `seg_xxxx_missing.wav`），杜绝双文件并存。
  - [src/subtitle_maker/domains/media/compose.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/media/compose.py)
    - 新增 `resolve_compose_audio_path()`，混音时优先同 ID 正常 wav，避免 `*_missing.wav` 抢占。
- 回归测试：
  - [tests/test_dubbing_runtime.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_runtime.py)
    - `test_compose_vocals_master_prefers_non_missing_audio_when_both_exist`
    - `test_synthesize_segments_resume_prefers_real_audio_over_missing_record_path`
- 验证证据：
  - `uv run python -m py_compile src/subtitle_maker/domains/dubbing/pipeline.py src/subtitle_maker/domains/media/compose.py tests/test_dubbing_runtime.py`：通过
  - `uv run python -m unittest tests.test_dubbing_cli_api tests.test_dubbing_runtime`：`Ran 77 tests ... OK`

## TODO（2026-04-27 Auto Dubbing V2 OmniVoice 中途掉线导致 missing）
- [x] 定位本次 `missing` 的真实来源，区分“误用 `*_missing.wav`”和“TTS 真失败”
- [x] 修复 `src/subtitle_maker/backends/omni_voice.py::OmniVoiceBackend.synthesize()`：本地 API 掉线后自动拉起并重试
- [x] 补回归测试，覆盖“首轮连接失败但本地恢复后二次成功”的路径
- [x] 跑定向验证，确认相关测试通过

## Review（2026-04-27 Auto Dubbing V2 OmniVoice 中途掉线导致 missing）
- 根因：
  - 实际产物日志 [outputs/dub_jobs/web_20260427_124857/longdub_20260427_204902/segment_jobs/segment_0001/logs/segment_0001.jsonl](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/outputs/dub_jobs/web_20260427_124857/longdub_20260427_204902/segment_jobs/segment_0001/logs/segment_0001.jsonl) 显示，`seg_0001`~`seg_0006` 正常，`seg_0007` 起连续报 `E-TTS-001 omnivoice api connect failed` / `Remote end closed connection without response`，说明是 OmniVoice API 中途掉线，不是后处理误判。
  - 当前实现 [src/subtitle_maker/backends/omni_voice.py::OmniVoiceBackend.synthesize()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/backends/omni_voice.py:334) 在 API 失败后只做“释放模型 + 同地址重试”，不会重新拉起本地 `127.0.0.1:8020` 服务，因此服务一旦掉线，后续句子会持续落入 missing。
- 修复：
  - [src/subtitle_maker/backends/omni_voice.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/backends/omni_voice.py)
    - 新增 `_should_attempt_local_omnivoice_recovery()` 与 `_recover_local_omnivoice_service()`，只对本地默认 OmniVoice URL 的断连症状触发恢复；
    - 恢复流程优先执行 `start_omnivoice_api.sh`，必要时再 `stop/start` 一次，避免本地僵死 listener 让后续整串句子直接 missing；
    - `OmniVoiceBackend.synthesize()` 第二次重试前接入上述恢复逻辑，并把恢复失败摘要带回最终异常，便于后续排障。
- 回归测试：
  - [tests/test_dubbing_runtime.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_runtime.py)
    - 新增 `test_omnivoice_backend_api_restarts_local_service_after_connect_failure`
- 验证证据：
  - `uv run python -m py_compile src/subtitle_maker/backends/omni_voice.py tests/test_dubbing_runtime.py`：通过
  - `uv run python -m unittest tests.test_dubbing_runtime`：`Ran 20 tests ... OK`

## TODO（2026-04-27 translated 模式短句合并 UI 语义修复）
- [x] 梳理 Auto Dubbing V1/V2 面板里短句合并开关与字幕模式的联动状态
- [x] 修复 `translated` 模式下的控件禁用、提示文案与提交保护，避免 source-only 选项误导用户
- [x] 跑前端语法验证，并补充 review 记录

## Review（2026-04-27 translated 模式短句合并 UI 语义修复）
- 根因：
  - [src/subtitle_maker/static/js/dubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/dubbingPanel.js) 的 `buildCommonStartFormData()` 之前无条件读取 `shortMergeEnabledCheckbox.checked`，因此在 `translated` 模式下也会继续提交 `short_merge_enabled=true/false`。
  - 同文件的 `syncShortMergeControls()` 之前只负责显示/隐藏阈值输入，不感知当前是 `source` 还是 `translated`，因此 UI 允许用户在 `translated` 直通模式下继续勾选 source-only 选项。
  - [tools/dub_pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_pipeline.py) 的 `load_or_transcribe_subtitles()` 实际只在 `persist_input_srt_to_source=True` 时才会执行 source 侧短句合并，所以之前属于“前端可选、后端实际忽略”的误导状态。
- 修复：
  - [src/subtitle_maker/static/js/dubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/dubbingPanel.js)
    - 新增 `resolveShortMergeAvailability()`，按 `Current Project / Standalone` 与 `source / translated` 推断短句合并是否可用；
    - `syncShortMergeControls()` 现在会在 `translated` 模式下禁用 checkbox、隐藏阈值输入、更新提示文案，并在切回 `source` 时恢复用户之前的勾选意图；
    - `buildCommonStartFormData()` 改为忽略 disabled 状态下的短句合并选项，杜绝继续把 source-only 参数带给后端。
  - [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html)
    - V1 / V2 面板都补充了短句合并提示文案，明确说明该能力只对 source 字幕 / ASR 结果生效。
- 验证证据：
  - `node --check src/subtitle_maker/static/js/dubbingPanel.js`：通过

## TODO（2026-04-27 translated 字幕短句合并能力 Spec）
- [x] Spec-1：核实 `translated` 直通链路、现有 source merge 生效点、review/redub 句级假设（带代码出处）
- [x] Spec-2：定义 `translated` merge 的用户语义、参数与最小改动面
- [x] Spec-3：确认 review/redub/resume 风险、映射策略与验证口径
- [x] HARD-GATE：等用户确认 Spec 后再实施

## Spec-1（2026-04-27 translated 字幕短句合并能力）
- 现状 1：当前 `translated` 输入的主语义是“跳过翻译，直接把上传字幕当作最终配音文本”。
  - 依据： [tools/dub_pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_pipeline.py) 的主流程在 `input_srt_is_translated` 分支里，先通过 `load_or_transcribe_subtitles(... persist_input_srt_to_source=False ...)` 读取上传字幕，然后在同文件的“translation”阶段直接执行 `translation_skipped_input_translated_srt` / `translation_rewrite_disabled`，不再调用翻译与 rewrite。
- 现状 2：当前实现会尽量保留上传译文的句级时间轴，而不是重新整理句边界。
  - 依据： [tools/dub_pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_pipeline.py) 在 `input_srt_is_translated` 分支里会把 `grouped_synthesis` 关闭、把 `force_fit_timing` 关闭；相关逻辑在主流程初始化处，注释明确写了“strict start-time alignment”和“disable hard end fitting”。
- 现状 3：现有短句合并能力严格属于 source 侧整理，不会作用到 translated 输入。
  - 依据： [tools/dub_pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_pipeline.py) 的 `load_or_transcribe_subtitles()` 只有在 `persist_input_srt_to_source=True and asr_balance_lines=True` 时才调用 `rebalance_source_subtitles()`；而 `rebalance_source_subtitles()` 内部才会继续触发 `merge_short_source_subtitles()`。
- 现状 4：Web API 当前只认识一组 source merge 参数，没有独立的 translated merge 配置。
  - 依据： [src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py) 的 `_normalize_auto_dubbing_request()` 只解析 `short_merge_enabled` / `short_merge_threshold`，并把结果落到 `source_short_merge_enabled` / `source_short_merge_threshold`。
- 现状 5：review/redub 现在默认假设“最终字幕行数”和“segment manifest 行数”一一对应。
  - 依据： [src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py) 的 `_build_review_line_mapping()` 用 segment manifest 行号顺序建立 `global_index -> local_index` 映射；`_execute_review_redub()` 又要求 `translated.srt` 与 `source.srt` 行数相等后，才能按 `local_index` 写回并调用 `_rerun_segment_with_translated_srt()`。
- 现状 6：如果后面要做 translated merge，真正的敏感点不在 TTS 本身，而在 review/redub 如何继续按句定位。
  - 依据： [src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py) 的 `_collect_review_lines()`、`_build_review_line_mapping()`、`_build_segment_review_redub_plan()`、`_execute_review_redub()` 都是按“现有逐句索引”运作，没有额外的“merged line -> original line set”映射层。

## Spec-2（2026-04-27 translated 字幕短句合并能力）
- 推荐产品语义：
  - 新增独立开关 `Merge short translated lines`，只在“实际输入模式 = translated”时展示；不复用现有 source merge 开关。
  - 默认关闭；文案明确说明“会调整你上传字幕的句边界，但不改文字内容，也不会触发翻译 rewrite”。
  - 阈值仍沿用当前秒数模型，建议保持与 source merge 一致的取值区间与默认值，避免用户理解两套不同刻度。
  - 一旦开启，系统把“并句后的 translated cues”视为本次任务后续 review/redub/resume 的 authoritative 句单元；不再保留“按原上传行号继续审阅”的承诺。
- 推荐执行时机：
  - translated merge 只在“长视频任务初始启动”时执行一次，不在 review redub 或 segment resume 时重复执行。
  - 依据 1： [src/subtitle_maker/jobs/command_builder.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/jobs/command_builder.py) 的 `build_segment_redub_command()` 当前固定传 `--input-srt-kind translated` 给局部重配；如果把“凡是 translated 输入都自动并句”写死到 CLI，会让 review redub 再次重排句边界。
  - 依据 2： [src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py) 的 `_execute_review_redub()` / `_rerun_segment_with_translated_srt()` 已经把段内 `translated.srt` 当成当前 authoritative 文本继续重跑，因此初始任务完成后不需要再次做 translated merge。
- 推荐最小实现策略：
  - 在 [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 复用现有时间窗并句算法，而不是再造第二套 translated 专用算法。
  - 依据：同文件的 `maybe_merge_translated_input_subtitles()` 直接复用了字幕领域的时间窗并句实现；它只依赖 `subtitles + target_seconds + gap_threshold`，没有 translated 专属外部状态。
  - 建议把 translated merge 放在“长视频初始编排阶段、`clip_subtitles_for_segment()` 之后、写入每段 `_input_segment.srt` 之前”，并且只允许 `resume_batch_dir is None` 时触发。这样不会跨 segment 合并，也不会在 review redub / batch resume 时重复改边界。
  - 依据： [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 的主循环已经在 `clip_subtitles_for_segment()` 后构造 `segment_subtitles`；把并句落在这里，后续 `run_segment_job()` 读到的就是本段 authoritative translated cues。
- 推荐参数与传输面：
  - Web/API/manifest/task 统一新增独立字段：
    - `translated_short_merge_enabled`
    - `translated_short_merge_threshold`
    - `translated_short_merge_threshold_mode="seconds"`
  - 不建议复用现有 `short_merge_enabled`，因为 [src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py) 的 `_normalize_auto_dubbing_request()`、任务持久化块、以及 [src/subtitle_maker/manifests/schema.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/manifests/schema.py) 的 `BatchReplayOptions` 当前都把这组字段视为 source merge 配置。
- 推荐最小改动面：
  - 前端：
    - [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html)：为 V1/V2 面板新增 translated merge 独立控件与提示文案；
    - [src/subtitle_maker/static/js/dubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/dubbingPanel.js)：按 `subtitle_mode` / `project-subtitle-mode` 控制 source merge 与 translated merge 的互斥显示，并在 `buildCommonStartFormData()` 里分别提交两组参数；`restoreLoadedBatchControls()` 也要能回填该状态。
  - API：
    - [src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py)：扩展 `/start`、`/start-from-project` 的 `Form(...)` 字段与 `_normalize_auto_dubbing_request()` 校验，并把新字段写入 task store / resume defaults / load-batch payload。
  - 命令透传：
    - [src/subtitle_maker/jobs/command_builder.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/jobs/command_builder.py) 的 `AutoDubbingCommandConfig` / `build_auto_dubbing_command()` 需要新增 CLI 参数；
    - `SegmentRedubCommandConfig` / `build_segment_redub_command()` 不建议透传这组参数，避免 review redub 二次并句。
  - CLI + manifest：
    - [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py)：在长视频初始编排层新增一次性 translated merge，并把配置写入 batch replay options；
    - [tools/dub_pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_pipeline.py)：新增 CLI flags 与 replay 字段持久化，但不在 segment pipeline 内再次执行 translated merge；
    - [src/subtitle_maker/manifests/schema.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/manifests/schema.py) 与 [src/subtitle_maker/manifests/readwrite.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/manifests/readwrite.py)：持久化与回放新字段，保证 load-batch / incomplete resume 能正确回填。
- 推荐不做的事（v1 范围外）：
  - 不做“merged line -> original uploaded line indices” 的额外映射文件。
  - 原因：如果在初始启动时就把合并后的 cues 作为 authoritative 句单元，现有 [src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py) 的 `_build_review_line_mapping()` / `_execute_review_redub()` 可以继续成立，不需要引入第二套索引系统。
  - 可追溯性仍然保留最低限度保障：Current Project 入口会通过 [src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py) 的 `_write_subtitles_json_to_srt()` 先把输入字幕落盘；Standalone 上传场景也天然保留原始字幕文件。

## Spec-3（2026-04-27 translated 字幕短句合并能力）
- 主要风险 1：如果 translated merge 在 review redub / resume-job 阶段重复触发，会把当前段内 `translated.srt` 再次改边界，直接破坏局部重配定位。
  - 依据： [src/subtitle_maker/jobs/command_builder.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/jobs/command_builder.py) 的 `build_segment_redub_command()` 固定透传 `--input-srt-kind translated`；[src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py) 的 `_execute_review_redub()` / `_rerun_segment_with_translated_srt()` 直接把段内 `subtitles/translated.srt` 当作 authoritative 文本继续跑。
  - 决策：translated merge 只允许在初始长视频任务启动时执行；`save-and-redub`、`redub-failed`、`resume-job-dir` 都不得再次执行 translated merge。
- 主要风险 2：如果新参数没有进入 task store / batch manifest / segment manifest / load-batch 恢复层，会出现“首跑生效、刷新页面后丢配置”的状态裂缝。
  - 依据： [src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py) 的任务创建块会把 `source_short_merge_*` 写入 `_tasks`；`_build_resume_options()`、`_infer_incomplete_batch_task_fields()`、`/load-batch` 也都依赖这些回放字段。
  - 依据： [src/subtitle_maker/manifests/readwrite.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/manifests/readwrite.py) 的 `_build_batch_options()` / `_build_segment_options()` / `build_batch_manifest()` / `build_segment_manifest()` 当前只读写 `source_short_merge_*`。
  - 决策：translated merge 新字段必须与 source merge 一样，完整进入 task、manifest、load-batch、resume recovery 链路；不接受“仅本次内存态可见”。
- 主要风险 3：translated merge 与 V2 时间轴标准化的先后顺序如果不稳定，会导致最终句边界不可预期，测试难以冻结。
  - 依据： [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 会先读取全局输入字幕，再在主循环里通过 `clip_subtitles_for_segment()` 产出每段 cues；segment pipeline 本身不会二次执行 translated merge。
  - 决策：实现时固定顺序为“读取全局输入字幕 -> 按段裁切 -> per-segment translated merge -> 写入 `_input_segment.srt` -> segment job 继续处理”。这个顺序一旦确认，就要用单测冻结。
- 主要风险 4：并句后 `source_full.srt` 与 `translated_full.srt` 行数可能不一致，双语字幕和 review 文案要接受这种语义。
  - 依据： [src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py) 的 `_collect_review_lines()` 优先从 final `translated_full.srt` / `source_full.srt` 覆盖文本；它按“现有最终字幕顺序”展示，不要求 source/translated 文本来自同一原始上传行号。
  - 决策：v1 接受“并句后 translated cues 是新的最终单位”；不承诺 review 里继续回显“上传前逐行对应关系”。这是功能语义的一部分，不当作 bug。
- 主要风险 5：Current Project 模式与 Standalone 模式必须表现一致，否则用户会在两条入口看到不同并句结果。
  - 依据： [src/subtitle_maker/static/js/dubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/dubbingPanel.js) 的 `buildCurrentProjectRequest()` 与 `buildStandaloneRequest()` 最终都复用 `buildCommonStartFormData()`；只要新参数在这里统一追加，就能维持两条入口一致。
  - 决策：新 translated merge 参数只能在公共表单拼装处统一生成，不能分别在 project / standalone 分支里散写。
- 不纳入本轮范围的风险：
  - 不解决“用户想回看原始上传的 translated 行号映射”这个更强需求。
  - 不解决“review 阶段再次开启/关闭 translated merge 并重算所有行号”的高级工作流。
  - 不改现有 source merge 算法本身，只复用其时间窗策略。

## Spec-3 验证口径
- 命令与参数透传：
  - 在 [tests/test_command_builder.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_command_builder.py) 增加：
    - `build_auto_dubbing_command()` 会带上 `--translated-short-merge-enabled/threshold`；
    - `build_segment_redub_command()` 默认不带这组参数，确保 review redub 不会二次并句。
- API 与 task/load-batch/recovery：
  - 在 [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 增加：
    - `/start` 与 `/start-from-project` 接受 translated merge 参数并写入 task；
    - `/load-batch` 能回填 translated merge 配置；
    - incomplete batch / `/resume/{task_id}` 续跑时会保留 translated merge 配置，但不会把它转成 segment redub 参数。
  - 在 [tests/test_job_recovery.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_job_recovery.py) 增加：
    - `build_batch_task_updates()` / `build_loaded_batch_task()` 会保留新的 replay 字段。
- Manifest 合同：
  - 在 [tests/test_manifest_contracts.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_manifest_contracts.py) 增加：
    - batch/segment manifest 写入并读取 `translated_short_merge_*`；
    - legacy manifest 缺失该字段时，reader 能稳定回落到默认值。
- 编排层算法与顺序：
  - 在 [tests/test_dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dub_long_video.py) 增加：
    - translated 输入开启 merge 时，会在 `clip_subtitles_for_segment()` 之后、写入 `_input_segment.srt` 之前按时间窗合并；
    - translated 输入关闭 merge 时，分段输入行数与文本保持不变；
    - gap 超过阈值时不跨静默合并；
    - review redub / segment resume 不会重复触发 translated merge。
- 最小手工 smoke：
  - 用一份 3 行碎 translated.srt 启动 `translated merge=true` 的任务，确认 final `translated_full.srt` 行数减少，review 面板按新行数展示；
  - 对其中 1 行执行 `save-and-redub` 或 `redub-failed`，确认只按合并后的行号重配，不会再次重新并句。

## HARD-GATE（2026-04-27 translated 字幕短句合并能力）
- Spec 已完整：现状、方案、风险、验证口径都已给出。
- 已在你明确确认后进入实现阶段，并按本节方案完成落地。

## Review（2026-04-27 translated 字幕短句合并能力）
- 实现结果：
  - Web 端已新增独立的 `translated_short_merge_enabled / translated_short_merge_threshold` 配置，并在 `translated` 模式下显示独立控件；`source` merge 与 `translated` merge 现在按输入模式互斥展示。
  - API / task store / load-batch / resume recovery / manifest replay 已完整保留 `translated_short_merge_*` 字段，避免刷新页面或续跑后丢配置。
  - 长视频初始编排层已在 [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 的 `clip_subtitles_for_segment()` 之后、写入每段 `_input_segment.srt` 之前执行一次 translated merge；segment pipeline 只解析并持久化 replay 字段，不在 review redub / segment resume 阶段再次并句。
  - `build_segment_redub_command()` 仍不透传 translated merge 参数，保持局部重配只针对当前 authoritative `translated.srt` 重跑。
- 反向同步：
  - 本次实现与早期 Spec 的偏差已修正回文档：真实执行点不在 `tools/dub_pipeline.py` 主流程，而在 `tools/dub_long_video.py` 的 per-segment 编排阶段。
- 验证证据：
  - `uv run python -m unittest tests.test_dub_long_video`：`Ran 2 tests ... OK`
  - `uv run python -m unittest tests.test_command_builder tests.test_job_recovery tests.test_manifest_contracts tests.test_dub_long_video tests.test_dubbing_cli_api`：`Ran 77 tests ... OK`

## Review（2026-04-27 translated merge smoke）
- CLI smoke 命令：
  - `uv run python tools/dub_long_video.py --input-media yue-test.mp4 --input-srt yue-test.srt --input-srt-kind translated --target-lang Chinese --out-dir ./outputs/dub_jobs_smoke --tts-backend index-tts --index-tts-via-api true --index-tts-api-url http://127.0.0.1:8010 --api-key smoke-key --translated-short-merge-enabled true --translated-short-merge-threshold 10`
- 结果拆分：
  - `translated merge` 本身已命中：CLI 输出明确记录 `Segment 01 translated merge: 3 -> 1 cues (merged_pairs=2, target=10s)`。
  - 分段输入字幕已被合并为 1 行，见 [outputs/dub_jobs_smoke/longdub_20260427_230959/segment_jobs/segment_0001/subtitles/_input_segment.srt](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/outputs/dub_jobs_smoke/longdub_20260427_230959/segment_jobs/segment_0001/subtitles/_input_segment.srt)。
  - segment manifest 已持久化 `translated_short_merge_enabled=true`、`translated_short_merge_threshold=10`，并保留 `grouped_synthesis=false`、`force_fit_timing=false`，见 [outputs/dub_jobs_smoke/longdub_20260427_230959/segment_jobs/segment_0001/manifest.json](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/outputs/dub_jobs_smoke/longdub_20260427_230959/segment_jobs/segment_0001/manifest.json)。
  - 本轮 smoke 未走到最终 `translated_full.srt`，失败原因是 `index-tts` 底座返回 `E-TTS-001 index-tts api http 503`；这属于独立的 TTS 可用性问题，不是 translated merge 逻辑失效。

## Review（2026-04-27 index-tts 启动诊断）
- 修复内容：
  - [tools/index_tts_fastapi_server.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/index_tts_fastapi_server.py) 的默认设备参数已从硬编码 `mps` 改为 `auto`，并新增 `_resolve_runtime_device()` 统一解析运行设备。
  - [start_index_tts_api.sh](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/start_index_tts_api.sh) 已新增 `INDEX_TTS_DEVICE` 环境变量，并显式透传 `--device` 给 API server。
  - 已新增单测 [tests/test_index_tts_fastapi_server.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_index_tts_fastapi_server.py) 覆盖 `auto -> cpu` 兜底与显式设备保持。
- 验证证据：
  - `uv run python -m py_compile tools/index_tts_fastapi_server.py tests/test_index_tts_fastapi_server.py`：通过
  - `uv run python -m unittest tests.test_index_tts_fastapi_server`：`Ran 2 tests ... OK`
  - 沙箱外前台启动 `index_tts_fastapi_server.py --load-on-startup` 已成功加载模型并打印 `Index-TTS API listening on http://127.0.0.1:8010`。
  - 重新跑 translated merge smoke 时，segment 日志已出现 `index_tts_api_ready` 与 `segment_tts_started`，并生成 `dubbed_segments/seg_0001_a0.wav`、`seg_0001_a1.wav`，说明本轮已跨过之前的 `index-tts api http 503` 阶段。

## TODO（2026-04-28 配音音量统一策略 Spec）
- [x] Spec-1：审计当前 TTS 产物、段内混音、batch 合并与最终导出阶段的音量处理点（带代码出处）
- [x] Spec-2：确认统一音量的产品语义、归一化策略与最小改动面
- [x] Spec-3：确认风险、回退开关、验证口径与回归范围
- [x] HARD-GATE：已确认并开始实现
- [x] 实施：新增句级活动语音归一化 helper，并接到 canonical dubbed audio 落盘路径
- [x] 实施：补齐 command / manifest / load-batch / resume recovery 的音量配置透传
- [x] 验证：语法检查 + 目标回归单测

## Spec-1（2026-04-28 配音音量统一策略）
- 现状 1：TTS backend 产出的单句音频目前没有统一响度归一化，backend 只负责“生成 / 分片拼接”，不负责调音量。
  - 依据 1： [src/subtitle_maker/backends/index_tts.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/backends/index_tts.py) 的 `IndexTtsBackend.synthesize()` 只是把分片生成后交给 `concat_generated_wavs()` 拼接，没有任何 gain / loudness 处理。
  - 依据 2： [src/subtitle_maker/backends/omni_voice.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/backends/omni_voice.py) 的 `OmniVoiceBackend.synthesize()` 只调用 CLI / API 输出 wav，也没有后置音量标准化。
- 现状 2：Index-TTS 分片拼接阶段是裸 `ffmpeg concat`，不会把同一句内部多个 part 的响度拉齐。
  - 依据： [src/subtitle_maker/domains/media/compose.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/media/compose.py) 的 `concat_generated_wavs()` 只执行 `ffmpeg -f concat ... -ac 1 -ar 22050`，没有 `loudnorm`、`volume`、`dynaudnorm` 或 RMS/LUFS 计算。
- 现状 3：段内“配音总轨”构建阶段只是按时间轴把 wav 覆盖回 master，唯一音量相关处理是“防爆音 peak clamp”，不是统一响度。
  - 依据： [src/subtitle_maker/domains/media/compose.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/media/compose.py) 的 `compose_vocals_master()` 把每句 wav 直接写进 `master[start:end] = wav`；最后只在 `peak > 0.99` 时按峰值缩回 `0.99`，没有按 LUFS / RMS 对每句做补偿。
- 现状 4：最终背景音混音阶段对人声和 BGM 都固定 `volume=1.0`，所以如果 TTS 原始句子响度不一致，最终 mix 会原样保留下来。
  - 依据： [src/subtitle_maker/domains/media/compose.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/media/compose.py) 的 `mix_with_bgm()` 使用 `[0:a]volume=1.0[v];[1:a]volume=1.0[b];[v][b]amix=...`，没有任何人声响度标准化、BGM ducking 或自适应增益。
- 现状 5：长视频 batch 合并阶段也是裸拼接，不会在 segment 之间再做一层响度统一。
  - 依据： [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 的 `main()` 在全时轴输出时，对 `dubbed_vocals_full.wav` / `source_bgm_full.wav` 使用 `concat_wav_files()` 或 `build_full_timeline_*()`；对应 [src/subtitle_maker/domains/media/compose.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/media/compose.py) 的 `concat_wav_files()` 也只是 `ffmpeg concat`，没有 loudness pass。
- 现状 6：当前 review / retry 判定只看“时长拟合”，不看响度偏差，因此系统不会把“过大/过小”句子识别成可重试或可审阅问题。
  - 依据： [tools/dub_pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_pipeline.py) 的主流程在 `synthesize_segments()` / `compose_vocals_master()` 之后，只基于 `delta_sec / effective_delta_sec / duration_error_ratio` 决定 `done / manual_review`；最新 smoke 产物 [manifest.json](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/outputs/dub_jobs_smoke/longdub_20260427_232306/segment_jobs/segment_0001/manifest.json) 的 `attempt_history` 和 `manual_review` 也只有时长字段，没有任何 loudness 指标。
- 现状 7：因此“配音音量忽大忽小”不是单一后端 bug，而是整条链路缺少一个明确的“统一响度基准”步骤。
  - 依据：从 backend 生成、分片拼接、句级 master、最终 mix 到 batch concat 的各层实现都没有 LUFS / RMS 标准化入口；当前唯一的音量保护是 `compose_vocals_master()` 里的峰值防削波。

## Spec-2（2026-04-28 配音音量统一策略）
- 推荐产品语义：
  - “统一配音音量”定义为：把每条最终用于拼轨的配音句子统一到同一个**语音响度目标**，而不是把所有波形简单拉到同一峰值。
  - 这一步只作用在 dubbed vocals，不改 source BGM，不改原视频整体响度；最终 mixed audio 只是继承“更一致的人声”。
  - v1 目标是先解决“句与句忽大忽小”，不解决“BGM 遮人声”或整片广播级母带响度一致性。
- 推荐算法：
  - 不推荐只做 peak normalize。原因是峰值一致不等于听感一致，气声/齿音/爆破音会把峰值抬高，但整句听感仍然偏小。
  - 不推荐只在最终 `dubbed_mix_full.wav` 上做一次整体 loudnorm。原因是这只能统一整片平均电平，不能修复句间相对差异；并且 [mix_with_bgm()](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/media/compose.py) 之后人声已经和 BGM 混在一起，会把问题耦合复杂化。
  - 推荐在**最终选中的句级 `seg_xxxx.wav`** 上做“活动语音 RMS/短窗响度归一化 + 峰值上限保护”：
    - 以“去掉前后静音后的活动语音窗口”测量响度；
    - 把活动语音拉到统一目标；
    - 再用峰值上限保护避免削波；
    - 对极端小声/极端大声句子设置最大增益变化夹具，避免噪声底被硬抬上来。
  - 原因 1： [src/subtitle_maker/domains/dubbing/alignment.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/alignment.py) 的 `fit_audio_to_duration()` 会在短句尾部补静音（`apad`），如果拿整条成品 wav 直接算 RMS，会把带静音的短句误判成“太小”并过度放大。
  - 原因 2：同文件的 `trim_silence_edges()` 已经证明“活动语音窗口”和“整条 wav”是两个不同概念；统一音量也应该沿用“只看有效语音”的思路。
- 推荐执行时机：
  - 主执行点放在 [src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py) 里，**在 best attempt 已选定、`persist_single_segment_output()` 已把它收敛成 canonical `seg_xxxx.wav` 之后、写 record 之前**。
  - 依据：同文件当前就是在 `best is not None` 分支里先 `shutil.copy2(best["path"], output_path)`，再 `persist_single_segment_output(seg_id, output_path)`，然后把 `tts_audio_path` 写入 record。这里插入音量统一，后面的 review / compose / mix / batch concat 都能自动复用统一后的文件。
  - 不建议放在 backend 内部。原因是 backend 层不知道最终哪个 attempt 会被保留，也不知道后面是否还会 `trim / fit / atempo`；太早做会被后续重试和时长拟合破坏。
  - 不建议只放在 `compose_vocals_master()`。原因是那样只能统一 master vocals，不能让 review 面板、局部 redub、段内 `seg_xxxx.wav` 播放都受益。
- 推荐 v1 范围：
  - 先统一**句级 canonical dubbed audio**；
  - 保留现有 `compose_vocals_master()` 的 peak clamp 作为第二道防线；
  - 最终 `mix_with_bgm()` 先不改 BGM 比例，也不加 ducking；
  - batch 级 `dubbed_vocals_full.wav` / `dubbed_mix_full.wav` 也先不额外再跑全片 loudnorm，避免把“句级统一”和“整片母带”两个问题混在一起。
- 推荐最小改动面：
  - 音频处理 helper：
    - [src/subtitle_maker/domains/media/compose.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/media/compose.py) 或新增同域 helper：新增“测活动语音响度 + 应用增益 + 峰值保护”的纯 wav 处理函数，复用现有 `numpy + soundfile` 栈，不额外引入外部依赖。
  - 句级主流程：
    - [src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py)：在 `persist_single_segment_output()` 之后对最终 `seg_xxxx.wav` 执行一次 loudness leveling，并把测得值/应用增益写入 record。
  - Manifest / replay：
    - [src/subtitle_maker/manifests/schema.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/manifests/schema.py) 与 [src/subtitle_maker/manifests/readwrite.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/manifests/readwrite.py)：记录 `dub_audio_leveling_enabled` 以及目标参数，避免 resume/load-batch 后语义漂移。
  - API / 任务配置：
    - 首轮可只走“后端默认开启 + manifest 持久化”，不急着把它做成前端新控件；先把质量问题压住，再决定是否暴露高级开关。
- 作为技术总监的推荐方案：
  - v1 采用“**句级活动语音 RMS 归一化 + 峰值上限保护 + 增益夹具**”，执行点放在 `seg_xxxx.wav` canonical 化之后。
  - 不选“最终整片 loudnorm”为主方案；那适合母带阶段，不适合修句间忽大忽小。

## Spec-3（2026-04-28 配音音量统一策略）
- 主要风险 1：如果把音量统一放在“复用已有音频”的分支也重复执行，resume / redub 会对同一条 `seg_xxxx.wav` 反复归一化，造成累计失真。
  - 依据： [src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py) 的复用分支会在 `resume_reuse_allowed` 命中时直接 `persist_single_segment_output(seg_id, reused_audio)`，然后把该文件继续写回 record。
  - 决策：句级音量统一只能作用在“本轮新选中的 best/rescue 输出”上；对 `resume_reuse_existing` 分支默认跳过，除非未来显式做离线 repair 工具。
- 主要风险 2：如果使用“整条 wav RMS”而不是“活动语音 RMS”，短句尾部补静音会被误当成小音量，导致增益过度。
  - 依据： [src/subtitle_maker/domains/dubbing/alignment.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/alignment.py) 的 `fit_audio_to_duration()` 会在短句场景追加 `apad`；`trim_silence_edges()` 已经证明边缘静音需要单独处理。
  - 决策：测量窗口必须剔除前后静音，统一活动语音响度，不得直接拿整条成品 wav 算平均能量。
- 主要风险 3：如果增益上限不设夹具，极端小声句子会把底噪一起抬高，反而更难听。
  - 依据：当前 backend 和 compose 层都没有噪声门或降噪步骤；见 [src/subtitle_maker/backends/index_tts.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/backends/index_tts.py) / [src/subtitle_maker/backends/omni_voice.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/backends/omni_voice.py) / [src/subtitle_maker/domains/media/compose.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/media/compose.py)。
  - 决策：v1 必须设置最大增益变化范围，只做“温和拉齐”，不追求每句完全同响。
- 主要风险 4：如果只在最终 `dubbed_mix_full.wav` 上统一，会把 BGM 一起重标定，既修不好句间波动，也会改变现有项目的背景乐平衡。
  - 依据： [src/subtitle_maker/domains/media/compose.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/media/compose.py) 的 `mix_with_bgm()` 直接把 vocals 和 bgm 用 `amix` 合成；一旦之后再整体处理，已无法只针对人声。
  - 决策：v1 不在最终 mix 层做主归一化；统一音量只作用在 canonical dubbed vocals。
- 主要风险 5：如果不把“音量统一开关/参数”进入 task / manifest / load-batch / resume，后续续跑会出现同批次前后音量策略不一致。
  - 依据：当前 short-merge 和 translated-merge 的 replay 字段已经通过 [src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py) 的 `_normalize_auto_dubbing_request()`、`_build_resume_options()`、`_infer_incomplete_batch_task_fields()`，以及 [src/subtitle_maker/manifests/readwrite.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/manifests/readwrite.py) 的 batch/segment manifest 读写完整回放。
  - 决策：若 v1 默认开启该能力，也至少要把 `dub_audio_leveling_enabled` 和目标参数写进 manifest；否则历史 batch 无法解释“为什么这批和那批听感不同”。
- 主要风险 6：如果统一音量发生在 `actual_duration_sec` 计算之前，任何限幅/微调都可能污染当前时长评估与 manual review 判定。
  - 依据： [src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py) 先根据 candidate wav 计算 `actual_duration_sec / duration_error_ratio / selection_score`，再选择 `best` 并落成最终 `seg_xxxx.wav`。
  - 决策：音量统一必须放在 `best` 已选定之后，只改最终保留文件，不参与 candidate 选择和时长打分。
- 不纳入本轮范围的风险：
  - 不解决“BGM 过大盖住人声”的 ducking/sidechain 问题。
  - 不做广播级两遍 `loudnorm` 或全片 LUFS 母带流程。
  - 不引入新的第三方 DSP 依赖，先复用 `numpy + soundfile`。

## Spec-3 验证口径
- 单句音量统一 helper：
  - 新增单测，覆盖：
    - 纯静音或极短 wav 不应报错；
    - 大小声两条活动语音归一化后，RMS 差距明显收敛；
    - 过大增益请求会被夹具限制；
    - 峰值保护后不出现超过 1.0 的削波。
- 句级主流程：
  - 在 [tests/test_dubbing_runtime.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_runtime.py) 增加：
    - `best` 选中后会对最终 `seg_xxxx.wav` 执行一次音量统一；
    - `resume_reuse_existing` 分支不会重复归一化既有音频；
    - `manual_review` / `done` 状态判定仍只由时长逻辑决定，不被音量步骤改变。
- Replay / manifest：
  - 在 [tests/test_manifest_contracts.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_manifest_contracts.py)、[tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py)、[tests/test_job_recovery.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_job_recovery.py) 增加：
    - 新的音量统一配置能进入 task / batch manifest / load-batch / resume recovery；
    - legacy manifest 缺失该字段时回落到稳定默认值。
- 最小 smoke：
  - 选两句明显一大一小的 TTS 句子跑一轮，检查最终 `segment_jobs/segment_xxxx/seg_*.wav` 或 canonical `seg_xxxx.wav` 的活动语音 RMS 差异显著收敛；
  - 再确认 [final/translated_full.srt](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/outputs/dub_jobs_smoke/longdub_20260427_232306/final/translated_full.srt) 这类文本产物完全不受影响；
  - 再跑一次 resume/review redub，确认历史复用音频不会被二次放大或缩小。

## Review（2026-04-28 配音音量统一）
- 核心实现：
  - [src/subtitle_maker/domains/media/compose.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/media/compose.py) 新增 `normalize_speech_audio_level()`，按短窗活动语音 RMS 做句级响度统一，并加峰值上限保护与最大增益夹具。
  - [src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py) 在逐句 `best` 输出和 grouped 最终输出上接入归一化；`resume_reuse_existing` 与“失败后复用旧音频”分支只继承旧统计，不重复处理。
  - segment record 现在会写入 `audio_leveling_*` 观测字段，方便后续从 manifest 回看某句是否被拉高/压低过。
- 配置透传：
  - [src/subtitle_maker/jobs/command_builder.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/jobs/command_builder.py)、[tools/dub_pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_pipeline.py)、[tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 已新增 `dub_audio_leveling_*` 参数并完整回放。
  - [src/subtitle_maker/manifests/schema.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/manifests/schema.py)、[src/subtitle_maker/manifests/readwrite.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/manifests/readwrite.py)、[src/subtitle_maker/jobs/recovery.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/jobs/recovery.py)、[src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py) 已把这组 hidden config 持久化到 task / batch manifest / load-batch / resume recovery。
- 验证证据：
  - `uv run python -m py_compile src/subtitle_maker/domains/media/compose.py src/subtitle_maker/domains/media/__init__.py src/subtitle_maker/domains/dubbing/pipeline.py src/subtitle_maker/jobs/command_builder.py src/subtitle_maker/manifests/schema.py src/subtitle_maker/manifests/readwrite.py src/subtitle_maker/jobs/models.py src/subtitle_maker/jobs/recovery.py src/subtitle_maker/dubbing_cli_api.py tools/dub_pipeline.py tools/dub_long_video.py tests/test_command_builder.py tests/test_job_recovery.py tests/test_manifest_contracts.py tests/test_dubbing_cli_api.py tests/test_dubbing_runtime.py`：通过
  - `uv run python -m unittest tests.test_command_builder tests.test_job_recovery tests.test_manifest_contracts tests.test_dubbing_cli_api tests.test_dubbing_runtime`：`Ran 99 tests ... OK`

## TODO（2026-04-28 Index-TTS 内存回收 + OmniVoice 隔离治理）
- [x] Spec-1：审计 `index-tts` API 生命周期、现有 release/restart 能力、`omnivoice` 质量/`missing` 观测缺口（带代码出处）
- [x] Spec-2：确认 `index-tts` 的“50 次后自动重启”策略落点，以及 `omnivoice` 的隔离修复方案
- [x] Spec-3：确认风险、隔离边界、验证口径与回归范围
- [x] HARD-GATE：已确认完整 Spec 并按方案实施

## Spec-1（2026-04-28 Index-TTS 内存回收 + OmniVoice 隔离治理）
- 现状 1：`index-tts` 服务端现在只有“按请求即时 synthesize”和“手动 release 模型”能力，没有“累计 N 次请求后自动 stop/start 重启”的机制。
  - 依据 1： [tools/index_tts_fastapi_server.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/index_tts_fastapi_server.py) 的 `IndexTTSRequestHandler._handle_synthesize()` 只处理单次 `/synthesize`，没有请求计数、内存水位或重启阈值状态。
  - 依据 2：同文件的 `ServerState.release()` 只做 `del self.tts -> empty_cache -> gc.collect()`，不会退出进程、不会重新 spawn 服务。
- 现状 2：当前链路里已经有 `index-tts api release after job`，但这只是“任务结束后卸载模型”，不是“服务重启”。
  - 依据 1： [tools/dub_pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_pipeline.py) 的 `main()` 在 `finally` 里根据 `should_release_index_tts_api` 调 `release_index_tts_api_model()`。
  - 依据 2： [src/subtitle_maker/backends/index_tts.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/backends/index_tts.py) 的 `release_index_tts_api_model()` 只调用 `/model/release`，不会 stop 进程。
- 现状 3：项目已经具备独立的 `index-tts` start/stop/release 管理面，所以“跑 50 次自动重启”不需要碰 `omnivoice` 链路，只需要在 `index-tts` 服务侧或调度侧新增计数与本地 restart 触发。
  - 依据 1： [src/subtitle_maker/index_tts_service.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/index_tts_service.py) 暴露了 `start_index_tts_service()`、`stop_index_tts_service()`、`release_index_tts_model()`。
  - 依据 2： [src/subtitle_maker/app/routes/jobs.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/app/routes/jobs.py) 已有 `/model/index-tts/start`、`/model/index-tts/release`、`/model/index-tts/stop` 路由。
  - 依据 3： [start_index_tts_api.sh](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/start_index_tts_api.sh) 当前只是单次拉起服务并等待 `/health`，没有 watchdog 或按请求轮换逻辑。
- 现状 4：从现有日志看，`index-tts` 确实会长期常驻一个进程，但日志里没有请求级计数、耗时或内存观测，无法在代码内判断“第 50 次”或“内存已经上涨到该重启了”。
  - 依据 1： [tools/index_tts_fastapi_server.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/index_tts_fastapi_server.py) 只打印 `Index-TTS API listening ...`，没有结构化请求日志。
  - 依据 2：最新 [outputs/index_tts_api.log](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/outputs/index_tts_api.log) 可见服务启动与模型加载，但没有每次 `/synthesize` 的独立记录，也没有 RSS/显存采样。
- 现状 5：`omnivoice` 当前的问题不只是不稳定，更关键的是“内容质量差但产物存在”时，后端会把它当作成功，不会自动判坏。
  - 依据 1： [src/subtitle_maker/backends/omni_voice.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/backends/omni_voice.py) 的 `OmniVoiceBackend.synthesize()` 只在 transport/连接类异常时走 `_should_attempt_local_omnivoice_recovery()`；只要 API 返回 `ok` 且输出文件存在，就算成功。
  - 依据 2： [src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py) 的 `synthesize_segments()` 里，对音频有效性的判定仅是 `_audio_is_effectively_silent(raw_path) or actual < min_valid_duration`。也就是说，“说得很快、内容乱、但不静音”的音频会直接通过。
- 现状 6：`omnivoice` 服务端当前的可观测性只能看“请求有没有完成、时长是多少”，看不到“内容是不是胡说”“语速是不是异常”。
  - 依据 1： [tools/omnivoice_fastapi_server.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/omnivoice_fastapi_server.py) 的 `OmniVoiceRequestHandler._handle_synthesize()` 只记录 `request_id/output_path/language/duration/text_preview/elapsed_ms/sample_rate`。
  - 依据 2：最新 [outputs/omnivoice_api.log](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/outputs/omnivoice_api.log) 里，`synthesize_started` 与 `synthesize_finished` 各 `83` 条、`synthesize_failed` 为 `0`；这说明 transport 层都成功了，但日志本身无法解释“音频内容烂”。
- 现状 7：`omnivoice` 的生成参数目前基本是固定默认值，没有按句长、目标时长、语言类型做更细粒度约束，因此“语速异常快”在服务层没有第二道保护。
  - 依据： [tools/omnivoice_fastapi_server.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/omnivoice_fastapi_server.py) 的 `ServerState.synthesize()` 直接把 `num_step/guidance_scale/speed/t_shift/denoise/postprocess_output/...` 从固定 cfg 或请求透传给 `model.generate()`；当前主链路只稳定透传了 `duration/language/ref_audio/ref_text`。
- 现状 8：`missing` 在现有实现里主要还是“连接失败 / 空文件 / 静音 / 过短”的结果，不是“内容差”的结果；所以你感知到的“又烂又 occasionally missing”实际上是两类问题。
  - 依据 1： [src/subtitle_maker/backends/omni_voice.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/backends/omni_voice.py) 会把连接失败、HTTP 错误、输出缺失统一抛成 `E-TTS-001`。
  - 依据 2： [src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py) 会把静音/过短识别成 `tts_invalid_audio -> E-TTS-002`，并最终落到 `manual_review` 或 `seg_xxxx_missing.wav`。
  - 依据 3：真实运行日志 [segment_0001.jsonl](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/outputs/dub_jobs/web_20260427_135229/longdub_20260427_215234/segment_jobs/segment_0001/logs/segment_0001.jsonl) 已出现 `seg_0073 marked manual review`，错误码是 `E-TTS-002`，说明当前只会抓“无效音频”，不会抓“可播放但不可懂”。
- 现状 9：可以把 `omnivoice` 修复严格隔离在 `omnivoice` 专属代码路径里，不影响当前 `index-tts` 逻辑链路。
  - 依据 1： [src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py) 的 `synthesize_text_once()` 先按 `tts_backend` 分发，`index-tts` 和 `omnivoice` 是两条独立 backend 路径。
  - 依据 2： [tools/dub_pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_pipeline.py) 的 `main()` 在 `args.tts_backend == "index-tts"` 时走 `check_index_tts_service()`，在 `else` 分支只打印 `omnivoice_backend_selected`，说明预热/服务检查已经分离。
  - 结论：如果后续只改 [src/subtitle_maker/backends/omni_voice.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/backends/omni_voice.py)、[tools/omnivoice_fastapi_server.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/omnivoice_fastapi_server.py) 以及 `omnivoice` 专属测试，不会碰 `index-tts` 的主合成链路。

## Spec-2（2026-04-28 Index-TTS 内存回收 + OmniVoice 隔离治理）
- `index-tts` 方案选项 A：继续沿用当前“每个 job 结束后 `/model/release`”策略，只是把 release 条件改成更频繁。
  - 优点：改动最小，几乎只动 [tools/dub_pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_pipeline.py) 和 [src/subtitle_maker/backends/index_tts.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/backends/index_tts.py)。
  - 不足：这不是进程重启，只是释放模型； [tools/index_tts_fastapi_server.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/index_tts_fastapi_server.py) 的 `ServerState.release()` 仍留在同一个 Python 进程里，无法满足“跑 50 次后真正重启 API 服务”这个目标。
- `index-tts` 方案选项 B：把“累计 50 次后 stop/start”放到 dubbing 调度层或 Web 路由层，由调用方计数后触发 `/stop -> /start`。
  - 优点：不需要动 `index-tts` 服务内部。
  - 不足 1：请求计数会散落在 CLI / Web / resume / review redub 多条调用链上，容易丢状态。
  - 不足 2：这会把 `index-tts` 的服务生命周期逻辑混进 [tools/dub_pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_pipeline.py) 或 [src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py)，不符合“底座问题落在底座层”的边界。
- `index-tts` 方案选项 C：在 `index-tts` 服务进程内维护请求计数，到阈值后以“特殊退出码”自愿退出；启动脚本改成监督模式，看到该退出码后自动拉起新进程。
  - 优点 1：真正实现“进程级重启”，最接近你的目标。
  - 优点 2：计数只存在 [tools/index_tts_fastapi_server.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/index_tts_fastapi_server.py) 一处；调用方完全无感，不需要改主配音链路。
  - 优点 3： [start_index_tts_api.sh](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/start_index_tts_api.sh) 本来就是唯一官方启动入口；把监督循环放这里最自然。
  - 代价：要同步调整 [stop_index_tts_api.sh](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/stop_index_tts_api.sh) 的 PID 管理，确保停掉的是监督进程而不是只停子进程。
- 我对 `index-tts` 的推荐：选 C。
  - 服务侧：
    - 在 [tools/index_tts_fastapi_server.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/index_tts_fastapi_server.py) 给 `ServerState` 增加 `requests_served`、`restart_after_requests`、`restart_pending`；
    - 每次 `/synthesize` 成功后递增计数，到阈值时先 `release()`，再以专用退出码（例如 `75`）结束进程；
    - `/health` 返回里追加 `requests_served`、`restart_after_requests`、`restart_pending`，方便排障。
  - 启动脚本侧：
    - [start_index_tts_api.sh](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/start_index_tts_api.sh) 改成监督循环；
    - 当子进程以“自动轮换退出码”结束时自动重启，其他非 0 退出仍视为异常；
    - 新增可配置阈值环境变量，例如 `INDEX_TTS_AUTO_RESTART_REQUESTS=50`，设为 `0` 则关闭。
  - 这样不会碰 `index-tts` 的调用方，也不会影响 `omnivoice`。

- `omnivoice` 方案选项 A：只补日志和观测，不改变合成策略。
  - 优点：风险最低，只动 [tools/omnivoice_fastapi_server.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/omnivoice_fastapi_server.py)。
  - 不足：只能更容易证明“它生成了烂音频”，不能减少烂音频和 `missing`。
- `omnivoice` 方案选项 B：把“异常快 / 内容异常”的判坏逻辑做进通用 pipeline。
  - 优点：可以复用 [src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py) 已有的 `actual_duration_sec / duration_error_ratio` 统计。
  - 不足：这会直接触碰当前 `index-tts` 的主合成链路，不符合你明确要求的隔离边界。
- `omnivoice` 方案选项 C：只在 `omnivoice` 服务端和 `OmniVoiceBackend` 增加“质量可观测 + 保守重试 + 本地恢复增强”，不改通用 `pipeline` 判定逻辑。
  - 优点 1：改动面严格收敛在 [src/subtitle_maker/backends/omni_voice.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/backends/omni_voice.py) 与 [tools/omnivoice_fastapi_server.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/omnivoice_fastapi_server.py)。
  - 优点 2：当前 `TtsSynthesisRequest` 已经带了 `ref_text / language / target_duration_sec`，见 [src/subtitle_maker/backends/base.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/backends/base.py)；`OmniVoiceBackend` 可以在不改 pipeline 的前提下，依据“目标时长 vs 实际时长”做本地质量门控。
  - 优点 3： [tools/omnivoice_fastapi_server.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/omnivoice_fastapi_server.py) 已支持 per-request `num_step/guidance_scale/speed/postprocess_output/...` 覆盖，因此 backend 可以在首轮异常时切到更保守的第二套参数重试。
  - 不足：它仍然不能真正“理解内容是不是胡说”；v1 主要能抓住“异常快、异常短、异常像坏样本”的那一类烂音频。
- 我对 `omnivoice` 的推荐：选 C，并拆成两步。
  - 第 1 步：先把服务端观测补齐。
    - 在 [tools/omnivoice_fastapi_server.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/omnivoice_fastapi_server.py) 的 `synthesize_started/finished/failed` 日志中增加：
      - `target_duration_sec`
      - `actual_duration_sec`
      - `duration_ratio`
      - 本次使用的 `speed/num_step/guidance_scale/postprocess_output`
      - 是否属于 `retry_profile`
    - 这样后台日志才能直接回答“它是不是快得离谱”。
  - 第 2 步：在 [src/subtitle_maker/backends/omni_voice.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/backends/omni_voice.py) 做 backend 自治。
    - 首轮仍按当前默认 profile 请求；
    - 若 API 成功但 `actual_duration_sec` 明显小于 `target_duration_sec`（例如低于某个可配比值），则触发一次“保守 profile”重试：
      - 更低 `speed`
      - 更高 `num_step`
      - 强制 `postprocess_output=true`
      - 必要时 `denoise=true`
    - 若保守重试仍明显异常，再把错误抛回上游，并在错误文本里明确标注 `omnivoice quality gate failed` 与两次参数摘要。
  - 对 `missing` 的补充：
    - 当前本地恢复只对连接/断连类错误触发，见 [src/subtitle_maker/backends/omni_voice.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/backends/omni_voice.py) 的 `_should_attempt_local_omnivoice_recovery()`；
    - 推荐把“HTTP 成功但输出缺失/0 字节/采样信息异常”的恢复也继续收在这个 backend 里，不把逻辑外溢到通用 pipeline。

- 最小改动面建议：
  - `index-tts`：
    - [tools/index_tts_fastapi_server.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/index_tts_fastapi_server.py)
    - [start_index_tts_api.sh](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/start_index_tts_api.sh)
    - [stop_index_tts_api.sh](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/stop_index_tts_api.sh)
  - `omnivoice`：
    - [src/subtitle_maker/backends/omni_voice.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/backends/omni_voice.py)
    - [tools/omnivoice_fastapi_server.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/omnivoice_fastapi_server.py)
- 不建议在本轮触碰：
  - [src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py) 的通用判坏逻辑
  - `index-tts` / `omnivoice` 以外的 backend 分发代码

## Spec-3（2026-04-28 Index-TTS 内存回收 + OmniVoice 隔离治理）
- `index-tts` 主要风险 1：自动轮换不能在当前请求返回前把进程杀掉，否则调用方会把“本次本来成功的合成”误判成 `E-TTS-001`。
  - 依据： [tools/index_tts_fastapi_server.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/index_tts_fastapi_server.py) 的 `_handle_synthesize()` 现在是“先 `tts.infer()`，再检查文件，再 `self._send_json(...)`”；如果在发送响应前直接退出，请求方只能看到连接断开。
  - 决策：轮换必须是“当前请求成功返回 -> 标记 `restart_pending` -> 进程自愿退出”；不能在 `infer()` 后立刻粗暴 `os._exit()`。
- `index-tts` 主要风险 2：监督重启脚本如果 PID 管理不清，会出现 `stop` 只停子进程、监督进程又自动拉起的反效果。
  - 依据 1： [start_index_tts_api.sh](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/start_index_tts_api.sh) 现在把后台 PID 写进 `index_tts_api.pid`。
  - 依据 2： [stop_index_tts_api.sh](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/stop_index_tts_api.sh) 当前是“读 PID -> `kill $PID` -> 端口清理”；如果未来 `PID_FILE` 存的是子进程而不是监督进程，行为会错。
  - 决策：监督模式上线后，`PID_FILE` 必须明确记录监督进程 PID；停止脚本只对监督进程负责，端口清理保留兜底。
- `index-tts` 主要风险 3：自动轮换不能改变现有 `release-after-job`、`health`、手动 `/model/release` 的语义，否则会让现有 Web 控制面失真。
  - 依据： [tools/index_tts_fastapi_server.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/index_tts_fastapi_server.py) 已有 `/health`、`/model/release`；[src/subtitle_maker/app/routes/jobs.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/app/routes/jobs.py) 已暴露对应控制入口。
  - 决策：自动轮换只增不改：
    - `/health` 追加计数字段，但保留现有 `status/service_state/loaded`
    - `/model/release` 继续只做模型释放，不触发重启
    - `INDEX_TTS_AUTO_RESTART_REQUESTS=0` 时应完全退化为当前行为

- `omnivoice` 主要风险 1：质量门控如果放进通用 `pipeline`，会直接污染 `index-tts` 的主链路，违背隔离边界。
  - 依据： [src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py) 的 `synthesize_text_once()` 与 `synthesize_segments()` 是所有 backend 共用的主循环。
  - 决策：本轮所有“异常快/质量差”的特殊逻辑都只能收在 [src/subtitle_maker/backends/omni_voice.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/backends/omni_voice.py) 与 [tools/omnivoice_fastapi_server.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/omnivoice_fastapi_server.py)。
- `omnivoice` 主要风险 2：仅凭“目标时长明显偏短”做质量门控，会误杀某些本来就该很短的自然句。
  - 依据 1： [src/subtitle_maker/backends/base.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/backends/base.py) 的 `TtsSynthesisRequest` 里 `target_duration_sec` 是可选值，不是每次都严格存在。
  - 依据 2： [src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py) 对 `omnivoice` 已有“自然收尾更宽松”的容忍，例如 `omnivoice_keep_natural_no_atempo` 分支。
  - 决策：v1 质量门控只拦“明显异常”的样本：
    - 仅当 `target_duration_sec` 存在时启用
    - 使用偏保守的最小比值阈值
    - 只触发一次保守 profile 重试，不在 backend 内做无限循环
- `omnivoice` 主要风险 3：如果把“质量差”直接伪装成 `missing`，会混淆两类问题，后续排障更难。
  - 依据：当前 [src/subtitle_maker/backends/omni_voice.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/backends/omni_voice.py) 已把连接/HTTP/输出缺失统一映射到 `E-TTS-001`；而 [src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py) 把静音/过短映射到 `E-TTS-002`。
  - 决策：新增的 `omnivoice quality gate failed` 必须在错误文本里显式带上“quality gate”字样和两次 profile 摘要，不能伪装成普通 connect failed。
- `omnivoice` 主要风险 4：服务端日志如果只记最终 `finished`，看不到 retry profile 和时长比值，事后还是无法解释“为什么听起来很快”。
  - 依据：当前 [tools/omnivoice_fastapi_server.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/omnivoice_fastapi_server.py) 的 `synthesize_finished` 只记 `elapsed_ms/duration_sec/sample_rate`。
  - 决策：日志字段必须同时覆盖请求目标和生成结果：
    - `target_duration_sec`
    - `actual_duration_sec`
    - `duration_ratio`
    - `speed/num_step/guidance_scale/postprocess_output`
    - `retry_profile`

- 验证口径：
  - `index-tts` 服务层：
    - 扩展 [tests/test_index_tts_fastapi_server.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_index_tts_fastapi_server.py)：
      - `auto restart requests=0` 时不触发轮换
      - 达到阈值前，`requests_served` 按请求递增
      - 达到阈值后，只在当前请求成功完成后标记 `restart_pending`
      - `/health` 返回新增计数字段
    - 若把“退出码判定”抽成 helper，优先单测 helper；不要求在单测里真的 `fork` 监督进程。
  - `index-tts` 启动脚本：
    - 至少做一条脚本级最小验证：
      - 设低阈值（如 `INDEX_TTS_AUTO_RESTART_REQUESTS=1`）
      - 连续打两次 `/synthesize`
      - 确认第二次前服务仍可用，且日志/健康检查能看出一次自动轮换
    - 这条更适合手工 smoke，不要求进 Python 单测。
  - `omnivoice` backend：
    - 在 [tests/test_dubbing_runtime.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_runtime.py) 扩展 `OmniVoiceBackend` 回归：
      - 现有 `test_omnivoice_backend_api_passes_duration()` 继续通过，证明没有改坏目标时长透传
      - 新增“首轮返回明显过短 -> 自动切保守 profile 重试一次”的断言
      - 新增“保守重试后仍异常 -> 抛出带 `quality gate failed` 的错误”断言
      - 现有 `test_omnivoice_backend_api_restarts_local_service_after_connect_failure()` 继续通过，证明连接恢复逻辑不退化
  - `omnivoice` 服务端日志：
    - 可通过单测或轻量 mock 验证日志 payload 至少包含 `target_duration_sec/actual_duration_sec/duration_ratio/retry_profile`
    - 不要求单测真正跑 OmniVoice 模型
  - 回归保护：
    - [tests/test_dubbing_runtime.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_runtime.py) 里现有 `omnivoice_keep_natural_no_atempo` 相关回归必须继续通过，证明这次没有把自然收尾策略误伤。
    - 这轮不新增也不修改 `index-tts` 主配音 pipeline 的判坏标准；若有任何现有 `index-tts` runtime 测试失败，视为越界。

- 最小 smoke：
  - `index-tts`：
    - 本地把阈值设成 `1` 或 `2`，快速发几次短句合成；
    - 观察 [outputs/index_tts_api.log](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/outputs/index_tts_api.log) 与 `/health`，确认请求成功、计数递增、到阈值后发生一次自动轮换。
  - `omnivoice`：
    - 选一条过去容易“说得很快”的句子跑一次；
    - 检查 [outputs/omnivoice_api.log](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/outputs/omnivoice_api.log) 是否能直接看出 `target_duration_sec -> actual_duration_sec -> duration_ratio -> retry_profile`；
    - 若仍失败，错误应明确区分“connect failure/missing”还是“quality gate failed”。

## Review（2026-04-28 Index-TTS 内存回收 + OmniVoice 隔离治理）
- 核心实现：
  - [tools/index_tts_fastapi_server.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/index_tts_fastapi_server.py) 新增 `requests_served / restart_after_requests / restart_pending`，`/health` 会暴露计数字段；达到阈值后不打断当前请求，而是在响应成功返回后异步 `shutdown()`，主进程以专用退出码 `75` 退出。
  - [start_index_tts_api.sh](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/start_index_tts_api.sh) 改成监督模式：子进程若以自动轮换退出码结束，就自动拉起新进程；[stop_index_tts_api.sh](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/stop_index_tts_api.sh) 继续通过 `PID_FILE` 停监督进程并保留端口清理兜底。
  - [src/subtitle_maker/backends/omni_voice.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/backends/omni_voice.py) 新增 `quality gate`：首轮 API 成功但相对 `target_duration_sec` 明显过短时，自动切保守 profile（更低 `speed`、更高 `num_step/guidance_scale`）重试一次；若仍异常，抛出带 `omnivoice quality gate failed` 的明确错误。
  - [tools/omnivoice_fastapi_server.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/omnivoice_fastapi_server.py) 现在会把 `target_duration_sec / actual_duration_sec / duration_ratio / retry_profile / speed / num_step / guidance_scale / denoise / postprocess_output` 带进结果与日志，便于直接从后台日志判断“是不是说得过快”。
- 回归覆盖：
  - [tests/test_index_tts_fastapi_server.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_index_tts_fastapi_server.py) 新增自动轮换阈值、`restart_pending` 与健康字段断言。
  - [tests/test_dubbing_runtime.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_runtime.py) 新增 `OmniVoiceBackend` 的“明显过快 -> 保守 profile 重试”和“保守重试后仍异常 -> quality gate failed”回归，同时保留现有连接恢复测试。
  - [tests/test_omnivoice_fastapi_server.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_omnivoice_fastapi_server.py) 新增服务端运行参数解析与 `duration_ratio / retry_profile` 元数据测试。
- 验证证据：
  - `uv run python -m py_compile tools/index_tts_fastapi_server.py src/subtitle_maker/backends/omni_voice.py tools/omnivoice_fastapi_server.py tests/test_index_tts_fastapi_server.py tests/test_dubbing_runtime.py tests/test_omnivoice_fastapi_server.py`：通过
  - `bash -n start_index_tts_api.sh stop_index_tts_api.sh`：通过
  - `uv run python -m unittest tests.test_index_tts_fastapi_server tests.test_dubbing_runtime tests.test_omnivoice_fastapi_server`：`Ran 33 tests ... OK`
  - 这轮还没有做服务级 smoke，原因是你当前还在跑本地测试；我没有去主动重启现有 `index-tts` / `omnivoice` 进程。

## TODO（2026-04-28 review redub 后 final 字幕被旧译文覆盖）
- [x] Spec-1：审计 `review/redub -> batch rebuild -> 长视频最终 merge` 三段链路，定位为何任务结束后又回到旧字幕
- [x] Spec-2：确认修复落点、最小改动面，以及为何昨天的修复没有覆盖这次场景
- [x] Spec-3：确认风险、验证口径与回归范围
- [x] HARD-GATE：已确认完整 Spec 并按方案实施

## Spec-1（2026-04-28 review redub 后 final 字幕被旧译文覆盖）
- 现状 1：`save-and-redub` 修改的 authoritative 文本，实际落点是每个 segment 自己目录下的 `subtitles/translated.srt` 和 `subtitles/dubbed_final.srt`，不是 segment manifest 里的历史 `paths.translated_srt`。
  - 依据 1： [src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py) 的 `_execute_review_redub()` 先读取 `segment_job_dir / "subtitles" / "translated.srt"` 与 `source.srt`，然后把改动直接写回 `translated_srt_path.write_text(...)` 和 `dubbed_final_srt_path.write_text(...)`。
  - 依据 2：同函数只同步更新了 `segment_manifest.raw["segments"][...]["translated_text"]`，并没有同步改 `segment_manifest.raw["paths"]["translated_srt"]` / `["dubbed_final_srt"]` 指向。
- 现状 2：昨天修过的 `_rebuild_batch_outputs()` 只负责“事后重拼 batch final 产物”，它已经优先读取 `segment/subtitles/*.srt`，但这条修复并没有覆盖“长视频任务自然结束时的主流程 merge”。
  - 依据 1： [src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py) 的 `_execute_review_redub()` 在局部重配后显式调用 `_rebuild_batch_outputs(batch_dir)`。
  - 依据 2： [tools/repair_bad_segments.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/repair_bad_segments.py) 的 `rebuild_batch_outputs()` 现在对 `translated_srt` / `dubbed_final_srt` 的策略是“只要 `segment/subtitles/*.srt` 存在，就优先用它；manifest 路径只作为回退”。
  - 依据 3： [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 的 `test_rebuild_batch_outputs_updates_final_subtitles_when_some_segments_are_skipped()` 也只锁住了 `_rebuild_batch_outputs()` 这条路径。
- 现状 3：真正把你“中途改好的译文”覆盖回旧文案的，更可能是任务结束时 [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 的主流程 `Step 5/5: merge outputs`。
  - 依据 1： [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 的主函数在所有 segment 完成后，统一执行 `merge outputs`，并直接生成 `final/translated_full.srt` 与 `final/dubbed_final_full.srt`。
  - 依据 2：同文件当前对 `translated_srt` / `dubbed_final_srt` 的策略仍是“先读 `item.manifest["paths"]`，只有 manifest 路径缺失或文件不存在时，才回退 `segment/subtitles/*.srt`”。
  - 结论：如果 `save-and-redub` 期间只是更新了 `segment/subtitles/*.srt`，但 manifest 里的旧路径文件仍存在，那么任务最终自然收尾时，`dub_long_video.py` 会再次把旧字幕拼回 `final/*_full.srt`。
- 现状 4：这解释了“昨天说修了，但今天你还是复现”的原因。昨天那次修复挡住的是“review redub 完成后立即手动/自动 rebuild batch final”的场景，没有挡住“主任务仍在跑，最后由 `dub_long_video.py` 再 merge 一次”的场景。
  - 依据 1： [tasks/lessons.md](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tasks/lessons.md) 已记录“batch 重建字幕时，必须优先读取 `segment/subtitles/*.srt` 最新文件”。
  - 依据 2：但当前 [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 的最终 merge 逻辑还没有同步同样的优先级修复，因此 lessons 落地是不完整的。
- 现状 5：review 面板本身读到的文字并不是问题源头；前端看到你改后的文本，和最终文件又被覆盖，是两回事。
  - 依据 1： [src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py) 的 `_collect_review_lines()` 明确优先用 `final/translated_full.srt` 覆盖 `translated_text`，注释里也写了“用户真正看到和修改的文本”。
  - 依据 2：同文件的 `_persist_review_lines()` 会先把全局 `translated_full.srt` / `dubbed_final_full.srt` 写成你修改后的内容，再进入 `_execute_review_redub()`。
  - 结论：你看到“改动成功”，说明 review 编辑链路本身没丢；问题出在后面的段级重配写回和最终 batch merge 重新收口时。
- 现状 6：当前测试缺口也和这个场景吻合。仓库里已经有“rebuild 后 final 不该读旧字幕”的回归，但还没有“任务仍在进行，最终由 `dub_long_video.py` 收尾 merge 时也不能回退旧字幕”的回归。
  - 依据： [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 现有相关回归都集中在 `_rebuild_batch_outputs()`、`save-and-redub` 回滚、`load-batch` 元数据恢复；没有直接覆盖 [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 的 `merge outputs` 字幕输入优先级。

## Spec-2（2026-04-28 review redub 后 final 字幕被旧译文覆盖）
- 方案选项 A：只在 `save-and-redub` 时把 segment manifest 的 `paths.translated_srt/dubbed_final_srt` 改成最新文件，其他读取方不动。
  - 优点：改动面小，表面上能减少“路径还指向旧文件”的概率。
  - 不足 1：不能解决 [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 已经把 manifest 提前读进 `results` 内存快照的问题。依据：同文件在构建 `SegmentResult` 时，把 `manifest = load_segment_manifest(manifest_path).raw` 直接塞进 `results.append(... manifest=manifest)`，之后 `merge outputs` 读取的是 `item.manifest`，不是重新读磁盘。
  - 不足 2：这只是“写侧补救”，无法防住其他地方未来再读旧优先级。
- 方案选项 B：只修 [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 的最终 `merge outputs`，让它在收尾时对字幕文件一律优先使用 `job_dir/subtitles/*.srt`，并尽量重新读取最新 manifest/路径。
  - 优点：直击这次 bug 的收尾覆盖点，能覆盖“任务仍在跑，最终自然完成”的真实场景。
  - 不足：如果其他链路未来还存在“优先信旧 manifest 路径”的读取逻辑，仍可能留下同类隐患。
- 方案选项 C：做一个统一的“段内最新字幕路径解析”策略，最小范围内同时用于 `dub_long_video.py` 主 merge 和已有的 `repair_bad_segments.py` rebuild；必要时再把 `save-and-redub` 写侧同步到 canonical 路径。
  - 优点：读侧语义统一，避免“一处修了，另一处忘了”的重复回归。
  - 不足：比只补 `dub_long_video.py` 多一点改动面，需要补 2 类回归测试。

- 我的推荐：选 C，但实现强度按“最小可交付”控制，不做大重构。
  - 第 1 步：修 [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 的 `Step 5/5: merge outputs`。
    - 决策 1：对 `source_srt/translated_srt/dubbed_final_srt`，优先读 `item.job_dir / "subtitles" / *.srt`，只有这些文件不存在时才回退 manifest 路径。
    - 决策 2：不要再完全信任 `results` 里缓存的 `item.manifest` 字幕路径；收尾 merge 时要以 segment 当前磁盘状态为准。
    - 原因：这次 bug 的关键不是 review 没写进去，而是“主流程晚于 review 收尾，并且拿着旧快照重新拼了一次”。
  - 第 2 步：把同一套解析顺序收敛成一个小 helper，给 [tools/repair_bad_segments.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/repair_bad_segments.py) 和 [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 共用，避免两边再次漂移。
    - 依据：两边现在都在手写 `resolve_output_path(...) + fallback subtitles/*.srt`，只是优先级不同，重复逻辑本身就是回归源。
  - 第 3 步：作为硬化项，在 [src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py) 的 `_execute_review_redub()` 里，文本有改动时同步把 segment manifest 的 `paths.translated_srt/dubbed_final_srt` 回写到 canonical `segment/subtitles/*.srt`。
    - 这不是主修复，但能降低其他旧读取方继续踩 stale path 的概率。

- 最小改动面建议：
  - 主修复文件： [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py)
  - 共享 helper 落点：优先放在 [tools/repair_bad_segments.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/repair_bad_segments.py) 和 `dub_long_video.py` 都能低成本调用的位置；如果需要进 `src/`，也只抽“解析最新 segment subtitle 路径”的纯函数，不动现有命令/manifest 协议。
  - 次级硬化： [src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py)

- 为什么昨天那次修复没成功，这次方案能补上：
  - 昨天修的是“review 结束后调用 `_rebuild_batch_outputs()` 时，不要再从 stale manifest path 读旧字幕”。
  - 这次要补的是“就算主任务后来继续跑完，也不能在 `dub_long_video.py` 的最终 merge 再次覆盖回旧字幕”。
  - 两者不是同一条链路，所以必须分别修。

## Spec-3（2026-04-28 review redub 后 final 字幕被旧译文覆盖）
- 主要风险 1：如果修复范围扩得太大，把 `paths.*` 的所有读取都一起改掉，容易误伤音频复用和 segment 可复用判定。
  - 依据： [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 的 `is_segment_job_reusable()` 除了看 `translated_srt/dubbed_final_srt`，还看 `dubbed_vocals`；`collect_reusable_jobs_by_segment()` 又依赖这个判定决定 resume 时是否跳过重跑。
  - 决策：v1 主修复只收敛在“字幕文件路径解析”层，不碰音频路径解析和可复用统计语义；必要时仅把 `translated_srt/dubbed_final_srt` 的存在性检查改成同一 helper，避免字幕路径逻辑再次分叉。
- 主要风险 2：如果只修 `merge outputs` 读取顺序，不补写侧 canonical path，同类 stale path 以后仍可能在其他读点复发。
  - 依据： [src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py) 的 `_execute_review_redub()` 当前只更新 `segments[].translated_text`，不更新 `manifest.paths.translated_srt/dubbed_final_srt`。
  - 决策：本轮把“写侧同步 canonical subtitle paths”作为次级硬化一并做掉，但不把它当主修复依赖。
- 主要风险 3：如果 helper 设计成“永远忽略 manifest path，只看 `subtitles/*.srt`”，会影响某些历史/异常任务的容错。
  - 依据： [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 和 [tools/repair_bad_segments.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/repair_bad_segments.py) 现在都保留了 `resolve_output_path(paths.get(...))` 作为回退，说明历史任务里确实可能存在只靠 manifest path 才能找到文件的情况。
  - 决策：helper 语义固定为“优先 canonical `segment/subtitles/*.srt`，不存在时回退 manifest path”，不能改成只认一种来源。
- 主要风险 4：如果修复只覆盖 `translated_full.srt`，漏掉 `dubbed_final_full.srt`，前端仍会出现“字幕文本和双语字幕不一致”。
  - 依据： [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 的最终 merge 同时维护 `translated_srt_inputs` 和 `dubbed_final_srt_inputs`；[src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py) 的 `_collect_written_batch_paths()` 也同时向前端暴露 `translated_full_srt` 与 `dubbed_final_full_srt`。
  - 决策：两条字幕产物必须同时修，同一 helper、同一优先级、同一回归。
- 主要风险 5：如果只补 `dub_long_video.py` 主 merge，不给它加独立回归，后续很容易再次被 `repair_bad_segments.py` 和主流程漂移带回来。
  - 依据：当前 [tests/test_dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dub_long_video.py) 还没有覆盖“manifest 路径是旧字幕，但 `segment/subtitles/*.srt` 是新字幕，最终 full 字幕必须选新字幕”这个场景。
  - 决策：必须新增 `tests/test_dub_long_video.py` 回归，直接锁住主流程 `merge outputs` 的字幕优先级。
- 主要风险 6：如果主流程 merge 重新读取磁盘最新字幕，不能顺手改变 translated merge、grouped synthesis、review redub 的既有语义。
  - 依据： [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 当前除了字幕 merge，还负责 translated merge 的初始编排与最终音频合成；[tests/test_dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dub_long_video.py) 已锁住 translated merge 的执行时机。
  - 决策：本轮只改字幕输入文件的解析优先级，不动 segment 切分、translated merge、生成功能参数和音频合并逻辑。

- 验证口径：
  - 单元/模块级：
    - 在 [tests/test_dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dub_long_video.py) 新增回归：
      - 构造 segment manifest 的 `paths.translated_srt/dubbed_final_srt` 指向旧文件；
      - 同时在 `segment/subtitles/translated.srt`、`dubbed_final.srt` 写入新文本；
      - 断言主流程 `main()` 最终生成的 `final/translated_full.srt` 与 `final/dubbed_final_full.srt` 都使用新文本。
    - 若抽 helper，再给 helper 单测或通过上述场景覆盖其“canonical 优先、manifest 回退”语义。
  - HTTP/review 级：
    - 在 [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 增加一条“`save-and-redub` 改完后，segment manifest 的 `paths.translated_srt/dubbed_final_srt` 会同步到 canonical 字幕路径”的断言；这条用于锁写侧硬化。
  - 回归保护：
    - 现有 `test_rebuild_batch_outputs_updates_final_subtitles_when_some_segments_are_skipped()` 必须继续通过，确保昨天修过的 `_rebuild_batch_outputs()` 不回退。
    - 现有 translated merge 回归必须继续通过，确保这次不误伤 [tests/test_dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dub_long_video.py) 已有的 “translated merge 只在初始编排执行一次” 语义。
- 最小 smoke：
  - 选一个正在跑或可快速复现的 translated 输入任务，在 segment 跑完但 batch 未结束前执行一次 `save-and-redub`；
  - 任务自然结束后，核对 `segment/subtitles/translated.srt`、`final/translated_full.srt`、`final/dubbed_final_full.srt` 三者文本一致，不再出现“配音是新文案、final 字幕是旧文案”。

## Review（2026-04-28 review redub 后 final 字幕被旧译文覆盖）
- 核心实现：
  - [src/subtitle_maker/manifests/readwrite.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/manifests/readwrite.py) 新增 `resolve_output_path()` 与 `resolve_preferred_segment_subtitle_path()`，把“优先 canonical `segment/subtitles/*.srt`、缺失时回退 manifest path”的语义收敛成一处。
  - [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 的 `is_segment_job_reusable()` 与最终 `merge outputs` 已接入同一 helper；主任务自然结束时不再因为内存里的旧 manifest 路径把 `final/translated_full.srt` / `dubbed_final_full.srt` 覆盖回旧文案。
  - [tools/repair_bad_segments.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/repair_bad_segments.py) 改为复用同一 helper，保持“事后 rebuild”与“主流程收尾 merge”一致。
  - [src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py) 的 `_execute_review_redub()` 在文本改动时同步回写 segment manifest 的 `paths.translated_srt` / `paths.dubbed_final_srt` 到 canonical 字幕文件，降低其他旧读取方继续踩 stale path 的概率。
- 回归覆盖：
  - [tests/test_dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dub_long_video.py) 新增“manifest 指向旧字幕、segment/subtitles 是新字幕时，主流程 final merge 必须选新字幕”的回归。
  - [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 增加 `save-and-redub` 后 segment manifest 字幕路径回写 canonical 的断言。
- 验证证据：
  - `uv run python -m py_compile src/subtitle_maker/manifests/readwrite.py src/subtitle_maker/manifests/__init__.py src/subtitle_maker/dubbing_cli_api.py tools/dub_long_video.py tools/repair_bad_segments.py tests/test_dub_long_video.py tests/test_dubbing_cli_api.py`：通过
  - `uv run python -m unittest tests.test_dub_long_video tests.test_dubbing_cli_api`：`Ran 65 tests ... OK`
  - `uv run python -m unittest tests.test_manifest_contracts tests.test_job_recovery`：`Ran 8 tests ... OK`

## Spec-1（2026-04-28 OmniVoice 配音质量调参调研）
- [x] 调研 `/Users/tim/Documents/vibe-coding/MVP/OmniVoice` 源码与现有文档，定位推理入口、生成参数、音色参考、语言映射、时长控制、批量推理能力。
- [x] 基于源码证据整理“配音最佳参数建议”，写入 OmniVoice repo 的 `docs/` 下，明确适用于字幕配音场景。
- [x] 回到 subtitle-maker 接入链路，解释当前 OmniVoice 效果差的根因，所有结论标注文件路径 + 函数名。
- [x] 明确下一步改造建议，但在没有新的 HARD-GATE 前不修改 subtitle-maker 的 OmniVoice 代码链路。

## Review（2026-04-28 OmniVoice 配音质量调参调研）
- 已写入调研文档：`/Users/tim/Documents/vibe-coding/MVP/OmniVoice/docs/dubbing-parameter-tuning.md`。
- 核心结论：当前效果差不是单纯参数问题，而是“逐句极短参考音 + 固定字幕时长 + 跨语言 voice clone + 默认随机 position sampling”的组合把 OmniVoice 放进了高失败率工作区间。
- 本轮未修改 subtitle-maker 的 OmniVoice 代码链路；只更新 `tasks/todo.md`、`tasks/lessons.md` 和 OmniVoice repo 的调研文档。
- 验证证据：
  - `wc -l docs/dubbing-parameter-tuning.md`：132 行
  - 本地数据统计：`outputs/dub_jobs/web_20260427_135229/longdub_20260427_215234` 有 303 个逐句 reference，其中 17 个短于 1.2s、11 个短于 0.8s；同任务 target duration 最短 0.119s，`seg_0073` 在 0.156s 目标时长下进入 manual review/missing。

## Spec-4（2026-04-28 translated short merge 实际执行链复核）
- 现状 1：`translated_short_merge` 不是“只有参数、没有执行”；它已经在长视频编排层执行。
  - 依据： [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 的 `maybe_merge_translated_input_subtitles()` 会在开关开启时复用 `merge_short_source_subtitles(...)` 做一次性并句；主流程 `main()` 在 `clip_subtitles_for_segment()` 之后、`run_segment_job()` 之前调用它。
- 现状 2：这个并句只在“上传字幕且 `input_srt_kind=translated` 且 `resume_batch_dir is None`”时执行，不会在 review redub / resume 阶段再次改边界。
  - 依据： [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 的 `main()` 里，translated merge 的触发条件是 `segment_subtitles and args.input_srt_kind == "translated" and resume_batch_dir is None`。
- 现状 3：前端和 API 已经区分了两套开关，`Merge short source lines` 与 `Merge short translated lines` 不是同一个东西。
  - 依据 1： [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html) 同时定义了 `auto-dub-short-merge-enabled` 与 `auto-dub-translated-short-merge-enabled` 两套控件，并分别给出“只对 source 生效”与“只对 translated 直通模式生效”的提示文案。
  - 依据 2： [src/subtitle_maker/static/js/dubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/dubbingPanel.js) 的 `buildCommonStartFormData()` 会同时提交 `short_merge_enabled/threshold` 与 `translated_short_merge_enabled/threshold`。
  - 依据 3： [src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py) 的 `start_auto_dubbing()`、`start_auto_dubbing_from_project()` 与 `_normalize_auto_dubbing_request()` 会分别接收、校验并持久化这两组字段。
- 现状 4：`translated_short_merge` 的算法能力和边界与 source merge 基本一致，它不是“无条件大并句”。
  - 依据： [src/subtitle_maker/domains/subtitles/short_merge.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/subtitles/short_merge.py) 的 `merge_short_source_subtitles()` 只会在相邻字幕静默间隔不超过阈值时合并；默认 15s 目标会推导出 `round(target / 3)` 的容差，且单条候选若已明显过长就不会继续并。
- 现状 5：如果用户上传 translated 字幕，却勾的是 `Merge short source lines`，那条开关确实不会作用到 TTS 输入；要生效必须使用 `Merge short translated lines`。
  - 依据： [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html) 的 source merge 提示文案已明确写明“仅对 source 字幕 / ASR 结果生效”；真正的 translated merge 在 [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 的 `main()` 中单独走分支。

## Review（2026-04-28 translated short merge 实际执行链复核）
- 纠偏结论：前面“`translated_short_merge` 只有参数透传、没有真实执行逻辑”的判断不成立；真实执行点在长视频编排层 [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py)，不是 segment CLI [tools/dub_pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_pipeline.py)。
- 当前更准确的结论应该是：
  - 上传 translated 字幕后，如果勾的是 `Merge short source lines`，不会生效。
  - 如果勾的是 `Merge short translated lines`，会在每个 segment 裁切后做一次性并句。
  - 该并句不会跨 segment，也不会跨越大于 1.5s 的静默间隔，更不会在 review redub / resume 阶段再次改边界。
- 本轮未改业务代码；只修正分析基线，避免后续基于错误前提继续设计或实现。

## TODO（2026-04-28 translated merge 意图同步 + 可观测性）
- [x] 前端：当用户已开启 source merge 又切到 translated 模式时，自动迁移一次“想合并短句”的意图到 translated merge，避免隐藏 source 开关后配置看似丢失
- [x] 编排层：为每个 segment 补充 translated merge 决策日志，输出 enabled/before/after/merged_pairs/threshold，便于直接排查“到底有没有并句”
- [x] 回归测试：补一条长视频编排测试，锁住 translated merge 日志与一次性执行语义
- [x] 最小验证：`node --check` + `uv run python -m unittest tests.test_dub_long_video`

## Review（2026-04-28 translated merge 意图同步 + 可观测性）
- 前端交互：
  - [src/subtitle_maker/static/js/dubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/dubbingPanel.js) 新增“短句合并意图同步”逻辑：
    - 当用户先勾了 source merge，再切到 translated 模式，且 translated merge 还没有被用户显式配置过时，会自动开启 translated merge，并复制当前阈值；
    - translated merge 提示文案会明确说明这是沿用刚才的 source merge 意图，减少“我明明开了 merge，怎么没生效”的错觉。
  - 这次没有改动 source/translated 两套开关的后端协议，也没有改变 `index-tts` / `omnivoice` 的任何合成参数。
- 编排层可观测性：
  - [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 现在会在 translated 输入的每个 segment 上稳定打印 merge 决策：
    - `status=applied|skipped_resume`
    - `enabled=...`
    - `before=... after=...`
    - `merged_pairs=...`
    - `target=...s`
  - 这样后续看后台日志时，可以直接判断“有没有并句”和“为什么没有并句”，不再只能靠最后的 SRT 结果反推。
- 回归与验证：
  - [tests/test_dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dub_long_video.py) 现有 translated merge 回归已补充 stdout 断言，锁住一次性执行语义和日志内容。
  - `node --check src/subtitle_maker/static/js/dubbingPanel.js`：通过
  - `uv run python -m py_compile tools/dub_long_video.py tests/test_dub_long_video.py`：通过
  - `uv run python -m unittest tests.test_dub_long_video`：`Ran 3 tests ... OK`

## TODO（2026-04-28 OmniVoice 过短目标时长保护）
- [x] 仅在 OmniVoice backend 增加最短 target duration 校验，过短句子直接拒绝并给出明确错误
- [x] 保持 `index-tts` 与现有 fallback 语义不变，不改其他底座链路
- [x] 回归测试：补 OmniVoice backend 的短时长拒绝用例
- [x] 最小验证：`py_compile` + `tests.test_dubbing_runtime`

## Review（2026-04-28 OmniVoice 过短目标时长保护）
- 代码改动：
  - [src/subtitle_maker/backends/omni_voice.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/backends/omni_voice.py) 新增 `_validate_request()`，在 OmniVoice 真正发起 API/CLI 合成前先检查 `target_duration_sec`；
  - 当 `0 < target_duration_sec < 1.2s` 时，直接抛出 `E-TTS-001 omnivoice target duration below safe floor`，避免把明显不适合的极短句继续送进 OmniVoice 生成阶段。
- 影响边界：
  - 这条 guard 只作用于 OmniVoice backend，不影响 [src/subtitle_maker/backends/index_tts.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/backends/index_tts.py)；
  - 也没有修改现有 fallback 语义，只是让 OmniVoice 在已知高失败率区间尽早失败、进入现有 manual review / 错误处理路径。
- 回归测试：
  - [tests/test_dubbing_runtime.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_runtime.py) 新增短时长拒绝用例，断言 backend 在 `target_duration_sec=0.8` 时会直接报错，且不会真的发 HTTP 请求。
- 验证证据：
  - `uv run python -m py_compile src/subtitle_maker/backends/omni_voice.py tests/test_dubbing_runtime.py`：通过
  - `uv run python -m unittest tests.test_dubbing_runtime`：`Ran 27 tests ... OK`

## TODO（2026-04-28 OmniVoice 共享参考音优先）
- [x] 仅在 `tts_backend=omnivoice` 时，把参考音 selector 改为“共享参考音优先，逐句 reference 达到最短时长门槛才启用”
- [x] 保持 `index-tts` 现有逐句 reference 逻辑不变，不影响当前主链路
- [x] 编排日志补充 OmniVoice reference 命中统计，便于直接看 shared/subtitle 各用了多少条
- [x] 回归测试：补 `dub_pipeline` 的 reference selector 用例
- [x] 最小验证：`py_compile` + `tests.test_dub_pipeline_asr_layout`

## Review（2026-04-28 OmniVoice 共享参考音优先）
- 代码改动：
  - [tools/dub_pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_pipeline.py) 新增 `build_backend_reference_selector()`，把参考音选择策略收敛成一处；
  - 当 `tts_backend != omnivoice` 时，维持原有 `sentence_original_audio_per_subtitle` 逻辑；
  - 当 `tts_backend == omnivoice` 时，改为 `shared_reference_preferred_for_omnivoice`：默认优先使用共享 `single_speaker_ref.wav`，只有逐句 reference 时长 `>= 1.2s` 才会真正启用逐句 reference。
- 现有链路影响：
  - 这次没有修改 [src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py) 的合成行为，只改了传给它的 `ref_audio_selector`；
  - [tools/dub_pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_pipeline.py) 的 `reference_ready` / `sentence_reference_mode_enabled` 日志现在会输出：
    - `reference_strategy`
    - `reference_count`
    - `shared_reference_count`
    - `subtitle_reference_count`
    - `subtitle_reference_min_sec`
  - 因此你直接看后台日志就能知道 OmniVoice 这批句子到底用了多少 shared ref、多少 subtitle ref。
- 回归测试：
  - [tests/test_dub_pipeline_asr_layout.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dub_pipeline_asr_layout.py) 新增两条 selector 用例：
    - `omnivoice` 会把 `<1.2s` 的逐句 reference 回退到 shared ref；
    - `index-tts` 会继续保留原有逐句 reference，不受新策略影响。
- 验证证据：
  - `uv run python -m py_compile tools/dub_pipeline.py tests/test_dub_pipeline_asr_layout.py`：通过
  - `uv run python -m unittest tests.test_dub_pipeline_asr_layout`：`Ran 13 tests ... OK`

## Spec-5（2026-04-28 OmniVoice 链路强制短句合并）
- 现状 1：`source short merge` 与 `translated short merge` 都还是“用户请求态”开关，不会因为 `tts_backend=omnivoice` 自动强制。
  - 依据 1： [tools/dub_pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_pipeline.py) 的 `rebalance_source_subtitles()` 只有在 `source_short_merge_enabled=True` 时才调用 `merge_short_source_subtitles(...)`。
  - 依据 2： [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 的 `maybe_merge_translated_input_subtitles()` 只有在 `translated_short_merge_enabled=True` 时才执行。
- 现状 2：这两组请求态开关会被持久化进任务、命令和 manifest，当前语义是“用户勾没勾”，不是“运行时最终是否生效”。
  - 依据 1： [src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py) 的 `_normalize_auto_dubbing_request()` 会分别保存 `source_short_merge_*` 与 `translated_short_merge_*`。
  - 依据 2： [src/subtitle_maker/manifests/schema.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/manifests/schema.py) 的 `BatchReplayOptions` 当前只有请求态字段，没有 `effective_*` 字段。
  - 依据 3： [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 构造 `BatchReplayOptions` 时，直接把 `source_short_merge_enabled` / `translated_short_merge_enabled` 原值写入 batch manifest。
- 现状 3：`translated short merge` 只允许在长视频初始编排执行一次；review redub / resume 不会重复并句，这个边界不能破。
  - 依据： [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 的主循环只在 `args.input_srt_kind == "translated" and resume_batch_dir is None` 时执行 `maybe_merge_translated_input_subtitles(...)`。
- 现状 4：前端当前会根据字幕模式隐藏/显示两套 merge 开关，但不会因为 `tts_backend=omnivoice` 自动把“请求态 false”改成 true。
  - 依据： [src/subtitle_maker/static/js/dubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/dubbingPanel.js) 的 `syncShortMergeControls()` 只按 `effectiveSubtitleMode` 切换 source/translated 两套控件，不读 `tts_backend`。

## Spec-5 方案建议
- 推荐实现语义：
  - 保留现有 `source_short_merge_enabled` / `translated_short_merge_enabled` 作为“用户请求态”；
  - 运行时新增“OmniVoice 策略态”：
    - `effective_source_short_merge_enabled = requested_source_short_merge_enabled or (tts_backend == "omnivoice")`
    - `effective_translated_short_merge_enabled = requested_translated_short_merge_enabled or (tts_backend == "omnivoice")`
  - 这样用户配置仍然真实可回显，但 OmniVoice 链路会被强制套上短句合并策略。
- 推荐落点：
  - `source/ASR` 链路：在 [tools/dub_pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_pipeline.py) 的 `main()` / `load_or_transcribe_subtitles()` 调用 `rebalance_source_subtitles()` 前计算 `effective_source_short_merge_enabled`，只把生效值传入运行时，不改 manifest 原字段。
  - `translated 上传字幕` 链路：在 [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 的 segment 初始编排里，计算 `effective_translated_short_merge_enabled`，但仍保持“只在初始任务执行一次，不在 resume/review 重并句”。
- 推荐日志：
  - source 链路的 `source_layout_rebalanced` 日志里增加：
    - `short_merge_requested`
    - `short_merge_effective`
    - `short_merge_effective_reason`
  - translated 链路的 segment 日志增加：
    - `requested=...`
    - `effective=...`
    - `reason=user|omnivoice_policy|resume_skipped`
  - 这样用户看到“没勾开关但日志显示合并生效”时，可以明确知道是 OmniVoice 策略强制。

## Spec-5 风险与边界
- 风险 1：如果直接把 manifest/task 里的 `source_short_merge_enabled`、`translated_short_merge_enabled` 覆盖成 `true`，会污染用户真实请求态，导致 Restore/Load Batch 时 UI 看起来像用户自己打开了开关。
  - 决策：保留 manifest 原字段为请求态；本轮不改 schema，不新增 `effective_*` 永久字段，先通过运行时日志体现策略生效。
- 风险 2：如果把 `translated short merge` 也强制到 review redub / resume，句边界会再次漂移，破坏已存在的 segment 定位。
  - 决策：OmniVoice 强制 translated merge 只作用于长视频初始编排；`resume_batch_dir is not None` 时仍然跳过。
- 风险 3：如果前端因为 `tts_backend=omnivoice` 直接把 checkbox 视觉上改成勾选，会把“请求态”和“策略态”混在一起，用户下次切回 `index-tts` 时会误以为自己永久打开了开关。
  - 决策：前端本轮不改 checkbox 真值，只补提示文案或任务日志；真正的强制只放在运行时。
- 风险 4：如果 source/translated 两边都无差别强制合并，但不保留当前算法边界，容易把用户担心的“停顿被吃掉”重新引入。
  - 决策：只强制“现有算法是否执行”，不改现有边界条件：
    - 目标阈值仍是 `6~20s`
    - 容差仍是 `round(target / 3)`
    - `>1.5s` 静默不跨
    - 单条已过长不并
    - translated 不跨 segment

## Spec-5 验证口径
- [tests/test_dub_pipeline_asr_layout.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dub_pipeline_asr_layout.py)
  - 新增 `tts_backend=omnivoice` 时，即使 `source_short_merge_enabled=False`，运行时仍会触发 source merge 的用例。
- [tests/test_dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dub_long_video.py)
  - 新增 `tts_backend=omnivoice` + `translated_short_merge_enabled=False` 时，初始编排仍会执行 translated merge；
  - 同时断言 `resume_batch_dir` 场景仍然 `skipped_resume`，避免重复并句。
- 最小验证：
  - `uv run python -m py_compile tools/dub_pipeline.py tools/dub_long_video.py tests/test_dub_pipeline_asr_layout.py tests/test_dub_long_video.py`
  - `uv run python -m unittest tests.test_dub_pipeline_asr_layout tests.test_dub_long_video`

## Spec-5 Review（2026-04-28）
- 已实现：
  - [tools/dub_pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_pipeline.py) 新增 `resolve_source_short_merge_policy()` 并在 `validate_args()`、`main()`、`load_or_transcribe_subtitles()` 之间透传 `requested/effective/reason`，确保 `tts_backend=omnivoice` 时 source short merge 在运行时强制生效，同时不污染 manifest 的请求态字段。
  - [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 新增 `resolve_translated_short_merge_policy()`，确保 translated 上传字幕在 `omnivoice` 初始编排阶段强制并句，而 `resume_batch_dir` 仍明确跳过并输出 `reason=resume_skipped`。
  - translated merge 的 segment 日志已扩展为 `requested/effective/reason` 三元信息，source merge 的 logger 也会记录 `short_merge_requested / short_merge_effective / short_merge_effective_reason`。
- 回归测试：
  - [tests/test_dub_pipeline_asr_layout.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dub_pipeline_asr_layout.py) 已新增 OmniVoice source merge 策略态用例，并补齐 `load_or_transcribe_subtitles()` 新签名参数。
  - [tests/test_dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dub_long_video.py) 已新增 OmniVoice translated merge 强制生效用例，以及 `resume_skipped` 策略函数用例；原 translated merge 日志断言已同步到新格式。
- 验证证据：
  - `uv run python -m py_compile tools/dub_pipeline.py tools/dub_long_video.py tests/test_dub_pipeline_asr_layout.py tests/test_dub_long_video.py`：通过
  - `uv run python -m unittest tests.test_dub_pipeline_asr_layout tests.test_dub_long_video`：`Ran 20 tests ... OK`

## Spec-6（2026-04-28 OmniVoice merge 后仍过短句子的前置拦截）
- [x] Spec-1：现状分析（带代码出处）
- [x] Spec-2：确认前置拦截语义、记录字段与精确改动范围
- [x] Spec-3：确认 grouped/逐句两条路径的风险与验证口径

### Spec-1 现状分析
- 现状 1：`OmniVoice` 的 `<1.2s` 安全下限目前只在 backend 合成入口校验，不在编排层预判。
  - 依据： [src/subtitle_maker/backends/omni_voice.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/backends/omni_voice.py) 的 `_validate_request()` 会在 `0 < target_duration_sec < 1.2s` 时直接抛出 `E-TTS-001 omnivoice target duration below safe floor`；`synthesize()` 一开始就执行这条校验。
- 现状 2：即使 source/translated short merge 已被 `omnivoice` 运行时强制开启，合并逻辑也只负责“是否并句”，不会在合并后对剩余短句做二次筛查。
  - 依据 1： [tools/dub_pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_pipeline.py) 的 `resolve_source_short_merge_policy()` 只决定 `effective_source_short_merge_enabled`。
  - 依据 2： [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 的 `resolve_translated_short_merge_policy()` 只决定 `effective_translated_short_merge_enabled`。
- 现状 3：逐句主循环里，`effective_target_duration` 仍会原样传给 `synthesize_text_once()`；如果这时仍 `<1.2s`，失败会在 TTS 阶段才暴露。
  - 依据： [src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py) 的 `synthesize_segments()` 在逐句循环中直接把 `effective_target_duration` 传给 `synthesize_text_once(...)`。
- 现状 4：当前这类失败在 manifest / manual review 里会被记录成通用 `tts_failed`，还没有一个专门的“OmniVoice 安全下限命中”原因码。
  - 依据 1： [src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py) 的异常分支会把 `failure_reason_code` 设成 `tts_failed`、`failure_error_code` 设成 `E-TTS-001`。
  - 依据 2： 同文件后续 `record["status"] != "done"` 时追加的 `manual_review` 也只会继承这个通用 reason code。
- 现状 5：即便是失败路径，当前 pipeline 也已经有稳定的缺失音频占位与最终混音保护，所以如果要前置拦截，不需要改混音层协议。
  - 依据： [src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py) 在逐句失败时会生成 `seg_xxxx_missing.wav` 占位；[src/subtitle_maker/domains/media/compose.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/media/compose.py) 的 `compose_vocals_master()` 已显式兼容 `*_missing.wav`。
- 结论：下一步最值钱的不是再改 merge 算法，而是把“merge 后仍低于 OmniVoice 安全下限的句子”在 `pipeline` 里前置标记出来，给出专用 reason code / 日志，并直接走现有 missing/manual review 协议，避免把明显不适合的句子送到 backend 再失败一次。

### Spec-2 功能点与精确改动范围
- 推荐实现语义：
  - 只在 `tts_backend=omnivoice` 的运行时路径启用“过短目标时长前置拦截”。
  - 判定标准先保持和 backend 一致：`0 < effective_target_duration_sec < 1.2s`。
  - 命中后不再调用 `synthesize_text_once()`，而是直接进入现有 missing/manual review 协议。
  - 不切换底座，不尝试自动 fallback，不改现有 short merge 算法。
- 推荐新增的运行时表达：
  - 新增一个专用判定 helper，例如 `is_omnivoice_target_duration_unsafe(...)`，只负责回答“当前句/组是否低于 OmniVoice 安全下限”。
  - 新增一个统一 reason code：
    - `reason_code = "omnivoice_target_duration_below_safe_floor"`
    - `error_code = "E-TTS-001"`
    - `error_stage = "tts_precheck"`
  - `reason_detail` 明确带上：
    - `effective_target_duration_sec`
    - `safe_floor_sec=1.2`
    - `tts_backend=omnivoice`
- 逐句路径改动范围：
  - 落点： [src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py) 的 `synthesize_segments()`。
  - 插入位置：在每句已经算出 `effective_target_duration`、但还没进入 `for attempt_no in range(...)` 重试循环之前。
  - 命中后的动作：
    - 直接生成 `seg_xxxx_missing.wav`
    - 直接构造 `record`
    - 直接追加 `manual_review`
    - `attempt_history` 只记一条 `action="omnivoice_duration_precheck"`，不要伪装成真实 TTS 失败
    - `audio_leveling_*` 字段保持 missing 协议的现状，不做 leveling
  - 这样可以跳过：
    - `synthesize_text_once()`
    - `invalid_audio` 检测
    - `fit_timing/atempo/retranslate`
    - 也不会再把它记成通用 `tts_failed`
- grouped 路径改动范围：
  - 落点： [src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py) 的 grouped 合成主循环（`build_synthesis_groups()` 之后、真正调用 `synthesize_text_once()` 之前）。
  - 判定对象不是单句 `target_duration_sec`，而是组级 `group_effective_target_duration`。
  - 命中后的动作：
    - 不跑组级 TTS
    - 直接给组内每一条 `seg_xxxx` 写 `*_missing.wav`
    - `attempt_history` 只记 `action="group_omnivoice_duration_precheck"`
    - `manual_review` 统一使用新的专用 reason code，而不是通用 `tts_failed`
  - 这样 grouped/legacy 路径与逐句路径的失败语义能对齐。
- 日志范围：
  - 逐句路径新增一个明确事件，例如：
    - `segment_tts_precheck_rejected`
  - grouped 路径新增一个明确事件，例如：
    - `group_tts_precheck_rejected`
  - 两者日志数据都至少带：
    - `segment_id` 或 `group_id`
    - `effective_target_duration_sec`
    - `safe_floor_sec`
    - `requested_target_duration_sec`
    - `borrowed_gap_sec`
- 明确不改的范围：
  - 不改 [src/subtitle_maker/backends/omni_voice.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/backends/omni_voice.py) 现有 backend guard；它继续保留，作为最后一道保护。
  - 不改 [tools/dub_pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_pipeline.py) / [tools/dub_long_video.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tools/dub_long_video.py) 的 short merge 规则、阈值和 UI 语义。
  - 不改 `index-tts` 路径，不把这条 precheck 推广到其他底座。

### Spec-3 风险、决策与验证口径
- 风险 1：如果 precheck 用的是原始 `target_duration_sec`，而不是已经借后续静默后的 `effective_target_duration_sec`，会误杀本来可以靠 borrowed gap 安全落地的句子。
  - 依据： [src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py) 的逐句/组级路径都会先调用 `compute_effective_target_duration(...)`，并把 `effective_target_duration_sec`、`borrowed_gap_sec` 记入 record。
  - 决策：precheck 统一只看 `effective_target_duration_sec`，并把 `requested_target_duration_sec` 作为日志附加信息，而不是判定主条件。
- 风险 2：如果把 precheck 直接套到 grouped 的非语音组，会破坏当前“非语音直接生成静音片段”的特例路径。
  - 依据： grouped 路径里当前先判 `non_speech_group`，命中时直接写 `group_id_silent.wav`，不会进入真实 TTS。
  - 决策：precheck 只对“有可说内容”的句/组生效；`non_speech_group` 和逐句 `segment_type=non_speech` 保持现状，不走这条拦截。
- 风险 3：如果 grouped 路径只给 anchor 行打 `manual_review`，不把组内每条都写入专用 reason code，会导致 review 列表、最终 merge 统计和用户感知不一致。
  - 依据：当前 grouped 失败时， [src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py) 会把组内每个 `seg_xxxx` 都写进 `records_by_index` 和 `manual_review`。
  - 决策：前置拦截沿用现有 grouped 失败语义，组内每一条都生成 `*_missing.wav`、每一条都追加 `manual_review`。
- 风险 4：如果 precheck 放在“复用已有音频”之前，会把普通 resume / 非 redub 行重新打成 missing，破坏你已经修好的恢复语义。
  - 依据：逐句路径当前先走 `resolve_existing_audio_path()` 和 `resume_reuse_allowed`，满足条件就直接复用历史音频并 `continue`。
  - 决策：precheck 必须放在“已有音频复用”之后、真实 TTS 重试循环之前；也就是说普通 resume 不重判，只有这次真正要重配的句子才会命中 precheck。
- 风险 5：如果把这条 precheck 泛化到“主底座不是 OmniVoice、但 fallback=omnivoice”的场景，会把 `index-tts` 主链路也污染进来，违背你要求的隔离边界。
  - 依据：当前逐句路径支持 `fallback_tts_backend=omnivoice`，但用户已经明确不建议中途切底座。
  - 决策：本轮 precheck 只看主 backend：`tts_backend == "omnivoice"` 才启用；不根据 fallback backend 触发。
- 风险 6：如果删掉 backend 层已有 guard，只靠 pipeline precheck，会让未来别的入口直接调用 `OmniVoiceBackend` 时失去最后一道保护。
  - 依据： [src/subtitle_maker/backends/omni_voice.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/backends/omni_voice.py) 的 `_validate_request()` 当前已经稳定工作，并有独立回归。
  - 决策：保留 backend guard；pipeline precheck 只是“更早、更清楚地失败”，不是替换 backend 校验。

### Spec-6 验证口径
- 单测主集：
  - [tests/test_dubbing_runtime.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_runtime.py)
    - 新增逐句路径用例：`tts_backend=omnivoice` 且 `effective_target_duration_sec < 1.2s` 时，直接进入 `manual_review`，`synthesize_text_once()` 不会被调用，`reason_code` 为 `omnivoice_target_duration_below_safe_floor`。
    - 新增 grouped 路径用例：`group_effective_target_duration_sec < 1.2s` 时，组内每条都写 `*_missing.wav`，并且 `manual_review` 对每条都记录专用 reason code。
    - 新增非语音组用例：grouped `non_speech_group` 仍走静音片段逻辑，不应被 precheck 误杀。
    - 现有 `resume reuse` 用例继续通过，证明 precheck 没有插错顺序。
    - 现有 `omnivoice_keep_natural_no_atempo` / `skips_fit_when_within_threshold` 用例继续通过，证明这次没有误伤 OmniVoice 其它时长对齐策略。
- backend 保护回归：
  - [tests/test_dubbing_runtime.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_runtime.py) 里现有 `test_omnivoice_backend_rejects_too_short_target_duration_before_request()` 继续通过，证明 backend guard 仍保留。
- 最小验证命令：
  - `uv run python -m py_compile src/subtitle_maker/domains/dubbing/pipeline.py tests/test_dubbing_runtime.py`
  - `uv run python -m unittest tests.test_dubbing_runtime`
- 非目标：
  - 这轮不要求真实跑 OmniVoice 服务级 smoke；重点是把“是否前置拦截、是否保留 resume/非语音/现有对齐行为”用本地回归锁住。

## Spec-6 Review（2026-04-28）
- 已实现：
  - [src/subtitle_maker/domains/dubbing/pipeline.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/dubbing/pipeline.py) 新增 OmniVoice 前置拦截 helper：
    - `_is_omnivoice_target_duration_unsafe()`
    - `_build_omnivoice_duration_precheck_reason_detail()`
    - `_write_missing_audio_placeholder()`
  - grouped 路径在真正调用 `synthesize_text_once()` 之前，若 `group_effective_target_duration_sec < 1.2s`，会直接打 `group_tts_precheck_rejected`，为组内每条写 `*_missing.wav`，并记录 `reason_code=omnivoice_target_duration_below_safe_floor`。
  - 逐句路径在“已有音频复用”之后、真实 TTS 重试循环之前，若 `effective_target_duration_sec < 1.2s`，会直接打 `segment_tts_precheck_rejected`，写 `seg_xxxx_missing.wav`，并记录同样的专用 reason code / `tts_precheck` stage。
  - backend 层 [src/subtitle_maker/backends/omni_voice.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/backends/omni_voice.py) 的 `_validate_request()` 未删除，仍作为最后一道保护保留。
- 回归测试：
  - [tests/test_dubbing_runtime.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_runtime.py) 新增：
    - 逐句 OmniVoice precheck 不触发真实 TTS 的用例；
    - grouped OmniVoice precheck 组内多条同时标记 manual review 的用例；
    - OmniVoice 非语音 grouped 仍走静音片段、不会被 precheck 误杀的用例。
  - 同时把原有两条 OmniVoice 时长对齐回归的目标时长调整到 `1.25s` 以上，确保它们继续验证“跳过 fit / 避免 atempo”本身，而不是被新的 precheck 提前拦截。
- 验证证据：
  - `uv run python -m py_compile src/subtitle_maker/domains/dubbing/pipeline.py tests/test_dubbing_runtime.py`：通过
  - `uv run python -m unittest tests.test_dubbing_runtime`：`Ran 30 tests ... OK`

## TODO（2026-04-28 OmniVoice 实测结果文档同步）
- [x] 汇总最新前端实测任务的 segment 日志、manifest 和 OmniVoice 服务日志
- [x] 新增 `docs/auto-dubbing-v2-omnivoice-status.md`，沉淀当前已落地策略与最新验证结果
- [x] 记录当前剩余待观察项：音量上限、最终视频封装层、听感持续回归

## Review（2026-04-28 OmniVoice 实测结果文档同步）
- 文档新增：
  - [docs/auto-dubbing-v2-omnivoice-status.md](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/docs/auto-dubbing-v2-omnivoice-status.md)
- 本次文档只记录已验证事实，不再写“预期上会更好”这类无证据表述。
- 文档里的关键证据来自：
  - [segment_0001.jsonl](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/outputs/dub_jobs/web_20260428_015019/longdub_20260428_095022/segment_jobs/segment_0001/logs/segment_0001.jsonl)
  - [segment manifest](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/outputs/dub_jobs/web_20260428_015019/longdub_20260428_095022/segment_jobs/segment_0001/manifest.json)
  - [batch_manifest.json](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/outputs/dub_jobs/web_20260428_015019/longdub_20260428_095022/batch_manifest.json)
  - [outputs/omnivoice_api.log](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/outputs/omnivoice_api.log)
- 当前结论已同步进文档：
  - 强制短句合并、reference 策略收紧、`<1.2s` 前置拦截、段级音量归一已经共同进入生产路径；
  - 最新实测任务 `done=3 failed=0 manual_review=0`，用户听感反馈“效果好多了”与日志结果一致；
  - 下一阶段应优先盯音量上限是否偏紧，以及最终视频封装层是否完整落盘。
- [x] 修正 `voxcpm-omnivoice` 链路中的 `ref_text` 语义：VoxCPM 使用原参考音对应文本，OmniVoice 使用 anchor 音频对应文本，避免把原参考 prompt 错喂给最终时长控制。

    - 第九阶段计划：直接删除/重写残留的 OmniVoice/VoxCPM 旧测试，随后收掉 `domains/dubbing/pipeline.py`、`backends/omni_voice.py`、`tools/repair_bad_segments.py`、`tools/dub_long_video.py` 中仍然活着的 OmniVoice 分支，最终让 Auto Dubbing 运行时只剩 `index-tts`。

    - 第九阶段已完成 index-tts 单底座收口：删除 `src/subtitle_maker/backends/omni_voice.py` 与导出，`domains/dubbing/pipeline.py` 的真实运行时已强制只走 `IndexTtsBackend`，工具层/前端中的 OmniVoice 偏好逻辑与文案残留已同步清掉；保留少量兼容形参仅用于旧调用不炸。
    - 第九阶段验证：`node --check src/subtitle_maker/static/js/dubbingPanel.js`、`uv run python -m py_compile src/subtitle_maker/backends/__init__.py src/subtitle_maker/domains/dubbing/pipeline.py tools/dub_pipeline.py tools/dub_long_video.py tools/repair_bad_segments.py`、`uv run python -m unittest -v tests.test_dub_pipeline_asr_layout tests.test_dub_long_video tests.test_dubbing_runtime tests.test_dubbing_cli_api` 全部通过。

## Review（2026-05-08 OmniVoice 旧目录收口）
- 本次修复把 `src/subtitle_maker/omnivoice_dub_api.py` 里旧输出根目录的主动创建去掉了，兼容逻辑只保留读取，不再落空目录。
- 旧的 `outputs/omnivoice_dub_jobs/` 已清理，新的 5 号链路继续只写 `outputs/dub_jobs/`。
- 验证结果：`uv run python -m py_compile src/subtitle_maker/omnivoice_dub_api.py` 通过。

## TODO（2026-05-08 SRT 导入优化）
- [x] 为 `upload_srt` 单独增加导入时优化规则，只合并同 speaker 的相邻短句，不改 Deepgram JSON 导入逻辑。
- [x] 补充 SRT 导入回归测试，验证短句合并和不同 speaker 保持分离。
- [x] 验证命令：`uv run python -m unittest tests.test_subtitle_speakers tests.test_web_routes_legacy`

## Review（2026-05-08 SRT 导入优化）
- SRT 上传现在会先做 `parse_srt()` + `normalize_subtitles_with_speakers()`，再走独立的 `optimize_srt_import_subtitles()`。
- Deepgram JSON 的导入和合并逻辑未改动，仍保持原来的 `deepgram_json_to_subtitles()` 路径。
- 验证结果：
  - `uv run python -m unittest tests.test_subtitle_speakers tests.test_web_routes_legacy` 通过
  - `uv run python -m py_compile src/subtitle_maker/domains/subtitles/srt_import.py src/subtitle_maker/app/routes/subtitles.py src/subtitle_maker/domains/subtitles/__init__.py` 通过
  - 规则已从保守的局部合并改成按连续 speaker block 的 short-merge 重分句，合并力度明显更大。
  - 最新修正：导入顺序调整为“先按 speaker 合并，再按标点切句”，保证整句尽量落在同一行。
  - 最新修正 2：主规则已切换成“speaker + 停顿分块 + 句末标点收敛”，碎片只做补救，不再把 `No.` 之类完整短句误判成碎片。

## TODO（2026-05-08 单参考音自动收敛）
- [x] 让 Auto Dubbing 在检测到仅 1 份 speaker 参考音时自动走 single speaker。
- [x] 让 SRT 导入的 single speaker 分支只做句子优先的简化处理，不再强依赖 speaker 边界。
- [x] 调整测试合同：1 份参考音应通过并返回 `dubbing_mode=single`，2 份参考音保持 `multi`。

## Review（2026-05-08 单参考音自动收敛）
- 现在 Auto Dubbing 会把单个 speaker 参考音自动收敛成 single speaker，不再把这种场景当成“部分上传错误”。
- SRT 导入的 single speaker 分支只保留更简单的句子级收敛，避免把多人规则硬套到单人字幕上。
- 验证结果：
  - `uv run python -m py_compile src/subtitle_maker/domains/subtitles/srt_import.py src/subtitle_maker/dubbing_cli_api.py tests/test_subtitle_speakers.py tests/test_dubbing_cli_api.py` 通过
  - `uv run python -m unittest tests.test_subtitle_speakers tests.test_dubbing_cli_api` 通过

## TODO（2026-05-12 OmniVoice 缺失参考音按性别目录选取）
- [x] 收紧 5 号面板缺失 speaker 的预存参考音选择逻辑
  - 先按源音频推断缺失 speaker 性别
  - 再只从 `ref-voices/<lang>/male/` 或 `ref-voices/<lang>/female/` 目录中随机选择
  - 保留已上传参考音同名排除，不影响 4 号链路
- [x] 补充/调整 OmniVoice 单测
  - 验证男声只命中 `male/`
  - 验证女声只命中 `female/`
  - 验证对应性别目录为空时不会误选另一性别目录

## Review（2026-05-12 OmniVoice 缺失参考音按性别目录选取）
- `src/subtitle_maker/omnivoice_dub_api.py` 已改为：
  - 先读取缺失 speaker 的 `speaker_gender_hints`
  - 有性别提示时只从 `ref-voices/<lang>/male/` 或 `ref-voices/<lang>/female/` 中选
  - 对应性别目录为空时直接报错，不再串到另一性别目录
  - 仅在没有性别提示时，才回退到 `ref-voices/<lang>/` 通用候选池
- `tests/test_dubbing_cli_api.py` 新增了“对应性别目录为空时报错”的回归测试，并保留原有男/女目录命中测试。
- 验证结果：
  - `uv run python -m py_compile src/subtitle_maker/omnivoice_dub_api.py tests/test_dubbing_cli_api.py`：通过
  - `uv run python -m unittest tests.test_dubbing_cli_api -k preset_ref_voices`：`Ran 5 tests ... OK`
  - `uv run python -m unittest tests.test_dubbing_cli_api -k omnivoice`：`Ran 17 tests ... OK`

## TODO（2026-05-12 OmniVoice 译文 speaker 回填按时间对齐）
- [x] 修复 5 号面板中 `speaker_id` 缺失时的回填策略
  - 从“按索引回填 fallback_rows”改为“按时间重叠优先回填”
  - 无重叠时回退到最近时间片的 speaker，再兜底索引/默认值
  - 避免 `selected_subtitles_with_speakers.srt` 在 speaker 切换后大量错贴 `Speaker 1`
- [x] 新增回归测试
  - 行数变化场景下应按时间窗命中正确 speaker
  - 无时间重叠场景下应命中最近 speaker，而非默认 `Speaker 1`

## Review（2026-05-12 OmniVoice 译文 speaker 回填按时间对齐）
- 已修改：
  - [src/subtitle_maker/omnivoice_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/omnivoice_dub_api.py)
  - [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py)
- 验证结果：
  - `uv run python -m py_compile src/subtitle_maker/omnivoice_dub_api.py tests/test_dubbing_cli_api.py`：通过
  - `uv run python -m unittest tests.test_dubbing_cli_api -k ensure_speaker_ids`：`Ran 2 tests ... OK`
  - `uv run python -m unittest tests.test_dubbing_cli_api -k omnivoice`：`Ran 18 tests ... OK`

## TODO（2026-05-12 OmniVoice 译文文本清洗与碎片回并）
- [x] 在 5 号面板 selected 字幕后处理里增加中英混排清洗
  - 修正粘连英文 token（如 `ClaudeCode` -> `Claude Code`）
  - 修正中英数字贴连（如 `AI时代` -> `AI 时代`）
- [x] 在 5 号面板 selected 后处理末端增加同 speaker 短残句回并
  - 仅对短时长/连接词断裂/半句碎片触发
  - 限制 gap 与时长上限，避免过度合并
- [x] 补充单测并回归
  - 文本规范化单测
  - 短残句回并单测

## Review（2026-05-12 OmniVoice 译文文本清洗与碎片回并）
- 已修改：
  - [src/subtitle_maker/omnivoice_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/omnivoice_dub_api.py)
  - [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py)
- 验证结果：
  - `uv run python -m py_compile src/subtitle_maker/omnivoice_dub_api.py tests/test_dubbing_cli_api.py`：通过
  - `uv run python -m unittest tests.test_dubbing_cli_api -k selected_text_normalizer`：`Ran 1 test ... OK`
  - `uv run python -m unittest tests.test_dubbing_cli_api -k merge_selected_fragment_rows`：`Ran 1 test ... OK`
  - `uv run python -m unittest tests.test_dubbing_cli_api -k omnivoice`：`Ran 20 tests ... OK`
- 对任务 `omnivoice_20260512_012742` 的离线复算对比（同一输入）：
  - 行数：`425 -> 398`
  - 驼峰/连写英文问题：`46 -> 37`
  - 疑似半句碎片：`48 -> 21`
  - speaker 时间重叠错配：`70 -> 59`（明显下降，但仍未归零）

## TODO（2026-05-12 OmniVoice speaker-first 强制时间对齐）
- [x] 在 5 号面板 selected 字幕关键入口开启 `force_align_by_time`
  - `_optimize_omnivoice_selected_rows` 内部补齐阶段
  - `prepare-subtitles-from-project` 的 `selected_subtitles` 与 preview 路径
  - `start-from-project` 复用 prepared selected 路径
  - `_run_omnivoice_job` 合成前 `selected_subtitles` 路径
- [x] 保持 4 号链路不变，仅收紧 5 号 OmniVoice
- [x] 回归测试通过
  - `uv run python -m unittest tests.test_dubbing_cli_api -k omnivoice`

## Review（2026-05-12 OmniVoice speaker-first 强制时间对齐）
- 已修改：
  - [src/subtitle_maker/omnivoice_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/omnivoice_dub_api.py)
  - [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py)
- 验证结果：
  - `uv run python -m py_compile src/subtitle_maker/omnivoice_dub_api.py tests/test_dubbing_cli_api.py`：通过
  - `uv run python -m unittest tests.test_dubbing_cli_api -k omnivoice`：`Ran 21 tests ... OK`
- 针对 `omnivoice_20260512_012742` 的离线复算（同输入、按新逻辑重算）：
  - speaker 时间重叠错配：`70 -> 0`

## Review（2026-05-12 最新产物对照验证）
- 对照文件：
  - source：[This is AGI： Sequoia AI Ascent 2026 Keynote.srt](/Users/tim/Downloads/This%20is%20AGI%EF%BC%9A%20Sequoia%20AI%20Ascent%202026%20Keynote.srt)
  - 最新带 speaker 译文：[selected_subtitles_with_speakers.srt](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/outputs/dub_jobs/omnivoice_20260512_034002/selected_subtitles_with_speakers.srt)
  - 对照基线：`outputs/dub_jobs/omnivoice_20260512_012742/selected_subtitles_with_speakers.srt`
- 关键指标（基线 -> 最新）：
  - speaker 错配：`70 -> 0`
  - 疑似半句碎片：`48 -> 9`
  - 超短碎片（<=0.4s）：`24 -> 0`
  - 驼峰/粘连英文：`46 -> 36`
  - 含英文行：`67 -> 62`
  - 总行数：`425 -> 369`
- 结论：
  - speaker-first 对齐已恢复正确（时间窗比对为 0 错配）
  - 译文碎片化明显改善
  - 仍有少量专有名词英文保留，属于可接受的后续文本优化项

## TODO（2026-05-12 Auto Dubbing 4号面板 401 报错定位）
- [x] 定位 4 号面板失败根因
  - 从 `outputs/dub_jobs/web_20260512_071958/web_cli_stdout.log` 确认失败发生在 `translate:translation_started` 之后
  - 确认外部翻译接口 `https://api.freemodel.dev/v1/chat/completions` 先返回 503，再返回 401
  - 排除“未上传参考音频”根因（失败时机早于 TTS/ref 阶段）
- [x] 最小修复错误文案，避免误导
  - 当 stdout 含 `401` + `chat/completions` / `Internal server error` 时
  - 将最终失败详情统一映射为“翻译 provider 鉴权失败（HTTP 401）”
- [x] 增加回归测试
  - `tests/test_dubbing_cli_api.py` 新增 401 文案映射用例

## Review（2026-05-12 Auto Dubbing 4号面板 401 报错定位）
- 已修改：
  - [src/subtitle_maker/dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/dubbing_cli_api.py)
  - [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py)
- 验证结果：
  - `uv run python -m py_compile src/subtitle_maker/dubbing_cli_api.py tests/test_dubbing_cli_api.py`：通过
  - `uv run python -m unittest tests.test_dubbing_cli_api -k DubbingCliApiFailureParsingTests`：`Ran 2 tests ... OK`
- 根因结论：
  - 4 号面板这次失败不是参考音频问题，是翻译 provider 返回 `401 Unauthorized`。

## 93. 2026-05-18 评估并实现 6 号面板 VoxCPM 自然朗读链路
- [x] 现状
  - [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html) 当前侧栏只有 5 个主面板入口：上传、字幕、切片、4 号 `Auto Dubbing`、5 号 `Auto Dub Omnivoice`
  - [src/subtitle_maker/static/js/dubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/dubbingPanel.js) 的 4 号面板明确固定走 `index-tts`，`getCurrentTtsBackend()` 直接返回 `index-tts`
  - [src/subtitle_maker/static/js/omnivoiceDubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/omnivoiceDubbingPanel.js) 的 5 号面板是独立 OmniVoice 链路，只共享当前项目上下文与翻译配置，不复用 4 号面板 backend 状态
  - [src/subtitle_maker/backends/base.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/backends/base.py) 的 `TtsSynthesisRequest` 统一合同包含 `ref_audio_path / ref_text / language / target_duration_sec`
  - [/Users/tim/Documents/vibe-coding/MVP/VoxCPM/app.py](/Users/tim/Documents/vibe-coding/MVP/VoxCPM/app.py) 当前 API 只暴露 `text / prompt_audio / prompt_text / cfg_value / inference_timesteps / normalize / denoise`，未暴露目标时长控制
  - [/Users/tim/Documents/vibe-coding/MVP/VoxCPM/src/voxcpm/model/voxcpm.py](/Users/tim/Documents/vibe-coding/MVP/VoxCPM/src/voxcpm/model/voxcpm.py) 模型层只有“异常偏长检测/重试”，没有 `duration/speed/target_duration` 生成参数
  - [/Users/tim/Documents/vibe-coding/MVP/VoxCPM/app.py](/Users/tim/Documents/vibe-coding/MVP/VoxCPM/app.py) 已内建 `粤语 / 廣東話 / cantonese / yue / zh-yue` 语言别名归一化
  - [/Users/tim/Documents/vibe-coding/MVP/VoxCPM/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/VoxCPM/templates/index.html) 与 [/Users/tim/Documents/vibe-coding/MVP/VoxCPM/使用说明.md](/Users/tim/Documents/vibe-coding/MVP/VoxCPM/使用说明.md) 也已把粤语作为支持语种暴露给用户
- [x] 功能点
  - 输出 6 号面板轻量 Spec，明确是否值得新增独立 VoxCPM 配音链路
  - 若值得新增，定义它与 4 号 `index-tts`、5 号 `OmniVoice` 的职责边界
  - 给出最小实现路径：前端入口、独立后端 API、时长策略、参考音策略、恢复策略
 - [x] 风险与决策
  - 决策 1：6 号面板改成自然朗读型 VoxCPM，不再强制 fit 到原字幕时间窗
  - 决策 2：6 号面板允许“仅字幕 + 参考音频”启动，不再强制上传视频
  - 决策 3：最终固定额外输出黑底字幕视频，字幕居中，字号 `120`
- [x] 实施
- [x] 实现 VoxCPM 独立后端 API 与任务产物合同
- [x] 接入 6 号面板模板、前端控制器与 `static/app.js` 初始化
- [x] 补批次级 resume
  - [x] 后端落盘 `selected_subtitles.srt / source_audio / ref 配置 / segment manifest`
  - [x] `load-batch` 基于磁盘真实推断 `resumable/resume_stage`
  - [x] `/voxcpm/auto/resume/{task_id}` 复用已完成 segment，只续跑缺失条目
  - [x] 6 号面板 Restore 区补 resume 按钮与交互
- [x] 补最小回归测试与静态校验
- [x] 切换为纯字幕自然朗读模式与黑底字幕视频输出
- [x] 验证
  - `./.venv/bin/python -m py_compile src/subtitle_maker/voxcpm_dub_api.py src/subtitle_maker/app/main.py tests/test_dubbing_cli_api.py` 通过
  - `node --check src/subtitle_maker/static/js/voxcpmDubbingPanel.js` 通过
  - `node --check src/subtitle_maker/static/app.js` 通过
  - `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_voxcpm_backend_status_proxies_health_payload tests.test_dubbing_cli_api.DubbingCliApiTests.test_list_voxcpm_batches_reads_manifest tests.test_dubbing_cli_api.DubbingCliApiTests.test_load_voxcpm_batch_restores_task_view` 通过（3 tests, OK）
  - `./.venv/bin/python -m py_compile src/subtitle_maker/voxcpm_dub_api.py tests/test_dubbing_cli_api.py` 通过
  - `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_voxcpm_backend_status_proxies_health_payload tests.test_dubbing_cli_api.DubbingCliApiTests.test_list_voxcpm_batches_reads_manifest tests.test_dubbing_cli_api.DubbingCliApiTests.test_load_voxcpm_batch_restores_task_view tests.test_dubbing_cli_api.DubbingCliApiTests.test_load_voxcpm_batch_marks_failed_batch_resumable_from_selected_subtitles tests.test_dubbing_cli_api.DubbingCliApiTests.test_resume_voxcpm_task_requeues_failed_batch tests.test_dubbing_cli_api.DubbingCliApiTests.test_run_voxcpm_job_resume_skips_completed_segments` 通过（6 tests, OK）
- `./.venv/bin/python -m py_compile src/subtitle_maker/voxcpm_dub_api.py src/subtitle_maker/domains/media/compose.py tests/test_dubbing_cli_api.py` 通过
- `node --check src/subtitle_maker/static/js/voxcpmDubbingPanel.js` 通过
- `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_voxcpm_backend_status_proxies_health_payload tests.test_dubbing_cli_api.DubbingCliApiTests.test_list_voxcpm_batches_reads_manifest tests.test_dubbing_cli_api.DubbingCliApiTests.test_load_voxcpm_batch_restores_task_view tests.test_dubbing_cli_api.DubbingCliApiTests.test_load_voxcpm_batch_marks_failed_batch_resumable_from_selected_subtitles tests.test_dubbing_cli_api.DubbingCliApiTests.test_resume_voxcpm_task_requeues_failed_batch tests.test_dubbing_cli_api.DubbingCliApiTests.test_run_voxcpm_job_resume_skips_completed_segments tests.test_dubbing_cli_api.DubbingCliApiTests.test_voxcpm_soft_align_segment_keeps_natural_duration_without_fit tests.test_dubbing_cli_api.DubbingCliApiTests.test_voxcpm_soft_align_segment_trims_leading_silence_without_fit tests.test_dubbing_cli_api.DubbingCliApiTests.test_start_voxcpm_from_project_allows_subtitle_only_mode tests.test_dubbing_cli_api.DubbingCliApiTests.test_run_voxcpm_job_subtitle_only_builds_natural_srt_and_black_video tests.test_dubbing_cli_api.DubbingCliApiTests.test_build_black_video_with_ass_subtitles_uses_black_canvas_and_ass_filter` 通过（11 tests, OK）
- [x] Review
  - [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 现在会在任务中途持续落盘 `selected_subtitles.srt`、`source_audio.wav`、参考音频路径、推理参数与每条 `segments/segment_XXXX/manifest.json`，并提供 `_infer_voxcpm_resume_state(...)`、`_build_voxcpm_resume_context(...)`、`/voxcpm/auto/resume/{task_id}` 真正续跑缺失 segment
  - [src/subtitle_maker/static/js/voxcpmDubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/voxcpmDubbingPanel.js) 与 [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html) 的 6 号面板 Restore 区已新增 resume 按钮，并按 `prepared / dubbing_partial / completed` 动态显示按钮文案
  - [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 新增 6 号面板恢复回归：失败批次加载可恢复态、resume 重新入队、续跑只生成缺失 segment
  - [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 已切到纯字幕自然朗读链路：不再强制 `fit_audio_to_duration(...)`，而是只做保守裁静音，并按每句真实生成时长顺序重建最终 `dubbed_final_full.srt`
  - 同文件新增 6 号面板专用 ASS 导出模板与黑底视频产物：最终会生成 `dubbed_mix_full.wav`、`dubbed_final_full-styled.ass`、`dubbed_video_full.mp4`
  - [src/subtitle_maker/domains/media/compose.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/media/compose.py) 新增 `build_black_video_with_ass_subtitles(...)`，统一用 FFmpeg `color + ass` 生成黑底字幕视频
  - [src/subtitle_maker/static/js/voxcpmDubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/voxcpmDubbingPanel.js) 与 [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html) 已同步改成“只要字幕 + 参考音频即可启动”的文案和前端校验
  - [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 新增纯字幕启动、自然时长 SRT 重建、黑底 ASS 视频生成回归测试，锁住本次新合同

## 94. 2026-05-18 6 号面板接入多 speaker 识别与按性别自动补齐参考音
- [x] 现状
  - [src/subtitle_maker/static/js/voxcpmDubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/voxcpmDubbingPanel.js) 当前只有单个 `Reference Audio` + `Reference Text` 输入，没有像 5 号面板那样按 `speaker_id` 渲染多条上传槽位
  - 同文件 `buildCurrentProjectRequest()` 当前只会提交单个 `ref_audio_file/ref_text`，6 号面板后端因此只能按“整批共用一份参考音”运行
  - [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 当前 `_run_voxcpm_job(...)` 对每一条字幕都调用同一组 `ref_audio_path/ref_text`，没有按 `speaker_id` 分流
  - [src/subtitle_maker/static/js/omnivoiceDubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/omnivoiceDubbingPanel.js) 已实现基于字幕 `speaker_id` 的稳定 speaker 列表提取和逐 speaker 上传 UI
  - [src/subtitle_maker/omnivoice_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/omnivoice_dub_api.py) 已实现缺失参考音自动补位链路：`_infer_missing_speaker_gender_hints(...)` 先从原音频 probe 缺失 speaker 的男女，再由预置 `ref-voices/<lang>/male|female/` 随机选一个补齐
  - [src/subtitle_maker/omnivoice_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/omnivoice_dub_api.py) 还实现了 `_infer_voice_gender_label(...)`、本地模型 `_classify_voice_gender_with_local_model(...)` 与 pitch 兜底，用于在自动补位前判断男女
- [x] 功能点
  - 在 [src/subtitle_maker/static/js/voxcpmDubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/voxcpmDubbingPanel.js) 复用 5 号面板的 speaker 识别逻辑，按当前字幕稳定提取 `speaker_id` 列表，并在 6 号面板渲染逐 speaker 上传槽位
  - 保留原有单 `Reference Audio` + `Reference Text` 入口，兼容单 speaker 或用户只想整批共用一份参考音的路径
  - 在 [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 支持接收 `speaker_ref_files + speaker_ref_speaker_ids_json`，允许只上传部分 speaker
  - 运行时按字幕 `speaker_id` 逐句选参考音；未上传的 speaker 优先基于原音频 probe 性别，再从预置参考音池补齐；纯字幕无媒体时降级为直接随机预置补位
  - 把 `speaker_ids / speaker_reference_mode / speaker_ref_map` 写入 manifest 与 resume context，保证 6 号面板后续恢复链路能复用本次 speaker 路由
- [x] 风险与决策
  - 决策 1：6 号面板继续允许“部分上传 + 自动补位”，不沿用 5 号面板早期的“0 或全上传”强约束，因为用户明确要求未上传 speaker 时自动随机选
  - 决策 2：性别判断只在“有媒体且已抽出 `source_audio.wav`”时启用；纯字幕模式没有可 probe 音频时，直接走 `preset_only`，不伪造性别结论
  - 决策 3：缺失 speaker 的默认参考文本继续随 `target_lang` 切换，保证自动补位音频和提示文案语义一致
- [x] 实施
  - [x] 更新 6 号面板前端 speaker 列表、上传槽位、提示文案与请求透传
  - [x] 更新 `voxcpm_dub_api.py` 的任务 payload / manifest / resume context / 逐句 speaker 路由
  - [x] 接入“部分上传 + 性别探测补位 + 无媒体降级 preset_only”三条后端分支
  - [x] 补 6 号面板多 speaker 定向回归测试
- [x] 验证
  - `./.venv/bin/python -m py_compile src/subtitle_maker/voxcpm_dub_api.py tests/test_dubbing_cli_api.py` 通过
  - `node --check src/subtitle_maker/static/js/voxcpmDubbingPanel.js` 通过
  - `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_voxcpm_collect_detected_speaker_ids_prefers_previous_row_before_speaker_1 tests.test_dubbing_cli_api.DubbingCliApiTests.test_start_voxcpm_from_project_accepts_partial_speaker_refs tests.test_dubbing_cli_api.DubbingCliApiTests.test_run_voxcpm_job_resume_skips_completed_segments tests.test_dubbing_cli_api.DubbingCliApiTests.test_run_voxcpm_job_partial_speaker_refs_fill_missing_speakers tests.test_dubbing_cli_api.DubbingCliApiTests.test_run_voxcpm_job_without_media_uses_preset_only_mode tests.test_dubbing_cli_api.DubbingCliApiTests.test_run_voxcpm_job_subtitle_only_builds_natural_srt_and_black_video` 通过（6 tests, OK）
- [x] Review
  - [src/subtitle_maker/static/js/voxcpmDubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/voxcpmDubbingPanel.js) 现在会基于当前字幕自动归一化 `speaker_id`，动态渲染 `Speaker Refs` 上传区，并把 `speaker_ref_speaker_ids_json + speaker_ref_files` 一起提交给后端
  - [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html) 的 6 号面板现已移除 `Single reference audio + text` 控件，只保留按 speaker 上传参考音的入口；0 上传时直接走后端 `preset_only`
  - [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 新增 `_normalize_speaker_ids_for_rows(...)`、`_collect_detected_speaker_ids(...)`、`_build_voxcpm_uploaded_speaker_ref_map(...)`，并让 `_run_voxcpm_job(...)` 按 speaker 路由 `ref_audio/ref_text`
  - 缺失 speaker 时，6 号面板现在会优先从 `source_audio.wav` 推断男女，再走预置参考音池补位；纯字幕无媒体时则明确降级成 `preset_only`
  - [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 已补回归，锁住“上一行优先补 speaker”“部分上传可启动”“自动混合补位”“纯字幕 preset_only”“resume 不回退”的核心合同

## 95. 2026-05-18 修复 6 号面板 VoxCPM 接口偶发 `IncompleteRead` 导致整批失败
- [x] 现状
  - [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 的 `_http_json(...)` 之前对 `urllib.request.urlopen(...)` 的响应只读一次，任何截断响应都会直接抛异常，中断整批任务
  - 同文件 `_call_voxcpm_tts(...)` 直接复用 `_http_json(...)` 调本地 VoxCPM API，因此单句 TTS 返回体略大或连接抖动时，会把一次短暂传输异常放大成整批失败
- [x] 功能点
  - 在 `_http_json(...)` 中为 `IncompleteRead` 增加有限次数自动重试，只处理“响应体被截断”这一类瞬时错误，不扩大到所有异常
  - 保持原有 `HTTPError / URLError` 语义不变，避免把真实接口错误误判成可重试成功
  - 补单测锁住“首次截断、二次成功”这条运行时合同
- [x] 风险与决策
  - 决策 1：首版只在 `_http_json(...)` 做轻量重试，不改整条 6 号面板调度策略，先收掉已确认的截断响应问题
  - 决策 2：重试次数保持很小，避免服务端持续坏响应时无上限拖长整批任务
- [x] 实施
  - [x] 在 `src/subtitle_maker/voxcpm_dub_api.py` 引入 `IncompleteRead` 并为 `_http_json(...)` 增加有限重试
  - [x] 在 `tests/test_dubbing_cli_api.py` 新增 `test_voxcpm_http_json_retries_incomplete_read`
- [x] 验证
  - `./.venv/bin/python -m py_compile src/subtitle_maker/voxcpm_dub_api.py tests/test_dubbing_cli_api.py` 通过
  - `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_voxcpm_http_json_retries_incomplete_read` 通过（1 test, OK）
  - `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_run_voxcpm_job_partial_speaker_refs_fill_missing_speakers` 通过（1 test, OK）
  - `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_run_voxcpm_job_subtitle_only_builds_natural_srt_and_black_video` 通过（1 test, OK）
- [x] Review
  - [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 的 `_http_json(...)` 现在会在 `IncompleteRead` 时记录 warning，并做最多 2 次短退避重试；只有重试耗尽后才抛出 `RuntimeError`
  - [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 已锁住这次修复，确保未来不会再回退成“首次截断即整批失败”

## 96. 2026-05-18 修复 6 号面板长句黑底字幕视频末尾两行显示不全
- [x] 现状
  - [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 当前 `_build_voxcpm_typewriter_dialogues(...)` 会把整条长字幕按逐字累积方式堆到同一页
  - 在 120 字号下，超长句容易被拆成过多行，导致中部字幕整体高度超出黑底视频安全区，最后两行看不全
- [x] 功能点
  - 为 6 号面板 ASS 生成增加“分页打字机”逻辑：每页最多 4 行，超长句自动分页显示
  - 保留打字机效果，但每页结尾都保留完整文本一小段时间，避免最后几行只在最后一瞬间出现
- [x] 风险与决策
  - 决策 1：不缩小 120 字号，也不改中部字幕布局，优先通过分页解决长句垂直溢出
  - 决策 2：分页仍保持从左到右、从上到下显现，只是把超长句拆成多页顺序展示
- [x] 实施
  - [x] 在 `src/subtitle_maker/voxcpm_dub_api.py` 新增分页逻辑与页级 typewriter 生成
  - [x] 调整超长句换行/保留策略，确保单页不超过 4 行
  - [x] 在 `tests/test_dubbing_cli_api.py` 新增长句分页可见性回归测试
- [x] 验证
  - `./.venv/bin/python -m py_compile src/subtitle_maker/voxcpm_dub_api.py tests/test_dubbing_cli_api.py` 通过
  - `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_build_voxcpm_centered_ass_from_rows_wraps_lines_and_uses_typewriter_dialogues tests.test_dubbing_cli_api.DubbingCliApiTests.test_build_voxcpm_centered_ass_from_rows_keeps_full_long_subtitle_visible_before_end` 通过（2 tests, OK）
- [x] Review
  - [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 现在会先把长句折行为多行，再按“每页最多 4 行”分页；每页单独做打字机显现和结尾完整停留，避免一整页堆到 8 至 10 行
  - [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 已锁住“最后一页完整停留 + 任意页不超过 4 行”的合同

## 97. 2026-05-18 调整 6 号面板 Run / Restore 卡片顺序
- [x] 实施
  - [x] 交换 [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html) 中 6 号面板 `Run` 与 `Restore` 卡片位置
- [x] 验证
  - `node --check src/subtitle_maker/static/js/voxcpmDubbingPanel.js` 通过

## 98. 2026-05-18 修复 6 号面板完成态未显示总耗时
- [x] 实施
  - [x] 给 6 号面板接入 `buildAutoDubElapsedLabel(...)`
  - [x] 完成态和加载已完成批次时显示 `用时 mm:ss / h:mm:ss`
- [x] 验证
  - `node --check src/subtitle_maker/static/js/voxcpmDubbingPanel.js` 通过
  - `node --check src/subtitle_maker/static/app.js` 通过

## 99. 2026-05-19 调整 6 号面板 Current Project / Setup 为并排布局
- [x] 实施
  - [x] 复用 `auto-dub-top-grid` 双栏，把 [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html) 中 `Current Project` 与 `Setup` 放到同一行
- [x] 验证
  - `node --check src/subtitle_maker/static/js/voxcpmDubbingPanel.js` 通过
  - `node --check src/subtitle_maker/static/app.js` 通过

## 100. 2026-05-19 给 6 号面板补齐和 5 号面板一致的实时计时显示
- [x] 实施
  - [x] 在 6 号面板状态区增加独立 `ETA / 用时` 显示位
  - [x] 运行中实时刷新 elapsed，完成后保留最终 `用时`
- [x] 验证
  - `node --check src/subtitle_maker/static/js/voxcpmDubbingPanel.js` 通过
  - `node --check src/subtitle_maker/static/app.js` 通过

## Spec-10（2026-05-19 6 号面板 final 字幕视频增加简体/繁体中文字幕开关）1/3 现状分析
- 目标：在 6 号面板前端增加一个开关，控制 final 黑底字幕视频使用简体中文字幕还是繁体中文字幕；默认简体。
- 现状 1：6 号面板 `Setup` 区当前只有 `Source Language / Target Language / CFG Value / Inference Steps / Custom System Prompt`，还没有任何“字幕字形”或“简繁转换”相关控件。
  - 证据：
    - [src/subtitle_maker/templates/index.html](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/templates/index.html) 的 6 号面板 `Setup` 卡片只渲染 `voxcpm-source`、`voxcpm-target`、`voxcpm-cfg-value`、`voxcpm-inference-steps`、`voxcpm-translate-system-prompt`
    - [src/subtitle_maker/static/js/voxcpmDubbingPanel.js](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/static/js/voxcpmDubbingPanel.js) 的 `buildCurrentProjectRequest()` 只提交 `source_lang / target_lang / cfg_value / inference_timesteps / translate_system_prompt / speaker_ref_*`，没有字幕字形参数
- 现状 2：6 号面板 final 字幕视频是由最终 `final_rows` 直接生成 ASS，再调用 FFmpeg 烧到黑底视频上；当前没有“额外派生一份简体/繁体字幕文本”的步骤。
  - 证据：
    - [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 的 `_run_voxcpm_job(...)` 在最终阶段把 `final_rows` 写到 `dubbed_final_full.srt`
    - 同文件 `_build_voxcpm_centered_ass_from_rows(...)` 接收的也是 `rows` 原文，当前签名没有任何 script/variant 参数
    - 同文件 `_run_voxcpm_job(...)` 随后把 `final_rows` 直接喂给 `_build_voxcpm_centered_ass_from_rows(...)` 生成 [dubbed_final_full-styled.ass](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py)
    - [src/subtitle_maker/domains/media/compose.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/domains/media/compose.py) 的 `build_black_video_with_ass_subtitles(...)` 只是消费现成 ASS 文件，不负责简繁转换
- 现状 3：当前项目里已经有“粤语目标语种统一按繁体落盘”的既有规则，但这套规则属于翻译输出规范，不等于“视频字幕字形开关”。
  - 证据：
    - [src/subtitle_maker/translator.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/translator.py) 的 `normalize_cantonese_translation_text(...)` 与相关注释明确说明：粤语目标语种当前统一繁体落盘，只区分港式/广东式口语风格
    - 这意味着如果要做“final 视频字幕简体/繁体开关”，应是 6 号面板 final 渲染层的新派生选项，不能直接混同为 `target_lang`
- 现状 4：6 号面板后端启动与恢复链路当前已经会把 `target_lang / subtitle_mode / speaker_ids / paths / artifacts` 持久化到 manifest，但还没有“字幕视频字形偏好”的持久化字段。
  - 证据：
    - [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 的 `start_voxcpm_from_project(...)` 只接收 `target_lang` 等现有表单字段
    - 同文件 `_persist_voxcpm_task_manifest(...)` / `load_voxcpm_batch(...)` 当前恢复的是 `target_lang`、`speaker_reference_mode`、`artifacts` 等字段，没有字幕视频字形偏好

## Spec-10（2026-05-19 6 号面板 final 字幕视频增加简体/繁体中文字幕开关）2/3 功能点与改动边界
- 功能点 1：在 6 号面板 `Setup` 区新增一个独立开关，控制 final 字幕视频的中文脚本输出。
  - 推荐 UI：`Final Subtitles Script`
  - 选项：`Simplified (默认)` / `Traditional`
  - 语义：只控制 final 字幕文件与黑底字幕视频的字形，不改变音频、不改变配音语言、不改变 speaker 选择
- 功能点 2：前端把该开关随启动/恢复请求一并提交，并在任务恢复视图中可读回当前值。
  - 请求字段建议命名为 `subtitle_script_variant`
  - 默认值固定为 `simplified`
  - `load-batch / resume` 需要把该值从 manifest 带回前端，避免恢复后界面和实际产物不一致
- 功能点 3：后端 final 渲染阶段按该开关派生中文脚本，再生成最终字幕文件和黑底视频。
  - 转换点放在 final `rows -> SRT/ASS` 的输出前，而不是翻译阶段
  - 这样可以保证：
    - 翻译阶段仍保留当前粤语/普通话口语质量规则
    - 同一批内容可以只切换显示字形，不重复跑翻译和配音
  - 受影响产物至少包括：
    - `dubbed_final_full.srt`
    - `dubbed_final_full_with_speakers.srt`
    - `dubbed_final_full-styled.ass`
    - `dubbed_video_full.mp4`
- 功能点 4：仅对中文 final 字幕生效，英文路径保持不变。
  - `target_lang = English` 时，开关无效
  - `target_lang = Chinese / Cantonese / Cantonese-Mainland` 时，按用户选择的脚本输出
- 功能点 5：恢复与审计必须保留该字段。
  - manifest 需要记录 `subtitle_script_variant`
  - `load-batch` 视图要展示当前批次采用的是简体还是繁体
  - 这样才能保证 resume / 重新加载后，final 输出和 UI 状态一致
- 改动边界：
  - 不改音频生成策略
  - 不改翻译 API 的口语化约束
  - 不改 speaker 逻辑
  - 不把这个开关扩散到 5 号面板或其他面板

## Spec-10（2026-05-19 6 号面板 final 字幕视频增加简体/繁体中文字幕开关）3/3 风险、关键决策与推荐方案
- 风险 1：如果把简繁转换放在翻译阶段，会误伤粤语口语化规则。
  - 原因：当前 `normalize_cantonese_translation_text(...)` 已经在翻译层做了粤语目标语种的专门收尾；再把简繁混进去，容易把“港式/广东式口语”和“字形切换”绑死，后续难以维护。
  - 推荐：把简繁转换放到 final 渲染前，只作用于输出字幕文本，不作用于翻译结果的内部语义。
- 风险 2：如果只改前端不落盘，恢复 / reload 后界面会和产物不一致。
  - 推荐：把 `subtitle_script_variant` 写进任务 manifest、load-batch、resume context 和任务公开状态，让前端能从磁盘批次恢复当前脚本选择。
- 风险 3：如果对所有语言都强制做简繁转换，英文或其他非中文内容会被污染。
  - 推荐：只在 `target_lang` 属于中文系时启用；英文直接跳过。
- 风险 4：如果 final SRT、final ASS、final video 使用不同脚本源，会造成下载产物互相不一致。
  - 推荐：在 final 阶段统一生成一个“已按脚本 variant 处理过的最终 rows”，然后所有 final 产物都从这份 rows 生成。
- 风险 5：如果把这个开关做成“粤语专属”，语义会和用户预期的“简体/繁体字幕”不一致。
  - 推荐：按“中文 final 输出脚本”定义，而不是按语言细分到粤语专属；这样最符合当前需求。
- 关键决策 1：脚本转换层级
  - 选项 A：翻译阶段做简繁切换
  - 选项 B：final 渲染阶段做简繁切换
  - 推荐：选项 B
  - 理由：最小化对翻译质量和 speaker 逻辑的影响，且更符合“只影响 final 字幕视频”的需求。
- 关键决策 2：默认值
  - 选项 A：默认繁体
  - 选项 B：默认简体
  - 推荐：选项 B
  - 理由：用户已明确要求默认简体。
- 关键决策 3：作用范围
  - 选项 A：只影响粤语
  - 选项 B：影响所有中文 final 字幕
  - 推荐：选项 B
  - 理由：用户已明确否定“只影响粤语”的范围，且更符合“简体/繁体中文字幕”的产品语义。
- 推荐实现方案：
  - 前端在 6 号面板 `Setup` 增加 `subtitle_script_variant` 单选/切换控件，默认 `simplified`
  - `buildCurrentProjectRequest()` 透传该字段到后端
  - `_create_task_payload(...)`、manifest、load-batch、resume context 全部持久化该字段
  - `_run_voxcpm_job(...)` 在生成 final rows 后，调用统一的脚本转换函数，再输出 SRT / ASS / MP4
  - 输出产物命名保持不变，避免破坏现有下载路由
- 结论：
  - 这是一个前端可见、后端可恢复、只作用于 final 输出的轻量开关，推荐直接按“final 渲染阶段转换”落地。
- [x] 实施
  - [x] 在 6 号面板 `Setup` 增加 `subtitle_script_variant` 开关，默认 `simplified`
  - [x] 让 6 号面板启动/恢复请求透传 `subtitle_script_variant`
  - [x] 在 6 号面板 final 渲染前统一做简繁转换，并同步到 final SRT / ASS / 视频
  - [x] 把 `subtitle_script_variant` 写入 manifest / load-batch / resume context
  - [x] 补 6 号面板简繁切换与恢复回归测试
- [x] 验证
  - `./.venv/bin/python -m py_compile src/subtitle_maker/domains/subtitles/zh_script.py src/subtitle_maker/domains/subtitles/__init__.py src/subtitle_maker/voxcpm_dub_api.py tests/test_dubbing_cli_api.py` 通过
  - `node --check src/subtitle_maker/static/js/voxcpmDubbingPanel.js` 通过
  - `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_convert_chinese_script_rows_supports_simplified_and_traditional tests.test_dubbing_cli_api.DubbingCliApiTests.test_run_voxcpm_job_subtitle_only_builds_natural_srt_and_black_video tests.test_dubbing_cli_api.DubbingCliApiTests.test_run_voxcpm_job_traditional_variant_converts_final_outputs tests.test_dubbing_cli_api.DubbingCliApiTests.test_load_voxcpm_batch_restores_task_view` 通过（4 tests, OK）
- [x] 6 号面板字幕描边加粗
  - [x] 在 [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 把 ASS 样式 `Outline` 从 `4` 提升到 `10`
  - [x] 在 [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 更新 6 号面板样式断言，锁住 `Outline=10`
  - [x] 验证 `test_build_voxcpm_centered_ass_from_rows_wraps_lines_and_uses_typewriter_dialogues`
- [x] 6 号面板描边改橘色
  - [x] 在 [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 把 ASS `OutlineColour` 从纯黑改为橘色 `&H000066FF`
  - [x] 在 [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 更新样式断言，锁住橘色描边
  - [x] 验证 `test_build_voxcpm_centered_ass_from_rows_wraps_lines_and_uses_typewriter_dialogues`
- [x] 6 号面板橘色描边厚度调整
  - [x] 在 [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 把橘色描边 `Outline` 从 `10` 调整为 `6`
  - [x] 在 [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 更新样式断言，锁住 `Outline=6`
  - [x] 验证 `test_build_voxcpm_centered_ass_from_rows_wraps_lines_and_uses_typewriter_dialogues`
- [x] 6 号面板改为黑字白描边
  - [x] 在 [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 把 ASS 样式改为黑字 `&H00000000` + 白色描边 `&H00FFFFFF`
  - [x] 在 [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 更新样式断言，锁住黑字白描边
  - [x] 验证 `test_build_voxcpm_centered_ass_from_rows_wraps_lines_and_uses_typewriter_dialogues`
- [x] 6 号面板恢复白字黑描边并放大字号
  - [x] 在 [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 把 ASS 样式恢复为白字 `&H00FFFFFF` + 黑色描边 `&H00000000`
  - [x] 同文件把三个规格字号按 20% 上调：`1920x1080` 从 `120` 到 `144`，`1080x1920` 从 `85` 到 `102`，`1440x1080` 从 `100` 到 `120`
  - [x] 在 [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 更新三种规格的字号断言和主样式颜色断言
  - [x] 验证 6 号面板 ASS 样式与三种规格字号测试
- [x] 6 号面板改为橙色描边并减细
  - [x] 在 [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 把描边改为橙色 `&H000066FF`
  - [x] 同文件把描边厚度从 `6` 调整为 `4`
  - [x] 在 [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 更新样式断言，锁住橙色描边与 `Outline=4`
  - [x] 验证 `test_build_voxcpm_centered_ass_from_rows_wraps_lines_and_uses_typewriter_dialogues`
- Review
  - 6 号面板黑底字幕视频当前样式为白字、橙色描边 `Outline=4`、半透明青色底条，且三个规格字号均上调 20%

## 6 号面板字幕视频对齐优化（播客长句）

- [x] 现状分析确认
  - [x] 核对 [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 的 `_compose_natural_sequence_mix(...)`、`_build_voxcpm_centered_ass_from_rows(...)` 与 final 输出链路，确认黑底字幕视频当前仍直接消费整句 `final_rows_for_output`
  - [x] 核对同文件 final 阶段的 `dubbed_final_full-rebuild.srt` 生成逻辑，确认它已经把长句拆成更短的 rebuild 行并重算时间戳，但尚未用于 ASS / MP4 渲染
- [x] 功能点待确认
  - [x] 确认 6 号面板主方案改为“翻译后、TTS 前的前置长句拆分”，不再依赖 rebuild 纠偏
  - [x] 确认拆分后的短句直接进入 `selected_subtitles.srt`、segment manifest、final srt 与字幕视频渲染链路
- [x] 风险与决策待确认
  - [x] 确认只改 6 号面板，不动 5 号面板
  - [x] 确认 `selected_subtitles.srt`、`selected_subtitles_with_speakers.srt`、`dubbed_final_full.srt`、`dubbed_final_full_with_speakers.srt` 都接受变成短句真值
  - [x] 确认 `dubbed_final_full-rebuild.srt` 先保留为 fallback/debug 产物
- [ ] 实施
  - [x] 在 [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 增加 6 号面板前置长句拆分 helper，按标点/语义优先切分超长句并继承 `speaker_id`
  - [x] 在同文件 `_run_voxcpm_job(...)` 接入前置拆分步骤，并让 `selected_subtitles.srt` / segment / final 输出统一吃短句真值
  - [x] 在 [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 补 6 号面板前置拆分回归测试，覆盖 speaker 继承、selected subtitles 短句化、final 短句化
  - [x] 评估 `dubbed_final_full-rebuild.srt` 在新流程下是否仍需保留当前生成逻辑
- [ ] 验证
  - [x] `./.venv/bin/python -m py_compile src/subtitle_maker/voxcpm_dub_api.py tests/test_dubbing_cli_api.py`
  - [x] `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_run_voxcpm_job_subtitle_only_builds_natural_srt_and_black_video tests.test_dubbing_cli_api.DubbingCliApiTests.test_run_voxcpm_job_splits_long_rows_before_tts_and_keeps_speaker_ids tests.test_dubbing_cli_api.DubbingCliApiTests.test_build_voxcpm_centered_ass_from_rows_wraps_lines_and_uses_typewriter_dialogues`
- Review
  - 6 号面板现在会在翻译后、TTS 前对超长句做前置拆分，`selected_subtitles.srt`、segment manifest、final SRT 与黑底字幕视频都会直接复用短句真值；`dubbed_final_full-rebuild.srt` 暂时保留为 fallback/debug 产物
- [x] 6 号面板前置拆分保留英文词间空格
  - [x] 在 [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 修正 CJK 兜底硬切逻辑，避免把中英混排里的英文短语压成连写
  - [x] 在 [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 增加中英混排回归测试，锁住 `Ideas are everywhere` / `They're worthless` 等英文短语空格
  - [x] 验证 `./.venv/bin/python -m py_compile src/subtitle_maker/voxcpm_dub_api.py tests/test_dubbing_cli_api.py`
  - [x] 验证 `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_split_voxcpm_long_text_before_tts_keeps_spaces_inside_english_phrases tests.test_dubbing_cli_api.DubbingCliApiTests.test_run_voxcpm_job_splits_long_rows_before_tts_and_keeps_speaker_ids`
- [x] 6 号面板前置拆分严格沿标点优先断句
  - [x] 在 [src/subtitle_maker/voxcpm_dub_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/src/subtitle_maker/voxcpm_dub_api.py) 增强中英混排切句：只要文本里含中文，也会优先识别英文句号 `.`、中文强标点和软标点，避免 `Ideas are everywhere.They're worthless...` 这类整段黏连
  - [x] 同文件对仍偏长的句子继续优先按软标点细分，减少落到字符级硬切的概率
  - [x] 在 [tests/test_dubbing_cli_api.py](/Users/tim/Documents/vibe-coding/MVP/subtitle-maker/tests/test_dubbing_cli_api.py) 增加回归测试，锁住 `Ideas are everywhere.` / `They're worthless.` 必须先断开，以及 `因为交税无可避免，` 这种优先沿标点切分
  - [x] 验证 `./.venv/bin/python -m unittest tests.test_dubbing_cli_api.DubbingCliApiTests.test_split_voxcpm_long_text_before_tts_keeps_spaces_inside_english_phrases tests.test_dubbing_cli_api.DubbingCliApiTests.test_split_voxcpm_long_text_before_tts_prefers_punctuation_boundaries tests.test_dubbing_cli_api.DubbingCliApiTests.test_split_voxcpm_mixed_text_breaks_on_english_period_before_chinese`

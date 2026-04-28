# TODO

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

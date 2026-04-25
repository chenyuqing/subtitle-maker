# 迁移路线

日期：2026-04-24

## 总原则

- 增量迁移，不推倒重写。
- 旧入口保留，新模块先被旧入口调用。
- 每阶段必须有测试或手测证据。
- 行为差异必须记录：是预期修复还是回归。
- 文档 review 完成前不进入业务代码实现。

## 阶段顺序

| 阶段 | 内容 | 产出 |
|---|---|---|
| Phase 0 | 写 `docs/refactor/*` 文档 | 本目录 7 份文档。 |
| Phase 1 | 多轮 review，锁定文档 | 修改后的最终计划。 |
| Phase 2 | 实现 Agent V1 | 右下角使用帮助抽屉，先解决用户卡住问题。 |
| Phase 3 | 补 contract/golden tests | 固定主链路行为。 |
| Phase 4 | 抽 Manifest、PipelineOptions、CommandBuilder | 统一字段和 CLI 参数。 |
| Phase 5 | 抽 Subtitle Domain | 统一 source.srt 处理规则。 |
| Phase 6 | 抽 Media Domain | 统一 ffmpeg、切片、拼接。 |
| Phase 7 | 抽 Dubbing Domain 和 TTS Backend | 支持 Index-TTS 主力、OmniVoice 备胎。 |
| Phase 8 | 重构 Job Store | 统一任务状态和恢复。 |
| Phase 9 | 拆 Web API routes | `web.py` 变薄。 |
| Phase 10 | 拆前端 JS 模块 | `app.js` 变薄。 |
| Phase 11 | 清理旧脚本和重复代码 | 旧入口 wrapper 化。 |

## Phase 2：Agent V1

目标：尽快提供产品内使用帮助和错误解释。

实现内容：

| 模块 | 内容 |
|---|---|
| `src/subtitle_maker/core/llm_client.py` | OpenAI-compatible chat client，后续翻译也可复用。 |
| `src/subtitle_maker/agent_api.py` | 迁移期 APIRouter，提供 `/api/agent/chat`。 |
| `src/subtitle_maker/web.py` | include agent router。 |
| 前端 | 右下角浮动抽屉。 |
| 测试 | key 缺失、空消息、401、超时、普通回答、禁止执行。 |

验收：

- 不保存 API key。
- 不执行任何项目操作。
- 能解释常见失败：DeepSeek key、Index-TTS 未启动、ASR 无字幕、ffmpeg 失败。
- 不影响上传、转写、翻译、Auto Dubbing 现有入口。

## Phase 3：Contract/Golden Tests

目标：冻结现有主链路行为。

测试覆盖：

| 测试 | 内容 |
|---|---|
| API contract | `/upload`、`/transcribe`、`/translate`、`/dubbing/auto/start`、status、review、redub。 |
| Manifest contract | batch manifest、segment manifest、failure manifest 关键字段。 |
| Subtitle golden | ASR 分句、上传 source 字幕分句、短句合并、时间戳重估。 |
| Long video | 空字幕 segment skip、partial subtitle merge、full timeline fallback。 |
| Review/redub | 改动句重配、失败 rollback、配置保持。 |

验收：

```bash
uv run python -m py_compile src/subtitle_maker tools tests
uv run python -m unittest tests.test_dubbing_cli_api
uv run python -m unittest tests.test_dub_pipeline_asr_layout
uv run python -m unittest tests.test_dub_long_video
```

## Phase 4：协议层

目标：消除字段散落。

实现内容：

| 模块 | 内容 |
|---|---|
| `manifests/schema.py` | BatchManifest、SegmentManifest、ReviewLine、Artifact。 |
| `manifests/readwrite.py` | 读写、默认值、旧 manifest 兼容。 |
| `jobs/models.py` | Project、Job、JobError。 |
| `jobs/command_builder.py` | 统一构造 `dub_long_video.py` 和 `dub_pipeline.py` 参数。 |

验收：

- load-batch 不丢 `target_lang`、`pipeline_version`、short merge 配置。
- save-and-redub 保留原始 synthesis/timing/pipeline 语义。
- 新旧 manifest 都能读取。

## Phase 5：Subtitle Domain

目标：统一 ASR 字幕和上传字幕的处理路径。

实现内容：

| 模块 | 内容 |
|---|---|
| `domains/subtitles/srt.py` | parse/write/merge。 |
| `sentence_split.py` | 句号优先、太长逗号拆。 |
| `short_merge.py` | 按时间目标合并短句。 |
| `timeline.py` | 文本片段时间戳重估。 |
| `asr.py` | ASR 输出到 source layout 的入口。 |

验收：

- ASR 和上传 source SRT 都走同一套分句/合并。
- `source.srt` 是处理后的最终 source 文件。
- 合并开关默认关闭，开启后按 `target_seconds ± round(target/3)`。

## Phase 6：Media Domain

目标：复用 ffmpeg/ffprobe、切片、拼接、导出逻辑。

实现内容：

| 模块 | 内容 |
|---|---|
| `core/ffmpeg.py` | 命令执行、错误包装。 |
| `domains/media/probe.py` | duration、media info。 |
| `segment.py` | range、silence boundary、segment clipping。 |
| `compose.py` | vocals/bgm/full timeline mix。 |
| `export.py` | mux video/audio/subtitle。 |

验收：

- 长视频部分字幕不会整批失败。
- skipped segment 不污染最终产物。
- repair_bad_segments 可逐步复用新 compose 逻辑。

## Phase 7：Dubbing Domain 和 TTS Backend

目标：主链路稳定逐句配音，backend 可替换。

实现内容：

| 模块 | 内容 |
|---|---|
| `domains/dubbing/references.py` | 每句原音频参考切片。 |
| `alignment.py` | 时长拟合、trim、fade。 |
| `pipeline.py` | 逐句配音编排。 |
| `review.py` | review lines、redub updates。 |
| `backends/base.py` | `TtsBackend` 接口。 |
| `backends/index_tts.py` | Index-TTS adapter。 |
| `backends/omni_voice.py` | OmniVoice fallback adapter。 |

验收：

- Index-TTS 是默认主 backend。
- OmniVoice 默认关闭，只在配置后作为备胎。
- 主失败和备胎失败都能出现在错误摘要中。

### 当前执行上下文（2026-04-24）

- 已完成第一刀下沉：
  - `domains/dubbing/references.py`
  - `domains/dubbing/alignment.py`
  - `backends/base.py`
  - `backends/index_tts.py`
  - `domains/dubbing/review.py`
- 已完成第二刀下沉：
  - `domains/dubbing/pipeline.py::synthesize_segments()`
  - `domains/dubbing/pipeline.py::synthesize_segments_grouped()`
- 旧入口已经开始转调新模块：
  - `tools/dub_pipeline.py` 的参考音频 helper、对齐 helper、`build_synthesis_groups()`、`synthesize_text_once()`
  - `tools/dub_pipeline.py` 的 `synthesize_segments()`、`synthesize_segments_grouped()`
  - `tools/repair_bad_segments.py` 的 Index-TTS / 对齐重复 helper
  - `src/subtitle_maker/dubbing_cli_api.py` 的 review redub 运行时参数恢复
- 当前 Phase 7 的运行时主循环已经完成收口，`tools/dub_pipeline.py` 保留为 facade，负责兼容旧 CLI/调用面。
- 下一步继续策略固定为：
  1. 保持 `tools/dub_pipeline.py` 为薄 facade，避免后续阶段回头污染旧入口
  2. 继续按 `/docs/refactor/05-migration-roadmap.md` 推进下一 phase
  3. 后续实现继续边改边回写 `tasks/todo.md` 与本路线图
- 这一阶段仍不做：
  - 不把 OmniVoice 接入主运行时
  - 不改 manifest schema
  - 不改 command builder 协议
  - 不重写 `dubbing_cli_api.py` 的 HTTP / 事务编排

## Phase 8：Job Store

目标：统一 Auto Dubbing 任务状态和恢复原语。

实现内容：

| 模块 | 内容 |
|---|---|
| `jobs/models.py` | 收口 Auto Dubbing 任务的最小 typed 记录与公开视图。 |
| `jobs/store.py` | 统一内存态任务创建、状态更新、stdout tail、公开视图。 |
| `jobs/recovery.py` | 统一 batch manifest 恢复、artifact 列表、batch 扫描。 |

验收：

- `load-batch` 不丢 `target_lang`、`pipeline_version`、short merge、`tts_backend`、`index_tts_api_url`。
- `status` 返回继续隐藏本地敏感路径。
- 保留 `_tasks` 兼容别名，不打碎现有测试与旧调用。

### 当前执行上下文（2026-04-24）

- 已新增：
  - `src/subtitle_maker/jobs/recovery.py`
- 已扩展：
  - `src/subtitle_maker/jobs/models.py`
  - `src/subtitle_maker/jobs/store.py`
  - `src/subtitle_maker/jobs/__init__.py`
- `src/subtitle_maker/dubbing_cli_api.py` 当前已改为通过 `jobs/store.py` / `jobs/recovery.py` 处理：
  - 公开任务视图
  - stdout tail 与阶段更新
  - `load-batch` 历史任务恢复
  - artifact 列表构建
- 当前刻意保留的兼容面：
  - `_task_store`
  - `_tasks = _task_store.items`
  - `src/subtitle_maker/web.py` 的普通转写 `tasks` 全局字典
- 本阶段验证已通过：
  - `uv run python -m py_compile src/subtitle_maker/jobs/models.py src/subtitle_maker/jobs/store.py src/subtitle_maker/jobs/recovery.py src/subtitle_maker/jobs/__init__.py src/subtitle_maker/dubbing_cli_api.py tests/test_task_store.py tests/test_job_recovery.py tests/test_dubbing_cli_api.py`
  - `uv run python -m unittest tests.test_task_store tests.test_job_recovery`（`Ran 7 tests ... OK`）
  - `uv run python -m unittest tests.test_dubbing_cli_api tests.test_manifest_contracts`（`Ran 46 tests ... OK`）

## Phase 9：Web API routes

目标：把 `web.py` 收成 app 初始化 wrapper，legacy routes 分组迁出。

实现内容：

| 模块 | 内容 |
|---|---|
| `app/main.py` | FastAPI app 创建、static/templates 挂载、router include。 |
| `app/legacy_runtime.py` | legacy `tasks`、ASR model、`transcribe_task()`、目录清理等共享运行态。 |
| `app/routes/projects.py` | 页面、上传、媒体回放、项目重置。 |
| `app/routes/subtitles.py` | 上传 SRT、转写、普通任务 cancel/status。 |
| `app/routes/translation.py` | legacy 翻译入口。 |
| `app/routes/exports.py` | export、download、segment。 |
| `app/routes/jobs.py` | 模型控制与运行态管理。 |

验收：

- 现有 URL 不变。
- `web.py` 继续导出 `app` 和 `start()`。
- 不影响现有 `streaming_api.py`、`dubbing_cli_api.py`、`agent_api.py`。

### 当前执行上下文（2026-04-24）

- `Phase 9` 已完成首轮实现。
- 已落地的拆分边界：
  - 只拆 `src/subtitle_maker/web.py` 里剩余的 legacy routes
  - 不迁 `src/subtitle_maker/streaming_api.py`
  - 不迁 `src/subtitle_maker/dubbing_cli_api.py`
  - 不迁 `src/subtitle_maker/agent_api.py`
- 已落地的兼容边界：
  - URL 不变
  - 前端 `src/subtitle_maker/static/app.js` fetch 协议不变
  - `src/subtitle_maker/web.py` 保留 compatibility wrapper
  - 普通转写 `tasks` 暂不和 Auto Dubbing `TaskStore` 合并
- 已新增：
  - `src/subtitle_maker/app/main.py`
  - `src/subtitle_maker/app/legacy_runtime.py`
  - `src/subtitle_maker/app/routes/projects.py`
  - `src/subtitle_maker/app/routes/subtitles.py`
  - `src/subtitle_maker/app/routes/translation.py`
  - `src/subtitle_maker/app/routes/exports.py`
  - `src/subtitle_maker/app/routes/jobs.py`
- 已收口：
  - `src/subtitle_maker/web.py` 现只保留 `app`、`start()` 和兼容导出
- 这一阶段仍不做：
  - 不改 URL 为 `/api/*`
  - 不重写 `segment_audio()` 逻辑
  - 不统一 legacy transcription 状态层
  - 不改前端 fetch 路径和返回结构
- 本阶段验证已通过：
  - `uv run python -m py_compile src/subtitle_maker/app/__init__.py src/subtitle_maker/app/main.py src/subtitle_maker/app/legacy_runtime.py src/subtitle_maker/app/routes/__init__.py src/subtitle_maker/app/routes/projects.py src/subtitle_maker/app/routes/subtitles.py src/subtitle_maker/app/routes/translation.py src/subtitle_maker/app/routes/exports.py src/subtitle_maker/app/routes/jobs.py src/subtitle_maker/web.py tests/test_web_routes_legacy.py`
  - `uv run python -m unittest tests.test_web_routes_legacy`（`Ran 4 tests ... OK`）
  - `uv run python -m unittest tests.test_agent_api tests.test_dubbing_cli_api`（`Ran 45 tests ... OK`）
- 下一步最自然的是继续 `Phase 10：前端 JS 模块拆分`，并继续保持“边实现边回写路线图和 todo”的节奏。

## Phase 10：前端 JS 模块拆分

目标：在不改现有页面协议和 DOM 契约的前提下，让 `app.js` 退成前端装配入口。

实现内容：

| 模块 | 内容 |
|---|---|
| `src/subtitle_maker/static/app.js` | 迁移期入口，只保留 bootstrap / 共享状态装配。 |
| `src/subtitle_maker/static/js/agentDrawer.js` | Agent 抽屉交互与会话状态。 |
| `src/subtitle_maker/static/js/dubbingPanel.js` | Auto Dubbing V1/V2、review、load-batch、轮询。 |
| `src/subtitle_maker/static/js/player.js` | 播放器、overlay、时间轴与快捷键。 |
| `src/subtitle_maker/static/js/subtitleWorkflow.js` | 上传、转写、翻译、导出、SRT 导入。 |

验收：

- `index.html` 现有 DOM id、现有 fetch 路径和返回字段保持不变。
- 旧 `/static/app.js` 入口保留，页面加载方式不切断。
- Auto Dubbing V1/V2 和 Agent 抽屉行为不回归。

### 当前执行上下文（2026-04-25）

- `Phase 10` 已完成首轮实现。
- 当前前端装配边界：
  - `src/subtitle_maker/templates/index.html` 仍只通过 `/static/app.js?v=...` 加载前端脚本
  - `src/subtitle_maker/static/app.js` 保留为 classic script 入口与 legacy workflow 装配层
  - 新增：
    - `src/subtitle_maker/static/js/agentDrawer.js`
    - `src/subtitle_maker/static/js/dubbingPanel.js`
- 本阶段的反向同步结论：
  - 实现上没有把模板改成 `type=module`
  - 而是保留 classic `/static/app.js` 入口，并通过原生 `import()` 装配子模块
  - 这样可以继续直接使用 `node --check` 校验 `app.js`
- `Spec-2` 已收敛出的首轮策略：
  - 首轮只落 `agentDrawer.js` 与 `dubbingPanel.js`
  - `player.js`、`subtitleWorkflow.js`、统一 `apiClient.js` 延后到第二刀
  - 不引入 bundler，不改现有 fetch 路径、DOM id、localStorage/sessionStorage key
- `Spec-3` 已收敛出的首轮护栏：
  - `legacy_runtime._static_version("app.js")` 现已覆盖 `static/js/*.js` 最新 mtime
  - `dubbingPanel.js` 通过依赖注入 + `applyAutoDubSubtitleItems()` 回写共享状态
  - 已补首页入口护栏与浏览器最小 smoke
- 本阶段验证已通过：
  - `node --check src/subtitle_maker/static/app.js`
  - `node --check src/subtitle_maker/static/js/agentDrawer.js`
  - `node --check src/subtitle_maker/static/js/dubbingPanel.js`
  - `uv run python -m py_compile src/subtitle_maker/app/legacy_runtime.py tests/test_web_routes_legacy.py`
  - `uv run python -m unittest tests.test_web_routes_legacy tests.test_agent_api tests.test_dubbing_cli_api`（`Ran 49 tests ... OK`）
  - 浏览器 smoke：Chrome 实测 Agent 抽屉可打开并发送消息，Auto Dubbing V1/V2 面板可切换且首屏无脚本报错

## Phase 11：清理旧脚本和重复代码

目标：清掉已经失效的旧入口和休眠逻辑，让迁移后的兼容层边界更清楚。

实现内容：

| 模块 | 内容 |
|---|---|
| `src/subtitle_maker/simple_web.py` | 评估旧 simple app 是否继续保留、wrapper 化或下线。 |
| `src/subtitle_maker/static/app.js` | 清理当前模板已不再使用的旧 `dubbing/start` 休眠逻辑。 |
| `src/subtitle_maker/web.py` | 保持为迁移期兼容 wrapper，不在首轮大改。 |
| `tools/dub_pipeline.py` / `tools/repair_bad_segments.py` | 保持旧 CLI / repair 入口，优先不动主调用面。 |
| `tools/dub_long_video.py` | 继续保留为长视频编排脚本，不误判为纯重复 wrapper。 |

验收：

- 当前页面不再引用的前端休眠逻辑被清掉。
- 旧 simple app 的去留策略明确，并且不影响现有主站入口。
- 现有兼容 wrapper 和 CLI 入口不被顺手打碎。

### 当前执行上下文（2026-04-25）

- `Phase 11` 已完成首轮实现。
- 已确认应暂时保留的兼容面：
  - `src/subtitle_maker/web.py` 已经是迁移期启动 wrapper
  - `tools/dub_pipeline.py` 主要保留兼容 CLI / 旧函数名
  - `tools/repair_bad_segments.py` 的重复 helper 已大量收口为 facade
  - `tools/dub_long_video.py` 仍然真实承载长视频分段编排
- 本阶段已完成的首轮收口：
  - `src/subtitle_maker/static/app.js` 已删除旧 `Dubbing Logic (Step 5)` 休眠代码，并清掉 `dub-target-lang` 残留引用
  - 已新增 `src/subtitle_maker/app/legacy_simple_app.py`
  - `src/subtitle_maker/simple_web.py` 已退成 wrapper，继续承接 `subtitle-maker-simple-web`
- 本阶段验证已通过：
  - `node --check src/subtitle_maker/static/app.js`
  - `uv run python -m py_compile src/subtitle_maker/app/legacy_simple_app.py src/subtitle_maker/simple_web.py`
  - `uv run python -m unittest tests.test_simple_web_legacy tests.test_web_routes_legacy`（`Ran 7 tests ... OK`）
  - 浏览器 smoke：Chrome 实测主站首页仍会加载 `/static/app.js?v=...`、`/static/js/dubbingPanel.js?v=...`、`/static/js/agentDrawer.js?v=...`，`Auto Dubbing` 与 `Auto Dubbing V2` 面板首屏无脚本报错
- 当前整线收口状态：
  - Phase 5 到 Phase 11 已全部落地
  - 更大范围回归已通过：`uv run python -m unittest tests.test_agent_api tests.test_command_builder tests.test_manifest_contracts tests.test_task_store tests.test_job_recovery tests.test_dubbing_runtime tests.test_dub_pipeline_asr_layout tests.test_dub_long_video tests.test_dubbing_cli_api tests.test_web_routes_legacy tests.test_simple_web_legacy`（`Ran 88 tests ... OK`）
  - 前端入口语法校验已通过：`node --check src/subtitle_maker/static/app.js src/subtitle_maker/static/js/agentDrawer.js src/subtitle_maker/static/js/dubbingPanel.js`

## 回滚策略

| 阶段 | 回滚方式 |
|---|---|
| 文档阶段 | 直接修改文档。 |
| Contract tests | 测试不影响生产，可保留或调整。 |
| 协议层 | 旧 dict 写法保留兼容，切换失败可回退调用旧函数。 |
| Subtitle/Media/Dubbing | 新模块先灰度接入旧入口，失败时回退旧逻辑。 |
| Agent | 独立入口，可隐藏浮动按钮或关闭 route。 |
| 前端拆分 | 保留旧 `app.js` 入口，逐模块迁移。 |

## 实施门槛

进入代码实现前必须满足：

- Review 1、Review 2、Review 3 全部完成。
- `tasks/todo.md` 中“最终确认后进入代码实现阶段”被明确勾选。
- Agent V1 作为第一个实现阶段时，不允许顺手做协议层、Job Store、前端模块拆分。
- 每个阶段开始前只创建该阶段的最小任务清单。

## 完成定义

每个阶段完成后必须记录：

- 改动范围。
- 验证命令和结果。
- 已知风险。
- 是否影响旧 API/旧 CLI/历史 batch。

## Review 3 结论

迁移路线确认调整为“文档 review -> Agent V1 -> contract/golden tests -> 协议层 -> 领域拆分”。原因是 Agent V1 是独立、低风险、直接提升自用体验的产品增量，不应等到深层架构拆分完成后才交付。

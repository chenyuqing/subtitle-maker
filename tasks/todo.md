# TODO

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
- [ ] HARD-GATE：等用户确认后实施
- [ ] 实施：接入 OmniVoice 作为第二备胎
- [ ] 验证：语法检查 + 定向回归 + 备胎触发样例复核

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

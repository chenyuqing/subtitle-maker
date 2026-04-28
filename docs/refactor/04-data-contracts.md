# 数据协议

日期：2026-04-24

## 目标

统一 Project、Job、Artifact、Manifest、PipelineOptions，避免同一个字段在 Web API、CLI、batch manifest、segment manifest、review redub 中各自维护。

核心原则：

- 创建任务时冻结 options。
- batch manifest 和 segment manifest 都必须保存足够信息，以便历史 batch load 和 review redub 不依赖当前默认值。
- 旧 manifest 缺字段时可以兼容读取，但必须区分“真实字段值”和“legacy inferred 默认值”。

## Project

```python
class Project:
    project_id: str
    name: str
    root_dir: Path
    input_media: Path | None
    source_subtitle: Path | None
    target_lang: str | None
    created_at: str
    updated_at: str
```

说明：

| 字段 | 含义 |
|---|---|
| `project_id` | 本地唯一 ID。 |
| `name` | 用户可读名称，默认来自上传文件名。 |
| `root_dir` | 项目产物根目录。 |
| `input_media` | 当前主媒体文件。 |
| `source_subtitle` | 当前 source.srt。 |
| `target_lang` | 当前目标语言。 |

## Job

```python
class Job:
    job_id: str
    project_id: str
    job_type: Literal["asr", "translate", "dubbing", "export", "long_dubbing"]
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    progress: float
    stage: str
    options: dict
    artifacts: list[Artifact]
    error: JobError | None
    created_at: str
    updated_at: str
```

说明：

| 字段 | 含义 |
|---|---|
| `job_id` | 统一任务 ID，兼容旧 `task_id`。 |
| `job_type` | 任务类型。 |
| `status` | 统一状态，不同任务共用。 |
| `stage` | 当前阶段，例如 `transcribing`、`dubbing:tts`。 |
| `options` | 创建任务时使用的参数快照。 |
| `artifacts` | 当前任务输出产物。 |
| `error` | 结构化错误。 |

## JobError

```python
class JobError:
    code: str
    message: str
    detail: str | None
    recoverable: bool
```

错误码方向：

| 错误码 | 含义 |
|---|---|
| `E-ASR-001` | ASR 或字幕输入没有产生有效字幕。 |
| `E-TRN-001` | 翻译 API key 缺失。 |
| `E-TRN-002` | 翻译 provider 请求失败。 |
| `E-TTS-001` | TTS backend 硬失败。 |
| `E-TTS-002` | TTS 产物无效或过短。 |
| `E-MANIFEST-001` | manifest 缺失或损坏。 |
| `E-FFMPEG-001` | ffmpeg/ffprobe 失败。 |
| `E-AGENT-001` | Agent API key 缺失。 |
| `E-AGENT-002` | Agent provider 请求失败。 |

## Artifact

```python
class Artifact:
    key: str
    path: Path
    media_type: Literal["video", "audio", "subtitle", "manifest", "json", "log"]
    label: str
    public_url: str | None
```

常见 key：

| key | 含义 |
|---|---|
| `output_video` | 最终视频。 |
| `dubbed_vocals` | 配音人声轨。 |
| `source_srt` | 源字幕。 |
| `translated_srt` | 翻译字幕。 |
| `bilingual_srt` | 双语字幕。 |
| `dubbed_final_srt` | 配音最终字幕。 |
| `manifest` | batch 或 segment manifest。 |
| `job_log` | 任务日志。 |

## PipelineOptions

```python
class PipelineOptions:
    target_lang: str
    input_subtitle_mode: Literal["source", "translated"]
    pipeline_version: Literal["v1", "v2"]
    time_ranges: list[TimeRange]
    auto_pick_ranges: bool
    subtitle_layout: SubtitleLayoutOptions
    translation: TranslationOptions
    dubbing: DubbingOptions
    tts: TtsOptions
```

默认值：

| 字段 | 默认 |
|---|---|
| `pipeline_version` | 新任务默认 `v2`；旧 manifest 缺失时标记为 legacy inferred。 |
| `input_subtitle_mode` | `source` |
| `time_ranges` | `[]` |
| `auto_pick_ranges` | `false` |

## SubtitleLayoutOptions

```python
class SubtitleLayoutOptions:
    enable_sentence_split: bool
    enable_short_merge: bool
    short_merge_target_seconds: int
    short_merge_tolerance_seconds: int
    short_merge_gap_seconds: float
```

默认值：

| 字段 | 默认 |
|---|---|
| `enable_sentence_split` | `true` |
| `enable_short_merge` | `false` |
| `short_merge_target_seconds` | `15` |
| `short_merge_tolerance_seconds` | `round(target_seconds / 3)`，至少 1 秒。 |
| `short_merge_gap_seconds` | `1.5` |

兼容规则：

- 历史 `source_short_merge_threshold` 若没有 `source_short_merge_threshold_mode=seconds`，且值落在旧字数阈值区间，UI 显示回退为默认 `15s`。
- ASR 生成字幕和上传 source 字幕必须使用同一套 layout options。

## TranslationOptions

```python
class TranslationOptions:
    provider: Literal["deepseek", "openai_compatible", "local_sakura"]
    base_url: str
    model: str
    rewrite_translation: bool
    api_key_env: str
```

默认值：

| 字段 | 默认 |
|---|---|
| `provider` | `deepseek` |
| `base_url` | `https://api.deepseek.com` |
| `model` | `deepseek-v4-flash` |
| `rewrite_translation` | `true` |
| `api_key_env` | `DEEPSEEK_API_KEY` |

兼容规则：

- `input_subtitle_mode=translated` 时可以跳过翻译，但仍要保存 translation options，供后续 redub 和 batch 回放使用。
- API key 不能写入 manifest。

## DubbingOptions

```python
class DubbingOptions:
    grouped_synthesis: bool
    force_fit_timing: bool
    translated_input_preserve_synthesis_mode: bool
    timing_mode: Literal["strict", "natural"]
    grouping_strategy: Literal["sentence", "legacy"]
```

默认值：

| 字段 | 默认 |
|---|---|
| `grouped_synthesis` | V1 legacy 可为 `true`，V2 默认逐句语义。 |
| `force_fit_timing` | V1 legacy 可为 `true`，V2 默认 `false`。 |
| `translated_input_preserve_synthesis_mode` | review redub 必须为 `true`。 |
| `timing_mode` | `strict` 或从旧 manifest 恢复。 |
| `grouping_strategy` | `sentence` |

兼容规则：

- review redub 必须从 segment manifest 恢复 `grouped_synthesis` 和 `force_fit_timing`，不得因为当前入口默认值改变重跑语义。
- grouped synthesis 的 segment 局部 redub 必须整段重跑，不能只重跑单行。

## TtsOptions

```python
class TtsOptions:
    backend: Literal["index-tts", "qwen", "omni-voice"]
    fallback_backend: Literal["none", "omni-voice"]
    index_tts_api_url: str
    index_tts_via_api: bool
    index_tts_release_after_job: bool
    omnivoice_root: str | None
    omnivoice_python_bin: str | None
    omnivoice_model: str | None
    omnivoice_device: str | None
```

默认值：

| 字段 | 默认 |
|---|---|
| `backend` | `index-tts` |
| `fallback_backend` | `none` |
| `index_tts_api_url` | `http://127.0.0.1:8010` |
| `index_tts_via_api` | `true` |
| `index_tts_release_after_job` | `false` |
| `omnivoice_*` | `None`，不做隐式猜测。 |

兼容规则：

- Qwen3-TTS 可保留为 legacy/experimental backend，但不是产品主链路默认值。
- OmniVoice 只作为配置后触发的备胎，不自动安装、不污染主 Web 环境。

## TimeRange

```python
class TimeRange:
    start: float
    end: float
```

规则：

- `start >= 0`。
- `end > start`。
- 多个 range 在保存前归一化、排序、合并重叠区间。

## Manifest 层级

```text
BatchManifest
  -> schema_version
  -> batch_id
  -> project_id
  -> options: PipelineOptions
  -> segments: list[SegmentManifestSummary]
  -> artifacts: list[Artifact]
  -> review: ReviewSummary

SegmentManifest
  -> schema_version
  -> job_id
  -> segment_index
  -> global_start / global_end
  -> options: PipelineOptions
  -> subtitles: source / translated / final
  -> synthesis_records
  -> artifacts
  -> manual_review
```

## 兼容原则

- 读旧 manifest 时必须补默认值。
- 写新 manifest 时必须包含 `schema_version`。
- save-and-redub 必须从 manifest 恢复 `PipelineOptions`。
- load-batch 不得私自把空字段回退成 Chinese 或 V1。
- artifact 路径必须相对 batch 或 segment root 可解析。
- API 返回不暴露本地敏感路径，除非是本地开发明确需要。

## 字段恢复规则

| 字段 | 恢复优先级 |
|---|---|
| `target_lang` | segment manifest -> batch manifest -> job options；全部缺失则报 legacy metadata missing，不默认 Chinese。 |
| `pipeline_version` | segment manifest -> batch manifest -> job options；旧 manifest 缺失可标记 `legacy_inferred=v1`。 |
| `input_subtitle_mode` | segment manifest `input_srt_kind` -> batch manifest `input_srt_kind/subtitle_mode` -> `source`。 |
| `rewrite_translation` | segment manifest -> batch manifest -> translation defaults。 |
| `grouped_synthesis` | segment manifest 显式字段 -> 从 synthesis records 推断 -> batch options。 |
| `force_fit_timing` | segment manifest 显式字段 -> pipeline/version 兼容推断 -> batch options。 |
| `short_merge` | batch options -> legacy threshold compatibility -> defaults。 |
| `tts backend` | segment manifest -> batch options -> `index-tts`。 |

## Review 2 结论

数据协议必须覆盖会影响“重新执行结果”的字段，而不只是展示字段。`target_lang`、`pipeline_version`、字幕 layout、翻译配置、合成模式、TTS backend、time ranges 都属于可重放配置，必须进入 `PipelineOptions` 或其子 options。

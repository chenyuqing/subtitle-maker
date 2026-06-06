# Subtitle Maker — 项目架构图

## 整体分层架构

```mermaid
graph TB
    subgraph Entry["🚪 入口层"]
        CLI["cli.py<br/>命令行工具"]
        WEB["web.py<br/>Web 服务启动"]
    end

    subgraph Frontend["🖥️ 前端 SPA"]
        direction TB
        IDX["index.html<br/>主页面"]
        P1["Panel 1: 上传"]
        P2["Panel 2: 转写"]
        P3["Panel 3: 编辑/导出"]
        P4["Panel 4: 配音 V1"]
        P5["Panel 5: 配音 V2"]
        AGENT["AgentDrawer<br/>AI 助手"]
        VIDEO["VideoPlayer<br/>字幕叠加播放"]
        LS["localStorage<br/>API Key / 主题 / 配置"]
        IDX --> P1 --> P2 --> P3 --> P4 --> P5
        IDX --> AGENT
        IDX --> VIDEO
    end

    subgraph API["🌐 API 层 (FastAPI)"]
        direction TB
        MAIN["app/main.py<br/>应用工厂"]
        
        subgraph Routes["路由模块"]
            PROJ["routes/projects.py<br/>上传 / 流媒体"]
            SUB["routes/subtitles.py<br/>转写同步/异步"]
            TRANS["routes/translation.py<br/>翻译"]
            EXPORT["routes/exports.py<br/>导出/下载/分段"]
            JOBS["routes/jobs.py<br/>状态/取消/模型管理"]
        end
        
        subgraph Extra["扩展 API"]
            DUB_API["dubbing_cli_api.py<br/>配音流程 API"]
            STREAM_API["streaming_api.py<br/>流式 ASR API"]
            AGENT_API["agent_api.py<br/>AI 助手 API"]
        end
        
        MAIN --> Routes
        MAIN --> Extra
    end

    subgraph Core["⚙️ 核心服务层"]
        TRANS_ENGINE["Translator<br/>DeepSeek 翻译"]
        ASR_ENGINE["SubtitleGenerator<br/>Qwen3-ASR 语音识别"]
        DUB_PIPELINE["Dubbing Pipeline<br/>配音流程编排"]
        STREAM_MGR["StreamingSessionManager<br/>流式 ASR 会话"]
        AGENT_CLIENT["OpenAICompatibleChatClient<br/>LLM 客户端"]
    end

    subgraph Domain["📦 领域层"]
        direction TB
        subgraph DUB_DOMAIN["domains/dubbing/"]
            DUB_PIPE["pipeline.py<br/>逐段合成 + 对齐"]
            DUB_ALIGN["alignment.py<br/>变速/裁剪"]
            DUB_REF["references.py<br/>参考音频提取"]
            DUB_REVIEW["review.py<br/>重配参数解析"]
        end
        subgraph SUB_DOMAIN["domains/subtitles/"]
            SRT_UTIL["srt.py<br/>SRT 工具"]
            TIMELINE["timeline.py<br/>时间分配"]
            SENT_SPLIT["sentence_split.py<br/>断句"]
            SHORT_MRG["short_merge.py<br/>短句合并"]
        end
        subgraph MEDIA_DOMAIN["domains/media/"]
            PROBE["probe.py<br/>音频探测"]
            SEGMENT["segment.py<br/>音频分段"]
            COMPOSE["compose.py<br/>混音/合成"]
        end
    end

    subgraph Backend["🔌 后端服务层"]
        direction TB
        
        subgraph TTS["TTS 后端"]
            TTS_BASE["backends/base.py<br/>TtsBackend (ABC)"]
            INDEX_TTS["backends/index_tts.py<br/>IndexTtsBackend"]
            OMNI_VOICE["backends/omni_voice.py<br/>OmniVoiceBackend"]
            TTS_BASE --> INDEX_TTS
            TTS_BASE --> OMNI_VOICE
        end
        
        subgraph Jobs["任务系统"]
            JOB_MODEL["jobs/models.py<br/>JobRecord"]
            JOB_STORE["jobs/store.py<br/>TaskStore (RLock)"]
            JOB_CMD["jobs/command_builder.py<br/>CLI 构建"]
            JOB_RECOVER["jobs/recovery.py<br/>任务恢复"]
        end
        
        subgraph Manifest["清单系统"]
            MAN_SCHEMA["manifests/schema.py<br/>数据结构"]
            MAN_RW["manifests/readwrite.py<br/>读写工具"]
        end
        
        CORE_FFMPEG["core/ffmpeg.py<br/>FFmpeg 子进程"]
        CORE_LLM["core/llm_client.py<br/>DeepSeek SDK"]
    end

    subgraph External["🌍 外部服务"]
        DEEPSEEK["DeepSeek API<br/>deepseek-v4-flash"]
        INDEXTTS_SVC["Index-TTS Server<br/>localhost:8010"]
        OMNIVOICE_SVC["OmniVoice Server<br/>localhost:8020"]
    end

    subgraph Models["🧠 本地模型"]
        QWEN_ASR["Qwen3-ASR-0.6B<br/>语音识别"]
        QWEN_FA["Qwen3-ForcedAligner<br/>字级对齐"]
        QWEN_TTS["Qwen3-TTS<br/>qwen_tts/ 内嵌"]
    end

    %% 数据流连接
    Frontend -->|HTTP/SSE/WS| API
    API --> Core
    Core --> Domain
    Core --> Backend
    Core --> External
    DUB_PIPELINE -->|子进程| Domain
    TTS_BASE --> INDEXTTS_SVC
    TTS_BASE --> OMNIVOICE_SVC
    ASR_ENGINE --> QWEN_ASR
    ASR_ENGINE --> QWEN_FA
    TRANS_ENGINE --> DEEPSEEK
    AGENT_CLIENT --> DEEPSEEK
    DUB_PIPELINE --> TTS
    DUB_PIPELINE --> Manifest
```

## 数据流

```mermaid
sequenceDiagram
    participant U as 👤 用户
    participant FE as 🖥️ 前端 SPA
    participant API as 🌐 FastAPI
    participant ASR as 🧠 Qwen3-ASR
    participant TR as 🤖 DeepSeek 翻译
    participant TTS as 🔊 TTS 后端
    participant FS as 💾 文件系统

    rect rgb(240,248,255)
    Note over U,FS: 流程 A — 字幕生成
    U->>FE: 上传视频/音频
    FE->>API: POST /upload
    API->>FS: 保存 uploads/{uuid}.ext
    U->>FE: 配置语言 → 开始转写
    FE->>API: POST /transcribe
    API->>ASR: 加载模型, 逐块转写
    ASR-->>API: 逐块返回字幕
    API->>FS: 写入 outputs/*.srt
    API-->>FE: 返回字幕列表
    FE->>FE: 轮询 GET /status/{id}
    U->>FE: 选择目标语言 → 翻译
    FE->>API: POST /translate
    API->>TR: translate_batch()
    TR-->>API: 翻译后字幕
    API-->>FE: 双语字幕显示
    FE->>API: POST /export
    API-->>FE: 下载 SRT 文件
    end

    rect rgb(255,248,240)
    Note over U,FS: 流程 B — 自动配音
    U->>FE: 配置配音参数
    FE->>API: POST /dubbing/auto/start
    API->>FS: 创建 batch 目录 + manifest
    API->>API: 启动子进程 dub_long_video.py
    API-->>FE: task_id
    loop 轮询进度
        FE->>API: GET /dubbing/auto/task/{id}
        API-->>FE: 进度/状态更新
    end
    Note over API,TTS: 子进程执行
    API->>ASR: 转写 (若无 SRT)
    API->>TR: 翻译 (若无译文)
    API->>TTS: 逐段合成语音
    TTS-->>API: WAV 音频段
    API->>FS: 拼接 + 混音 → 输出
    FE->>API: GET /dubbing/auto/download/...
    API-->>FE: 下载配音视频
    end
```

## 模块依赖关系

```mermaid
graph LR
    subgraph 路由
        PROJ["projects.py"]
        SUB["subtitles.py"]
        TRANS["translation.py"]
        EXPORT["exports.py"]
        JOBS["jobs.py"]
        DUB["dubbing_cli_api.py"]
        STREAM["streaming_api.py"]
        AGT["agent_api.py"]
    end

    subgraph 核心
        TC["transcriber.py"]
        TL["translator.py"]
        DP["dubbing pipeline"]
        SA["streaming_asr.py"]
        LC["llm_client.py"]
    end

    subgraph 领域
        SD["subtitles/*"]
        MD["media/*"]
        DD["dubbing/*"]
        FF["ffmpeg.py"]
    end

    subgraph 后端
        IT["index_tts.py"]
        OV["omni_voice.py"]
        TS["TaskStore"]
        MF["manifests/*"]
    end

    SUB --> TC
    TRANS --> TL
    STREAM --> SA
    AGT --> LC
    DUB --> DP
    DUB --> TS
    DUB --> MF
    
    TC --> FF
    TC --> SD
    DP --> MD
    DP --> DD
    DP --> IT
    DP --> OV
    DP --> MF
    TL --> LC
    
    EXPORT --> SD
    EXPORT --> MD
    PROJ --> FF
```

## 关键设计模式

| 模式 | 位置 | 说明 |
|---|---|---|
| **全局单例** | `legacy_runtime.py`, `streaming_asr.py` | ASR 模型懒加载,加锁保证线程安全 |
| **后台任务** | `web.py`, `dubbing_cli_api.py` | CPU 密集操作通过 `asyncio.to_thread()` 异步化 |
| **子进程编排** | `dubbing_cli_api.py` → `tools/dub_long_video.py` | 配音流程以独立子进程运行,通过 manifest JSON 通信 |
| **轮询模式** | 前端 JS → `GET /status/`, `GET /dubbing/auto/task/` | 前端定时轮询后端任务状态 |
| **策略模式** | `backends/base.py` → `index_tts.py`, `omni_voice.py` | TTS 后端抽象基类,可插拔切换 |
| **清单持久化** | `manifests/` | 配音任务状态以 JSON 文件持久化,支持恢复/重配 |
| **线程安全存储** | `jobs/store.py` → `TaskStore(RLock)` | 配音任务使用 RLock 保护的字典存储 |
| **localStorage** | 前端 | API Key、主题、TTS 后端选择等用户配置持久化在浏览器 |

## 目录职责速览

```
src/subtitle_maker/
├── app/             FastAPI 应用 + 路由 (HTTP 层)
├── backends/        TTS 后端抽象 + 实现 (Index-TTS, OmniVoice)
├── core/            FFmpeg 封装 + LLM SDK 客户端
├── domains/         纯领域逻辑 (字幕/媒体/配音)
├── jobs/            任务记录 + 线程安全存储 + CLI 构建
├── manifests/       配音批次的 JSON 清单读写
├── qwen_tts/        内嵌 Qwen3-TTS 推理代码
├── static/          前端 CSS/JS
├── templates/       Jinja2 HTML 模板
├── cli.py           命令行入口
├── web.py           Web 服务入口
├── transcriber.py   Qwen3-ASR 封装
├── translator.py    DeepSeek 翻译客户端
├── dubbing_cli_api.py  配音 REST API (~1500 行)
├── streaming_asr.py     流式 ASR 会话管理
├── streaming_api.py     流式 ASR HTTP 路由
└── agent_api.py         产品内 AI 助手
```

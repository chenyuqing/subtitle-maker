/**
 * 初始化独立 OmniVoice Auto Dub 面板。
 * 这条链路不复用 4.Auto Dubbing 的 backend 状态，只读取当前项目上下文和翻译配置。
 */
export function setupOmnivoiceDubbingPanel(deps) {
    const byId = (id) => document.getElementById(id);
    const panelEl = byId('panel-auto-dub-omnivoice');
    if (!panelEl) return;

    const {
        buildAutoDubElapsedLabel,
        describeAutoStage,
        formatLineProgress,
        formatEtaAsSegmentProgress,
        getProjectDubbingContext,
        getTranslateApiKey,
        getTranslateBaseUrl,
        getTranslateModel,
    } = deps;

    const projectMediaEl = byId('omnivoice-project-media');
    const projectTaskEl = byId('omnivoice-project-task');
    const projectReadinessEl = byId('omnivoice-project-readiness');
    const projectNoteEl = byId('omnivoice-project-note');
    const projectSourceCountEl = byId('omnivoice-project-source-count');
    const projectTranslatedCountEl = byId('omnivoice-project-translated-count');
    const subtitleModeSelect = byId('omnivoice-subtitle-mode');
    const sourceLangSelect = byId('omnivoice-source');
    const targetLangSelect = byId('omnivoice-target');
    const translateSystemPromptInput = byId('omnivoice-translate-system-prompt');
    const sharedKeyNoteEl = byId('omnivoice-shared-key-note');
    const backendNoteEl = byId('omnivoice-backend-note');
    const speakerRefListEl = byId('omnivoice-speaker-ref-list');
    const speakerRefHintEl = byId('omnivoice-speaker-ref-hint');
    const startBtn = byId('start-omnivoice-dub-btn');
    const batchSelect = byId('omnivoice-load-batch-select');
    const refreshBatchesBtn = byId('omnivoice-refresh-batches-btn');
    const loadBatchBtn = byId('omnivoice-load-batch-btn');
    const batchHintEl = byId('omnivoice-batch-hint');
    const statusContainer = byId('omnivoice-status-container');
    const progressFill = byId('omnivoice-progress-fill');
    const statusText = byId('omnivoice-status-text');
    const taskLabel = byId('omnivoice-task-id');
    const lineProgressEl = byId('omnivoice-line-progress');
    const etaEl = byId('omnivoice-eta');
    const resultsContainer = byId('omnivoice-results');
    const downloadLinks = resultsContainer?.querySelector('.download-links') || null;

    const SUBTITLE_MODE_KEY = 'sm_omnivoiceSubtitleMode';
    const FIXED_SPEAKER_REF_TEXT = '你好，这是我的声音音色，很高兴为你进行配音服务。';
    let pollTimer = null;
    let backendPollTimer = null;
    let autoDubStartedAtMs = null;
    let omnivoiceBackendReady = false;
    let speakerRefFiles = new Map();

    /**
     * 读取当前项目上下文。
     */
    function readProjectContext() {
        if (typeof getProjectDubbingContext === 'function') {
            return getProjectDubbingContext() || {};
        }
        return {};
    }

    /**
     * 统计字幕里的 speaker 数量，便于当前项目状态更直观。
     */
    function countSpeakers(rows) {
        const speakerSet = new Set();
        (Array.isArray(rows) ? rows : []).forEach((row) => {
            const speakerId = String(row?.speaker_id || '').trim();
            if (speakerId) {
                speakerSet.add(speakerId);
            }
        });
        return speakerSet.size;
    }

    /**
     * 根据当前 subtitle_mode 选出本轮真正用于 speaker 映射的字幕集合。
     */
    function getEffectiveSubtitleRows(projectContext) {
        const sourceItems = Array.isArray(projectContext?.sourceSubtitles) ? projectContext.sourceSubtitles : [];
        const translatedItems = Array.isArray(projectContext?.translatedSubtitles) ? projectContext.translatedSubtitles : [];
        const preferredMode = subtitleModeSelect?.value || '';
        if (preferredMode === 'translated' && translatedItems.length > 0) {
            return translatedItems;
        }
        if (preferredMode === 'source' && sourceItems.length > 0) {
            return sourceItems;
        }
        return translatedItems.length > 0 ? translatedItems : sourceItems;
    }

    /**
     * 提取稳定 speaker 列表，和 4 号面板一样完全以字幕 speaker_id 为准。
     */
    function getDetectedSpeakerIds(projectContext = readProjectContext()) {
        const rows = getEffectiveSubtitleRows(projectContext);
        const ordered = [];
        const seen = new Set();
        (Array.isArray(rows) ? rows : []).forEach((row) => {
            const speakerId = String(row?.speaker_id || '').trim() || 'Speaker 1';
            if (!seen.has(speakerId)) {
                seen.add(speakerId);
                ordered.push(speakerId);
            }
        });
        return ordered;
    }

    /**
     * 渲染 strict speaker 参考音上传列表。
     */
    function renderSpeakerReferenceInputs() {
        if (!speakerRefListEl || !speakerRefHintEl) return;
        const projectContext = readProjectContext();
        const speakerIds = getDetectedSpeakerIds(projectContext);
        const nextMap = new Map();
        speakerRefListEl.innerHTML = '';

        if (speakerIds.length === 0) {
            speakerRefHintEl.textContent = '当前项目字幕里还没有 speaker 信息；请上传带 Speaker 前缀或 speaker_id 的字幕。';
            return;
        }

        speakerIds.forEach((speakerId) => {
            const existingFile = speakerRefFiles.get(speakerId) || null;
            if (existingFile) {
                nextMap.set(speakerId, existingFile);
            }

            const row = document.createElement('div');
            row.className = 'omnivoice-speaker-ref-row';

            const meta = document.createElement('div');
            meta.className = 'omnivoice-speaker-ref-meta';
            const title = document.createElement('div');
            title.className = 'omnivoice-speaker-ref-title';
            title.textContent = speakerId;
            const copy = document.createElement('div');
            copy.className = 'omnivoice-speaker-ref-copy';
            copy.textContent = `参考文本固定为：${FIXED_SPEAKER_REF_TEXT}`;
            meta.appendChild(title);
            meta.appendChild(copy);

            const inputWrap = document.createElement('div');
            const input = document.createElement('input');
            input.type = 'file';
            input.accept = 'audio/*,.wav,.mp3,.m4a,.aac,.flac,.ogg';
            input.className = 'omnivoice-speaker-ref-input';
            input.dataset.speakerId = speakerId;
            const status = document.createElement('span');
            status.className = 'omnivoice-speaker-ref-status';
            status.textContent = existingFile ? `已选择：${existingFile.name}` : '未上传参考音';
            input.addEventListener('change', () => {
                const file = input.files && input.files[0] ? input.files[0] : null;
                if (file) {
                    speakerRefFiles.set(speakerId, file);
                    status.textContent = `已选择：${file.name}`;
                } else {
                    speakerRefFiles.delete(speakerId);
                    status.textContent = '未上传参考音';
                }
                renderSpeakerRefHint();
            });
            inputWrap.appendChild(input);
            inputWrap.appendChild(status);

            row.appendChild(meta);
            row.appendChild(inputWrap);
            speakerRefListEl.appendChild(row);
        });

        speakerRefFiles = nextMap;
        renderSpeakerRefHint();
    }

    /**
     * 刷新 speaker 参考音上传提示，明确告诉用户还缺谁。
     */
    function renderSpeakerRefHint() {
        if (!speakerRefHintEl) return;
        const speakerIds = getDetectedSpeakerIds();
        if (speakerIds.length === 0) {
            speakerRefHintEl.textContent = '当前项目字幕里还没有 speaker 信息；请上传带 Speaker 前缀或 speaker_id 的字幕。';
            return;
        }
        const missing = speakerIds.filter((speakerId) => !speakerRefFiles.get(speakerId));
        if (missing.length === 0) {
            speakerRefHintEl.textContent = `已就绪：${speakerIds.length} 个 speaker 都已上传参考音。`;
            return;
        }
        speakerRefHintEl.textContent = `还缺 ${missing.length} 个 speaker 参考音：${missing.join('、')}`;
    }

    /**
     * strict 模式校验：检测到的每个 speaker 都必须上传参考音。
     */
    function validateSpeakerReferenceUploads() {
        const speakerIds = getDetectedSpeakerIds();
        if (speakerIds.length === 0) {
            throw new Error('当前项目字幕里没有稳定 speaker 信息，OmniVoice strict 模式无法建立参考音映射。');
        }
        const missing = speakerIds.filter((speakerId) => !speakerRefFiles.get(speakerId));
        if (missing.length > 0) {
            throw new Error(`OmniVoice 需要为每个 speaker 上传参考音，当前缺少：${missing.join('、')}`);
        }
        return speakerIds;
    }

    /**
     * 同步 Start 按钮状态，避免后端未 ready 时误点。
     */
    function syncStartButtonState() {
        if (!startBtn) return;
        startBtn.disabled = !omnivoiceBackendReady;
    }

    /**
     * 轮询独立 OmniVoice 后端模型就绪状态。
     */
    async function refreshBackendStatus({ scheduleRetry = true } = {}) {
        try {
            const res = await fetch('/omnivoice/auto/backend-status');
            const data = res.ok ? await res.json() : { ok: false, detail: `HTTP ${res.status}` };
            omnivoiceBackendReady = !!data?.ready;
            if (backendNoteEl) {
                if (omnivoiceBackendReady) {
                    backendNoteEl.textContent = 'OmniVoice 后端已就绪，可以开始配音。';
                } else {
                    backendNoteEl.textContent = `OmniVoice 后端加载中：${data?.detail || data?.status || 'loading'}`;
                }
            }
            syncStartButtonState();
            if (omnivoiceBackendReady && backendPollTimer) {
                clearInterval(backendPollTimer);
                backendPollTimer = null;
            } else if (!omnivoiceBackendReady && scheduleRetry && !backendPollTimer) {
                backendPollTimer = setInterval(() => {
                    refreshBackendStatus({ scheduleRetry: false }).catch(() => {});
                }, 5000);
            }
            return data;
        } catch (error) {
            omnivoiceBackendReady = false;
            if (backendNoteEl) {
                backendNoteEl.textContent = `OmniVoice 后端状态检查失败：${error.message}`;
            }
            syncStartButtonState();
            if (scheduleRetry && !backendPollTimer) {
                backendPollTimer = setInterval(() => {
                    refreshBackendStatus({ scheduleRetry: false }).catch(() => {});
                }, 5000);
            }
            return { ok: false, ready: false, detail: error.message };
        }
    }

    /**
     * 当前项目可用字幕决定可选策略，和 4 号面板保持同样的“直白”表达。
     */
    function buildProjectSubtitleOptions(projectContext) {
        const sourceItems = Array.isArray(projectContext?.sourceSubtitles) ? projectContext.sourceSubtitles : [];
        const translatedItems = Array.isArray(projectContext?.translatedSubtitles) ? projectContext.translatedSubtitles : [];
        const options = [];
        if (translatedItems.length > 0) {
            options.push({
                value: 'translated',
                label: `使用当前译文直接配音（${translatedItems.length} 行）`,
            });
        }
        if (sourceItems.length > 0) {
            options.push({
                value: 'source',
                label: `使用当前原字幕先翻译后配音（${sourceItems.length} 行）`,
            });
        }
        return options;
    }

    /**
     * 同步当前项目摘要与可用性文案。
     */
    function renderProjectContextSummary() {
        const projectContext = readProjectContext();
        const mediaName = projectContext?.mediaOriginalFilename || projectContext?.mediaFilename || '';
        const sourceSubtitles = Array.isArray(projectContext?.sourceSubtitles) ? projectContext.sourceSubtitles : [];
        const translatedSubtitles = Array.isArray(projectContext?.translatedSubtitles) ? projectContext.translatedSubtitles : [];
        const sourceCount = sourceSubtitles.length;
        const translatedCount = translatedSubtitles.length;
        const speakerCount = Math.max(countSpeakers(sourceSubtitles), countSpeakers(translatedSubtitles));

        if (projectMediaEl) {
            projectMediaEl.textContent = mediaName || '未上传媒体';
        }
        if (projectTaskEl) {
            projectTaskEl.textContent = projectContext?.taskId || '未生成';
        }
        if (projectSourceCountEl) {
            projectSourceCountEl.textContent = `${sourceCount} 行`;
        }
        if (projectTranslatedCountEl) {
            projectTranslatedCountEl.textContent = `${translatedCount} 行`;
        }
        if (projectReadinessEl) {
            projectReadinessEl.textContent = mediaName && (sourceCount > 0 || translatedCount > 0)
                ? `可复用 · ${speakerCount} speaker`
                : '缺少媒体或字幕';
        }
        if (projectNoteEl) {
            if (!mediaName) {
                projectNoteEl.textContent = '请先在 1.Upload Video + Optional SRT 中上传视频。OmniVoice 会直接复用当前项目上下文，不再单独上传。';
            } else if (sourceCount === 0 && translatedCount === 0) {
                projectNoteEl.textContent = '当前项目还没有可用字幕。OmniVoice 只能复用当前项目字幕上下文，不能像 4.Auto Dubbing 一样重新起一条 index-tts 链路。';
            } else {
                projectNoteEl.textContent = 'OmniVoice 会优先复用 translated 字幕，否则翻译 source 字幕；speaker 会从字幕自动识别，参考音需要你逐个上传并严格映射。';
            }
        }
        if (sharedKeyNoteEl) {
            const key = getTranslateApiKey ? getTranslateApiKey() : '';
            const baseUrl = getTranslateBaseUrl ? getTranslateBaseUrl() : '';
            const model = getTranslateModel ? getTranslateModel() : '';
            if (key) {
                sharedKeyNoteEl.textContent = `当前使用翻译 API 配置：${baseUrl || '默认 Base URL'} / ${model || '默认 Model'}。OmniVoice 只共享翻译配置，不共享 4 号面板的 backend 状态。`;
            } else {
                sharedKeyNoteEl.textContent = '如果当前项目需要翻译 source 字幕，将复用左侧 Translation API 配置或后端环境变量。';
            }
        }
        if (subtitleModeSelect) {
            const previous = subtitleModeSelect.value;
            const options = buildProjectSubtitleOptions(projectContext);
            subtitleModeSelect.innerHTML = '';
            options.forEach((option) => {
                const node = document.createElement('option');
                node.value = option.value;
                node.textContent = option.label;
                subtitleModeSelect.appendChild(node);
            });
            const values = options.map((item) => item.value);
            if (values.includes(previous)) {
                subtitleModeSelect.value = previous;
            } else if (values.includes('translated')) {
                subtitleModeSelect.value = 'translated';
            } else if (values.includes('source')) {
                subtitleModeSelect.value = 'source';
            } else {
                subtitleModeSelect.value = '';
            }
        }
        renderSpeakerReferenceInputs();
    }

    /**
     * 读取 subtitle_mode 的本地浏览器记忆。
     */
    function restoreSubtitleMode() {
        if (!subtitleModeSelect) return;
        const saved = localStorage.getItem(SUBTITLE_MODE_KEY);
        if (saved && ['translated', 'source'].includes(saved)) {
            subtitleModeSelect.value = saved;
        }
        subtitleModeSelect.addEventListener('change', () => {
            localStorage.setItem(SUBTITLE_MODE_KEY, subtitleModeSelect.value);
        });
    }

    /**
     * 构造当前项目启动请求。
     */
    function buildCurrentProjectRequest() {
        const projectContext = readProjectContext();
        const mediaFilename = String(projectContext?.mediaFilename || '').trim();
        const sourceSubtitles = Array.isArray(projectContext?.sourceSubtitles) ? projectContext.sourceSubtitles : [];
        const translatedSubtitles = Array.isArray(projectContext?.translatedSubtitles) ? projectContext.translatedSubtitles : [];
        if (!mediaFilename) {
            throw new Error('OmniVoice 需要先上传视频，再从当前项目启动。');
        }
        if (sourceSubtitles.length === 0 && translatedSubtitles.length === 0) {
            throw new Error('OmniVoice 需要当前项目里已有字幕。');
        }

        const formData = new FormData();
        formData.append('filename', mediaFilename);
        formData.append('original_filename', projectContext?.mediaOriginalFilename || mediaFilename);
        formData.append('task_id', projectContext?.taskId || '');
        formData.append('source_subtitles_json', JSON.stringify(sourceSubtitles));
        formData.append('translated_subtitles_json', JSON.stringify(translatedSubtitles));
        formData.append('subtitle_mode', subtitleModeSelect?.value || 'source');
        formData.append('source_lang', sourceLangSelect?.value || 'auto');
        formData.append('target_lang', targetLangSelect?.value || 'Chinese');
        formData.append('api_key', getTranslateApiKey ? getTranslateApiKey() : '');
        formData.append('translate_base_url', getTranslateBaseUrl ? getTranslateBaseUrl() : '');
        formData.append('translate_model', getTranslateModel ? getTranslateModel() : '');
        formData.append('translate_system_prompt', translateSystemPromptInput?.value.trim() || '');
        const speakerIds = validateSpeakerReferenceUploads();
        formData.append('speaker_ref_speaker_ids_json', JSON.stringify(speakerIds));
        speakerIds.forEach((speakerId) => {
            const file = speakerRefFiles.get(speakerId);
            if (file) {
                formData.append('speaker_ref_files', file, file.name);
            }
        });

        return {
            endpoint: '/omnivoice/auto/start-from-project',
            formData,
        };
    }

    /**
     * 统一渲染下载链接。
     */
    function renderResults(data) {
        if (!resultsContainer || !downloadLinks) return;
        const artifacts = Array.isArray(data?.artifacts) ? data.artifacts : [];
        downloadLinks.innerHTML = '';
        artifacts.forEach((artifact, index) => {
            if (!artifact?.url) return;
            const link = document.createElement('a');
            link.href = artifact.url;
            link.className = index === 0 ? 'primary-btn' : 'secondary-btn';
            link.textContent = artifact.label || artifact.key || 'Download';
            link.style.display = 'block';
            link.style.textAlign = 'center';
            downloadLinks.appendChild(link);
        });
        resultsContainer.style.display = 'block';
    }

    /**
     * 更新状态区，兼容轮询和恢复任务。
     */
    function renderTaskState(data) {
        if (!statusContainer) return;
        statusContainer.style.display = 'block';
        if (progressFill && typeof data?.progress === 'number') {
            progressFill.style.width = `${Math.max(0, Math.min(100, data.progress))}%`;
        }
        if (taskLabel && (data?.short_id || data?.id)) {
            taskLabel.textContent = `Task · ${(data.short_id || data.id.split('_')[0]).toUpperCase()}`;
        }
        if (lineProgressEl) {
            const processed = data?.processed_segments ?? 0;
            const total = data?.total_segments ?? 0;
            lineProgressEl.textContent = typeof formatLineProgress === 'function'
                ? formatLineProgress(processed, total)
                : `Segments ${processed}/${total || 0}`;
        }
        if (etaEl) {
            const elapsedLabel = typeof buildAutoDubElapsedLabel === 'function'
                ? buildAutoDubElapsedLabel(data, autoDubStartedAtMs)
                : '';
            etaEl.textContent = elapsedLabel || (typeof formatEtaAsSegmentProgress === 'function'
                ? formatEtaAsSegmentProgress(data?.processed_segments ?? 0, data?.total_segments ?? 0)
                : 'ETA —');
        }
        if (statusText) {
            if (data?.status === 'failed') {
                statusText.textContent = `Failed: ${data?.error || 'Unknown error'}`;
                statusText.className = 'status-text error';
            } else {
                const stageLabel = typeof describeAutoStage === 'function'
                    ? describeAutoStage(data?.stage || data?.status || '')
                    : (data?.stage || 'running');
                statusText.textContent = stageLabel;
                statusText.className = `status-text ${data?.status === 'completed' ? 'success' : ''}`.trim();
            }
        }
        if (data?.status === 'completed') {
            renderResults(data);
        }
    }

    /**
     * 轮询 OmniVoice 任务状态。
     */
    function pollStatus(taskId) {
        if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
        }
        pollTimer = setInterval(async () => {
            try {
                const res = await fetch(`/omnivoice/auto/status/${taskId}`);
                if (!res.ok) {
                    throw new Error('Status poll failed');
                }
                const data = await res.json();
                renderTaskState(data);
                if (data?.status === 'completed' || data?.status === 'failed') {
                    clearInterval(pollTimer);
                    pollTimer = null;
                    startBtn && (startBtn.disabled = false);
                    loadBatchBtn && (loadBatchBtn.disabled = false);
                    refreshBatchesBtn && (refreshBatchesBtn.disabled = false);
                }
            } catch (error) {
                clearInterval(pollTimer);
                pollTimer = null;
                if (statusText) {
                    statusText.textContent = `Polling Error: ${error.message}`;
                    statusText.className = 'status-text error';
                }
                startBtn && (startBtn.disabled = false);
                loadBatchBtn && (loadBatchBtn.disabled = false);
                refreshBatchesBtn && (refreshBatchesBtn.disabled = false);
            }
        }, 1200);
    }

    /**
     * 拉取可恢复任务列表。
     */
    async function refreshBatches() {
        if (!batchHintEl || !batchSelect) return;
        batchHintEl.textContent = '正在加载 OmniVoice 结果文件夹列表...';
        try {
            const res = await fetch('/omnivoice/auto/batches');
            if (!res.ok) {
                throw new Error('Failed to load batches');
            }
            const data = await res.json();
            const items = Array.isArray(data?.items) ? data.items : [];
            batchSelect.innerHTML = '<option value="">选择已生成结果文件夹</option>';
            items.forEach((item) => {
                const option = document.createElement('option');
                option.value = item.batch_id || item.task_id || '';
                option.textContent = `${item.batch_id || item.task_id || 'batch'} · ${item.project_filename || 'unknown'} · ${item.status || 'unknown'}`;
                batchSelect.appendChild(option);
            });
            batchHintEl.textContent = items.length > 0
                ? `已找到 ${items.length} 个 OmniVoice 结果文件夹`
                : '当前没有可加载的 OmniVoice 结果文件夹';
        } catch (error) {
            batchHintEl.textContent = `加载失败：${error.message}`;
        }
    }

    /**
     * 从磁盘恢复一个已有结果。
     */
    async function loadBatch() {
        if (!batchSelect || !batchSelect.value) {
            if (batchHintEl) {
                batchHintEl.textContent = '请先选择一个 OmniVoice 结果文件夹';
            }
            return;
        }
        if (loadBatchBtn) loadBatchBtn.disabled = true;
        if (refreshBatchesBtn) refreshBatchesBtn.disabled = true;
        try {
            const formData = new FormData();
            formData.append('batch_id', batchSelect.value);
            const res = await fetch('/omnivoice/auto/load-batch', {
                method: 'POST',
                body: formData,
            });
            const data = await res.json();
            if (!res.ok) {
                throw new Error(data.detail || 'Failed to load OmniVoice batch');
            }
            renderTaskState(data);
            renderResults(data);
            if (batchHintEl) {
                batchHintEl.textContent = `已加载 ${data.project_filename || batchSelect.value}`;
            }
        } catch (error) {
            if (batchHintEl) {
                batchHintEl.textContent = `加载失败：${error.message}`;
            }
        } finally {
            if (loadBatchBtn) loadBatchBtn.disabled = false;
            if (refreshBatchesBtn) refreshBatchesBtn.disabled = false;
        }
    }

    /**
     * 开始独立 OmniVoice 任务。
     */
    async function startTask() {
        try {
            const backendStatus = await refreshBackendStatus({ scheduleRetry: false });
            if (!backendStatus?.ready) {
                throw new Error(backendStatus?.detail || 'OmniVoice backend is still loading');
            }
            const request = buildCurrentProjectRequest();
            if (startBtn) startBtn.disabled = true;
            if (loadBatchBtn) loadBatchBtn.disabled = true;
            if (refreshBatchesBtn) refreshBatchesBtn.disabled = true;
            if (resultsContainer) resultsContainer.style.display = 'none';
            if (statusContainer) statusContainer.style.display = 'block';
            if (statusText) {
                statusText.textContent = 'Initializing...';
                statusText.className = 'status-text';
            }
            if (progressFill) {
                progressFill.style.width = '8%';
            }
            autoDubStartedAtMs = Date.now();
            const res = await fetch(request.endpoint, {
                method: 'POST',
                body: request.formData,
            });
            const data = await res.json();
            if (!res.ok) {
                throw new Error(data.detail || 'Failed to start OmniVoice task');
            }
            renderTaskState(data);
            pollStatus(data.task_id);
        } catch (error) {
            if (statusText) {
                statusText.textContent = `Failed: ${error.message}`;
                statusText.className = 'status-text error';
            }
            if (startBtn) startBtn.disabled = false;
            if (loadBatchBtn) loadBatchBtn.disabled = false;
            if (refreshBatchesBtn) refreshBatchesBtn.disabled = false;
        }
    }

    /**
     * 监听项目变化，保持摘要和提示始终同步。
     */
    function syncProjectUi() {
        renderProjectContextSummary();
    }

    if (subtitleModeSelect) {
        restoreSubtitleMode();
        subtitleModeSelect.addEventListener('change', () => {
            renderSpeakerReferenceInputs();
        });
    }
    if (startBtn) {
        startBtn.addEventListener('click', startTask);
    }
    if (refreshBatchesBtn) {
        refreshBatchesBtn.addEventListener('click', refreshBatches);
    }
    if (loadBatchBtn) {
        loadBatchBtn.addEventListener('click', loadBatch);
    }
    window.addEventListener('subtitle-maker:project-context-changed', syncProjectUi);
    window.addEventListener('subtitle-maker:translate-config-changed', syncProjectUi);
    syncProjectUi();
    refreshBackendStatus().catch(() => {});
    refreshBatches();
}

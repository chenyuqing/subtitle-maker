/**
 * 初始化 Auto Dubbing V1/V2 两个面板。
 * 首轮只把这一整块前端子域迁出，仍通过依赖注入复用 `app.js` 的共享状态和播放器。
 */
export function setupDubbingPanels(deps) {
    setupAutoDubbing({
        prefix: 'auto-dub',
        panelId: 'panel-auto-dub',
        startButtonId: 'start-auto-dub-btn',
        stepIds: {
            transcribing: 'step-transcribe',
            translating: 'step-translate',
            dubbing: 'step-dub',
        },
        pipelineVersion: 'v1',
    }, deps);
    setupAutoDubbing({
        prefix: 'auto-dub-v2',
        panelId: 'panel-auto-dub-v2',
        startButtonId: 'start-auto-dub-v2-btn',
        stepIds: {
            transcribing: 'step-v2-transcribe',
            translating: 'step-v2-translate',
            dubbing: 'step-v2-dub',
        },
        pipelineVersion: 'v2',
    }, deps);
}

/**
 * 按前缀绑定一套独立 Auto Dubbing 实例，避免 V1/V2 状态串扰。
 */
function setupAutoDubbing(config, deps) {
    const prefix = String(config?.prefix || '').trim();
    const byId = (suffix) => document.getElementById(`${prefix}-${suffix}`);
    const panelEl = document.getElementById(config?.panelId || '');
    if (!panelEl || !prefix) return;

    const {
        videoPlayer,
        videoPlaceholder,
        shortMergeTargetDefault,
        shortMergeTargetMin,
        shortMergeTargetMax,
        secondsToDisplay,
        timeToSeconds,
        formatLineProgress,
        formatEtaAsSegmentProgress,
        buildAutoDubElapsedLabel,
        describeAutoStage,
        normalizeShortMergeTargetSeconds,
        applyAutoDubSubtitleItems,
        getDeepSeekApiKey,
        getProjectDubbingContext,
    } = deps;

    const projectModeBtn = byId('mode-project-btn');
    const standaloneModeBtn = byId('mode-standalone-btn');
    const projectReadinessEl = byId('project-readiness');
    const projectMediaEl = byId('project-media');
    const projectTaskEl = byId('project-task');
    const projectSourceCountEl = byId('project-source-count');
    const projectTranslatedCountEl = byId('project-translated-count');
    const projectSubtitleModeSelect = byId('project-subtitle-mode');
    const projectNoteEl = byId('project-note');
    const standaloneDetailsEl = byId('standalone-details');
    const uploadArea = byId('upload-area');
    const fileInput = byId('file-input');
    const browseBtn = byId('browse-btn');
    const filenameDisplay = byId('filename');
    const subtitleInput = byId('subtitle-input');
    const subtitleBrowseBtn = byId('subtitle-browse-btn');
    const subtitleNameDisplay = byId('subtitle-name');
    const subtitleModeSelect = byId('subtitle-mode');
    const sourceLangSelect = byId('source');
    const targetLangSelect = byId('target');
    const groupingStrategySelect = byId('grouping-strategy');
    const shortMergeEnabledCheckbox = byId('short-merge-enabled');
    const shortMergeSettingsEl = byId('short-merge-settings');
    const shortMergeThresholdInput = byId('short-merge-threshold');
    const autoPickRangesCheckbox = byId('auto-pick-ranges');
    const rewriteTranslationCheckbox = byId('rewrite-translation');
    const startBtn = document.getElementById(config?.startButtonId || '');
    const statusContainer = byId('status-container');
    const autoProgressFill = byId('progress-fill');
    const statusText = byId('status-text');
    const resultsContainer = byId('results');
    const reviewPanel = byId('review-panel');
    const reviewLoadBtn = byId('review-load-btn');
    const reviewSaveRedubBtn = byId('review-save-redub-btn');
    const reviewListEl = byId('review-list');
    const taskLabel = byId('task-id');
    const lineProgressEl = byId('line-progress');
    const etaEl = byId('eta');
    const loadBatchSelect = byId('load-batch-select');
    const refreshBatchesBtn = byId('refresh-batches-btn');
    const loadBatchBtn = byId('load-batch-btn');
    const audioTrackSwitcher = document.getElementById('audio-track-switcher');
    const audioTrackModeSelect = document.getElementById('audio-track-mode');
    const autoDubRangesList = byId('time-ranges-list');
    const autoDubRangeError = byId('range-error');
    const autoDubRangeStartM = byId('range-start-m');
    const autoDubRangeStartS = byId('range-start-s');
    const autoDubRangeEndM = byId('range-end-m');
    const autoDubRangeEndS = byId('range-end-s');
    const autoDubAddRangeBtn = byId('add-range-btn');
    const autoDubUseCurrentBtn = byId('use-current-time-btn');
    const autoDubClearRangesBtn = byId('clear-ranges-btn');

    let selectedFile = null;
    let selectedSubtitleFile = null;
    let autoDubPreviewUrl = null;
    let autoDubTimeRanges = [];
    let autoDubStartedAtMs = 0;
    let currentAutoDubTaskId = '';
    let reviewLinesCache = [];
    let startMode = 'project';
    const dubbedAudioPlayer = new Audio();
    dubbedAudioPlayer.preload = 'metadata';
    let dubbedAudioUrl = null;

    /**
     * 读取主 workflow 当前上下文，供 Current Project 模式复用已有媒体与字幕。
     */
    function readProjectContext() {
        if (typeof getProjectDubbingContext === 'function') {
            return getProjectDubbingContext() || {};
        }
        return {};
    }

    /**
     * 计算 Current Project 模式下可选的字幕策略，避免前端隐式猜测字幕语义。
     */
    function buildProjectSubtitleOptions(projectContext) {
        const sourceItems = Array.isArray(projectContext?.sourceSubtitles) ? projectContext.sourceSubtitles : [];
        const translatedItems = Array.isArray(projectContext?.translatedSubtitles) ? projectContext.translatedSubtitles : [];
        const options = [];
        if (translatedItems.length > 0) {
            options.push({
                value: 'translated',
                label: `使用当前译文直接配音（${translatedItems.length} 行，跳过 ASR / 翻译）`,
            });
        }
        if (sourceItems.length > 0) {
            options.push({
                value: 'source',
                label: `使用当前原字幕继续翻译（${sourceItems.length} 行，跳过 ASR）`,
            });
        }
        options.push({
            value: 'media_only',
            label: '只使用当前媒体，重新执行完整流程',
        });
        return options;
    }

    /**
     * 渲染 Current Project 摘要卡，让用户看到当前项目是否真的具备可直接配音的输入。
     */
    function renderProjectContextSummary() {
        const projectContext = readProjectContext();
        const sourceItems = Array.isArray(projectContext?.sourceSubtitles) ? projectContext.sourceSubtitles : [];
        const translatedItems = Array.isArray(projectContext?.translatedSubtitles) ? projectContext.translatedSubtitles : [];
        const mediaName = projectContext?.mediaOriginalFilename || projectContext?.mediaFilename || '';
        if (projectMediaEl) {
            projectMediaEl.textContent = mediaName || '未上传媒体';
        }
        if (projectTaskEl) {
            projectTaskEl.textContent = projectContext?.taskId || '未生成';
        }
        if (projectSourceCountEl) {
            projectSourceCountEl.textContent = `${sourceItems.length} 行`;
        }
        if (projectTranslatedCountEl) {
            projectTranslatedCountEl.textContent = `${translatedItems.length} 行`;
        }
        if (projectSubtitleModeSelect) {
            const previous = projectSubtitleModeSelect.value;
            const options = buildProjectSubtitleOptions(projectContext);
            projectSubtitleModeSelect.innerHTML = '';
            options.forEach((option) => {
                const node = document.createElement('option');
                node.value = option.value;
                node.textContent = option.label;
                projectSubtitleModeSelect.appendChild(node);
            });
            const values = options.map((item) => item.value);
            if (values.includes(previous)) {
                projectSubtitleModeSelect.value = previous;
            } else if (values.includes('translated')) {
                projectSubtitleModeSelect.value = 'translated';
            } else if (values.includes('source')) {
                projectSubtitleModeSelect.value = 'source';
            } else {
                projectSubtitleModeSelect.value = 'media_only';
            }
        }
        if (projectReadinessEl) {
            projectReadinessEl.textContent = mediaName ? '可复用' : '缺少媒体';
        }
        if (projectNoteEl) {
            if (!mediaName) {
                projectNoteEl.textContent = '当前项目还没有可复用的媒体文件。若只导入了 SRT，请切换到 Standalone Upload 或先上传媒体。';
            } else if (translatedItems.length > 0) {
                projectNoteEl.textContent = '当前项目已有译文，默认可直接跳过 ASR 与翻译。';
            } else if (sourceItems.length > 0) {
                projectNoteEl.textContent = '当前项目已有原字幕，可直接跳过 ASR，仅继续翻译与配音。';
            } else {
                projectNoteEl.textContent = '当前项目只有媒体，启动后会重新执行完整流程。';
            }
        }
        // 当前项目没有媒体时，默认展开独立上传模式，让用户能直接开始使用，而不是停在不可执行的 project 模式。
        if (!mediaName && !selectedFile && startMode !== 'standalone') {
            setStartMode('standalone');
        }
    }

    /**
     * 在 Current Project / Standalone Upload 之间切换，避免两套流程并行显示造成误导。
     */
    function setStartMode(nextMode) {
        startMode = nextMode === 'standalone' ? 'standalone' : 'project';
        if (projectModeBtn) {
            projectModeBtn.classList.toggle('active', startMode === 'project');
            projectModeBtn.setAttribute('aria-pressed', startMode === 'project' ? 'true' : 'false');
        }
        if (standaloneModeBtn) {
            standaloneModeBtn.classList.toggle('active', startMode === 'standalone');
            standaloneModeBtn.setAttribute('aria-pressed', startMode === 'standalone' ? 'true' : 'false');
        }
        if (standaloneDetailsEl) {
            standaloneDetailsEl.open = startMode === 'standalone';
        }
        if (startBtn) {
            startBtn.textContent = startMode === 'project'
                ? `Start ${config?.pipelineVersion === 'v2' ? 'Auto Dubbing V2' : 'Auto Dubbing'} From Current Project`
                : `Start ${config?.pipelineVersion === 'v2' ? 'Auto Dubbing V2' : 'Auto Dubbing'}`;
        }
    }

    /**
     * 同步“短句合并”开关与阈值面板显示，避免默认关闭时仍暴露无效参数。
     */
    function syncShortMergeControls() {
        if (!shortMergeSettingsEl) return;
        const shortMergeEnabled = shortMergeEnabledCheckbox ? !!shortMergeEnabledCheckbox.checked : false;
        shortMergeSettingsEl.style.display = shortMergeEnabled ? 'flex' : 'none';
    }

    /**
     * 校验自动配音时间区间，避免提交重叠或非法区间。
     */
    function validateAutoDubRange(startSec, endSec, durationSec) {
        if (startSec < 0) {
            return { valid: false, error: '起始时间不能小于 0' };
        }
        if (durationSec > 0 && endSec > durationSec) {
            return { valid: false, error: `结束时间不能超过视频时长 ${secondsToDisplay(durationSec)}` };
        }
        if (endSec <= startSec) {
            return { valid: false, error: '结束时间必须大于起始时间' };
        }
        for (const range of autoDubTimeRanges) {
            if (!(endSec <= range.start || startSec >= range.end)) {
                return { valid: false, error: '该区间与已有区间重叠' };
            }
        }
        return { valid: true, error: '' };
    }

    /**
     * 渲染自动配音区间标签列表，与主字幕工作流保持一致交互。
     */
    function renderAutoDubTimeRanges() {
        if (!autoDubRangesList) return;
        autoDubRangesList.innerHTML = '';
        autoDubTimeRanges.forEach((range, index) => {
            const tag = document.createElement('div');
            tag.className = 'time-range-tag';
            tag.innerHTML = `
                <span class="range-times">${secondsToDisplay(range.start)} - ${secondsToDisplay(range.end)}</span>
                <button class="delete-range" data-index="${index}" title="删除">&times;</button>
            `;
            autoDubRangesList.appendChild(tag);
        });
        autoDubRangesList.querySelectorAll('.delete-range').forEach((btn) => {
            btn.addEventListener('click', (event) => {
                const idx = parseInt(event.target.dataset.index, 10);
                autoDubTimeRanges.splice(idx, 1);
                renderAutoDubTimeRanges();
            });
        });
    }

    /**
     * 清空自动配音区间输入框，减少重复输入操作。
     */
    function clearAutoDubRangeInputs() {
        if (autoDubRangeStartM) autoDubRangeStartM.value = '';
        if (autoDubRangeStartS) autoDubRangeStartS.value = '';
        if (autoDubRangeEndM) autoDubRangeEndM.value = '';
        if (autoDubRangeEndS) autoDubRangeEndS.value = '';
    }

    /**
     * 使用当前播放器时间填充起始时间，便于快速打点。
     */
    function setAutoDubStartFromCurrent() {
        if (!videoPlayer || Number.isNaN(videoPlayer.currentTime)) return;
        const current = videoPlayer.currentTime;
        const mm = Math.floor(current / 60);
        const ss = Math.floor(current % 60);
        if (autoDubRangeStartM) autoDubRangeStartM.value = mm.toString().padStart(2, '0');
        if (autoDubRangeStartS) autoDubRangeStartS.value = ss.toString().padStart(2, '0');
    }

    /**
     * 添加一个自动配音时间区间（MM:SS），并按时间排序。
     */
    function addAutoDubRange() {
        const startM = autoDubRangeStartM?.value || '';
        const startS = autoDubRangeStartS?.value || '';
        const endM = autoDubRangeEndM?.value || '';
        const endS = autoDubRangeEndS?.value || '';

        if (!startM && !startS) {
            if (autoDubRangeError) {
                autoDubRangeError.textContent = '请填写起始时间';
                autoDubRangeError.style.display = 'block';
            }
            return false;
        }
        if (!endM && !endS) {
            if (autoDubRangeError) {
                autoDubRangeError.textContent = '请填写结束时间';
                autoDubRangeError.style.display = 'block';
            }
            return false;
        }
        const startSec = timeToSeconds(startM, startS);
        const endSec = timeToSeconds(endM, endS);
        const durationSec = (videoPlayer && !Number.isNaN(videoPlayer.duration)) ? videoPlayer.duration : 0;
        const validation = validateAutoDubRange(startSec, endSec, durationSec);
        if (!validation.valid) {
            if (autoDubRangeError) {
                autoDubRangeError.textContent = validation.error;
                autoDubRangeError.style.display = 'block';
            }
            return false;
        }
        autoDubTimeRanges.push({ start: startSec, end: endSec });
        autoDubTimeRanges.sort((a, b) => a.start - b.start);
        if (autoDubRangeError) autoDubRangeError.style.display = 'none';
        renderAutoDubTimeRanges();
        return true;
    }

    if (autoDubAddRangeBtn) {
        autoDubAddRangeBtn.addEventListener('click', () => {
            if (addAutoDubRange()) {
                clearAutoDubRangeInputs();
            }
        });
    }
    if (autoDubUseCurrentBtn) {
        autoDubUseCurrentBtn.addEventListener('click', () => {
            setAutoDubStartFromCurrent();
        });
    }
    if (autoDubClearRangesBtn) {
        autoDubClearRangesBtn.addEventListener('click', () => {
            autoDubTimeRanges = [];
            renderAutoDubTimeRanges();
            if (autoDubRangeError) autoDubRangeError.style.display = 'none';
        });
    }

    /**
     * 根据可用音轨更新播放器模式：original=原视频声音，dubbed=配音音频。
     */
    function applyAudioTrackMode(mode) {
        if (!videoPlayer) return;
        const targetMode = mode === 'dubbed' ? 'dubbed' : 'original';
        const hasDubbed = !!dubbedAudioUrl;
        if (targetMode === 'dubbed' && !hasDubbed) {
            // 关键修复：V1/V2 双实例都监听同一个音轨选择器时，
            // 没有配音链接的实例不能把选择器强制回退到 original，
            // 否则会覆盖另一个实例（有配音）的切换结果。
            return;
        }

        if (targetMode === 'original') {
            videoPlayer.muted = false;
            dubbedAudioPlayer.pause();
            return;
        }

        videoPlayer.muted = true;
        dubbedAudioPlayer.playbackRate = videoPlayer.playbackRate || 1;
        try {
            dubbedAudioPlayer.currentTime = videoPlayer.currentTime || 0;
        } catch (e) {
            // 某些浏览器在 metadata 未就绪时会抛错，这里忽略即可。
            console.debug('sync dubbed audio time failed', e);
        }
        if (!videoPlayer.paused) {
            dubbedAudioPlayer.play().catch(() => {});
        }
    }

    /**
     * 在导入新媒体或新任务结果时重置音轨状态，避免沿用旧任务的配音链接。
     */
    function resetAudioTrackState() {
        dubbedAudioUrl = null;
        dubbedAudioPlayer.pause();
        dubbedAudioPlayer.removeAttribute('src');
        dubbedAudioPlayer.load();
        if (audioTrackModeSelect) {
            audioTrackModeSelect.value = 'original';
        }
        if (audioTrackSwitcher) {
            audioTrackSwitcher.style.display = 'none';
        }
        if (videoPlayer) {
            videoPlayer.muted = false;
        }
    }

    /**
     * 根据后端返回结果提取可播放的配音音频链接。
     */
    function pickDubbedAudioUrl(data) {
        if (data && typeof data.result_audio === 'string' && data.result_audio) {
            return data.result_audio;
        }
        const artifacts = Array.isArray(data?.artifacts) ? data.artifacts : [];
        const preferred = artifacts.find((item) => item?.key === 'preferred_audio' && item.url)
            || artifacts.find((item) => item?.key === 'mix' && item.url)
            || artifacts.find((item) => item?.key === 'vocals' && item.url);
        return preferred?.url || null;
    }

    /**
     * 加载历史任务时，恢复原视频到播放器，避免“只有音轨没有画面”。
     */
    function loadInputMediaToPlayer(data) {
        const mediaUrl = data?.input_media_url;
        if (!videoPlayer) return;
        if (!mediaUrl) {
            if (statusText) {
                statusText.textContent = 'Loaded · Completed（源视频已不存在，请重新上传视频进行预览）';
                statusText.className = 'status-text';
            }
            return;
        }
        resetAudioTrackState();
        if (autoDubPreviewUrl) {
            URL.revokeObjectURL(autoDubPreviewUrl);
            autoDubPreviewUrl = null;
        }
        videoPlayer.src = mediaUrl;
        videoPlayer.style.display = 'block';
        videoPlayer.load();
        videoPlayer.controls = true;
        if (videoPlaceholder) {
            videoPlaceholder.style.display = 'none';
        }
    }

    /**
     * 渲染逐句审阅列表，支持直接编辑翻译文本。
     */
    function renderReviewLines(lines) {
        if (!reviewListEl) return;
        reviewListEl.innerHTML = '';
        for (const line of (Array.isArray(lines) ? lines : [])) {
            const row = document.createElement('div');
            row.style.borderBottom = '1px solid var(--border)';
            row.style.padding = '8px 0';
            const meta = document.createElement('div');
            meta.style.fontSize = '0.82rem';
            meta.style.color = 'var(--text-muted)';
            meta.textContent = `#${line.index}  ${secondsToDisplay(Number(line.start_sec || 0))} - ${secondsToDisplay(Number(line.end_sec || 0))}  ·  ${line.status || 'unknown'}`;
            const source = document.createElement('div');
            source.style.fontSize = '0.86rem';
            source.style.margin = '4px 0';
            source.textContent = `Source: ${line.source_text || ''}`;
            const editor = document.createElement('textarea');
            editor.value = line.translated_text || '';
            editor.dataset.index = String(line.index || '');
            editor.style.width = '100%';
            editor.style.minHeight = '54px';
            editor.style.padding = '8px';
            editor.style.borderRadius = '6px';
            editor.style.border = '1px solid var(--border)';
            row.appendChild(meta);
            row.appendChild(source);
            row.appendChild(editor);
            reviewListEl.appendChild(row);
        }
    }

    /**
     * 收集审阅编辑；可选择仅提交真正改动的行。
     */
    function collectReviewEdits({ diffOnly = false } = {}) {
        if (!reviewListEl) return [];
        const originalTextByIndex = new Map();
        for (const row of (Array.isArray(reviewLinesCache) ? reviewLinesCache : [])) {
            originalTextByIndex.set(Number(row.index || 0), String(row.translated_text || ''));
        }
        const edits = [];
        reviewListEl.querySelectorAll('textarea[data-index]').forEach((node) => {
            const index = Number(node.dataset.index || 0);
            const nextText = String(node.value || '');
            if (!index) return;
            if (diffOnly) {
                const prevText = originalTextByIndex.get(index) ?? '';
                if (nextText === prevText) return;
            }
            edits.push({
                index,
                translated_text: nextText,
            });
        });
        return edits;
    }

    /**
     * 为媒体 URL 增加版本参数，规避浏览器复用旧 Range 导致的 416/无声。
     */
    function withCacheBust(url) {
        const raw = String(url || '').trim();
        if (!raw) return raw;
        const sep = raw.includes('?') ? '&' : '?';
        return `${raw}${sep}v=${Date.now()}`;
    }

    /**
     * 拉取当前任务的逐句审阅数据。
     */
    async function loadReviewLines() {
        if (!currentAutoDubTaskId) {
            throw new Error('当前没有可审阅任务');
        }
        const res = await fetch(`/dubbing/auto/review/${currentAutoDubTaskId}`);
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        const payload = await res.json();
        reviewLinesCache = Array.isArray(payload?.lines) ? payload.lines : [];
        renderReviewLines(reviewLinesCache);
        if (reviewPanel) reviewPanel.style.display = 'block';
    }

    /**
     * 保存修改并触发“局部重配 + final 重拼”。
     */
    async function saveReviewAndRedub() {
        if (!currentAutoDubTaskId) {
            throw new Error('当前没有可重配任务');
        }
        const edits = collectReviewEdits({ diffOnly: true });
        if (!edits.length) {
            return { status: 'no_changes' };
        }
        const formData = new FormData();
        formData.append('edits_json', JSON.stringify(edits));
        const res = await fetch(`/dubbing/auto/review/${currentAutoDubTaskId}/save-and-redub`, { method: 'POST', body: formData });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        const payload = await res.json();
        await loadReviewLines();
        const statusRes = await fetch(`/dubbing/auto/status/${currentAutoDubTaskId}`);
        if (statusRes.ok) {
            const taskData = await statusRes.json();
            renderResults(taskData);
        }
        return payload;
    }

    /**
     * 从任务结果中选择可自动加载的字幕文件。
     */
    function pickAutoDubSrtUrl(data) {
        if (data && typeof data.result_srt === 'string' && data.result_srt) {
            return data.result_srt;
        }
        const artifacts = Array.isArray(data?.artifacts) ? data.artifacts : [];
        const preferred = artifacts.find((item) => item?.key === 'bilingual_srt' && item.url)
            || artifacts.find((item) => item?.key === 'translated_srt' && item.url)
            || artifacts.find((item) => item?.key === 'source_srt' && item.url);
        return preferred?.url || null;
    }

    /**
     * 将 SRT 时间戳（如 00:01:02,345）转换成秒。
     */
    function parseSrtTimeToSeconds(timeText) {
        const match = String(timeText || '').trim().match(/^(\d{2}):(\d{2}):(\d{2}),(\d{3})$/);
        if (!match) return null;
        const h = Number(match[1]);
        const m = Number(match[2]);
        const s = Number(match[3]);
        const ms = Number(match[4]);
        return h * 3600 + m * 60 + s + ms / 1000;
    }

    /**
     * 轻量 SRT 解析：输出与现有字幕渲染一致的数据结构。
     */
    function parseSrtToSubtitleItems(srtText) {
        const normalized = String(srtText || '').replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim();
        if (!normalized) return [];
        const blocks = normalized.split(/\n{2,}/);
        const items = [];
        for (const block of blocks) {
            const lines = block.split('\n').map((line) => line.trimEnd()).filter(Boolean);
            if (lines.length < 2) continue;
            const timeLineIndex = lines.findIndex((line) => line.includes('-->'));
            if (timeLineIndex < 0) continue;
            const timeLine = lines[timeLineIndex];
            const [startText, endText] = timeLine.split('-->').map((part) => part.trim());
            const start = parseSrtTimeToSeconds(startText);
            const end = parseSrtTimeToSeconds(endText);
            if (start === null || end === null) continue;
            const text = lines.slice(timeLineIndex + 1).join('\n').trim();
            if (!text) continue;
            items.push({ start, end, text });
        }
        return items;
    }

    /**
     * Auto Dubbing 完成后自动加载产出的字幕到播放器 overlay。
     */
    async function autoLoadAutoDubSubtitles(data) {
        const srtUrl = pickAutoDubSrtUrl(data);
        if (!srtUrl) return;
        try {
            const response = await fetch(srtUrl);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            const srtText = await response.text();
            const parsed = parseSrtToSubtitleItems(srtText);
            if (!parsed.length) {
                throw new Error('empty or invalid srt');
            }
            applyAutoDubSubtitleItems(parsed);
        } catch (error) {
            console.warn('Auto load dubbing subtitles failed:', error);
        }
    }

    // 绑定主播放器与配音音频的同步：播放/暂停/拖动/倍速都同步。
    if (videoPlayer) {
        videoPlayer.addEventListener('play', () => {
            if (audioTrackModeSelect?.value === 'dubbed' && dubbedAudioUrl) {
                dubbedAudioPlayer.play().catch(() => {});
            }
        });
        videoPlayer.addEventListener('pause', () => {
            dubbedAudioPlayer.pause();
        });
        videoPlayer.addEventListener('seeking', () => {
            if (audioTrackModeSelect?.value === 'dubbed' && dubbedAudioUrl) {
                try {
                    dubbedAudioPlayer.currentTime = videoPlayer.currentTime || 0;
                } catch (e) {
                    console.debug('seek sync failed', e);
                }
            }
        });
        videoPlayer.addEventListener('ratechange', () => {
            dubbedAudioPlayer.playbackRate = videoPlayer.playbackRate || 1;
        });
        videoPlayer.addEventListener('ended', () => {
            dubbedAudioPlayer.pause();
            try {
                dubbedAudioPlayer.currentTime = 0;
            } catch (e) {
                console.debug('reset dubbed audio failed', e);
            }
        });
    }

    if (audioTrackModeSelect) {
        audioTrackModeSelect.addEventListener('change', () => {
            applyAudioTrackMode(audioTrackModeSelect.value);
        });
    }

    if (projectModeBtn) {
        projectModeBtn.addEventListener('click', () => setStartMode('project'));
    }
    if (standaloneModeBtn) {
        standaloneModeBtn.addEventListener('click', () => setStartMode('standalone'));
    }
    window.addEventListener('subtitle-maker:project-context-changed', () => {
        renderProjectContextSummary();
    });
    renderProjectContextSummary();
    setStartMode('project');

    // File Upload Logic.
    if (uploadArea && fileInput) {
        uploadArea.addEventListener('click', () => fileInput.click());

        if (browseBtn) {
            browseBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                fileInput.click();
            });
        }

        uploadArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadArea.classList.add('drag-active');
        });

        uploadArea.addEventListener('dragleave', () => {
            uploadArea.classList.remove('drag-active');
        });

        uploadArea.addEventListener('drop', (e) => {
            e.preventDefault();
            uploadArea.classList.remove('drag-active');
            if (e.dataTransfer.files.length > 0) {
                handleAutoDubFile(e.dataTransfer.files[0]);
            }
        });

        fileInput.addEventListener('change', (e) => {
            if (e.target.files.length > 0) {
                handleAutoDubFile(e.target.files[0]);
            }
        });
    }
    if (subtitleBrowseBtn && subtitleInput) {
        subtitleBrowseBtn.addEventListener('click', () => subtitleInput.click());
        subtitleInput.addEventListener('change', (event) => {
            const file = event.target.files && event.target.files.length > 0 ? event.target.files[0] : null;
            if (!file) return;
            setStartMode('standalone');
            const name = String(file.name || '').toLowerCase();
            if (!(name.endsWith('.srt') || name.endsWith('.vtt') || name.endsWith('.md'))) {
                alert('字幕文件必须是 .srt / .vtt / .md');
                subtitleInput.value = '';
                return;
            }
            selectedSubtitleFile = file;
            if (subtitleNameDisplay) {
                const mode = subtitleModeSelect ? subtitleModeSelect.value : 'source';
                const modeHint = mode === 'translated' ? '将跳过 ASR 与翻译' : '将跳过 ASR';
                subtitleNameDisplay.textContent = `已选择：${file.name}（${modeHint}）`;
            }
        });
    }
    if (subtitleModeSelect) {
        subtitleModeSelect.addEventListener('change', () => {
            if (!selectedSubtitleFile || !subtitleNameDisplay) return;
            const modeHint = subtitleModeSelect.value === 'translated' ? '将跳过 ASR 与翻译' : '将跳过 ASR';
            subtitleNameDisplay.textContent = `已选择：${selectedSubtitleFile.name}（${modeHint}）`;
        });
    }

    /**
     * 处理 Auto Dubbing 的媒体文件选择与预览。
     */
    function handleAutoDubFile(file) {
        setStartMode('standalone');
        selectedFile = file;
        selectedSubtitleFile = null;
        if (subtitleInput) subtitleInput.value = '';
        if (subtitleNameDisplay) subtitleNameDisplay.textContent = '未选择字幕文件（默认自动识别）';
        if (subtitleModeSelect) subtitleModeSelect.value = 'source';
        autoDubTimeRanges = [];
        renderAutoDubTimeRanges();
        if (autoDubRangeError) autoDubRangeError.style.display = 'none';
        const sizeMb = (file.size / (1024 * 1024)).toFixed(2);
        if (filenameDisplay) {
            filenameDisplay.textContent = `${file.name} · ${sizeMb} MB`;
        }
        uploadArea.classList.add('has-file');

        if (autoDubPreviewUrl) {
            URL.revokeObjectURL(autoDubPreviewUrl);
        }
        autoDubPreviewUrl = URL.createObjectURL(file);
        resetAudioTrackState();

        if (videoPlayer) {
            videoPlayer.src = autoDubPreviewUrl;
            videoPlayer.style.display = 'block';
            videoPlayer.load();
            videoPlayer.controls = true;
        }
        if (videoPlaceholder) {
            videoPlaceholder.style.display = 'none';
        }
    }

    /**
     * 加载历史 batch 后，尽量恢复当前面板控件到当时的执行参数。
     */
    function restoreLoadedBatchControls(data) {
        const payload = data && typeof data === 'object' ? data : {};

        const setSelectValueIfPresent = (selectEl, value) => {
            if (!selectEl || value === undefined || value === null || value === '') return;
            const normalized = String(value);
            if ([...selectEl.options].some((option) => option.value === normalized)) {
                selectEl.value = normalized;
            }
        };

        setSelectValueIfPresent(sourceLangSelect, payload.source_lang);
        setSelectValueIfPresent(targetLangSelect, payload.target_lang);
        setSelectValueIfPresent(subtitleModeSelect, payload.subtitle_mode);
        setSelectValueIfPresent(groupingStrategySelect, payload.grouping_strategy);

        if (shortMergeEnabledCheckbox) {
            shortMergeEnabledCheckbox.checked = !!payload.source_short_merge_enabled;
        }
        if (shortMergeThresholdInput) {
            shortMergeThresholdInput.value = String(
                normalizeShortMergeTargetSeconds(payload.source_short_merge_threshold)
            );
        }
        if (autoPickRangesCheckbox && typeof payload.auto_pick_ranges === 'boolean') {
            autoPickRangesCheckbox.checked = payload.auto_pick_ranges;
        }
        if (rewriteTranslationCheckbox && typeof payload.rewrite_translation === 'boolean') {
            rewriteTranslationCheckbox.checked = payload.rewrite_translation;
        }
        syncShortMergeControls();
    }

    if (shortMergeEnabledCheckbox) {
        shortMergeEnabledCheckbox.addEventListener('change', () => {
            syncShortMergeControls();
        });
    }
    syncShortMergeControls();

    /**
     * 组装两种启动模式共用的表单字段，避免 Current Project / Standalone 出现参数漂移。
     */
    function buildCommonStartFormData(apiKey, options = {}) {
        const formData = new FormData();
        const sourceLang = sourceLangSelect?.value || 'auto';
        const targetLang = targetLangSelect?.value || 'Chinese';
        const groupingStrategy = groupingStrategySelect ? groupingStrategySelect.value : 'sentence';
        const shortMergeEnabled = shortMergeEnabledCheckbox ? !!shortMergeEnabledCheckbox.checked : false;
        const shortMergeThreshold = Number.parseInt(
            shortMergeThresholdInput?.value || String(shortMergeTargetDefault),
            10,
        );
        const autoPickRanges = autoPickRangesCheckbox ? !!autoPickRangesCheckbox.checked : false;
        const rewriteTranslation = rewriteTranslationCheckbox ? !!rewriteTranslationCheckbox.checked : null;
        if (
            shortMergeEnabled
            && (
                !Number.isInteger(shortMergeThreshold)
                || shortMergeThreshold < shortMergeTargetMin
                || shortMergeThreshold > shortMergeTargetMax
            )
        ) {
            throw new Error(`Short merge target must be an integer between ${shortMergeTargetMin} and ${shortMergeTargetMax} seconds.`);
        }
        formData.append('source_lang', sourceLang);
        formData.append('target_lang', targetLang);
        formData.append('grouping_strategy', groupingStrategy);
        formData.append('short_merge_enabled', shortMergeEnabled ? 'true' : 'false');
        formData.append('short_merge_threshold', String(shortMergeThreshold));
        formData.append('api_key', apiKey || '');
        formData.append('auto_pick_ranges', autoPickRanges ? 'true' : 'false');
        formData.append('pipeline_version', config?.pipelineVersion || 'v1');
        if (rewriteTranslation !== null) {
            formData.append('rewrite_translation', rewriteTranslation ? 'true' : 'false');
        }
        if (autoDubTimeRanges.length > 0) {
            const payload = autoDubTimeRanges.map((item) => ({
                start_sec: Number(item.start),
                end_sec: Number(item.end),
            }));
            formData.append('time_ranges', JSON.stringify(payload));
        }
        Object.entries(options).forEach(([key, value]) => {
            if (value === undefined || value === null || value === '') return;
            formData.append(key, value);
        });
        return formData;
    }

    /**
     * Current Project 模式下，从主 workflow 读取媒体和字幕，并映射成 project-aware 请求。
     */
    function buildCurrentProjectRequest(apiKey) {
        const projectContext = readProjectContext();
        const mediaFilename = String(projectContext?.mediaFilename || '').trim();
        if (!mediaFilename) {
            throw new Error('Current project has no reusable media. Upload media first or switch to Standalone Upload.');
        }
        const requestedMode = projectSubtitleModeSelect ? projectSubtitleModeSelect.value : 'media_only';
        let subtitleMode = 'source';
        let subtitlesJson = '';
        if (requestedMode === 'translated') {
            subtitleMode = 'translated';
            subtitlesJson = JSON.stringify(projectContext?.translatedSubtitles || []);
        } else if (requestedMode === 'source') {
            subtitleMode = 'source';
            subtitlesJson = JSON.stringify(projectContext?.sourceSubtitles || []);
        }
        const formData = buildCommonStartFormData(apiKey, {
            filename: mediaFilename,
            original_filename: projectContext?.mediaOriginalFilename || mediaFilename,
            task_id: projectContext?.taskId || '',
            subtitle_mode: subtitleMode,
            subtitles_json: subtitlesJson,
        });
        const subtitleLabel = requestedMode === 'translated'
            ? 'Skip ASR + Translation with current translated subtitles'
            : requestedMode === 'source'
                ? 'Skip ASR with current source subtitles'
                : 'Run from current project media';
        return {
            endpoint: '/dubbing/auto/start-from-project',
            formData,
            initLabel: `Initializing... (${subtitleLabel})`,
        };
    }

    /**
     * Standalone 模式继续走原有上传入口，但统一复用全局 key 和公共参数拼装。
     */
    function buildStandaloneRequest(apiKey) {
        const subtitleMode = subtitleModeSelect ? subtitleModeSelect.value : 'source';
        if (!selectedFile) {
            throw new Error('Please select a video file first.');
        }
        const formData = buildCommonStartFormData(apiKey, {
            subtitle_mode: selectedSubtitleFile ? subtitleMode : '',
        });
        formData.append('video', selectedFile);
        if (selectedSubtitleFile) {
            formData.append('subtitle_file', selectedSubtitleFile);
        }
        const initLabel = selectedSubtitleFile
            ? (subtitleMode === 'translated'
                ? 'Initializing... (Skip ASR + Translation with uploaded translated subtitles)'
                : 'Initializing... (Skip ASR with uploaded subtitles)')
            : 'Initializing...';
        return {
            endpoint: '/dubbing/auto/start',
            formData,
            initLabel,
        };
    }

    if (startBtn) {
        startBtn.addEventListener('click', async () => {
            const apiKey = typeof getDeepSeekApiKey === 'function' ? getDeepSeekApiKey() : '';
            autoDubStartedAtMs = Date.now();

            startBtn.disabled = true;
            statusContainer.style.display = 'block';
            resultsContainer.style.display = 'none';
            if (autoProgressFill) {
                autoProgressFill.style.width = '5%';
            }
            statusText.className = 'status-text';

            [config?.stepIds?.transcribing, config?.stepIds?.translating, config?.stepIds?.dubbing].forEach((id) => {
                const stepEl = id ? document.getElementById(id) : null;
                if (!stepEl) return;
                stepEl.style.fontWeight = 'normal';
                stepEl.style.color = 'var(--text-muted)';
            });
            if (taskLabel) taskLabel.textContent = 'Task —';
            if (lineProgressEl) lineProgressEl.textContent = 'Lines —';
            if (etaEl) etaEl.textContent = 'ETA —';

            try {
                const request = startMode === 'project'
                    ? buildCurrentProjectRequest(apiKey)
                    : buildStandaloneRequest(apiKey);
                statusText.textContent = request.initLabel;
                const res = await fetch(request.endpoint, { method: 'POST', body: request.formData });
                if (!res.ok) {
                    const err = await res.json().catch(() => ({}));
                    throw new Error(err.detail || 'Failed to start dubbing task');
                }

                const data = await res.json();
                const taskId = data.task_id;
                currentAutoDubTaskId = taskId;
                if (taskLabel && taskId) {
                    taskLabel.textContent = `Task · ${taskId.split('-')[0].toUpperCase()}`;
                }

                pollAutoDubStatus(taskId);
            } catch (e) {
                console.error(e);
                statusText.textContent = 'Error: ' + e.message;
                statusText.className = 'status-text error';
                startBtn.disabled = false;
            }
        });
    }

    /**
     * 加载历史 longdub 结果目录，恢复下载链接与音轨切换。
     */
    async function refreshBatchOptions() {
        if (!loadBatchSelect) return;
        try {
            const res = await fetch('/dubbing/auto/batches');
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const payload = await res.json();
            const batches = Array.isArray(payload?.batches) ? payload.batches : [];
            const previous = loadBatchSelect.value;
            loadBatchSelect.innerHTML = batches.length
                ? '<option value="">选择已生成结果文件夹</option>'
                : '<option value="">暂无可加载结果，请先运行一次 Auto Dubbing</option>';
            for (const item of batches) {
                const id = item?.batch_id || '';
                if (!id) continue;
                const option = document.createElement('option');
                option.value = id;
                option.textContent = `${id} (${item?.web_dir || 'web'})`;
                loadBatchSelect.appendChild(option);
            }
            if (previous) loadBatchSelect.value = previous;
        } catch (error) {
            console.warn('Load batch list failed:', error);
            loadBatchSelect.innerHTML = '<option value="">列表加载失败（可点击“加载结果”手动输入）</option>';
        }
    }

    if (refreshBatchesBtn) {
        refreshBatchesBtn.addEventListener('click', () => {
            refreshBatchOptions();
        });
    }
    refreshBatchOptions();

    if (loadBatchBtn && loadBatchSelect) {
        loadBatchBtn.addEventListener('click', async () => {
            let batchId = (loadBatchSelect.value || '').trim();
            if (!batchId) {
                const typed = window.prompt('请输入结果文件夹名（例如 longdub_20260419_102927）', '');
                batchId = (typed || '').trim();
            }
            if (!batchId) return;
            loadBatchBtn.disabled = true;
            try {
                const formData = new FormData();
                formData.append('batch_id', batchId);
                const res = await fetch('/dubbing/auto/load-batch', { method: 'POST', body: formData });
                if (!res.ok) {
                    const err = await res.json().catch(() => ({}));
                    throw new Error(err.detail || 'Load batch failed');
                }
                const data = await res.json();
                currentAutoDubTaskId = data.id || data.task_id || currentAutoDubTaskId;
                if (statusContainer) statusContainer.style.display = 'block';
                if (resultsContainer) resultsContainer.style.display = 'none';
                if (taskLabel && (data.short_id || data.id)) {
                    taskLabel.textContent = `Task · ${(data.short_id || data.id.split('-')[0]).toUpperCase()}`;
                }
                if (autoProgressFill) autoProgressFill.style.width = '100%';
                if (statusText) {
                    statusText.textContent = data.status === 'failed' ? 'Loaded · Failed' : 'Loaded · Completed';
                    statusText.className = data.status === 'failed' ? 'status-text error' : 'status-text success';
                }
                updateStepHighlights('dubbing:completed');
                restoreLoadedBatchControls(data);
                loadInputMediaToPlayer(data);
                renderResults(data);
            } catch (error) {
                if (statusText) {
                    statusText.textContent = `Load Error: ${error.message}`;
                    statusText.className = 'status-text error';
                }
            } finally {
                loadBatchBtn.disabled = false;
            }
        });
    }

    if (reviewLoadBtn) {
        reviewLoadBtn.addEventListener('click', async () => {
            try {
                await loadReviewLines();
            } catch (error) {
                if (statusText) {
                    statusText.textContent = `Review Error: ${error.message}`;
                    statusText.className = 'status-text error';
                }
            }
        });
    }

    if (reviewSaveRedubBtn) {
        reviewSaveRedubBtn.addEventListener('click', async () => {
            reviewSaveRedubBtn.disabled = true;
            let redubProgressTimer = null;
            try {
                if (statusContainer) statusContainer.style.display = 'block';
                if (statusText) {
                    statusText.textContent = '正在局部重配改动句并重建 final...';
                    statusText.className = 'status-text';
                }
                if (autoProgressFill) autoProgressFill.style.width = '20%';
                redubProgressTimer = setInterval(() => {
                    if (!autoProgressFill) return;
                    const current = Number(String(autoProgressFill.style.width || '0').replace('%', '')) || 0;
                    const next = Math.min(92, current + (current < 60 ? 6 : 2));
                    autoProgressFill.style.width = `${next}%`;
                }, 900);

                const payload = await saveReviewAndRedub();
                if (redubProgressTimer) {
                    clearInterval(redubProgressTimer);
                    redubProgressTimer = null;
                }
                if (autoProgressFill) autoProgressFill.style.width = '100%';
                if (statusText) {
                    statusText.textContent = `Saved & Re-dubbed · 影响段数 ${payload?.redubbed_segments ?? 0}`;
                    statusText.className = 'status-text success';
                }
            } catch (error) {
                if (redubProgressTimer) {
                    clearInterval(redubProgressTimer);
                    redubProgressTimer = null;
                }
                if (statusText) {
                    statusText.textContent = `Re-dub Error: ${error.message}`;
                    statusText.className = 'status-text error';
                }
            } finally {
                reviewSaveRedubBtn.disabled = false;
            }
        });
    }

    /**
     * 轮询 Auto Dubbing 任务状态，并更新当前面板的进度与结果。
     */
    function pollAutoDubStatus(taskId) {
        const interval = setInterval(async () => {
            try {
                const res = await fetch(`/dubbing/auto/status/${taskId}`);
                if (!res.ok) {
                    clearInterval(interval);
                    throw new Error('Status poll failed');
                }

                const data = await res.json();

                if (autoProgressFill && typeof data.progress === 'number') {
                    autoProgressFill.style.width = `${data.progress}%`;
                }

                if (taskLabel && (data.short_id || data.id)) {
                    taskLabel.textContent = `Task · ${(data.short_id || data.id.split('-')[0]).toUpperCase()}`;
                }

                const processed = data.processed_segments ?? data?.dub_progress?.processed_segments;
                const total = data.total_segments ?? data?.dub_progress?.total_segments;
                if (lineProgressEl) {
                    lineProgressEl.textContent = formatLineProgress(processed, total);
                }

                if (etaEl) {
                    etaEl.textContent = formatEtaAsSegmentProgress(processed, total);
                }

                const stageLabel = describeAutoStage(data.stage);
                if (statusText) {
                    let suffix = '';
                    if (data.status === 'completed') suffix = ' • Done';
                    else if (data.status === 'failed') suffix = ' • Failed';
                    statusText.textContent = `${stageLabel}${suffix}`;
                    statusText.className = 'status-text';
                    if (data.status === 'failed') statusText.classList.add('error');
                    else if (data.status === 'completed') statusText.classList.add('success');
                }

                updateStepHighlights(data.stage);

                if (data.status === 'completed') {
                    clearInterval(interval);
                    startBtn.disabled = false;
                    const elapsedLabel = buildAutoDubElapsedLabel(data, autoDubStartedAtMs);
                    statusText.textContent = elapsedLabel ? `Process Complete · ${elapsedLabel}` : 'Process Complete';
                    statusText.className = 'status-text success';
                    renderResults(data);
                } else if (data.status === 'failed') {
                    clearInterval(interval);
                    startBtn.disabled = false;
                    statusText.textContent = 'Failed: ' + data.error;
                    statusText.className = 'status-text error';
                }
            } catch (e) {
                console.error(e);
                clearInterval(interval);
                statusText.textContent = 'Polling Error: ' + e.message;
                startBtn.disabled = false;
            }
        }, 1200);
    }

    /**
     * 更新当前阶段高亮，维持 V1/V2 面板的步骤提示。
     */
    function updateStepHighlights(stage) {
        const steps = {
            transcribing: config?.stepIds?.transcribing,
            translating: config?.stepIds?.translating,
            dubbing: config?.stepIds?.dubbing,
        };

        let normalized = stage;
        if (stage && stage.startsWith('dubbing')) normalized = 'dubbing';
        if (stage === 'finished') normalized = 'dubbing';

        for (const [key, id] of Object.entries(steps)) {
            const el = document.getElementById(id);
            if (el) {
                if (key === normalized) {
                    el.style.fontWeight = 'bold';
                    el.style.color = 'var(--accent)';
                } else {
                    el.style.fontWeight = 'normal';
                    el.style.color = 'var(--text-muted)';
                }
            }
        }
    }

    /**
     * 渲染 Auto Dubbing 结果区，并联动播放器音轨与字幕恢复。
     */
    function renderResults(data) {
        resultsContainer.style.display = 'block';
        if (reviewPanel) reviewPanel.style.display = 'block';
        const links = resultsContainer.querySelector('.download-links');
        if (!links) return;
        links.innerHTML = '';

        autoLoadAutoDubSubtitles(data);

        dubbedAudioUrl = pickDubbedAudioUrl(data);
        if (dubbedAudioUrl) {
            dubbedAudioUrl = withCacheBust(dubbedAudioUrl);
            dubbedAudioPlayer.src = dubbedAudioUrl;
            dubbedAudioPlayer.load();
            if (audioTrackSwitcher) {
                audioTrackSwitcher.style.display = 'inline-flex';
            }
            if (audioTrackModeSelect) {
                audioTrackModeSelect.value = 'original';
            }
            applyAudioTrackMode('original');
        } else {
            resetAudioTrackState();
        }

        const artifacts = Array.isArray(data.artifacts) ? data.artifacts : [];
        artifacts.forEach((artifact, index) => {
            if (!artifact || !artifact.url) return;
            const btn = document.createElement('a');
            btn.href = artifact.url;
            btn.className = index === 0 ? 'primary-btn' : 'secondary-btn';
            btn.textContent = artifact.label || artifact.key || 'Download';
            btn.style.display = 'block';
            btn.style.textAlign = 'center';
            links.appendChild(btn);
        });

        if (artifacts.length === 0 && data.result_audio) {
            const audioBtn = document.createElement('a');
            audioBtn.href = data.result_audio;
            audioBtn.className = 'primary-btn';
            audioBtn.textContent = 'Download Dubbed Audio';
            audioBtn.style.display = 'block';
            audioBtn.style.textAlign = 'center';
            links.appendChild(audioBtn);
        }

        if (artifacts.length === 0 && data.result_video) {
            const videoBtn = document.createElement('a');
            videoBtn.href = data.result_video;
            videoBtn.className = 'secondary-btn';
            videoBtn.textContent = 'Download Final Video';
            videoBtn.style.display = 'block';
            videoBtn.style.textAlign = 'center';
            links.appendChild(videoBtn);
        }

        const summary = document.createElement('p');
        summary.style.marginTop = '5px';
        summary.style.fontSize = '0.85rem';
        summary.style.color = 'var(--text-muted)';
        const processed = data.processed_segments ?? data.total_segments;
        const total = data.total_segments ?? processed;
        if (total) {
            const manual = data.manual_review_segments || 0;
            summary.textContent = manual > 0
                ? `Completed ${processed || total}/${total} segments. Manual review: ${manual}.`
                : `Completed ${processed || total}/${total} segments.`;
        } else {
            summary.textContent = 'Dub completed.';
        }
        const elapsedLabel = buildAutoDubElapsedLabel(data, autoDubStartedAtMs);
        if (elapsedLabel) {
            summary.textContent = `${summary.textContent} ${elapsedLabel}.`;
        }
        links.appendChild(summary);
    }
}

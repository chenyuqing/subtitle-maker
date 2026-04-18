const mediaUploadArea = document.getElementById('upload-area');
const mediaFileInput = document.getElementById('file-input');
const srtUploadArea = document.getElementById('srt-upload-area');
const srtFileInput = document.getElementById('srt-file-input');

const uploadStatus = document.getElementById('upload-status');
const videoPlayer = document.getElementById('video-player');
const videoPlaceholder = document.getElementById('video-placeholder');
const subtitleOverlay = document.getElementById('subtitle-overlay');
const posSelect = document.getElementById('sub-position');

const transcribeBtn = document.getElementById('transcribe-btn');
const progressContainer = document.getElementById('progress-container');
const progressFill = document.querySelector('.progress-fill');
const progressText = document.getElementById('progress-text');
const themeToggleBtn = document.getElementById('theme-toggle-btn');

const originalDisplay = document.getElementById('original-subtitles');
const translatedDisplay = document.getElementById('translated-subtitles');
const translateBtn = document.getElementById('translate-btn');
const downloadOriginal = document.getElementById('download-original');
// const downloadTranslated = document.getElementById('download-translated'); // Removed in HTML, recreated dynamically? Or hidden?

let currentFilename = null;
let currentOriginalFilename = null;
let currentTaskId = null;
let originalSubtitlesData = [];
let translatedSubtitlesData = [];
let transcriptionStartTime = null;
let timerInterval = null;
const SEEK_STEP_SECONDS = 10;
const SUBTITLE_POSITION_KEY = 'sm_subPosition';
const THEME_KEY = 'sm_theme';
let isAudioMode = false;

// Time Ranges State
let timeRanges = [];
let videoDuration = 0;

function seekVideo(deltaSeconds) {
    if (!videoPlayer || Number.isNaN(videoPlayer.duration)) return;
    const targetTime = Math.min(
        Math.max(0, (videoPlayer.currentTime || 0) + deltaSeconds),
        videoPlayer.duration || (videoPlayer.currentTime || 0)
    );
    videoPlayer.currentTime = targetTime;
}

function isTypingTarget(el) {
    if (!el) return false;
    const tag = el.tagName ? el.tagName.toLowerCase() : "";
    return (
        tag === "input" ||
        tag === "textarea" ||
        el.isContentEditable ||
        el.getAttribute?.("role") === "textbox"
    );
}

function applySubtitlePosition(position, persist = true) {
    if (!subtitleOverlay) return;
    const valid = ["top", "middle", "bottom"];
    const target = valid.includes(position) ? position : "bottom";
    subtitleOverlay.classList.remove("top-pos", "middle-pos", "bottom-pos");
    if (target === "top") {
        subtitleOverlay.classList.add("top-pos");
    } else if (target === "middle") {
        subtitleOverlay.classList.add("middle-pos");
    } else {
        subtitleOverlay.classList.add("bottom-pos");
    }
    if (posSelect && posSelect.value !== target) {
        posSelect.value = target;
    }
    if (persist) {
        localStorage.setItem(SUBTITLE_POSITION_KEY, target);
    }
}

function applyTheme(theme, persist = true) {
    // 主题只允许 dark/light 两种值，避免本地存储脏值影响界面
    const nextTheme = theme === 'light' ? 'light' : 'dark';
    document.body.setAttribute('data-theme', nextTheme);
    if (themeToggleBtn) {
        // 按钮文案显示“切换到另一个主题”
        themeToggleBtn.textContent = nextTheme === 'light' ? 'Dark Theme' : 'Light Theme';
    }
    if (persist) {
        localStorage.setItem(THEME_KEY, nextTheme);
    }
}

const initialSubtitlePosition =
    localStorage.getItem(SUBTITLE_POSITION_KEY) ||
    (posSelect ? posSelect.value : "bottom");
applySubtitlePosition(initialSubtitlePosition, false);

const initialTheme = localStorage.getItem(THEME_KEY) || 'dark';
applyTheme(initialTheme, false);

function setMediaMode(isAudio) {
    isAudioMode = !!isAudio;
    if (videoWrapper) {
        videoWrapper.classList.toggle('audio-mode', isAudioMode);
    }
}

function updateRuntimeTimer() {
    if (!transcriptionStartTime) return;
    const elapsedSeconds = Math.floor((Date.now() - transcriptionStartTime) / 1000);
    const m = Math.floor(elapsedSeconds / 60).toString().padStart(2, '0');
    const s = (elapsedSeconds % 60).toString().padStart(2, '0');
    const timerEl = document.getElementById('runtime-timer');
    if (timerEl) timerEl.textContent = `${m}:${s}`;
}

function startTimer() {
    stopTimer();
    transcriptionStartTime = Date.now();
    saveState();
    timerInterval = setInterval(updateRuntimeTimer, 1000);
}

function stopTimer() {
    if (timerInterval) {
        clearInterval(timerInterval);
        timerInterval = null;
    }
}

function formatEtaLabel(seconds) {
    if (seconds === undefined || seconds === null || Number.isNaN(seconds)) {
        return 'ETA —';
    }
    if (seconds < 1) return 'ETA ~<1s';
    const mins = Math.floor(seconds / 60);
    const secs = Math.round(seconds % 60);
    const mm = mins.toString().padStart(2, '0');
    const ss = secs.toString().padStart(2, '0');
    return `ETA ~${mm}:${ss}`;
}

function formatLineProgress(processed, total) {
    if (processed === undefined || total === undefined) {
        return 'Segments —';
    }
    return `Segments ${processed}/${total}`;
}

function parseIsoUtcToMs(isoText) {
    const value = Date.parse(String(isoText || ''));
    return Number.isFinite(value) ? value : null;
}

function formatElapsedClock(elapsedSeconds) {
    const safeSeconds = Math.max(0, Math.floor(Number(elapsedSeconds) || 0));
    const hours = Math.floor(safeSeconds / 3600);
    const mins = Math.floor((safeSeconds % 3600) / 60);
    const secs = safeSeconds % 60;
    if (hours > 0) {
        return `${hours}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
    }
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
}

function buildAutoDubElapsedLabel(taskData, fallbackStartMs) {
    // 优先使用后端任务时间戳，保证页面刷新后仍能得到准确耗时。
    const createdMs = parseIsoUtcToMs(taskData?.created_at);
    const finishedMs = parseIsoUtcToMs(taskData?.updated_at);
    if (createdMs !== null && finishedMs !== null && finishedMs >= createdMs) {
        return `用时 ${formatElapsedClock((finishedMs - createdMs) / 1000)}`;
    }
    // 兜底：若后端未返回可解析时间，使用前端本地启动时间。
    if (Number.isFinite(fallbackStartMs) && fallbackStartMs > 0) {
        return `用时 ${formatElapsedClock((Date.now() - fallbackStartMs) / 1000)}`;
    }
    return '';
}

function describeAutoStage(stage) {
    if (!stage) return 'Waiting';
    const mapping = {
        queued: 'Queued',
        transcribing: 'Transcribing audio',
        translating: 'Translating subtitles',
        dubbing: 'Dubbing',
        'dubbing:preparing': 'Preparing job',
        'dubbing:planning': 'Planning segments',
        'dubbing:segmenting': 'Cutting segments',
        'dubbing:separating': 'Preparing stems',
        'dubbing:tts': 'Generating speech',
        'dubbing:mixing': 'Mixing tracks',
        'dubbing:merging': 'Muxing final video',
        'dubbing:completed': 'Dub complete',
        finished: 'Finished'
    };
    return mapping[stage] || stage.replace(/_/g, ' ');
}

// --- Time Range Management ---

// Convert MM:SS to seconds
function timeToSeconds(m, s) {
    const mNum = parseInt(m) || 0;
    const sNum = parseInt(s) || 0;
    return mNum * 60 + sNum;
}

// Convert seconds to MM:SS display format
function secondsToDisplay(seconds) {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

function validateTimeRange(startSec, endSec, duration) {
    if (startSec < 0) {
        return { valid: false, error: '起始时间不能小于 0' };
    }
    if (endSec > duration) {
        return { valid: false, error: `结束时间不能超过视频时长 ${secondsToDisplay(duration)}` };
    }
    if (endSec <= startSec) {
        return { valid: false, error: '结束时间必须大于起始时间' };
    }
    // Check for overlap with existing ranges
    for (const range of timeRanges) {
        if (!(endSec <= range.start || startSec >= range.end)) {
            return { valid: false, error: '该区间与已有区间重叠' };
        }
    }
    return { valid: true, error: '' };
}

function renderTimeRanges() {
    const container = document.getElementById('time-ranges-list');
    if (!container) return;

    container.innerHTML = '';
    timeRanges.forEach((range, index) => {
        const tag = document.createElement('div');
        tag.className = 'time-range-tag';
        tag.innerHTML = `
            <span class="range-times">${secondsToDisplay(range.start)} - ${secondsToDisplay(range.end)}</span>
            <button class="delete-range" data-index="${index}" title="删除">&times;</button>
        `;
        container.appendChild(tag);
    });

    // Add delete handlers
    container.querySelectorAll('.delete-range').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const idx = parseInt(e.target.dataset.index);
            timeRanges.splice(idx, 1);
            renderTimeRanges();
        });
    });
}

function addTimeRange() {
    const rangeError = document.getElementById('range-error');
    const duration = videoDuration || 0;

    // Get values from MM:SS inputs
    const startM = document.getElementById('range-start-h')?.value || '';  // Actually minutes now
    const startS = document.getElementById('range-start-m')?.value || '';  // Actually seconds now
    const endM = document.getElementById('range-end-h')?.value || '';     // Actually minutes now
    const endS = document.getElementById('range-end-m')?.value || '';      // Actually seconds now

    // Check if any start time is filled
    if (!startM && !startS) {
        if (rangeError) {
            rangeError.textContent = '请填写起始时间';
            rangeError.style.display = 'block';
        }
        return false;
    }

    // Check if any end time is filled
    if (!endM && !endS) {
        if (rangeError) {
            rangeError.textContent = '请填写结束时间';
            rangeError.style.display = 'block';
        }
        return false;
    }

    const startSec = timeToSeconds(startM, startS);
    const endSec = timeToSeconds(endM, endS);

    // Validate
    const validation = validateTimeRange(startSec, endSec, duration);
    if (!validation.valid) {
        if (rangeError) {
            rangeError.textContent = validation.error;
            rangeError.style.display = 'block';
        }
        return false;
    }

    timeRanges.push({
        start: startSec,
        end: endSec
    });

    // Sort ranges by start time
    timeRanges.sort((a, b) => a.start - b.start);

    if (rangeError) rangeError.style.display = 'none';
    renderTimeRanges();
    return true;
}

function updateVideoDuration() {
    if (videoPlayer && videoPlayer.duration && !isNaN(videoPlayer.duration)) {
        videoDuration = videoPlayer.duration;
        const maxMinutes = Math.floor(videoDuration / 60);
        const displayDuration = secondsToDisplay(videoDuration);

        // Update placeholders for MM:SS inputs
        const startM = document.getElementById('range-start-h');
        const startS = document.getElementById('range-start-m');
        const endM = document.getElementById('range-end-h');
        const endS = document.getElementById('range-end-m');

        if (startM) startM.placeholder = `0-${maxMinutes}`;
        if (startS) startS.placeholder = '00-59';
        if (endM) endM.placeholder = `0-${maxMinutes}`;
        if (endS) endS.placeholder = '00-59';

        console.log(`Video duration: ${displayDuration} (${maxMinutes} minutes max)`);
    }
}

// --- Navigation Logic ---
const navButtons = document.querySelectorAll('.nav-item');
const panels = document.querySelectorAll('.panel');

navButtons.forEach(btn => {
    btn.addEventListener('click', () => {
        // Remove active from all buttons
        navButtons.forEach(b => b.classList.remove('active'));
        // Add active to clicked
        btn.classList.add('active');

        // Hide all panels
        panels.forEach(p => p.style.display = 'none');
        panels.forEach(p => p.classList.remove('active'));

        // Show target panel
        const targetId = btn.getAttribute('data-target');
        const targetPanel = document.getElementById(targetId);
        if (targetPanel) {
            targetPanel.style.display = 'block';
            setTimeout(() => targetPanel.classList.add('active'), 10);
        }
    });
});

function switchTab(stepIndex) {
    if (stepIndex >= 0 && stepIndex < navButtons.length) {
        navButtons[stepIndex].click();
    }
}

// --- Persistence Logic ---
function saveState() {
    if (currentTaskId) localStorage.setItem('sm_taskId', currentTaskId);
    if (currentFilename) localStorage.setItem('sm_filename', currentFilename);
    if (currentOriginalFilename) localStorage.setItem('sm_originalFilename', currentOriginalFilename);
    if (transcriptionStartTime) localStorage.setItem('sm_startTime', transcriptionStartTime);

    // Save subtitles content
    if (originalSubtitlesData && originalSubtitlesData.length > 0) {
        localStorage.setItem('sm_originalSubtitles', JSON.stringify(originalSubtitlesData));
    }
    if (translatedSubtitlesData && translatedSubtitlesData.length > 0) {
        localStorage.setItem('sm_translatedSubtitles', JSON.stringify(translatedSubtitlesData));
    }

    const apiKey = document.getElementById('api-key').value;
    if (apiKey) localStorage.setItem('sm_apiKey', apiKey);
}

function loadState() {
    const savedTaskId = localStorage.getItem('sm_taskId');
    const savedFilename = localStorage.getItem('sm_filename');
    const savedOriginalFilename = localStorage.getItem('sm_originalFilename');
    const savedApiKey = localStorage.getItem('sm_apiKey');
    const savedStartTime = localStorage.getItem('sm_startTime');

    // Restore Subtitles Independent of Task Status
    const savedOriginalSubs = localStorage.getItem('sm_originalSubtitles');
    const savedTranslatedSubs = localStorage.getItem('sm_translatedSubtitles');

    if (savedApiKey) {
        const apiKeyEl = document.getElementById('api-key');
        if (apiKeyEl) apiKeyEl.value = savedApiKey;
    }

    if (savedStartTime) {
        transcriptionStartTime = parseInt(savedStartTime);
    }

    if (savedOriginalSubs) {
        try {
            originalSubtitlesData = JSON.parse(savedOriginalSubs);
            renderSubtitles(originalSubtitlesData, originalDisplay);
            if (originalSubtitlesData.length > 0) {
                // Determine which tab to show? 
                // If we have subtitles, likely show results.
                switchTab(2);
            }
        } catch (e) { console.error("Failed to parse saved subtitles", e); }
    }

    if (originalSubtitlesData && originalSubtitlesData.length > 0) {
        if (translateBtn) translateBtn.disabled = false;
        if (exportBtn) exportBtn.disabled = false;
        // Note: convert exportBtn usage to be safe by ID lookup or check if variable exists
        const expBtn = document.getElementById('export-btn');
        if (expBtn) expBtn.disabled = false;

        const segBtn = document.getElementById('export-segments-btn');
        if (segBtn) segBtn.disabled = false;

        // Also enable transcribe button? It should be enabled by default anyway unless processing.
    }

    if (savedTranslatedSubs) {
        try {
            translatedSubtitlesData = JSON.parse(savedTranslatedSubs);
            renderSubtitles(translatedSubtitlesData, translatedDisplay);
        } catch (e) { console.error("Failed to parse saved translated subtitles", e); }
    }

    if (savedTaskId && savedFilename) {
        currentTaskId = savedTaskId;
        currentFilename = savedFilename;
        currentOriginalFilename = savedOriginalFilename || savedFilename;

        // Restore video
        if (videoPlayer) {
            // Note: If server restarted, this URL might be invalid if it was a temp file? 
            // We'll try. 
            videoPlayer.src = `/stream/${currentFilename}`;
            videoPlayer.style.display = 'block';
        }
        if (videoPlaceholder) videoPlaceholder.style.display = 'none';

        // Poll to see if task is still alive/running on server
        pollStatus();
    }

    // Sync Language if previously saved
    const savedLang = localStorage.getItem('sm_targetLang');
    if (savedLang) {
        const dubbingSelects = ['dub-target-lang', 'auto-dub-target']
            .map(id => document.getElementById(id))
            .filter(Boolean);
        for (const select of dubbingSelects) {
            select.value = savedLang;
        }
        if (translatedSubtitlesData && translatedSubtitlesData.length > 0) {
            syncDubbingLanguage(savedLang);
        }
    }
}

function syncDubbingLanguage(lang) {
    const dubbingSelects = ['dub-target-lang', 'auto-dub-target']
        .map(id => document.getElementById(id))
        .filter(Boolean);
    if (dubbingSelects.length === 0) return;

    let matched = false;
    for (const select of dubbingSelects) {
        select.value = lang;
        if (select.value === lang) {
            matched = true;
        }
    }

    if (matched) {
        localStorage.setItem('sm_targetLang', lang);
    }
}

async function clearState() {
    const confirmed = confirm("Are you sure you want to start a new project? This will clear current progress and uploaded files.");
    if (!confirmed) return;

    const cleanupRequests = [];

    if (currentTaskId) {
        cleanupRequests.push(fetch(`/cancel/${currentTaskId}`, { method: 'POST' }));
    }

    cleanupRequests.push(fetch('/model/asr/release', { method: 'POST' }));
    cleanupRequests.push(fetch('/project/reset', { method: 'POST' }));

    try {
        await Promise.all(
            cleanupRequests.map(p =>
                p.catch(err => console.error("Cleanup request failed", err))
            )
        );
    } catch (err) {
        console.error("New project cleanup encountered an error", err);
    }

    localStorage.removeItem('sm_taskId');
    localStorage.removeItem('sm_filename');
    localStorage.removeItem('sm_originalFilename');
    localStorage.removeItem('sm_startTime');
    localStorage.removeItem('sm_originalSubtitles');
    localStorage.removeItem('sm_translatedSubtitles');
    location.reload();
}

// Bind Clear Button
const newProjectBtn = document.getElementById('new-project-btn');
if (newProjectBtn) {
    newProjectBtn.addEventListener('click', clearState);
}

const releaseModelsBtn = document.getElementById('release-models-btn');
if (releaseModelsBtn) {
    releaseModelsBtn.addEventListener('click', async () => {
        const originalLabel = releaseModelsBtn.textContent;
        releaseModelsBtn.disabled = true;
        releaseModelsBtn.textContent = "Releasing...";
        try {
            const res = await fetch('/model/all/release', { method: 'POST' });
            if (!res.ok) throw new Error("Server rejected the release request");
            const data = await res.json().catch(() => ({}));
            const tx = data.cancelled_transcriptions ?? 0;
            const auto = data.cancelled_auto_tasks ?? 0;
            alert(`Released models. Cancelled ${tx} transcription task(s) and ${auto} dubbing job(s).`);
        } catch (err) {
            console.error("Failed to release models", err);
            alert("Model release failed: " + err.message);
        } finally {
            releaseModelsBtn.disabled = false;
            releaseModelsBtn.textContent = originalLabel;
        }
    });
}

if (themeToggleBtn) {
    themeToggleBtn.addEventListener('click', () => {
        const currentTheme = document.body.getAttribute('data-theme') || 'dark';
        applyTheme(currentTheme === 'dark' ? 'light' : 'dark');
    });
}

// Initialize
window.addEventListener('DOMContentLoaded', loadState);

// Bind Overlay Mode Selector
const displayModeSelect = document.getElementById('display-mode');
if (displayModeSelect) {
    displayModeSelect.addEventListener('change', (e) => {
        overlayMode = e.target.value;
        // Optionally force redraw if video is paused?
        // But timeupdate handles it on play.
        // If paused, we can manually trigger a "fake" timeupdate logic or just wait.
    });
}


// --- Core Logic ---

// Sync Logic
// Sync Logic
let overlayMode = 'original'; // Default

if (videoPlayer) {
    videoPlayer.addEventListener('timeupdate', () => {
        const currentTime = videoPlayer.currentTime;
        let textToShow = "";

        // Helper to find subtitle at current time
        const findSub = (list) => list ? list.find(sub => currentTime >= sub.start && currentTime <= sub.end) : null;

        const orig = findSub(originalSubtitlesData);
        const trans = findSub(translatedSubtitlesData);

        const safeText = (t) => t ? t.replace(/\n/g, '<br>') : '';
        const origText = orig ? safeText(orig.text) : '';
        const transText = trans ? safeText(trans.text) : '';

        if (overlayMode === 'original') {
            textToShow = origText;
        } else if (overlayMode === 'translated') {
            textToShow = transText;
        } else if (overlayMode === 'bilingual_orig_trans') {
            if (orig && trans) textToShow = `${origText}<br><span class="sub-secondary">${transText}</span>`;
            else if (orig) textToShow = origText;
            else if (trans) textToShow = transText;
        } else if (overlayMode === 'bilingual_trans_orig') {
            if (orig && trans) textToShow = `${transText}<br><span class="sub-secondary">${origText}</span>`;
            else if (trans) textToShow = transText;
            else if (orig) textToShow = origText;
        }

        if (subtitleOverlay) {
            if (textToShow) {
                subtitleOverlay.innerHTML = textToShow;
                subtitleOverlay.style.display = 'block';
            } else {
                subtitleOverlay.style.display = 'none';
            }
        }
    });

    videoPlayer.addEventListener('loadedmetadata', () => {
        updateVideoDuration();
    });
}

// 1. Media Upload Logic (Panel 1)
setupUploadLogic(mediaUploadArea, mediaFileInput, handleMediaUpload);

// 4. SRT Upload Logic (Panel 4)
setupUploadLogic(srtUploadArea, srtFileInput, handleSrtUploadWrapper);

function setupUploadLogic(area, input, handler) {
    if (area && input) {
        // Click
        area.addEventListener('click', (e) => {
            if (e.target !== input) input.click();
        });

        // Reset input on click
        input.addEventListener('click', (e) => {
            e.stopPropagation();
            input.value = '';
        });

        // Drag & Drop
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            area.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
            }, false);
        });

        ['dragenter', 'dragover'].forEach(eventName => {
            area.addEventListener(eventName, () => area.classList.add('highlight'), false);
        });

        ['dragleave', 'drop'].forEach(eventName => {
            area.addEventListener(eventName, () => area.classList.remove('highlight'), false);
        });

        area.addEventListener('drop', (e) => {
            const dt = e.dataTransfer;
            const files = dt.files;
            if (files.length > 0) handler(files[0]);
        }, false);

        // Change
        input.addEventListener('change', (e) => {
            if (e.target.files.length > 0) handler(e.target.files[0]);
        });
    }
}

async function handleMediaUpload(file) {
    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);

    if (uploadStatus) uploadStatus.textContent = "Uploading...";

    if (progressContainer) {
        progressContainer.style.display = 'block';
        if (progressText) progressText.textContent = "Uploading Media...";
    }

    try {
        const res = await fetch('/upload', { method: 'POST', body: formData });
        if (!res.ok) throw new Error("Upload failed");

        const data = await res.json();
        currentTaskId = data.task_id;
        currentFilename = data.filename;
        currentOriginalFilename = file.name;

        // Clear previous subtitles
        originalSubtitlesData = [];
        translatedSubtitlesData = [];
        renderSubtitles([], document.getElementById('original-subtitles'));
        renderSubtitles([], document.getElementById('translated-subtitles'));

        // Clear time ranges
        timeRanges = [];
        renderTimeRanges();

        saveState();

        // Setup Video
        if (videoPlayer) {
            videoPlayer.src = data.url;
            videoPlayer.style.display = 'block';
        }
        if (videoPlaceholder) videoPlaceholder.style.display = 'none';

        const isAudioFile = (file.type && file.type.startsWith('audio/')) ||
            /\.(mp3|wav|m4a|aac|flac|ogg)$/i.test(file.name || '');
        setMediaMode(isAudioFile);
        if (isAudioFile) {
            applySubtitlePosition('middle');
        } else if (!localStorage.getItem(SUBTITLE_POSITION_KEY)) {
            applySubtitlePosition('bottom');
        }

        if (uploadStatus) uploadStatus.textContent = "Upload Complete";

        switchTab(1); // Go to Transcribe

        if (transcribeBtn) transcribeBtn.disabled = false;

    } catch (e) {
        console.error(e);
        alert("Upload Error: " + e.message);
    } finally {
        // Keep progress container hidden unless transcribing? 
        // Actually usually we hide it.
        if (progressContainer) progressContainer.style.display = 'none';
    }
}

async function handleSrtUploadWrapper(file) {
    if (!file.name.toLowerCase().endsWith('.srt')) {
        alert("Please select a valid .srt file");
        return;
    }

    // Clear video if any, or maybe keep it? 
    // Usually if importing SRT, it matches the video? 
    // For now, let's just upload SRT.

    try {
        await handleSrtUpload(file);
    } catch (e) {
        console.error("SRT Upload Error:", e);
        alert("SRT Upload Failed: " + e.message);
    }
}

// 2. Transcribe
if (transcribeBtn) {
    transcribeBtn.addEventListener('click', async () => {
        if (!currentFilename) return;

        const lang = document.getElementById('source-lang').value;
        const width = document.getElementById('max-width').value;

        const formData = new FormData();
        formData.append('filename', currentFilename);
        formData.append('language', lang);
        formData.append('max_width', width);
        if (currentOriginalFilename) {
            formData.append('original_filename', currentOriginalFilename);
        }

        // Add time ranges if any
        if (timeRanges.length > 0) {
            formData.append('time_ranges', JSON.stringify(timeRanges));
        }

        // Add existing subtitles for append mode
        if (originalSubtitlesData && originalSubtitlesData.length > 0) {
            formData.append('existing_subtitles', JSON.stringify(originalSubtitlesData));
        }

        transcribeBtn.disabled = true;
        progressContainer.style.display = 'block';
        if (progressFill) progressFill.style.width = '10%';
        if (progressText) progressText.textContent = "Requesting transcription...";

        try {
            const res = await fetch('/transcribe', { method: 'POST', body: formData });
            const data = await res.json();
            currentTaskId = data.task_id;

            // Start Timer
            startTimer();

            saveState();
            pollStatus();

        } catch (e) {
            if (progressText) progressText.textContent = "Error starting task: " + e.message;
            transcribeBtn.disabled = false;
        }
    });
}

// 2.1 Time Range Button Handlers
const addRangeBtn = document.getElementById('add-range-btn');
const useCurrentTimeBtn = document.getElementById('use-current-time-btn');
// MM:SS format inputs
const rangeStartM = document.getElementById('range-start-h');  // Actually minutes
const rangeStartS = document.getElementById('range-start-m');  // Actually seconds
const rangeEndM = document.getElementById('range-end-h');      // Actually minutes
const rangeEndS = document.getElementById('range-end-m');      // Actually seconds

function clearTimeInputs() {
    if (rangeStartM) rangeStartM.value = '';
    if (rangeStartS) rangeStartS.value = '';
    if (rangeEndM) rangeEndM.value = '';
    if (rangeEndS) rangeEndS.value = '';
}

function setStartTimeFromCurrent() {
    if (videoPlayer && !isNaN(videoPlayer.currentTime)) {
        const current = videoPlayer.currentTime;
        const m = Math.floor(current / 60);
        const s = Math.floor(current % 60);

        if (rangeStartM) rangeStartM.value = m.toString().padStart(2, '0');
        if (rangeStartS) rangeStartS.value = s.toString().padStart(2, '0');
    }
}

if (addRangeBtn) {
    addRangeBtn.addEventListener('click', () => {
        if (addTimeRange()) {
            clearTimeInputs();
        }
    });
}

if (useCurrentTimeBtn) {
    useCurrentTimeBtn.addEventListener('click', () => {
        setStartTimeFromCurrent();
    });
}

function displayTranscriptionTimer() {
    if (transcriptionStartTime) {
        const elapsedMs = Date.now() - transcriptionStartTime;
        const elapsedSeconds = Math.floor(elapsedMs / 1000);
        const minutes = Math.floor(elapsedSeconds / 60);
        const seconds = elapsedSeconds % 60;

        const timerDisplay = document.getElementById('transcription-timer');
        if (timerDisplay) {
            timerDisplay.textContent = `⏱️ Transcription completed in ${minutes}m ${seconds}s`;
        }
    }
}

async function pollStatus() {
    if (progressContainer) progressContainer.style.display = 'block'; // Ensure visible on restore

    const interval = setInterval(async () => {
        try {
            const res = await fetch(`/status/${currentTaskId}`);
            if (res.status === 404) {
                // Task invalid
                clearInterval(interval);
                return;
            }
            const data = await res.json();

            // Render Partial Subtitles (Real-time update)
            if (data.subtitles && data.subtitles.length > 0) {
                originalSubtitlesData = data.subtitles;
                renderSubtitles(originalSubtitlesData, originalDisplay);
                saveState(); // Save progress

                // If first time seeing subtitles, maybe switch tab?
                if (progressFill.style.width === '10%') {
                    progressFill.style.width = '30%';
                }
            }

            if (data.status === 'completed') {
                clearInterval(interval);
                stopTimer();
                if (progressFill) progressFill.style.width = '100%';
                if (progressText) progressText.textContent = "Completed!";

                displayTranscriptionTimer();

                // Final Render
                originalSubtitlesData = data.subtitles;
                renderSubtitles(originalSubtitlesData, originalDisplay);

                if (data.translated_subtitles) {
                    translatedSubtitlesData = data.translated_subtitles;
                    renderSubtitles(translatedSubtitlesData, translatedDisplay);
                }

                saveState(); // Save final state

                // Clear time ranges after successful transcription (for next append)
                timeRanges = [];
                renderTimeRanges();

                if (downloadOriginal) {
                    downloadOriginal.href = data.srt_url;
                    const baseName = currentOriginalFilename || currentFilename;
                    downloadOriginal.download = baseName.replace(/\.[\w]+$/, '.srt');
                    downloadOriginal.style.display = 'inline-block';
                }

                if (transcribeBtn) transcribeBtn.disabled = false;
                if (translateBtn) translateBtn.disabled = false;
                const exportBtn = document.getElementById('export-btn');
                if (exportBtn) exportBtn.disabled = false;

                const segBtn = document.getElementById('export-segments-btn');
                if (segBtn) segBtn.disabled = false;

                switchTab(2);

            } else if (data.status === 'failed') {
                clearInterval(interval);
                stopTimer();
                if (progressText) progressText.textContent = "Failed: " + data.error;
                if (transcribeBtn) transcribeBtn.disabled = false;
            } else {
                // If we are polling and have a start time but no interval, restart ticker (for page refresh)
                if (transcriptionStartTime && !timerInterval) {
                    timerInterval = setInterval(updateRuntimeTimer, 1000);
                }
                // Processing...
                if (data.subtitles && data.subtitles.length > 0) {
                    if (progressText) progressText.textContent = `Processing... (${data.subtitles.length} lines generated)`;
                    const resultsPanel = document.getElementById('panel-results');
                    if (resultsPanel && !resultsPanel.classList.contains('active')) {
                        switchTab(2);
                    }
                } else {
                    if (progressFill) progressFill.style.width = '50%';
                    if (progressText) progressText.textContent = "Processing...";
                }
            }
        } catch (e) {
            console.error(e);
        }
    }, 2000);
}

function renderSubtitles(subs, container) {
    if (!container) return;
    container.innerHTML = '';
    if (!subs) return;
    subs.forEach(sub => {
        const div = document.createElement('div');
        div.className = 'item';
        div.innerHTML = `
            <div class="item-time">${formatTime(sub.start)} --> ${formatTime(sub.end)}</div>
            <div class="item-text">${sub.text}</div>
        `;
        container.appendChild(div);
    });
}

function formatTime(seconds) {
    const pad = (num, size) => ('000' + num).slice(size * -1);
    const date = new Date(seconds * 1000);
    const h = pad(Math.floor(seconds / 3600), 2);
    const m = pad(date.getUTCMinutes(), 2);
    const s = pad(date.getUTCSeconds(), 2);
    return `${h}:${m}:${s}`;
}

// 3. Translate
if (translateBtn) {
    translateBtn.addEventListener('click', async () => {
        console.log("Translate button clicked");

        if (!originalSubtitlesData || originalSubtitlesData.length === 0) {
            console.warn("No subtitles to translate");
            alert("No subtitles found. Please upload a video/SRT or transcribe first.");
            return;
        }

        const provider = document.getElementById('model-provider').value;
        const targetLang = document.getElementById('target-lang').value; // Get target language
        const apiKey = document.getElementById('api-key').value;
        const systemPrompt = document.getElementById('system-prompt').value;

        console.log("Provider:", provider, "Target:", targetLang);

        // Validation
        if (provider === 'deepseek' && !apiKey) {
            alert("DeepSeek API Key is required.");
            return;
        }

        translateBtn.disabled = true;
        translateBtn.textContent = "Translating...";



        // Prepare data (Use FormData to match Backend Form(...) expectation)
        const formData = new FormData();
        if (currentTaskId) formData.append('task_id', currentTaskId);

        // Always send local subtitles to ensure stateless translation works (e.g. server restart)
        if (originalSubtitlesData && originalSubtitlesData.length > 0) {
            formData.append('subtitles_json', JSON.stringify(originalSubtitlesData));
        }

        formData.append('target_lang', targetLang);
        formData.append('model_provider', provider);
        formData.append('api_key', apiKey || '');
        if (systemPrompt) formData.append('system_prompt', systemPrompt);

        try {
            const res = await fetch('/translate', {
                method: 'POST',
                body: formData // No Content-Type header needed, browser sets it with boundary
            });

            if (!res.ok) throw new Error("Translation failed");

            const data = await res.json();
            translatedSubtitlesData = data.translated_subtitles;

            // Render
            renderSubtitles(translatedSubtitlesData, translatedDisplay);
            saveState(); // Persist

            // Update overlay mode to show translation
            if (document.getElementById('display-mode')) {
                document.getElementById('display-mode').value = 'bilingual_orig_trans';
            }

            // Sync to Dubbing Panel
            syncDubbingLanguage(targetLang);

        } catch (e) {
            alert("Error: " + e.message);
        } finally {
            translateBtn.disabled = false;
            translateBtn.textContent = "Translate";

            // Should we unload local model? 
            // User asked to unload ASR, but didn't explicitly say unload Translation model immediately?
            // "等我字幕识别完后，自动释放内存，然后如果使用翻译功能，点击翻译时才加载翻译模型"
            // Usually we keep translation model loaded for session? 
            // Better to add a "Unload Model" button or unload on "New Project".
        }
    });
}

function bindExportButtons() {
    const exportButton = document.getElementById('export-btn');
    if (exportButton && !exportButton.dataset.bound) {
        exportButton.dataset.bound = "true";
        exportButton.addEventListener('click', async () => {
            const format = document.getElementById('export-format').value;
            const formData = new FormData();
            formData.append('task_id', currentTaskId || ""); // Send empty string if null, though backend handles fallback
            formData.append('format', format);

        // Robustness: Send local data in case backend tasks got wiped (e.g. server restart)
        if (originalSubtitlesData && originalSubtitlesData.length > 0) {
            formData.append('subtitles_json', JSON.stringify(originalSubtitlesData));
        }
        if (translatedSubtitlesData && translatedSubtitlesData.length > 0) {
            formData.append('translated_subtitles_json', JSON.stringify(translatedSubtitlesData));
        }

        try {
            const res = await fetch('/export', { method: 'POST', body: formData });
            if (!res.ok) throw new Error("Export failed");

            // Trigger download
            const blob = await res.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;

            // Language Code Map
            const langMap = {
                'English': 'en',
                'Chinese': 'zh',
                'Japanese': 'jp',
                'French': 'fr',
                'German': 'de',
                'Cantonese': 'yue',
                'Italian': 'it',
                'Korean': 'ko',
                'Portuguese': 'pt',
                'Russian': 'ru',
                'Spanish': 'es'
            };

            const targetLangVal = document.getElementById('target-lang').value;
            const langCode = langMap[targetLangVal] || 'trans';

            // Construct Filename
            let suffix = "";

            if (format === 'original') {
                suffix = ".srt";
            } else if (format === 'translated') {
                suffix = `_${langCode}.srt`;
            } else if (format === 'bilingual_orig_trans') {
                suffix = `_${langCode}_orig_trans.srt`;
            } else if (format === 'bilingual_trans_orig') {
                suffix = `_${langCode}_trans_orig.srt`;
            }

            const baseName = currentOriginalFilename || currentFilename;
            // Remove existing extension if any, then append suffix
            const nameWithoutExt = baseName.replace(/\.[^/.]+$/, "");
            a.download = nameWithoutExt + suffix;

            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);

        } catch (e) {
            alert("Export error: " + e.message);
        }
        });
    }

    const exportSegmentsBtn = document.getElementById('export-segments-btn');
    if (exportSegmentsBtn && !exportSegmentsBtn.dataset.bound) {
        exportSegmentsBtn.dataset.bound = "true";
        exportSegmentsBtn.addEventListener('click', async () => {
            console.log("Export segments button clicked");
            if (exportSegmentsBtn.disabled) return;

            const maxDurationInput = document.getElementById('seg-max-duration');
            const maxDuration = maxDurationInput ? maxDurationInput.value : 30;
            const originalText = exportSegmentsBtn.textContent;

            exportSegmentsBtn.disabled = true;
            exportSegmentsBtn.textContent = "Generating...";

            const formData = new FormData();
            formData.append('task_id', currentTaskId || "");
            formData.append('max_duration', maxDuration);

            if (originalSubtitlesData && originalSubtitlesData.length > 0) {
                formData.append('subtitles_json', JSON.stringify(originalSubtitlesData));
            } else {
                console.warn("No subtitles data found to send for segmentation.");
            }

            try {
                const res = await fetch('/segment', { method: 'POST', body: formData });

                if (!res.ok) {
                    const err = await res.json().catch(() => ({ detail: "Unknown error" }));
                    throw new Error(err.detail || "Segmentation failed");
                }

                const data = await res.json();

                if (data.zip_url) {
                    const a = document.createElement('a');
                    a.href = data.zip_url;
                    a.download = `segments_${currentTaskId ? currentTaskId.slice(0, 8) : 'export'}.zip`;
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);

                    alert(`Exported ${data.count} segments successfully!`);
                } else {
                    alert("No segments generated. Check if subtitles exist.");
                }

            } catch (error) {
                console.error(error);
                alert("Export error: " + error.message);
            } finally {
                exportSegmentsBtn.disabled = false;
                exportSegmentsBtn.textContent = originalText;
            }
        });
    }
}

// --- Handler for SRT Upload ---
async function handleSrtUpload(file) {
    if (!file) return;

    if (uploadStatus) uploadStatus.textContent = "Uploading SRT...";

    const formData = new FormData();
    formData.append('file', file);

    // Pass existing video filename if available (so Dubbing knows about it)
    // Simple check: if currentFilename exists and is NOT an srt (meaning it's likely a video from Step 1)
    if (currentFilename && !currentFilename.toLowerCase().endsWith('.srt')) {
        formData.append('video_filename', currentFilename);
    }

    try {
        const res = await fetch('/upload_srt', { method: 'POST', body: formData });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || "Upload failed");
        }

        const data = await res.json();

        // Update state
        currentTaskId = data.task_id;
        currentFilename = data.filename;
        originalSubtitlesData = data.subtitles;
        translatedSubtitlesData = []; // Clear translation

        // Render
        renderSubtitles(originalSubtitlesData, originalDisplay);
        renderSubtitles([], translatedDisplay); // Clear right side

        saveState();

        if (uploadStatus) uploadStatus.textContent = "SRT Upload Complete";

        // Enable buttons since we possess subtitles now
        if (translateBtn) translateBtn.disabled = false;

        const expBtn = document.getElementById('export-btn');
        if (expBtn) expBtn.disabled = false;

        const segBtn = document.getElementById('export-segments-btn');
        if (segBtn) segBtn.disabled = false;

        // Switch to Translate tab (since transcription is skipped)
        switchTab(2);

    } catch (e) {
        console.error("SRT Upload Error:", e);
        alert("SRT Upload Failed: " + e.message);
        if (uploadStatus) uploadStatus.textContent = "Upload Failed";
    }
}

// --- API Key Auto-Save ---
const apiKeyInput = document.getElementById('api-key');
const saveApiKeyCheckbox = document.getElementById('save-api-key');
const MAIN_API_KEY = 'sm_apiKey';
const MAIN_SAVE_KEY = 'sm_saveApiKey';

if (apiKeyInput) {
    // Load saved key
    const savedKey = localStorage.getItem(MAIN_API_KEY);
    const savedChecked = localStorage.getItem(MAIN_SAVE_KEY) === 'true';
    if (savedKey && savedChecked) {
        apiKeyInput.value = savedKey;
    }
    if (saveApiKeyCheckbox) {
        saveApiKeyCheckbox.checked = savedChecked;
    }

    // Save on checkbox change
    if (saveApiKeyCheckbox) {
        saveApiKeyCheckbox.addEventListener('change', () => {
            if (saveApiKeyCheckbox.checked && apiKeyInput.value) {
                localStorage.setItem(MAIN_API_KEY, apiKeyInput.value);
            } else if (!saveApiKeyCheckbox.checked) {
                localStorage.removeItem(MAIN_API_KEY);
            }
            localStorage.setItem(MAIN_SAVE_KEY, saveApiKeyCheckbox.checked);
        });
    }

    // Also save when typing if checkbox is checked
    apiKeyInput.addEventListener('input', () => {
        if (saveApiKeyCheckbox && saveApiKeyCheckbox.checked && apiKeyInput.value) {
            localStorage.setItem(MAIN_API_KEY, apiKeyInput.value);
        }
    });
}

// --- Fullscreen Support ---
const fullscreenBtn = document.getElementById('fullscreen-btn');
const videoWrapper = document.querySelector('.video-wrapper');
const seekBackBtn = document.getElementById('seek-back-btn');
const seekForwardBtn = document.getElementById('seek-forward-btn');

if (fullscreenBtn && videoWrapper) {
    fullscreenBtn.addEventListener('click', () => {
        videoWrapper.classList.toggle('web-fullscreen');
    });

    // Exit web fullscreen on ESC
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && videoWrapper.classList.contains('web-fullscreen')) {
            videoWrapper.classList.remove('web-fullscreen');
        }
    });
}

if (seekBackBtn) {
    seekBackBtn.addEventListener('click', () => seekVideo(-SEEK_STEP_SECONDS));
}
if (seekForwardBtn) {
    seekForwardBtn.addEventListener('click', () => seekVideo(SEEK_STEP_SECONDS));
}

// --- Auto-hide Video Controls ---
const videoControlsBar = document.querySelector('.video-controls-bar');
let controlsHideTimeout = null;

function showControls() {
    if (!videoControlsBar) return;
    videoControlsBar.style.opacity = '1';
    videoControlsBar.style.visibility = 'visible';
    videoControlsBar.style.pointerEvents = 'auto';

    // Clear any pending hide
    if (controlsHideTimeout) {
        clearTimeout(controlsHideTimeout);
        controlsHideTimeout = null;
    }

    // Auto-hide after 3 seconds of inactivity
    if (videoPlayer && !videoPlayer.paused) {
        controlsHideTimeout = setTimeout(() => {
            if (videoControlsBar) {
                videoControlsBar.style.opacity = '0';
                videoControlsBar.style.visibility = 'hidden';
                videoControlsBar.style.pointerEvents = 'none';
            }
        }, 1200);
    }
}

function hideControls() {
    if (controlsHideTimeout) {
        clearTimeout(controlsHideTimeout);
        controlsHideTimeout = null;
    }
    if (videoControlsBar) {
        videoControlsBar.style.opacity = '0';
        videoControlsBar.style.visibility = 'hidden';
        videoControlsBar.style.pointerEvents = 'none';
    }
}

if (videoWrapper && videoControlsBar) {
    // Show controls on mouse move
    videoWrapper.addEventListener('mousemove', showControls);

    // Show controls when video is paused
    if (videoPlayer) {
        videoPlayer.addEventListener('pause', showControls);
        videoPlayer.addEventListener('play', () => {
            // Start auto-hide timer when playing
            showControls();
            controlsHideTimeout = setTimeout(hideControls, 3000);
        });
    }

    // Also show when hovering controls bar itself (so you can click)
    videoControlsBar.addEventListener('mouseenter', () => {
        if (controlsHideTimeout) {
            clearTimeout(controlsHideTimeout);
            controlsHideTimeout = null;
        }
        showControls();
    });

    videoControlsBar.addEventListener('mouseleave', () => {
        if (videoPlayer && !videoPlayer.paused) {
            controlsHideTimeout = setTimeout(hideControls, 1500);
        }
    });

    // Initial state
    hideControls();

    // Show on first mouse enter
    videoWrapper.addEventListener('mouseenter', showControls, { once: true });
}

document.addEventListener('keydown', (e) => {
    if (!videoPlayer || !videoPlayer.src || videoPlayer.readyState === 0) return;
    if (isTypingTarget(e.target)) return;
    if (e.key === 'ArrowLeft') {
        e.preventDefault();
        seekVideo(-SEEK_STEP_SECONDS);
    } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        seekVideo(SEEK_STEP_SECONDS);
    }
});

// --- Player Load Subtitles ---
document.addEventListener('DOMContentLoaded', () => {
    bindExportButtons();
    // Expose explicitly to window for inline onclick
    window.triggerSrtLoad = function () {
        console.log("Global triggerSrtLoad called");
        const input = document.getElementById('player-srt-input');
        if (input) {
            input.click();
        } else {
            alert("Error: Input element not found!");
        }
    };

    const playerSrtInput = document.getElementById('player-srt-input');
    if (playerSrtInput) {
        playerSrtInput.addEventListener('change', async (e) => {
            if (e.target.files.length > 0) {
                const file = e.target.files[0];
                if (!file.name.toLowerCase().endsWith('.srt')) {
                    alert("Please select a valid .srt file");
                    return;
                }
                try {
                    await handleSrtUpload(file);
                } catch (e) {
                    console.error("SRT Upload Error:", e);
                    alert("SRT Upload Failed: " + e.message);
                } finally {
                    playerSrtInput.value = '';
                }
            }
        });
    }

    // --- Dubbing Logic (Step 5) ---
    const startDubbingBtn = document.getElementById('start-dubbing-btn');
    const dubbingStatusContainer = document.getElementById('dubbing-status-container');
    const dubbingProgressBar = document.getElementById('dubbing-progress-bar');
    const dubbingStatusText = document.getElementById('dubbing-status-text');
    const dubbingResults = document.getElementById('dubbing-results');

    let currentDubTaskId = null;

    if (startDubbingBtn) {
        startDubbingBtn.addEventListener('click', async () => {
            if (!currentTaskId) {
                alert("Please complete the transcription (Step 2) first.");
                return;
            }

            const targetLang = document.getElementById('dub-target-lang').value;

            // UI Reset
            startDubbingBtn.disabled = true;
            dubbingStatusContainer.style.display = 'block';
            dubbingResults.style.display = 'none';
            dubbingProgressBar.style.width = '10%';
            dubbingStatusText.textContent = "Starting Dubbing Task...";
            dubbingStatusText.className = 'status-text';

            try {
                // Start Dubbing
                const formData = new FormData();
                formData.append('task_id', currentTaskId);
                formData.append('target_lang', targetLang);

                // Resilience: Pass current state to recover if server restarted
                if (currentFilename) {
                    formData.append('filename', currentFilename);
                }
                if (currentOriginalFilename) {
                    formData.append('original_filename', currentOriginalFilename);
                }
                // Prefer translated, fallback to original
                if (translatedSubtitlesData && translatedSubtitlesData.length > 0) {
                    formData.append('subtitles_json', JSON.stringify(translatedSubtitlesData));
                } else if (originalSubtitlesData && originalSubtitlesData.length > 0) {
                    formData.append('subtitles_json', JSON.stringify(originalSubtitlesData));
                }

                const res = await fetch('/dubbing/start', { method: 'POST', body: formData });
                if (!res.ok) {
                    const err = await res.json();
                    throw new Error(err.detail || "Failed to start dubbing");
                }

                const data = await res.json();
                currentDubTaskId = data.dubbing_task_id;

                // Poll Status
                const pollInterval = setInterval(async () => {
                    try {
                        const sRes = await fetch(`/status/${currentDubTaskId}`);
                        if (sRes.status === 404) {
                            clearInterval(pollInterval);
                            throw new Error("Dubbing task lost");
                        }
                        const sData = await sRes.json();

                        if (sData.status === 'completed') {
                            clearInterval(pollInterval);
                            dubbingProgressBar.style.width = '100%';
                            dubbingStatusText.textContent = "Dubbing Complete!";
                            dubbingStatusText.className = 'status-text success';
                            startDubbingBtn.disabled = false;

                            renderDubbingResults(sData.result);

                        } else if (sData.status === 'failed') {
                            clearInterval(pollInterval);
                            throw new Error(sData.error || "Dubbing failed");
                        } else {
                            // Processing
                            if (typeof sData.progress === 'number') {
                                dubbingProgressBar.style.width = `${sData.progress}%`;
                            } else {
                                dubbingProgressBar.style.width = '60%';
                            }
                            const manualStage = describeAutoStage(sData.stage);
                            let detail = '';
                            if (sData.processed_segments !== undefined && sData.total_segments) {
                                detail = ` (${sData.processed_segments}/${sData.total_segments})`;
                            }
                            if (sData.eta_seconds !== undefined) {
                                detail += ` · ${formatEtaLabel(sData.eta_seconds)}`;
                            }
                            dubbingStatusText.className = 'status-text';
                            dubbingStatusText.textContent = `${manualStage}...${detail}`;
                        }
                    } catch (pe) {
                        console.error(pe);
                        clearInterval(pollInterval);
                        dubbingStatusText.textContent = "Error polling status: " + pe.message;
                        startDubbingBtn.disabled = false;
                    }
                }, 1200);

            } catch (e) {
                console.error(e);
                dubbingStatusText.textContent = "Error: " + e.message;
                dubbingStatusText.className = 'status-text error';
                startDubbingBtn.disabled = false;
            }
        });
    }

    function renderDubbingResults(result) {
        if (!result) return;
        dubbingResults.style.display = 'block';

        const container = dubbingResults.querySelector('.download-links');
        container.innerHTML = '';

        // Add Download Button for Video
        if (result.video_url) {
            const btn = document.createElement('a');
            btn.href = result.video_url;
            btn.className = 'primary-btn';
            btn.textContent = '🎬 Download Dubbed Video';
            btn.style.display = 'block';
            btn.style.marginBottom = '10px';
            btn.style.textAlign = 'center';
            container.appendChild(btn);
        }

        // Add Download Button for Audio
        if (result.audio_url) {
            const btn = document.createElement('a');
            btn.href = result.audio_url;
            btn.className = 'secondary-btn';
            btn.textContent = '🎵 Download Mixed Audio';
            btn.style.display = 'block';
            btn.style.marginBottom = '10px';
            btn.style.textAlign = 'center';
            container.appendChild(btn);
        }

        const count = result.total_clips;
        const msg = document.createElement('p');
        msg.style.fontSize = '0.9em';
        msg.style.color = 'var(--text-muted)';
        msg.textContent = `Generated ${count} TTS clips.`;
        container.appendChild(msg);
    }

    // --- Subtitle Position Toggle ---
    if (posSelect && subtitleOverlay) {
        posSelect.addEventListener('change', () => applySubtitlePosition(posSelect.value));
    }

    // --- Auto Dubbing Module ---
    setupAutoDubbing();

    function setupAutoDubbing() {
        const uploadArea = document.getElementById('auto-dub-upload-area');
        const fileInput = document.getElementById('auto-dub-file-input');
        const browseBtn = document.getElementById('auto-dub-browse-btn');
        const filenameDisplay = document.getElementById('auto-dub-filename');
        const subtitleInput = document.getElementById('auto-dub-subtitle-input');
        const subtitleBrowseBtn = document.getElementById('auto-dub-subtitle-browse-btn');
        const subtitleNameDisplay = document.getElementById('auto-dub-subtitle-name');
        const subtitleModeSelect = document.getElementById('auto-dub-subtitle-mode');
        const startBtn = document.getElementById('start-auto-dub-btn');
        const statusContainer = document.getElementById('auto-dub-status-container');
        const autoProgressFill = document.getElementById('auto-dub-progress-fill');
        const statusText = document.getElementById('auto-dub-status-text');
        const resultsContainer = document.getElementById('auto-dub-results');
        const taskLabel = document.getElementById('auto-dub-task-id');
        const lineProgressEl = document.getElementById('auto-dub-line-progress');
        const etaEl = document.getElementById('auto-dub-eta');
        const apiKeyInput = document.getElementById('auto-dub-api-key');
        const saveKeyCheckbox = document.getElementById('auto-dub-save-key');
        const audioTrackSwitcher = document.getElementById('audio-track-switcher');
        const audioTrackModeSelect = document.getElementById('audio-track-mode');
        const autoDubRangesList = document.getElementById('auto-dub-time-ranges-list');
        const autoDubRangeError = document.getElementById('auto-dub-range-error');
        const autoDubRangeStartM = document.getElementById('auto-dub-range-start-m');
        const autoDubRangeStartS = document.getElementById('auto-dub-range-start-s');
        const autoDubRangeEndM = document.getElementById('auto-dub-range-end-m');
        const autoDubRangeEndS = document.getElementById('auto-dub-range-end-s');
        const autoDubAddRangeBtn = document.getElementById('auto-dub-add-range-btn');
        const autoDubUseCurrentBtn = document.getElementById('auto-dub-use-current-time-btn');
        const autoDubClearRangesBtn = document.getElementById('auto-dub-clear-ranges-btn');

        let selectedFile = null;
        let selectedSubtitleFile = null;
        let autoDubPreviewUrl = null;
        let autoDubTimeRanges = [];
        let autoDubStartedAtMs = 0;
        const dubbedAudioPlayer = new Audio();
        dubbedAudioPlayer.preload = 'metadata';
        let dubbedAudioUrl = null;

        // 校验自动配音时间区间，避免提交重叠或非法区间。
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

        // 渲染自动配音区间标签列表，与「Generate Subtitles」保持一致交互。
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
            autoDubRangesList.querySelectorAll('.delete-range').forEach(btn => {
                btn.addEventListener('click', (event) => {
                    const idx = parseInt(event.target.dataset.index, 10);
                    autoDubTimeRanges.splice(idx, 1);
                    renderAutoDubTimeRanges();
                });
            });
        }

        // 清空自动配音区间输入框，减少重复输入操作。
        function clearAutoDubRangeInputs() {
            if (autoDubRangeStartM) autoDubRangeStartM.value = '';
            if (autoDubRangeStartS) autoDubRangeStartS.value = '';
            if (autoDubRangeEndM) autoDubRangeEndM.value = '';
            if (autoDubRangeEndS) autoDubRangeEndS.value = '';
        }

        // 使用当前播放器时间填充起始时间，便于快速打点。
        function setAutoDubStartFromCurrent() {
            if (!videoPlayer || Number.isNaN(videoPlayer.currentTime)) return;
            const current = videoPlayer.currentTime;
            const mm = Math.floor(current / 60);
            const ss = Math.floor(current % 60);
            if (autoDubRangeStartM) autoDubRangeStartM.value = mm.toString().padStart(2, '0');
            if (autoDubRangeStartS) autoDubRangeStartS.value = ss.toString().padStart(2, '0');
        }

        // 添加一个自动配音时间区间（MM:SS），并按时间排序。
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

        // 根据可用音轨更新播放器模式：original=原视频声音，dubbed=配音音频
        function applyAudioTrackMode(mode) {
            if (!videoPlayer) return;
            const targetMode = mode === 'dubbed' ? 'dubbed' : 'original';
            const hasDubbed = !!dubbedAudioUrl;
            if (targetMode === 'dubbed' && !hasDubbed) {
                if (audioTrackModeSelect) {
                    audioTrackModeSelect.value = 'original';
                }
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
                // 某些浏览器在 metadata 未就绪时会抛错，这里忽略即可
                console.debug('sync dubbed audio time failed', e);
            }
            if (!videoPlayer.paused) {
                dubbedAudioPlayer.play().catch(() => {});
            }
        }

        // 在导入新媒体或新任务结果时重置音轨状态，避免沿用旧任务的配音链接
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

        // 根据后端返回结果提取可播放的配音音频链接（优先 result_audio）
        function pickDubbedAudioUrl(data) {
            if (data && typeof data.result_audio === 'string' && data.result_audio) {
                return data.result_audio;
            }
            const artifacts = Array.isArray(data?.artifacts) ? data.artifacts : [];
            const preferred = artifacts.find(item => item?.key === 'preferred_audio' && item.url)
                || artifacts.find(item => item?.key === 'mix' && item.url)
                || artifacts.find(item => item?.key === 'vocals' && item.url);
            return preferred?.url || null;
        }

        // 从任务结果中选择可自动加载的字幕文件（优先双语，其次翻译，再次原文）
        function pickAutoDubSrtUrl(data) {
            if (data && typeof data.result_srt === 'string' && data.result_srt) {
                return data.result_srt;
            }
            const artifacts = Array.isArray(data?.artifacts) ? data.artifacts : [];
            const preferred = artifacts.find(item => item?.key === 'bilingual_srt' && item.url)
                || artifacts.find(item => item?.key === 'translated_srt' && item.url)
                || artifacts.find(item => item?.key === 'source_srt' && item.url);
            return preferred?.url || null;
        }

        // 将 SRT 时间戳（如 00:01:02,345）转换成秒
        function parseSrtTimeToSeconds(timeText) {
            const match = String(timeText || '').trim().match(/^(\d{2}):(\d{2}):(\d{2}),(\d{3})$/);
            if (!match) return null;
            const h = Number(match[1]);
            const m = Number(match[2]);
            const s = Number(match[3]);
            const ms = Number(match[4]);
            return h * 3600 + m * 60 + s + ms / 1000;
        }

        // 轻量 SRT 解析：输出与现有字幕渲染一致的数据结构
        function parseSrtToSubtitleItems(srtText) {
            const normalized = String(srtText || '').replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim();
            if (!normalized) return [];
            const blocks = normalized.split(/\n{2,}/);
            const items = [];
            for (const block of blocks) {
                const lines = block.split('\n').map(line => line.trimEnd()).filter(Boolean);
                if (lines.length < 2) continue;
                const timeLineIndex = lines.findIndex(line => line.includes('-->'));
                if (timeLineIndex < 0) continue;
                const timeLine = lines[timeLineIndex];
                const [startText, endText] = timeLine.split('-->').map(part => part.trim());
                const start = parseSrtTimeToSeconds(startText);
                const end = parseSrtTimeToSeconds(endText);
                if (start === null || end === null) continue;
                const text = lines.slice(timeLineIndex + 1).join('\n').trim();
                if (!text) continue;
                items.push({ start, end, text });
            }
            return items;
        }

        // Auto Dubbing 完成后自动加载产出的字幕到播放器 overlay
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
                originalSubtitlesData = parsed;
                translatedSubtitlesData = [];
                renderSubtitles(originalSubtitlesData, originalDisplay);
                renderSubtitles([], translatedDisplay);
                overlayMode = 'original';
                const modeSelect = document.getElementById('display-mode');
                if (modeSelect) modeSelect.value = 'original';
                saveState();
            } catch (error) {
                console.warn('Auto load dubbing subtitles failed:', error);
            }
        }

        // 绑定主播放器与配音音频的同步：播放/暂停/拖动/倍速都同步
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

        // Load saved API key
        const SAVED_KEY = 'sm_autoDub_apiKey';
        const SAVED_KEY_CHECKED = 'sm_autoDub_saveKey';
        const savedApiKey = localStorage.getItem(SAVED_KEY);
        const savedCheckState = localStorage.getItem(SAVED_KEY_CHECKED) === 'true';
        if (savedApiKey && apiKeyInput) {
            apiKeyInput.value = savedApiKey;
        }
        if (saveKeyCheckbox) {
            saveKeyCheckbox.checked = savedCheckState;
        }

        // Save API key on checkbox change
        if (saveKeyCheckbox && apiKeyInput) {
            saveKeyCheckbox.addEventListener('change', () => {
                if (saveKeyCheckbox.checked && apiKeyInput.value) {
                    localStorage.setItem(SAVED_KEY, apiKeyInput.value);
                } else if (!saveKeyCheckbox.checked) {
                    localStorage.removeItem(SAVED_KEY);
                }
                localStorage.setItem(SAVED_KEY_CHECKED, saveKeyCheckbox.checked);
            });
        }

        // Also save when user types in API key (if checkbox is already checked)
        if (apiKeyInput && saveKeyCheckbox) {
            apiKeyInput.addEventListener('input', () => {
                if (saveKeyCheckbox.checked && apiKeyInput.value) {
                    localStorage.setItem(SAVED_KEY, apiKeyInput.value);
                }
            });
        }

        // File Upload Logic
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
                const name = String(file.name || '').toLowerCase();
                if (!name.endsWith('.srt')) {
                    alert('字幕文件必须是 .srt');
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

        function handleAutoDubFile(file) {
            selectedFile = file;
            // 切换媒体时清空已选字幕，避免旧字幕误绑定到新视频。
            selectedSubtitleFile = null;
            if (subtitleInput) subtitleInput.value = '';
            if (subtitleNameDisplay) subtitleNameDisplay.textContent = '未选择字幕文件（默认自动识别）';
            if (subtitleModeSelect) subtitleModeSelect.value = 'source';
            // 切换新文件时清空旧区间，避免把上一个项目的配置误用于当前文件。
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

        // Start Logic
        if (startBtn) {
            startBtn.addEventListener('click', async () => {
                const sourceLang = document.getElementById('auto-dub-source').value;
                const targetLang = document.getElementById('auto-dub-target').value;
                const groupingStrategySelect = document.getElementById('auto-dub-grouping-strategy');
                const groupingStrategy = groupingStrategySelect ? groupingStrategySelect.value : 'sentence';
                const apiKey = document.getElementById('auto-dub-api-key').value;
                const autoPickRangesEl = document.getElementById('auto-dub-auto-pick-ranges');
                // 兜底默认关闭：当页面未渲染该控件时，避免误开启自动区间切分导致碎片分段。
                const autoPickRanges = autoPickRangesEl ? !!autoPickRangesEl.checked : false;
                // 字幕模式：source=源字幕需翻译，translated=已翻译字幕直接跳过翻译。
                const subtitleMode = subtitleModeSelect ? subtitleModeSelect.value : 'source';
                const skipTranslationBySubtitle = !!selectedSubtitleFile && subtitleMode === 'translated';

                if (!selectedFile) {
                    alert("Please select a video file first.");
                    return;
                }
                if (!apiKey && !skipTranslationBySubtitle) {
                    alert("Please enter your DeepSeek API Key.");
                    return;
                }
                autoDubStartedAtMs = Date.now();

                // UI Reset
                startBtn.disabled = true;
                statusContainer.style.display = 'block';
                resultsContainer.style.display = 'none';
                if (autoProgressFill) {
                    autoProgressFill.style.width = '5%';
                }
                if (selectedSubtitleFile) {
                    statusText.textContent = subtitleMode === 'translated'
                        ? "Initializing... (Skip ASR + Translation with uploaded translated subtitles)"
                        : "Initializing... (Skip ASR with uploaded subtitles)";
                } else {
                    statusText.textContent = "Initializing...";
                }
                statusText.className = 'status-text';

                // Reset steps
                ['step-transcribe', 'step-translate', 'step-dub'].forEach(id => {
                    document.getElementById(id).style.fontWeight = 'normal';
                    document.getElementById(id).style.color = 'var(--text-muted)';
                });
                if (taskLabel) taskLabel.textContent = 'Task —';
                if (lineProgressEl) lineProgressEl.textContent = 'Lines —';
                if (etaEl) etaEl.textContent = 'ETA —';

                try {
                    const formData = new FormData();
                    formData.append('video', selectedFile);
                    if (selectedSubtitleFile) {
                        formData.append('subtitle_file', selectedSubtitleFile);
                        formData.append('subtitle_mode', subtitleMode);
                    }
                    formData.append('source_lang', sourceLang);
                    formData.append('target_lang', targetLang);
                    formData.append('grouping_strategy', groupingStrategy);
                    formData.append('api_key', apiKey);
                    formData.append('auto_pick_ranges', autoPickRanges ? 'true' : 'false');
                    // 手动区间优先：存在时按结构化 JSON 透传给后端。
                    if (autoDubTimeRanges.length > 0) {
                        const payload = autoDubTimeRanges.map(item => ({
                            start_sec: Number(item.start),
                            end_sec: Number(item.end),
                        }));
                        formData.append('time_ranges', JSON.stringify(payload));
                    }

                    const res = await fetch('/dubbing/auto/start', { method: 'POST', body: formData });
                    if (!res.ok) {
                        const err = await res.json().catch(() => ({}));
                        throw new Error(err.detail || "Failed to start dubbing task");
                    }

                    const data = await res.json();
                    const taskId = data.task_id;
                    if (taskLabel && taskId) {
                        taskLabel.textContent = `Task · ${taskId.split('-')[0].toUpperCase()}`;
                    }

                    pollAutoDubStatus(taskId);

                } catch (e) {
                    console.error(e);
                    statusText.textContent = "Error: " + e.message;
                    statusText.className = 'status-text error';
                    startBtn.disabled = false;
                }
            });
        }

        function pollAutoDubStatus(taskId) {
            const interval = setInterval(async () => {
                try {
                    const res = await fetch(`/dubbing/auto/status/${taskId}`);
                    if (!res.ok) {
                        clearInterval(interval);
                        throw new Error("Status poll failed");
                    }

                    const data = await res.json();

                    // Update Progress
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

                    const eta = data.eta_seconds ?? data?.dub_progress?.eta_seconds;
                    if (etaEl) {
                        etaEl.textContent = formatEtaLabel(eta);
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
                        statusText.textContent = elapsedLabel ? `Process Complete · ${elapsedLabel}` : "Process Complete";
                        statusText.className = 'status-text success';
                        renderResults(data);
                    } else if (data.status === 'failed') {
                        clearInterval(interval);
                        startBtn.disabled = false;
                        statusText.textContent = "Failed: " + data.error;
                        statusText.className = 'status-text error';
                    }

                } catch (e) {
                    console.error(e);
                    clearInterval(interval);
                    statusText.textContent = "Polling Error: " + e.message;
                    startBtn.disabled = false;
                }
            }, 1200);
        }

        function updateStepHighlights(stage) {
            // stages: transcribing, translating, dubbing, finished
            const steps = {
                'transcribing': 'step-transcribe',
                'translating': 'step-translate',
                'dubbing': 'step-dub'
            };

            let normalized = stage;
            if (stage && stage.startsWith('dubbing')) normalized = 'dubbing';
            if (stage === 'finished') normalized = 'dubbing';

            const activeId = steps[normalized];
            for (const [key, id] of Object.entries(steps)) {
                const el = document.getElementById(id);
                if (el) {
                    if (key === normalized) {
                        el.style.fontWeight = 'bold';
                        el.style.color = 'var(--accent)';
                    } else {
                        // Mark previous as done if needed? simple highlighting for now
                        el.style.fontWeight = 'normal';
                        el.style.color = 'var(--text-muted)';
                    }
                }
            }
        }

        function renderResults(data) {
            resultsContainer.style.display = 'block';
            const links = resultsContainer.querySelector('.download-links');
            if (!links) return;
            links.innerHTML = '';

            // 自动加载该任务产出的 SRT 到播放器字幕层（失败不阻断下载与播放）
            autoLoadAutoDubSubtitles(data);

            // 结果回填后启用音轨切换：原音=当前预览媒体，配音=任务输出音频
            dubbedAudioUrl = pickDubbedAudioUrl(data);
            if (dubbedAudioUrl) {
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
});

// 5. Export Segments (Event Delegation)

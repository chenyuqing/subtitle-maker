const mediaUploadArea = document.getElementById('upload-area');
const mediaFileInput = document.getElementById('file-input');
const srtUploadArea = document.getElementById('srt-upload-area');
const srtFileInput = document.getElementById('srt-file-input');

const uploadStatus = document.getElementById('upload-status');
const videoPlayer = document.getElementById('video-player');
const videoPlaceholder = document.getElementById('video-placeholder');
const subtitleOverlay = document.getElementById('subtitle-overlay');

const transcribeBtn = document.getElementById('transcribe-btn');
const progressContainer = document.getElementById('progress-container');
const progressFill = document.querySelector('.progress-fill');
const progressText = document.getElementById('progress-text');

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
}

function clearState() {
    if (confirm("Are you sure you want to start a new project? This will clear current progress.")) {
        // Attempt to cancel current task if exists
        if (currentTaskId) {
            fetch(`/cancel/${currentTaskId}`, { method: 'POST' })
                .catch(err => console.error("Cancel failed", err));
        }

        // Release ASR model memory on the backend
        fetch('/model/asr/release', { method: 'POST' })
            .catch(err => console.error("Failed to release ASR model", err));

        localStorage.removeItem('sm_taskId');
        localStorage.removeItem('sm_filename');
        localStorage.removeItem('sm_originalFilename');
        localStorage.removeItem('sm_startTime');
        localStorage.removeItem('sm_originalSubtitles');
        localStorage.removeItem('sm_translatedSubtitles');
        // Keep API key
        location.reload();
    }
}

// Bind Clear Button
const newProjectBtn = document.getElementById('new-project-btn');
if (newProjectBtn) {
    newProjectBtn.addEventListener('click', clearState);
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

        if (overlayMode === 'original') {
            if (orig) textToShow = orig.text;
        } else if (overlayMode === 'translated') {
            if (trans) textToShow = trans.text;
        } else if (overlayMode === 'bilingual_orig_trans') {
            if (orig && trans) textToShow = `${orig.text}<br><span class="sub-secondary">${trans.text}</span>`;
            else if (orig) textToShow = orig.text;
            else if (trans) textToShow = trans.text;
        } else if (overlayMode === 'bilingual_trans_orig') {
            if (orig && trans) textToShow = `${trans.text}<br><span class="sub-secondary">${orig.text}</span>`;
            else if (trans) textToShow = trans.text;
            else if (orig) textToShow = orig.text;
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
        saveState();

        // Setup Video
        if (videoPlayer) {
            videoPlayer.src = data.url;
            videoPlayer.style.display = 'block';
        }
        if (videoPlaceholder) videoPlaceholder.style.display = 'none';

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

        // Always send local subtitles to ensure stateless translation works (e.g. after server restart)
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

// 4. Export
const exportBtn = document.getElementById('export-btn');
if (exportBtn) {
    exportBtn.addEventListener('click', async () => {
        const format = document.getElementById('export-format').value;
        const formData = new FormData();
        formData.append('task_id', currentTaskId);
        formData.append('format', format);

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

// --- Handler for SRT Upload ---
async function handleSrtUpload(file) {
    if (!file) return;

    if (uploadStatus) uploadStatus.textContent = "Uploading SRT...";

    const formData = new FormData();
    formData.append('file', file);

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
if (apiKeyInput) {
    apiKeyInput.addEventListener('input', () => {
        const val = apiKeyInput.value;
        localStorage.setItem('sm_apiKey', val);
    });
}

// --- Fullscreen Support ---
const fullscreenBtn = document.getElementById('fullscreen-btn');
const videoWrapper = document.querySelector('.video-wrapper');

if (fullscreenBtn && videoWrapper) {
    fullscreenBtn.addEventListener('click', () => {
        if (!document.fullscreenElement) {
            videoWrapper.requestFullscreen().catch(err => {
                alert(`Error attempting to enable fullscreen mode: ${err.message} (${err.name})`);
            });
        } else {
            document.exitFullscreen();
        }
    });
}

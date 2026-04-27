/**
 * 初始化 Agent 抽屉。
 * 该模块只处理 `agent-*` DOM、会话历史和聊天请求，不依赖其它页面状态。
 */
export function setupAgentDrawer(options = {}) {
    const fab = document.getElementById('agent-fab');
    const drawer = document.getElementById('agent-drawer');
    const closeBtn = document.getElementById('agent-close-btn');
    const backdrop = document.getElementById('agent-backdrop');
    const form = document.getElementById('agent-form');
    const input = document.getElementById('agent-input');
    const sendBtn = document.getElementById('agent-send-btn');
    const messagesEl = document.getElementById('agent-messages');
    const HISTORY_KEY = 'sm_agentMessages';
    const CONVERSATION_KEY = 'sm_agentConversationId';

    if (!fab || !drawer || !form || !input || !messagesEl) return;

    /**
     * 获取当前活动面板，帮助 Agent 返回更贴近上下文的建议。
     */
    function currentPanelName() {
        if (typeof options.getCurrentPanelName === 'function') {
            return options.getCurrentPanelName();
        }
        const activePanel = document.querySelector('.panel.active');
        return activePanel?.id || 'unknown';
    }

    /**
     * 切换抽屉开合态。
     */
    function setOpen(open) {
        drawer.classList.toggle('open', open);
        drawer.setAttribute('aria-hidden', open ? 'false' : 'true');
        fab.setAttribute('aria-expanded', open ? 'true' : 'false');
        if (backdrop) backdrop.hidden = !open;
        if (open) input.focus();
    }

    /**
     * 从 sessionStorage 读取会话历史。
     */
    function readHistory() {
        try {
            return JSON.parse(sessionStorage.getItem(HISTORY_KEY) || '[]');
        } catch (error) {
            return [];
        }
    }

    /**
     * 写入会话历史，并限制最大条数，避免无边界增长。
     */
    function writeHistory(items) {
        sessionStorage.setItem(HISTORY_KEY, JSON.stringify(items.slice(-20)));
    }

    /**
     * 渲染单条消息；统一使用 textContent，避免注入风险。
     */
    function renderMessage(item) {
        const bubble = document.createElement('div');
        bubble.className = `agent-message ${item.role || 'assistant'}`;
        bubble.textContent = item.text || '';
        if (Array.isArray(item.actions) && item.actions.length > 0) {
            const list = document.createElement('ul');
            list.className = 'agent-actions';
            item.actions.forEach((action) => {
                const li = document.createElement('li');
                li.textContent = action;
                list.appendChild(li);
            });
            bubble.appendChild(list);
        }
        messagesEl.appendChild(bubble);
        messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    /**
     * 首次加载或重新打开时恢复消息历史。
     */
    function renderHistory() {
        messagesEl.innerHTML = '';
        const history = readHistory();
        if (history.length === 0) {
            renderMessage({
                role: 'assistant',
                text: '我可以解释报错、说明参数含义、建议下一步。不会修改文件，也不会替你执行任务。',
            });
            return;
        }
        history.forEach(renderMessage);
    }

    /**
     * 发起 Agent 对话请求；API key 只随请求发送，不落本地存储。
     */
    async function sendAgentMessage(message) {
        const payload = {
            message,
            page: currentPanelName(),
            conversation_id: sessionStorage.getItem(CONVERSATION_KEY) || '',
            api_key: typeof options.getDeepSeekApiKey === 'function' ? options.getDeepSeekApiKey() : '',
        };
        const response = await fetch('/api/agent/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            const detail = data?.detail || {};
            throw new Error(detail.message || detail.code || 'Agent request failed');
        }
        if (data.conversation_id) {
            sessionStorage.setItem(CONVERSATION_KEY, data.conversation_id);
        }
        return data;
    }

    fab.addEventListener('click', () => setOpen(true));
    closeBtn?.addEventListener('click', () => setOpen(false));
    backdrop?.addEventListener('click', () => setOpen(false));

    input.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            form.requestSubmit();
        }
    });

    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const message = input.value.trim();
        if (!message) return;

        const history = readHistory();
        const userItem = { role: 'user', text: message };
        history.push(userItem);
        writeHistory(history);
        renderMessage(userItem);
        input.value = '';
        if (sendBtn) sendBtn.disabled = true;

        const loadingItem = { role: 'assistant', text: '正在分析...' };
        renderMessage(loadingItem);
        const loadingNode = messagesEl.lastElementChild;

        try {
            const data = await sendAgentMessage(message);
            const assistantItem = {
                role: 'assistant',
                text: data.reply || '没有收到有效回复。',
                actions: Array.isArray(data.suggested_actions) ? data.suggested_actions : [],
            };
            loadingNode?.remove();
            const nextHistory = readHistory();
            nextHistory.push(assistantItem);
            writeHistory(nextHistory);
            renderMessage(assistantItem);
        } catch (error) {
            loadingNode?.remove();
            const errorItem = { role: 'error', text: error.message || 'Agent 请求失败。' };
            const nextHistory = readHistory();
            nextHistory.push(errorItem);
            writeHistory(nextHistory);
            renderMessage(errorItem);
        } finally {
            if (sendBtn) sendBtn.disabled = false;
            input.focus();
        }
    });

    renderHistory();
}

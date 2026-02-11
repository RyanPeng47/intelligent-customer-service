/**
 * 智能客服系统 - 前端交互逻辑
 * Phase 1: 用户端 (登录/对话/历史/转人工)
 * Phase 2: 坐席端 (工单队列/对话/接单/AI Copilot)
 */

const API_BASE = '';  // 同源，无需前缀

// ============================================================
// 全局状态
// ============================================================
const state = {
    isLoggedIn: false,
    userId: '',
    userRole: 'user', // user | agent | audit | admin
    currentView: 'user',       // user | agent | audit | knowledge
    currentTicketId: null,
    currentTicketStatus: null,
    lastMessageId: 0,          // 用于轮询
    pollTimer: null,
    isSending: false,
    // Phase 2: 坐席端状态
    agentCurrentTicketId: null,
    agentCurrentTicketStatus: null,
    agentLastMessageId: 0,
    agentPollTimer: null,
    agentIsSending: false,
    agentFilter: 'all',
    agentTicketsCache: [],
    copilotSuggestionText: '',
    // Phase 4: 质检端状态
    auditTicketsCache: [],
    auditSelectedTicketId: null,
    auditFilterStatus: 'all', // all | resolved | rated
    auditFilterScore: 'all', // all | unrated | rated
    auditFilterDays: 'all', // all | 7 | 30
    auditRateScore: 5,
    // Phase 3: 知识库状态
    knowledgeTab: 'docs', // docs | qa
    knowledgeData: null,
};

// ============================================================
// 工具函数
// ============================================================

async function apiCall(url, method = 'GET', body = null) {
    const options = {
        method,
        headers: { 'Content-Type': 'application/json' },
    };
    if (body) options.body = JSON.stringify(body);

    const resp = await fetch(API_BASE + url, options);
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: '网络错误' }));
        throw new Error(err.detail || '请求失败');
    }
    return resp.json();
}

function formatTime(isoStr) {
    if (!isoStr) return '';
    const d = new Date(isoStr);
    const pad = n => String(n).padStart(2, '0');
    return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function formatDateTime(isoStr) {
    if (!isoStr) return '--';
    const d = new Date(isoStr);
    if (Number.isNaN(d.getTime())) return '--';
    return d.toLocaleString();
}

function getStatusText(status) {
    const map = {
        'pending_ai': 'AI 对话中',
        'queued': '等待人工',
        'in_progress': '人工服务中',
        'resolved': '已完结',
        'rated': '已评价',
    };
    return map[status] || status;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function getAllowedViews() {
    if (state.userRole === 'admin') return ['user', 'agent', 'audit', 'knowledge'];
    if (state.userRole === 'agent') return ['agent'];
    if (state.userRole === 'audit') return ['audit'];
    return ['user'];
}

function applyRolePermissions() {
    const allowed = new Set(getAllowedViews());
    document.querySelectorAll('.nav-tab').forEach(tab => {
        const view = tab.dataset.view;
        tab.style.display = allowed.has(view) ? 'inline-flex' : 'none';
    });
}

// ============================================================
// 登录
// ============================================================

async function handleLogin(e) {
    e.preventDefault();
    const username = document.getElementById('username').value.trim();
    const password = document.getElementById('password').value.trim();
    const entry = document.getElementById('login-entry').value;
    const errorEl = document.getElementById('login-error');

    if (!username || !password) {
        errorEl.textContent = '请输入用户名和密码';
        errorEl.style.display = 'block';
        return false;
    }

    try {
        const data = await apiCall('/api/login', 'POST', { username, password });
        state.isLoggedIn = true;
        state.userId = data.user_id;
        state.userRole = entry || 'user';
        document.getElementById('current-user').textContent = data.username;
        document.getElementById('login-page').style.display = 'none';
        document.getElementById('app-layout').classList.add('active');
        applyRolePermissions();
        const firstView = getAllowedViews()[0];
        switchView(firstView);
    } catch (err) {
        errorEl.textContent = err.message;
        errorEl.style.display = 'block';
    }
    return false;
}

function handleLogout() {
    state.isLoggedIn = false;
    state.userId = '';
    state.userRole = 'user';
    state.currentTicketId = null;
    stopPolling();
    document.getElementById('login-page').style.display = 'flex';
    document.getElementById('app-layout').classList.remove('active');
    document.querySelectorAll('.nav-tab').forEach(tab => {
        tab.style.display = 'inline-flex';
    });
}

// ============================================================
// 视图切换
// ============================================================

function switchView(view) {
    if (!state.isLoggedIn) return;
    if (!getAllowedViews().includes(view)) return;

    state.currentView = view;
    stopPolling();

    // 更新导航标签
    document.querySelectorAll('.nav-tab').forEach(tab => {
        tab.classList.toggle('active', tab.dataset.view === view);
    });

    // 显示/隐藏视图面板
    document.querySelectorAll('.view-panel').forEach(panel => {
        panel.style.display = 'none';
    });
    const target = document.getElementById(`view-${view}`);
    if (target) target.style.display = 'flex';

    // 根据视图加载数据
    if (view === 'user') loadUserTickets();
    if (view === 'agent') loadAgentTickets();
    if (view === 'audit') loadAuditTickets();
    if (view === 'knowledge') loadKnowledgeData();
}

// ============================================================
// 用户端: 会话管理
// ============================================================

async function loadUserTickets() {
    try {
        const data = await apiCall(`/api/tickets/history?user_id=${state.userId}`);
        renderUserTicketList(data.tickets);
    } catch (err) {
        console.error('加载历史失败:', err);
    }
}

function renderUserTicketList(tickets) {
    const container = document.getElementById('user-ticket-list');
    if (!tickets || tickets.length === 0) {
        container.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-muted);font-size:13px;">暂无历史会话</div>';
        return;
    }

    container.innerHTML = tickets.map(t => `
        <div class="sidebar-item ${state.currentTicketId === t.id ? 'active' : ''}"
             onclick="selectUserTicket(${t.id})">
            <div class="item-header">
                <span class="item-title">
                    <span class="status-dot ${t.status}"></span>
                    工单 #${t.id}
                </span>
                <span class="item-time">${formatTime(t.created_at)}</span>
            </div>
            <div class="item-preview">${escapeHtml(t.last_message || '无消息')}</div>
        </div>
    `).join('');
}

async function createNewChat() {
    state.currentTicketId = null;
    state.currentTicketStatus = null;
    state.lastMessageId = 0;
    stopPolling();

    document.getElementById('user-chat-header').style.display = 'none';
    document.getElementById('user-input-area').style.display = 'block';
    document.getElementById('user-message-input').disabled = false;
    document.getElementById('btn-send-user').disabled = false;

    const msgContainer = document.getElementById('user-chat-messages');
    msgContainer.innerHTML = `
        <div class="chat-empty">
            <div class="empty-icon">🤖</div>
            <p>新对话已就绪</p>
            <p style="font-size:12px;color:var(--text-muted);">请输入您的问题，AI 将为您解答</p>
        </div>
    `;

    // 取消侧边栏选中
    document.querySelectorAll('#user-ticket-list .sidebar-item').forEach(el => {
        el.classList.remove('active');
    });
}

async function selectUserTicket(ticketId) {
    state.currentTicketId = ticketId;
    state.lastMessageId = 0;
    stopPolling();

    // 加载消息
    try {
        const data = await apiCall(`/api/messages/${ticketId}`);
        state.currentTicketStatus = data.status;
        renderChatMessages(data.messages, 'user');
        updateChatHeader(ticketId, data.status);

        // 侧边栏高亮
        document.querySelectorAll('#user-ticket-list .sidebar-item').forEach(el => {
            el.classList.remove('active');
        });
        // 找到对应的 sidebar-item 并高亮
        loadUserTickets();

        // 开始轮询 (等待坐席/AI 回复)
        if (data.status !== 'resolved' && data.status !== 'rated') {
            startPolling(ticketId);
        }

        // 控制输入框
        const canSend = !['resolved', 'rated'].includes(data.status);
        document.getElementById('user-input-area').style.display = 'block';
        document.getElementById('user-message-input').disabled = !canSend;
        document.getElementById('btn-send-user').disabled = !canSend;
        if (!canSend) {
            document.getElementById('user-message-input').placeholder = '该工单已完结，无法继续对话';
        } else {
            document.getElementById('user-message-input').placeholder = '输入您的问题...';
        }

    } catch (err) {
        console.error('加载消息失败:', err);
    }
}

function updateChatHeader(ticketId, status) {
    const header = document.getElementById('user-chat-header');
    header.style.display = 'flex';
    document.getElementById('user-ticket-id').textContent = `工单 #${ticketId}`;

    const statusEl = document.getElementById('user-ticket-status');
    statusEl.textContent = getStatusText(status);
    statusEl.className = `ticket-status status-badge-${status}`;

    // 转人工按钮: 仅在 pending_ai 状态下显示
    const btnTransfer = document.getElementById('btn-transfer');
    btnTransfer.style.display = status === 'pending_ai' ? 'inline-flex' : 'none';
}

// ============================================================
// 聊天消息渲染
// ============================================================

function renderChatMessages(messages, view) {
    const containerId = view === 'user' ? 'user-chat-messages' : 'agent-chat-messages';
    const container = document.getElementById(containerId);

    if (!messages || messages.length === 0) {
        container.innerHTML = `
            <div class="chat-empty">
                <div class="empty-icon">💬</div>
                <p>暂无消息</p>
            </div>
        `;
        return;
    }

    container.innerHTML = messages.map(msg => renderSingleMessage(msg)).join('');

    // 更新 lastMessageId
    if (messages.length > 0) {
        state.lastMessageId = messages[messages.length - 1].id;
    }

    // 滚动到底部
    container.scrollTop = container.scrollHeight;
}

function renderSingleMessage(msg) {
    const avatarMap = {
        'user': '👤',
        'ai': '🤖',
        'agent': '👮',
        'system': '⚙️',
    };
    const avatar = avatarMap[msg.sender] || '❓';
    const time = formatTime(msg.created_at);

    return `
        <div class="message ${msg.sender}">
            ${msg.sender !== 'system' ? `<div class="avatar">${avatar}</div>` : ''}
            <div>
                <div class="bubble">${escapeHtml(msg.content)}</div>
                ${msg.sender !== 'system' ? `<span class="source-tag">${time}</span>` : ''}
            </div>
        </div>
    `;
}

function appendMessage(msg, target = 'user') {
    const containerId = target === 'user' ? 'user-chat-messages' : 'agent-chat-messages';
    const container = document.getElementById(containerId);

    // 如果是空提示，先清除
    const empty = container.querySelector('.chat-empty');
    if (empty) empty.remove();

    container.insertAdjacentHTML('beforeend', renderSingleMessage(msg));
    container.scrollTop = container.scrollHeight;

    if (target === 'user') {
        if (msg.id && msg.id > state.lastMessageId) {
            state.lastMessageId = msg.id;
        }
    } else {
        if (msg.id && msg.id > state.agentLastMessageId) {
            state.agentLastMessageId = msg.id;
        }
    }
}

// ============================================================
// 用户端: 发送消息
// ============================================================

async function sendUserMessage() {
    const input = document.getElementById('user-message-input');
    const message = input.value.trim();
    if (!message || state.isSending) return;

    state.isSending = true;
    input.value = '';
    document.getElementById('btn-send-user').disabled = true;

    // 立即在界面上显示用户消息
    appendMessage({
        sender: 'user',
        content: message,
        created_at: new Date().toISOString(),
    });

    // 显示 AI 思考中
    const thinkingEl = document.createElement('div');
    thinkingEl.className = 'message ai';
    thinkingEl.id = 'ai-thinking';
    thinkingEl.innerHTML = `
        <div class="avatar">🤖</div>
        <div>
            <div class="bubble">正在思考<span class="loading-dots"></span></div>
        </div>
    `;
    document.getElementById('user-chat-messages').appendChild(thinkingEl);
    document.getElementById('user-chat-messages').scrollTop = document.getElementById('user-chat-messages').scrollHeight;

    try {
        const data = await apiCall('/api/chat', 'POST', {
            ticket_id: state.currentTicketId,
            message: message,
            user_id: state.userId,
        });

        // 移除思考中
        const thinking = document.getElementById('ai-thinking');
        if (thinking) thinking.remove();

        // 如果是新工单，更新状态
        if (!state.currentTicketId && data.ticket_id) {
            state.currentTicketId = data.ticket_id;
            state.currentTicketStatus = 'pending_ai';
            updateChatHeader(data.ticket_id, 'pending_ai');
            loadUserTickets();
            startPolling(data.ticket_id);
        }

        // 显示 AI 回复
        if (data.reply) {
            appendMessage({
                sender: 'ai',
                content: data.reply,
                created_at: new Date().toISOString(),
            });
        }

    } catch (err) {
        const thinking = document.getElementById('ai-thinking');
        if (thinking) thinking.remove();

        appendMessage({
            sender: 'system',
            content: `⚠️ 发送失败: ${err.message}`,
            created_at: new Date().toISOString(),
        });
    } finally {
        state.isSending = false;
        document.getElementById('btn-send-user').disabled = false;
        input.focus();
    }
}

// ============================================================
// 用户端: 转人工
// ============================================================

async function transferToHuman() {
    if (!state.currentTicketId) return;
    if (!confirm('确认将此对话转接至人工坐席？')) return;

    try {
        await apiCall('/api/tickets/transfer', 'POST', {
            ticket_id: state.currentTicketId,
        });

        state.currentTicketStatus = 'queued';
        updateChatHeader(state.currentTicketId, 'queued');
        loadUserTickets();

        // 立即刷新消息，显示后端的系统提示
        await apiCall(`/api/messages/poll/${state.currentTicketId}?after_id=${state.lastMessageId}`)
            .then(data => {
                if (data.messages) data.messages.forEach(msg => appendMessage(msg));
            });

    } catch (err) {
        alert('转人工失败: ' + err.message);
    }
}

// ============================================================
// 轮询: 实时同步消息
// ============================================================

function startPolling(ticketId) {
    stopPolling();
    state.pollTimer = setInterval(async () => {
        try {
            const data = await apiCall(`/api/messages/poll/${ticketId}?after_id=${state.lastMessageId}`);

            // 状态变化
            if (data.status !== state.currentTicketStatus) {
                state.currentTicketStatus = data.status;
                updateChatHeader(ticketId, data.status);
                loadUserTickets();

                if (['resolved', 'rated'].includes(data.status)) {
                    document.getElementById('user-message-input').disabled = true;
                    document.getElementById('btn-send-user').disabled = true;
                    document.getElementById('user-message-input').placeholder = '该工单已完结';
                    stopPolling();
                }
            }

            // 新消息 (排除自己刚发的)
            if (data.messages && data.messages.length > 0) {
                data.messages.forEach(msg => {
                    appendMessage(msg);
                });
            }
        } catch (err) {
            console.error('轮询错误:', err);
        }
    }, 2000); // 每2秒轮询一次
}

function stopPolling() {
    if (state.pollTimer) {
        clearInterval(state.pollTimer);
        state.pollTimer = null;
    }
}

// ============================================================
// Phase 2: 坐席端逻辑
// ============================================================

async function loadAgentTickets() {
    try {
        const data = await apiCall('/api/agent/tickets');
        state.agentTicketsCache = data.tickets || [];
        renderAgentTicketList();
    } catch (err) {
        console.error('加载工单队列失败:', err);
    }
}

function filterAgentTickets(filter) {
    state.agentFilter = filter;
    // 更新筛选按钮
    document.querySelectorAll('#view-agent .filter-tab').forEach(tab => {
        tab.classList.toggle('active', tab.dataset.filter === filter);
    });
    renderAgentTicketList();
}

function renderAgentTicketList() {
    const container = document.getElementById('agent-ticket-list');
    let tickets = state.agentTicketsCache;

    // 按筛选条件过滤
    if (state.agentFilter !== 'all') {
        tickets = tickets.filter(t => t.status === state.agentFilter);
    }

    if (tickets.length === 0) {
        container.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-muted);font-size:13px;">暂无工单</div>';
        return;
    }

    container.innerHTML = tickets.map(t => `
        <div class="sidebar-item ${state.agentCurrentTicketId === t.id ? 'active' : ''}"
             onclick="selectAgentTicket(${t.id})">
            <div class="item-header">
                <span class="item-title">
                    <span class="status-dot ${t.status}"></span>
                    #${t.id}
                </span>
                <span class="item-time">${formatTime(t.created_at)}</span>
            </div>
            <div class="item-preview">
                <span style="color:var(--accent-purple);font-size:11px;">👤 ${escapeHtml(t.user_id || '匿名')}</span>
                · ${escapeHtml(t.last_message || getStatusText(t.status))}
            </div>
        </div>
    `).join('');
}

async function selectAgentTicket(ticketId) {
    state.agentCurrentTicketId = ticketId;
    state.agentLastMessageId = 0;
    stopAgentPolling();

    try {
        const data = await apiCall(`/api/messages/${ticketId}`);
        state.agentCurrentTicketStatus = data.status;
        renderChatMessages(data.messages, 'agent');
        updateAgentChatHeader(ticketId, data.status, data.user_id);
        updateCopilotInfo(ticketId, data);

        // 刷新侧边栏高亮
        renderAgentTicketList();

        // 开始轮询
        if (!['resolved', 'rated'].includes(data.status)) {
            startAgentPolling(ticketId);
        }

        // 输入框控制
        const canReply = ['queued', 'in_progress'].includes(data.status);
        document.getElementById('agent-input-area').style.display = 'block';
        document.getElementById('agent-message-input').disabled = !canReply;
        document.getElementById('btn-send-agent').disabled = !canReply;
        if (!canReply) {
            document.getElementById('agent-message-input').placeholder = data.status === 'resolved' ? '工单已完结' : '该工单当前不可回复';
        } else {
            document.getElementById('agent-message-input').placeholder = '输入回复内容...';
        }

        // Copilot 按钮
        document.getElementById('btn-copilot-gen').disabled = !canReply;

    } catch (err) {
        console.error('加载工单消息失败:', err);
    }
}

function updateAgentChatHeader(ticketId, status, userId) {
    const header = document.getElementById('agent-chat-header');
    header.style.display = 'flex';
    document.getElementById('agent-ticket-id').textContent = `工单 #${ticketId}`;

    const statusEl = document.getElementById('agent-ticket-status');
    statusEl.textContent = getStatusText(status);
    statusEl.className = `ticket-status status-badge-${status}`;

    // 用户标签
    const userTag = document.getElementById('agent-ticket-user');
    if (userId) {
        userTag.textContent = `👤 ${userId}`;
        userTag.style.display = 'inline-block';
    } else {
        userTag.style.display = 'none';
    }

    // 按钮: 接入 vs 完结
    document.getElementById('btn-pickup').style.display = status === 'queued' ? 'inline-flex' : 'none';
    document.getElementById('btn-close-ticket').style.display = status === 'in_progress' ? 'inline-flex' : 'none';
}

function updateCopilotInfo(ticketId, data) {
    const infoBox = document.getElementById('copilot-ticket-info');
    const msgCount = data.messages ? data.messages.length : 0;
    infoBox.innerHTML = `
        <div class="info-row"><span class="info-label">工单编号</span><span class="info-value">#${ticketId}</span></div>
        <div class="info-row"><span class="info-label">用户</span><span class="info-value">${escapeHtml(data.user_id || '匿名')}</span></div>
        <div class="info-row"><span class="info-label">状态</span><span class="info-value">${getStatusText(data.status)}</span></div>
        <div class="info-row"><span class="info-label">消息数</span><span class="info-value">${msgCount} 条</span></div>
    `;
    // 重置建议
    document.getElementById('copilot-suggestion').innerHTML = '<p class="copilot-placeholder">点击下方按钮生成 AI 建议回复</p>';
    document.getElementById('btn-copilot-use').style.display = 'none';
    state.copilotSuggestionText = '';
}

// ============================================================
// 坐席端: 接入工单
// ============================================================

async function agentPickupTicket() {
    if (!state.agentCurrentTicketId) return;

    try {
        await apiCall('/api/agent/pickup', 'POST', {
            ticket_id: state.agentCurrentTicketId,
        });

        state.agentCurrentTicketStatus = 'in_progress';
        updateAgentChatHeader(state.agentCurrentTicketId, 'in_progress');
        loadAgentTickets();

        // 刷新消息 (显示「坐席已接入」系统消息)
        const pollData = await apiCall(`/api/messages/poll/${state.agentCurrentTicketId}?after_id=${state.agentLastMessageId}`);
        if (pollData.messages) {
            pollData.messages.forEach(msg => appendMessage(msg, 'agent'));
        }

        // 启用输入框
        document.getElementById('agent-message-input').disabled = false;
        document.getElementById('btn-send-agent').disabled = false;
        document.getElementById('agent-message-input').placeholder = '输入回复内容...';
        document.getElementById('btn-copilot-gen').disabled = false;

    } catch (err) {
        alert('接入失败: ' + err.message);
    }
}

// ============================================================
// 坐席端: 发送回复
// ============================================================

async function sendAgentMessage() {
    const input = document.getElementById('agent-message-input');
    const message = input.value.trim();
    if (!message || state.agentIsSending) return;

    state.agentIsSending = true;
    input.value = '';
    document.getElementById('btn-send-agent').disabled = true;

    // 乐观展示
    appendMessage({
        sender: 'agent',
        content: message,
        created_at: new Date().toISOString(),
    }, 'agent');

    try {
        await apiCall('/api/agent/reply', 'POST', {
            ticket_id: state.agentCurrentTicketId,
            message: message,
        });
        loadAgentTickets();
    } catch (err) {
        appendMessage({
            sender: 'system',
            content: `⚠️ 回复失败: ${err.message}`,
            created_at: new Date().toISOString(),
        }, 'agent');
    } finally {
        state.agentIsSending = false;
        document.getElementById('btn-send-agent').disabled = false;
        input.focus();
    }
}

// ============================================================
// 坐席端: 完结工单
// ============================================================

async function agentCloseTicket() {
    if (!state.agentCurrentTicketId) return;
    if (!confirm('确认完结此工单？')) return;

    try {
        await apiCall('/api/agent/close', 'POST', {
            ticket_id: state.agentCurrentTicketId,
        });

        state.agentCurrentTicketStatus = 'resolved';
        updateAgentChatHeader(state.agentCurrentTicketId, 'resolved');
        loadAgentTickets();

        // 刷新消息
        const pollData = await apiCall(`/api/messages/poll/${state.agentCurrentTicketId}?after_id=${state.agentLastMessageId}`);
        if (pollData.messages) {
            pollData.messages.forEach(msg => appendMessage(msg, 'agent'));
        }

        // 禁用输入
        document.getElementById('agent-message-input').disabled = true;
        document.getElementById('btn-send-agent').disabled = true;
        document.getElementById('agent-message-input').placeholder = '工单已完结';
        document.getElementById('btn-copilot-gen').disabled = true;
        stopAgentPolling();

    } catch (err) {
        alert('完结失败: ' + err.message);
    }
}

// ============================================================
// 坐席端: AI Copilot
// ============================================================

async function generateCopilotSuggestion() {
    if (!state.agentCurrentTicketId) return;

    const btn = document.getElementById('btn-copilot-gen');
    const box = document.getElementById('copilot-suggestion');
    btn.disabled = true;
    btn.classList.add('loading');
    btn.textContent = '🤖 正在生成...';
    box.innerHTML = '<p class="copilot-placeholder">AI 正在分析对话，生成建议回复...</p>';
    document.getElementById('btn-copilot-use').style.display = 'none';

    try {
        const data = await apiCall('/api/copilot/suggest', 'POST', {
            ticket_id: state.agentCurrentTicketId,
        });

        state.copilotSuggestionText = data.suggestion || '无建议';
        box.textContent = state.copilotSuggestionText;
        document.getElementById('btn-copilot-use').style.display = 'block';

    } catch (err) {
        box.innerHTML = `<p class="copilot-placeholder" style="color:var(--accent-red);">生成失败: ${escapeHtml(err.message)}</p>`;
    } finally {
        btn.disabled = false;
        btn.classList.remove('loading');
        btn.textContent = '🤖 生成智能回复';
    }
}

function useCopilotSuggestion() {
    if (!state.copilotSuggestionText) return;
    const input = document.getElementById('agent-message-input');
    input.value = state.copilotSuggestionText;
    input.focus();
    // 隐藏采纳按钮
    document.getElementById('btn-copilot-use').style.display = 'none';
}

// ============================================================
// 坐席端: 轮询
// ============================================================

function startAgentPolling(ticketId) {
    stopAgentPolling();
    state.agentPollTimer = setInterval(async () => {
        try {
            const data = await apiCall(`/api/messages/poll/${ticketId}?after_id=${state.agentLastMessageId}`);

            // 状态变化
            if (data.status !== state.agentCurrentTicketStatus) {
                state.agentCurrentTicketStatus = data.status;
                updateAgentChatHeader(ticketId, data.status);
                loadAgentTickets();

                if (['resolved', 'rated'].includes(data.status)) {
                    document.getElementById('agent-message-input').disabled = true;
                    document.getElementById('btn-send-agent').disabled = true;
                    stopAgentPolling();
                }
            }

            // 新消息
            if (data.messages && data.messages.length > 0) {
                data.messages.forEach(msg => appendMessage(msg, 'agent'));
            }
        } catch (err) {
            console.error('坐席轮询错误:', err);
        }
    }, 2000);
}

function stopAgentPolling() {
    if (state.agentPollTimer) {
        clearInterval(state.agentPollTimer);
        state.agentPollTimer = null;
    }
}

// ============================================================
// Phase 4: 质检端
// ============================================================

async function loadAuditTickets() {
    try {
        const data = await apiCall('/api/admin/tickets/resolved');
        state.auditTicketsCache = data.tickets || [];
        renderAuditTicketList(getFilteredAuditTickets());
        renderAuditStats(state.auditTicketsCache);
    } catch (err) {
        console.error('加载质检工单失败:', err);
    }
}

function getFilteredAuditTickets() {
    let tickets = [...state.auditTicketsCache];

    if (state.auditFilterStatus !== 'all') {
        tickets = tickets.filter(t => t.status === state.auditFilterStatus);
    }

    if (state.auditFilterScore === 'unrated') {
        tickets = tickets.filter(t => !t.score || Number(t.score) <= 0);
    }
    if (state.auditFilterScore === 'rated') {
        tickets = tickets.filter(t => Number(t.score) > 0);
    }

    if (state.auditFilterDays !== 'all') {
        const days = Number(state.auditFilterDays);
        if (days > 0) {
            const since = Date.now() - days * 24 * 3600 * 1000;
            tickets = tickets.filter(t => {
                const ts = new Date(t.created_at).getTime();
                return !Number.isNaN(ts) && ts >= since;
            });
        }
    }

    return tickets;
}

function applyAuditFilters() {
    state.auditFilterStatus = document.getElementById('audit-filter-status')?.value || 'all';
    state.auditFilterScore = document.getElementById('audit-filter-score')?.value || 'all';
    state.auditFilterDays = document.getElementById('audit-filter-days')?.value || 'all';
    renderAuditTicketList(getFilteredAuditTickets());
}

function renderAuditStats(tickets) {
    const statsEl = document.getElementById('audit-stats');
    if (!statsEl) return;

    const total = tickets.length;
    const rated = tickets.filter(t => Number(t.score) > 0).length;
    const avgScore = rated > 0
        ? (tickets.filter(t => Number(t.score) > 0).reduce((s, t) => s + Number(t.score), 0) / rated).toFixed(2)
        : '--';

    statsEl.innerHTML = `
        <div class="summary-item"><span>工单总数</span><strong>${total}</strong></div>
        <div class="summary-item"><span>已评分</span><strong>${rated}</strong></div>
        <div class="summary-item"><span>平均分</span><strong>${avgScore}</strong></div>
    `;
}

function renderAuditTicketList(tickets) {
    const container = document.getElementById('audit-ticket-list');
    if (!container) return;

    if (!tickets || tickets.length === 0) {
        container.innerHTML = '<div class="knowledge-empty">暂无符合条件的工单</div>';
        return;
    }

    container.innerHTML = tickets.map(t => `
        <div class="sidebar-item ${state.auditSelectedTicketId === t.id ? 'active' : ''}"
             onclick="selectAuditTicket(${t.id})">
            <div class="item-header">
                <span class="item-title">
                    <span class="status-dot ${t.status}"></span>
                    工单 #${t.id}
                </span>
                <span class="item-time">${formatTime(t.created_at)}</span>
            </div>
            <div class="item-preview">
                👤 ${escapeHtml(t.user_id || '匿名')} · ${Number(t.score) > 0 ? `评分 ${t.score}` : '未评分'}
            </div>
        </div>
    `).join('');
}

async function selectAuditTicket(ticketId) {
    state.auditSelectedTicketId = ticketId;
    renderAuditTicketList(getFilteredAuditTickets());

    const current = state.auditTicketsCache.find(t => t.id === ticketId);
    const titleEl = document.getElementById('audit-detail-title');
    const metaEl = document.getElementById('audit-detail-meta');
    if (titleEl) titleEl.textContent = `工单 #${ticketId}`;
    if (metaEl && current) {
        metaEl.textContent = `用户: ${current.user_id || '匿名'} · 状态: ${getStatusText(current.status)} · 评分: ${current.score || '未评分'} · 消息数: ${current.message_count || 0}`;
    }

    const btnRate = document.getElementById('btn-audit-rate');
    if (btnRate) btnRate.disabled = !current;

    try {
        const data = await apiCall(`/api/messages/${ticketId}`);
        renderAuditMessages(data.messages || []);
        const summaryBox = document.getElementById('audit-summary-content');
        if (summaryBox) {
            const summary = (current?.summary || '').trim();
            summaryBox.textContent = summary || '暂无评分备注';
        }
    } catch (err) {
        console.error('加载质检工单消息失败:', err);
    }
}

function renderAuditMessages(messages) {
    const container = document.getElementById('audit-chat-messages');
    if (!container) return;

    if (!messages || messages.length === 0) {
        container.innerHTML = '<div class="knowledge-empty">暂无消息记录</div>';
        return;
    }

    container.innerHTML = messages.map(msg => renderSingleMessage(msg)).join('');
    container.scrollTop = container.scrollHeight;
}

function openAuditRateModal() {
    const ticketId = state.auditSelectedTicketId;
    if (!ticketId) {
        alert('请先选择工单');
        return;
    }

    const t = state.auditTicketsCache.find(x => x.id === ticketId);
    state.auditRateScore = Number(t?.score) > 0 ? Number(t.score) : 5;

    const modal = document.getElementById('audit-rate-modal');
    const commentInput = document.getElementById('audit-rate-comment');
    const titleEl = document.getElementById('audit-rate-title');
    if (titleEl) titleEl.textContent = `工单 #${ticketId} 服务评分`;
    if (commentInput) commentInput.value = t?.summary || '';
    setAuditRateScore(state.auditRateScore);
    if (modal) modal.style.display = 'flex';
}

function closeAuditRateModal() {
    const modal = document.getElementById('audit-rate-modal');
    if (modal) modal.style.display = 'none';
}

function setAuditRateScore(score) {
    state.auditRateScore = score;
    document.querySelectorAll('.audit-star').forEach(star => {
        const starScore = Number(star.dataset.score || 0);
        star.classList.toggle('active', starScore <= score);
    });
}

async function submitAuditRating() {
    if (!state.auditSelectedTicketId) return;

    const comment = (document.getElementById('audit-rate-comment')?.value || '').trim();
    const submitBtn = document.getElementById('btn-submit-audit-rate');
    if (submitBtn) submitBtn.disabled = true;

    try {
        await apiCall('/api/admin/tickets/rate', 'POST', {
            ticket_id: state.auditSelectedTicketId,
            score: state.auditRateScore,
            comment: comment,
        });

        closeAuditRateModal();
        await loadAuditTickets();
        await selectAuditTicket(state.auditSelectedTicketId);
    } catch (err) {
        alert(`评分失败: ${err.message}`);
    } finally {
        if (submitBtn) submitBtn.disabled = false;
    }
}

// ============================================================
// Phase 3: 知识库管理
// ============================================================

async function loadKnowledgeData() {
    try {
        const data = await apiCall('/api/knowledge/list?limit=120');
        state.knowledgeData = data;
        renderKnowledgeSummary(data);
        renderKnowledgeSources(data.sources || []);
        renderKnowledgeDocs(data.vectors || []);
        renderKnowledgeQAPairs(data.qa_pairs || []);
    } catch (err) {
        const resultEl = document.getElementById('knowledge-upload-result');
        if (resultEl) {
            resultEl.className = 'knowledge-upload-result error';
            resultEl.textContent = `加载失败: ${err.message}`;
        }
    }
}

function switchKnowledgeTab(tab) {
    state.knowledgeTab = tab;
    document.querySelectorAll('.knowledge-tab').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.kbTab === tab);
    });
    document.getElementById('knowledge-docs-list').style.display = tab === 'docs' ? 'block' : 'none';
    document.getElementById('knowledge-qa-list').style.display = tab === 'qa' ? 'block' : 'none';
}

function renderKnowledgeSummary(data) {
    const summaryEl = document.getElementById('knowledge-summary');
    if (!summaryEl) return;

    const sourceCount = (data.sources || []).length;
    const vectorCount = (data.vectors || []).length;
    const qaCount = (data.qa_pairs || []).length;

    summaryEl.innerHTML = `
        <div class="summary-item"><span>来源文件</span><strong>${sourceCount}</strong></div>
        <div class="summary-item"><span>文档切片</span><strong>${vectorCount}</strong></div>
        <div class="summary-item"><span>QA 对</span><strong>${qaCount}</strong></div>
    `;
}

function renderKnowledgeSources(sources) {
    const container = document.getElementById('knowledge-sources');
    if (!container) return;

    if (!sources || sources.length === 0) {
        container.innerHTML = '<p class="copilot-placeholder">暂无来源数据</p>';
        return;
    }

    container.innerHTML = sources.map(s => `
        <div class="knowledge-source-item">
            <div class="knowledge-source-main">
                <div class="knowledge-source-name">${escapeHtml(s.source || 'unknown')}</div>
                <div class="knowledge-source-time">更新于 ${formatDateTime(s.updated_at)}</div>
            </div>
            <div class="knowledge-source-badges">
                <span class="knowledge-badge">切片 ${s.vector_count || 0}</span>
                <span class="knowledge-badge">QA ${s.qa_count || 0}</span>
            </div>
        </div>
    `).join('');
}

function renderKnowledgeDocs(vectors) {
    const container = document.getElementById('knowledge-docs-list');
    if (!container) return;

    if (!vectors || vectors.length === 0) {
        container.innerHTML = '<div class="knowledge-empty">暂无文档切片</div>';
        return;
    }

    container.innerHTML = vectors.map(item => `
        <div class="knowledge-list-item">
            <div class="knowledge-item-meta">
                <span>#${item.id}</span>
                <span>${escapeHtml(item.source || 'unknown')}</span>
                <span>${formatDateTime(item.created_at)}</span>
            </div>
            <div class="knowledge-item-content">${escapeHtml(item.content || '')}</div>
        </div>
    `).join('');
}

function renderKnowledgeQAPairs(qaPairs) {
    const container = document.getElementById('knowledge-qa-list');
    if (!container) return;

    if (!qaPairs || qaPairs.length === 0) {
        container.innerHTML = '<div class="knowledge-empty">暂无 QA 对</div>';
        return;
    }

    container.innerHTML = qaPairs.map(item => `
        <div class="knowledge-list-item">
            <div class="knowledge-item-meta">
                <span>#${item.id}</span>
                <span>${escapeHtml(item.source || 'unknown')}</span>
                <span>${formatDateTime(item.created_at)}</span>
            </div>
            <div class="knowledge-item-q">Q: ${escapeHtml(item.question || '')}</div>
            <div class="knowledge-item-a">A: ${escapeHtml(item.answer || '')}</div>
        </div>
    `).join('');
}

async function uploadKnowledgeFile() {
    const input = document.getElementById('knowledge-file-input');
    const btn = document.getElementById('btn-knowledge-upload');
    const resultEl = document.getElementById('knowledge-upload-result');

    if (!input || !input.files || input.files.length === 0) {
        resultEl.className = 'knowledge-upload-result error';
        resultEl.textContent = '请先选择 .md 文件';
        return;
    }

    const file = input.files[0];
    if (!file.name.toLowerCase().endsWith('.md')) {
        resultEl.className = 'knowledge-upload-result error';
        resultEl.textContent = '仅支持 .md 文件';
        return;
    }

    const formData = new FormData();
    formData.append('file', file);

    btn.disabled = true;
    btn.textContent = '上传中...';
    resultEl.className = 'knowledge-upload-result';
    resultEl.textContent = '正在处理，请稍候...';

    try {
        const resp = await fetch('/api/knowledge/upload', {
            method: 'POST',
            body: formData,
        });
        const data = await resp.json();
        if (!resp.ok) {
            throw new Error(data.detail || '上传失败');
        }

        resultEl.className = 'knowledge-upload-result success';
        resultEl.textContent = `入库成功：${data.source}，切片 ${data.vector_count} 条，QA ${data.qa_count} 条`;
        input.value = '';
        await loadKnowledgeData();
        switchKnowledgeTab(state.knowledgeTab);
    } catch (err) {
        resultEl.className = 'knowledge-upload-result error';
        resultEl.textContent = `上传失败: ${err.message}`;
    } finally {
        btn.disabled = false;
        btn.textContent = '上传并入库';
    }
}

// ============================================================
// 初始化
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('username').focus();

    const auditModal = document.getElementById('audit-rate-modal');
    if (auditModal) {
        auditModal.addEventListener('click', (e) => {
            if (e.target === auditModal) closeAuditRateModal();
        });
    }

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closeAuditRateModal();
    });
});

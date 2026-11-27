// ==================== Outlook Mail Minimalist Workbench Core ====================

let csrfToken = null;
let workbenchMode = 'outlook'; // 'outlook' | 'imap' | 'temp'
let groups = [];
let allAccounts = [];
let filteredAccounts = [];
let selectedGroupId = 'all';
let activeAccountEmail = null;
let selectedAccountIds = new Set();
let editingGroupId = null;
let selectedColor = '#2563eb';
let fetchedEmails = [];
let openedEmailContext = null; // { emailAddr, messageId, subject, from, date, body, html }
let isDetailTrusted = false;
let lastErrorDetail = null;
const accountPasswordCache = {};

// ==================== 通用工具 & CSRF ====================

function translateAppTextLocal(text) {
    if (window.I18n && typeof window.I18n.translateText === 'function') {
        return window.I18n.translateText(text);
    }
    return text;
}

function pickApiMessage(payload, fallbackZh, fallbackEn) {
    if (window.I18n && typeof window.I18n.pickApiMessage === 'function') {
        return window.I18n.pickApiMessage(payload, fallbackZh, fallbackEn);
    }
    return (payload && payload.message) || fallbackZh || '';
}

function escapeHtml(text) {
    if (text === null || text === undefined) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}

function getCSRFToken() {
    if (csrfToken) return csrfToken;
    const meta = document.querySelector('meta[name="csrf-token"]');
    csrfToken = meta ? meta.getAttribute('content') : '';
    return csrfToken;
}

// 自动为写请求注入 X-CSRFToken
(function wrapFetchWithCsrf() {
    const rawFetch = window.fetch.bind(window);
    window.fetch = async function (input, init = {}) {
        const method = ((init && init.method) || 'GET').toUpperCase();
        const url = typeof input === 'string' ? input : (input && input.url) || '';
        const isSameOrigin = !url.startsWith('http://') && !url.startsWith('https://');
        if (isSameOrigin && ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
            const headers = new Headers(init.headers || {});
            const token = getCSRFToken();
            if (token && !headers.has('X-CSRFToken')) {
                headers.set('X-CSRFToken', token);
            }
            init = { ...init, headers };
        }
        return rawFetch(input, init);
    };
})();

function formatDateTime(raw) {
    if (!raw) return '';
    const d = new Date(raw);
    if (isNaN(d.getTime())) return String(raw).slice(0, 16);
    const pad = n => String(n).padStart(2, '0');
    return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function showToast(message, type = 'info', errorDetail = null, persistent = false) {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    const icon = type === 'success' ? '✅' : type === 'error' ? '❌' : type === 'warning' ? '⚠️' : 'ℹ️';
    const textSpan = document.createElement('span');
    textSpan.style.flex = '1';
    textSpan.textContent = `${icon} ${translateAppTextLocal(message)}`;
    toast.appendChild(textSpan);

    if (errorDetail) {
        const detailBtn = document.createElement('button');
        detailBtn.type = 'button';
        detailBtn.className = 'btn btn-sm';
        detailBtn.textContent = '详情';
        detailBtn.onclick = () => showErrorDetailModal(errorDetail);
        toast.appendChild(detailBtn);
    }

    container.appendChild(toast);
    if (!persistent) {
        setTimeout(() => {
            if (toast.parentNode) toast.remove();
        }, type === 'error' ? 5000 : 3200);
    } else {
        const closeBtn = document.createElement('button');
        closeBtn.type = 'button';
        closeBtn.className = 'btn-icon-mini';
        closeBtn.textContent = '×';
        closeBtn.onclick = () => toast.remove();
        toast.appendChild(closeBtn);
    }
}

function handleApiError(data, fallbackMsg = '操作失败') {
    const err = data && data.error ? data.error : data;
    const msg = (err && (err.message || err.msg)) || (data && data.message) || fallbackMsg;
    showToast(msg, 'error', err && typeof err === 'object' ? err : null);
}

async function copyToClipboard(text, label = '') {
    if (!text) return;
    try {
        await navigator.clipboard.writeText(text);
        showToast(label ? `已复制${label}` : '已复制到剪贴板', 'success');
    } catch (_) {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        ta.remove();
        showToast(label ? `已复制${label}` : '已复制到剪贴板', 'success');
    }
}

// ==================== 统一错误详情弹窗 ====================

function showErrorDetailModal(error) {
    lastErrorDetail = error || {};
    const titleEl = document.getElementById('errorDetailModalTitle');
    const standardBody = document.getElementById('errorModalStandardBody');
    const fetchBody = document.getElementById('errorModalFetchBody');
    if (titleEl) titleEl.textContent = '❌ 错误详情';
    if (standardBody) standardBody.style.display = 'block';
    if (fetchBody) fetchBody.style.display = 'none';

    document.getElementById('errorModalUserMessage').textContent = (error && error.message) || '发生未知错误';
    document.getElementById('errorModalCode').textContent = (error && error.code) || '-';
    document.getElementById('errorModalType').textContent = (error && error.type) || '-';
    document.getElementById('errorModalStatus').textContent = (error && error.status) || '-';
    document.getElementById('errorModalTraceId').textContent = (error && error.trace_id) || '-';

    const detailBox = document.getElementById('errorModalDetailsContainer');
    const detailPre = document.getElementById('errorModalDetails');
    detailPre.textContent = typeof error?.details === 'string'
        ? error.details
        : JSON.stringify(error?.details || error || {}, null, 2);
    detailBox.style.display = 'none';
    document.getElementById('toggleTraceBtn').textContent = '显示技术详情';
    document.getElementById('errorDetailModal').classList.add('show');
}

function showEmailFetchErrorModal(details) {
    const titleEl = document.getElementById('errorDetailModalTitle');
    const standardBody = document.getElementById('errorModalStandardBody');
    const fetchBody = document.getElementById('errorModalFetchBody');
    if (titleEl) titleEl.textContent = '❌ 获取邮件失败';
    if (standardBody) standardBody.style.display = 'none';
    if (fetchBody) fetchBody.style.display = 'block';

    const names = { graph: 'Graph API', imap_new: 'IMAP (New)', imap_old: 'IMAP (Old)', imap_generic: 'IMAP' };
    let html = '';
    Object.entries(details || {}).forEach(([k, v]) => {
        if (v === undefined || v === null) return;
        const msg = typeof v === 'string' ? v : (v.message || v.details || JSON.stringify(v));
        const code = typeof v === 'object' ? (v.code || '-') : '-';
        html += `<div class="error-message-box" style="margin-bottom:8px;">
            <div style="font-weight:700;color:var(--clr-danger);margin-bottom:4px;">${escapeHtml(names[k] || k)}</div>
            <div>${escapeHtml(msg)}</div>
            <div style="font-size:11.5px;color:var(--text-muted);margin-top:4px;">Code: ${escapeHtml(code)}</div>
        </div>`;
    });
    document.getElementById('emailFetchErrorContent').innerHTML = html || '<div>无详细错误信息</div>';
    document.getElementById('errorDetailModal').classList.add('show');
}

function hideErrorDetailModal() {
    const modal = document.getElementById('errorDetailModal');
    if (modal) modal.classList.remove('show');
}

function toggleStackTrace() {
    const box = document.getElementById('errorModalDetailsContainer');
    const btn = document.getElementById('toggleTraceBtn');
    const open = box.style.display === 'none';
    box.style.display = open ? 'block' : 'none';
    btn.textContent = open ? '隐藏技术详情' : '显示技术详情';
}

function copyErrorDetails() {
    copyToClipboard(JSON.stringify(lastErrorDetail || {}, null, 2), '错误详情');
}

// ==================== 顶部模式切换（Outlook / IMAP / CF 临时邮箱） ====================

function switchWorkbenchMode(mode) {
    workbenchMode = mode;
    document.querySelectorAll('.mode-tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.mode === mode);
    });

    const mailboxView = document.getElementById('view-mailbox');
    const tempView = document.getElementById('view-temp-emails');

    if (mode === 'temp') {
        mailboxView.classList.add('view-hidden');
        tempView.classList.remove('view-hidden');
        if (typeof loadTempEmailsWorkbench === 'function') loadTempEmailsWorkbench();
        return;
    }

    tempView.classList.add('view-hidden');
    mailboxView.classList.remove('view-hidden');

    const isImap = mode === 'imap';
    document.getElementById('sidebarMailboxTitle').textContent = isImap ? 'IMAP 邮箱列表' : 'Outlook 邮箱列表';
    document.getElementById('outlookRefreshActions').style.display = isImap ? 'none' : 'grid';
    document.getElementById('outlookProtocolPills').style.display = isImap ? 'none' : 'inline-flex';
    document.getElementById('imapModeBadge').style.display = isImap ? 'inline-flex' : 'none';
    document.getElementById('emailEmptySub').textContent = isImap
        ? '支持通用 IMAP 账号直连取件，自动遵循全局或分组代理设置'
        : '支持 IMAP OAuth2 + Graph API 双协议并行取件，自动识别验证码一键复制';

    selectedAccountIds.clear();
    activeAccountEmail = null;
    applyAccountFilters();
}

function syncProtocolPillStyles() {
    const imapCb = document.getElementById('protoImapToggle');
    const graphCb = document.getElementById('protoGraphToggle');
    // 至少保留一个协议勾选
    if (!imapCb.checked && !graphCb.checked) {
        graphCb.checked = true;
        showToast('请至少保留一个取件协议', 'warning');
    }
    document.getElementById('protoImapPill').classList.toggle('inactive', !imapCb.checked);
    document.getElementById('protoGraphPill').classList.toggle('inactive', !graphCb.checked);
}

// ==================== 分组管理 ====================

async function loadGroups() {
    try {
        const res = await fetch('/api/groups');
        const data = await res.json();
        if (!data.success) return;
        groups = (data.groups || []).filter(g => g.name !== '临时邮箱');
        renderGroupSelectors();
    } catch (e) {
        console.error('加载分组失败:', e);
    }
}

function renderGroupSelectors() {
    const filterSelect = document.getElementById('groupFilterSelect');
    if (filterSelect) {
        const prev = selectedGroupId;
        filterSelect.innerHTML = '<option value="all">全部分组</option>' +
            groups.map(g => `<option value="${g.id}">${escapeHtml(g.name)} (${g.account_count || 0})</option>`).join('');
        filterSelect.value = groups.some(g => String(g.id) === String(prev)) ? String(prev) : 'all';
        selectedGroupId = filterSelect.value;
    }

    ['importGroupId', 'editAccountGroup', 'exportGroupSelect', 'batchMoveGroupSelect'].forEach(id => {
        const el = document.getElementById(id);
        if (!el) return;
        const prevVal = el.value;
        el.innerHTML = groups.map(g => `<option value="${g.id}">${escapeHtml(g.name)}</option>`).join('');
        if (prevVal && groups.some(g => String(g.id) === String(prevVal))) {
            el.value = prevVal;
        }
    });
}

function onGroupFilterChange(val) {
    selectedGroupId = val || 'all';
    selectedAccountIds.clear();
    applyAccountFilters();
}

function showAddGroupModal(groupObj = null) {
    editingGroupId = groupObj ? groupObj.id : null;
    document.getElementById('groupModalTitle').textContent = editingGroupId ? '编辑分组' : '添加分组';
    document.getElementById('groupName').value = groupObj ? (groupObj.name || '') : '';
    document.getElementById('groupDesc').value = groupObj ? (groupObj.description || '') : '';
    const mode = groupObj ? (groupObj.proxy_mode || (groupObj.proxy_url ? 'custom' : 'inherit')) : 'inherit';
    const radio = document.querySelector(`input[name="groupProxyMode"][value="${mode}"]`);
    if (radio) radio.checked = true;
    document.getElementById('groupProxyUrl').value = groupObj ? (groupObj.proxy_url || '') : '';
    document.getElementById('groupProxyTestResult').textContent = '';
    onGroupProxyModeChange();

    selectedColor = (groupObj && groupObj.color) || '#2563eb';
    document.querySelectorAll('#colorPicker .color-option').forEach(el => {
        el.classList.toggle('selected', el.dataset.color === selectedColor);
    });

    const delBtn = document.getElementById('btnDeleteGroupInModal');
    if (delBtn) delBtn.style.display = editingGroupId && editingGroupId !== 1 ? 'inline-flex' : 'none';
    document.getElementById('addGroupModal').classList.add('show');
}

function editSelectedGroup() {
    if (selectedGroupId === 'all') {
        showToast('请先在下拉框中选择一个具体分组再编辑', 'info');
        return;
    }
    const g = groups.find(item => String(item.id) === String(selectedGroupId));
    if (g) showAddGroupModal(g);
}

function hideAddGroupModal() {
    document.getElementById('addGroupModal').classList.remove('show');
    editingGroupId = null;
}

function onGroupProxyModeChange() {
    const mode = document.querySelector('input[name="groupProxyMode"]:checked')?.value || 'inherit';
    document.getElementById('groupCustomProxyWrap').style.display = mode === 'custom' ? 'block' : 'none';
}

async function testGroupProxy() {
    const proxyUrl = document.getElementById('groupProxyUrl').value.trim();
    const btn = document.getElementById('btnTestGroupProxy');
    const resultEl = document.getElementById('groupProxyTestResult');
    if (typeof runProxyConnectivityTest === 'function') {
        await runProxyConnectivityTest(proxyUrl, btn, resultEl, '🔗 测试');
    }
}

async function saveGroup() {
    const name = document.getElementById('groupName').value.trim();
    if (!name) {
        showToast('请输入分组名称', 'error');
        return;
    }
    const proxy_mode = document.querySelector('input[name="groupProxyMode"]:checked')?.value || 'inherit';
    const proxy_url = proxy_mode === 'custom' ? document.getElementById('groupProxyUrl').value.trim() : '';
    if (proxy_mode === 'custom' && !proxy_url) {
        showToast('自定义代理模式下请填写代理地址', 'error');
        return;
    }
    const payload = {
        name,
        description: document.getElementById('groupDesc').value.trim(),
        color: selectedColor,
        proxy_mode,
        proxy_url
    };
    const url = editingGroupId ? `/api/groups/${editingGroupId}` : '/api/groups';
    const method = editingGroupId ? 'PUT' : 'POST';
    try {
        const res = await fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.success) {
            hideAddGroupModal();
            showToast(editingGroupId ? '分组已更新' : '分组已创建', 'success');
            await loadGroups();
            await loadAllAccounts();
        } else {
            handleApiError(data, '保存分组失败');
        }
    } catch (_) {
        showToast('网络错误，保存分组失败', 'error');
    }
}

async function deleteEditingGroup() {
    if (!editingGroupId || editingGroupId === 1) return;
    if (!confirm('确认删除该分组？组内账号会自动移至默认分组。')) return;
    try {
        const res = await fetch(`/api/groups/${editingGroupId}`, { method: 'DELETE' });
        const data = await res.json();
        if (data.success) {
            hideAddGroupModal();
            selectedGroupId = 'all';
            showToast('分组已删除', 'success');
            await loadGroups();
            await loadAllAccounts();
        } else {
            handleApiError(data, '删除分组失败');
        }
    } catch (_) {
        showToast('删除分组失败', 'error');
    }
}

// ==================== 账号加载、渲染、导入与编辑 ====================

async function loadAllAccounts() {
    try {
        const collected = [];
        let page = 1;
        while (page <= 20) {
            const qs = new URLSearchParams({ page: String(page), page_size: '100' });
            const res = await fetch(`/api/accounts?${qs.toString()}`);
            const data = await res.json();
            if (!data.success) break;
            const batch = data.accounts || [];
            collected.push(...batch);
            const total = Number(data.total || collected.length);
            if (!batch.length || collected.length >= total) break;
            page += 1;
        }
        allAccounts = collected.filter(a => a.provider !== 'cloudflare_temp_mail');
        applyAccountFilters();
    } catch (e) {
        console.error('加载账号失败:', e);
    }
}

function filterVisibleAccounts() {
    applyAccountFilters();
}

function applyAccountFilters() {
    const keyword = (document.getElementById('accountSearchInput')?.value || '').trim().toLowerCase();
    const targetType = workbenchMode === 'imap' ? 'imap' : 'outlook';

    filteredAccounts = allAccounts.filter(acc => {
        const accType = (acc.account_type || 'outlook').toLowerCase();
        if (targetType === 'imap' ? accType !== 'imap' : accType === 'imap') return false;
        if (selectedGroupId !== 'all' && String(acc.group_id) !== String(selectedGroupId)) return false;
        if (keyword) {
            const hay = `${acc.email || ''} ${acc.remark || ''} ${(acc.tags || []).map(t => t.name || t).join(' ')}`.toLowerCase();
            if (!hay.includes(keyword)) return false;
        }
        return true;
    });

    renderAccountList();
}

function renderAccountList() {
    const container = document.getElementById('accountList');
    const countBadge = document.getElementById('accountCountBadge');
    if (countBadge) countBadge.textContent = String(filteredAccounts.length);

    if (!filteredAccounts.length) {
        container.innerHTML = `<div class="empty-state">
            <div class="empty-state-icon">✉️</div>
            <div class="empty-state-title">暂无邮箱</div>
            <div class="empty-state-sub">点击上方按钮批量导入</div>
        </div>`;
        updateSelectionUi();
        return;
    }

    container.innerHTML = filteredAccounts.map(acc => {
        const isChecked = selectedAccountIds.has(acc.id);
        const isActive = activeAccountEmail === acc.email;
        const isImap = (acc.account_type || 'outlook').toLowerCase() === 'imap';
        const dotClass = isImap ? 'imap' : (acc.last_refresh_status === 'failed' || acc.status === 'inactive' ? 'err' : 'ok');
        const statusTip = isImap ? 'IMAP 通用邮箱' : (dotClass === 'err' ? `上次刷新异常：${acc.last_refresh_error || '请刷新令牌'}` : 'Outlook 令牌状态正常');
        const remark = acc.remark ? escapeHtml(acc.remark) : (acc.group_name ? escapeHtml(acc.group_name) : '');

        return `<div class="account-item ${isActive ? 'active' : ''}" onclick="selectAccountItem(${acc.id}, '${escapeHtml(acc.email)}')">
            <input type="checkbox" class="account-item-checkbox" ${isChecked ? 'checked' : ''}
                onclick="event.stopPropagation(); toggleAccountSelection(${acc.id}, this.checked)">
            <div class="account-item-main">
                <div class="account-item-top">
                    <span class="status-dot ${dotClass}" data-tip="${escapeHtml(statusTip)}"></span>
                    <span class="account-email-text" title="${escapeHtml(acc.email)}">${escapeHtml(acc.email)}</span>
                </div>
                <div class="account-item-meta">
                    <span class="account-remark-text">${remark || (isImap ? 'IMAP' : 'Outlook')}</span>
                    <div class="account-item-actions" onclick="event.stopPropagation()">
                        <button type="button" class="btn-icon-mini" onclick="copyToClipboard('${escapeHtml(acc.email)}', '邮箱地址')" data-tip="复制邮箱地址">📋</button>
                        <button type="button" class="btn-icon-mini" onclick="copyAccountPasswordQuick(${acc.id})" data-tip="复制已保存的账号密码">🔑</button>
                        <button type="button" class="btn-icon-mini" onclick="showEditAccountModal(${acc.id})" data-tip="编辑分组、备注、凭据或 Telegram 推送开关">✏️</button>
                    </div>
                </div>
            </div>
        </div>`;
    }).join('');

    updateSelectionUi();
}

function selectAccountItem(accountId, emailAddr) {
    activeAccountEmail = emailAddr;
    renderAccountList();
}

function toggleAccountSelection(accountId, checked) {
    if (checked) selectedAccountIds.add(accountId);
    else selectedAccountIds.delete(accountId);
    updateSelectionUi();
}

function toggleSelectAllVisible(checked) {
    filteredAccounts.forEach(acc => {
        if (checked) selectedAccountIds.add(acc.id);
        else selectedAccountIds.delete(acc.id);
    });
    renderAccountList();
}

function updateSelectionUi() {
    const visibleSelected = filteredAccounts.filter(a => selectedAccountIds.has(a.id)).length;
    const countEl = document.getElementById('selectedAccountCount');
    if (countEl) countEl.textContent = String(visibleSelected);

    const allCb = document.getElementById('selectAllCheckbox');
    if (allCb) {
        allCb.checked = filteredAccounts.length > 0 && visibleSelected === filteredAccounts.length;
    }
    const showBatch = visibleSelected > 0;
    document.getElementById('btnSidebarMoveGroup').style.display = showBatch ? 'inline-flex' : 'none';
    document.getElementById('btnSidebarDelete').style.display = showBatch ? 'inline-flex' : 'none';
}

async function copyAccountPasswordQuick(accountId) {
    if (accountPasswordCache[accountId]) {
        await copyToClipboard(accountPasswordCache[accountId], '密码');
        return;
    }
    try {
        const res = await fetch(`/api/accounts/${accountId}/reveal-password`, { method: 'POST' });
        const data = await res.json();
        if (data.success && data.password) {
            accountPasswordCache[accountId] = data.password;
            await copyToClipboard(data.password, '密码');
        } else {
            showToast((data.error && data.error.message) || '该账号未保存密码', 'warning');
        }
    } catch (_) {
        showToast('获取密码失败', 'error');
    }
}

// 批量导入
function showAddAccountModal() {
    const modeSelect = document.getElementById('importModeSelect');
    modeSelect.value = workbenchMode === 'imap' ? 'imap' : 'outlook';
    onImportModeChange();
    document.getElementById('batchAccountInput').value = '';
    document.getElementById('importRemarkInput').value = '';
    document.getElementById('importProgressHint').textContent = '';
    if (selectedGroupId !== 'all') {
        document.getElementById('importGroupId').value = String(selectedGroupId);
    }
    document.getElementById('addAccountModal').classList.add('show');
}

function hideAddAccountModal() {
    document.getElementById('addAccountModal').classList.remove('show');
}

function onImportModeChange() {
    const mode = document.getElementById('importModeSelect').value;
    const isImap = mode === 'imap';
    document.getElementById('imapImportServerRow').style.display = isImap ? 'flex' : 'none';
    document.getElementById('batchAccountInput').placeholder = isImap
        ? 'user@qq.com----authorization_code\n或 user@domain.com----password----imap.domain.com----993'
        : 'user@outlook.com----password----client_id----refresh_token';
}

function onImapPresetChange(preset) {
    const map = {
        qq: ['imap.qq.com', 993],
        '163': ['imap.163.com', 993],
        '126': ['imap.126.com', 993],
        gmail: ['imap.gmail.com', 993],
        aliyun: ['imap.aliyun.com', 993]
    };
    if (map[preset]) {
        document.getElementById('imapImportHost').value = map[preset][0];
        document.getElementById('imapImportPort').value = map[preset][1];
    }
}

async function submitBatchImport() {
    const raw = document.getElementById('batchAccountInput').value.trim();
    if (!raw) {
        showToast('请粘贴至少一条账号信息', 'error');
        return;
    }
    const mode = document.getElementById('importModeSelect').value;
    const groupId = parseInt(document.getElementById('importGroupId').value, 10) || 1;
    const remark = document.getElementById('importRemarkInput').value.trim();
    const lines = raw.split(/\r?\n/).map(l => l.trim()).filter(Boolean);

    const btn = document.getElementById('btnConfirmImport');
    const hint = document.getElementById('importProgressHint');
    btn.disabled = true;

    let added = 0;
    let updated = 0;
    let failed = 0;
    const CHUNK = 50;

    try {
        for (let i = 0; i < lines.length; i += CHUNK) {
            const slice = lines.slice(i, i + CHUNK);
            hint.textContent = `导入中 ${Math.min(i + slice.length, lines.length)} / ${lines.length}…`;
            const payload = {
                account_string: slice.join('\n'),
                group_id: groupId,
                provider: mode === 'imap' ? (document.getElementById('imapPresetSelect').value || 'custom') : 'outlook',
                remark
            };
            if (mode === 'imap') {
                payload.imap_host = document.getElementById('imapImportHost').value.trim();
                payload.imap_port = parseInt(document.getElementById('imapImportPort').value, 10) || 993;
            }
            const res = await fetch('/api/accounts', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            if (data.success) {
                added += data.added || data.created || (data.account ? 1 : 0);
                updated += data.updated || 0;
                failed += data.failed || 0;
            } else {
                failed += slice.length;
                if (lines.length <= CHUNK) {
                    handleApiError(data, '导入失败');
                    btn.disabled = false;
                    return;
                }
            }
        }
        hideAddAccountModal();
        showToast(`导入完成：新增 ${added}，更新 ${updated}${failed ? `，失败 ${failed}` : ''}`, failed ? 'warning' : 'success');
        await loadGroups();
        await loadAllAccounts();
    } catch (_) {
        showToast('导入请求失败', 'error');
    } finally {
        btn.disabled = false;
        hint.textContent = '';
    }
}

// 编辑账号
function showEditAccountModal(accountId) {
    const acc = allAccounts.find(a => a.id === accountId);
    if (!acc) return;
    const isImap = (acc.account_type || 'outlook').toLowerCase() === 'imap';
    document.getElementById('editAccountId').value = acc.id;
    document.getElementById('editAccountType').value = isImap ? 'imap' : 'outlook';
    document.getElementById('editAccountEmail').value = acc.email || '';
    document.getElementById('editAccountGroup').value = String(acc.group_id || 1);
    document.getElementById('editAccountRemark').value = acc.remark || '';
    document.getElementById('editOutlookFields').style.display = isImap ? 'none' : 'block';
    document.getElementById('editImapFields').style.display = isImap ? 'block' : 'none';
    document.getElementById('editClientId').value = acc.client_id || '';
    document.getElementById('editClientId').dataset.originalValue = acc.client_id || '';
    document.getElementById('editRefreshToken').value = '';
    document.getElementById('editImapHost').value = acc.imap_host || '';
    document.getElementById('editImapPort').value = acc.imap_port || 993;
    document.getElementById('editImapPassword').value = '';
    document.getElementById('editTelegramPush').checked = Boolean(acc.telegram_push_enabled);
    document.getElementById('editAccountModal').classList.add('show');
}

function hideEditAccountModal() {
    document.getElementById('editAccountModal').classList.remove('show');
}

async function saveAccountEdit() {
    const id = parseInt(document.getElementById('editAccountId').value, 10);
    const isImap = document.getElementById('editAccountType').value === 'imap';
    const payload = {
        group_id: parseInt(document.getElementById('editAccountGroup').value, 10) || 1,
        remark: document.getElementById('editAccountRemark').value.trim(),
        telegram_push_enabled: document.getElementById('editTelegramPush').checked
    };
    if (isImap) {
        payload.imap_host = document.getElementById('editImapHost').value.trim();
        payload.imap_port = parseInt(document.getElementById('editImapPort').value, 10) || 993;
        const pw = document.getElementById('editImapPassword').value.trim();
        if (pw) payload.imap_password = pw;
    } else {
        const cidInput = document.getElementById('editClientId');
        const cid = cidInput.value.trim();
        const rt = document.getElementById('editRefreshToken').value.trim();
        if (cid !== (cidInput.dataset.originalValue || '') || rt) {
            if (!cid || !rt) {
                showToast('更新 Outlook 凭据时需同时填写 Client ID 和 Refresh Token', 'error');
                return;
            }
            payload.client_id = cid;
            payload.refresh_token = rt;
        }
    }
    try {
        const res = await fetch(`/api/accounts/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.success) {
            delete accountPasswordCache[id];
            hideEditAccountModal();
            showToast('账号已更新', 'success');
            await loadGroups();
            await loadAllAccounts();
        } else {
            handleApiError(data, '更新账号失败');
        }
    } catch (_) {
        showToast('更新账号失败', 'error');
    }
}

async function deleteEditingAccount() {
    const id = parseInt(document.getElementById('editAccountId').value, 10);
    if (!id || !confirm('确认永久删除该账号？')) return;
    try {
        const res = await fetch(`/api/accounts/${id}`, { method: 'DELETE' });
        const data = await res.json();
        if (data.success) {
            selectedAccountIds.delete(id);
            delete accountPasswordCache[id];
            hideEditAccountModal();
            showToast('账号已删除', 'success');
            await loadGroups();
            await loadAllAccounts();
        } else {
            handleApiError(data, '删除失败');
        }
    } catch (_) {
        showToast('删除失败', 'error');
    }
}

// 批量移动 & 批量删除
function showBatchMoveGroupModal() {
    if (!selectedAccountIds.size) return;
    document.getElementById('batchMoveGroupModal').classList.add('show');
}

function hideBatchMoveGroupModal() {
    document.getElementById('batchMoveGroupModal').classList.remove('show');
}

async function confirmBatchMoveGroup() {
    const groupId = parseInt(document.getElementById('batchMoveGroupSelect').value, 10);
    const ids = Array.from(selectedAccountIds);
    if (!groupId || !ids.length) return;
    try {
        const res = await fetch('/api/accounts/batch-update-group', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ account_ids: ids, group_id: groupId })
        });
        const data = await res.json();
        if (data.success) {
            hideBatchMoveGroupModal();
            selectedAccountIds.clear();
            showToast('已批量移动分组', 'success');
            await loadGroups();
            await loadAllAccounts();
        } else {
            handleApiError(data, '批量移动失败');
        }
    } catch (_) {
        showToast('批量移动失败', 'error');
    }
}

async function showBatchDeleteConfirm() {
    const ids = Array.from(selectedAccountIds);
    if (!ids.length) return;
    if (!confirm(`确认永久删除已选中的 ${ids.length} 个账号？此操作不可撤销。`)) return;
    try {
        const res = await fetch('/api/accounts/batch-delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ account_ids: ids })
        });
        const data = await res.json();
        if (data.success) {
            ids.forEach(id => delete accountPasswordCache[id]);
            selectedAccountIds.clear();
            showToast(`已删除 ${ids.length} 个账号`, 'success');
            await loadGroups();
            await loadAllAccounts();
        } else {
            handleApiError(data, '批量删除失败');
        }
    } catch (_) {
        showToast('批量删除失败', 'error');
    }
}

// 导出 & 标签
function showExportModal() {
    document.getElementById('exportVerifyPassword').value = '';
    if (selectedGroupId !== 'all') {
        document.getElementById('exportGroupSelect').value = String(selectedGroupId);
    }
    document.getElementById('exportModal').classList.add('show');
}

function hideExportModal() {
    document.getElementById('exportModal').classList.remove('show');
}

async function confirmExportGroup() {
    const groupId = document.getElementById('exportGroupSelect').value;
    const password = document.getElementById('exportVerifyPassword').value;
    if (!password) {
        showToast('请输入登录密码进行验证', 'error');
        return;
    }
    try {
        const vRes = await fetch('/api/export/verify', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ password })
        });
        const vData = await vRes.json();
        if (!vData.success || !vData.verify_token) {
            handleApiError(vData, '密码验证失败');
            return;
        }
        hideExportModal();
        window.location.href = `/api/groups/${groupId}/export?verify_token=${encodeURIComponent(vData.verify_token)}`;
        showToast('已开始下载导出文件', 'success');
    } catch (_) {
        showToast('导出验证失败', 'error');
    }
}

async function showTagManagementModal() {
    document.getElementById('tagManagementModal').classList.add('show');
    await loadTagsList();
}

function hideTagManagementModal() {
    document.getElementById('tagManagementModal').classList.remove('show');
}

async function loadTagsList() {
    const box = document.getElementById('tagListContainer');
    try {
        const res = await fetch('/api/tags');
        const data = await res.json();
        const tags = data.tags || [];
        if (!tags.length) {
            box.innerHTML = '<span style="font-size:12.5px;color:var(--text-muted);">暂无自定义标签</span>';
            return;
        }
        box.innerHTML = tags.map(t => `<span class="tag-chip">
            ${escapeHtml(t.name)}
            <button type="button" class="btn-icon-mini" style="width:16px;height:16px;" onclick="deleteTagItem(${t.id})">×</button>
        </span>`).join('');
    } catch (_) {
        box.innerHTML = '<span style="color:var(--clr-danger);">加载失败</span>';
    }
}

async function createNewTag() {
    const input = document.getElementById('newTagName');
    const name = input.value.trim();
    if (!name) return;
    const res = await fetch('/api/tags', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name })
    });
    const data = await res.json();
    if (data.success) {
        input.value = '';
        await loadTagsList();
    } else {
        handleApiError(data, '添加标签失败');
    }
}

async function deleteTagItem(tagId) {
    const res = await fetch(`/api/tags/${tagId}`, { method: 'DELETE' });
    const data = await res.json();
    if (data.success) await loadTagsList();
}

// ==================== 核心极速取件（支持双协议并行 + 关键词/发件人过滤 + 验证码高亮） ====================

function getFetchOptions() {
    const keyword = (document.getElementById('fetchKeywordInput')?.value || '').trim();
    const sender = (document.getElementById('fetchSenderInput')?.value || '').trim();
    const top = parseInt(document.getElementById('fetchLimitSelect')?.value, 10) || 10;
    const folderVal = document.getElementById('fetchFolderSelect')?.value || 'both';
    const folders = folderVal === 'both' ? ['inbox', 'junkemail'] : [folderVal];

    const protocols = [];
    if (workbenchMode !== 'imap') {
        if (document.getElementById('protoGraphToggle')?.checked) protocols.push('graph');
        if (document.getElementById('protoImapToggle')?.checked) protocols.push('imap');
    }
    return {
        keyword,
        sender,
        top,
        folders,
        protocols: protocols.length ? protocols : ['graph', 'imap'],
        parallel: protocols.length > 1
    };
}

function quickExtractCodeFromText(text) {
    if (!text) return '';
    const str = String(text);
    const labeled = str.match(/(?:验证码|校验码|动态码|code|otp|pin|passcode)[^0-9A-Za-z]{0,12}([0-9]{4,8}|[A-Z0-9]{6,8})\b/i);
    if (labeled && labeled[1]) return labeled[1];
    const standalone = str.match(/\b(\d{6})\b/);
    return standalone ? standalone[1] : '';
}

async function fetchMailboxesByAccounts(targetAccounts) {
    if (!targetAccounts.length) {
        showToast('请先在左侧选择或勾选要取件的邮箱', 'warning');
        return;
    }
    const opts = getFetchOptions();
    const btnSel = document.getElementById('btnFetchSelected');
    const btnAll = document.getElementById('btnFetchAll');
    btnSel.disabled = true;
    btnAll.disabled = true;

    const listPane = document.getElementById('emailListPane');
    listPane.innerHTML = `<div class="empty-state">
        <div class="spinner" style="width:26px;height:26px;border-width:3px;"></div>
        <div class="empty-state-title">正在取件（共 ${targetAccounts.length} 个邮箱）…</div>
        <div class="empty-state-sub">${opts.parallel && workbenchMode !== 'imap' ? 'Graph + IMAP 双协议并行竞速中' : '正在连接邮件服务器'}</div>
    </div>`;
    closeEmailDetail();

    try {
        const aggregated = [];
        let okCount = 0;
        let failCount = 0;
        let firstErrorDetails = null;

        if (targetAccounts.length === 1 && opts.folders.length === 1) {
            const acc = targetAccounts[0];
            const qs = new URLSearchParams({
                folder: opts.folders[0],
                top: String(opts.top),
                protocols: opts.protocols.join(','),
                parallel: opts.parallel ? 'true' : 'false'
            });
            if (opts.keyword) qs.set('keyword', opts.keyword);
            if (opts.sender) qs.set('sender', opts.sender);
            const res = await fetch(`/api/emails/${encodeURIComponent(acc.email)}?${qs.toString()}`);
            const data = await res.json();
            if (data.success) {
                okCount = 1;
                (data.emails || []).forEach(em => {
                    aggregated.push({ ...em, _ownerEmail: acc.email, _folder: opts.folders[0], _method: data.method || '' });
                });
            } else {
                failCount = 1;
                firstErrorDetails = (data.error && data.error.details) || data.details || data.error;
            }
        } else {
            const res = await fetch('/api/emails/batch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    account_ids: targetAccounts.map(a => a.id),
                    folders: opts.folders,
                    top: opts.top,
                    protocols: opts.protocols,
                    parallel: opts.parallel,
                    keyword: opts.keyword,
                    sender: opts.sender
                })
            });
            const data = await res.json();
            if (!data.success) {
                handleApiError(data, '取件失败');
                renderFetchedEmails([]);
                return;
            }
            (data.results || []).forEach(item => {
                if (item.success) okCount += 1;
                else failCount += 1;
                const folderMap = item.folders || {};
                Object.entries(folderMap).forEach(([folderName, fRes]) => {
                    if (fRes && fRes.success && Array.isArray(fRes.emails)) {
                        fRes.emails.forEach(em => {
                            aggregated.push({
                                ...em,
                                _ownerEmail: item.email || '',
                                _folder: folderName,
                                _method: fRes.method || ''
                            });
                        });
                    } else if (fRes && fRes.error && !firstErrorDetails) {
                        firstErrorDetails = fRes.error;
                    }
                });
            });
        }

        // 按时间倒序合并展示
        aggregated.sort((a, b) => {
            const ta = Date.parse(a.date || '') || 0;
            const tb = Date.parse(b.date || '') || 0;
            return tb - ta;
        });

        fetchedEmails = aggregated;
        renderFetchedEmails(aggregated, { okCount, failCount, totalAccounts: targetAccounts.length });

        if (failCount > 0 && okCount === 0 && firstErrorDetails) {
            if (firstErrorDetails.graph || firstErrorDetails.imap_new || firstErrorDetails.imap_old) {
                showEmailFetchErrorModal(firstErrorDetails);
            } else {
                showToast(firstErrorDetails.message || '取件失败，请检查账号或代理配置', 'error', firstErrorDetails);
            }
        } else if (failCount > 0) {
            showToast(`取件完成：${okCount} 个邮箱成功，${failCount} 个失败`, 'warning');
        } else {
            showToast(`取件完成：共获取 ${aggregated.length} 封邮件`, 'success');
        }
    } catch (e) {
        showToast(`取件请求异常: ${e.message}`, 'error');
        renderFetchedEmails([]);
    } finally {
        btnSel.disabled = false;
        btnAll.disabled = false;
    }
}

function fetchSelectedMailboxes() {
    let targets = filteredAccounts.filter(a => selectedAccountIds.has(a.id));
    if (!targets.length && activeAccountEmail) {
        targets = filteredAccounts.filter(a => a.email === activeAccountEmail);
    }
    fetchMailboxesByAccounts(targets);
}

function fetchAllVisibleMailboxes() {
    fetchMailboxesByAccounts(filteredAccounts.slice(0, 50));
}

function clearFetchedResults() {
    fetchedEmails = [];
    closeEmailDetail();
    document.getElementById('resultsCanvasHeader').style.display = 'none';
    document.getElementById('emailListPane').innerHTML = `<div class="empty-state">
        <div class="empty-state-icon">📩</div>
        <div class="empty-state-title">在左侧选择或勾选邮箱，然后点击「选中取件」或「全部取件」</div>
        <div class="empty-state-sub">${workbenchMode === 'imap' ? '支持通用 IMAP 账号直连取件' : '支持 IMAP OAuth2 + Graph API 双协议并行取件，自动识别验证码一键复制'}</div>
    </div>`;
}

function renderFetchedEmails(items, stats = null) {
    const header = document.getElementById('resultsCanvasHeader');
    const summary = document.getElementById('resultsSummaryText');
    const pane = document.getElementById('emailListPane');

    header.style.display = 'flex';
    const statSuffix = stats ? `（成功 ${stats.okCount}/${stats.totalAccounts} 个邮箱）` : '';
    summary.textContent = `共获取 ${items.length} 封邮件${statSuffix}`;

    if (!items.length) {
        pane.innerHTML = `<div class="empty-state">
            <div class="empty-state-icon">📭</div>
            <div class="empty-state-title">未匹配到符合条件的邮件</div>
            <div class="empty-state-sub">可尝试清空关键词/发件人过滤，或切换文件夹后重试</div>
        </div>`;
        return;
    }

    pane.innerHTML = items.map((em, idx) => {
        const code = quickExtractCodeFromText(`${em.subject || ''} ${em.body_preview || ''}`);
        const folderTag = em._folder === 'junkemail' ? '<span class="badge badge-red">垃圾箱</span>' : '';
        const methodTag = em._method ? `<span class="badge badge-blue">${escapeHtml(em._method)}</span>` : '';
        const codeHtml = code
            ? `<div class="email-code-bar">
                <button type="button" class="code-chip" onclick="event.stopPropagation(); copyToClipboard('${escapeHtml(code)}', '验证码')"
                    data-tip="点击一键复制识别到的验证码">🔑 ${escapeHtml(code)} · 复制</button>
              </div>`
            : '';

        return `<div class="email-card" data-idx="${idx}" onclick="openEmailDetail(${idx})">
            <div class="email-card-head">
                <div class="email-card-subject">${escapeHtml(em.subject || '(无主题)')}</div>
                <span class="email-card-date">${escapeHtml(formatDateTime(em.date))}</span>
            </div>
            <div class="email-card-meta">
                <span>发件人: ${escapeHtml(em.from || '未知')}</span>
                ${em._ownerEmail ? `<span class="email-owner-tag">${escapeHtml(em._ownerEmail)}</span>` : ''}
                ${folderTag}${methodTag}
            </div>
            ${em.body_preview ? `<div class="email-card-preview">${escapeHtml(em.body_preview)}</div>` : ''}
            ${codeHtml}
        </div>`;
    }).join('');
}

async function openEmailDetail(idx) {
    const item = fetchedEmails[idx];
    if (!item) return;

    document.querySelectorAll('#emailListPane .email-card').forEach(c => {
        c.classList.toggle('active', Number(c.dataset.idx) === idx);
    });

    const split = document.getElementById('resultsSplit');
    const detailPane = document.getElementById('emailDetailPane');
    split.classList.remove('no-detail');
    detailPane.style.display = 'flex';
    document.getElementById('emailDetailMeta').innerHTML = `<div style="font-weight:700;font-size:15px;">${escapeHtml(item.subject || '(无主题)')}</div>
        <div style="font-size:12.5px;color:var(--text-secondary);margin-top:4px;">发件人：${escapeHtml(item.from || '未知')} · 所属邮箱：${escapeHtml(item._ownerEmail || '')}</div>`;
    document.getElementById('emailDetailBody').innerHTML = '<div class="empty-state"><span class="spinner"></span><span>加载正文中…</span></div>';

    try {
        const qs = new URLSearchParams({ folder: item._folder || 'inbox' });
        const res = await fetch(`/api/email/${encodeURIComponent(item._ownerEmail)}/${encodeURIComponent(item.id)}?${qs.toString()}`);
        const data = await res.json();
        if (!data.success || !data.email) {
            document.getElementById('emailDetailBody').innerHTML = `<div class="error-message-box">${escapeHtml((data.error && data.error.message) || '加载邮件正文失败')}</div>`;
            return;
        }
        openedEmailContext = {
            emailAddr: item._ownerEmail,
            messageId: item.id,
            folder: item._folder || 'inbox',
            email: data.email
        };
        renderOpenedEmailBody();
    } catch (_) {
        document.getElementById('emailDetailBody').innerHTML = '<div class="error-message-box">网络异常，无法加载正文</div>';
    }
}

function renderOpenedEmailBody() {
    if (!openedEmailContext || !openedEmailContext.email) return;
    const em = openedEmailContext.email;
    const bodyEl = document.getElementById('emailDetailBody');
    const htmlContent = em.body_html || (em.body_type === 'html' ? em.body : '') || '';
    const textContent = em.body_text || em.body || em.body_preview || '';

    if (isDetailTrusted && htmlContent) {
        const iframe = document.createElement('iframe');
        iframe.setAttribute('sandbox', 'allow-same-origin');
        iframe.srcdoc = htmlContent;
        bodyEl.innerHTML = '';
        bodyEl.appendChild(iframe);
        return;
    }
    if (htmlContent && window.DOMPurify) {
        bodyEl.innerHTML = window.DOMPurify.sanitize(htmlContent, { FORBID_TAGS: ['script', 'style', 'iframe', 'object', 'embed'] });
        return;
    }
    bodyEl.innerHTML = `<pre style="white-space:pre-wrap;font-family:inherit;margin:0;">${escapeHtml(textContent)}</pre>`;
}

function toggleDetailTrustMode(checked) {
    isDetailTrusted = Boolean(checked);
    renderOpenedEmailBody();
}

function closeEmailDetail() {
    openedEmailContext = null;
    document.getElementById('resultsSplit').classList.add('no-detail');
    document.getElementById('emailDetailPane').style.display = 'none';
}

async function extractVerificationFromCurrentDetail() {
    if (!openedEmailContext) return;
    const btn = document.getElementById('btnExtractDetailCode');
    btn.disabled = true;
    try {
        const res = await fetch(`/api/emails/${encodeURIComponent(openedEmailContext.emailAddr)}/extract-verification?folder=${encodeURIComponent(openedEmailContext.folder || 'inbox')}`);
        const data = await res.json();
        const info = data.data || data;
        const code = info.verification_code || info.code || '';
        const link = info.verification_link || info.link || '';
        if (code) {
            await copyToClipboard(code, `验证码 ${code}`);
        } else if (link) {
            await copyToClipboard(link, '验证链接');
        } else {
            showToast('未在当前邮箱最近邮件中识别到验证码或验证链接', 'info');
        }
    } catch (_) {
        showToast('提取验证码失败', 'error');
    } finally {
        btn.disabled = false;
    }
}

async function deleteCurrentOpenedEmail() {
    if (!openedEmailContext) return;
    if (!confirm('确认从服务器永久删除这封邮件？')) return;
    try {
        const res = await fetch('/api/emails/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                email: openedEmailContext.emailAddr,
                ids: [openedEmailContext.messageId],
                folder: openedEmailContext.folder || 'inbox'
            })
        });
        const data = await res.json();
        if (data.success) {
            fetchedEmails = fetchedEmails.filter(e => !(e._ownerEmail === openedEmailContext.emailAddr && e.id === openedEmailContext.messageId));
            closeEmailDetail();
            renderFetchedEmails(fetchedEmails);
            showToast('邮件已删除', 'success');
        } else {
            handleApiError(data, '删除邮件失败');
        }
    } catch (_) {
        showToast('删除邮件失败', 'error');
    }
}

// ==================== 令牌刷新（10 分钟冷却防重复） ====================

async function consumeRefreshSseResponse(res) {
    const bar = document.getElementById('refreshInlineProgress');
    const textEl = document.getElementById('refreshProgressText');
    const fillEl = document.getElementById('refreshProgressFill');
    const countEl = document.getElementById('refreshProgressCount');
    bar.style.display = 'flex';
    fillEl.style.width = '0%';

    const reader = res.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    try {
        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const parts = buffer.split('\n\n');
            buffer = parts.pop() || '';
            for (const part of parts) {
                const line = part.trim();
                if (!line.startsWith('data:')) continue;
                const payload = JSON.parse(line.slice(5).trim());
                if (payload.type === 'start') {
                    const skipNote = payload.skipped_recent_count ? `（已自动跳过 ${payload.skipped_recent_count} 个 10 分钟内刷新过的账号）` : '';
                    textEl.textContent = `开始刷新令牌${skipNote}`;
                    countEl.textContent = `0 / ${payload.total || 0}`;
                } else if (payload.type === 'progress') {
                    const pct = payload.total ? Math.round((payload.current / payload.total) * 100) : 100;
                    fillEl.style.width = `${pct}%`;
                    countEl.textContent = `${payload.current} / ${payload.total}`;
                    textEl.textContent = `正在刷新 ${payload.email || ''}…`;
                } else if (payload.type === 'complete') {
                    fillEl.style.width = '100%';
                    const skipped = payload.skipped_recent_count || 0;
                    const msg = `令牌刷新完成：成功 ${payload.success_count || 0}，失败 ${payload.failed_count || 0}${skipped ? `，冷却跳过 ${skipped}` : ''}`;
                    showToast(msg, payload.failed_count ? 'warning' : 'success');
                } else if (payload.type === 'error') {
                    showToast((payload.error && payload.error.message) || '刷新任务出错', 'warning', payload.error);
                }
            }
        }
    } finally {
        setTimeout(() => { bar.style.display = 'none'; }, 1200);
        await loadAllAccounts();
    }
}

async function refreshSelectedTokensWithCooldown() {
    const ids = filteredAccounts.filter(a => selectedAccountIds.has(a.id)).map(a => a.id);
    if (!ids.length) {
        showToast('请先在左侧勾选要刷新令牌的 Outlook 账号', 'warning');
        return;
    }
    const btn = document.getElementById('btnRefreshSelected');
    btn.disabled = true;
    try {
        const res = await fetch('/api/accounts/refresh/selected', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ account_ids: ids, cooldown_minutes: 10 })
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            handleApiError(err, '刷新失败');
            return;
        }
        await consumeRefreshSseResponse(res);
    } catch (_) {
        showToast('刷新令牌请求失败', 'error');
    } finally {
        btn.disabled = false;
    }
}

async function refreshAllTokensWithCooldown() {
    const btn = document.getElementById('btnRefreshAll');
    btn.disabled = true;
    try {
        const res = await fetch('/api/accounts/refresh-all?cooldown_minutes=10', { method: 'GET' });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            handleApiError(err, '全量刷新失败');
            return;
        }
        await consumeRefreshSseResponse(res);
    } catch (_) {
        showToast('全量刷新请求失败', 'error');
    } finally {
        btn.disabled = false;
    }
}

// ==================== 轻量版本检查与登录退出 ====================

async function checkVersionUpdate() {
    try {
        const res = await fetch('/api/system/version-check');
        if (!res.ok) return;
        const data = await res.json();
        if (!data || !data.has_update || !data.latest_version) return;
        if (localStorage.getItem('dismissed_version') === data.latest_version) return;
        document.getElementById('versionUpdateText').textContent =
            `发现新版本 v${data.latest_version}（当前 v${data.current_version}），可执行 docker compose pull && docker compose up -d 更新`;
        const link = document.getElementById('versionReleaseLink');
        if (link && data.release_url) link.href = data.release_url;
        const banner = document.getElementById('versionUpdateBanner');
        banner.dataset.version = data.latest_version;
        banner.style.display = 'flex';
    } catch (_) {}
}

function dismissVersionBanner() {
    const banner = document.getElementById('versionUpdateBanner');
    if (banner && banner.dataset.version) {
        localStorage.setItem('dismissed_version', banner.dataset.version);
    }
    if (banner) banner.style.display = 'none';
}

function logout() {
    if (!confirm('确认退出登录？')) return;
    fetch('/logout', { method: 'POST' })
        .catch(() => {})
        .finally(() => { window.location.href = '/login'; });
}

function closeAllModals() {
    ['settingsModal', 'addGroupModal', 'addAccountModal', 'editAccountModal', 'exportModal', 'tagManagementModal', 'batchMoveGroupModal', 'errorDetailModal']
        .forEach(id => {
            const el = document.getElementById(id);
            if (el) el.classList.remove('show');
        });
}

// ==================== 启动初始化 ====================

document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeAllModals();
});

document.addEventListener('DOMContentLoaded', async () => {
    document.querySelectorAll('#colorPicker .color-option').forEach(el => {
        el.addEventListener('click', () => {
            selectedColor = el.dataset.color || '#2563eb';
            document.querySelectorAll('#colorPicker .color-option').forEach(o => o.classList.toggle('selected', o === el));
        });
    });

    await loadGroups();
    await loadAllAccounts();
    syncProtocolPillStyles();
    checkVersionUpdate();
});

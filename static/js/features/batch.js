// ==================== 标签管理与账号批量操作 ====================

// ==================== 标签管理 ====================

let allTags = [];

// 显示标签管理模态框
async function showTagManagementModal() {
    document.getElementById('tagManagementModal').classList.add('show');
    await loadTags();
}

// 隐藏标签管理模态框
function hideTagManagementModal() {
    document.getElementById('tagManagementModal').classList.remove('show');
}

// 加载标签列表
async function loadTags() {
    try {
        const response = await fetch('/api/tags');
        const data = await response.json();
        if (data.success) {
            allTags = data.tags;
            renderTagList();
            updateTagFilter();  // Update Filter Dropdown
        }
    } catch (error) {
        showToast(translateAppTextLocal('加载标签失败'), 'error');
    }
}

// 更新标签筛选下拉框
function updateTagFilter() {
    const container = document.getElementById('tagFilterContainer');
    if (!container) return;

    if (allTags.length === 0) {
        container.style.display = 'none';
        return;
    }

    container.style.display = 'flex';

    let html = '';
    allTags.forEach(tag => {
        html += `
            <label style="display: inline-flex; align-items: center; gap: 4px; font-size: 11px; cursor: pointer; padding: 2px 6px; border: 1px solid #e5e5e5; border-radius: 12px; background: white; user-select: none;">
                <input type="checkbox" class="tag-filter-checkbox" value="${tag.id}" onchange="handleTagFilterChange()" style="margin: 0;">
                <span style="width: 8px; height: 8px; border-radius: 50%; background-color: ${tag.color}; display: inline-block;"></span>
                ${escapeHtml(tag.name)}
            </label>
        `;
    });
    container.innerHTML = html;
    /* Old dropdown code removed */


}

// 渲染标签列表
function renderTagList() {
    const listEl = document.getElementById('tagList');
    if (!allTags.length) {
        listEl.innerHTML = `<div style="text-align: center; color: #999; padding: 20px;">${translateAppTextLocal('暂无标签')}</div>`;
        return;
    }

    let html = '';
    allTags.forEach(tag => {
        html += `
            <div style="display: flex; align-items: center; justify-content: space-between; padding: 8px; border-bottom: 1px solid #f0f0f0;">
                <div style="display: flex; align-items: center; gap: 8px;">
                    <span class="tag-badge" style="background-color: ${tag.color};">${escapeHtml(tag.name)}</span>
                </div>
                <button class="btn btn-sm btn-danger" onclick="deleteTag(${tag.id})">${translateAppTextLocal('删除')}</button>
            </div>
        `;
    });
    listEl.innerHTML = html;
}

// 创建标签
async function createTag() {
    const nameInput = document.getElementById('newTagName');
    const colorInput = document.getElementById('newTagColor');
    const name = nameInput.value.trim();
    const color = colorInput.value;

    if (!name) {
        showToast(translateAppTextLocal('请输入标签名称'), 'error');
        return;
    }

    try {
        const response = await fetch('/api/tags', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, color })
        });
        const data = await response.json();

        if (data.success) {
            nameInput.value = '';
            showToast(translateAppTextLocal('标签创建成功'), 'success');
            await loadTags();
            // 刷新账号列表以重新加载标签（如果是在查看列表时添加标签，可能不需要立即刷新列表，但为了保持一致性可以刷新）
            // 但通常添加标签不影响当前列表显示，除非是给账号打标
        } else {
            handleApiError(data, '创建失败');
        }
    } catch (error) {
        showToast(translateAppTextLocal('创建标签失败'), 'error');
    }
}

// 删除标签
async function deleteTag(id) {
    if (!confirm('确定要删除这个标签吗？')) return;

    try {
        const response = await fetch(`/api/tags/${id}`, { method: 'DELETE' });
        const data = await response.json();

        if (data.success) {
            showToast(translateAppTextLocal('标签已删除'), 'success');
            await loadTags();
            // 刷新账号列表以更新标签显示
            if (currentGroupId) {
                loadAccountsByGroup(currentGroupId, true);
            }
        } else {
            handleApiError(data, '删除失败');
        }
    } catch (error) {
        showToast(translateAppTextLocal('删除标签失败'), 'error');
    }
}

// ==================== 批量操作 ====================

// 全局选中的账号 ID 集合（跨分组保持）
let selectedAccountIds = new Set();
let batchMoveGroupContext = { scopedAccountIds: null };

function getActiveAccountCheckboxes() {
    const selector = mailboxViewMode === 'compact'
        ? '#compactAccountList .account-select-checkbox'
        : '#accountList .account-select-checkbox';
    return Array.from(document.querySelectorAll(selector));
}

function handleAccountSelectionChange(accountId, checked) {
    if (checked) {
        selectedAccountIds.add(accountId);
    } else {
        selectedAccountIds.delete(accountId);
    }
    updateBatchActionBar();
    updateSelectAllCheckbox();
}

// 更新批量操作栏状态
function updateBatchActionBar() {
    const barConfigs = [
        { barId: 'batchActionBar', countId: 'selectedCount', active: mailboxViewMode === 'standard' },
        { barId: 'compactBatchActionBar', countId: 'compactSelectedCount', active: mailboxViewMode === 'compact' }
    ];

    barConfigs.forEach(config => {
        const bar = document.getElementById(config.barId);
        const countSpan = document.getElementById(config.countId);
        if (!bar || !countSpan) return;

        if (selectedAccountIds.size > 0 && config.active) {
            bar.style.display = 'flex';
            countSpan.textContent = formatSelectedItemsLabel(selectedAccountIds.size);
        } else {
            bar.style.display = 'none';
        }
    });
}

window.addEventListener('ui-language-changed', () => {
    updateTopbar(currentPage);
    updateBatchActionBar();

    // 语言切换后，重渲染部署警告文案（后端同时返回中英文）
    if (lastDeploymentInfo) {
        try {
            renderDeploymentWarnings(lastDeploymentInfo);
        } catch (e) {}
    }
});

// 显示批量刷新 Token 确认框
async function showBatchRefreshConfirm() {
    if (selectedAccountIds.size === 0) {
        showToast('请选择要刷新 Token 的账号', 'error');
        return;
    }

    const accountIds = Array.from(selectedAccountIds);

    // 检查是否有 IMAP 账号（通过 data-account-type 属性判断）
    let imapCount = 0;
    const allCheckboxes = document.querySelectorAll('.account-select-checkbox');
    allCheckboxes.forEach(cb => {
        const id = parseInt(cb.dataset.accountId || cb.value);
        if (accountIds.includes(id)) {
            const card = cb.closest('[data-account-type]');
            if (card && card.dataset.accountType === 'imap') {
                imapCount++;
            }
        }
    });

    const outlookCount = accountIds.length - imapCount;

    if (outlookCount === 0) {
        showToast('所选账号均为 IMAP 账号，不支持 Token 刷新', 'warning');
        return;
    }

    let confirmMsg;
    if (imapCount > 0) {
        confirmMsg = `已选 ${accountIds.length} 个账号，其中 ${imapCount} 个 IMAP 账号不支持 Token 刷新将被跳过，确认刷新 ${outlookCount} 个 Outlook 账号？`;
    } else {
        confirmMsg = `确认刷新选中的 ${accountIds.length} 个账号的 Token？`;
    }

    if (!confirm(confirmMsg)) {
        return;
    }

    await batchRefreshSelected(accountIds);
}

// 执行指定账号批量刷新 Token（SSE 流式）
async function batchRefreshSelected(accountIds) {
    await initCSRFToken();

    // 显示常驻进度 Toast
    const toastId = 'batch-refresh-toast-' + Date.now();
    showPersistentToast(toastId, `🔄 正在刷新 Token... 0 / ${accountIds.length}`);

    const controller = new AbortController();
    const OVERALL_TIMEOUT_MS = 120000; // 2 分钟整体超时
    const HEARTBEAT_TIMEOUT_MS = 30000; // 30 秒心跳超时
    let overallTimeoutId = null;
    let heartbeatTimeoutId = null;
    let isAborted = false;

    function clearTimers() {
        if (overallTimeoutId) clearTimeout(overallTimeoutId);
        if (heartbeatTimeoutId) clearTimeout(heartbeatTimeoutId);
    }

    function startHeartbeatTimer() {
        if (heartbeatTimeoutId) clearTimeout(heartbeatTimeoutId);
        heartbeatTimeoutId = setTimeout(() => {
            if (!isAborted) {
                isAborted = true;
                controller.abort();
            }
        }, HEARTBEAT_TIMEOUT_MS);
    }

    overallTimeoutId = setTimeout(() => {
        if (!isAborted) {
            isAborted = true;
            controller.abort();
        }
    }, OVERALL_TIMEOUT_MS);

    try {
        const response = await fetch('/api/accounts/refresh/selected', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ account_ids: accountIds }),
            signal: controller.signal
        });

        if (!response.ok || !response.body) {
            clearTimers();
            dismissPersistentToast(toastId);
            showToast('刷新请求失败，请稍后重试', 'error');
            return;
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let totalCount = accountIds.length;
        let streamDone = false;

        startHeartbeatTimer();

        while (!streamDone) {
            const { done, value } = await reader.read();
            if (done) {
                streamDone = true;
                break;
            }

            startHeartbeatTimer();

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop(); // 保留未完整的行

            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                let data;
                try {
                    data = JSON.parse(line.slice(6));
                } catch (e) {
                    continue;
                }

                handleBatchRefreshSSEEvent(data, toastId, totalCount);

                if (data.type === 'start') {
                    totalCount = data.total;
                }
                if (data.type === 'complete' || data.type === 'error') {
                    streamDone = true;
                    break;
                }
            }
        }

        clearTimers();
    } catch (error) {
        clearTimers();
        dismissPersistentToast(toastId);
        if (error.name === 'AbortError') {
            if (isAborted) {
                showToast('刷新请求超时，请检查网络或代理配置后重试', 'warning');
            } else {
                showToast('刷新请求已取消', 'info');
            }
        } else {
            showToast('刷新执行出现错误，请稍后重试', 'error');
        }
        console.error('batchRefreshSelected error:', error);
    }
}

function buildSelectedRefreshActionGuide(errorPayload) {
    const lang = getUiLanguage();
    const code = String(errorPayload && errorPayload.code || '').trim();
    const traceId = String(errorPayload && errorPayload.trace_id || '').trim();
    const details = errorPayload && errorPayload.details;
    const detailText = typeof details === 'string'
        ? details
        : (details ? JSON.stringify(details) : '');

    if (code === 'REFRESH_CONFLICT') {
        if (lang === 'en') {
            return [
                'Another refresh task is running. Wait for it to finish before retrying.',
                'Go to refresh logs and verify the current task has completed.',
                traceId ? `If it keeps happening, share Trace ID: ${traceId}` : 'If it keeps happening, capture and share the Trace ID.',
            ];
        }
        return [
            '当前已有刷新任务在执行，请等待其完成后再重试。',
            '先到刷新历史确认当前任务已结束。',
            traceId ? `若持续出现，请反馈 Trace ID：${traceId}` : '若持续出现，请记录并反馈 Trace ID。',
        ];
    }

    if (code === 'REFRESH_SELECTED_STREAM_FAILED') {
        if (lang === 'en') {
            return [
                'Recheck selected accounts (status, account type, and authorization fields).',
                'Verify network/proxy connectivity and retry selected refresh.',
                traceId ? `If retry fails, share Trace ID: ${traceId}` : 'If retry fails, capture and share the Trace ID.',
            ];
        }
        return [
            '请先检查所选账号状态、账号类型与授权字段是否完整。',
            '请检查网络/代理连通性后重新执行“Selected 刷新”。',
            traceId ? `若重试仍失败，请反馈 Trace ID：${traceId}` : '若重试仍失败，请记录并反馈 Trace ID。',
        ];
    }

    if (/token|refresh|aadsts|invalid_grant|proxy|timeout|network/i.test(detailText)) {
        if (lang === 'en') {
            return [
                'Re-authorize or refresh credentials for the affected account(s).',
                'Check network/proxy settings and retry once.',
                traceId ? `Still failing? Share Trace ID: ${traceId}` : 'Still failing? Capture and share the Trace ID.',
            ];
        }
        return [
            '请重新授权或更新异常账号的凭据。',
            '请检查网络/代理配置后重试一次。',
            traceId ? `仍失败请反馈 Trace ID：${traceId}` : '仍失败请记录并反馈 Trace ID。',
        ];
    }

    return lang === 'en'
        ? [
            'Retry the selected refresh once after reloading the page.',
            'If the same error repeats, open error details and keep the Trace ID.',
            traceId ? `Current Trace ID: ${traceId}` : 'Keep the Trace ID from error details for backend troubleshooting.',
        ]
        : [
            '请刷新页面后重试一次“Selected 刷新”。',
            '若同样错误再次出现，请打开详情并保留 Trace ID。',
            traceId ? `当前 Trace ID：${traceId}` : '请保留错误详情中的 Trace ID 供后端排查。',
        ];
}

function buildSelectedRefreshErrorSummary(errorPayload) {
    const code = String(errorPayload && errorPayload.code || '').trim();
    const rawMessage = window.resolveApiErrorMessage
        ? window.resolveApiErrorMessage(errorPayload, '刷新执行失败', 'Refresh failed')
        : ((errorPayload && (errorPayload.message || errorPayload.message_en)) || '刷新执行失败');
    const guide = buildSelectedRefreshActionGuide(errorPayload);
    const guideText = guide.map((item, idx) => `${idx + 1}. ${item}`).join('\n');
    const codeLine = code ? `\n[Code] ${code}` : '';
    return `${rawMessage}${codeLine}\n\n建议处理：\n${guideText}`;
}

// 处理批量刷新 SSE 事件
function handleBatchRefreshSSEEvent(data, toastId, totalCount) {
    if (data.type === 'start') {
        const total = data.total;
        updatePersistentToast(toastId, `🔄 正在刷新 Token... 0 / ${total}`);

    } else if (data.type === 'progress') {
        if (data.result === 'processing') {
            // 刚开始处理该账号
            updatePersistentToast(toastId, `🔄 正在刷新 Token... ${data.current - 1} / ${data.total}`);
        } else {
            // 该账号刷新完成（success 或 failed）
            updatePersistentToast(toastId, `🔄 正在刷新 Token... ${data.current} / ${data.total}`);
            // 更新对应账号卡片状态
            if (data.account_id) {
                updateAccountCardRefreshStatus(data.account_id, data.result, data.last_refresh_at, data.error_message);
            }
        }

    } else if (data.type === 'complete') {
        const { total, success_count, failed_count, failed_list } = data;
        dismissPersistentToast(toastId);

        if (failed_count === 0) {
            showToast(`✅ Token 刷新完成：成功 ${success_count} 个`, 'success');
        } else {
            let detail = null;
            if (failed_list && failed_list.length > 0) {
                detail = '失败账号：\n' + failed_list.map(f => `${f.email}：${f.error || '未知错误'}`).join('\n');
            }
            showToast(`⚠️ Token 刷新完成：成功 ${success_count} 个，失败 ${failed_count} 个`, 'warning', detail, true);
        }

        // 刷新账号列表以同步状态
        if (currentGroupId) {
            loadAccountsByGroup(currentGroupId, true);
        }

    } else if (data.type === 'error') {
        dismissPersistentToast(toastId);
        const errCode = data.error && data.error.code;
        if (errCode === 'REFRESH_CONFLICT') {
            showToast(buildSelectedRefreshErrorSummary(data.error), 'warning', data.error || null, true);
        } else {
            showToast(buildSelectedRefreshErrorSummary(data.error || {}), 'error', data.error || null, true);
        }
    }
}

// 更新账号卡片的刷新状态显示
function updateAccountCardRefreshStatus(accountId, result, lastRefreshAt, errorMessage) {
    // 标准视图：查找 data-account-id 匹配的卡片
    const cards = document.querySelectorAll(`[data-account-id="${accountId}"]`);
    cards.forEach(card => {
        // 更新刷新状态徽章（如果存在）
        const refreshBadge = card.querySelector('.refresh-status-badge, [data-refresh-status]');
        if (refreshBadge) {
            refreshBadge.textContent = result === 'success' ? '✅' : '❌';
            refreshBadge.title = result === 'success' ? '刷新成功' : (errorMessage || '刷新失败');
        }
        // 更新最后刷新时间（如果存在）
        if (lastRefreshAt) {
            const timeEl = card.querySelector('[data-refresh-time], .last-refresh-at');
            if (timeEl) {
                timeEl.textContent = formatUiRelativeTime(lastRefreshAt, '刚刚', 'Just now');
                timeEl.title = lastRefreshAt;
            }
        }
    });
}

// 显示持久 Toast（用于进度展示）
function showPersistentToast(id, message) {
    // 先清除同 id 的旧 toast
    dismissPersistentToast(id);
    showToast(message, 'info', null, true);
    // 给最后一个 toast 打上 id 标记
    const toasts = document.querySelectorAll('.toast');
    if (toasts.length > 0) {
        toasts[toasts.length - 1].dataset.persistentId = id;
    }
}

// 更新持久 Toast 内容
function updatePersistentToast(id, message) {
    const toast = document.querySelector(`.toast[data-persistent-id="${id}"]`);
    if (toast) {
        const msgEl = toast.querySelector('span') || toast;
        msgEl.textContent = message;
    } else {
        // 如果 toast 已被用户关闭，重新显示
        showPersistentToast(id, message);
    }
}

// 关闭持久 Toast
function dismissPersistentToast(id) {
    const toast = document.querySelector(`.toast[data-persistent-id="${id}"]`);
    if (toast) {
        toast.remove();
    }
}

// 显示批量删除确认
function showBatchDeleteConfirm() {
    if (selectedAccountIds.size === 0) {
        showToast(translateAppTextLocal('请选择要删除的账号'), 'error');
        return;
    }

    if (!confirm(`确定要删除选中的 ${selectedAccountIds.size} 个账号吗？此操作不可恢复！`)) {
        return;
    }

    batchDeleteAccounts();
}

// 批量删除账号
async function batchDeleteAccounts() {
    const accountIds = Array.from(selectedAccountIds);

    // 确保使用最新的 CSRF token
    await initCSRFToken();

    try {
        const response = await fetch('/api/accounts/batch-delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ account_ids: accountIds })
        });

        const data = await response.json();
        if (data.success) {
            showToast(pickApiMessage(data, data.message, 'Accounts deleted successfully'), 'success');
            // 清空选中状态
            selectedAccountIds.clear();
            // 刷新分组和邮箱列表
            loadGroups();
            if (currentGroupId) {
                delete accountsCache[currentGroupId];
                loadAccountsByGroup(currentGroupId, true);
            }
            // 更新批量操作栏
            updateBatchActionBar();
        } else {
            handleApiError(data, '删除失败');
        }
    } catch (error) {
        showToast(translateAppTextLocal('删除失败'), 'error');
    }
}

// ── 批量拉取邮件（Issue #55: 标准模式 latest-only）──

function resolveSelectedAccountsForBatchFetch() {
    const result = [];
    const idSet = selectedAccountIds;
    if (!idSet || idSet.size === 0) return result;

    const seen = new Set();
    const groupArrays = Object.values(accountsCache);
    for (const group of groupArrays) {
        if (!Array.isArray(group)) continue;
        for (const acc of group) {
            if (acc && acc.id && idSet.has(acc.id) && !seen.has(acc.id)) {
                seen.add(acc.id);
                result.push({
                    id: acc.id,
                    email: acc.email,
                    account_type: acc.account_type,
                    provider: acc.provider,
                });
            }
        }
    }
    return result;
}

function showBatchFetchConfirm() {
    if (selectedAccountIds.size === 0) {
        showToast(translateAppTextLocal('请选择要批量拉取邮件的账号'), 'error');
        return;
    }

    const accounts = resolveSelectedAccountsForBatchFetch();
    if (accounts.length === 0) {
        showToast(translateAppTextLocal('请选择要批量拉取邮件的账号'), 'error');
        return;
    }

    if (!confirm(`${translateAppTextLocal('批量拉取邮件')}：${translateAppTextLocal('收件箱 + 垃圾箱')} (${accounts.length} ${translateAppTextLocal('个账号')})？`)) {
        return;
    }

    batchFetchSelectedEmails(accounts);
}

async function batchFetchSelectedEmails(accounts) {
    const toastId = 'batch-fetch-toast-' + Date.now();
    showPersistentToast(toastId, `${translateAppTextLocal('正在批量拉取邮件')}...`);

    const ids = accounts.map(a => a.id);

    try {
        const response = await fetch('/api/emails/batch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ account_ids: ids, folders: ['inbox', 'junkemail'], skip: 0, top: 10 })
        });
        const data = await response.json();

        dismissPersistentToast(toastId);

        if (!data.success) {
            handleApiError(data, translateAppTextLocal('批量拉取失败'));
            return;
        }

        // 回写缓存 + 刷新当前邮箱
        let successAccounts = 0;
        const failedAccounts = [];

        for (const result of (data.results || [])) {
            if (result.success) {
                successAccounts++;
                const emailAddr = result.email || '';
                const folders = result.folders || {};
                for (const [folder, folderData] of Object.entries(folders)) {
                    if (folderData && folderData.success) {
                        if (folderData.account_summary && typeof syncAccountSummaryToAccountCache === 'function') {
                            syncAccountSummaryToAccountCache(emailAddr, folderData.account_summary);
                        }
                        cacheBatchFetchedFolder(emailAddr, folder, folderData);
                        refreshCurrentMailboxIfNeeded(emailAddr, folder, folderData);
                    }
                }
            } else {
                failedAccounts.push(result.email || result.account_id);
            }
        }

        const failCount = failedAccounts.length;
        let msg = `${translateAppTextLocal('批量拉取完成')}：${translateAppTextLocal('成功')} ${successAccounts}，${translateAppTextLocal('失败')} ${failCount}`;
        if (failCount > 0) {
            msg += `（${failedAccounts.join(', ')}）`;
        }
        showToast(msg, failCount > 0 ? 'warning' : 'success');
    } catch (error) {
        dismissPersistentToast(toastId);
        showToast(translateAppTextLocal('操作失败'), 'error');
    }
}

async function fetchLatestFoldersForAccount(acc) {
    const folders = ['inbox', 'junkemail'];
    let accountSuccess = false;
    for (const folder of folders) {
        try {
            const url = `/api/emails/${encodeURIComponent(acc.email)}?folder=${folder}&skip=0&top=10`;
            const response = await fetch(url);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            if (data.success) {
                if (data.account_summary && typeof syncAccountSummaryToAccountCache === 'function') {
                    syncAccountSummaryToAccountCache(acc.email, data.account_summary);
                }
                cacheBatchFetchedFolder(acc.email, folder, data);
                refreshCurrentMailboxIfNeeded(acc.email, folder, data);
                accountSuccess = true;
            }
        } catch (_e) {}
    }

    return { success: accountSuccess };
}

function cacheBatchFetchedFolder(email, folder, data) {
    const cacheKey = `${email}_${folder}`;
    emailListCache[cacheKey] = {
        emails: (typeof sortEmailsByNewestFirst === 'function')
            ? sortEmailsByNewestFirst(data.emails || [])
            : (data.emails || []),
        has_more: data.has_more || false,
        skip: 0,
        method: data.method || 'Graph API',
    };
}

function refreshCurrentMailboxIfNeeded(email, folder, data) {
    if (currentAccount !== email || currentFolder !== folder) return;

    const sortedEmails = (typeof sortEmailsByNewestFirst === 'function')
        ? sortEmailsByNewestFirst(data.emails || [])
        : (data.emails || []);

    currentEmails = sortedEmails;
    const emailCountEl = document.getElementById('emailCount');
    if (emailCountEl) emailCountEl.textContent = `(${currentEmails.length})`;
    renderEmailList(currentEmails);
}

let batchActionType = ''; // 'add' or 'remove'
let batchTagContext = { scopedAccountIds: null };

// 显示批量打标模态框
async function showBatchTagModal(type, options = {}) {
    batchActionType = type;
    batchTagContext = {
        scopedAccountIds: Array.isArray(options.scopedAccountIds) && options.scopedAccountIds.length > 0
            ? [...options.scopedAccountIds]
            : null
    };
    document.getElementById('batchTagTitle').textContent = translateAppTextLocal(type === 'add' ? '批量添加标签' : '批量移除标签');
    document.getElementById('batchTagModal').classList.add('show');

    // 加载标签选项
    await loadTagsForSelect();
}

function hideBatchTagModal() {
    document.getElementById('batchTagModal').classList.remove('show');
    batchTagContext = { scopedAccountIds: null };
}

// 加载标签到下拉框
async function loadTagsForSelect() {
    const select = document.getElementById('batchTagSelect');
    select.innerHTML = `<option value="">${translateAppTextLocal('加载中...')}</option>`;

    try {
        const response = await fetch('/api/tags');
        const data = await response.json();
        if (data.success) {
            let html = `<option value="">${translateAppTextLocal('请选择标签...')}</option>`;
            data.tags.forEach(tag => {
                html += `<option value="${tag.id}">${escapeHtml(tag.name)}</option>`;
            });
            select.innerHTML = html;
        }
    } catch (error) {
        select.innerHTML = `<option value="">${translateAppTextLocal('加载失败')}</option>`;
    }
}

// 确认批量打标
async function confirmBatchTag() {
    const tagId = document.getElementById('batchTagSelect').value;
    if (!tagId) {
        showToast(translateAppTextLocal('请选择标签'), 'error');
        return;
    }

    const accountIds = batchTagContext.scopedAccountIds ? [...batchTagContext.scopedAccountIds] : Array.from(selectedAccountIds);

    if (accountIds.length === 0) return;

    try {
        const hasScopedAccountIds = Boolean(batchTagContext.scopedAccountIds);
        const response = await fetch('/api/accounts/tags', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                account_ids: accountIds,
                tag_id: parseInt(tagId),
                action: batchActionType
            })
        });

        const data = await response.json();
        if (data.success) {
            showToast(pickApiMessage(data, data.message, 'Tag update completed'), 'success');
            hideBatchTagModal();
            if (!hasScopedAccountIds) {
                selectedAccountIds.clear();
            }
            // 失效相关缓存并由 loadGroups 统一刷新（避免双发 GET /api/accounts）
            invalidateAccountsCache(currentGroupId);
            await loadGroups();
            updateBatchActionBar();
        } else {
            handleApiError(data, '操作失败');
        }
    } catch (error) {
        showToast(translateAppTextLocal('请求失败'), 'error');
    }
}

// ==================== 批量移动分组 ====================

// 显示批量移动分组模态框
async function showBatchMoveGroupModal(options = {}) {
    batchMoveGroupContext = {
        scopedAccountIds: Array.isArray(options.scopedAccountIds) && options.scopedAccountIds.length > 0
            ? [...options.scopedAccountIds]
            : null
    };
    document.getElementById('batchMoveGroupModal').classList.add('show');
    await loadGroupsForBatchMove();
}

function hideBatchMoveGroupModal() {
    document.getElementById('batchMoveGroupModal').classList.remove('show');
    batchMoveGroupContext = { scopedAccountIds: null };
}

// 加载分组到下拉框
async function loadGroupsForBatchMove() {
    const select = document.getElementById('batchMoveGroupSelect');
    select.innerHTML = `<option value="">${translateAppTextLocal('加载中...')}</option>`;

    try {
        const response = await fetch('/api/groups');
        const data = await response.json();
        if (data.success) {
            let html = `<option value="">${translateAppTextLocal('请选择分组...')}</option>`;
            data.groups.filter(g => !g.is_system).forEach(group => {
                html += `<option value="${group.id}">${escapeHtml(group.name)}</option>`;
            });
            select.innerHTML = html;
        }
    } catch (error) {
        select.innerHTML = `<option value="">${translateAppTextLocal('加载失败')}</option>`;
    }
}

// 确认批量移动分组
async function confirmBatchMoveGroup() {
    const groupId = document.getElementById('batchMoveGroupSelect').value;
    if (!groupId) {
        showToast(translateAppTextLocal('请选择目标分组'), 'error');
        return;
    }

    const accountIds = batchMoveGroupContext.scopedAccountIds
        ? [...batchMoveGroupContext.scopedAccountIds]
        : Array.from(selectedAccountIds);

    if (accountIds.length === 0) return;

    try {
        const hasScopedAccountIds = Boolean(batchMoveGroupContext.scopedAccountIds);
        const response = await fetch('/api/accounts/batch-update-group', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                account_ids: accountIds,
                group_id: parseInt(groupId)
            })
        });

        const data = await response.json();
        if (data.success) {
            showToast(pickApiMessage(data, data.message, 'Accounts moved successfully'), 'success');
            hideBatchMoveGroupModal();
            if (!hasScopedAccountIds) {
                selectedAccountIds.clear();
            }
            // 失效当前分组、目标分组与全局搜索缓存并统一刷新（避免双发 GET /api/accounts）
            invalidateAccountsCache(currentGroupId, parseInt(groupId, 10));
            await loadGroups();
            updateBatchActionBar();
        } else {
            handleApiError(data, '操作失败');
        }
    } catch (error) {
        showToast(translateAppTextLocal('请求失败'), 'error');
    }
}

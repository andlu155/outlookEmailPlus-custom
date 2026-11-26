// ==================== Token 刷新管理、失效治理与刷新日志 ====================

// ==================== Token 刷新管理 ====================

// 显示刷新模态框（并行拉取统计、失败列表与失效 Token 候选）
async function showRefreshModal() {
    document.getElementById('refreshModal').classList.add('show');
    resetInvalidTokenGovernanceState();
    await Promise.all([
        loadRefreshStats(),
        autoLoadFailedListIfNeeded(),
        loadInvalidTokenGovernanceCandidates({
            keepVisibleWhenEmpty: false,
            silentWhenEmpty: true
        })
    ]);
}

// 自动加载失败列表（如果有失败记录）
async function autoLoadFailedListIfNeeded() {
    try {
        const response = await fetch('/api/accounts/refresh-logs/failed');
        const data = await response.json();

        if (data.success && data.logs && data.logs.length > 0) {
            // 有失败记录，自动显示失败列表
            showFailedListFromData(data.logs.map(log => ({
                id: log.account_id,
                email: log.account_email,
                error: log.error_message
            })));
        }
    } catch (error) {
        console.error('自动加载失败列表失败:', error);
    }
}

// 隐藏刷新模态框
function hideRefreshModal() {
    const modal = document.getElementById('refreshModal');
    modal.classList.remove('show');

    // 确保所有内容都被隐藏，防止残留
    const progress = document.getElementById('refreshProgress');
    if (progress) {
        progress.style.display = 'none';
    }
    const failedList = document.getElementById('failedListContainer');
    if (failedList) {
        failedList.style.display = 'none';
    }
    const logsContainer = document.getElementById('refreshLogsContainer');
    if (logsContainer) {
        logsContainer.style.display = 'none';
    }
    resetInvalidTokenGovernanceState();

    // 重置按钮状态
    const refreshAllBtn = document.getElementById('refreshAllBtn');
    if (refreshAllBtn) {
        refreshAllBtn.disabled = false;
        refreshAllBtn.textContent = translateAppTextLocal('🔄 全量刷新');
    }

    const retryFailedBtn = document.getElementById('retryFailedBtn');
    if (retryFailedBtn) {
        retryFailedBtn.disabled = false;
        retryFailedBtn.textContent = translateAppTextLocal('🔁 重试失败');
    }
}

// ==================== 失效 Token 治理面板 ====================

/** 重置治理面板状态（模态框打开/关闭时调用） */
function resetInvalidTokenGovernanceState() {
    latestInvalidTokenDetectedCount = 0;
    invalidTokenGovernanceCandidates = [];
    const container = document.getElementById('invalidTokenGovernanceContainer');
    if (container) container.style.display = 'none';
    const summary = document.getElementById('invalidTokenSummary');
    if (summary) summary.style.display = 'none';
    const listWrap = document.getElementById('invalidTokenCandidateListWrap');
    if (listWrap) listWrap.style.display = 'none';
}

/** 显示检测摘要横幅（刷新完成有 invalid token 时调用） */
function showInvalidTokenDetectionSummary(count, failedList) {
    const summary = document.getElementById('invalidTokenSummary');
    const summaryText = document.getElementById('invalidTokenSummaryText');
    if (!summary || !summaryText) return;

    summaryText.textContent = `检测到 ${count} 个疑似失效 Token 的账号，需要治理处理`;
    summary.style.display = 'block';

    // 同时显示治理面板容器
    const container = document.getElementById('invalidTokenGovernanceContainer');
    if (container) container.style.display = 'block';
}

/** 隐藏治理面板 */
function hideInvalidTokenGovernance() {
    const container = document.getElementById('invalidTokenGovernanceContainer');
    if (container) container.style.display = 'none';
    const summary = document.getElementById('invalidTokenSummary');
    if (summary) summary.style.display = 'none';
    const listWrap = document.getElementById('invalidTokenCandidateListWrap');
    if (listWrap) listWrap.style.display = 'none';
}

/** 从后端加载治理候选列表并渲染 */
async function loadInvalidTokenGovernanceCandidates(options = {}) {
    const { keepVisibleWhenEmpty = false, silentWhenEmpty = false } = options;

    try {
        const response = await fetch('/api/accounts/invalid-token-candidates?limit=200');
        const data = await response.json();

        if (!data.success) {
            if (!silentWhenEmpty) {
                showToast('加载失效 Token 候选失败', 'error');
            }
            return;
        }

        invalidTokenGovernanceCandidates = data.candidates || [];
        const count = invalidTokenGovernanceCandidates.length;

        // 更新数量标签
        const countEl = document.getElementById('invalidTokenCandidateCount');
        if (countEl) {
            countEl.textContent = `${count} 个`;
        }

        if (count === 0) {
            if (!keepVisibleWhenEmpty) {
                hideInvalidTokenGovernance();
            }
            return;
        }

        // 渲染候选列表
        const listEl = document.getElementById('invalidTokenCandidateList');
        const listWrap = document.getElementById('invalidTokenCandidateListWrap');

        if (!listEl || !listWrap) return;

        let html = '';
        invalidTokenGovernanceCandidates.forEach(item => {
            const statusBadge = item.account_status === 'inactive'
                ? '<span style="background-color:#fbbf24;color:#78350f;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;">已停用</span>'
                : '<span style="background-color:#34d399;color:#064e3b;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;">活跃</span>';

            html += `
                <div style="padding:10px 12px;border-bottom:1px solid #e5e5e5;display:flex;justify-content:space-between;align-items:start;gap:10px;">
                    <div style="flex:1;min-width:0;">
                        <div style="font-weight:600;margin-bottom:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="${escapeHtml(item.account_email)}">${escapeHtml(item.account_email)}</div>
                        <div style="font-size:12px;color:#dc3545;margin-bottom:2px;word-break:break-all;">${escapeHtml(item.error_message || '未知错误')}</div>
                        <div style="font-size:11px;color:#999;">原因: ${escapeHtml(item.reason_label || item.reason_code || '-')} ｜ 刷新时间: ${formatDateTime(item.created_at)}</div>
                    </div>
                    <div style="flex-shrink:0;display:flex;align-items:center;gap:4px;">
                        ${statusBadge}
                    </div>
                </div>
            `;
        });

        listEl.innerHTML = html;
        listWrap.style.display = 'block';

        // 确保容器可见
        const container = document.getElementById('invalidTokenGovernanceContainer');
        if (container) container.style.display = 'block';

    } catch (error) {
        console.error('加载失效 Token 候选失败:', error);
        if (!silentWhenEmpty) {
            showToast('加载失效 Token 候选失败', 'error');
        }
    }
}

/** 批量将失效 Token 候选账号置为停用 */
async function batchSetInvalidTokenInactive() {
    if (invalidTokenGovernanceCandidates.length === 0) {
        showToast('没有需要处理的候选账号', 'warning');
        return;
    }

    // 只取状态不是 inactive 的账号
    const targetCandidates = invalidTokenGovernanceCandidates.filter(c => c.account_status !== 'inactive');
    if (targetCandidates.length === 0) {
        showToast('所有候选账号已经是停用状态', 'info');
        return;
    }

    const accountIds = targetCandidates.map(c => c.account_id);
    const confirmed = confirm(`确定要将 ${accountIds.length} 个失效 Token 账号置为停用吗？停用后账号将不再参与刷新和使用。`);
    if (!confirmed) return;

    await initCSRFToken();

    try {
        const response = await fetch('/api/accounts/batch-update-status', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ account_ids: accountIds, status: 'inactive' })
        });

        const data = await response.json();
        if (data.success) {
            showToast(pickApiMessage(data, data.message, '批量停用成功'), 'success');
            // 刷新候选列表与统计
            await loadInvalidTokenGovernanceCandidates({ keepVisibleWhenEmpty: true, silentWhenEmpty: true });
            await loadRefreshStats();
            if (currentGroupId) {
                delete accountsCache[currentGroupId];
                loadAccountsByGroup(currentGroupId, true);
            }
        } else {
            handleApiError(data, '批量停用失败');
        }
    } catch (error) {
        console.error('批量停用失败:', error);
        showToast('批量停用请求失败', 'error');
    }
}

/** 批量删除失效 Token 候选账号（二次确认） */
async function batchDeleteInvalidTokenCandidates() {
    if (invalidTokenGovernanceCandidates.length === 0) {
        showToast('没有需要处理的候选账号', 'warning');
        return;
    }

    const accountIds = invalidTokenGovernanceCandidates.map(c => c.account_id);
    const emailPreview = invalidTokenGovernanceCandidates.slice(0, 3).map(c => c.account_email).join(', ')
        + (accountIds.length > 3 ? ` 等 ${accountIds.length} 个` : '');

    const confirmed = confirm(
        `⚠️ 危险操作：确定要删除 ${accountIds.length} 个失效 Token 账号吗？\n\n涉及账号：${emailPreview}\n\n此操作不可撤销，请确认！`
    );
    if (!confirmed) return;

    // 二次确认
    const doubleConfirmed = confirm('再次确认：删除账号将同时清除所有相关数据，是否继续？');
    if (!doubleConfirmed) return;

    await initCSRFToken();

    try {
        const response = await fetch('/api/accounts/batch-delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ account_ids: accountIds })
        });

        const data = await response.json();
        if (data.success) {
            showToast(pickApiMessage(data, data.message, '批量删除成功'), 'success');
            hideInvalidTokenGovernance();
            await loadRefreshStats();
            if (currentGroupId) {
                delete accountsCache[currentGroupId];
                loadAccountsByGroup(currentGroupId, true);
            }
            loadGroups();
        } else {
            handleApiError(data, '批量删除失败');
        }
    } catch (error) {
        console.error('批量删除失败:', error);
        showToast('批量删除请求失败', 'error');
    }
}

// ==================== 刷新统计与全量刷新 ====================

// 加载刷新统计
async function loadRefreshStats() {
    try {
        const response = await fetch('/api/accounts/refresh-stats');
        const data = await response.json();

        console.log('刷新统计数据:', data);

        if (data.success) {
            const stats = data.stats;

            // 优先使用保存的本地刷新时间
            if (lastRefreshTime && lastRefreshTime instanceof Date) {
                document.getElementById('lastRefreshTime').textContent = formatDateTime(lastRefreshTime.toISOString());
            } else if (stats.last_refresh_time) {
                document.getElementById('lastRefreshTime').textContent = formatDateTime(stats.last_refresh_time);
            } else {
                document.getElementById('lastRefreshTime').textContent = '-';
            }

            document.getElementById('totalRefreshCount').textContent = stats.total;
            document.getElementById('successRefreshCount').textContent = stats.success_count;
            document.getElementById('failedRefreshCount').textContent = stats.failed_count;

            console.log('统计数据已更新到页面');
        }
    } catch (error) {
        console.error('加载刷新统计失败:', error);
    }
}

// 全量刷新所有账号
async function refreshAllAccounts() {
    const btn = document.getElementById('refreshAllBtn');
    const progress = document.getElementById('refreshProgress');
    const progressText = document.getElementById('refreshProgressText');

    if (btn.disabled) return;

    if (!confirm('确定要刷新所有账号的 Token 吗？')) {
        return;
    }

    btn.disabled = true;
    btn.textContent = translateAppTextLocal('刷新中...');
    progress.style.display = 'block';
    progressText.innerHTML = translateAppTextLocal('正在初始化...');

    try {
        const eventSource = new EventSource('/api/accounts/trigger-scheduled-refresh?force=true');
        let totalCount = 0;
        let successCount = 0;
        let failedCount = 0;

        eventSource.onmessage = function (event) {
            try {
                const data = JSON.parse(event.data);

                if (data.type === 'start') {
                    totalCount = data.total;
                    const delayInfo = data.delay_seconds > 0 ? `（间隔 ${data.delay_seconds} 秒）` : '';
                    progressText.innerHTML = `${translateAppTextLocal('总共')} <strong>${totalCount}</strong> ${translateAppTextLocal('个账号')}${delayInfo}，${translateAppTextLocal('准备开始刷新...')}`;
                    // 初始化统计
                    document.getElementById('totalRefreshCount').textContent = totalCount;
                    document.getElementById('successRefreshCount').textContent = '0';
                    document.getElementById('failedRefreshCount').textContent = '0';
                } else if (data.type === 'progress') {
                    successCount = data.success_count;
                    failedCount = data.failed_count;
                    // 实时更新统计
                    document.getElementById('successRefreshCount').textContent = successCount;
                    document.getElementById('failedRefreshCount').textContent = failedCount;
                    progressText.innerHTML = `
                        ${translateAppTextLocal('正在处理')}: <strong>${data.email}</strong><br>
                        ${translateAppTextLocal('进度')}: <strong>${data.current}/${data.total}</strong> |
                        ${translateAppTextLocal('成功')}: <strong style="color: #28a745;">${successCount}</strong> |
                        ${translateAppTextLocal('失败')}: <strong style="color: #dc3545;">${failedCount}</strong>
                    `;
                } else if (data.type === 'delay') {
                    progressText.innerHTML += `<br><span style="color: #999;">${translateAppTextLocal('等待')} ${data.seconds} ${translateAppTextLocal('秒后继续...')}</span>`;
                } else if (data.type === 'complete') {
                    eventSource.close();
                    progress.style.display = 'none';
                    btn.disabled = false;
                    btn.textContent = translateAppTextLocal('🔄 全量刷新');

                    const invalidTokenFailedCount = Number(data.invalid_token_failed_count || 0);
                    latestInvalidTokenDetectedCount = invalidTokenFailedCount;

                    // 直接更新统计数据，使用本地时间
                    const now = new Date();
                    lastRefreshTime = now; // 保存刷新时间
                    document.getElementById('lastRefreshTime').textContent = formatUiRelativeTime(new Date().toISOString(), '刚刚', 'Just now');
                    document.getElementById('totalRefreshCount').textContent = data.total;
                    document.getElementById('successRefreshCount').textContent = data.success_count;
                    document.getElementById('failedRefreshCount').textContent = data.failed_count;

                    showToast(`${
                        getUiLanguage() === 'en'
                            ? `Refresh completed. Success: ${data.success_count}, Failed: ${data.failed_count}`
                            : `刷新完成！成功: ${data.success_count}, 失败: ${data.failed_count}`
                    }`,
                        data.failed_count > 0 ? 'warning' : 'success');

                    if (invalidTokenFailedCount > 0) {
                        showInvalidTokenDetectionSummary(invalidTokenFailedCount, data.invalid_token_failed_list || []);
                        loadInvalidTokenGovernanceCandidates({
                            keepVisibleWhenEmpty: true,
                            silentWhenEmpty: false
                        });
                    }

                    // 如果有失败的，显示失败列表
                    if (data.failed_count > 0) {
                        showFailedListFromData(data.failed_list);
                    }

                    // 刷新账号列表以更新刷新时间
                    if (currentGroupId) {
                        loadAccountsByGroup(currentGroupId, true);
                    }
                } else if (data.type === 'error') {
                    eventSource.close();
                    progress.style.display = 'none';
                    btn.disabled = false;
                    btn.textContent = translateAppTextLocal('🔄 全量刷新');

                    const errCode = data.error && data.error.code;
                    if (errCode === 'NO_MAIL_PERMISSION') {
                        showToast(buildRefreshAllPermissionErrorSummary(data.error || {}), 'error', data.error || null, true);
                    } else {
                        const userMessage = window.resolveApiErrorMessage
                            ? window.resolveApiErrorMessage(data.error || {}, '刷新过程中出现错误', 'Refresh failed during execution')
                            : translateAppTextLocal('刷新过程中出现错误');

                        if (errCode === 'REFRESH_CONFLICT') {
                            showToast(userMessage, 'warning', data.error || null, true);
                        } else {
                            showToast(userMessage, 'error', data.error || null, true);
                        }
                    }
                }
            } catch (e) {
                console.error('解析进度数据失败:', e);
            }
        };

        eventSource.onerror = function (error) {
            console.error('EventSource 错误:', error);
            eventSource.close();
            progress.style.display = 'none';
            btn.disabled = false;
            btn.textContent = translateAppTextLocal('🔄 全量刷新');
            showToast(translateAppTextLocal('刷新过程中出现错误'), 'error');
        };

    } catch (error) {
        progress.style.display = 'none';
        btn.disabled = false;
        btn.textContent = translateAppTextLocal('🔄 全量刷新');
        showToast(translateAppTextLocal('刷新请求失败'), 'error');
    }
}

function buildRefreshAllPermissionErrorSummary(errorPayload) {
    const traceId = String(errorPayload && errorPayload.trace_id || '').trim();
    const lang = getUiLanguage();

    if (lang === 'en') {
        const lines = [
            'This Outlook account is missing mail read permission, so full refresh cannot proceed.',
            '[Code] NO_MAIL_PERMISSION',
            '',
            'Suggested actions:',
            '1. Re-authorize the account and ensure Mail.Read or Mail.ReadWrite scope is granted.',
            '2. Save account settings and retry full refresh.',
            traceId
                ? `3. If it still fails, share Trace ID: ${traceId}`
                : '3. If it still fails, capture and share the Trace ID for backend diagnostics.',
        ];
        return lines.join('\n');
    }

    const lines = [
        '当前账号缺少邮件读取权限，导致全量刷新无法继续。',
        '[Code] NO_MAIL_PERMISSION',
        '',
        '建议处理：',
        '1. 重新授权账号，并确保授予 Mail.Read 或 Mail.ReadWrite 权限。',
        '2. 保存账号设置后再次执行“全量刷新”。',
        traceId
            ? `3. 若仍失败，请反馈 Trace ID：${traceId}`
            : '3. 若仍失败，请记录并反馈 Trace ID 以便后端排查。',
    ];
    return lines.join('\n');
}

// 重试失败的账号
async function retryFailedAccounts() {
    const btn = document.getElementById('retryFailedBtn');
    const progress = document.getElementById('refreshProgress');
    const progressText = document.getElementById('refreshProgressText');

    if (btn.disabled) return;

    btn.disabled = true;
    btn.textContent = translateAppTextLocal('重试中...');
    progress.style.display = 'block';
    progressText.textContent = translateAppTextLocal('正在重试失败的账号...');

    try {
        const response = await fetch('/api/accounts/refresh-failed', {
            method: 'POST'
        });
        const data = await response.json();

        progress.style.display = 'none';
        btn.disabled = false;
        btn.textContent = translateAppTextLocal('🔁 重试失败');

        if (data.success) {
            if (data.total === 0) {
                showToast(translateAppTextLocal('没有需要重试的失败账号'), 'info');
            } else {
                showToast(`${
                    getUiLanguage() === 'en'
                        ? `Retry completed. Success: ${data.success_count}, Failed: ${data.failed_count}`
                        : `重试完成！成功: ${data.success_count}, 失败: ${data.failed_count}`
                }`,
                    data.failed_count > 0 ? 'warning' : 'success');

                // 刷新统计
                loadRefreshStats();

                // 失效 Token 治理
                const retryInvalidTokenCount = Number(data.invalid_token_failed_count || 0);
                latestInvalidTokenDetectedCount = retryInvalidTokenCount;
                if (retryInvalidTokenCount > 0) {
                    showInvalidTokenDetectionSummary(retryInvalidTokenCount, data.invalid_token_failed_list || []);
                    loadInvalidTokenGovernanceCandidates({
                        keepVisibleWhenEmpty: true,
                        silentWhenEmpty: false
                    });
                }

                // 如果还有失败的，显示失败列表
                if (data.failed_count > 0) {
                    showFailedListFromData(data.failed_list);
                } else {
                    hideFailedList();
                }
            }
        } else {
            const errCode = data && data.error && data.error.code;
            if (errCode === 'REFRESH_CONFLICT') {
                const msg = window.resolveApiErrorMessage
                    ? window.resolveApiErrorMessage(data.error, '当前已有刷新任务执行中，请等待当前任务完成后再重试', 'Another refresh task is already running. Wait for it to finish and retry.')
                    : translateAppTextLocal('当前已有刷新任务执行中，请等待当前任务完成后再重试');
                showToast(msg, 'warning', data.error || null, true);
            } else {
                handleApiError(data, '重试失败');
            }
        }
    } catch (error) {
        progress.style.display = 'none';
        btn.disabled = false;
        btn.textContent = translateAppTextLocal('🔁 重试失败');
        showToast(translateAppTextLocal('重试请求失败'), 'error');
    }
}

// 单个账号重试
async function retrySingleAccount(accountId, accountEmail) {
    try {
        const response = await fetch(`/api/accounts/${accountId}/retry-refresh`, {
            method: 'POST'
        });
        const data = await response.json();

        if (data.success) {
            showToast(
                getUiLanguage() === 'en'
                    ? `${accountEmail} refreshed successfully`
                    : `${accountEmail} 刷新成功`,
                'success'
            );
            loadRefreshStats();

            // 刷新失败列表
            loadFailedLogs();
        } else {
            handleApiError(data, `${accountEmail} 刷新失败`);
        }
    } catch (error) {
        handleApiError({
            success: false,
            error: {
                message: '刷新请求失败',
                message_en: 'Refresh request failed',
                details: error.message,
                code: 'NETWORK_ERROR',
                type: 'Frontend'
            }
        });
    }
}

// 显示失败列表（从数据）
function showFailedListFromData(failedList) {
    const container = document.getElementById('failedListContainer');
    const listEl = document.getElementById('failedList');

    // 隐藏其他列表
    hideRefreshLogs();

    if (!failedList || failedList.length === 0) {
        container.style.display = 'none';
        return;
    }

    let html = '';
    failedList.forEach(item => {
        html += `
            <div style="padding: 12px; border-bottom: 1px solid #e5e5e5; display: flex; justify-content: space-between; align-items: start;">
                <div style="flex: 1;">
                    <div style="font-weight: 600; margin-bottom: 4px;">${escapeHtml(item.email)}</div>
                    <div style="font-size: 12px; color: #dc3545;">${escapeHtml(item.error || '未知错误')}</div>
                </div>
                <button class="btn btn-sm btn-primary" onclick="retrySingleAccount(${item.id}, '${escapeHtml(item.email)}')">
                    重试
                </button>
            </div>
        `;
    });

    listEl.innerHTML = html;
    container.style.display = 'block';
}

// 隐藏失败列表
function hideFailedList() {
    document.getElementById('failedListContainer').style.display = 'none';
}

// 加载失败日志
async function loadFailedLogs() {
    const container = document.getElementById('failedListContainer');
    const listEl = document.getElementById('failedList');

    hideRefreshLogs();

    try {
        const response = await fetch('/api/accounts/refresh-logs/failed');
        const data = await response.json();

        if (data.success) {
            if (data.logs.length === 0) {
                listEl.innerHTML = '<div style="padding: 20px; text-align: center; color: #666;">暂无失败状态的邮箱</div>';
            } else {
                let html = '';
                data.logs.forEach(log => {
                    html += `
                        <div style="padding: 12px; border-bottom: 1px solid #e5e5e5; display: flex; justify-content: space-between; align-items: center;">
                            <div style="flex: 1;">
                                <div style="font-weight: 600; margin-bottom: 4px;">${escapeHtml(log.account_email)}</div>
                                <div style="font-size: 12px; color: #dc3545;">${escapeHtml(log.error_message || '未知错误')}</div>
                                <div style="font-size: 11px; color: #999; margin-top: 4px;">最后刷新: ${formatDateTime(log.created_at)}</div>
                            </div>
                            <button class="btn btn-sm btn-primary" onclick="retrySingleAccount(${log.account_id}, '${escapeJs(log.account_email)}')">
                                重试
                            </button>
                        </div>
                    `;
                });
                listEl.innerHTML = html;
            }
            container.style.display = 'block';
        }
    } catch (error) {
        showToast(translateAppTextLocal('加载失败邮箱列表失败'), 'error');
    }
}

// 加载刷新历史
async function loadRefreshLogs() {
    const container = document.getElementById('refreshLogsContainer');
    const listEl = document.getElementById('refreshLogsList');

    try {
        const response = await fetch('/api/accounts/refresh-logs?limit=1000');
        const data = await response.json();

        if (data.success) {
            if (data.logs.length === 0) {
                listEl.innerHTML = '<div style="padding: 20px; text-align: center; color: #666;">暂无全量刷新历史</div>';
            } else {
                listEl.innerHTML = `<div style="padding: 12px; background-color: #f8f9fa; border-bottom: 1px solid #e5e5e5; font-size: 13px; color: #666;">近半年刷新历史（共 ${data.logs.length} 条）</div>`;
                let html = '';
                data.logs.forEach(log => {
                    const statusColor = log.status === 'success' ? '#28a745' : '#dc3545';
                    const statusText = log.status === 'success' ? '成功' : '失败';
                    const typeText = translateAppTextLocal(log.refresh_type === 'manual' ? '手动' : '自动');
                    const typeColor = log.refresh_type === 'manual' ? '#007bff' : '#28a745';
                    const typeBgColor = log.refresh_type === 'manual' ? '#e7f3ff' : '#e8f5e9';

                    html += `
                        <div style="padding: 14px; border-bottom: 1px solid #e5e5e5; transition: background-color 0.2s;"
                             onmouseover="this.style.backgroundColor='#f8f9fa'"
                             onmouseout="this.style.backgroundColor='transparent'">
                            <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 6px;">
                                <div style="font-weight: 600; font-size: 14px;">${escapeHtml(log.account_email)}</div>
                                <div style="display: flex; gap: 8px; align-items: center;">
                                    <span style="font-size: 11px; padding: 3px 8px; background-color: ${typeBgColor}; color: ${typeColor}; border-radius: 4px; font-weight: 500;">${typeText}</span>
                                    <span style="font-size: 13px; color: ${statusColor}; font-weight: 600;">${statusText}</span>
                                </div>
                            </div>
                            <div style="font-size: 12px; color: #888;">${formatDateTime(log.created_at)}</div>
                            ${log.error_message ? `<div style="font-size: 12px; color: #dc3545; margin-top: 6px; padding: 6px; background-color: #fff5f5; border-radius: 4px;">${escapeHtml(log.error_message)}</div>` : ''}
                        </div>
                    `;
                });
                listEl.innerHTML += html;
            }
            container.style.display = 'block';
        }
    } catch (error) {
        showToast(translateAppTextLocal('加载刷新历史失败'), 'error');
    }
}

// 隐藏刷新历史
function hideRefreshLogs() {
    document.getElementById('refreshLogsContainer').style.display = 'none';
}

// ==================== 页面级：刷新日志 ====================

async function loadRefreshLogPage() {
    const container = document.getElementById('refreshLogContainer');
    if (!container) return;
    container.innerHTML = `<div class="loading-overlay"><span class="spinner"></span> ${translateAppTextLocal('加载中…')}</div>`;

    try {
        const response = await fetch('/api/accounts/refresh-logs?limit=200');
        const data = await response.json();

        if (data.success && data.logs && data.logs.length > 0) {
            container.innerHTML = `
                <div style="padding:0.6rem 1rem;font-size:0.78rem;color:var(--text-muted);border-bottom:1px solid var(--border-light);">
                    ${translateAppTextLocal(`共 ${data.logs.length} 条记录`)}
                </div>
                <div class="dashboard-list-wrap">
                    ${data.logs.map(log => {
                        const isSuccess = log.status === 'success';
                        const statusBadge = isSuccess
                            ? `<span class="badge" style="background:var(--clr-jade);color:white;">${translateAppTextLocal('成功')}</span>`
                            : `<span class="badge" style="background:var(--clr-danger);color:white;">${translateAppTextLocal('失败')}</span>`;
                        const typeText = translateAppTextLocal(
                            log.refresh_type === 'manual' ? '手动' : (log.refresh_type === 'scheduled' ? '定时' : (log.refresh_type || '-'))
                        );
                        return `
                            <div style="padding:0.75rem 1rem;border-bottom:1px solid var(--border-light);display:flex;align-items:center;gap:0.8rem;">
                                <div style="flex:1;min-width:0;">
                                    <div style="font-weight:600;font-size:0.85rem;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(log.account_email || '-')}</div>
                                    <div style="font-size:0.72rem;color:var(--text-muted);margin-top:2px;">${formatDateTime(log.created_at)} · ${escapeHtml(typeText)}</div>
                                    ${log.error_message ? `<div style="font-size:0.72rem;color:var(--clr-danger);margin-top:4px;padding:4px 8px;background:rgba(185,28,28,0.06);border-radius:4px;">${escapeHtml(log.error_message)}</div>` : ''}
                                </div>
                                ${statusBadge}
                            </div>
                        `;
                    }).join('')}
                </div>
            `;
        } else {
            container.innerHTML = `<div class="empty-state"><span class="empty-icon">📭</span><p>${translateAppTextLocal('暂无刷新记录')}</p></div>`;
        }
    } catch (error) {
        container.innerHTML = `<div class="empty-state"><span class="empty-icon">⚠️</span><p>${translateAppTextLocal('加载刷新历史失败')}</p></div>`;
    }
}

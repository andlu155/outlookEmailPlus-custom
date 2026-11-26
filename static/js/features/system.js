// ==================== 审计日志、版本更新与数据库备份 ====================

// ==================== 页面级：审计日志 ====================

function translateAuditDetailValue(value) {
    if (typeof value === 'string') {
        return translateAppTextLocal(value);
    }
    if (Array.isArray(value)) {
        return value.map(translateAuditDetailValue);
    }
    if (value && typeof value === 'object') {
        return Object.fromEntries(
            Object.entries(value).map(([key, nestedValue]) => [key, translateAuditDetailValue(nestedValue)])
        );
    }
    return value;
}

function formatAuditDetailText(details) {
    if (details == null) {
        return '';
    }
    if (typeof details === 'string') {
        const trimmed = details.trim();
        if ((trimmed.startsWith('{') && trimmed.endsWith('}')) || (trimmed.startsWith('[') && trimmed.endsWith(']'))) {
            try {
                return JSON.stringify(translateAuditDetailValue(JSON.parse(trimmed)));
            } catch (error) {
                return translateAppTextLocal(details);
            }
        }
        return translateAppTextLocal(details);
    }
    if (typeof details === 'object') {
        try {
            return JSON.stringify(translateAuditDetailValue(details));
        } catch (error) {
            return translateAppTextLocal(String(details));
        }
    }
    return translateAppTextLocal(String(details));
}

async function loadDiagnosticsPage() {
    const container = document.getElementById('diagnosticsContainer');
    const traceInput = document.getElementById('diagnosticsTraceId');
    if (!container) return;

    const traceId = traceInput ? traceInput.value.trim() : '';
    container.innerHTML = `<div class="loading-overlay"><span class="spinner"></span> ${translateAppTextLocal('加载中…')}</div>`;

    try {
        const params = new URLSearchParams({ limit: '100' });
        if (traceId) params.set('trace_id', traceId);
        const [diagnosticsResponse, auditResponse] = await Promise.all([
            fetch('/api/system/diagnostics'),
            fetch(`/api/audit-logs?${params.toString()}`),
        ]);
        const diagnosticsData = await diagnosticsResponse.json();
        const auditData = await auditResponse.json();
        const diagnostics = diagnosticsData.diagnostics || {};
        const schema = diagnostics.schema || {};
        const auditLogs = auditData.logs || [];
        const traceSummary = traceId ? `Trace ID: ${escapeHtml(traceId)}` : translateAppTextLocal('最近 100 条审计记录');

        container.innerHTML = `
            <div class="diagnostics-summary-grid">
                <div class="diagnostics-stat"><span>数据库版本</span><strong>${escapeHtml(String(schema.version ?? '-'))}</strong><small>${schema.up_to_date ? '已是目标版本' : '需要升级'}</small></div>
                <div class="diagnostics-stat"><span>运行中的刷新任务</span><strong>${escapeHtml(String((diagnostics.running_runs || []).length))}</strong><small>用于核对任务阻塞</small></div>
                <div class="diagnostics-stat"><span>活跃锁定 IP</span><strong>${escapeHtml(String(diagnostics.login_locked_ip_count ?? 0))}</strong><small>登录保护状态</small></div>
                <div class="diagnostics-stat"><span>关联审计记录</span><strong>${escapeHtml(String(auditData.total ?? auditLogs.length))}</strong><small>${traceSummary}</small></div>
            </div>
            <section class="diagnostics-panel">
                <div class="diagnostics-panel-header"><h3>关联审计记录</h3><span>${traceSummary}</span></div>
                ${auditLogs.length ? `<div class="diagnostics-log-list">${auditLogs.map(log => `
                    <article class="diagnostics-log-item">
                        <div><span class="badge">${escapeHtml(translateAppTextLocal(log.action || '-'))}</span><strong>${escapeHtml(log.resource_type || '-')}</strong></div>
                        <time>${escapeHtml(formatDateTime(log.created_at))}</time>
                        <p>${escapeHtml(formatAuditDetailText(log.details) || log.resource_id || '-')}</p>
                        <code>${escapeHtml(log.trace_id || '-')}</code>
                    </article>`).join('')}</div>` : `<div class="empty-state"><span class="empty-icon">🔎</span><p>${translateAppTextLocal('未找到关联审计记录')}</p></div>`}
            </section>`;
    } catch (error) {
        container.innerHTML = `<div class="empty-state"><span class="empty-icon">⚠️</span><p>${translateAppTextLocal('加载诊断信息失败')}</p></div>`;
    }
}

async function loadAuditLogPage() {
    const container = document.getElementById('auditLogContainer');
    if (!container) return;
    container.innerHTML = `<div class="loading-overlay"><span class="spinner"></span> ${translateAppTextLocal('加载中…')}</div>`;

    try {
        const response = await fetch('/api/audit-logs?limit=200');
        const data = await response.json();

        if (data.success && data.logs && data.logs.length > 0) {
            container.innerHTML = `
                <div style="padding:0.6rem 1rem;font-size:0.78rem;color:var(--text-muted);border-bottom:1px solid var(--border-light);">
                    ${translateAppTextLocal(`共 ${data.total || data.logs.length} 条记录`)}
                </div>
                <div class="dashboard-list-wrap">
                    ${data.logs.map(log => {
                        const actionColor = log.action === 'delete' ? 'var(--clr-danger)' : (log.action === 'create' ? 'var(--clr-jade)' : 'var(--clr-primary)');
                        const actionLabel = translateAppTextLocal(log.action || '-');
                        const resourceTypeLabel = translateAppTextLocal(log.resource_type || '-');
                        const detailText = formatAuditDetailText(log.details);
                        return `
                            <div style="padding:0.75rem 1rem;border-bottom:1px solid var(--border-light);">
                                <div style="display:flex;align-items:center;gap:0.6rem;margin-bottom:4px;">
                                    <span class="badge" style="background:${actionColor};color:white;font-size:0.68rem;">${escapeHtml(actionLabel)}</span>
                                    <span style="font-size:0.78rem;color:var(--text-muted);">${escapeHtml(resourceTypeLabel)}</span>
                                    <span style="font-size:0.72rem;color:var(--text-muted);margin-left:auto;">${formatDateTime(log.created_at)}</span>
                                </div>
                                <div style="font-size:0.82rem;color:var(--text);">${escapeHtml(log.resource_id || '-')}</div>
                                ${detailText ? `<div style="font-size:0.72rem;color:var(--text-muted);margin-top:4px;word-break:break-all;">${escapeHtml(detailText).substring(0, 200)}</div>` : ''}
                                <div style="font-size:0.68rem;color:var(--text-muted);margin-top:2px;">IP: ${escapeHtml(log.user_ip || '-')} ${log.trace_id ? '· trace: ' + escapeHtml(log.trace_id) : ''}</div>
                            </div>
                        `;
                    }).join('')}
                </div>
            `;
        } else {
            container.innerHTML = `<div class="empty-state"><span class="empty-icon">📭</span><p>${translateAppTextLocal('暂无审计记录')}</p></div>`;
        }
    } catch (error) {
        container.innerHTML = `<div class="empty-state"><span class="empty-icon">⚠️</span><p>${translateAppTextLocal('加载审计日志失败')}</p></div>`;
    }
}

// 格式化日期时间
function formatDateTime(dateStr) {
    return formatUiDateTime(dateStr, { fallback: '-' });
}

// ==================== 版本更新检测 ====================

/**
 * 页面加载时调用一次，检查是否有可用更新
 */
async function checkVersionUpdate() {
    try {
        const res = await fetch('/api/system/version-check');
        if (!res.ok) return;
        const data = await res.json();
        // 版本检查被管理员关闭时，不再提示也不再重试
        if (data.disabled) return;
        if (data.has_update) {
            const banner = document.getElementById('versionUpdateBanner');
            const msg = document.getElementById('versionUpdateMsg');
            if (!banner || !msg) return;
            msg.innerHTML = `发现新版本 <strong>v${data.latest_version}</strong>（当前 v${data.current_version}）
                <a href="${data.release_url}" target="_blank" class="ms-1">查看更新日志</a>`;
            banner.classList.remove('d-none');
            document.getElementById('app').style.paddingTop = banner.offsetHeight + 'px';
        }
    } catch (e) {
        // 静默失败
    }
}

function dismissVersionBanner() {
    document.getElementById('versionUpdateBanner').classList.add('d-none');
    document.getElementById('app').style.paddingTop = '';
}

/**
 * 用户点击"立即更新"时触发
 */
async function triggerUpdate() {
    const btn = document.getElementById('btnTriggerUpdate');
    btn.disabled = true;
    btn.textContent = translateAppTextLocal('正在触发更新...');

    // 获取更新方式（从设置中读取或默认为 watchtower）
    let updateMethod = 'watchtower';
    try {
        const settingsRes = await fetch('/api/settings');
        const settingsData = await settingsRes.json();
        if (settingsData.success && settingsData.settings) {
            updateMethod = settingsData.settings.update_method || 'watchtower';
        }
    } catch (e) {
        console.warn('Failed to load update method, using default (watchtower):', e);
    }

    try {
        // 根据更新方式决定 timeout 和 URL
        const timeout = updateMethod === 'docker_api' ? 120000 : 60000;  // Docker API 模式 120s, Watchtower 模式 60s
        const url = `/api/system/trigger-update?method=${updateMethod}`;

        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), timeout);

        const res = await fetch(url, {
            method: 'POST',
            headers: { 'X-CSRFToken': getCSRFToken() },
            signal: controller.signal
        });
        clearTimeout(timeoutId);

        const data = await res.json();
        if (data.success) {
            // 镜像已是最新，无需等待重启
            if (data.already_latest) {
                showToast(translateAppTextLocal('当前已是最新版本，无需更新'), 'info', 5000);
                btn.disabled = false;
                btn.textContent = translateAppTextLocal('立即更新');
                return;
            }

            // 记录本次更新方式，供 waitForRestart 调整等待时长
            try {
                window.__lastUpdateMethod = updateMethod;
            } catch (e) {}

            // Docker API 与 Watchtower 都可能触发容器重启：统一走“等待恢复”逻辑
            btn.textContent = translateAppTextLocal('等待容器重启...');
            if (updateMethod === 'docker_api') {
                showToast(translateAppTextLocal('Docker API 更新已启动，等待容器重启...'), 'info', 5000);
            }
            await waitForRestart();
        } else {
            const msg = data.message || '未知错误';
            // 区分常见错误场景，给出友好提示
            if (updateMethod === 'docker_api') {
                if (msg.includes('未启用') || msg.includes('DOCKER_SELF_UPDATE_ALLOW')) {
                    showToast(translateAppTextLocal('Docker API 自更新功能未启用。请在 .env 中设置 DOCKER_SELF_UPDATE_ALLOW=true，并在 docker-compose.yml 中挂载 docker.sock'), 'warning', 10000);
                } else if (msg.includes('docker.sock') || msg.includes('无法连接')) {
                    showToast(translateAppTextLocal('无法访问 Docker API。请确认已在 docker-compose.yml 中挂载 /var/run/docker.sock'), 'warning', 8000);
                } else {
                    showToast(translateAppTextLocal('Docker API 更新失败：') + msg, 'error', 8000);
                }
            } else {
                if (msg.includes('WATCHTOWER_HTTP_API_TOKEN') || (msg.includes('未配置') && res.status === 500)) {
                    showToast(translateAppTextLocal('一键更新需要配置 Watchtower 服务（仅 Docker 部署支持）。请在 .env 中设置 WATCHTOWER_HTTP_API_TOKEN，并使用含 Watchtower 的 docker-compose 部署方式'), 'warning', 10000);
                } else if (msg.includes('无法连接') || msg.includes('Watchtower')) {
                    showToast(translateAppTextLocal('无法连接 Watchtower 服务，请确认已使用 docker-compose 方式部署，且 watchtower 容器正常运行'), 'warning', 8000);
                } else {
                    showToast(translateAppTextLocal('更新失败：') + msg, 'error');
                }
            }
            btn.disabled = false;
            btn.textContent = translateAppTextLocal('立即更新');
        }
    } catch (e) {
        if (e.name === 'AbortError') {
            showToast(translateAppTextLocal('更新请求超时，请检查配置和网络连接'), 'error', 8000);
        } else {
            showToast(translateAppTextLocal('更新请求失败，请检查网络连接'), 'error');
        }
        btn.disabled = false;
        btn.textContent = translateAppTextLocal('立即更新');
    }
}

/**
 * 轮询 /healthz 等待容器重启后恢复
 * - 立即开始轮询，每 3 秒一次
 * - 最长等待 90 秒，超时提示用户手动检查
 * - 检测到服务恢复后刷新页面
 */
async function waitForRestart() {
    // 默认 90 秒（Watchtower 通常更快）；Docker API 更新可能涉及 pull 镜像，适当放宽
    const WATCHTOWER_MAX_WAIT_MS = 90000;  // 90 秒
    const DOCKER_API_MAX_WAIT_MS = 180000;  // 180 秒
    const POLL_INTERVAL_MS = 3000;  // 每 3 秒

    let MAX_WAIT_MS = WATCHTOWER_MAX_WAIT_MS;
    try {
        const method = (window.__lastUpdateMethod || 'watchtower');
        if (method === 'docker_api') {
            MAX_WAIT_MS = DOCKER_API_MAX_WAIT_MS;
        }
    } catch (e) {
        MAX_WAIT_MS = WATCHTOWER_MAX_WAIT_MS;
    }
    const startAt = Date.now();
    let seenDown = false;
    let initialBootId = null;

    // 先读取一次 boot_id，用于判断是否发生“新进程启动”
    try {
        const firstRes = await fetch('/healthz', { cache: 'no-store' });
        if (firstRes.ok) {
            const firstData = await firstRes.json();
            if (firstData && firstData.boot_id) {
                initialBootId = String(firstData.boot_id);
            }
        }
    } catch (e) {
        // ignore
    }

    while (Date.now() - startAt < MAX_WAIT_MS) {
        await new Promise(resolve => setTimeout(resolve, POLL_INTERVAL_MS));
        try {
            const res = await fetch('/healthz', { cache: 'no-store' });
            if (res.ok) {
                let bootIdChanged = false;
                try {
                    const d = await res.json();
                    const bootId = d && d.boot_id ? String(d.boot_id) : null;
                    if (bootId && initialBootId && bootId !== initialBootId) {
                        bootIdChanged = true;
                    }
                } catch (e) {
                    // ignore json parse
                }

                // 以“boot_id 变化”作为更可靠的重启完成信号
                if (bootIdChanged || seenDown) {
                    showToast(translateAppTextLocal('更新完成，正在刷新页面...'), 'success');
                    setTimeout(() => location.reload(), 1500);
                    return;
                }
                // 还没看到重启迹象：可能仍在 pull/重建中，继续等
            } else {
                seenDown = true;
            }
        } catch (e) {
            // 请求失败通常意味着容器正在重启/网络暂不可用
            seenDown = true;
        }
    }

    // 超时处理
    try {
        const method = (window.__lastUpdateMethod || 'watchtower');
        if (method === 'docker_api') {
            if (!seenDown) {
                showToast(translateAppTextLocal('等待超时：容器未发生重启，可能已是最新版本或更新仍在后台进行'), 'warning', 9000);
            } else {
                showToast(translateAppTextLocal('等待超时：容器尚未恢复，请检查容器状态/日志'), 'warning', 9000);
            }
        } else {
            if (!seenDown) {
                showToast(translateAppTextLocal('等待超时：容器未发生重启，请检查 Watchtower 配置/日志'), 'warning', 9000);
            } else {
                showToast(translateAppTextLocal('更新超时，请手动检查容器状态'), 'warning', 8000);
            }
        }
    } catch (e) {
        showToast(translateAppTextLocal('更新超时，请手动检查容器状态'), 'warning', 8000);
    }
    const btn = document.getElementById('btnTriggerUpdate');
    if (btn) {
        btn.disabled = false;
        btn.textContent = translateAppTextLocal('立即更新');
    }
}

/**
 * 设置面板：下载 SQLite 一致性快照备份
 */
async function downloadDatabaseBackup() {
    const btn = document.getElementById('btnDownloadDatabaseBackup');
    const resultDiv = document.getElementById('databaseBackupResult');
    if (btn) {
        btn.disabled = true;
        btn.textContent = translateAppTextLocal('正在生成备份…');
    }
    if (resultDiv) {
        resultDiv.style.display = 'none';
        resultDiv.innerHTML = '';
    }

    try {
        const res = await fetch('/api/system/database-backup', {
            method: 'GET',
            credentials: 'same-origin',
            headers: { 'X-CSRFToken': getCSRFToken() },
        });
        if (!res.ok) {
            let message = translateAppTextLocal('数据库备份失败，请稍后重试');
            try {
                const data = await res.json();
                message = pickApiMessage(data, message, data.message_en || message);
            } catch (_err) {
                // keep default message
            }
            throw new Error(message);
        }

        const blob = await res.blob();
        let filename = 'outlook_accounts_backup.db';
        const disposition = res.headers.get('Content-Disposition') || '';
        const utfMatch = disposition.match(/filename\*=UTF-8''([^;]+)/i);
        const plainMatch = disposition.match(/filename=\"?([^\";]+)\"?/i);
        if (utfMatch && utfMatch[1]) {
            try {
                filename = decodeURIComponent(utfMatch[1]);
            } catch (_err) {
                filename = utfMatch[1];
            }
        } else if (plainMatch && plainMatch[1]) {
            filename = plainMatch[1];
        }

        const objectUrl = URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = objectUrl;
        anchor.download = filename;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);

        if (resultDiv) {
            resultDiv.style.display = 'block';
            resultDiv.style.color = 'var(--clr-success, #3A7D44)';
            resultDiv.textContent = translateAppTextLocal('备份已开始下载');
        }
        if (typeof showToast === 'function') {
            showToast(translateAppTextLocal('数据库备份已开始下载'), 'success');
        }
    } catch (error) {
        const message = (error && error.message)
            ? error.message
            : translateAppTextLocal('数据库备份失败，请稍后重试');
        if (resultDiv) {
            resultDiv.style.display = 'block';
            resultDiv.style.color = 'var(--clr-danger, #C75050)';
            resultDiv.textContent = message;
        }
        if (typeof showToast === 'function') {
            showToast(message, 'error');
        }
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = translateAppTextLocal('下载备份');
        }
    }
}

/**
 * 设置面板中的"手动触发更新"按钮回调
 * 与 triggerUpdate() 类似，但 UI 反馈在设置面板内
 */
async function manualTriggerUpdate() {
    const btn = document.getElementById('btnManualTriggerUpdate');
    const resultDiv = document.getElementById('manualUpdateResult');
    if (!btn) return;

    btn.disabled = true;
    btn.textContent = translateAppTextLocal('正在触发更新...');
    if (resultDiv) {
        resultDiv.style.display = 'none';
        resultDiv.innerHTML = '';
    }

    // 读取当前选择的更新方式
    const selectedRadio = document.querySelector('input[name="updateMethod"]:checked');
    const updateMethod = selectedRadio ? selectedRadio.value : 'watchtower';

    try {
        const timeout = updateMethod === 'docker_api' ? 120000 : 60000;
        const url = `/api/system/trigger-update?method=${updateMethod}`;

        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), timeout);

        const res = await fetch(url, {
            method: 'POST',
            headers: { 'X-CSRFToken': getCSRFToken() },
            signal: controller.signal
        });
        clearTimeout(timeoutId);

        const data = await res.json();
        if (data.success) {
            if (resultDiv) {
                resultDiv.style.display = 'block';
                const msg = pickApiMessage(data, '更新已触发', 'Update triggered');
                resultDiv.innerHTML = `<span style="color: var(--clr-success, #28a745);">✅ ${escapeHtml(msg)}</span>`;
            }
            // 镜像已是最新，无需等待重启
            if (data.already_latest) {
                showToast(pickApiMessage(data, '当前已是最新版本', 'Already up to date'), 'info', 5000);
                btn.disabled = false;
                btn.textContent = translateAppTextLocal('立即更新');
                return;
            }
            window.__lastUpdateMethod = updateMethod;
            btn.textContent = translateAppTextLocal('等待容器重启...');
            await waitForRestart();
        } else {
            const msg = data.message || '未知错误';
            const detail = data.detail ? `\n详情: ${data.detail}` : '';
            if (resultDiv) {
                resultDiv.style.display = 'block';
                resultDiv.innerHTML = `<span style="color: var(--clr-danger, #dc3545);">❌ ${escapeHtml(msg)}</span>${detail ? '<br><small style="color: var(--text-muted);">' + escapeHtml(detail.trim()) + '</small>' : ''}`;
            }
            showToast(translateAppTextLocal('更新失败：') + msg, 'error', 8000);
            btn.disabled = false;
            btn.textContent = translateAppTextLocal('立即更新');
        }
    } catch (e) {
        const errMsg = e.name === 'AbortError' ? translateAppTextLocal('请求超时') : (e.message || translateAppTextLocal('网络错误'));
        if (resultDiv) {
            resultDiv.style.display = 'block';
            resultDiv.innerHTML = `<span style="color: var(--clr-danger, #dc3545);">❌ ${escapeHtml(errMsg)}</span>`;
        }
        showToast(translateAppTextLocal('更新请求失败：') + errMsg, 'error', 8000);
        btn.disabled = false;
        btn.textContent = translateAppTextLocal('立即更新');
    }
}

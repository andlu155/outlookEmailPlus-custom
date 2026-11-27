// ==================== 精简系统设置（3 Tab：基础与代理 / 刷新与推送 / 临时邮箱与系统） ====================

function switchSettingsTab(tabName) {
    document.querySelectorAll('#settingsTabNav .settings-tab').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tabName);
    });
    document.querySelectorAll('#settingsModalBody .settings-tab-pane').forEach(pane => {
        pane.classList.toggle('active', pane.dataset.tab === tabName);
    });
}

async function showSettingsModal() {
    document.getElementById('settingsModal').classList.add('show');
    await loadSettings();
}

function hideSettingsModal() {
    document.getElementById('settingsModal').classList.remove('show');
}

function _setMaskedSecretInput(elId, isSet, maskedValue) {
    const el = document.getElementById(elId);
    if (!el) return;
    el.dataset.isSet = isSet ? 'true' : 'false';
    el.dataset.maskedValue = maskedValue || '';
    el.value = isSet ? (maskedValue || '') : '';
}

function _readMaskedSecretInput(elId) {
    const el = document.getElementById(elId);
    if (!el) return { el: null, value: '', shouldSend: false, hasValue: false };
    const value = el.value.trim();
    const masked = el.dataset.maskedValue || '';
    const isSet = el.dataset.isSet === 'true';
    const unchangedMasked = isSet && Boolean(value) && value === masked;
    return {
        el,
        value,
        shouldSend: !unchangedMasked,
        hasValue: Boolean(value) || unchangedMasked
    };
}

async function loadSettings() {
    try {
        const res = await fetch('/api/settings');
        const data = await res.json();
        if (!data.success || !data.settings) return;
        const s = data.settings;

        // Tab 1: 基础与代理
        document.getElementById('settingsPassword').value = '';
        document.getElementById('settingsGlobalProxyEnabled').checked = s.global_proxy_enabled === true || s.global_proxy_enabled === 'true';
        document.getElementById('settingsGlobalProxyUrl').value = s.global_proxy_url || '';
        document.getElementById('globalProxyTestResult').textContent = '';

        document.getElementById('settingsVerificationAiEnabled').checked = s.verification_ai_enabled === true || s.verification_ai_enabled === 'true';
        document.getElementById('settingsVerificationAiBaseUrl').value = s.verification_ai_base_url || '';
        document.getElementById('settingsVerificationAiModel').value = s.verification_ai_model || '';
        _setMaskedSecretInput('settingsVerificationAiApiKey', Boolean(s.verification_ai_api_key_set), s.verification_ai_api_key_masked);
        document.getElementById('verificationAiTestResult').textContent = '';

        // Tab 2: 刷新与 Telegram 推送
        document.getElementById('enableScheduledRefresh').checked = s.enable_scheduled_refresh === true || s.enable_scheduled_refresh === 'true';
        document.getElementById('refreshIntervalDays').value = s.refresh_interval_days ?? 30;
        document.getElementById('refreshDelaySeconds').value = s.refresh_delay_seconds ?? 5;

        document.getElementById('telegramBotToken').value = s.telegram_bot_token_set ? (s.telegram_bot_token_masked || '') : '';
        document.getElementById('telegramChatId').value = s.telegram_chat_id || '';
        document.getElementById('telegramPollInterval').value = s.telegram_poll_interval ?? 300;

        // Tab 3: CF 临时邮箱、单 Key API、数据库备份
        document.getElementById('settingsCfWorkerBaseUrl').value = s.cf_worker_base_url || '';
        _setMaskedSecretInput('settingsCfWorkerAdminKey', Boolean(s.cf_worker_admin_key_set), s.cf_worker_admin_key_masked);
        const cfDomains = Array.isArray(s.cf_worker_domains)
            ? s.cf_worker_domains.map(d => (typeof d === 'string' ? d : d.name || '')).filter(Boolean).join(', ')
            : '';
        document.getElementById('settingsCfWorkerDomains').value = cfDomains;
        document.getElementById('settingsCfWorkerDefaultDomain').value = s.cf_worker_default_domain || '';
        document.getElementById('cfSyncResult').textContent = '';

        _setMaskedSecretInput('settingsExternalApiKey', Boolean(s.external_api_key_set), s.external_api_key_masked);
        document.getElementById('databaseBackupResult').textContent = '';
    } catch (e) {
        showToast('加载设置失败', 'error');
    }
}

async function saveSettings() {
    const payload = {};

    const pw = document.getElementById('settingsPassword').value;
    if (pw) payload.login_password = pw;

    // 全局代理
    const globalProxyEnabled = document.getElementById('settingsGlobalProxyEnabled').checked;
    const globalProxyUrl = document.getElementById('settingsGlobalProxyUrl').value.trim();
    if (globalProxyEnabled && !globalProxyUrl) {
        showToast('开启全局代理前请先填写全局代理地址', 'error');
        return;
    }
    payload.global_proxy_enabled = globalProxyEnabled;
    payload.global_proxy_url = globalProxyUrl;

    // 验证码 AI
    const aiEnabled = document.getElementById('settingsVerificationAiEnabled').checked;
    const aiBaseUrl = document.getElementById('settingsVerificationAiBaseUrl').value.trim();
    const aiModel = document.getElementById('settingsVerificationAiModel').value.trim();
    const aiKey = _readMaskedSecretInput('settingsVerificationAiApiKey');
    if (aiEnabled && (!aiBaseUrl || !aiModel || !aiKey.hasValue)) {
        showToast('启用验证码 AI 需完整填写 Base URL、API Key 与模型 ID', 'error');
        return;
    }
    payload.verification_ai_enabled = aiEnabled;
    payload.verification_ai_base_url = aiBaseUrl;
    payload.verification_ai_model = aiModel;
    if (aiKey.shouldSend) payload.verification_ai_api_key = aiKey.value;

    // 定时刷新
    const days = parseInt(document.getElementById('refreshIntervalDays').value, 10);
    const delay = parseInt(document.getElementById('refreshDelaySeconds').value, 10);
    if (isNaN(days) || days < 1 || days > 90) {
        showToast('刷新周期必须在 1-90 天之间', 'error');
        return;
    }
    if (isNaN(delay) || delay < 0 || delay > 60) {
        showToast('单号间隔必须在 0-60 秒之间', 'error');
        return;
    }
    payload.enable_scheduled_refresh = document.getElementById('enableScheduledRefresh').checked;
    payload.use_cron_schedule = false;
    payload.refresh_interval_days = days;
    payload.refresh_delay_seconds = delay;

    // Telegram 推送（自动复用全局代理，清空旧独立代理字段避免误覆盖）
    const tgToken = document.getElementById('telegramBotToken').value.trim();
    const tgChatId = document.getElementById('telegramChatId').value.trim();
    const tgPoll = parseInt(document.getElementById('telegramPollInterval').value, 10);
    if (!isNaN(tgPoll) && (tgPoll < 10 || tgPoll > 86400)) {
        showToast('Telegram 轮询间隔必须在 10-86400 秒之间', 'error');
        return;
    }
    payload.telegram_bot_token = tgToken;
    payload.telegram_chat_id = tgChatId;
    if (!isNaN(tgPoll)) payload.telegram_poll_interval = tgPoll;
    payload.telegram_proxy_url = '';

    // CF 临时邮箱（固定收敛为 cloudflare_temp_mail）
    payload.temp_mail_provider = 'cloudflare_temp_mail';
    payload.cf_worker_base_url = document.getElementById('settingsCfWorkerBaseUrl').value.trim();
    const cfKey = _readMaskedSecretInput('settingsCfWorkerAdminKey');
    if (cfKey.shouldSend) payload.cf_worker_admin_key = cfKey.value;

    // 对外开放 API（单 Key）
    const extKey = _readMaskedSecretInput('settingsExternalApiKey');
    if (extKey.shouldSend) payload.external_api_key = extKey.value;

    const btn = document.getElementById('btnSaveSettings');
    btn.disabled = true;
    try {
        const res = await fetch('/api/settings', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.success) {
            showToast(pickApiMessage(data, '设置已保存', 'Settings saved'), 'success');
            hideSettingsModal();
        } else {
            handleApiError(data, '保存设置失败');
        }
    } catch (_) {
        showToast('保存设置失败', 'error');
    } finally {
        btn.disabled = false;
    }
}

async function runProxyConnectivityTest(proxyUrl, btnEl, resultEl, defaultLabel) {
    if (!proxyUrl) {
        if (resultEl) {
            resultEl.textContent = '❌ 请先输入代理地址';
            resultEl.style.color = 'var(--clr-danger)';
        }
        return;
    }
    if (btnEl) { btnEl.disabled = true; btnEl.textContent = '⏳ 测试中…'; }
    if (resultEl) resultEl.textContent = '';
    try {
        const res = await fetch('/api/settings/test-proxy', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ proxy_url: proxyUrl })
        });
        const data = await res.json();
        if (data.ok) {
            const ms = typeof data.latency_ms === 'number' ? ` (${data.latency_ms}ms)` : '';
            if (resultEl) {
                resultEl.textContent = `✅ 连通成功${ms}`;
                resultEl.style.color = 'var(--clr-success)';
            }
        } else if (resultEl) {
            resultEl.textContent = `❌ ${data.message || '连接失败'}`;
            resultEl.style.color = 'var(--clr-danger)';
        }
    } catch (e) {
        if (resultEl) {
            resultEl.textContent = `❌ ${e.message}`;
            resultEl.style.color = 'var(--clr-danger)';
        }
    } finally {
        if (btnEl) { btnEl.disabled = false; btnEl.textContent = defaultLabel || '🔗 测试连通性'; }
    }
}

async function testGlobalProxy() {
    await runProxyConnectivityTest(
        document.getElementById('settingsGlobalProxyUrl').value.trim(),
        document.getElementById('btnTestGlobalProxy'),
        document.getElementById('globalProxyTestResult'),
        '🔗 测试连通性'
    );
}

async function testVerificationAiConfig() {
    const btn = document.getElementById('btnTestVerificationAi');
    const resultEl = document.getElementById('verificationAiTestResult');
    const aiKey = _readMaskedSecretInput('settingsVerificationAiApiKey');
    btn.disabled = true;
    btn.textContent = '⏳ 测试中…';
    resultEl.textContent = '';
    try {
        const payload = {
            base_url: document.getElementById('settingsVerificationAiBaseUrl').value.trim(),
            model: document.getElementById('settingsVerificationAiModel').value.trim()
        };
        if (aiKey.shouldSend) payload.api_key = aiKey.value;
        const res = await fetch('/api/settings/verification-ai-test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.success) {
            resultEl.textContent = '✅ AI 接口探测成功';
            resultEl.style.color = 'var(--clr-success)';
        } else {
            resultEl.textContent = `❌ ${(data.error && data.error.message) || data.message || '探测失败'}`;
            resultEl.style.color = 'var(--clr-danger)';
        }
    } catch (e) {
        resultEl.textContent = `❌ ${e.message}`;
        resultEl.style.color = 'var(--clr-danger)';
    } finally {
        btn.disabled = false;
        btn.textContent = '🧪 测试 AI 配置';
    }
}

async function testTelegramPush() {
    const btn = document.getElementById('btnTestTelegram');
    btn.disabled = true;
    btn.textContent = '⏳ 发送中…';
    try {
        const res = await fetch('/api/settings/telegram-test', { method: 'POST' });
        const data = await res.json();
        if (data.success) showToast('测试消息已发送，请检查 Telegram', 'success');
        else handleApiError(data, '发送测试消息失败');
    } catch (_) {
        showToast('发送测试消息失败', 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = '📨 发送测试消息';
    }
}

async function syncCfWorkerDomains() {
    const btn = document.getElementById('btnSyncCfWorkerDomains');
    const resultEl = document.getElementById('cfSyncResult');
    const cfKey = _readMaskedSecretInput('settingsCfWorkerAdminKey');
    const payload = {
        cf_worker_base_url: document.getElementById('settingsCfWorkerBaseUrl').value.trim()
    };
    if (cfKey.shouldSend && cfKey.value) payload.cf_worker_admin_key = cfKey.value;

    btn.disabled = true;
    btn.textContent = '⏳ 同步中…';
    resultEl.textContent = '';
    try {
        const res = await fetch('/api/settings/cf-worker-sync-domains', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.success) {
            const list = (data.domains || []).map(d => (typeof d === 'string' ? d : d.name || '')).filter(Boolean);
            document.getElementById('settingsCfWorkerDomains').value = list.join(', ');
            document.getElementById('settingsCfWorkerDefaultDomain').value = data.default_domain || list[0] || '';
            resultEl.textContent = `✅ 已同步 ${list.length} 个域名`;
            resultEl.style.color = 'var(--clr-success)';
        } else {
            resultEl.textContent = `❌ ${(data.error && data.error.message) || data.message || '同步失败'}`;
            resultEl.style.color = 'var(--clr-danger)';
        }
    } catch (e) {
        resultEl.textContent = `❌ ${e.message}`;
        resultEl.style.color = 'var(--clr-danger)';
    } finally {
        btn.disabled = false;
        btn.textContent = '🔄 同步可用域名';
    }
}

function generateExternalApiKey() {
    const input = document.getElementById('settingsExternalApiKey');
    if (input.value.trim() && !confirm('当前已存在 API Key，是否覆盖？')) return;
    const bytes = new Uint8Array(32);
    window.crypto.getRandomValues(bytes);
    const hex = Array.from(bytes).map(b => b.toString(16).padStart(2, '0')).join('');
    input.value = `omp_${hex}`;
    input.dataset.isSet = 'false';
    input.dataset.maskedValue = '';
    showToast('已生成新 API Key，请点击「保存设置」使其生效', 'info');
}

async function copyExternalApiKey() {
    const input = document.getElementById('settingsExternalApiKey');
    const val = input.value.trim();
    const isUnchangedMasked = input.dataset.isSet === 'true' && val === (input.dataset.maskedValue || '');
    if (isUnchangedMasked) {
        try {
            const res = await fetch('/api/settings/external-api-key/plaintext');
            const data = await res.json();
            if (data.success && data.external_api_key) {
                await copyToClipboard(data.external_api_key, 'API Key');
                return;
            }
        } catch (_) {}
    }
    if (!val) {
        showToast('当前未设置 API Key', 'warning');
        return;
    }
    await copyToClipboard(val, 'API Key');
}

async function downloadDatabaseBackup() {
    const btn = document.getElementById('btnDownloadDatabaseBackup');
    const resultEl = document.getElementById('databaseBackupResult');
    btn.disabled = true;
    btn.textContent = '⏳ 生成快照…';
    resultEl.textContent = '';
    try {
        const res = await fetch('/api/system/database-backup', {
            method: 'GET',
            credentials: 'same-origin',
            headers: { 'X-CSRFToken': getCSRFToken() }
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error((err.error && err.error.message) || err.message || '数据库备份失败');
        }
        const blob = await res.blob();
        const disp = res.headers.get('Content-Disposition') || '';
        const match = disp.match(/filename="?([^";]+)"?/i);
        const filename = (match && match[1]) || 'outlook_accounts_backup.db';
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        resultEl.textContent = '✅ 备份已开始下载';
        resultEl.style.color = 'var(--clr-success)';
    } catch (e) {
        resultEl.textContent = `❌ ${e.message}`;
        resultEl.style.color = 'var(--clr-danger)';
    } finally {
        btn.disabled = false;
        btn.textContent = '📥 下载数据库快照';
    }
}

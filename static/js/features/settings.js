// ==================== 设置页面、代理测试与自动轮询配置 ====================

// ==================== 设置相关 ====================

// ==================== 一键更新配置（更新方式切换） ====================

function toggleUpdateMethodConfig() {
    const watchtowerConfigArea = document.getElementById('watchtowerConfigArea');
    const dockerApiWarning = document.getElementById('dockerApiWarning');
    if (!watchtowerConfigArea || !dockerApiWarning) return;

    const selectedMethod = document.querySelector('input[name="updateMethod"]:checked')?.value;
    if (selectedMethod === 'docker_api') {
        watchtowerConfigArea.style.display = 'none';
        dockerApiWarning.style.display = 'block';
    } else {
        watchtowerConfigArea.style.display = 'block';
        dockerApiWarning.style.display = 'none';
    }
}

function initUpdateMethodConfigToggles() {
    try {
        const updateMethodRadios = document.getElementsByName('updateMethod');
        if (!updateMethodRadios || updateMethodRadios.length === 0) {
            return;
        }

        updateMethodRadios.forEach((radio) => {
            if (!radio) return;
            // 防止重复绑定（某些情况下可能多次初始化）
            if (radio.dataset && radio.dataset.boundUpdateMethodToggle === 'true') {
                return;
            }
            radio.addEventListener('change', toggleUpdateMethodConfig);
            if (radio.dataset) {
                radio.dataset.boundUpdateMethodToggle = 'true';
            }
        });

        // 初始化时调用一次，确保初始显隐正确
        toggleUpdateMethodConfig();
    } catch (e) {
        // 静默失败：不影响其它功能
    }
}

// 显示设置模态框
async function showSettingsModal() {
    document.getElementById('settingsModal').classList.add('show');
    await loadSettings();
}

// 隐藏设置模态框
function hideSettingsModal() {
    document.getElementById('settingsModal').classList.remove('show');
    // 清空密码输入框
    document.getElementById('settingsPassword').value = '';
}

function buildExternalApiKeysEditorItems(items) {
    if (!Array.isArray(items)) return [];

    return items.map((item, index) => {
        if (!item || typeof item !== 'object' || Array.isArray(item)) {
            throw new Error(`第 ${index + 1} 项必须是对象`);
        }

        const normalized = {
            name: item.name || '',
            api_key: item.api_key || item.api_key_masked || '',
            enabled: !(item.enabled === false || item.enabled === 'false' || item.enabled === 0 || item.enabled === '0'),
            pool_access: item.pool_access === true || item.pool_access === 'true' || item.pool_access === 1 || item.pool_access === '1',
            allowed_emails: Array.isArray(item.allowed_emails) ? item.allowed_emails : []
        };

        if (item.id !== undefined && item.id !== null && item.id !== '') {
            normalized.id = item.id;
        }

        return normalized;
    });
}

function setExternalApiKeysEditor(items) {
    const editorEl = document.getElementById('settingsExternalApiKeysJson');
    if (!editorEl) return;

    const normalized = buildExternalApiKeysEditorItems(items);
    const prettyValue = normalized.length ? JSON.stringify(normalized, null, 2) : '';
    editorEl.value = prettyValue;
    editorEl.dataset.originalCanonical = JSON.stringify(normalized);

    const hintEl = document.getElementById('externalApiKeysJsonHint');
    if (!hintEl) return;

    if (normalized.length > 0) {
        hintEl.textContent = `当前已配置 ${normalized.length} 个多 Key。保留已有脱敏 api_key 表示不修改该 Key；清空后保存表示清空全部多 Key。`;
    } else {
        hintEl.textContent = '用于按调用方维护多个 Key、邮箱范围授权和启停状态。保留已有脱敏 api_key 表示不修改该 Key；清空后保存表示清空全部多 Key。';
    }
}

// 加载设置
async function loadSettings() {
    try {
        const response = await fetch('/api/settings');
        const data = await response.json();

        if (data.success) {
            // 密码不回显
            document.getElementById('settingsPassword').value = '';

            const verificationAiEnabledEl = document.getElementById('settingsVerificationAiEnabled');
            if (verificationAiEnabledEl) {
                verificationAiEnabledEl.checked = !!data.settings.verification_ai_enabled;
            }

            const verificationAiBaseUrlEl = document.getElementById('settingsVerificationAiBaseUrl');
            if (verificationAiBaseUrlEl) {
                verificationAiBaseUrlEl.value = data.settings.verification_ai_base_url || '';
            }

            const verificationAiModelEl = document.getElementById('settingsVerificationAiModel');
            if (verificationAiModelEl) {
                verificationAiModelEl.value = data.settings.verification_ai_model || '';
            }

            const verificationAiApiKeyEl = document.getElementById('settingsVerificationAiApiKey');
            if (verificationAiApiKeyEl) {
                const maskedValue = data.settings.verification_ai_api_key_masked || '';
                verificationAiApiKeyEl.value = maskedValue;
                verificationAiApiKeyEl.dataset.maskedValue = maskedValue;
                verificationAiApiKeyEl.dataset.isSet = data.settings.verification_ai_api_key_set ? 'true' : 'false';
            }

            const verificationAiApiKeyHintEl = document.getElementById('verificationAiApiKeyHint');
            if (verificationAiApiKeyHintEl) {
                if (data.settings.verification_ai_api_key_set) {
                    verificationAiApiKeyHintEl.textContent = `已设置：${data.settings.verification_ai_api_key_masked || ''}`;
                } else {
                    verificationAiApiKeyHintEl.textContent = '未设置';
                }
            }

            const verificationAiTestResultEl = document.getElementById('verificationAiTestResult');
            if (verificationAiTestResultEl) {
                verificationAiTestResultEl.textContent = '建议先保存配置再测试。';
                verificationAiTestResultEl.style.color = 'var(--text-secondary, #666)';
            }

            // v0.3: Provider 选择器改为单选按钮
            const rawProvider = data.settings.temp_mail_provider || 'legacy_bridge';
            const mappedProvider = (rawProvider === 'custom_domain_temp_mail' || rawProvider === 'legacy_bridge' || rawProvider === 'legacy_gptmail' || rawProvider === 'gptmail')
                ? 'legacy_bridge'
                : rawProvider;
            const providerGroup = document.querySelector('.provider-radio-group');
            if (providerGroup) {
                providerGroup.dataset.pendingProvider = mappedProvider;
            }
            const radioBtn = document.querySelector(`input[name="tempMailProvider"][value="${mappedProvider}"]`);
            if (radioBtn) {
                radioBtn.checked = true;
                if (providerGroup) {
                    providerGroup.dataset.pendingProvider = '';
                }
            }
            if (typeof onTempMailProviderChange === 'function') {
                onTempMailProviderChange(mappedProvider);
            }

            const tempMailApiBaseUrlEl = document.getElementById('settingsTempMailApiBaseUrl');
            if (tempMailApiBaseUrlEl) {
                tempMailApiBaseUrlEl.value = data.settings.temp_mail_api_base_url || '';
            }

            // 临时邮箱 API Key（v0.3: ID 从 settingsApiKey 改为 settingsTempMailApiKey）
            const tempMailApiKeyEl = document.getElementById('settingsTempMailApiKey');
            if (tempMailApiKeyEl) {
                const maskedValue = data.settings.temp_mail_api_key_masked || '';
                tempMailApiKeyEl.value = maskedValue;
                tempMailApiKeyEl.dataset.maskedValue = maskedValue;
                tempMailApiKeyEl.dataset.isSet = data.settings.temp_mail_api_key_set ? 'true' : 'false';
            }

            const tempMailDomainsEl = document.getElementById('settingsTempMailDomains');
            if (tempMailDomainsEl) {
                const domains = Array.isArray(data.settings.temp_mail_domains) ? data.settings.temp_mail_domains : [];
                tempMailDomainsEl.value = domains.length ? JSON.stringify(domains, null, 2) : '';
            }

            const tempMailDefaultDomainEl = document.getElementById('settingsTempMailDefaultDomain');
            if (tempMailDefaultDomainEl) {
                tempMailDefaultDomainEl.value = data.settings.temp_mail_default_domain || '';
            }

            const tempMailPrefixRulesEl = document.getElementById('settingsTempMailPrefixRules');
            if (tempMailPrefixRulesEl) {
                const prefixRules = data.settings.temp_mail_prefix_rules || {};
                tempMailPrefixRulesEl.value = Object.keys(prefixRules).length ? JSON.stringify(prefixRules, null, 2) : '';
            }

            // CF Worker 独立配置
            const cfWorkerBaseUrlEl = document.getElementById('settingsCfWorkerBaseUrl');
            if (cfWorkerBaseUrlEl) {
                cfWorkerBaseUrlEl.value = data.settings.cf_worker_base_url || '';
            }

            const cfWorkerAdminKeyEl = document.getElementById('settingsCfWorkerAdminKey');
            if (cfWorkerAdminKeyEl) {
                const cfMasked = data.settings.cf_worker_admin_key_masked || '';
                cfWorkerAdminKeyEl.value = cfMasked;
                cfWorkerAdminKeyEl.dataset.maskedValue = cfMasked;
                cfWorkerAdminKeyEl.dataset.isSet = data.settings.cf_worker_admin_key_set ? 'true' : 'false';
            }

            // v0.3: CF Worker 独立域名配置（只读字段）
            const cfWorkerDomainsEl = document.getElementById('settingsCfWorkerDomains');
            if (cfWorkerDomainsEl) {
                const cfDomains = data.settings.cf_worker_domains || [];
                cfWorkerDomainsEl.value = cfDomains.length ? JSON.stringify(cfDomains, null, 2) : '';
                cfWorkerDomainsEl.classList.add('readonly-field');
                cfWorkerDomainsEl.readOnly = true;
                if (!cfDomains.length) {
                    cfWorkerDomainsEl.setAttribute('placeholder', '尚未同步，请点击上方按钮同步');
                }
            }

            const cfWorkerDefaultDomainEl = document.getElementById('settingsCfWorkerDefaultDomain');
            if (cfWorkerDefaultDomainEl) {
                cfWorkerDefaultDomainEl.value = data.settings.cf_worker_default_domain || '';
                cfWorkerDefaultDomainEl.classList.add('readonly-field');
                cfWorkerDefaultDomainEl.readOnly = true;
                if (!cfWorkerDefaultDomainEl.value) {
                    cfWorkerDefaultDomainEl.setAttribute('placeholder', '尚未同步');
                }
            }

            const cfWorkerPrefixRulesEl = document.getElementById('settingsCfWorkerPrefixRules');
            if (cfWorkerPrefixRulesEl) {
                const cfPrefixRules = data.settings.cf_worker_prefix_rules || {};
                cfWorkerPrefixRulesEl.value = Object.keys(cfPrefixRules).length ? JSON.stringify(cfPrefixRules, null, 2) : '';
            }

            const externalApiKeyEl = document.getElementById('settingsExternalApiKey');
            if (externalApiKeyEl) {
                const maskedValue = data.settings.external_api_key_masked || '';
                externalApiKeyEl.value = maskedValue;
                externalApiKeyEl.dataset.maskedValue = maskedValue;
                externalApiKeyEl.dataset.isSet = data.settings.external_api_key_set ? 'true' : 'false';
            }

            const externalHintEl = document.getElementById('externalApiKeyHint');
            if (externalHintEl) {
                if (data.settings.external_api_key_set) {
                    externalHintEl.textContent = translateAppTextLocal(`已设置：${data.settings.external_api_key_masked || ''}`);
                } else {
                    externalHintEl.textContent = '未设置（设置后可通过 /api/external/* 对外开放接口读取邮件与验证码）';
                }
            }

            setExternalApiKeysEditor(data.settings.external_api_keys || []);

            // P1：公网安全配置
            const publicModeEl = document.getElementById('externalApiPublicMode');
            if (publicModeEl) publicModeEl.checked = data.settings.external_api_public_mode === true;

            const ipWhitelistEl = document.getElementById('externalApiIpWhitelist');
            if (ipWhitelistEl) {
                const wl = data.settings.external_api_ip_whitelist;
                ipWhitelistEl.value = Array.isArray(wl) ? wl.join('\n') : '';
            }

            const rateLimitEl = document.getElementById('externalApiRateLimit');
            if (rateLimitEl) rateLimitEl.value = data.settings.external_api_rate_limit_per_minute || 60;

            const disableRawEl = document.getElementById('externalApiDisableRaw');
            if (disableRawEl) disableRawEl.checked = data.settings.external_api_disable_raw_content === true;

            const disableWaitEl = document.getElementById('externalApiDisableWait');
            if (disableWaitEl) disableWaitEl.checked = data.settings.external_api_disable_wait_message === true;

            const poolExternalEnabledEl = document.getElementById('poolExternalEnabled');
            if (poolExternalEnabledEl) poolExternalEnabledEl.checked = data.settings.pool_external_enabled === true;

            const disablePoolClaimRandomEl = document.getElementById('externalApiDisablePoolClaimRandom');
            if (disablePoolClaimRandomEl) disablePoolClaimRandomEl.checked = data.settings.external_api_disable_pool_claim_random === true;

            const disablePoolClaimReleaseEl = document.getElementById('externalApiDisablePoolClaimRelease');
            if (disablePoolClaimReleaseEl) disablePoolClaimReleaseEl.checked = data.settings.external_api_disable_pool_claim_release === true;

            const disablePoolClaimCompleteEl = document.getElementById('externalApiDisablePoolClaimComplete');
            if (disablePoolClaimCompleteEl) disablePoolClaimCompleteEl.checked = data.settings.external_api_disable_pool_claim_complete === true;

            const disablePoolStatsEl = document.getElementById('externalApiDisablePoolStats');
            if (disablePoolStatsEl) disablePoolStatsEl.checked = data.settings.external_api_disable_pool_stats === true;

            // 加载刷新配置
            document.getElementById('refreshIntervalDays').value = data.settings.refresh_interval_days || '30';
            document.getElementById('refreshDelaySeconds').value = data.settings.refresh_delay_seconds || '5';
            document.getElementById('refreshCron').value = data.settings.refresh_cron || '0 2 * * *';

            // 设置定时刷新开关
            const enableScheduled = data.settings.enable_scheduled_refresh !== 'false';
            document.getElementById('enableScheduledRefresh').checked = enableScheduled;

            // 设置刷新策略单选框
            const useCron = data.settings.use_cron_schedule === 'true';
            document.querySelector('input[name="refreshStrategy"][value="' + (useCron ? 'cron' : 'days') + '"]').checked = true;
            toggleRefreshStrategy();

            // 加载全局代理设置
            const globalProxyEnabledEl = document.getElementById('settingsGlobalProxyEnabled');
            const globalProxyUrlEl = document.getElementById('settingsGlobalProxyUrl');
            const globalProxyTestResultEl = document.getElementById('globalProxyTestResult');
            if (globalProxyEnabledEl) globalProxyEnabledEl.checked = data.settings.global_proxy_enabled === true;
            if (globalProxyUrlEl) globalProxyUrlEl.value = (data.settings && data.settings.global_proxy_url) || '';
            if (globalProxyTestResultEl) globalProxyTestResultEl.textContent = '';
            window.__globalProxyState = {
                enabled: data.settings.global_proxy_enabled === true,
                maskedUrl: (data.settings && data.settings.global_proxy_url_masked) || ''
            };
            if (typeof settingsDirtyTabs !== 'undefined' && settingsDirtyTabs && typeof settingsDirtyTabs.clear === 'function') {
                settingsDirtyTabs.clear();
            }

            // 加载轮询设置（后端返回 boolean，兼容处理）
            // [Phase 3 兼容] 任一开关开启，设置面板复选框就显示为勾选状态
            const enablePolling = isAutoPollingEnabledSetting(data.settings.enable_auto_polling)
                || isAutoPollingEnabledSetting(data.settings.enable_compact_auto_poll);
            document.getElementById('enableAutoPolling').checked = enablePolling;
            document.getElementById('pollingInterval').value = String(parseIntegerSetting(data.settings.polling_interval, 10));
            document.getElementById('pollingCount').value = String(parseIntegerSetting(data.settings.polling_count, 5));

            // [Phase 3] 简洁模式独立面板已合并，使用统一引擎配置
            applyPollingSettings(data.settings);

            // 加载 Telegram 推送设置
            const tgToken = document.getElementById('telegramBotToken');
            const tgChat = document.getElementById('telegramChatId');
            const tgPoll = document.getElementById('telegramPollInterval');
            const tgProxy = document.getElementById('telegramProxyUrl');
            const emailEnabled = document.getElementById('emailNotificationEnabled');
            const emailRecipient = document.getElementById('emailNotificationRecipient');
            const webhookEnabledEl = document.getElementById('webhookNotificationEnabled');
            const webhookUrlEl = document.getElementById('webhookNotificationUrl');
            const webhookTokenEl = document.getElementById('webhookNotificationToken');
            if (tgToken) tgToken.value = data.telegram_bot_token || '';
            if (tgChat) tgChat.value = data.telegram_chat_id || '';
            if (tgPoll) tgPoll.value = String(parseIntegerSetting(data.telegram_poll_interval, 600));
            if (tgProxy) tgProxy.value = (data.settings && data.settings.telegram_proxy_url) || '';
            if (emailEnabled) emailEnabled.checked = !!data.settings.email_notification_enabled;
            if (emailRecipient) emailRecipient.value = data.settings.email_notification_recipient || '';
            if (webhookEnabledEl) webhookEnabledEl.checked = data.settings.webhook_notification_enabled === true;
            if (webhookUrlEl) webhookUrlEl.value = (data.settings && data.settings.webhook_notification_url) || '';
            if (webhookTokenEl) {
                const webhookMasked = (data.settings && data.settings.webhook_notification_token) || '';
                webhookTokenEl.value = webhookMasked;
                webhookTokenEl.dataset.maskedValue = webhookMasked;
                webhookTokenEl.dataset.isSet = webhookMasked ? 'true' : 'false';
            }

            // 加载 Watchtower 一键更新设置
            const wtUrl = document.getElementById('watchtowerUrl');
            const wtToken = document.getElementById('watchtowerToken');
            if (wtUrl) wtUrl.value = (data.settings && data.settings.watchtower_url) || '';
            if (wtToken) wtToken.value = (data.settings && data.settings.watchtower_token) || '';

            // 加载更新方式设置
            const updateMethod = (data.settings && data.settings.update_method) || 'watchtower';
            const updateMethodRadios = document.getElementsByName('updateMethod');
            updateMethodRadios.forEach(radio => {
                radio.checked = (radio.value === updateMethod);
            });

            // 触发更新方式切换逻辑（index.html 内联脚本绑定了 change 事件）
            // 注意：直接设置 radio.checked 不会触发 change，需手动派发事件以更新显隐。
            try {
                const selectedUpdateMethodRadio = document.querySelector('input[name="updateMethod"]:checked');
                if (selectedUpdateMethodRadio) {
                    selectedUpdateMethodRadio.dispatchEvent(new Event('change'));
                }
            } catch (e) {
                // 静默失败
            }

            // 加载部署信息警告（用于一键更新的部署提示）
            loadDeploymentInfo({ silent: true });
        }
    } catch (error) {
        console.error('loadSettings error:', error);
        showToast(translateAppTextLocal('加载设置失败'), 'error');
    }
}

// ==================== 部署信息检测（用于一键更新提示） ====================

// 缓存最近一次部署信息，用于语言切换时重渲染
let lastDeploymentInfo = null;

function pickDeploymentWarningText(warning, keyZh, keyEn) {
    if (!warning || typeof warning !== 'object') return '';
    const zh = String(warning[keyZh] || '').trim();
    const en = String(warning[keyEn] || '').trim();
    return getUiLanguage() === 'en' ? (en || zh) : (zh || en);
}

function normalizeDeploymentWarningSeverity(severityRaw) {
    const normalized = String(severityRaw || 'info').trim().toLowerCase();
    if (normalized === 'error' || normalized === 'warning' || normalized === 'info') return normalized;
    // 兼容后端可能返回的其它值
    return 'info';
}

function buildDeploymentWarningStyle(severity) {
    // 统一用 CSS 变量，兼容浅色/深色主题
    if (severity === 'error') {
        return {
            color: 'var(--clr-danger)',
            background: 'rgba(192,57,43,0.08)',
            icon: '⛔'
        };
    }
    if (severity === 'warning') {
        return {
            color: 'var(--clr-warn)',
            background: 'rgba(230,126,34,0.08)',
            icon: '⚠️'
        };
    }
    return {
        color: 'var(--clr-accent)',
        background: 'rgba(200,150,62,0.08)',
        icon: 'ℹ️'
    };
}

function renderDeploymentWarnings(deployment) {
    const container = document.getElementById('deploymentWarnings');
    if (!container) return;

    const warnings = Array.isArray(deployment && deployment.warnings) ? deployment.warnings : [];
    if (warnings.length === 0) {
        container.innerHTML = '';
        return;
    }

    const html = warnings.map((warning) => {
        const severity = normalizeDeploymentWarningSeverity(warning && warning.severity);
        const style = buildDeploymentWarningStyle(severity);

        const title = pickDeploymentWarningText(warning, 'message', 'message_en');
        const suggestion = pickDeploymentWarningText(warning, 'suggestion', 'suggestion_en');

        const suggestionHtml = suggestion
            ? `<div style="margin-top:6px;font-size:0.78rem;color:var(--text-muted);">
                    <strong>${escapeHtml(translateAppTextLocal('处理建议'))}：</strong>${escapeHtml(suggestion)}
               </div>`
            : '';

        return `
            <div class="form-hint" style="background:${style.background}; padding: 12px; border-radius: 6px; border-left: 3px solid ${style.color}; margin-bottom: 10px;">
                <div style="display:flex; gap: 10px; align-items:flex-start;">
                    <div style="font-size: 1rem; line-height: 1.2;">${style.icon}</div>
                    <div style="flex: 1;">
                        <div style="font-weight: 600; color: var(--text);">${escapeHtml(title)}</div>
                        ${suggestionHtml}
                    </div>
                </div>
            </div>
        `;
    }).join('');

    container.innerHTML = html;
}

async function loadDeploymentInfo({ silent = true } = {}) {
    const container = document.getElementById('deploymentWarnings');
    if (!container) return;

    try {
        const res = await fetch('/api/system/deployment-info', { cache: 'no-store' });
        if (!res.ok) return;
        const data = await res.json();
        if (!data || !data.success || !data.deployment) {
            if (!silent) {
                handleApiError(data || { success: false, error: '请求失败' }, '请求失败');
            }
            return;
        }

        lastDeploymentInfo = data.deployment;
        renderDeploymentWarnings(lastDeploymentInfo);

        // 根据后端推荐的更新方式自动选择 radio
        const recommended = data.deployment.recommended_method;
        if (recommended) {
            const radios = document.getElementsByName('updateMethod');
            radios.forEach(radio => {
                if (radio.value === recommended) {
                    radio.checked = true;
                    radio.dispatchEvent(new Event('change'));
                }
            });
        }
    } catch (e) {
        if (!silent) {
            showToast(`${translateAppTextLocal('请求失败')}: ${e.message}`, 'error');
        }
    }
}

// 切换刷新策略
function toggleRefreshStrategy() {
    const strategy = document.querySelector('input[name="refreshStrategy"]:checked').value;
    document.getElementById('daysStrategyContainer').style.display = strategy === 'days' ? 'block' : 'none';
    document.getElementById('cronStrategyContainer').style.display = strategy === 'cron' ? 'block' : 'none';
}

// 选择 Cron 样例
async function selectCronExample(cronExpr) {
    document.getElementById('refreshCron').value = cronExpr;
    await validateCronExpression();
}

// 验证 Cron 表达式
async function validateCronExpression() {
    const cronExpr = document.getElementById('refreshCron').value.trim();
    const resultEl = document.getElementById('cronValidationResult');

    if (!cronExpr) {
        resultEl.innerHTML = '';
        return;
    }

    try {
        const response = await fetch('/api/settings/validate-cron', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ cron_expression: cronExpr })
        });

        const data = await response.json();

        if (data.success && data.valid) {
            const nextRun = formatUiDateTime(data.next_run, { fallback: data.next_run, includeSeconds: false });
            resultEl.innerHTML = `
                <div style="color: #28a745;">
                    ✓ ${translateAppTextLocal('表达式有效')}<br>
                    ${translateAppTextLocal('下次执行:')} ${nextRun}
                </div>
            `;
        } else {
            resultEl.innerHTML = `
                <div style="color: #dc3545;">
                    ✗ ${window.resolveApiErrorMessage ? window.resolveApiErrorMessage(data.error || data, '表达式无效', 'Invalid expression') : (data.error && data.error.message ? data.error.message : (data.error || '表达式无效'))}
                </div>
            `;
        }
    } catch (error) {
        resultEl.innerHTML = `
            <div style="color: #dc3545;">
                ✗ ${translateAppTextLocal('验证失败:')} ${error.message}
            </div>
        `;
    }
}

const DEFAULT_TEMP_MAIL_PREFIX_RULES = {
    min_length: 1,
    max_length: 32,
    pattern: '^[a-z0-9][a-z0-9._-]*$'
};

function _readMaskedSecretInput(elId) {
    const el = document.getElementById(elId);
    if (!el) return { el: null, value: '', shouldSend: false, hasValue: false };
    const value = el.value.trim();
    const masked = el.dataset.maskedValue || '';
    const isSet = el.dataset.isSet === 'true';
    const isUnchangedMasked = isSet && Boolean(value) && value === masked;
    return {
        el,
        value,
        shouldSend: !isUnchangedMasked,
        hasValue: Boolean(value) || isUnchangedMasked
    };
}

function _collectBasicSettings(settings, strict) {
    const passwordEl = document.getElementById('settingsPassword');
    const password = passwordEl ? passwordEl.value : '';
    if (password) {
        settings.login_password = password;
    }

    const aiEnabledEl = document.getElementById('settingsVerificationAiEnabled');
    const aiBaseUrlEl = document.getElementById('settingsVerificationAiBaseUrl');
    const aiModelEl = document.getElementById('settingsVerificationAiModel');
    const aiEnabled = aiEnabledEl ? aiEnabledEl.checked : false;
    const aiBaseUrl = aiBaseUrlEl ? aiBaseUrlEl.value.trim() : '';
    const aiModel = aiModelEl ? aiModelEl.value.trim() : '';
    const aiKey = _readMaskedSecretInput('settingsVerificationAiApiKey');

    settings.verification_ai_enabled = aiEnabled;
    settings.verification_ai_base_url = aiBaseUrl;
    settings.verification_ai_model = aiModel;
    if (aiKey.shouldSend) {
        settings.verification_ai_api_key = aiKey.value;
    }

    if (strict && aiEnabled) {
        if (!aiBaseUrl) {
            showToast('请填写 AI Base URL', 'error');
            return false;
        }
        if (!aiModel) {
            showToast('请填写 AI 模型 ID', 'error');
            return false;
        }
        if (!aiKey.hasValue) {
            showToast('请填写 AI API Key', 'error');
            return false;
        }
    }

    const globalProxyEnabledEl = document.getElementById('settingsGlobalProxyEnabled');
    const globalProxyUrlEl = document.getElementById('settingsGlobalProxyUrl');
    const globalProxyEnabled = globalProxyEnabledEl ? globalProxyEnabledEl.checked : false;
    const globalProxyUrl = globalProxyUrlEl ? globalProxyUrlEl.value.trim() : '';
    if (strict && globalProxyEnabled && !globalProxyUrl) {
        showToast(translateAppTextLocal('开启全局代理前请先填写全局代理地址'), 'error');
        return false;
    }
    settings.global_proxy_enabled = globalProxyEnabled;
    settings.global_proxy_url = globalProxyUrl;
    return true;
}

function _collectTempMailSettings(settings, strict) {
    const providerRadio = document.querySelector('input[name="tempMailProvider"]:checked');
    const provider = providerRadio ? (providerRadio.value.trim() || 'legacy_bridge') : 'legacy_bridge';
    settings.temp_mail_provider = provider;

    const includeLegacy = strict || provider === 'legacy_bridge';
    const includeCf = strict || provider === 'cloudflare_temp_mail';

    if (includeLegacy) {
        const baseUrlEl = document.getElementById('settingsTempMailApiBaseUrl');
        const defaultDomainEl = document.getElementById('settingsTempMailDefaultDomain');
        const domainsEl = document.getElementById('settingsTempMailDomains');
        const prefixRulesEl = document.getElementById('settingsTempMailPrefixRules');
        if (baseUrlEl) settings.temp_mail_api_base_url = baseUrlEl.value.trim();
        else if (strict) settings.temp_mail_api_base_url = '';
        if (defaultDomainEl) settings.temp_mail_default_domain = defaultDomainEl.value.trim();
        else if (strict) settings.temp_mail_default_domain = '';

        const apiKey = _readMaskedSecretInput('settingsTempMailApiKey');
        if (apiKey.el && apiKey.shouldSend) {
            settings.temp_mail_api_key = apiKey.value;
        }

        if (domainsEl) {
            const rawDomains = domainsEl.value.trim();
            if (rawDomains) {
                try {
                    settings.temp_mail_domains = JSON.parse(rawDomains);
                } catch (_) {
                    if (strict) {
                        showToast(translateAppTextLocal('临时邮箱域名配置必须是合法 JSON'), 'error');
                        return false;
                    }
                }
            } else if (strict) {
                settings.temp_mail_domains = [];
            }
        }

        if (prefixRulesEl) {
            const rawPrefixRules = prefixRulesEl.value.trim();
            if (rawPrefixRules) {
                try {
                    settings.temp_mail_prefix_rules = JSON.parse(rawPrefixRules);
                } catch (_) {
                    if (strict) {
                        showToast(translateAppTextLocal('临时邮箱前缀规则必须是合法 JSON'), 'error');
                        return false;
                    }
                }
            } else if (strict) {
                settings.temp_mail_prefix_rules = { ...DEFAULT_TEMP_MAIL_PREFIX_RULES };
            }
        }
    }

    if (includeCf) {
        const cfBaseUrlEl = document.getElementById('settingsCfWorkerBaseUrl');
        if (cfBaseUrlEl) settings.cf_worker_base_url = cfBaseUrlEl.value.trim();
        const cfKey = _readMaskedSecretInput('settingsCfWorkerAdminKey');
        if (cfKey.el && cfKey.shouldSend) {
            settings.cf_worker_admin_key = cfKey.value;
        }
        const cfPrefixRulesEl = document.getElementById('settingsCfWorkerPrefixRules');
        if (cfPrefixRulesEl) {
            const rawCfPrefixRules = cfPrefixRulesEl.value.trim();
            if (rawCfPrefixRules) {
                try {
                    settings.cf_worker_prefix_rules = JSON.parse(rawCfPrefixRules);
                } catch (_) {
                    if (strict) {
                        showToast(translateAppTextLocal('CF Worker 前缀规则必须是合法 JSON'), 'error');
                        return false;
                    }
                }
            } else if (strict) {
                settings.cf_worker_prefix_rules = { ...DEFAULT_TEMP_MAIL_PREFIX_RULES };
            }
        }
    }
    return true;
}

function _collectApiSecuritySettings(settings, strict) {
    const extKey = _readMaskedSecretInput('settingsExternalApiKey');
    if (extKey.el && extKey.shouldSend) {
        settings.external_api_key = extKey.value;
    }

    const keysJsonEl = document.getElementById('settingsExternalApiKeysJson');
    if (keysJsonEl) {
        const rawKeys = keysJsonEl.value.trim();
        const originalCanonical = keysJsonEl.dataset.originalCanonical || '[]';
        if (rawKeys) {
            let parsed;
            try {
                parsed = JSON.parse(rawKeys);
            } catch (_) {
                if (strict) {
                    showToast(translateAppTextLocal('多 Key 配置必须是合法 JSON'), 'error');
                    return false;
                }
                parsed = null;
            }
            if (parsed !== null) {
                if (!Array.isArray(parsed)) {
                    if (strict) {
                        showToast(translateAppTextLocal('多 Key 配置必须是 JSON 数组'), 'error');
                        return false;
                    }
                } else if (strict) {
                    let normalized;
                    try {
                        normalized = buildExternalApiKeysEditorItems(parsed);
                    } catch (error) {
                        showToast(error.message || '多 Key 配置格式无效', 'error');
                        return false;
                    }
                    if (JSON.stringify(normalized) !== originalCanonical) {
                        settings.external_api_keys = normalized;
                    }
                } else {
                    settings.external_api_keys = parsed;
                }
            }
        } else if (!strict || originalCanonical !== '[]') {
            settings.external_api_keys = [];
        }
    }

    const publicModeEl = document.getElementById('externalApiPublicMode');
    if (publicModeEl) settings.external_api_public_mode = publicModeEl.checked;
    const disableRawEl = document.getElementById('externalApiDisableRaw');
    if (disableRawEl) settings.external_api_disable_raw_content = disableRawEl.checked;
    const disableWaitEl = document.getElementById('externalApiDisableWait');
    if (disableWaitEl) settings.external_api_disable_wait_message = disableWaitEl.checked;
    const poolExternalEnabledEl = document.getElementById('poolExternalEnabled');
    if (poolExternalEnabledEl) settings.pool_external_enabled = poolExternalEnabledEl.checked;
    const disablePoolClaimRandomEl = document.getElementById('externalApiDisablePoolClaimRandom');
    if (disablePoolClaimRandomEl) settings.external_api_disable_pool_claim_random = disablePoolClaimRandomEl.checked;
    const disablePoolClaimReleaseEl = document.getElementById('externalApiDisablePoolClaimRelease');
    if (disablePoolClaimReleaseEl) settings.external_api_disable_pool_claim_release = disablePoolClaimReleaseEl.checked;
    const disablePoolClaimCompleteEl = document.getElementById('externalApiDisablePoolClaimComplete');
    if (disablePoolClaimCompleteEl) settings.external_api_disable_pool_claim_complete = disablePoolClaimCompleteEl.checked;
    const disablePoolStatsEl = document.getElementById('externalApiDisablePoolStats');
    if (disablePoolStatsEl) settings.external_api_disable_pool_stats = disablePoolStatsEl.checked;

    const ipWhitelistEl = document.getElementById('externalApiIpWhitelist');
    if (ipWhitelistEl) {
        settings.external_api_ip_whitelist = ipWhitelistEl.value.trim().split('\n').map(l => l.trim()).filter(Boolean);
    }

    const rateLimitEl = document.getElementById('externalApiRateLimit');
    if (rateLimitEl) {
        const rl = parseInt(rateLimitEl.value, 10);
        if (!isNaN(rl)) settings.external_api_rate_limit_per_minute = rl;
    }
    return true;
}

function _collectAutomationSettings(settings, strict) {
    const strategy = document.querySelector('input[name="refreshStrategy"]:checked')?.value;
    const enableScheduledEl = document.getElementById('enableScheduledRefresh');
    if (enableScheduledEl) settings.enable_scheduled_refresh = enableScheduledEl.checked;
    if (strategy) settings.use_cron_schedule = strategy === 'cron';

    const days = parseInt(document.getElementById('refreshIntervalDays')?.value, 10);
    const delay = parseInt(document.getElementById('refreshDelaySeconds')?.value, 10);
    if (isNaN(days) || days < 1 || days > 90) {
        if (strict) {
            showToast(translateAppTextLocal('刷新周期必须在 1-90 天之间'), 'error');
            return false;
        }
    } else {
        settings.refresh_interval_days = days;
    }

    if (isNaN(delay) || delay < 0 || delay > 60) {
        if (strict) {
            showToast(translateAppTextLocal('刷新间隔必须在 0-60 秒之间'), 'error');
            return false;
        }
    } else {
        settings.refresh_delay_seconds = delay;
    }

    const refreshCron = document.getElementById('refreshCron')?.value?.trim() || '';
    if (strategy === 'cron') {
        if (!refreshCron) {
            if (strict) {
                showToast(translateAppTextLocal('请输入 Cron 表达式'), 'error');
                return false;
            }
        } else {
            settings.refresh_cron = refreshCron;
        }
    }

    // 轮询配置（[Phase 3] 简洁模式独立配置已合并，镜像标准字段值）
    const enablePollingEl = document.getElementById('enableAutoPolling');
    const pInterval = parseInt(document.getElementById('pollingInterval')?.value, 10);
    const pCount = parseInt(document.getElementById('pollingCount')?.value, 10);
    if (enablePollingEl) {
        settings.enable_auto_polling = enablePollingEl.checked;
        settings.enable_compact_auto_poll = enablePollingEl.checked;
    }
    if (isNaN(pInterval) || pInterval < 3 || pInterval > 300) {
        if (strict) {
            showToast(translateAppTextLocal('轮询间隔必须在 3-300 秒之间'), 'error');
            return false;
        }
    } else {
        settings.polling_interval = pInterval;
        settings.compact_poll_interval = pInterval;
    }
    if (isNaN(pCount) || pCount < 0 || pCount > 100) {
        if (strict) {
            showToast(translateAppTextLocal('轮询次数必须在 0-100 次之间（0 表示持续轮询）'), 'error');
            return false;
        }
    } else {
        settings.polling_count = pCount;
        settings.compact_poll_max_count = pCount;
    }

    const emailNotifEnabledEl = document.getElementById('emailNotificationEnabled');
    if (emailNotifEnabledEl) settings.email_notification_enabled = emailNotifEnabledEl.checked;
    const emailRecipientEl = document.getElementById('emailNotificationRecipient');
    if (emailRecipientEl) settings.email_notification_recipient = emailRecipientEl.value.trim();

    // Telegram 推送配置
    const tgToken = document.getElementById('telegramBotToken')?.value?.trim() || '';
    const tgChatIdEl = document.getElementById('telegramChatId');
    const tgPoll = parseInt(document.getElementById('telegramPollInterval')?.value, 10);
    const tgProxyEl = document.getElementById('telegramProxyUrl');
    if (tgToken) settings.telegram_bot_token = tgToken;
    if (tgChatIdEl) settings.telegram_chat_id = tgChatIdEl.value.trim();
    if (!isNaN(tgPoll)) {
        if (tgPoll < 10 || tgPoll > 86400) {
            if (strict) {
                showToast(translateAppTextLocal('Telegram 轮询间隔必须在 10-86400 秒之间'), 'error');
                return false;
            }
        } else {
            settings.telegram_poll_interval = tgPoll;
        }
    }
    if (tgProxyEl) settings.telegram_proxy_url = tgProxyEl.value.trim();

    // Webhook 通知配置
    const webhookEnabledEl = document.getElementById('webhookNotificationEnabled');
    const webhookUrlEl = document.getElementById('webhookNotificationUrl');
    const webhookEnabled = webhookEnabledEl ? webhookEnabledEl.checked : false;
    const webhookUrl = webhookUrlEl ? webhookUrlEl.value.trim() : '';
    if (strict && webhookEnabled && !webhookUrl) {
        showToast(translateAppTextLocal('启用 Webhook 通知时必须填写 Webhook URL'), 'error');
        return false;
    }
    if (strict && webhookUrl && !(webhookUrl.startsWith('http://') || webhookUrl.startsWith('https://'))) {
        showToast(translateAppTextLocal('Webhook URL 必须以 http:// 或 https:// 开头'), 'error');
        return false;
    }
    if (webhookEnabledEl) settings.webhook_notification_enabled = webhookEnabled;
    if (webhookUrlEl) settings.webhook_notification_url = webhookUrl;
    const webhookToken = _readMaskedSecretInput('webhookNotificationToken');
    if (webhookToken.el && webhookToken.shouldSend) {
        settings.webhook_notification_token = webhookToken.value;
    }

    // Watchtower / 更新方式配置
    const wtUrlEl = document.getElementById('watchtowerUrl');
    const wtToken = document.getElementById('watchtowerToken')?.value?.trim() || '';
    if (wtUrlEl) settings.watchtower_url = wtUrlEl.value.trim();
    if (wtToken) settings.watchtower_token = wtToken;
    const updateMethodRadio = document.querySelector('input[name="updateMethod"]:checked');
    if (updateMethodRadio) settings.update_method = updateMethodRadio.value;
    return true;
}

function collectSettingsPayload(scope = 'all', { strict = true } = {}) {
    const settings = {};
    const scopes = scope === 'all' ? ['basic', 'temp-mail', 'api-security', 'automation'] : [scope];
    const collectors = {
        basic: _collectBasicSettings,
        'temp-mail': _collectTempMailSettings,
        'api-security': _collectApiSecuritySettings,
        automation: _collectAutomationSettings
    };
    for (const s of scopes) {
        const fn = collectors[s];
        if (fn && fn(settings, strict) === false) {
            return null;
        }
    }
    return settings;
}

// 保存设置
async function saveSettings() {
    const settings = collectSettingsPayload('all', { strict: true });
    if (!settings) return;

    try {
        const response = await fetch('/api/settings', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(settings)
        });

        const data = await response.json();

        if (data.success) {
            applyPollingSettings(settings, { restart: true });
            const globalProxyUrl = settings.global_proxy_url || '';
            window.__globalProxyState = {
                enabled: Boolean(settings.global_proxy_enabled),
                maskedUrl: globalProxyUrl ? globalProxyUrl.replace(/(\/\/)([^/\s@]+)@/, '$1***@') : ''
            };
            if (typeof settingsDirtyTabs !== 'undefined' && settingsDirtyTabs && typeof settingsDirtyTabs.clear === 'function') {
                settingsDirtyTabs.clear();
            }
            document.querySelectorAll('#page-settings .settings-tab.save-error').forEach(btn => {
                btn.classList.remove('save-error');
                const dot = btn.querySelector('.tab-save-dot');
                if (dot) dot.remove();
            });
            showToast(pickApiMessage(data, '设置已保存', 'Settings saved successfully'), 'success');
            if (currentSettingsTab === 'temp-mail') {
                setTempMailSettingsDirty(false);
            }
        } else {
            handleApiError(data, '保存设置失败');
        }
    } catch (error) {
        showToast(translateAppTextLocal('保存设置失败'), 'error');
    }
}

async function runProxyConnectivityTest(proxyUrl, btnEl, resultEl, defaultBtnLabel) {
    if (!proxyUrl) {
        if (resultEl) {
            resultEl.textContent = `❌ ${translateAppTextLocal('请先输入代理地址')}`;
            resultEl.style.color = 'var(--danger, red)';
        }
        return;
    }
    if (btnEl) {
        btnEl.disabled = true;
        btnEl.textContent = translateAppTextLocal('⏳ 测试中…');
    }
    if (resultEl) resultEl.textContent = '';
    try {
        const resp = await fetch('/api/settings/test-proxy', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ proxy_url: proxyUrl })
        });
        const data = await resp.json();
        if (data.ok) {
            const latencyText = typeof data.latency_ms === 'number' ? ` (${data.latency_ms}ms)` : '';
            if (resultEl) {
                resultEl.textContent = `✅ ${translateAppTextLocal('连通成功')}${latencyText}`;
                resultEl.style.color = 'var(--success, green)';
            }
        } else {
            if (resultEl) {
                resultEl.textContent = `❌ ${data.message || translateAppTextLocal('连接失败')}`;
                resultEl.style.color = 'var(--danger, red)';
            }
        }
    } catch (e) {
        if (resultEl) {
            resultEl.textContent = `❌ ${e.message}`;
            resultEl.style.color = 'var(--danger, red)';
        }
    } finally {
        if (btnEl) {
            btnEl.disabled = false;
            btnEl.textContent = translateAppTextLocal(defaultBtnLabel || '🔗 测试连通性');
        }
    }
}

async function testGlobalProxy() {
    const btn = document.getElementById('btnTestGlobalProxy');
    const resultEl = document.getElementById('globalProxyTestResult');
    const proxyInput = document.getElementById('settingsGlobalProxyUrl');
    const proxyUrl = proxyInput ? proxyInput.value.trim() : '';
    await runProxyConnectivityTest(proxyUrl, btn, resultEl, '🔗 测试连通性');
}

async function testTelegramPush() {
    const btn = document.getElementById('btnTestTelegram');
    if (btn) { btn.disabled = true; btn.textContent = translateAppTextLocal('⏳ 发送中…'); }
    try {
        const resp = await fetch('/api/settings/telegram-test', { method: 'POST', headers: { 'Content-Type': 'application/json' } });
        const data = await resp.json();
        if (data.success) {
            showToast(pickApiMessage(data, '测试消息已发送，请检查 Telegram', 'Test message sent successfully. Please check Telegram'), 'success');
        } else {
            handleApiError(data, '发送失败');
        }
    } catch (e) {
        showToast(`${translateAppTextLocal('请求失败')}: ${e.message}`, 'error');
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = translateAppTextLocal('📨 发送测试消息'); }
    }
}

async function testTelegramProxy() {
    const btn = document.getElementById('btnTestTelegramProxy');
    const resultEl = document.getElementById('telegramProxyTestResult');
    const proxyInput = document.getElementById('telegramProxyUrl');
    const proxyUrl = proxyInput ? proxyInput.value.trim() : '';
    if (btn) { btn.disabled = true; btn.textContent = translateAppTextLocal('⏳ 测试中…'); }
    if (resultEl) resultEl.textContent = '';
    try {
        const resp = await fetch('/api/settings/test-telegram-proxy', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ proxy_url: proxyUrl })
        });
        const data = await resp.json();
        if (data.ok) {
            const latencyText = typeof data.latency_ms === 'number' ? ` (${data.latency_ms}ms)` : '';
            if (resultEl) {
                resultEl.textContent = `✅ ${data.message || '连通'}${latencyText}`;
                resultEl.style.color = 'var(--success, green)';
            }
        } else {
            if (resultEl) { resultEl.textContent = `❌ ${data.message || '失败'}`; resultEl.style.color = 'var(--danger, red)'; }
        }
    } catch (e) {
        if (resultEl) { resultEl.textContent = `❌ ${e.message}`; resultEl.style.color = 'var(--danger, red)'; }
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = translateAppTextLocal('🔗 测试连通性'); }
    }
}

async function testWatchtower() {
    const btn = document.getElementById('btnTestWatchtower');
    const resultEl = document.getElementById('watchtowerTestResult');
    const urlInput = document.getElementById('watchtowerUrl');
    const tokenInput = document.getElementById('watchtowerToken');
    const wtUrl = urlInput ? urlInput.value.trim() : '';
    const wtToken = tokenInput ? tokenInput.value.trim() : '';
    if (btn) { btn.disabled = true; btn.textContent = translateAppTextLocal('⏳ 测试中…'); }
    if (resultEl) resultEl.textContent = '';
    try {
        const body = {};
        if (wtUrl) body.url = wtUrl;
        if (wtToken && !wtToken.startsWith('****')) body.token = wtToken;
        const resp = await fetch('/api/system/test-watchtower', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCSRFToken()
            },
            body: JSON.stringify(body)
        });
        const data = await resp.json();
        if (data.success) {
            if (resultEl) { resultEl.textContent = translateAppTextLocal('✅ 连通正常'); resultEl.style.color = 'var(--success, green)'; }
        } else {
            if (resultEl) { resultEl.textContent = `❌ ${data.message || translateAppTextLocal('失败')}`; resultEl.style.color = 'var(--danger, red)'; }
        }
    } catch (e) {
        if (resultEl) { resultEl.textContent = `❌ ${e.message}`; resultEl.style.color = 'var(--danger, red)'; }
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = translateAppTextLocal('🔗 测试连通性'); }
    }
}

async function testEmailNotification() {
    const btn = document.getElementById('btnTestEmailNotification');
    if (btn) { btn.disabled = true; btn.textContent = translateAppTextLocal('⏳ 发送中…'); }
    try {
        const resp = await fetch('/api/settings/email-test', { method: 'POST', headers: { 'Content-Type': 'application/json' } });
        const data = await resp.json();
        if (data.success) {
            showToast(pickApiMessage(data, '测试邮件已提交，请检查收件箱', 'Test email accepted. Please check your inbox'), 'success');
        } else {
            handleApiError(data, '测试邮件发送失败');
        }
    } catch (e) {
        showToast(`${translateAppTextLocal('请求失败')}: ${e.message}`, 'error');
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = translateAppTextLocal('📨 发送测试邮件'); }
    }
}

async function testWebhookNotification() {
    const btn = document.getElementById('btnTestWebhookNotification');
    if (btn) { btn.disabled = true; btn.textContent = translateAppTextLocal('⏳ 发送中…'); }
    try {
        const resp = await fetch('/api/settings/webhook-test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });
        const data = await resp.json();
        if (data.success) {
            showToast(pickApiMessage(data, 'Webhook 测试成功', 'Webhook test succeeded'), 'success');
        } else {
            handleApiError(data, 'Webhook 测试失败');
        }
    } catch (e) {
        showToast(`${translateAppTextLocal('请求失败')}: ${e.message}`, 'error');
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = translateAppTextLocal('测试 Webhook'); }
    }
}

function generateExternalApiKey() {
    const input = document.getElementById('settingsExternalApiKey');
    if (!input) return;

    const currentValue = input.value.trim();
    if (currentValue) {
        const confirmed = confirm(translateAppTextLocal('当前已存在 API Key，是否覆盖？'));
        if (!confirmed) return;
    }

    const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';
    const bytes = new Uint8Array(64);
    window.crypto.getRandomValues(bytes);
    const key = Array.from(bytes, b => alphabet[b % alphabet.length]).join('');

    input.value = key;
    showToast(translateAppTextLocal('已生成新的 API Key（尚未保存）'), 'success');
}

async function copyExternalApiKey() {
    const input = document.getElementById('settingsExternalApiKey');
    if (!input) return;

    const value = input.value || '';
    const maskedValue = input.dataset.maskedValue || '';
    const isSet = input.dataset.isSet === 'true';
    let copyValue = value.trim();

    if (isSet && copyValue && maskedValue && copyValue === maskedValue) {
        try {
            const resp = await fetch('/api/settings/external-api-key/plaintext');
            const data = await resp.json();
            if (!resp.ok || !data.success || !data.api_key) {
                throw new Error((data && (data.message || data.error?.message)) || '获取真实 API Key 失败');
            }
            copyValue = String(data.api_key || '').trim();
        } catch (error) {
            showToast(`${translateAppTextLocal('请求失败')}: ${error.message}`, 'error');
            return;
        }
    }

    if (!copyValue) {
        showToast(translateAppTextLocal('当前没有可复制的 API Key'), 'warning');
        return;
    }

    try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(copyValue);
        } else {
            const tempInput = document.createElement('textarea');
            tempInput.value = copyValue;
            tempInput.setAttribute('readonly', 'readonly');
            tempInput.style.position = 'fixed';
            tempInput.style.opacity = '0';
            tempInput.style.pointerEvents = 'none';
            document.body.appendChild(tempInput);
            tempInput.focus();
            tempInput.select();
            const ok = document.execCommand('copy');
            document.body.removeChild(tempInput);
            if (!ok) {
                throw new Error('execCommand_copy_failed');
            }
        }
        showToast(translateAppTextLocal('内容已复制到剪贴板'), 'success');
    } catch (error) {
        showToast(translateAppTextLocal('复制失败，请手动复制'), 'error');
    }
}

async function testVerificationAiConfig() {
    const btn = document.getElementById('btnTestVerificationAi');
    const resultEl = document.getElementById('verificationAiTestResult');
    if (btn) { btn.disabled = true; btn.textContent = translateAppTextLocal('⏳ 测试中…'); }
    if (resultEl) {
        resultEl.textContent = '正在验证已保存的 AI 配置连通性...';
        resultEl.style.color = 'var(--text-secondary, #666)';
    }

    try {
        const resp = await fetch('/api/settings/verification-ai-test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });
        const data = await resp.json();

        if (!data.success) {
            handleApiError(data, 'AI 配置测试失败');
            if (resultEl) {
                resultEl.textContent = '❌ AI 配置测试失败';
                resultEl.style.color = 'var(--danger, red)';
            }
            return;
        }

        const probe = data.probe || {};
        if (data.ok) {
            const parsed = probe.parsed_output || {};
            const code = parsed.verification_code || '-';
            const confidence = parsed.confidence || '-';
            const latency = probe.latency_ms || 0;
            const connectivityOnly = data.connectivity_ok && !data.contract_ok;
            if (resultEl) {
                if (connectivityOnly) {
                    resultEl.textContent = `✅ 连通正常（${latency}ms，HTTP ${probe.http_status || 200}）；契约校验未通过：${probe.error || '-'}`;
                    resultEl.style.color = 'var(--warning, #ff8c00)';
                } else {
                    resultEl.textContent = `✅ 可用（${latency}ms，code=${code}，confidence=${confidence}）`;
                    resultEl.style.color = 'var(--success, green)';
                }
            }
            showToast(connectivityOnly ? 'AI 连通性测试成功' : 'AI 配置测试成功', 'success');
            return;
        }

        const message = probe.message || 'AI 配置测试失败';
        const detail = probe.error ? `（${probe.error}）` : '';
        if (resultEl) {
            resultEl.textContent = `❌ ${message}${detail}`;
            resultEl.style.color = 'var(--danger, red)';
        }
        showToast(message, 'warning');
    } catch (e) {
        const msg = `${translateAppTextLocal('请求失败')}: ${e.message}`;
        if (resultEl) {
            resultEl.textContent = `❌ ${msg}`;
            resultEl.style.color = 'var(--danger, red)';
        }
        showToast(msg, 'error');
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = translateAppTextLocal('🤖 测试 AI 配置'); }
    }
}

async function syncCfWorkerDomains() {
    const btn = document.getElementById('btnSyncCfWorkerDomains');
    const hintEl = document.getElementById('cfWorkerSyncTime');
    if (btn) { btn.disabled = true; btn.textContent = translateAppTextLocal('⏳ 同步中…'); }
    try {
        const resp = await fetch('/api/settings/cf-worker-sync-domains', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        const data = await resp.json();
        if (data.success) {
            // v0.3: 同步成功后更新 CF Worker 独立域名只读字段（不覆盖 GPTMail 的 temp_mail_* 字段）
            updateCfWorkerReadonlyFields(data);
            const msg = data.message || `已同步 ${(data.domains || []).length} 个域名`;
            showToast(msg, 'success');
            if (hintEl) {
                const versionInfo = data.version ? ` (${data.version})` : '';
                const titleInfo = data.title ? `「${data.title}」` : '';
                hintEl.textContent = `✅ 同步成功 ${titleInfo}${versionInfo}：${(data.domains || []).join(', ')}  — 上次同步：${new Date().toLocaleString()}`;
            }
        } else {
            const errMsg = (data.error && data.error.message) || '同步失败，请检查 CF Worker 地址配置';
            handleApiError(data, errMsg);
            if (hintEl) { hintEl.textContent = `❌ ${errMsg}`; }
        }
    } catch (e) {
        showToast(`${translateAppTextLocal('请求失败')}: ${e.message}`, 'error');
        if (hintEl) { hintEl.textContent = `❌ 请求失败: ${e.message}`; }
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = translateAppTextLocal('☁ 从 CF Worker 同步域名'); }
    }
}

// ==================== v0.3: 设置页面 Tab 重构 ====================

// 当前激活的 Tab（默认 basic）
let currentSettingsTab = 'basic';

function setTempMailSettingsDirty(isDirty) {
    const hint = document.getElementById('tempMailSettingsDirtyHint');
    if (hint) hint.style.display = isDirty ? 'block' : 'none';
}

function initTempMailSettingsDirtyTracking() {
    const fieldIds = [
        'settingsTempMailApiBaseUrl',
        'settingsTempMailApiKey',
        'settingsTempMailDomains',
        'settingsTempMailDefaultDomain',
        'settingsTempMailPrefixRules',
        'settingsCfWorkerBaseUrl',
        'settingsCfWorkerAdminKey',
        'settingsCfWorkerPrefixRules',
    ];
    fieldIds.forEach(id => {
        const field = document.getElementById(id);
        if (!field) return;
        field.addEventListener('input', () => setTempMailSettingsDirty(true));
        field.addEventListener('change', () => setTempMailSettingsDirty(true));
    });
    const settingsPage = document.getElementById('page-settings');
    if (settingsPage && !settingsPage.dataset.dirtyDelegated) {
        settingsPage.dataset.dirtyDelegated = 'true';
        const markTabDirty = (event) => {
            const pane = event.target?.closest?.('.settings-tab-pane');
            if (!pane || !pane.id.startsWith('settings-tab-')) return;
            const tabId = pane.id.replace('settings-tab-', '');
            settingsDirtyTabs.add(tabId);
            if (tabId === 'temp-mail') {
                setTempMailSettingsDirty(true);
            }
        };
        settingsPage.addEventListener('input', markTabDirty);
        settingsPage.addEventListener('change', markTabDirty);
    }
}

const settingsDirtyTabs = new Set();

// Tab 切换函数（严格限定在 #page-settings 内，避免误伤仪表盘概览页签）
function switchSettingsTab(tabName) {
    const prevTab = currentSettingsTab;
    if (prevTab === tabName) return; // 同一 Tab 无操作
    currentSettingsTab = tabName;

    // 1. 基础 Tab 切走时，密码框有内容则清空 + Toast 提示
    if (prevTab === 'basic') {
        const pwdEl = document.getElementById('settingsPassword');
        if (pwdEl && pwdEl.value.trim()) {
            pwdEl.value = '';
            showToast('密码修改未保存，如需修改请在「基础」Tab 重新输入后点击保存', 'warning');
        }
    }

    // 2. 立即更新 Tab 按钮视觉状态（限定在 #page-settings）
    document.querySelectorAll('#page-settings .settings-tab').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tabName);
    });

    // 3. 立即更新 Tab 内容区显隐（限定在 #page-settings）
    document.querySelectorAll('#page-settings .settings-tab-pane').forEach(pane => {
        pane.classList.toggle('active', pane.id === `settings-tab-${tabName}`);
    });

    // 4. 仅在有实际修改时后台异步触发自动保存（基础 Tab 除外）
    if (prevTab !== 'basic' && settingsDirtyTabs.has(prevTab)) {
        autoSaveSettings(prevTab);
    }
}

// 自动保存逻辑（密码除外，复用统一字段收集器）
async function autoSaveSettings(tabName) {
    if (tabName === 'basic') return;

    const settings = collectSettingsPayload(tabName, { strict: false });
    if (!settings || Object.keys(settings).length === 0) return;

    // 显示保存中圆点（限定在 #page-settings）
    const prevTabBtn = document.querySelector(`#page-settings .settings-tab[data-tab="${tabName}"]`);
    let dotEl = null;
    if (prevTabBtn) {
        prevTabBtn.classList.remove('save-error');
        const existingDot = prevTabBtn.querySelector('.tab-save-dot');
        if (existingDot) existingDot.remove();
        dotEl = document.createElement('span');
        dotEl.className = 'tab-save-dot';
        prevTabBtn.appendChild(dotEl);
        prevTabBtn.classList.add('saving');
    }

    try {
        const resp = await fetch('/api/settings', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(settings)
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok || data.success === false) throw new Error(data.error?.message || `HTTP ${resp.status}`);
        settingsDirtyTabs.delete(tabName);
        if (tabName === 'temp-mail') {
            setTempMailSettingsDirty(false);
        } else if (tabName === 'automation') {
            applyPollingSettings(settings, { restart: true });
        }
        // 保存成功：移除圆点
        if (prevTabBtn) {
            prevTabBtn.classList.remove('saving');
            if (dotEl) dotEl.remove();
        }
    } catch (e) {
        // 保存失败：圆点变红保留 + 持久 Toast
        if (prevTabBtn) {
            prevTabBtn.classList.remove('saving');
            prevTabBtn.classList.add('save-error');
        }
        showToast(`保存失败，[${tabName}] Tab 的修改尚未保存，请手动重试`, 'error', null, true);
    }
}

// Provider 切换面板显隐
function onTempMailProviderChange(provider) {
    const gptmailPanel = document.getElementById('gptmailConfigPanel');
    const cfWorkerPanel = document.getElementById('cfWorkerConfigPanel');
    const pluginPanel = document.getElementById('pluginProviderConfigPanel');
    const pluginManager = typeof window !== 'undefined' && window.PluginManager ? window.PluginManager : null;

    if (provider === 'legacy_bridge') {
        if (gptmailPanel) gptmailPanel.style.display = 'block';
        if (cfWorkerPanel) cfWorkerPanel.style.display = 'none';
        if (pluginManager && typeof pluginManager.hideProviderConfig === 'function') {
            pluginManager.hideProviderConfig();
        } else if (pluginPanel) {
            pluginPanel.style.display = 'none';
        }
    } else if (provider === 'cloudflare_temp_mail') {
        if (gptmailPanel) gptmailPanel.style.display = 'none';
        if (cfWorkerPanel) cfWorkerPanel.style.display = 'block';
        if (pluginManager && typeof pluginManager.hideProviderConfig === 'function') {
            pluginManager.hideProviderConfig();
        } else if (pluginPanel) {
            pluginPanel.style.display = 'none';
        }
    } else {
        if (gptmailPanel) gptmailPanel.style.display = 'none';
        if (cfWorkerPanel) cfWorkerPanel.style.display = 'none';
        if (pluginPanel) pluginPanel.style.display = 'block';
        if (pluginManager && typeof pluginManager.showProviderConfig === 'function') {
            pluginManager.showProviderConfig(provider);
        }
    }
}

// 同步成功后更新 CF Worker 只读字段
function updateCfWorkerReadonlyFields(data) {
    const domainsEl = document.getElementById('settingsCfWorkerDomains');
    const defaultDomainEl = document.getElementById('settingsCfWorkerDefaultDomain');
    const syncTimeEl = document.getElementById('cfWorkerSyncTime');

    if (domainsEl && data.domains) {
        domainsEl.value = JSON.stringify(
            data.domains.map(d => ({ name: d, enabled: true })),
            null, 2
        );
        domainsEl.classList.add('readonly-field');
        domainsEl.readOnly = true;
    }

    if (defaultDomainEl && data.default_domain) {
        defaultDomainEl.value = data.default_domain;
        defaultDomainEl.classList.add('readonly-field');
        defaultDomainEl.readOnly = true;
    }

    if (syncTimeEl) {
        syncTimeEl.textContent = `上次同步：${new Date().toLocaleString()}`;
        syncTimeEl.style.display = 'block';
    }
}

// ==================== 自动轮询功能 ====================

// 初始化轮询设置
async function initPollingSettings() {
    try {
        // 优先使用 bootstrap 已缓存的轮询设置，避免首页阶段重复请求 /api/settings
        const cached = window.__bootstrapPollingSettings;
        if (cached) {
            applyPollingSettings(cached);
            delete window.__bootstrapPollingSettings;
            return;
        }
        // 降级：如果 bootstrap 未执行或失败，回退到 /api/settings
        const response = await fetch('/api/settings');
        const data = await response.json();

        if (data.success) {
            applyPollingSettings(data.settings);
        }
    } catch (error) {
        console.error('初始化轮询设置失败:', error);
    }
}

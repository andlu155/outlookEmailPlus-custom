// ==================== CF 临时邮箱精简双栏工作台 ====================

let tempMailboxes = [];
let activeTempMailbox = null;
let tempMessages = [];

async function loadTempEmailsWorkbench() {
    await Promise.all([loadCfTempDomains(), loadTempMailboxList()]);
}

async function loadCfTempDomains() {
    const select = document.getElementById('tempEmailDomainSelect');
    if (!select) return;
    try {
        const res = await fetch('/api/temp-emails/options?provider=cloudflare_temp_mail');
        const data = await res.json();
        const domains = (data.options && data.options.domains) || data.domains || [];
        const names = domains.map(d => (typeof d === 'string' ? d : d.name || '')).filter(Boolean);
        select.innerHTML = '<option value="">自动分配域名</option>' +
            names.map(n => `<option value="${escapeHtml(n)}">@${escapeHtml(n)}</option>`).join('');
    } catch (_) {}
}

async function loadTempMailboxList() {
    const container = document.getElementById('tempEmailContainer');
    const badge = document.getElementById('tempEmailCountBadge');
    try {
        const res = await fetch('/api/temp-emails');
        const data = await res.json();
        tempMailboxes = data.temp_emails || data.emails || [];
        if (badge) badge.textContent = String(tempMailboxes.length);

        if (!tempMailboxes.length) {
            container.innerHTML = `<div class="empty-state">
                <div class="empty-state-icon">⚡</div>
                <div class="empty-state-title">暂无 CF 临时邮箱</div>
                <div class="empty-state-sub">在设置中配置 CF Worker 后即可一键创建</div>
            </div>`;
            return;
        }

        container.innerHTML = tempMailboxes.map(item => {
            const addr = item.email || '';
            const active = activeTempMailbox === addr;
            return `<div class="account-item ${active ? 'active' : ''}" onclick="selectTempMailbox('${escapeHtml(addr)}')">
                <div class="account-item-main">
                    <div class="account-item-top">
                        <span class="status-dot imap"></span>
                        <span class="account-email-text" title="${escapeHtml(addr)}">${escapeHtml(addr)}</span>
                    </div>
                    <div class="account-item-meta">
                        <span>${escapeHtml(formatDateTime(item.created_at))}</span>
                        <div class="account-item-actions" onclick="event.stopPropagation()">
                            <button type="button" class="btn-icon-mini" onclick="copyToClipboard('${escapeHtml(addr)}', '临时邮箱')" data-tip="复制临时邮箱地址">📋</button>
                            <button type="button" class="btn-icon-mini" onclick="deleteTempMailbox('${escapeHtml(addr)}')" data-tip="删除此临时邮箱">🗑</button>
                        </div>
                    </div>
                </div>
            </div>`;
        }).join('');
    } catch (_) {
        container.innerHTML = '<div class="empty-state"><div class="empty-state-title">加载临时邮箱失败</div></div>';
    }
}

async function generateTempEmail() {
    const btn = document.getElementById('btnCreateTempEmail');
    const prefix = (document.getElementById('tempEmailPrefixInput')?.value || '').trim();
    const domain = (document.getElementById('tempEmailDomainSelect')?.value || '').trim();
    btn.disabled = true;
    try {
        const payload = { provider: 'cloudflare_temp_mail' };
        if (prefix) payload.prefix = prefix;
        if (domain) payload.domain = domain;
        const res = await fetch('/api/temp-emails/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.success) {
            const email = data.email || (data.temp_email && data.temp_email.email) || '';
            document.getElementById('tempEmailPrefixInput').value = '';
            showToast(`已创建临时邮箱：${email}`, 'success');
            if (email) copyToClipboard(email, '新临时邮箱');
            await loadTempMailboxList();
            if (email) selectTempMailbox(email);
        } else {
            handleApiError(data, '创建 CF 临时邮箱失败，请检查设置中的 Worker 配置');
        }
    } catch (_) {
        showToast('创建临时邮箱失败', 'error');
    } finally {
        btn.disabled = false;
    }
}

async function selectTempMailbox(emailAddr) {
    activeTempMailbox = emailAddr;
    document.getElementById('tempEmailCurrentName').textContent = emailAddr;
    document.getElementById('tempEmailRefreshBtn').style.display = 'inline-flex';
    closeTempEmailDetail();
    await loadTempMailboxList();
    await loadTempMessages(emailAddr);
}

function copyTempEmailCurrent() {
    if (activeTempMailbox) copyToClipboard(activeTempMailbox, '临时邮箱');
}

async function refreshCurrentTempMailbox() {
    if (!activeTempMailbox) return;
    const btn = document.getElementById('tempEmailRefreshBtn');
    btn.disabled = true;
    try {
        await fetch(`/api/temp-emails/${encodeURIComponent(activeTempMailbox)}/refresh`, { method: 'POST' });
        await loadTempMessages(activeTempMailbox);
    } finally {
        btn.disabled = false;
    }
}

async function loadTempMessages(emailAddr) {
    const pane = document.getElementById('tempEmailMessageList');
    pane.innerHTML = '<div class="empty-state"><span class="spinner"></span><span>加载邮件中…</span></div>';
    try {
        const res = await fetch(`/api/temp-emails/${encodeURIComponent(emailAddr)}/messages`);
        const data = await res.json();
        tempMessages = data.messages || data.emails || [];
        if (!tempMessages.length) {
            pane.innerHTML = '<div class="empty-state"><div class="empty-state-icon">📭</div><div class="empty-state-title">暂无邮件</div><div class="empty-state-sub">点击右上角「获取邮件」刷新</div></div>';
            return;
        }
        pane.innerHTML = tempMessages.map((m, idx) => {
            const code = quickExtractCodeFromText(`${m.subject || ''} ${m.content || m.body_preview || ''}`);
            return `<div class="email-card" data-tidx="${idx}" onclick="openTempMessageDetail(${idx})">
                <div class="email-card-head">
                    <div class="email-card-subject">${escapeHtml(m.subject || '(无主题)')}</div>
                    <span class="email-card-date">${escapeHtml(formatDateTime(m.created_at || m.timestamp || m.date))}</span>
                </div>
                <div class="email-card-meta"><span>发件人: ${escapeHtml(m.from_address || m.from || '未知')}</span></div>
                ${code ? `<div class="email-code-bar"><button type="button" class="code-chip" onclick="event.stopPropagation(); copyToClipboard('${escapeHtml(code)}', '验证码')">🔑 ${escapeHtml(code)} · 复制</button></div>` : ''}
            </div>`;
        }).join('');
    } catch (_) {
        pane.innerHTML = '<div class="empty-state"><div class="empty-state-title">获取临时邮件失败</div></div>';
    }
}

async function openTempMessageDetail(idx) {
    const item = tempMessages[idx];
    if (!item || !activeTempMailbox) return;
    document.getElementById('tempResultsSplit').classList.remove('no-detail');
    document.getElementById('tempEmailDetailPane').style.display = 'flex';
    document.getElementById('tempEmailDetailMeta').innerHTML = `<div style="font-weight:700;font-size:15px;">${escapeHtml(item.subject || '(无主题)')}</div>
        <div style="font-size:12.5px;color:var(--text-secondary);margin-top:4px;">发件人：${escapeHtml(item.from_address || item.from || '未知')}</div>`;
    const bodyEl = document.getElementById('tempEmailDetailBody');
    bodyEl.innerHTML = '<div class="empty-state"><span class="spinner"></span></div>';
    try {
        const res = await fetch(`/api/temp-emails/${encodeURIComponent(activeTempMailbox)}/messages/${encodeURIComponent(item.id)}`);
        const data = await res.json();
        const msg = data.message || data.email || item;
        const html = msg.html_content || msg.body_html || '';
        const text = msg.content || msg.body_text || msg.body || '';
        if (html && window.DOMPurify) {
            bodyEl.innerHTML = window.DOMPurify.sanitize(html, { FORBID_TAGS: ['script', 'style', 'iframe', 'object', 'embed'] });
        } else {
            bodyEl.innerHTML = `<pre style="white-space:pre-wrap;font-family:inherit;margin:0;">${escapeHtml(text)}</pre>`;
        }
    } catch (_) {
        bodyEl.innerHTML = '<div class="error-message-box">加载邮件详情失败</div>';
    }
}

function closeTempEmailDetail() {
    document.getElementById('tempResultsSplit').classList.add('no-detail');
    document.getElementById('tempEmailDetailPane').style.display = 'none';
}

async function extractTempVerification() {
    if (!activeTempMailbox) return;
    try {
        const res = await fetch(`/api/temp-emails/${encodeURIComponent(activeTempMailbox)}/extract-verification`);
        const data = await res.json();
        const info = data.data || data;
        const code = info.verification_code || info.code || '';
        const link = info.verification_link || info.link || '';
        if (code) await copyToClipboard(code, `验证码 ${code}`);
        else if (link) await copyToClipboard(link, '验证链接');
        else showToast('未识别到验证码或验证链接', 'info');
    } catch (_) {
        showToast('提取验证码失败', 'error');
    }
}

async function deleteTempMailbox(emailAddr) {
    if (!confirm(`确认删除临时邮箱 ${emailAddr}？`)) return;
    try {
        const res = await fetch(`/api/temp-emails/${encodeURIComponent(emailAddr)}`, { method: 'DELETE' });
        const data = await res.json();
        if (data.success) {
            if (activeTempMailbox === emailAddr) {
                activeTempMailbox = null;
                document.getElementById('tempEmailCurrentName').textContent = '选择一个临时邮箱';
                document.getElementById('tempEmailRefreshBtn').style.display = 'none';
                closeTempEmailDetail();
            }
            showToast('临时邮箱已删除', 'success');
            await loadTempMailboxList();
        } else {
            handleApiError(data, '删除失败');
        }
    } catch (_) {
        showToast('删除失败', 'error');
    }
}

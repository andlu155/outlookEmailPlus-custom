let __overviewBound = false;
const __overviewState = {
    activeTab: 'summary',
    cache: {},
    loading: {}
};

function ovT(text) {
    if (text === null || text === undefined || text === '') return '';
    if (typeof translateAppTextLocal === 'function') return translateAppTextLocal(text);
    if (window.translateAppText) return window.translateAppText(text);
    return String(text);
}

function ovLocale() {
    return (window.getCurrentUiLanguage && window.getCurrentUiLanguage() === 'en') ? 'en-US' : 'zh-CN';
}

function ovLabelValue(label, value) {
    return `${ovT(label)} ${value}`;
}

function initOverview() {
    const page = document.getElementById('page-dashboard');
    if (!page) return;
    syncOverviewStaticText();

    if (!__overviewBound) {
        document.querySelectorAll('.ov-tab').forEach((button) => {
            button.addEventListener('click', () => switchOverviewTab(button.dataset.tab || 'summary'));
        });

        const refreshBtn = document.getElementById('ov-refresh-btn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', refreshOverview);
        }

        window.addEventListener('ui-language-changed', () => {
            syncOverviewStaticText();
            updateOverviewRefreshTime();
            if (__overviewState.cache[__overviewState.activeTab]) {
                renderOverviewTab(__overviewState.activeTab, __overviewState.cache[__overviewState.activeTab]);
            }
        });

        window.addEventListener('overview-data-changed', (event) => {
            const detail = event && event.detail ? event.detail : {};
            invalidateOverviewCache(detail.tabs);

            const pageIsActive = !page.classList.contains('page-hidden');
            if (pageIsActive) {
                loadOverviewTab(__overviewState.activeTab || 'summary', true);
            }
        });
        __overviewBound = true;
    }

    const activeTab = __overviewState.activeTab || 'summary';
    __overviewState.activeTab = activeTab;
    document.querySelectorAll('.ov-tab').forEach((button) => {
        button.classList.toggle('active', button.dataset.tab === activeTab);
    });
    document.querySelectorAll('.ov-tab-pane').forEach((pane) => {
        pane.classList.toggle('active', pane.dataset.tab === activeTab);
    });
    loadOverviewTab(activeTab, true);
    updateOverviewRefreshTime();
}

function switchOverviewTab(tabId) {
    const targetTab = tabId || 'summary';
    __overviewState.activeTab = targetTab;

    document.querySelectorAll('.ov-tab').forEach((button) => {
        button.classList.toggle('active', button.dataset.tab === targetTab);
    });
    document.querySelectorAll('.ov-tab-pane').forEach((pane) => {
        pane.classList.toggle('active', pane.dataset.tab === targetTab);
    });

    if (__overviewState.cache[targetTab]) {
        renderOverviewTab(targetTab, __overviewState.cache[targetTab]);
        return;
    }
    loadOverviewTab(targetTab);
}

function refreshOverview() {
    invalidateOverviewCache();
    loadOverviewTab(__overviewState.activeTab || 'summary', true);
    updateOverviewRefreshTime();
}

function invalidateOverviewCache(tabIds) {
    const targets = Array.isArray(tabIds) && tabIds.length
        ? tabIds.map((item) => String(item || '').trim()).filter(Boolean)
        : Object.keys(__overviewState.cache);

    if (!targets.length) {
        __overviewState.cache = {};
        return;
    }

    targets.forEach((tabId) => {
        delete __overviewState.cache[tabId];
    });
}

async function loadOverviewTab(tabId, forceReload = false) {
    if (__overviewState.loading[tabId]) return;
    if (!forceReload && __overviewState.cache[tabId]) {
        renderOverviewTab(tabId, __overviewState.cache[tabId]);
        return;
    }

    const endpointMap = {
        summary: '/api/overview/summary',
        verification: '/api/overview/verification',
        'external-api': '/api/overview/external-api',
        pool: '/api/overview/pool',
        activity: '/api/overview/activity'
    };
    const endpoint = endpointMap[tabId];
    if (!endpoint) return;

    __overviewState.loading[tabId] = true;
    renderOverviewLoading(tabId);
    try {
        const response = await fetch(endpoint);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        const data = await response.json();
        __overviewState.cache[tabId] = data || {};
        renderOverviewTab(tabId, data || {});
        updateOverviewRefreshTime();
    } catch (error) {
        renderOverviewError(tabId, error);
    } finally {
        __overviewState.loading[tabId] = false;
    }
}

function renderOverviewTab(tabId, data) {
    const renderers = {
        summary: renderOverviewSummary,
        verification: renderVerificationStats,
        'external-api': renderExternalApiStats,
        pool: renderPoolStats,
        activity: renderActivityStats
    };
    const renderer = renderers[tabId];
    if (renderer) renderer(data || {});
}

function renderOverviewLoading(tabId) {
    const container = getOverviewContainer(tabId);
    if (!container) return;
    container.innerHTML = `<div class="ov-empty">${esc(ovT('加载中…'))}</div>`;
}

function renderOverviewError(tabId) {
    const container = getOverviewContainer(tabId);
    if (!container) return;
    container.innerHTML = `<div class="ov-empty">${esc(ovT('加载失败'))}</div>`;
}

function syncOverviewStaticText() {
    const textMap = {
        'ov-page-eyebrow': '玻璃态概览面板',
        'ov-page-badge': '细腻卡片视图',
        'ov-page-subtitle': '账号、验证码、对外 API、邮箱池与系统活动统一看板',
        'ov-refresh-label': '最近刷新：'
    };
    Object.keys(textMap).forEach((id) => {
        const el = document.getElementById(id);
        if (el) {
            el.textContent = ovT(textMap[id]);
        }
    });

    const titleEl = document.getElementById('ov-page-title');
    if (titleEl) {
        titleEl.textContent = `📊 ${ovT('数据概览')}`;
    }

    const refreshBtn = document.getElementById('ov-refresh-btn');
    if (refreshBtn) {
        refreshBtn.textContent = `⟳ ${ovT('刷新')}`;
    }

    const tabLabels = {
        summary: '总览',
        verification: '验证码提取',
        'external-api': '对外 API',
        pool: '邮箱池',
        activity: '系统活动'
    };
    document.querySelectorAll('.ov-tab').forEach((button) => {
        const labelEl = button.querySelector('.ov-tab-label');
        const tabId = button.dataset.tab || '';
        if (labelEl && tabLabels[tabId]) {
            labelEl.textContent = ovT(tabLabels[tabId]);
        }
    });
}

function getOverviewContainer(tabId) {
    return document.getElementById(`ov-${tabId}-body`);
}

function renderOverviewSummary(data) {
    const container = getOverviewContainer('summary');
    if (!container) return;

    const accountStatus = data.account_status || {};
    const pool = data.pool_snapshot || {};
    const refresh = data.refresh_health || {};
    const kpi = data.kpi || {};

    container.innerHTML = `
        <div class="kpi-row">
            ${renderKpiCard('总账号数', formatNumber(accountStatus.total || 0), ovLabelValue('活跃', formatNumber(accountStatus.active || 0)), 'kpi-primary', '快速观察账号池总体规模，以及当前真正处于活跃状态的账号占比。')}
            ${renderKpiCard('邮箱池可用', formatNumber(pool.available || 0), ovLabelValue('占用', formatNumber(pool.in_use || 0)), 'kpi-success', '这张卡片更适合盯实时供给，避免申领高峰时可用量突然见底。')}
            ${renderKpiCard('今日验证码提取', formatNumber(kpi.verification_extracted || 0), ovLabelValue('临时邮箱', formatNumber(kpi.temp_emails_active || 0)), 'kpi-accent', '用来快速判断今天验证链路的真实活跃度，以及临时邮箱侧是否同步跟上。')}
            ${renderKpiCard('最近刷新成功率', formatPercent(refresh.success_rate_7d || 0), ovLabelValue('失败', formatNumber(refresh.last_fail_count || 0)), 'kpi-warn', '当这张卡片连续下滑时，优先检查刷新任务、凭据有效性和网络稳定性。')}
        </div>
        <div class="two-col">
            ${renderDataCard({
                title: '账号状态分布',
                icon: '◔',
                badge: '实时',
                hoverNote: '重点看待刷新与异常是否持续抬头，避免问题在账号层面积压。',
                body: renderProgressBlock([
                    { label: '活跃', value: accountStatus.active || 0, total: accountStatus.total || 0, tone: 'jade' },
                    { label: '过期', value: accountStatus.expired || 0, total: accountStatus.total || 0, tone: 'danger' },
                    { label: '待刷新', value: accountStatus.pending_refresh || 0, total: accountStatus.total || 0, tone: 'warn' },
                    { label: '异常', value: accountStatus.error || 0, total: accountStatus.total || 0, tone: 'primary' }
                ])
            })}
            ${renderDataCard({
                title: '邮箱池快照',
                icon: '◌',
                badge: '供给',
                hoverNote: '这张卡片更适合判断池子是否健康，尤其是可用、占用和冷却之间的结构平衡。',
                body: renderProgressBlock([
                    { label: '可用', value: pool.available || 0, total: pool.total || 0, tone: 'jade' },
                    { label: '占用中', value: pool.in_use || 0, total: pool.total || 0, tone: 'primary' },
                    { label: '冷却中', value: pool.cooldown || 0, total: pool.total || 0, tone: 'warn' },
                    { label: '已使用', value: pool.used || 0, total: pool.total || 0, tone: 'accent' }
                ])
            })}
            ${renderDataCard({
                title: '刷新健康',
                icon: '↻',
                badge: '任务',
                hoverNote: '当最近耗时和失败数一起抬升时，通常意味着刷新链路已经开始变脆。',
                body: `
                    <div class="ov-kv"><span>${esc(ovT('最近启动'))}</span><strong>${formatTime(refresh.last_run_at)}</strong></div>
                    <div class="ov-kv"><span>${esc(ovT('最近成功数'))}</span><strong>${formatNumber(refresh.last_success_count || 0)}</strong></div>
                    <div class="ov-kv"><span>${esc(ovT('最近失败数'))}</span><strong>${formatNumber(refresh.last_fail_count || 0)}</strong></div>
                    <div class="ov-kv"><span>${esc(ovT('最近耗时'))}</span><strong>${formatDurationSeconds(refresh.last_duration_s || 0)}</strong></div>
                `
            })}
            ${renderDataCard({
                title: '今日快捷数字',
                icon: '✦',
                badge: '当天',
                hoverNote: '这是面向今天的即时读数，适合和外部流量高峰一起对着看。',
                body: `
                    <div class="ov-kv"><span>${esc(ovT('今日收件'))}</span><strong>${formatNumber(kpi.emails_received || 0)}</strong></div>
                    <div class="ov-kv"><span>${esc(ovT('验证码提取'))}</span><strong>${formatNumber(kpi.verification_extracted || 0)}</strong></div>
                    <div class="ov-kv"><span>${esc(ovT('活跃临时邮箱'))}</span><strong>${formatNumber(kpi.temp_emails_active || 0)}</strong></div>
                `
            })}
        </div>
    `;
}

function renderVerificationStats(data) {
    const container = getOverviewContainer('verification');
    if (!container) return;

    const kpi = data.kpi || {};
    const channelStats = Array.isArray(data.channel_stats) ? data.channel_stats : [];
    const recent = Array.isArray(data.recent) ? data.recent : [];

    container.innerHTML = `
        <div class="kpi-row">
            ${renderKpiCard('近 7 天提取次数', formatNumber(kpi.total_count || 0), ovLabelValue('成功', formatNumber(kpi.success_count || 0)), 'kpi-primary', '用于感知验证码链路总吞吐，波动大时先对照外部调用和收件量一起看。')}
            ${renderKpiCard('总体成功率', formatPercent(kpi.success_rate || 0), ovLabelValue('失败', formatNumber(kpi.fail_count || 0)), 'kpi-success', '如果成功率掉得很快，优先排查渠道可达性、规则命中率和凭据状态。')}
            ${renderKpiCard('AI 兜底次数', formatNumber(kpi.ai_used_count || 0), ovLabelValue('AI 成功率', formatPercent(kpi.ai_success_rate || 0)), 'kpi-warn', '这里能看出规则提取是否变弱，AI 兜底是否开始扛主力。')}
            ${renderKpiCard('平均耗时', formatDurationMs(kpi.avg_duration_ms || 0), `P95 ${formatDurationMs(kpi.p95_duration_ms || 0)}`, 'kpi-accent', '平均值看整体体感，P95 更适合抓长尾卡顿。')}
        </div>
        <div class="two-col">
            ${renderDataCard({
                title: '各通道成功率',
                icon: '◎',
                badge: '效率',
                hoverNote: '通道之间的成功率差距越大，越说明路由策略或上游稳定性还可以继续细调。',
                body: renderProgressBlock(channelStats.map((item) => ({
                    label: formatChannelLabel(item.label || item.channel || 'unknown'),
                    value: item.success_count || 0,
                    total: item.count || 0,
                    tone: 'jade',
                    suffix: `${formatPercent(item.success_rate || 0)} · ${formatNumber(item.count || 0)} ${ovT('次')}`
                })))
            })}
            ${renderDataCard({
                title: '各通道平均耗时',
                icon: '◷',
                badge: '性能',
                hoverNote: '如果某个通道耗时抬头但成功率没掉，通常是链路变慢而不是直接失效。',
                body: renderProgressBlock(channelStats.map((item) => ({
                    label: formatChannelLabel(item.label || item.channel || 'unknown'),
                    value: item.avg_duration_ms || 0,
                    total: Math.max(...channelStats.map((row) => Number(row.avg_duration_ms || 0)), 1),
                    tone: 'accent',
                    suffix: formatDurationMs(item.avg_duration_ms || 0)
                })))
            })}
        </div>
        ${renderDataCard({
            title: '最近提取记录',
            icon: '⌁',
            badge: '明细',
            hoverNote: '适合快速确认最近异常是不是集中发生在特定账号、通道或结果类型上。',
            className: 'ov-mt',
            body: renderTable(
                ['时间', '账号', '通道', '结果', '耗时', '状态'],
                recent.map((item) => [
                    formatTime(item.started_at),
                    esc(item.account_email || '--'),
                    esc(formatChannelLabel(item.channel_label || item.channel || '--')),
                    esc(item.code_found || '--'),
                    formatDurationMs(item.duration_ms || 0),
                    renderResultBadge(item.result_type, item.error_code)
                ]),
                6
            )
        })}
    `;
}

function renderExternalApiStats(data) {
    const container = getOverviewContainer('external-api');
    if (!container) return;

    const kpi = data.kpi || {};
    const dailySeries = Array.isArray(data.daily_series) ? data.daily_series : [];
    const callerRank = Array.isArray(data.caller_rank) ? data.caller_rank : [];
    const byEndpoint = Array.isArray(data.by_endpoint) ? data.by_endpoint : [];

    container.innerHTML = `
        <div class="kpi-row">
            ${renderKpiCard('今日调用量', formatNumber(kpi.today_calls || 0), ovLabelValue('7 日', formatNumber(kpi.week_calls || 0)), 'kpi-primary', '用来衡量当天外部接口的瞬时热度，以及是否明显偏离近 7 天基线。')}
            ${renderKpiCard('调用波动', formatPercent(kpi.today_vs_yesterday_rate || 0), '对比昨日', 'kpi-accent', '正值表示放量，负值表示回落；很适合和业务投放节奏一起对照。')}
            ${renderKpiCard('7 日成功率', formatPercent(kpi.success_rate || 0), ovLabelValue('错误', formatNumber(kpi.error_count || 0)), 'kpi-success', '成功率与错误数结合看，比单看成功率更容易发现局部接口异常。')}
            ${renderKpiCard('活跃调用方', formatNumber(kpi.active_callers || 0), '近 7 日有调用', 'kpi-warn', '这个数越集中，越要警惕单一调用方对系统波峰的牵引。')}
        </div>
        <div class="two-col">
            ${renderDataCard({
                title: '7 日调用趋势',
                icon: '⌁',
                badge: '趋势',
                hoverNote: '悬浮每根柱子可以快速看单日调用量，适合找峰值和回落点。',
                body: `<div id="ov-external-chart"></div>`
            })}
            ${renderDataCard({
                title: '接口占比',
                icon: '◫',
                badge: '分布',
                hoverNote: '如果某个接口占比过高，通常说明业务入口开始单点集中。',
                body: renderProgressBlock(byEndpoint.map((item) => ({
                    label: item.endpoint || '--',
                    value: item.count || 0,
                    total: kpi.week_calls || 0,
                    tone: 'primary',
                    suffix: `${formatNumber(item.count || 0)} · ${formatPercent(item.rate || 0)}`
                })))
            })}
        </div>
            ${renderDataCard({
                title: '调用方排名',
                icon: '◉',
                badge: '排行',
                hoverNote: '用来抓最主要的流量来源，适合和接口占比一起判断负载结构。',
                className: 'ov-mt',
                body: renderTable(
                ['调用方', '今日', '7 日', '成功率', '最近调用'],
                callerRank.map((item) => [
                    esc(item.key_name || item.caller_id || '--'),
                    formatNumber(item.today_calls || 0),
                    formatNumber(item.week_calls || 0),
                    formatPercent(item.success_rate || 0),
                    esc(item.last_used_at || '--')
                ]),
                5
            )
        })}
    `;
    renderBarChart(document.getElementById('ov-external-chart'), dailySeries);
}

function renderPoolStats(data) {
    const container = getOverviewContainer('pool');
    if (!container) return;

    const kpi = data.kpi || {};
    const dist = data.operation_distribution || {};
    const recent = Array.isArray(data.recent_operations) ? data.recent_operations : [];
    const topProjects = Array.isArray(data.project_top5) ? data.project_top5 : [];

    container.innerHTML = `
        <div class="kpi-row">
            ${renderKpiCard('可用账号', formatNumber(kpi.available || 0), ovLabelValue('占用', formatNumber(kpi.in_use || 0)), 'kpi-primary', '先看可用与占用的对比，能快速判断池子是不是正被持续抽空。')}
            ${renderKpiCard('冷却中', formatNumber(kpi.cooldown || 0), ovLabelValue('已使用', formatNumber(kpi.used || 0)), 'kpi-warn', '冷却中高说明周转变慢，已使用高说明池子消耗速度偏快。')}
            ${renderKpiCard('近 7 天领取', formatNumber(kpi.claim_count_7d || 0), ovLabelValue('完成率', formatPercent(kpi.complete_success_rate || 0)), 'kpi-success', '领取量高但完成率低时，优先排查任务完成链路或外部使用质量。')}
            ${renderKpiCard('最长占用', formatDurationSeconds(kpi.max_claimed_duration_s || 0), '当前占用中', 'kpi-accent', '长时间不释放通常代表外部任务卡住，适合直接盯这张卡片。')}
        </div>
        <div class="two-col">
            ${renderDataCard({
                title: '操作分布',
                icon: '◑',
                badge: '池子',
                hoverNote: 'Claim、Complete、Release、Expire 的相对关系，比单看数量更能说明池子的运作状态。',
                body: renderProgressBlock([
                    { label: '领取', value: dist.claim || 0, total: totalValues(dist), tone: 'primary' },
                    { label: '完成', value: dist.complete || 0, total: totalValues(dist), tone: 'jade' },
                    { label: '释放', value: dist.release || 0, total: totalValues(dist), tone: 'accent' },
                    { label: '过期回收', value: dist.expire || 0, total: totalValues(dist), tone: 'danger' }
                ])
            })}
            ${renderDataCard({
                title: '项目 Top 5',
                icon: '◈',
                badge: '项目',
                hoverNote: '看哪些项目在高频使用池子，也能顺手判断复用率是否集中在少数项目。',
                body: renderTable(
                    ['项目', '账号数', '成功数', '复用率'],
                    topProjects.map((item) => [
                        esc(item.project_key || '--'),
                        formatNumber(item.account_count || 0),
                        formatNumber(item.success_count || 0),
                        formatPercent(item.reuse_rate || 0)
                    ]),
                    4
                )
            })}
        </div>
        ${renderDataCard({
            title: '最近邮箱池操作',
            icon: '⌘',
            badge: '流转',
            hoverNote: '这里适合快速肉眼确认最近的领取、释放和完成是否符合预期节奏。',
            className: 'ov-mt',
            body: renderTable(
                ['时间', '账号', '动作', '调用方', '项目', '结果'],
                recent.map((item) => [
                    esc(item.time || '--'),
                    esc(item.account_email || '--'),
                    esc(formatPoolActionLabel(item.action || '--')),
                    esc(item.caller_id || '--'),
                    esc(item.project_key || '--'),
                    esc(formatTimelineStatus(item.result || '--'))
                ]),
                6
            )
        })}
    `;
}

function renderActivityStats(data) {
    const container = getOverviewContainer('activity');
    if (!container) return;

    const kpi = data.kpi || {};
    const notificationStats = data.notification_stats || {};
    const timeline = Array.isArray(data.timeline) ? data.timeline : [];

    container.innerHTML = `
        <div class="kpi-row">
            ${renderKpiCard('24h 审计操作', formatNumber(kpi.audit_ops_24h || 0), '系统活动', 'kpi-primary', '这张卡适合感知系统活跃度是否突然放大，尤其是管理动作是否异常增加。')}
            ${renderKpiCard('24h 通知投递', formatNumber(kpi.notification_total_24h || 0), '全部通道', 'kpi-success', '当投递量高但通知健康不佳时，通常说明下游通道开始抖动。')}
            ${renderKpiCard('24h 提取事件', formatNumber(kpi.verification_events_24h || 0), '验证码链路', 'kpi-accent', '这里是验证码侧的活动热度卡，适合配合成功率一起看。')}
        </div>
        <div class="two-col">
            ${renderDataCard({
                title: '通知健康',
                icon: '✳',
                badge: '通道',
                hoverNote: '适合同时观察发送量和成功率，快速看出是不是某一类通知通道在拖后腿。',
                body: renderProgressBlock(Object.keys(notificationStats).map((channel) => ({
                    label: formatChannelLabel(channel),
                    value: notificationStats[channel].success_count || 0,
                    total: notificationStats[channel].count || 0,
                    tone: 'jade',
                    suffix: `${formatNumber(notificationStats[channel].count || 0)} · ${formatPercent(notificationStats[channel].success_rate || 0)}`
                })))
            })}
            ${renderDataCard({
                title: '最近系统活动',
                icon: '☰',
                badge: '时间线',
                hoverNote: '这里是全局近况流，适合快速判断系统刚刚发生了什么。',
                body: `<div id="ov-activity-timeline"></div>`
            })}
        </div>
    `;
    renderTimeline(document.getElementById('ov-activity-timeline'), timeline);
}

function renderKpiCard(label, value, note, tone, hoverNote = '') {
    return `
        <div class="kpi-card ${tone || ''} ov-hover-card">
            ${renderHoverNote(hoverNote)}
            <div class="kpi-head">
                <span class="kpi-icon">${esc(pickToneGlyph(tone))}</span>
                <div class="kpi-label">${esc(ovT(label))}</div>
            </div>
            <div class="kpi-value">${esc(value)}</div>
            <div class="kpi-note">${esc(ovT(note))}</div>
        </div>
    `;
}

function renderDataCard(options) {
    const config = options || {};
    return `
        <div class="data-card ov-hover-card ${esc(config.className || '')}">
            ${renderHoverNote(config.hoverNote)}
            <div class="data-card-header">
                <div class="ov-card-header-main">
                    <span class="ov-card-icon">${esc(config.icon || '◌')}</span>
                    <span class="ov-card-title">${esc(ovT(config.title || ''))}</span>
                </div>
                ${config.badge ? `<span class="ov-card-badge">${esc(ovT(config.badge))}</span>` : ''}
            </div>
            <div class="data-card-body">${config.body || ''}</div>
        </div>
    `;
}

function renderHoverNote(text) {
    if (!text) return '';
    return `<div class="ov-hover-note">${esc(ovT(text))}</div>`;
}

function renderProgressBlock(items) {
    const safeItems = Array.isArray(items) ? items.filter(Boolean) : [];
    if (!safeItems.length) {
        return `<div class="ov-empty">${esc(ovT('暂无数据'))}</div>`;
    }
    return safeItems.map((item) => {
        const total = Number(item.total || 0);
        const value = Number(item.value || 0);
        const percent = total > 0 ? Math.max(0, Math.min(100, (value / total) * 100)) : 0;
        const suffix = item.suffix || `${formatNumber(value)} / ${formatNumber(total)}`;
        return `
            <div class="prog-row">
                <div class="prog-label">
                    <span class="prog-name">${esc(ovT(item.label || '--'))}</span>
                    <span class="prog-val">${esc(suffix)}</span>
                </div>
                <div class="prog-track"><div class="prog-fill ${esc(item.tone || 'primary')}" style="width:${percent}%"></div></div>
            </div>
        `;
    }).join('');
}

function renderTable(headers, rows, colCount) {
    if (!rows || !rows.length) {
        return `<div class="ov-empty">${esc(ovT('暂无数据'))}</div>`;
    }
    return `
        <div class="data-table-shell">
            <table class="data-table">
                <thead><tr>${headers.map((header) => `<th>${esc(ovT(header))}</th>`).join('')}</tr></thead>
                <tbody>
                    ${rows.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join('')}</tr>`).join('')}
                </tbody>
            </table>
        </div>
    `;
}

function renderBarChart(container, data) {
    if (!container) return;
    const series = Array.isArray(data) ? data : [];
    if (!series.length) {
        container.innerHTML = `<div class="ov-empty">${esc(ovT('暂无数据'))}</div>`;
        return;
    }
    const maxValue = Math.max(...series.map((item) => Number(item.count || 0)), 1);
    container.innerHTML = `
        <div class="bar-chart">
            ${series.map((item) => {
                const count = Number(item.count || 0);
                const height = Math.max((count / maxValue) * 100, count > 0 ? 6 : 2);
                return `
                    <div class="bar-item">
                        <div class="bar-popover">${esc(item.date || '--')} · ${formatNumber(count)} ${esc(ovT('次'))}</div>
                        <div class="bar-col" style="height:${height}%"></div>
                        <div class="bar-value">${formatNumber(count)}</div>
                        <div class="bar-label">${esc((item.date || '').slice(5) || '--')}</div>
                    </div>
                `;
            }).join('')}
        </div>
    `;
}

function renderTimeline(container, events) {
    if (!container) return;
    const items = Array.isArray(events) ? events : [];
    if (!items.length) {
        container.innerHTML = `<div class="ov-empty">${esc(ovT('暂无数据'))}</div>`;
        return;
    }
    container.innerHTML = `
        <div class="timeline">
            ${items.map((item) => `
                <div class="tl-item">
                    <div class="tl-icon">${pickTimelineIcon(item.action)}</div>
                    <div class="tl-content">
                        <div class="tl-title">${esc(formatTimelineAction(item.action || '--'))}</div>
                        <div class="tl-meta">${esc(item.time || '--')} · ${esc(formatTimelineStatus(item.status || '--'))}</div>
                    </div>
                </div>
            `).join('')}
        </div>
    `;
}

function renderResultBadge(resultType, errorCode) {
    if (resultType === 'code' || resultType === 'link') {
        return `<span class="badge-pill badge-success">${esc(ovT('成功'))}</span>`;
    }
    return `<span class="badge-pill badge-danger">${esc(errorCode || ovT('失败'))}</span>`;
}

function formatNumber(value) {
    return Number(value || 0).toLocaleString(ovLocale());
}

function formatPercent(value) {
    return `${(Number(value || 0) * 100).toFixed(1)}%`;
}

function formatDurationMs(value) {
    const ms = Number(value || 0);
    if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
    return `${ms}ms`;
}

function formatDurationSeconds(value) {
    const seconds = Number(value || 0);
    if (seconds >= 3600) return `${(seconds / 3600).toFixed(1)}h`;
    if (seconds >= 60) return `${(seconds / 60).toFixed(1)}m`;
    return `${seconds}s`;
}

function formatTime(value) {
    if (value === null || value === undefined || value === '') return '--';
    if (typeof value === 'number') {
        try {
            return new Date(value * 1000).toLocaleString(ovLocale(), { hour12: false });
        } catch (error) {
            return String(value);
        }
    }
    return String(value);
}

function esc(value) {
    if (typeof escapeHtml === 'function') {
        return escapeHtml(String(value === null || value === undefined ? '' : value));
    }
    return String(value === null || value === undefined ? '' : value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function totalValues(values) {
    return Object.keys(values || {}).reduce((sum, key) => sum + Number(values[key] || 0), 0);
}

function formatChannelLabel(value) {
    const raw = String(value || '').trim();
    const normalized = raw.toLowerCase();
    const mapped = {
        unknown: '未知通道',
        'graph inbox': 'Graph 收件箱',
        'graph junk': 'Graph 垃圾箱',
        'imap new': 'IMAP 新链路',
        'imap old': 'IMAP 旧链路',
        'temp mail': '临时邮箱通道',
        'ai fallback': 'AI 兜底通道',
        graph: 'Graph 通道',
        imap: 'IMAP 通道',
        telegram: 'Telegram',
        email: 'Email',
        webhook: 'Webhook',
        graph_inbox: 'Graph 收件箱',
        graph_junk: 'Graph 垃圾箱',
        imap_new: 'IMAP 新链路',
        imap_old: 'IMAP 旧链路',
        temp_mail: '临时邮箱通道',
        ai_fallback: 'AI 兜底通道',
        graph_delta: 'Graph 通道',
        imap_ssl: 'IMAP 通道'
    };
    return ovT(mapped[normalized] || raw || '--');
}

function formatTimelineAction(value) {
    const raw = String(value || '').trim();
    const normalized = raw.toLowerCase();
    if (normalized === 'verification_extract') {
        return ovT('验证码提取事件');
    }
    if (normalized.startsWith('notification:')) {
        const channel = raw.includes(':') ? raw.slice(raw.indexOf(':') + 1) : '';
        return ovT(`通知：${formatChannelLabel(channel)}`);
    }
    return ovT(raw || '--');
}

function formatTimelineStatus(value) {
    const raw = String(value || '').trim();
    const normalized = raw.toLowerCase();
    const mapped = {
        success: '成功',
        successful: '成功',
        sent: '已发送',
        ok: '正常',
        failed: '失败',
        error: '失败',
        fail: '失败'
    };
    return ovT(mapped[normalized] || raw || '--');
}

function formatPoolActionLabel(value) {
    const raw = String(value || '').trim();
    const normalized = raw.toLowerCase();
    const mapped = {
        claim: '领取',
        complete: '完成',
        release: '释放',
        expire: '过期回收'
    };
    return ovT(mapped[normalized] || raw || '--');
}

function pickTimelineIcon(action) {
    const text = String(action || '').toLowerCase();
    if (text.includes('verification')) return '🔑';
    if (text.includes('notification')) return '📣';
    if (text.includes('external')) return '🌐';
    if (text.includes('pool') || text.includes('claim') || text.includes('release') || text.includes('complete')) return '🎱';
    return '📋';
}

function pickToneGlyph(tone) {
    const key = String(tone || '').toLowerCase();
    if (key.includes('success')) return '◉';
    if (key.includes('accent')) return '✦';
    if (key.includes('warn')) return '◔';
    if (key.includes('danger')) return '◆';
    return '◎';
}

function updateOverviewRefreshTime() {
    const el = document.getElementById('ov-last-refresh');
    if (el) {
        el.textContent = new Date().toLocaleString(ovLocale(), { hour12: false });
    }
}

window.notifyOverviewDataChanged = function notifyOverviewDataChanged(tabIds, reason) {
    window.dispatchEvent(new CustomEvent('overview-data-changed', {
        detail: {
            tabs: Array.isArray(tabIds) ? tabIds : [],
            reason: reason || ''
        }
    }));
};

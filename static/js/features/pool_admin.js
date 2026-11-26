// ===== Pool Admin Feature Module (Issue #60) — UI/UX v2 =====
//
// 业务背景:
//   - PRD: docs/PRD/2026-05-18-Issue60-号池管理UI与状态维护PRD.md
//   - 为现有邮箱池补齐管理员可视化管理入口，解决"导入后无法持续维护"问题
//   - 最低必须: 看得见池内/池外、能移入/移出号池、claimed 保护
//   - 增强项: 强制释放、审计日志、批量操作、分页折叠、空数据弱化
//
// 设计决策 (TDD):
//   - TDD: docs/TDD/2026-05-18-Issue60-号池管理UI与状态维护TDD.md
//   - 独立查询接口 GET /api/pool-admin/accounts（不受 claimed 保护的只读查询）
//   - 单条动作接口 POST /api/pool-admin/accounts/:id/action（受 claimed 保护）
//   - claimed 状态只允许 force_release，其他动作一律拒绝
//
// 任务追踪:
//   - FD: docs/FD/2026-05-18-Issue60-号池管理UI与状态维护FD.md
//   - UI/UX v2: 筛选横向紧凑、分页省略号折叠、空数据弱化、行内按钮→文字链接、批量选择/操作

let __poolAdminState = {
    page: 1,
    pageSize: 20, // 业务规则 (PRD): 每页 20 条，平衡可读性与加载速度
    groupOptionsLoaded: false,
    selectedIds: new Set(),
};

// paT — Pool Admin 翻译封装，委托给 i18n.js 的 translateAppTextLocal
// 设计权衡: 整句翻译（而非分片拼接）以支持中英语序差异
// i18n.js 中通过 regex pattern 匹配 "已选 N 条" → "$1 selected" 等模式
function paT(text) {
    if (text === null || text === undefined || text === '') return '';
    if (typeof translateAppTextLocal === 'function') return translateAppTextLocal(text);
    if (window.translateAppText) return window.translateAppText(text);
    return String(text);
}

// loadPoolAdmin — 号池管理页面主入口，由 main.js navigate('pool-admin') 调用
// 请求参数: in_pool(池内/池外)、pool_status、provider、group_id、search、page、page_size
// API: GET /api/pool-admin/accounts
function loadPoolAdmin(forceRefresh = false) {
    const wrapper = document.getElementById('poolAdminTableWrapper');
    if (!wrapper) return;

    ensurePoolAdminGroupOptions();

    if (!forceRefresh && __poolAdminState.cache) {
        renderPoolAdmin(__poolAdminState.cache);
        return;
    }

    const inPool = document.getElementById('poolAdminInPoolFilter')?.value || 'all';
    const poolStatus = document.getElementById('poolAdminStatusFilter')?.value || '';
    const provider = document.getElementById('poolAdminProviderFilter')?.value || '';
    const groupId = document.getElementById('poolAdminGroupFilter')?.value || '';
    const search = document.getElementById('poolAdminSearch')?.value || '';

    __poolAdminState.loading = true;
    __poolAdminState.selectedIds.clear();
    updatePoolAdminBatchBar();
    wrapper.innerHTML = '<div class="loading-overlay"><span class="spinner"></span> ' + paT('加载中…') + '</div>';

    const params = new URLSearchParams();
    params.set('in_pool', inPool);
    if (poolStatus) params.set('pool_status', poolStatus);
    if (provider) params.set('provider', provider);
    if (groupId) params.set('group_id', groupId);
    if (search) params.set('search', search);
    params.set('page', String(__poolAdminState.page));
    params.set('page_size', String(__poolAdminState.pageSize));

    fetch('/api/pool-admin/accounts?' + params.toString())
        .then(r => r.json())
        .then(data => {
            __poolAdminState.cache = data;
            renderPoolAdmin(data);
        })
        .catch(err => {
            wrapper.innerHTML = '<div class="ov-empty" style="padding:2rem;">' + paT('加载失败') + ': ' + String(err) + '</div>';
        })
        .finally(() => {
            __poolAdminState.loading = false;
        });
}

function ensurePoolAdminGroupOptions(forceRefresh = false) {
    const select = document.getElementById('poolAdminGroupFilter');
    if (!select) return;
    if (!forceRefresh && __poolAdminState.groupOptionsLoaded) return;

    const selectedValue = select.value || '';

    fetch('/api/groups')
        .then(r => r.json())
        .then(data => {
            const groups = Array.isArray(data?.groups) ? data.groups : [];
            const optionsHtml = ['<option value="">' + paT('所有分组') + '</option>'];
            groups.forEach(group => {
                const id = String(group.id ?? '').trim();
                if (!id) return;
                const name = escapeHtml(group.name || id);
                optionsHtml.push(`<option value="${id}">${name}</option>`);
            });
            select.innerHTML = optionsHtml.join('');
            if (selectedValue && select.querySelector(`option[value="${selectedValue}"]`)) {
                select.value = selectedValue;
            }
            __poolAdminState.groupOptionsLoaded = true;
        })
        .catch(() => {
            // 分组加载失败不阻断列表查询
        });
}

let __poolAdminSearchDebounce = null;
function debouncePoolAdminSearch() {
    if (__poolAdminSearchDebounce) clearTimeout(__poolAdminSearchDebounce);
    __poolAdminSearchDebounce = setTimeout(() => {
        __poolAdminState.page = 1;
        loadPoolAdmin(true);
    }, 400);
}

// renderCell — 空/NULL 数据视觉弱化，渲染为灰色斜体低透明度
// 设计决策 (FD/1.2.1): 空值不渲染原始 "NULL"/"-" 文本，而是用 CSS 弱化
function renderCell(text, fallback) {
    if (text === null || text === undefined || text === '' || text === 'NULL' || text === fallback) {
        return `<span style="color:var(--text-muted);opacity:0.5;font-style:italic;">${fallback || '-'}</span>`;
    }
    return escapeHtml(String(text));
}

// actionLink — 行内操作渲染为文字链接而非实体按钮
// 设计权衡 (PRD/用户反馈): 实体 btn 权重过高喧宾夺主，改为 <a> + hover 背景效果
// 颜色语义: 主操作蓝色(var(--clr-primary))、危险红色(var(--clr-danger))、常规灰色
function actionLink(label, onclick, color) {
    const c = color || 'var(--clr-primary)';
    return `<a href="javascript:void(0)" onclick="${onclick}" style="color:${c};font-size:0.78rem;text-decoration:none;white-space:nowrap;padding:2px 6px;border-radius:4px;transition:background 0.15s;" onmouseover="this.style.background='rgba(0,0,0,0.04)'" onmouseout="this.style.background='transparent'">${paT(label)}</a>`;
}

// buildPagination — 省略号折叠分页器
// 设计决策: delta=1，当前页前后各 1 页 + 首尾页 + "…" 省略号
// 业务场景: 801 条数据 / 每页 3 条 = 267 页，全平铺不可接受
function buildPagination(current, total) {
    if (total <= 1) return '';

    const delta = 1; // 当前页前后各显示多少页
    const range = [];
    const left = Math.max(2, current - delta);
    const right = Math.min(total - 1, current + delta);

    range.push(1);
    if (left > 2) range.push('...');
    for (let i = left; i <= right; i++) range.push(i);
    if (right < total - 1) range.push('...');
    if (total > 1) range.push(total);

    return range.map(p => {
        if (p === '...') return `<span style="color:var(--text-muted);padding:0 4px;">…</span>`;
        const active = p === current;
        const cls = active ? 'btn-primary' : 'btn-ghost';
        return `<button class="btn btn-sm ${cls}" onclick="goPoolAdminPage(${p})" ${active ? 'disabled' : ''}>${p}</button>`;
    }).join('');
}

// ---- 批量选择 ----
function togglePoolAdminRow(id, checked) {
    if (checked) {
        __poolAdminState.selectedIds.add(id);
    } else {
        __poolAdminState.selectedIds.delete(id);
    }
    updatePoolAdminBatchBar();
}

function togglePoolAdminAll(checked) {
    const items = __poolAdminState.cache?.items || [];
    __poolAdminState.selectedIds.clear();
    if (checked) {
        items.forEach(item => __poolAdminState.selectedIds.add(item.id));
    }
    // 更新所有 checkbox 状态
    document.querySelectorAll('.pa-row-check').forEach(cb => { cb.checked = checked; });
    updatePoolAdminBatchBar();
}

function updatePoolAdminBatchBar() {
    const bar = document.getElementById('poolAdminBatchBar');
    const count = document.getElementById('poolAdminBatchCount');
    if (!bar || !count) return;
    const n = __poolAdminState.selectedIds.size;
    if (n > 0) {
        bar.style.display = 'flex';
        count.textContent = paT('已选 ' + n + ' 条');
    } else {
        bar.style.display = 'none';
    }
}

// batchPoolAdminAction — 批量操作：逐条串行调用后端单条 action 接口
// 设计权衡: 后端只有单条 POST /api/pool-admin/accounts/:id/action，无批量接口
// 串行策略: 完成后汇总 toast，不使用 Promise.all（避免并发压力 + 便于统计成功/失败数）
// 业务规则 (TDD/A-01,A-02): 批量仅支持 move_into_pool 和 move_out_of_pool
function batchPoolAdminAction(action) {
    const ids = Array.from(__poolAdminState.selectedIds);
    if (ids.length === 0) return;
    const actionNames = {
        'move_into_pool': '批量移入号池',
        'move_out_of_pool': '批量移出号池',
    };
    const actionName = actionNames[action] || action;
    if (!confirm(paT('确定对 ' + ids.length + ' 条记录执行「' + paT(actionName) + '」吗？'))) return;

    // 逐条调用（后端是单条 action 接口）
    let done = 0;
    let failed = 0;
    const total = ids.length;
    const doNext = () => {
        if (done + failed >= total) {
            showToast(paT('完成: ' + done + ' 成功, ' + failed + ' 失败'), failed > 0 ? 'warning' : 'success');
            __poolAdminState.selectedIds.clear();
            loadPoolAdmin(true);
            return;
        }
        const id = ids[done + failed];
        fetch(`/api/pool-admin/accounts/${id}/action`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action }),
        })
        .then(r => r.json())
        .then(data => {
            if (data.success) { done++; } else { failed++; }
            doNext();
        })
        .catch(() => { failed++; doNext(); });
    };
    doNext();
}

// renderPoolAdmin — 主渲染函数，构建号池管理表格 + 分页 + 批量操作栏
// 数据结构: items[].{ id, email, group_name, provider, pool_status, last_result, claimed_by, claimed_at }
// 业务规则 (TDD/C-01~C-04): claimed 状态只展示 force_release，其他操作全部隐藏
// 业务规则 (PRD): NULL 状态只展示"移入号池"，非 NULL 状态展示"移出" + 状态相关操作
function renderPoolAdmin(data) {
    const wrapper = document.getElementById('poolAdminTableWrapper');
    const paginationEl = document.getElementById('poolAdminPagination');
    if (!wrapper) return;

    const items = data.items || [];
    if (items.length === 0) {
        wrapper.innerHTML = '<div class="ov-empty" style="padding:2rem;">' + paT('暂无数据') + '</div>';
        if (paginationEl) paginationEl.innerHTML = '';
        return;
    }

    const statusLabelMap = {
        'available': { text: '可用', cls: 'status-badge status-success' },
        'claimed': { text: '占用中', cls: 'status-badge status-warning' },
        'cooldown': { text: '冷却中', cls: 'status-badge status-info' },
        'used': { text: '已使用', cls: 'status-badge status-muted' },
        'frozen': { text: '冻结', cls: 'status-badge status-danger' },
        'retired': { text: '退休', cls: 'status-badge status-muted' },
    };

    const rows = items.map(item => {
        const status = item.pool_status || 'NULL';
        const statusInfo = statusLabelMap[status] || { text: status || 'NULL', cls: 'status-badge' };
        const isClaimed = status === 'claimed';
        const isNull = status === 'NULL' || !status;
        const isInPool = !isNull;
        const checked = __poolAdminState.selectedIds.has(item.id) ? 'checked' : '';

        // 行内操作：文字链接风格
        let actionsHtml = '';
        if (isClaimed) {
            actionsHtml = actionLink('强制释放', `confirmPoolAdminAction(${item.id}, 'force_release', '${item.email}')`, 'var(--clr-warn)');
        } else if (isNull) {
            actionsHtml = actionLink('移入号池', `confirmPoolAdminAction(${item.id}, 'move_into_pool', '${item.email}')`);
        } else {
            actionsHtml = actionLink('移出号池', `confirmPoolAdminAction(${item.id}, 'move_out_of_pool', '${item.email}')`, 'var(--text-muted)');
            if (['cooldown', 'used', 'frozen', 'retired'].includes(status)) {
                actionsHtml += ' · ' + actionLink('恢复可用', `confirmPoolAdminAction(${item.id}, 'restore_available', '${item.email}')`);
            }
            if (['available', 'cooldown', 'used'].includes(status)) {
                actionsHtml += ' · ' + actionLink('冻结', `confirmPoolAdminAction(${item.id}, 'freeze', '${item.email}')`, 'var(--text-muted)');
            }
            if (['available', 'cooldown', 'used', 'frozen'].includes(status)) {
                actionsHtml += ' · ' + actionLink('退休', `confirmPoolAdminAction(${item.id}, 'retire', '${item.email}')`, 'var(--clr-danger)');
            }
        }

        const claimedInfo = isClaimed
            ? `<div style="font-size:0.72rem;color:var(--text-muted);margin-top:2px;">${paT('占用方')}: ${escapeHtml(item.claimed_by || '')} · ${escapeHtml(item.claimed_at || '').slice(0, 16)}</div>`
            : '';

        return `<tr>
            <td style="white-space:nowrap;width:28px;"><input type="checkbox" class="pa-row-check" data-id="${item.id}" ${checked} onchange="togglePoolAdminRow(${item.id}, this.checked)"></td>
            <td style="white-space:nowrap;font-weight:500;">${escapeHtml(item.email)}</td>
            <td>${renderCell(item.group_name, '-')}</td>
            <td>${renderCell(item.provider, '-')}</td>
            <td><span class="${statusInfo.cls}">${paT(statusInfo.text)}</span></td>
            <td>${renderCell(item.last_result, '-')}</td>
            <td style="min-width:180px;">
                ${claimedInfo}
                <div style="display:flex;gap:2px;flex-wrap:wrap;align-items:center;">${actionsHtml}</div>
            </td>
        </tr>`;
    }).join('');

    // 全选 checkbox 状态
    const allChecked = items.length > 0 && items.every(item => __poolAdminState.selectedIds.has(item.id));

    wrapper.innerHTML = `<div class="table-responsive">
        <table class="data-table data-table--pool-admin">
            <thead>
                <tr>
                    <th style="width:28px;"><input type="checkbox" id="paCheckAll" ${allChecked ? 'checked' : ''} onchange="togglePoolAdminAll(this.checked)"></th>
                    <th>${paT('邮箱')}</th>
                    <th>${paT('分组')}</th>
                    <th>${paT('类型')}</th>
                    <th>${paT('池状态')}</th>
                    <th>${paT('最近结果')}</th>
                    <th>${paT('操作')}</th>
                </tr>
            </thead>
            <tbody>${rows}</tbody>
        </table>
    </div>`;

    // 分页
    if (paginationEl) {
        const total = data.total || 0;
        const page = data.page || 1;
        const pageSize = data.page_size || 20;
        const totalPages = data.total_pages || 1;
        if (totalPages > 1) {
            const pagesHtml = buildPagination(page, totalPages);
            paginationEl.innerHTML = `<div style="display:flex;gap:6px;align-items:center;justify-content:center;flex-wrap:wrap;">
                <span style="color:var(--text-muted);font-size:0.78rem;margin-right:8px;">${paT('共 ' + total + ' 条 · 第 ' + page + '/' + totalPages + ' 页')}</span>
                ${pagesHtml}
            </div>`;
        } else {
            paginationEl.innerHTML = `<div style="text-align:center;color:var(--text-muted);font-size:0.78rem;">${paT('共 ' + total + ' 条')}</div>`;
        }
    }

    updatePoolAdminBatchBar();
}

function goPoolAdminPage(page) {
    __poolAdminState.page = page;
    loadPoolAdmin(true);
}

// confirmPoolAdminAction — 单条操作确认 + 执行
// API: POST /api/pool-admin/accounts/:id/action
// 业务规则 (TDD): claimed 只允许 force_release；非 claimed 不允许 force_release
function confirmPoolAdminAction(accountId, action, email) {
    const actionNames = {
        'move_into_pool': '移入号池',
        'move_out_of_pool': '移出号池',
        'restore_available': '恢复可用',
        'freeze': '冻结',
        'retire': '退休',
        'force_release': '强制释放',
    };
    const actionName = actionNames[action] || action;
    const msg = paT('确定对 ' + String(email || '') + ' 执行「' + paT(actionName) + '」吗？');
    if (!confirm(msg)) return;

    fetch(`/api/pool-admin/accounts/${accountId}/action`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action }),
    })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                showToast(paT('操作成功'), 'success');
                if (typeof window.notifyOverviewDataChanged === 'function') {
                    window.notifyOverviewDataChanged(['summary', 'pool']);
                }
                loadPoolAdmin(true);
            } else {
                showToast(data.message || paT('操作失败'), 'error');
            }
        })
        .catch(err => {
            showToast(paT('请求失败') + ': ' + String(err), 'error');
        });
}

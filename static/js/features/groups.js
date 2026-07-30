        // ==================== 分组相关 ====================

        // 加载分组列表
        async function loadGroups() {
            const container = document.getElementById('groupList');
            container.innerHTML = `<div class="loading-overlay"><span class="spinner"></span> ${translateAppTextLocal('加载中…')}</div>`;

            try {
                const response = await fetch('/api/groups');
                const data = await response.json();

                if (data.success) {
                    groups = data.groups;

                    // 找到临时邮箱分组
                    const tempGroup = groups.find(g => g.name === '临时邮箱');
                    if (tempGroup) {
                        tempEmailGroupId = tempGroup.id;
                    }

                    renderGroupList(data.groups);
                    if (typeof renderCompactGroupStrip === 'function') {
                        renderCompactGroupStrip(data.groups, currentGroupId);
                    }
                    updateGroupSelects();

                    // 如果之前选中了分组，保持选中状态并刷新邮箱列表
                    if (currentGroupId) {
                        const group = groups.find(g => g.id === currentGroupId);
                        if (group) {
                            // 刷新当前分组的邮箱列表
                            if (currentGroupId === tempEmailGroupId) {
                                loadTempEmails(true);
                            } else {
                                await loadAccountsByGroup(currentGroupId, true);
                            }
                        }
                    } else if (currentPage !== 'temp-emails') {
                        // BUG-06 防御：在临时邮箱页面时，不自动选组。
                        // 自动选组会调用 selectGroup()，进而清空 currentAccount，
                        // 导致用户在临时邮箱页选中的邮箱被意外重置。
                        // 仅在其他页面（mailbox/dashboard 等）才执行首次自动选组。
                        const firstNormalGroup = groups.find(g => !isTempMailboxGroup(g));
                        if (firstNormalGroup) {
                            selectGroup(firstNormalGroup.id);
                        }
                    }
                }
            } catch (error) {
                container.innerHTML = `<div class="empty-state"><p>${translateAppTextLocal('加载失败')}</p></div>`;
                showToast(translateAppTextLocal('加载分组失败'), 'error');
            }
        }

        // 渲染分组列表
        function renderGroupList(groups) {
            const container = document.getElementById('groupList');

            // 过滤掉临时邮箱分组（已有独立页面管理）
            const filteredGroups = groups.filter(g => !isTempMailboxGroup(g));

            if (filteredGroups.length === 0) {
                container.innerHTML = `
                    <div class="empty-state">
                        <span class="empty-icon">📁</span>
                        <p>${translateAppTextLocal('暂无分组')}</p>
                    </div>
                `;
                return;
            }

            container.innerHTML = filteredGroups.map(group => {
                const isSystem = group.is_system === 1;
                const isDefault = group.id === 1;

                return `
                    <div class="group-item ${currentGroupId === group.id ? 'active' : ''}"
                         data-group-id="${group.id}"
                         onclick="selectGroup(${group.id})">
                        <span class="group-color-dot" style="background-color: ${group.color || '#666'}"></span>
                        <span class="group-name">${escapeHtml(group.name)}</span>
                        <span class="badge-count">${group.account_count || 0}</span>
                        <div class="group-actions">
                            ${!isSystem ? `<button class="btn-icon" onclick="event.stopPropagation(); editGroup(${group.id})" title="编辑">✏️</button>` : ''}
                            ${!isDefault && !isSystem ? `<button class="btn-icon" onclick="event.stopPropagation(); deleteGroup(${group.id})" title="删除">🗑️</button>` : ''}
                        </div>
                    </div>
                `;
            }).join('');
        }

        // 仅同步左侧分组选中态与面板标题，不重载列表、不清空搜索/邮件
        function focusGroupSelection(groupId) {
            if (groupId === null || groupId === undefined || groupId === '') return null;
            const normalizedId = Number(groupId);
            if (!Number.isFinite(normalizedId)) return null;

            currentGroupId = normalizedId;
            const group = (typeof groups !== 'undefined' ? groups : []).find(g => Number(g.id) === normalizedId) || null;
            isTempEmailGroup = Boolean(group && typeof isTempMailboxGroup === 'function' && isTempMailboxGroup(group));

            document.querySelectorAll('.group-item').forEach(item => {
                item.classList.toggle('active', parseInt(item.dataset.groupId, 10) === normalizedId);
            });
            if (typeof renderCompactGroupStrip === 'function') {
                renderCompactGroupStrip(groups, normalizedId);
            }

            if (group) {
                const nameEl = document.getElementById('currentGroupName');
                const colorEl = document.getElementById('currentGroupColor');
                if (nameEl) nameEl.textContent = formatGroupDisplayName(group.name);
                if (colorEl) colorEl.style.backgroundColor = group.color || '#666';
                const importSelect = document.getElementById('importGroupSelect');
                if (importSelect) importSelect.value = normalizedId;
            }
            if (typeof updateAccountPanelFooter === 'function') {
                updateAccountPanelFooter();
            }
            return group;
        }

        // 从账号列表打开账号：全局模式下先定位所属分组，再打开邮件列
        async function openAccountFromList(email, groupId) {
            const targetEmail = String(email || '').trim();
            if (!targetEmail) return;

            if (accountSearchScope === 'all' && groupId !== null && groupId !== undefined && groupId !== '') {
                const group = focusGroupSelection(groupId);
                if (group && typeof isTempMailboxGroup === 'function' && isTempMailboxGroup(group)) {
                    navigate('temp-emails');
                    return;
                }
            }

            if (typeof selectAccount === 'function') {
                selectAccount(targetEmail);
            }
        }

        // 选择分组
        async function selectGroup(groupId) {
            currentGroupId = groupId;
            currentAccountPage = 1;  // 切换分组时重置到第 1 页

            // 切换分组时停止所有正在运行的轮询（避免跨分组轮询堆积）
            if (typeof stopAllPolls === 'function') {
                stopAllPolls();
            }

            // 仅「当前分组」范围清空搜索，避免跨组误读；「全部账号」保留关键词与结果上下文
            const searchInput = document.getElementById('globalSearch');
            if (accountSearchScope !== 'all') {
                currentAccountSearchQuery = '';
                if (searchInput) searchInput.value = '';
                updateAccountSearchClearButton();
            }

            // 重置右侧邮件列 UI（清除上一个分组的残留状态）
            currentAccount = null;
            const accountBar = document.getElementById('currentAccountBar');
            if (accountBar) accountBar.style.display = 'none';
            const emailListEl = document.getElementById('emailList');
            if (emailListEl) {
                emailListEl.innerHTML = `<div class="empty-state"><span class="empty-icon">📬</span><p>${translateAppTextLocal('请从左侧选择一个邮箱账号')}</p></div>`;
            }
            const detailSection = document.getElementById('emailDetailSection');
            if (detailSection) detailSection.style.display = 'none';
            const folderTabs = document.getElementById('folderTabs');
            if (folderTabs) folderTabs.style.display = 'none';
            const emailCount = document.getElementById('emailCount');
            if (emailCount) emailCount.textContent = '';
            const methodTag = document.getElementById('methodTag');
            if (methodTag) methodTag.style.display = 'none';

            // 检查是否是临时邮箱分组
            const group = focusGroupSelection(groupId) || groups.find(g => g.id === groupId);
            isTempEmailGroup = Boolean(group && isTempMailboxGroup(group));

            // 加载该分组的邮箱
            if (isTempEmailGroup) {
                // 临时邮箱已有独立页面，跳转到专属页面管理
                navigate('temp-emails');
                return;
            } else if (accountSearchScope === 'all') {
                // 全局范围不依赖左侧选中分组；保留关键词并刷新跨组列表
                await loadAccountList(true, 1);
            } else {
                // 切换分组：加载账号列表（不启动批量轮询）
                await loadAccountsByGroup(groupId);
            }
        }

        // 更新账号面板底部按钮（新布局无独立footer，通过topbar按钮实现）
        function updateAccountPanelFooter() {
            // No-op: new layout uses topbar action buttons instead
        }

        // Account list search scope must be declared before loadAccountList helpers.
        let accountSearchScope = 'group'; // 'group' | 'all'
        const GLOBAL_ACCOUNT_CACHE_KEY = '__all__';

        function getAccountListCacheKey(groupId = currentGroupId) {
            if (accountSearchScope === 'all') {
                return GLOBAL_ACCOUNT_CACHE_KEY;
            }
            return groupId;
        }

        function resolveAccountListTarget(groupId = currentGroupId) {
            if (accountSearchScope === 'all') {
                return { cacheKey: GLOBAL_ACCOUNT_CACHE_KEY, requestGroupId: null };
            }
            return { cacheKey: groupId, requestGroupId: groupId };
        }

        // 加载账号列表（支持当前分组 / 全部账号）
        async function loadAccountList(forceRefresh = false, page = currentAccountPage, groupId = currentGroupId) {
            const container = document.getElementById('accountList');
            if (!container) return;

            if (accountSearchScope !== 'all' && (groupId === null || groupId === undefined)) {
                container.innerHTML = `
                    <div class="empty-state">
                        <span class="empty-icon">📁</span>
                        <p>${translateAppTextLocal('请从左侧选择一个分组')}</p>
                    </div>
                `;
                if (typeof renderCompactEmptyState === 'function') {
                    renderCompactEmptyState(translateAppTextLocal('请从左侧选择一个分组'));
                } else if (typeof renderCompactErrorState === 'function') {
                    renderCompactErrorState(translateAppTextLocal('请从左侧选择一个分组'));
                }
                return;
            }

            const { cacheKey, requestGroupId } = resolveAccountListTarget(groupId);
            const savedScrollTop = forceRefresh ? container.scrollTop : 0;
            const queryKey = buildAccountListQueryKey(requestGroupId, page);
            const cachedMeta = accountListMetaCache[cacheKey];

            if (!forceRefresh && Array.isArray(accountsCache[cacheKey]) && cachedMeta && cachedMeta.queryKey === queryKey) {
                currentAccountPage = Number(cachedMeta.page || page || 1);
                renderAccountList(accountsCache[cacheKey]);
                if (typeof renderCompactAccountList === 'function') {
                    renderCompactAccountList(accountsCache[cacheKey]);
                }
                return;
            }

            if (!forceRefresh) {
                const loadingText = currentAccountSearchQuery
                    ? translateAppTextLocal('搜索中…')
                    : translateAppTextLocal('加载中…');
                container.innerHTML = `<div class="loading-overlay"><span class="spinner"></span> ${loadingText}</div>`;
                if (typeof renderCompactLoadingState === 'function') {
                    renderCompactLoadingState(loadingText);
                }
            }

            try {
                const response = await fetch(`/api/accounts?${queryKey}`);
                const data = await response.json();

                if (data.success) {
                    updateAccountListCache(cacheKey, data.accounts, data.pagination, queryKey);

                    const toolbarRetryBtn = document.getElementById('toolbarRetryBtn');
                    if (toolbarRetryBtn) {
                        const list = accountsCache[cacheKey] || [];
                        const hasFailedAccounts = list.some(acc => isRefreshableOutlookAccount(acc) && acc.last_refresh_status === 'failed');
                        toolbarRetryBtn.style.display = hasFailedAccounts ? 'inline-block' : 'none';
                    }

                    renderAccountList(accountsCache[cacheKey]);
                    if (typeof renderCompactAccountList === 'function') {
                        renderCompactAccountList(accountsCache[cacheKey]);
                    }
                    if (forceRefresh) {
                        requestAnimationFrame(() => { container.scrollTop = savedScrollTop; });
                    }
                }
            } catch (error) {
                container.innerHTML = `<div class="empty-state"><p>${translateAppTextLocal('加载失败')}</p></div>`;
                if (typeof renderCompactErrorState === 'function') {
                    renderCompactErrorState(translateAppTextLocal('加载失败'));
                }
            }
        }

        // 加载分组下的账号（兼容旧调用；全局范围时忽略 groupId）
        async function loadAccountsByGroup(groupId, forceRefresh = false, page = currentAccountPage) {
            if (accountSearchScope === 'all') {
                return loadAccountList(forceRefresh, page, null);
            }
            return loadAccountList(forceRefresh, page, groupId);
        }

        // 获取 provider 的中文展示名（账号卡片 tag）
        function getProviderLabel(provider) {
            const key = (provider || 'outlook').toString().toLowerCase();
            const labels = {
                outlook: 'Outlook',
                gmail: 'Gmail',
                qq: 'QQ 邮箱',
                '163': '163 邮箱',
                '126': '126 邮箱',
                yahoo: 'Yahoo 邮箱',
                aliyun: '阿里邮箱',
                custom: '自定义 IMAP',
                cloudflare_temp_mail: 'CF 临时邮箱'
            };
            return translateAppTextLocal(labels[key] || provider || '未知');
        }

        function isOutlookLikeAccount(account) {
            if (!account) return false;
            const accountType = String(account.account_type || '').toLowerCase();
            const provider = String(account.provider || '').toLowerCase();
            if (accountType === 'imap' || provider === 'imap') return false;
            if (provider === 'cloudflare_temp_mail' || accountType === 'temp_mail') return false;
            return accountType === 'outlook' || provider === 'outlook' || !provider;
        }

        function buildAccountAliasCountBadge(account) {
            if (!isOutlookLikeAccount(account)) return '';
            const usedRaw = account.alias_used_count;
            if (usedRaw === null || usedRaw === undefined || usedRaw === '') {
                return `<span class="account-alias-count account-alias-count-empty clickable" title="${escapeHtml(translateAppTextLocal('点击状态刷新'))}" onclick="event.stopPropagation(); triggerAliasSyncForAccount(${account.id})">+</span>`;
            }
            const used = Number(usedRaw);
            if (!Number.isFinite(used)) return '';
            const softLimit = Number(account.alias_soft_limit || 5) || 5;
            const warnClass = used >= softLimit ? ' alias-count-warn' : '';
            return `<span class="account-alias-count${warnClass}" title="${escapeHtml(translateAppTextLocal('已使用的分裂地址数量'))}">+${used}</span>`;
        }

        async function triggerAliasSyncForAccount(accountId) {
            // Select this account implicitly for the sync operation
            selectedAccountIds.add(accountId);
            updateSelectAllCheckbox();
            updateBatchActionBar();
            await batchSyncEmailAliases(true); // pass true to indicate it was a single trigger
        }

        function applyAliasScanResultToCache(accountId, used, softLimit, scannedAt, extra = {}) {
            const aid = Number(accountId);
            if (!Number.isFinite(aid) || aid <= 0) return;
            Object.keys(accountsCache || {}).forEach((groupKey) => {
                const list = accountsCache[groupKey];
                if (!Array.isArray(list)) return;
                const target = list.find((item) => Number(item && item.id) === aid);
                if (!target) return;
                if (used !== null && used !== undefined) {
                    target.alias_used_count = Number(used || 0);
                    target.alias_soft_limit = Number(softLimit || 5) || 5;
                }
                if (scannedAt) target.alias_scanned_at = scannedAt;
                if (extra.last_refresh_at) target.last_refresh_at = extra.last_refresh_at;
                if (extra.status) target.status = extra.status;
                if (extra.last_refresh_status) target.last_refresh_status = extra.last_refresh_status;
            });
        }

        let aliasSyncInProgress = false;
        let aliasSyncAbortController = null;
        // Small chunks keep progress moving without freezing at 0/N for a whole page.
        // 5 balances request overhead vs per-account Graph latency.
        const ALIAS_BATCH_CHUNK_SIZE = 5;

        function findAccountEmailById(accountId) {
            const aid = Number(accountId);
            if (!Number.isFinite(aid) || aid <= 0) return '';
            let found = '';
            Object.values(accountsCache || {}).some((list) => {
                if (!Array.isArray(list)) return false;
                const hit = list.find((item) => Number(item && item.id) === aid);
                if (hit) {
                    found = String(hit.email || '');
                    return true;
                }
                return false;
            });
            return found;
        }

        function setAliasSyncProgressVisible(visible) {
            const bar = document.getElementById('aliasSyncProgressBar');
            if (bar) bar.style.display = visible ? 'flex' : 'none';
            const syncBtn = document.getElementById('toolbarAliasSyncBtn');
            if (syncBtn) syncBtn.disabled = !!visible;
        }

        function updateAliasSyncProgress({
            done = 0,
            total = 0,
            text = '',
            cancelled = false,
            successCount = 0,
            failedCount = 0,
        } = {}) {
            const safeTotal = Math.max(0, Number(total) || 0);
            const safeDone = Math.max(0, Math.min(safeTotal, Number(done) || 0));
            const fill = document.getElementById('aliasSyncProgressFill');
            const countEl = document.getElementById('aliasSyncProgressCount');
            const textEl = document.getElementById('aliasSyncProgressText');
            const pct = safeTotal > 0 ? Math.round((safeDone / safeTotal) * 100) : 0;
            if (fill) fill.style.width = `${pct}%`;
            if (countEl) {
                const stats = [];
                if (successCount) stats.push(`${successCount}${translateAppTextLocal('成功')}`);
                if (failedCount) stats.push(`${failedCount}${translateAppTextLocal('失败')}`);
                countEl.textContent = stats.length
                    ? `${safeDone} / ${safeTotal}（${stats.join(' · ')}）`
                    : `${safeDone} / ${safeTotal}`;
            }
            if (textEl) {
                if (text) {
                    textEl.textContent = text;
                } else if (cancelled) {
                    textEl.textContent = translateAppTextLocal('已取消状态刷新');
                } else {
                    textEl.textContent = translateAppTextLocal('正在状态刷新…');
                }
            }
            const cancelBtn = document.getElementById('aliasSyncCancelBtn');
            if (cancelBtn) {
                cancelBtn.disabled = cancelled || !aliasSyncInProgress;
                cancelBtn.textContent = cancelled
                    ? translateAppTextLocal('已取消')
                    : translateAppTextLocal('取消');
            }
        }

        function cancelAliasSync() {
            if (!aliasSyncInProgress || !aliasSyncAbortController) return;
            aliasSyncAbortController.abort();
            const textEl = document.getElementById('aliasSyncProgressText');
            if (textEl) textEl.textContent = translateAppTextLocal('正在取消…');
            const cancelBtn = document.getElementById('aliasSyncCancelBtn');
            if (cancelBtn) {
                cancelBtn.disabled = true;
                cancelBtn.textContent = translateAppTextLocal('已取消');
            }
        }

        function resolveAliasSyncTargets(fromSingleBadge = false) {
            const selectedIds = Array.from(selectedAccountIds || [])
                .map(Number)
                .filter((id) => Number.isFinite(id) && id > 0);

            // Selected accounts take priority; otherwise default to current page.
            let fallbackIds = [];
            const pageCacheKey = getAccountListCacheKey(currentGroupId);
            if (!selectedIds.length && !fromSingleBadge && Array.isArray(accountsCache[pageCacheKey])) {
                fallbackIds = accountsCache[pageCacheKey]
                    .filter((acc) => isOutlookLikeAccount(acc))
                    .map((acc) => Number(acc.id))
                    .filter((id) => Number.isFinite(id) && id > 0);
            }

            const idsToUse = selectedIds.length ? selectedIds : fallbackIds;
            if (!idsToUse.length) return [];

            const selectedAccounts = [];
            Object.values(accountsCache || {}).forEach((list) => {
                if (!Array.isArray(list)) return;
                list.forEach((acc) => {
                    if (idsToUse.includes(Number(acc.id))) selectedAccounts.push(acc);
                });
            });

            const outlookIds = selectedAccounts
                .filter((acc) => isOutlookLikeAccount(acc))
                .map((acc) => Number(acc.id))
                .filter((id) => Number.isFinite(id) && id > 0);

            // Prefer Outlook-like accounts; still fall back to selection so backend can mark unsupported ones.
            return outlookIds.length ? outlookIds : idsToUse;
        }

        function refreshAliasSyncAccountViews() {
            const cacheKey = getAccountListCacheKey(currentGroupId);
            if (!Array.isArray(accountsCache[cacheKey])) return;

            // 已刷新 = last_refresh_at AND alias scan both present; 未刷新 if either missing.
            let list = accountsCache[cacheKey];
            if (currentAccountStatusFilter === 'unsynced') {
                list = list.filter((acc) => {
                    if (!acc) return true;
                    const noRefresh = !acc.last_refresh_at;
                    const noAliasScan = acc.alias_used_count === null || acc.alias_used_count === undefined || acc.alias_used_count === '';
                    return noRefresh || noAliasScan;
                });
                accountsCache[cacheKey] = list;
            } else if (currentAccountStatusFilter === 'synced') {
                list = list.filter((acc) => {
                    if (!acc || !acc.last_refresh_at) return false;
                    return !(acc.alias_used_count === null || acc.alias_used_count === undefined || acc.alias_used_count === '');
                });
                accountsCache[cacheKey] = list;
            } else if (currentAccountStatusFilter === 'has_alias') {
                list = list.filter((acc) => Number(acc && acc.alias_used_count) > 0);
                accountsCache[cacheKey] = list;
            } else if (currentAccountStatusFilter === 'no_alias') {
                list = list.filter((acc) => acc && acc.alias_used_count != null && Number(acc.alias_used_count) === 0);
                accountsCache[cacheKey] = list;
            } else if (currentAccountStatusFilter === 'active' || currentAccountStatusFilter === 'inactive') {
                list = list.filter((acc) => acc && acc.status === currentAccountStatusFilter);
                accountsCache[cacheKey] = list;
            }

            renderAccountList(list);
            if (typeof renderCompactAccountList === 'function') {
                renderCompactAccountList(list);
            }
        }

        async function batchSyncEmailAliases(fromSingleBadge = false) {
            if (aliasSyncInProgress) {
                showToast(translateAppTextLocal('状态刷新进行中，请稍候或先取消'), 'warning');
                return;
            }

            const idsToSync = resolveAliasSyncTargets(fromSingleBadge);
            if (!idsToSync.length) {
                showToast(translateAppTextLocal('请选择要状态刷新的账号'), 'warning');
                return;
            }

            aliasSyncInProgress = true;
            aliasSyncAbortController = new AbortController();
            const signal = aliasSyncAbortController.signal;

            let successCount = 0;
            let failedCount = 0;
            let unsupportedCount = 0;
            let processedCount = 0;
            let cancelled = false;
            let hardFailed = false;

            setAliasSyncProgressVisible(true);
            updateAliasSyncProgress({
                done: 0,
                total: idsToSync.length,
                text: translateAppTextLocal('正在状态刷新…'),
            });

            try {
                for (let offset = 0; offset < idsToSync.length; offset += ALIAS_BATCH_CHUNK_SIZE) {
                    if (signal.aborted) {
                        cancelled = true;
                        break;
                    }

                    const chunk = idsToSync.slice(offset, offset + ALIAS_BATCH_CHUNK_SIZE);
                    const currentIndex = processedCount + 1;
                    const currentEmail = findAccountEmailById(chunk[0]) || `#${chunk[0]}`;
                    updateAliasSyncProgress({
                        done: processedCount,
                        total: idsToSync.length,
                        successCount,
                        failedCount,
                        text: `${translateAppTextLocal('正在状态刷新…')} ${currentIndex}/${idsToSync.length} · ${currentEmail}`,
                    });

                    let response;
                    try {
                        response = await fetch('/api/emails/aliases/batch', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ account_ids: chunk, top: 50 }),
                            signal,
                        });
                    } catch (fetchError) {
                        if (signal.aborted || (fetchError && fetchError.name === 'AbortError')) {
                            cancelled = true;
                            break;
                        }
                        throw fetchError;
                    }

                    const data = await response.json();
                    if (!data.success) {
                        hardFailed = true;
                        handleApiError(data, '状态刷新失败');
                        break;
                    }

                    const results = Array.isArray(data.results) ? data.results : [];
                    results.forEach((item) => {
                        if (!item) return;
                        const nowIso = new Date().toISOString().replace('T', ' ').slice(0, 19);
                        if (item.success && item.supported !== false) {
                            applyAliasScanResultToCache(
                                item.account_id,
                                item.used ?? item.alias_used_count ?? 0,
                                item.soft_limit ?? item.alias_soft_limit ?? 5,
                                item.alias_scanned_at || nowIso,
                                {
                                    last_refresh_at: item.last_refresh_at || nowIso,
                                    status: item.status || 'active',
                                    last_refresh_status: 'success',
                                }
                            );
                        } else if (!item.success && item.supported !== false) {
                            // Failed status refresh: inactive + last_refresh_at, but no alias
                            // scan means dual-criteria 已刷新 is still not met (stays 未刷新).
                            applyAliasScanResultToCache(
                                item.account_id,
                                null,
                                null,
                                null,
                                {
                                    last_refresh_at: item.last_refresh_at || nowIso,
                                    status: item.status || 'inactive',
                                    last_refresh_status: 'failed',
                                }
                            );
                        }
                    });

                    const summary = data.summary || {};
                    successCount += Number(summary.success_accounts || 0);
                    failedCount += Number(summary.failed_accounts || 0);
                    unsupportedCount += Number(summary.unsupported_accounts || 0);
                    processedCount += chunk.length;

                    updateAliasSyncProgress({
                        done: processedCount,
                        total: idsToSync.length,
                        successCount,
                        failedCount,
                        text: `${translateAppTextLocal('正在状态刷新…')} ${processedCount}/${idsToSync.length}` +
                            (processedCount < idsToSync.length ? ` · ${currentEmail}` : ''),
                    });

                    refreshAliasSyncAccountViews();
                }

                if (hardFailed) {
                    updateAliasSyncProgress({
                        done: processedCount,
                        total: idsToSync.length,
                        successCount,
                        failedCount,
                        text: translateAppTextLocal('状态刷新失败'),
                    });
                } else if (cancelled || signal.aborted) {
                    updateAliasSyncProgress({
                        done: processedCount,
                        total: idsToSync.length,
                        cancelled: true,
                        successCount,
                        failedCount,
                        text: translateAppTextLocal('已取消状态刷新'),
                    });
                    showToast(
                        `${translateAppTextLocal('已取消状态刷新')}：${processedCount}/${idsToSync.length}` +
                        (successCount ? `，${successCount} 成功` : ''),
                        'warning'
                    );
                } else {
                    updateAliasSyncProgress({
                        done: idsToSync.length,
                        total: idsToSync.length,
                        successCount,
                        failedCount,
                        text: translateAppTextLocal('状态刷新完成'),
                    });
                    showToast(
                        `${translateAppTextLocal('状态刷新完成')}：${successCount} 成功` +
                        (failedCount ? ` / ${failedCount} 失败` : '') +
                        (unsupportedCount ? ` / ${unsupportedCount} 不支持` : ''),
                        failedCount ? 'warning' : 'success'
                    );
                }

                // Final server refresh so filters/counts match DB after partial cancel or completion.
                if (processedCount > 0 && (accountSearchScope === 'all' || currentGroupId != null)) {
                    try {
                        await loadAccountList(true, currentAccountPage);
                    } catch (_reloadError) {
                        // Local cache already updated; ignore reload failure.
                    }
                }
            } catch (error) {
                if (signal.aborted || (error && error.name === 'AbortError')) {
                    showToast(translateAppTextLocal('已取消状态刷新'), 'warning');
                } else {
                    showToast(translateAppTextLocal('状态刷新失败'), 'error');
                }
            } finally {
                aliasSyncInProgress = false;
                aliasSyncAbortController = null;
                // Keep the board visible briefly so the final state is readable, then hide.
                setTimeout(() => {
                    if (!aliasSyncInProgress) setAliasSyncProgressVisible(false);
                }, cancelled || signal?.aborted || hardFailed ? 1600 : 900);
            }
        }

        // 渲染邮箱列表
        function renderAccountList(accounts) {
            const container = document.getElementById('accountList');
            const safeAccounts = Array.isArray(accounts) ? accounts : [];

            if (safeAccounts.length === 0) {
                let emptyMessage = translateAppTextLocal('该分组暂无邮箱');
                let emptyActions = '';
                if (accountSearchScope === 'all') {
                    emptyMessage = currentAccountSearchQuery || currentAccountStatusFilter
                        ? translateAppTextLocal('未找到匹配账号，试试切换范围或清空筛选')
                        : translateAppTextLocal('暂无账号');
                } else if (!currentGroupId) {
                    emptyMessage = translateAppTextLocal('请从左侧选择一个分组');
                } else if (currentAccountSearchQuery || currentAccountStatusFilter || getSelectedTagFilterIds().length) {
                    emptyMessage = translateAppTextLocal('未找到匹配账号，试试切换到「全部账号」或清空筛选');
                    emptyActions = `
                        <div class="account-empty-actions">
                            <button type="button" class="btn btn-sm btn-primary" onclick="setAccountSearchScope('all')">${escapeHtml(translateAppTextLocal('全部账号'))}</button>
                            <button type="button" class="btn btn-sm btn-ghost" onclick="clearAccountListFilters()">${escapeHtml(translateAppTextLocal('清除筛选'))}</button>
                        </div>
                    `;
                }
                const emptySummary = buildAccountListSummaryHtml(0);
                container.innerHTML = `
                    ${emptySummary}
                    <div class="empty-state">
                        <span class="empty-icon">📭</span>
                        <p>${emptyMessage}</p>
                        ${emptyActions}
                    </div>
                `;
                const selectAllCheckbox = document.getElementById('selectAllCheckbox');
                if (selectAllCheckbox) {
                    selectAllCheckbox.checked = false;
                    selectAllCheckbox.indeterminate = selectedAccountIds.size > 0;
                }
                updateBatchActionBar();
                return;
            }

            const pagination = getAccountListMeta();
            const totalAccounts = Number(pagination.total_count || 0);
            const totalPages = Number(pagination.total_pages || 0);
            currentAccountPage = Number(pagination.page || 1);
            const pageAccounts = safeAccounts;
            const showGroupBadge = accountSearchScope === 'all';
            const avatarGradients = [
                ['#B85C38', '#E8734A'],  // 砖红→珊瑚
                ['#3A7D44', '#5BAF6A'],  // 翠绿→嫩绿
                ['#2E6B8A', '#4BA3CC'],  // 海蓝→天蓝
                ['#8B5E3C', '#C8963E'],  // 棕→琥珀金
                ['#7B4F9B', '#B77FD8'],  // 紫罗兰→薰衣草
                ['#C75050', '#E88080'],  // 朱红→浅红
                ['#2C7A7B', '#4DC9C9'],  // 青绿→薄荷
                ['#9B6B3E', '#D4A65A'],  // 赭石→沙金
            ];

            container.innerHTML = pageAccounts.map((acc, index) => {
                const isChecked = selectedAccountIds.has(acc.id);
                const initial = (acc.email || '?')[0].toUpperCase();
                const supportsTokenRefresh = isRefreshableOutlookAccount(acc);
                const isFailed = supportsTokenRefresh && acc.last_refresh_status === 'failed';
                const defaultMethodLabel = supportsTokenRefresh ? 'Graph' : 'IMAP';
                const gradient = avatarGradients[index % avatarGradients.length];
                const providerLabel = getProviderLabel(acc.provider || acc.account_type || 'outlook');
                const providerTagHtml = `<span class="account-provider-tag">${escapeHtml(providerLabel)}</span>`;
                const aliasCountHtml = buildAccountAliasCountBadge(acc);
                const groupBadgeHtml = showGroupBadge
                    ? `<div class="account-group-badge" title="${escapeHtml(acc.group_name || '')}">
                            <span class="group-color-dot" style="background-color:${escapeHtml(acc.group_color || '#666')}"></span>
                            <span>${escapeHtml(acc.group_name || translateAppTextLocal('未分组'))}</span>
                       </div>`
                    : '';
                const notificationEnabled = acc.notification_enabled !== undefined
                    ? !!acc.notification_enabled
                    : !!acc.telegram_push_enabled;
                const isCfPoolAccount = String(acc.provider || '').toLowerCase() === 'cloudflare_temp_mail';

                let tokenBadge = `<span class="badge badge-gray">IMAP</span>`;
                if (supportsTokenRefresh) {
                    tokenBadge = `<span class="badge badge-gray">– ${translateAppTextLocal('未知')}</span>`;
                    if (acc.token_status === 'valid') {
                        tokenBadge = `<span class="badge badge-green">✓ ${translateAppTextLocal('有效')}</span>`;
                    } else if (acc.token_status === 'invalid' || acc.token_status === 'expired') {
                        tokenBadge = `<span class="badge badge-red">✗ ${translateAppTextLocal('过期')}</span>`;
                    } else if (acc.token_status === 'expiring') {
                        tokenBadge = `<span class="badge badge-gold">⚠ ${translateAppTextLocal('即将过期')}</span>`;
                    }
                }

                let passwordRowHtml = '';
                if (acc.has_password) {
                    passwordRowHtml = `
                        <div class="account-password-row" id="password-row-${acc.id}">
                            <span class="pw-mask">••••••••</span>
                            <button class="btn-icon pw-btn" onclick="event.stopPropagation(); revealPassword(${acc.id})" title="${escapeHtml(translateAppTextLocal('显示密码'))}">👁️</button>
                            <button class="btn-icon pw-btn" onclick="event.stopPropagation(); copyPassword(${acc.id})" title="${escapeHtml(translateAppTextLocal('复制密码'))}">📋</button>
                            <button class="btn-icon pw-btn" onclick="event.stopPropagation(); copyAccountAndPassword(${acc.id}, '${escapeJs(acc.email)}')" title="${escapeHtml(translateAppTextLocal('复制账密'))}">🔗</button>
                        </div>
                    `;
                }

                const groupIdAttr = (acc.group_id === null || acc.group_id === undefined || acc.group_id === '')
                    ? 'null'
                    : String(Number(acc.group_id));
                return `
                <div class="account-card ${currentAccount === acc.email ? 'active' : ''}"
                     onclick="openAccountFromList('${escapeJs(acc.email)}', ${groupIdAttr})">
                    <div class="account-token-badge">${tokenBadge}</div>
                    <div class="account-card-top">
                        <input type="checkbox" class="account-select-checkbox" value="${acc.id}"
                               ${isChecked ? 'checked' : ''}
                               onclick="event.stopPropagation()"
                               onchange="event.stopPropagation(); handleAccountSelectionChange(${acc.id}, this.checked)">
                        <div class="account-avatar" style="background: linear-gradient(135deg, ${gradient[0]}, ${gradient[1]})">${initial}</div>
                        <div class="account-info">
                            <div class="account-email"
                                 onclick="event.stopPropagation(); copyEmail('${escapeJs(acc.email)}')"
                                 title="${escapeHtml(translateAppTextLocal('点击复制邮箱地址'))}"
                                 style="${isFailed ? 'color:var(--clr-danger);' : ''}cursor:pointer;">
                                ${escapeHtml(acc.email)}
                            </div>
                            ${passwordRowHtml}
                            ${groupBadgeHtml}
                            ${acc.remark && acc.remark.trim() ? `<div style="font-size:0.72rem;color:var(--text-muted);margin-top:2px;">📝 ${escapeHtml(translateAppTextLocal('备注'))}: ${escapeHtml(acc.remark)}</div>` : ''}
                            <div style="display:flex;flex-wrap:wrap;gap:3px;margin-top:3px;">
                                ${providerTagHtml}
                                ${aliasCountHtml}
                                ${(acc.tags || []).map(tag => `<span class="tag" style="background-color:${tag.color};color:white;">${escapeHtml(tag.name)}</span>`).join('')}
                                ${notificationEnabled ? `<span class="tag tg-push-tag" onclick="event.stopPropagation(); toggleTelegramPush(${acc.id}, false)" title="${escapeHtml(translateAppTextLocal('点击关闭该邮箱通知参与'))}">🔔 ${escapeHtml(translateAppTextLocal('通知'))}</span>` : ''}
                            </div>
                        </div>
                    </div>
                    <div class="account-card-bottom">
                        <div class="account-meta">
                            <span class="account-api-tag">${acc.method || defaultMethodLabel}</span>
                            <span>🕐 ${formatRelativeTime(acc.last_refresh_at)}</span>
                            ${isFailed ? `
                                <button class="btn btn-sm btn-danger" onclick="event.stopPropagation(); showRefreshError(${acc.id}, '${escapeJs(acc.last_refresh_error || '未知错误')}', '${escapeJs(acc.email)}', '${escapeJs(acc.account_type || 'outlook')}', '${escapeJs(acc.provider || 'outlook')}')" style="padding:1px 6px;font-size:0.65rem;">${escapeHtml(translateAppTextLocal('查看错误'))}</button>
                                <button class="btn btn-sm btn-primary" onclick="event.stopPropagation(); (async () => { await retrySingleAccount(${acc.id}, '${escapeJs(acc.email)}'); if (typeof loadAccountList === 'function') { loadAccountList(true); } else if (typeof loadAccountsByGroup === 'function' && currentGroupId) { loadAccountsByGroup(currentGroupId, true); } })()" style="padding:1px 6px;font-size:0.65rem;">${escapeHtml(translateAppTextLocal('重试'))}</button>
                            ` : ''}
                        </div>
                        <div class="account-actions">
                            <button class="btn-icon ${notificationEnabled ? 'tg-push-active' : ''}" onclick="event.stopPropagation(); toggleTelegramPush(${acc.id}, ${!notificationEnabled})" title="${escapeHtml(translateAppTextLocal(notificationEnabled ? '该邮箱通知参与（已开启）' : '开启该邮箱通知参与'))}">🔔</button>
                            <button class="btn btn-sm btn-accent" onclick="event.stopPropagation(); copyVerificationInfo('${escapeJs(acc.email)}', this)" title="${escapeHtml(translateAppTextLocal('验证码'))}" style="font-size:0.72rem;padding:2px 8px;">🔑 ${escapeHtml(translateAppTextLocal('验证码'))}</button>
                            <button class="btn-icon" onclick="event.stopPropagation(); showEmailAliasesModal('${escapeJs(acc.email)}')" title="${escapeHtml(translateAppTextLocal('分裂邮箱'))}"> cons</button>
                            <button class="btn-icon" onclick="event.stopPropagation(); copyEmail('${escapeJs(acc.email)}')" title="${escapeHtml(translateAppTextLocal('复制'))}">📋</button>
                            ${isCfPoolAccount
                                ? `<button class="btn-icon" disabled title="${escapeHtml(translateAppTextLocal('邮箱池管理的账号不支持编辑'))}" style="opacity:0.3;cursor:not-allowed;">✏️</button>`
                                : `<button class="btn-icon" onclick="event.stopPropagation(); showEditAccountModal(${acc.id})" title="${escapeHtml(translateAppTextLocal('编辑'))}">✏️</button>`
                            }
                            ${isCfPoolAccount
                                ? `<button class="btn-icon" disabled title="${escapeHtml(translateAppTextLocal('邮箱池管理的账号不支持手动删除'))}" style="opacity:0.3;cursor:not-allowed;color:var(--clr-danger);">🗑️</button>`
                                : `<button class="btn-icon" onclick="event.stopPropagation(); deleteAccount(${acc.id}, '${escapeJs(acc.email)}')" title="${escapeHtml(translateAppTextLocal('删除'))}" style="color:var(--clr-danger);">🗑️</button>`
                            }
                        </div>
                    </div>
                </div>
            `}).join('');

            const summaryHtml = buildAccountListSummaryHtml(totalAccounts);
            if (summaryHtml) {
                container.insertAdjacentHTML('afterbegin', summaryHtml);
            }

            // 多页时始终显示翻页；无顶栏摘要时单页筛选也显示匹配数
            if (totalPages > 1) {
                const paginationEl = document.createElement('div');
                paginationEl.className = 'account-pagination';
                paginationEl.innerHTML = `
                    <button class="page-btn page-btn-prev"
                            onclick="goToAccountPage(${currentAccountPage - 1})"
                            ${currentAccountPage <= 1 ? 'disabled' : ''}>
                        ◀
                    </button>
                    <span class="page-info">
                        ${currentAccountPage} / ${totalPages} ${translateAppTextLocal('页')}${summaryHtml ? '' : ` &nbsp;·&nbsp; ${translateAppTextLocal('共')} ${totalAccounts} ${translateAppTextLocal('个账号')}`}
                    </span>
                    <button class="page-btn page-btn-next"
                            onclick="goToAccountPage(${currentAccountPage + 1})"
                            ${currentAccountPage >= totalPages ? 'disabled' : ''}>
                        ▶
                    </button>
                `;
                container.appendChild(paginationEl);
            }

            updateSelectAllCheckbox();
            updateBatchActionBar();
            // 如果有正在运行的轮询，重新显示轮询指示器（账号列表重渲染后会丢失绿点）
            if (typeof reapplyAllPollUI === 'function') {
                reapplyAllPollUI();
            }
        }

        function hasActiveAccountListFilters() {
            return !!(
                currentAccountSearchQuery ||
                currentAccountStatusFilter ||
                getSelectedTagFilterIds().length ||
                accountSearchScope === 'all'
            );
        }

        function buildAccountListSummaryHtml(totalCount) {
            if (!hasActiveAccountListFilters()) return '';

            const parts = [];
            parts.push(accountSearchScope === 'all'
                ? translateAppTextLocal('全部账号')
                : translateAppTextLocal('当前分组'));
            parts.push(`${translateAppTextLocal('匹配')} ${Number(totalCount || 0)} ${translateAppTextLocal('个账号')}`);

            if (currentAccountSearchQuery) {
                parts.push(`${translateAppTextLocal('关键词')} “${currentAccountSearchQuery}”`);
            }
            if (currentAccountStatusFilter) {
                const statusLabels = {
                    active: translateAppTextLocal('正常'),
                    inactive: translateAppTextLocal('失效'),
                    has_alias: translateAppTextLocal('有分裂'),
                    no_alias: translateAppTextLocal('无分裂'),
                    synced: translateAppTextLocal('已刷新'),
                    unsynced: translateAppTextLocal('未刷新'),
                };
                parts.push(statusLabels[currentAccountStatusFilter] || currentAccountStatusFilter);
            }
            const tagCount = getSelectedTagFilterIds().length;
            if (tagCount > 0) {
                parts.push(`${tagCount} ${translateAppTextLocal('个标签')}`);
            }

            const hint = accountSearchScope === 'all'
                ? `<span class="account-list-summary-hint">${escapeHtml(translateAppTextLocal('点击账号可定位到所属分组'))}</span>`
                : '';

            return `
                <div class="account-list-summary" role="status">
                    <div class="account-list-summary-text">
                        <span>${parts.map((part) => escapeHtml(part)).join(' · ')}</span>
                        ${hint}
                    </div>
                    <button type="button" class="btn btn-sm btn-ghost account-list-summary-clear" onclick="clearAccountListFilters()">
                        ${escapeHtml(translateAppTextLocal('清除筛选'))}
                    </button>
                </div>
            `;
        }

        function clearAccountListFilters() {
            currentAccountSearchQuery = '';
            currentAccountStatusFilter = '';
            currentAccountPage = 1;

            const searchInput = document.getElementById('globalSearch');
            if (searchInput) searchInput.value = '';
            updateAccountSearchClearButton();

            document.querySelectorAll('.status-filter-btn').forEach(btn => btn.classList.remove('active'));
            const allStatusBtn = document.querySelector('.status-filter-btn[data-status=""]')
                || document.querySelector('.status-filter-btn[data-status="all"]');
            if (allStatusBtn) allStatusBtn.classList.add('active');

            document.querySelectorAll('.tag-filter-checkbox:checked').forEach(cb => {
                cb.checked = false;
            });

            if (accountSearchScope === 'all') {
                accountSearchScope = 'group';
                const scopeSelect = document.getElementById('accountSearchScope');
                if (scopeSelect) scopeSelect.value = 'group';
            }

            if (currentGroupId) {
                loadAccountList(true, 1);
            } else {
                const container = document.getElementById('accountList');
                if (container) {
                    container.innerHTML = `
                        <div class="empty-state">
                            <span class="empty-icon">📁</span>
                            <p>${translateAppTextLocal('请从左侧选择一个分组')}</p>
                        </div>
                    `;
                }
            }
        }

        // 跳转到指定账号分页
        function goToAccountPage(page) {
            if (accountSearchScope !== 'all' && !currentGroupId) return;
            const totalPages = Number(getAccountListMeta().total_pages || 0);
            if (page < 1 || page > totalPages) return;
            currentAccountPage = page;
            loadAccountList(false, page);
            const containers = [
                document.getElementById('accountList'),
                document.getElementById('compactAccountList')
            ].filter(Boolean);
            containers.forEach(container => {
                container.scrollTop = 0;
            });
        }

        // 排序相关变量
        let currentSortBy = 'refresh_time';
        let currentSortOrder = 'asc';

        // 账号列表分页状态
        let currentAccountPage = 1;
        const ACCOUNT_PAGE_SIZE = 50;
        let currentAccountSearchQuery = '';
        let currentAccountStatusFilter = '';
        const accountListMetaCache = {};

        function getSelectedTagFilterIds() {
            return Array.from(document.querySelectorAll('.tag-filter-checkbox:checked'))
                .map(cb => parseInt(cb.value, 10))
                .filter(tagId => Number.isInteger(tagId) && tagId > 0);
        }

        function buildAccountListQueryKey(groupId, page = currentAccountPage) {
            const params = new URLSearchParams();
            if (groupId !== null && groupId !== undefined) {
                params.set('group_id', String(groupId));
            }
            params.set('page', String(page || 1));
            params.set('page_size', String(ACCOUNT_PAGE_SIZE));
            params.set('sort_by', currentSortBy);
            params.set('sort_order', currentSortOrder);

            if (currentAccountStatusFilter === 'active' || currentAccountStatusFilter === 'inactive') {
                params.set('status', currentAccountStatusFilter);
            } else if (currentAccountStatusFilter === 'has_alias') {
                params.set('alias_filter', 'has');
            } else if (currentAccountStatusFilter === 'no_alias') {
                params.set('alias_filter', 'none');
            } else if (currentAccountStatusFilter === 'synced') {
                params.set('alias_filter', 'synced');
            } else if (currentAccountStatusFilter === 'unsynced') {
                params.set('alias_filter', 'unsynced');
            }

            const normalizedSearch = String(currentAccountSearchQuery || '').trim();
            if (normalizedSearch) {
                params.set('search', normalizedSearch);
            }

            getSelectedTagFilterIds().forEach(tagId => {
                params.append('tag_id', String(tagId));
            });

            return params.toString();
        }

        function getAccountListMeta(groupId = currentGroupId) {
            const cacheKey = getAccountListCacheKey(groupId);
            const cachedMeta = accountListMetaCache[cacheKey];
            if (cachedMeta) {
                return cachedMeta;
            }
            const fallbackAccounts = Array.isArray(accountsCache[cacheKey]) ? accountsCache[cacheKey] : [];
            return {
                page: currentAccountPage,
                page_size: ACCOUNT_PAGE_SIZE,
                total_count: fallbackAccounts.length,
                total_pages: fallbackAccounts.length > 0 ? 1 : 0,
                queryKey: ''
            };
        }

        function updateAccountListCache(groupId, accounts, pagination, queryKey) {
            const cacheKey = (groupId === GLOBAL_ACCOUNT_CACHE_KEY || accountSearchScope === 'all')
                ? GLOBAL_ACCOUNT_CACHE_KEY
                : groupId;
            const safeAccounts = Array.isArray(accounts) ? accounts : [];
            const safePagination = pagination && typeof pagination === 'object'
                ? pagination
                : { page: currentAccountPage || 1, page_size: ACCOUNT_PAGE_SIZE, total_count: safeAccounts.length, total_pages: safeAccounts.length > 0 ? 1 : 0 };

            accountsCache[cacheKey] = safeAccounts;
            accountListMetaCache[cacheKey] = {
                page: Number(safePagination.page || 1),
                page_size: Number(safePagination.page_size || ACCOUNT_PAGE_SIZE),
                total_count: Number(safePagination.total_count || 0),
                total_pages: Number(safePagination.total_pages || 0),
                queryKey
            };
            currentAccountPage = Number(accountListMetaCache[cacheKey].page || 1);
        }

        // 排序账号列表
        function sortAccounts(sortBy) {
            // 如果点击同一个排序按钮，切换排序顺序
            if (currentSortBy === sortBy) {
                currentSortOrder = currentSortOrder === 'asc' ? 'desc' : 'asc';
            } else {
                currentSortBy = sortBy;
                // 添加时间默认最新在上；刷新时间默认最久未刷新在上；邮箱名默认升序
                currentSortOrder = sortBy === 'created_at' ? 'desc' : 'asc';
            }

            // 更新按钮状态
            document.querySelectorAll('.sort-btn').forEach(btn => {
                btn.classList.remove('active');
            });

            const activeBtn = document.querySelector(`[data-sort="${sortBy}"]`);
            if (activeBtn) {
                activeBtn.classList.add('active');
            }

            if (accountSearchScope === 'all' || currentGroupId) {
                currentAccountPage = 1;  // 排序时重置到第 1 页
                loadAccountList(true, 1);
            }
        }

        function filterAccountsByStatus(status) {
            if (currentAccountStatusFilter === status) return;
            currentAccountStatusFilter = status;

            document.querySelectorAll('.status-filter-btn').forEach(btn => {
                btn.classList.remove('active');
            });
            const activeBtn = document.querySelector(`.status-filter-btn[data-status="${status}"]`);
            if (activeBtn) activeBtn.classList.add('active');

            if (accountSearchScope === 'all' || currentGroupId) {
                currentAccountPage = 1;
                loadAccountList(true, 1);
            }
        }

        async function retryFailedInCurrentGroup() {
            const cacheKey = getAccountListCacheKey(currentGroupId);
            if (!Array.isArray(accountsCache[cacheKey])) return;

            const failedIds = accountsCache[cacheKey]
                .filter(acc => isRefreshableOutlookAccount(acc) && acc.last_refresh_status === 'failed')
                .map(acc => acc.id);

            if (!failedIds.length) {
                showToast(translateAppTextLocal('当前页面没有刷新失败的账号'), 'info');
                return;
            }

            await batchRefreshSelected(failedIds);
            await loadAccountList(true);
        }

        // 应用筛选和排序
        function applyFiltersAndSort(accounts) {
            return Array.isArray(accounts) ? [...accounts] : [];
        }

        // Tag Filter Change Handler
        function handleTagFilterChange() {
            if (accountSearchScope === 'all' || currentGroupId) {
                currentAccountPage = 1;  // 标签过滤时重置到第 1 页
                loadAccountList(true, 1);
            }
        }

        // 防抖函数
        function debounce(func, wait) {
            let timeout;
            return function (...args) {
                clearTimeout(timeout);
                timeout = setTimeout(() => func.apply(this, args), wait);
            };
        }

        function updateAccountSearchClearButton() {
            const clearBtn = document.getElementById('accountSearchClearBtn');
            const searchInput = document.getElementById('globalSearch');
            if (!clearBtn || !searchInput) return;
            const hasValue = String(searchInput.value || '').trim().length > 0;
            clearBtn.style.display = hasValue ? 'inline-flex' : 'none';
        }

        function setAccountSearchScope(scope) {
            const nextScope = scope === 'all' ? 'all' : 'group';
            if (accountSearchScope === nextScope) return;
            accountSearchScope = nextScope;
            const scopeSelect = document.getElementById('accountSearchScope');
            if (scopeSelect && scopeSelect.value !== accountSearchScope) {
                scopeSelect.value = accountSearchScope;
            }
            currentAccountPage = 1;
            if (accountSearchScope === 'group' && !currentGroupId) {
                const container = document.getElementById('accountList');
                if (container) {
                    container.innerHTML = `
                        <div class="empty-state">
                            <span class="empty-icon">📁</span>
                            <p>${translateAppTextLocal('请从左侧选择一个分组')}</p>
                        </div>
                    `;
                }
                return;
            }
            loadAccountList(true, 1);
        }

        function clearAccountSearch() {
            const searchInput = document.getElementById('globalSearch');
            if (searchInput) searchInput.value = '';
            currentAccountSearchQuery = '';
            updateAccountSearchClearButton();
            currentAccountPage = 1;
            if (accountSearchScope === 'all' || currentGroupId) {
                loadAccountList(true, 1);
            }
        }

        // 全局搜索函数（支持当前分组 / 全部账号）
        async function searchAccounts(query) {
            const container = document.getElementById('accountList');
            currentAccountSearchQuery = String(query || '').trim();
            updateAccountSearchClearButton();

            if (accountSearchScope !== 'all' && !currentGroupId) {
                if (container) {
                    container.innerHTML = `
                        <div class="empty-state">
                            <span class="empty-icon">📁</span>
                            <p>${translateAppTextLocal('请先选择分组')}</p>
                        </div>
                    `;
                }
                return;
            }

            currentAccountPage = 1;
            try {
                await loadAccountList(true, 1);
            } catch (error) {
                console.error('搜索失败:', error);
                if (container) {
                    container.innerHTML = `<div class="empty-state"><p>${translateAppTextLocal('搜索失败，请重试')}</p></div>`;
                }
            }
        }

        // 更新分组下拉选择框
        function updateGroupSelects() {
            const selects = ['importGroupSelect', 'editGroupSelect'];
            selects.forEach(selectId => {
                const select = document.getElementById(selectId);
                if (select) {
                    const currentValue = select.value;
                    // 过滤掉临时邮箱分组（导入邮箱时不能选择临时邮箱分组）
                    const filteredGroups = selectId === 'importGroupSelect'
                        ? groups.filter(g => g.name !== '临时邮箱')
                        : groups;

                    select.innerHTML = filteredGroups.map(g =>
                        `<option value="${g.id}">${escapeHtml(g.name)}</option>`
                    ).join('');
                    // 恢复之前的选择
                    if (currentValue && filteredGroups.find(g => g.id === parseInt(currentValue))) {
                        select.value = currentValue;
                    } else if (currentGroupId && filteredGroups.find(g => g.id === currentGroupId)) {
                        select.value = currentGroupId;
                    }
                }
            });
        }

        // 显示添加分组模态框
        function showAddGroupModal() {
            editingGroupId = null;
            document.getElementById('groupModalTitle').textContent = translateAppTextLocal('添加分组');
            document.getElementById('groupName').value = '';
            document.getElementById('groupDescription').value = '';
            selectedColor = '#B85C38';
            document.querySelectorAll('.color-option').forEach(o => {
                o.classList.toggle('selected', o.dataset.color === selectedColor);
            });
            document.getElementById('customColorInput').value = selectedColor;
            document.getElementById('customColorHex').value = selectedColor;
            document.getElementById('groupProxyUrl').value = '';
            document.getElementById('groupVerificationCodeLength').value = '6-6';
            document.getElementById('groupVerificationCodeRegex').value = '';
            document.getElementById('addGroupModal').classList.add('show');
        }

        // 隐藏添加分组模态框
        function hideAddGroupModal() {
            document.getElementById('addGroupModal').classList.remove('show');
        }

        // 编辑分组
        async function editGroup(groupId) {
            try {
                const response = await fetch(`/api/groups/${groupId}`);
                const data = await response.json();

                if (data.success) {
                    editingGroupId = groupId;
                    document.getElementById('groupModalTitle').textContent = translateAppTextLocal('编辑分组');
                    document.getElementById('groupName').value = data.group.name;
                    document.getElementById('groupDescription').value = data.group.description || '';
                    selectedColor = data.group.color || '#B85C38';

                    // 检查是否是预设颜色
                    let isPresetColor = false;
                    document.querySelectorAll('.color-option').forEach(o => {
                        if (o.dataset.color === selectedColor) {
                            o.classList.add('selected');
                            isPresetColor = true;
                        } else {
                            o.classList.remove('selected');
                        }
                    });

                    // 更新自定义颜色输入框
                    document.getElementById('customColorInput').value = selectedColor;
                    document.getElementById('customColorHex').value = selectedColor;

                    // 填充代理设置
                    document.getElementById('groupProxyUrl').value = data.group.proxy_url || '';

                    // 回填验证码提取策略
                    document.getElementById('groupVerificationCodeLength').value = data.group.verification_code_length || '6-6';
                    document.getElementById('groupVerificationCodeRegex').value = data.group.verification_code_regex || '';

                    document.getElementById('addGroupModal').classList.add('show');
                }
            } catch (error) {
                showToast(translateAppTextLocal('加载分组信息失败'), 'error');
            }
        }

        // 保存分组
        async function saveGroup() {
            const name = document.getElementById('groupName').value.trim();
            const description = document.getElementById('groupDescription').value.trim();
            const verificationCodeLength = document.getElementById('groupVerificationCodeLength')?.value?.trim() || '6-6';
            const verificationCodeRegex = document.getElementById('groupVerificationCodeRegex')?.value?.trim() || '';

            if (!name) {
                showToast(translateAppTextLocal('请输入分组名称'), 'error');
                return;
            }

            try {
                const url = editingGroupId ? `/api/groups/${editingGroupId}` : '/api/groups';
                const method = editingGroupId ? 'PUT' : 'POST';

                const response = await fetch(url, {
                    method: method,
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        name,
                        description,
                        color: selectedColor,
                        proxy_url: document.getElementById('groupProxyUrl').value.trim(),
                        verification_code_length: verificationCodeLength,
                        verification_code_regex: verificationCodeRegex
                    })
                });

                const data = await response.json();

                if (data.success) {
                    showToast(pickApiMessage(data, data.message, 'Group saved successfully'), 'success');
                    hideAddGroupModal();
                    loadGroups();
                } else {
                    handleApiError(data, '保存分组失败');
                }
            } catch (error) {
                showToast(translateAppTextLocal('保存失败'), 'error');
            }
        }

        // 删除分组
        async function deleteGroup(groupId) {
            if (!confirm('确定要删除该分组吗？分组下的邮箱将移至默认分组。')) {
                return;
            }

            try {
                const response = await fetch(`/api/groups/${groupId}`, { method: 'DELETE' });
                const data = await response.json();

                if (data.success) {
                    showToast(pickApiMessage(data, data.message, 'Group deleted successfully'), 'success');
                    // 清除缓存
                    delete accountsCache[groupId];
                    // 如果删除的是当前选中的分组，切换到默认分组
                    if (currentGroupId === groupId) {
                        currentGroupId = 1;
                    }
                    loadGroups();
                } else {
                    handleApiError(data, '删除分组失败');
                }
            } catch (error) {
                showToast(translateAppTextLocal('删除失败'), 'error');
            }
        }

        // ==================== 全选功能 ====================

        // 全选/取消全选账号（当前分组）
        function toggleSelectAll() {
            const selectAllCheckbox = mailboxViewMode === 'compact'
                ? document.getElementById('compactSelectAllCheckbox')
                : document.getElementById('selectAllCheckbox');

            if (selectAllCheckbox.checked) {
                selectAllAccounts();
            } else {
                unselectAllAccounts();
            }
        }

        // 全选当前分组所有账号
        function selectAllAccounts() {
            const checkboxes = getActiveAccountCheckboxes();
            checkboxes.forEach(cb => {
                cb.checked = true;
                selectedAccountIds.add(parseInt(cb.value));
            });
            updateBatchActionBar();
            updateSelectAllCheckbox();
        }

        // 取消全选当前分组
        function unselectAllAccounts() {
            const checkboxes = getActiveAccountCheckboxes();
            checkboxes.forEach(cb => {
                cb.checked = false;
                selectedAccountIds.delete(parseInt(cb.value));
            });
            updateBatchActionBar();
            updateSelectAllCheckbox();
        }

        // 更新全选复选框状态（基于当前分组）
        function updateSelectAllCheckbox() {
            const checkboxes = getActiveAccountCheckboxes();
            const checkedCount = checkboxes.filter(cb => cb.checked).length;
            const selectAllCheckboxes = [
                document.getElementById('selectAllCheckbox'),
                document.getElementById('compactSelectAllCheckbox')
            ].filter(Boolean);

            selectAllCheckboxes.forEach(selectAllCheckbox => {
                if (checkboxes.length === 0) {
                    selectAllCheckbox.checked = false;
                    selectAllCheckbox.indeterminate = selectedAccountIds.size > 0;
                } else if (checkedCount === 0) {
                    selectAllCheckbox.checked = false;
                    selectAllCheckbox.indeterminate = selectedAccountIds.size > 0;
                } else if (checkedCount === checkboxes.length) {
                    selectAllCheckbox.checked = true;
                    selectAllCheckbox.indeterminate = false;
                } else {
                    selectAllCheckbox.checked = false;
                    selectAllCheckbox.indeterminate = true;
                }
            });
        }

        // ==================== 验证码复制功能 ====================

        function rerenderAccountCaches() {
            const cacheKey = getAccountListCacheKey(currentGroupId);
            if (!Array.isArray(accountsCache[cacheKey])) {
                return;
            }

            renderAccountList(accountsCache[cacheKey]);
            if (typeof renderCompactAccountList === 'function') {
                renderCompactAccountList(accountsCache[cacheKey]);
            }
            if (typeof renderCompactGroupStrip === 'function') {
                renderCompactGroupStrip(groups, currentGroupId);
            }
            updateSelectAllCheckbox();
            updateBatchActionBar();
        }

        function syncAccountSummaryToAccountCache(email, accountSummary) {
            const normalizedEmail = String(email || '').trim().toLowerCase();
            if (!normalizedEmail || !accountSummary || typeof accountSummary !== 'object') {
                return false;
            }

            let updated = false;
            Object.values(accountsCache).forEach(accounts => {
                if (!Array.isArray(accounts)) {
                    return;
                }

                accounts.forEach(account => {
                    if (!account || String(account.email || '').trim().toLowerCase() !== normalizedEmail) {
                        return;
                    }

                    account.latest_email_subject = String(accountSummary.latest_email_subject || '');
                    account.latest_email_from = String(accountSummary.latest_email_from || '');
                    account.latest_email_folder = String(accountSummary.latest_email_folder || '');
                    account.latest_email_received_at = String(accountSummary.latest_email_received_at || '');
                    account.latest_verification_code = String(accountSummary.latest_verification_code || '');
                    account.latest_verification_folder = String(accountSummary.latest_verification_folder || '');
                    account.latest_verification_received_at = String(accountSummary.latest_verification_received_at || '');
                    updated = true;
                });
            });

            if (updated) {
                rerenderAccountCaches();
            }

            return updated;
        }

        function syncExtractedVerificationToAccountCache(email, verificationData, accountSummary = null) {
            if (syncAccountSummaryToAccountCache(email, accountSummary)) {
                return true;
            }

            const normalizedEmail = String(email || '').trim().toLowerCase();
            const verificationCode = String(
                verificationData?.verification_code || verificationData?.verificationCode || ''
            ).trim();

            if (!normalizedEmail || !verificationCode) {
                return false;
            }

            let updated = false;
            Object.values(accountsCache).forEach(accounts => {
                if (!Array.isArray(accounts)) {
                    return;
                }

                accounts.forEach(account => {
                    if (!account || String(account.email || '').trim().toLowerCase() !== normalizedEmail) {
                        return;
                    }

                    account.latest_verification_code = verificationCode;
                    if (verificationData?.folder) {
                        account.latest_verification_folder = String(verificationData.folder);
                    }
                    if (verificationData?.received_at) {
                        account.latest_verification_received_at = String(verificationData.received_at);
                    }
                    if (verificationData?.subject && !account.latest_email_subject) {
                        account.latest_email_subject = String(verificationData.subject);
                    }
                    updated = true;
                });
            });

            if (!updated) {
                return false;
            }
            rerenderAccountCaches();

            return true;
        }

        // 复制验证信息到剪贴板
        const verificationCopyInFlight = new Set();

        function buildVerificationExtractEndpoint(email, options = {}) {
            const normalizedSource = String(options?.source || '').trim().toLowerCase();
            const field = String(options?.field || 'any').trim().toLowerCase();
            const query = field && field !== 'any' ? `?field=${encodeURIComponent(field)}` : '';
            if (normalizedSource === 'temp' || normalizedSource === 'temp-mail' || normalizedSource === 'temp_mail') {
                return `/api/temp-emails/${encodeURIComponent(email)}/verification${query}`;
            }
            return `/api/emails/${encodeURIComponent(email)}/verification${query}`;
        }

        async function tryFallbackVerificationExtraction(options = {}) {
            if (typeof options.fallbackExtractor !== 'function') {
                return null;
            }

            try {
                const fallbackResult = await options.fallbackExtractor();
                if (!fallbackResult || !fallbackResult.formatted) {
                    return null;
                }
                return fallbackResult;
            } catch (fallbackError) {
                console.error('本地兜底提取失败:', fallbackError);
                return null;
            }
        }

        async function copyVerificationInfo(email, buttonElement, options = {}) {
            const requestKey = String(email || '').trim().toLowerCase();
            if (!requestKey || verificationCopyInFlight.has(requestKey)) {
                return false;
            }
            verificationCopyInFlight.add(requestKey);

            // 禁用按钮并显示加载状态
            const originalContent = buttonElement.innerHTML;
            buttonElement.disabled = true;
            buttonElement.innerHTML = '⏳';
            buttonElement.style.opacity = '0.6';
            buttonElement.style.cursor = 'wait';

            try {
                const response = await fetch(buildVerificationExtractEndpoint(email, options));
                const data = await response.json();

                if (data.success && data.data && data.data.formatted) {
                    await copyToClipboard(data.data.formatted);
                    syncExtractedVerificationToAccountCache(email, data.data, data.account_summary || null);
                    if (typeof window.notifyOverviewDataChanged === 'function') {
                        window.notifyOverviewDataChanged(['summary', 'verification', 'activity'], 'verification-extracted');
                    }
                    showToast(
                        getUiLanguage() === 'en'
                            ? `Copied: ${data.data.formatted}`
                            : `已复制: ${data.data.formatted}`,
                        'success'
                    );
                    // 成功状态
                    buttonElement.innerHTML = '✅';
                    buttonElement.style.opacity = '1';
                    return true;
                } else {
                    const fallbackResult = await tryFallbackVerificationExtraction(options);
                    if (fallbackResult) {
                        await copyToClipboard(
                            fallbackResult.copyText || fallbackResult.verification_code || fallbackResult.verification_link || fallbackResult.formatted
                        );
                        const copiedValue = fallbackResult.displayValue || fallbackResult.verification_code || fallbackResult.verification_link || fallbackResult.formatted;
                        showToast(
                            getUiLanguage() === 'en'
                                ? `Copied from current email: ${copiedValue}`
                                : `已从当前邮件兜底复制: ${copiedValue}`,
                            'warning'
                        );
                        buttonElement.innerHTML = '✅';
                        buttonElement.style.opacity = '1';
                        return true;
                    }

                    const errorMsg = window.resolveApiErrorMessage
                        ? window.resolveApiErrorMessage(data.error || data, '未找到验证码或链接', 'No verification code or link was found')
                        : (data.error?.message || data.error || '未找到验证码或链接');
                    showToast(errorMsg, 'error');
                    // 失败状态
                    buttonElement.innerHTML = '❌';
                    buttonElement.style.opacity = '1';
                    return false;
                }
            } catch (error) {
                console.error('提取验证码失败:', error);
                const fallbackResult = await tryFallbackVerificationExtraction(options);
                if (fallbackResult) {
                    await copyToClipboard(
                        fallbackResult.copyText || fallbackResult.verification_code || fallbackResult.verification_link || fallbackResult.formatted
                    );
                    const copiedValue = fallbackResult.displayValue || fallbackResult.verification_code || fallbackResult.verification_link || fallbackResult.formatted;
                    showToast(
                        getUiLanguage() === 'en'
                            ? `Copied from current email: ${copiedValue}`
                            : `已从当前邮件兜底复制: ${copiedValue}`,
                        'warning'
                    );
                    buttonElement.innerHTML = '✅';
                    buttonElement.style.opacity = '1';
                    return true;
                }
                showToast(translateAppTextLocal('网络错误，请重试'), 'error');
                // 失败状态
                buttonElement.innerHTML = '❌';
                buttonElement.style.opacity = '1';
                return false;
            } finally {
                verificationCopyInFlight.delete(requestKey);
                // 延迟恢复按钮状态
                setTimeout(() => {
                    buttonElement.disabled = false;
                    buttonElement.innerHTML = originalContent;
                    buttonElement.style.cursor = 'pointer';
                }, 1500);
            }
        }

        // 复制文本到剪贴板
        async function copyToClipboard(text) {
            try {
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    await navigator.clipboard.writeText(text);
                } else {
                    // 降级方案：使用 textarea
                    const textarea = document.createElement('textarea');
                    textarea.value = text;
                    textarea.style.position = 'fixed';
                    textarea.style.left = '-9999px';
                    document.body.appendChild(textarea);
                    textarea.select();
                    document.execCommand('copy');
                    document.body.removeChild(textarea);
                }
            } catch (error) {
                console.error('复制失败:', error);
                throw error;
            }
        }

        // Fix: #accountList 在 i18n skip 列表中，MutationObserver 不会自动翻译。
        // 切换语言时必须手动重渲染账号列表，否则账号卡片文字保留旧语言（如
        // Unknown / 16 hours ago 混搭中文）。简洁模式已在 mailbox_compact.js 正确处理，
        // 此处补全标准模式。
        window.addEventListener('ui-language-changed', () => {
            const cacheKey = typeof getAccountListCacheKey === 'function'
                ? getAccountListCacheKey(currentGroupId)
                : currentGroupId;
            if (accountsCache[cacheKey]) {
                renderAccountList(accountsCache[cacheKey]);
            }
        });


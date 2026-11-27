// ==================== 全站悬停注释说明（默认不显示，鼠标移到元素上显示） ====================
(function () {
    let tooltipEl = null;
    let activeTarget = null;
    let showTimer = null;

    function ensureTooltipEl() {
        if (!tooltipEl) {
            tooltipEl = document.createElement('div');
            tooltipEl.id = 'globalHoverTooltip';
            tooltipEl.className = 'hover-tooltip';
            tooltipEl.setAttribute('role', 'tooltip');
            tooltipEl.setAttribute('aria-hidden', 'true');
            document.body.appendChild(tooltipEl);
        }
        return tooltipEl;
    }

    function translateTipText(text) {
        if (!text) return '';
        if (typeof translateAppTextLocal === 'function') {
            return translateAppTextLocal(text);
        }
        return text;
    }

    function positionTooltip(target) {
        if (!tooltipEl || !target) return;
        const rect = target.getBoundingClientRect();
        const tipRect = tooltipEl.getBoundingClientRect();
        const pad = 10;
        const gap = 7;

        let top = rect.bottom + gap;
        if (top + tipRect.height > window.innerHeight - pad && rect.top - gap - tipRect.height >= pad) {
            top = rect.top - gap - tipRect.height;
        }

        let left = rect.left + Math.min(18, rect.width * 0.25);
        if (left + tipRect.width > window.innerWidth - pad) {
            left = window.innerWidth - tipRect.width - pad;
        }
        if (left < pad) left = pad;

        tooltipEl.style.top = `${Math.round(top)}px`;
        tooltipEl.style.left = `${Math.round(left)}px`;
    }

    function showTooltip(target) {
        const rawText = target && target.getAttribute('data-tip');
        if (!rawText || !rawText.trim()) return;
        const el = ensureTooltipEl();
        activeTarget = target;
        el.textContent = translateTipText(rawText.trim());
        el.classList.add('visible');
        el.setAttribute('aria-hidden', 'false');
        positionTooltip(target);
    }

    function hideTooltip() {
        if (showTimer) {
            clearTimeout(showTimer);
            showTimer = null;
        }
        activeTarget = null;
        if (tooltipEl) {
            tooltipEl.classList.remove('visible');
            tooltipEl.setAttribute('aria-hidden', 'true');
        }
    }

    function findTipTarget(node) {
        if (!node || typeof node.closest !== 'function') return null;
        return node.closest('[data-tip]');
    }

    document.addEventListener('mouseover', function (e) {
        const target = findTipTarget(e.target);
        if (!target) {
            if (activeTarget) hideTooltip();
            return;
        }
        if (target === activeTarget && tooltipEl && tooltipEl.classList.contains('visible')) return;
        if (showTimer) clearTimeout(showTimer);
        showTimer = setTimeout(() => showTooltip(target), 120);
    });

    document.addEventListener('mouseout', function (e) {
        const target = findTipTarget(e.target);
        if (!target) return;
        const related = e.relatedTarget;
        if (related && target.contains(related)) return;
        hideTooltip();
    });

    document.addEventListener('focusin', function (e) {
        const target = findTipTarget(e.target);
        if (target && e.target.matches(':focus-visible')) {
            showTooltip(target);
        }
    });

    document.addEventListener('focusout', hideTooltip);
    document.addEventListener('mousedown', hideTooltip);
    window.addEventListener('scroll', hideTooltip, true);
    window.addEventListener('resize', hideTooltip);
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') hideTooltip();
    });

    window.hideHoverTooltip = hideTooltip;
})();

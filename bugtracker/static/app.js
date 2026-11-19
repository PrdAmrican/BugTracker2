/* SPDX-License-Identifier: AGPL-3.0-or-later
 * Copyright (C) 2026 PrdAmrican <https://github.com/PrdAmrican> */
(function () {
    'use strict';

    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';

    // ── local times ─────────────────────────────────────────────────────
    const rtf = window.Intl && Intl.RelativeTimeFormat ? new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' }) : null;
    const dateFmt = new Intl.DateTimeFormat(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
    const dateTimeFmt = new Intl.DateTimeFormat(undefined, { year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });

    function relative(date) {
        const seconds = Math.round((date - Date.now()) / 1000);
        const abs = Math.abs(seconds);
        if (!rtf || abs > 60 * 60 * 24 * 30) return dateFmt.format(date);
        if (abs < 60) return 'just now';
        if (abs < 3600) return rtf.format(Math.round(seconds / 60), 'minute');
        if (abs < 86400) return rtf.format(Math.round(seconds / 3600), 'hour');
        return rtf.format(Math.round(seconds / 86400), 'day');
    }

    function renderTimes() {
        document.querySelectorAll('time[datetime]').forEach(el => {
            const date = new Date(el.getAttribute('datetime'));
            if (isNaN(date)) return;
            const style = el.dataset.style;
            el.title = dateTimeFmt.format(date);
            el.textContent = style === 'date' ? dateFmt.format(date)
                : style === 'relative' ? relative(date) : dateTimeFmt.format(date);
        });
    }
    renderTimes();
    setInterval(renderTimes, 60000);

    // ── theme toggle ────────────────────────────────────────────────────
    document.querySelectorAll('[data-theme-toggle]').forEach(btn => btn.addEventListener('click', () => {
        const next = document.documentElement.getAttribute('data-bs-theme') === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-bs-theme', next);
        try { localStorage.setItem('bt-theme', next); } catch (e) { /* storage unavailable */ }
    }));

    // ── confirmations ───────────────────────────────────────────────────
    document.querySelectorAll('form[data-confirm]').forEach(form => form.addEventListener('submit', e => {
        if (!window.confirm(form.dataset.confirm)) e.preventDefault();
    }));

    // ── filter dropdowns submit immediately ─────────────────────────────
    document.querySelectorAll('select[data-autosubmit]').forEach(sel => sel.addEventListener('change', () => sel.form.submit()));

    // ── copy link ───────────────────────────────────────────────────────
    document.querySelectorAll('[data-copy]').forEach(btn => btn.addEventListener('click', () => {
        navigator.clipboard?.writeText(btn.dataset.copy).then(() => {
            const original = btn.innerHTML;
            btn.innerHTML = '<i class="bi bi-check-lg"></i> Copied';
            setTimeout(() => { btn.innerHTML = original; }, 1500);
        });
    }));

    // ── files: paste screenshots, drag and drop ─────────────────────────
    function addFiles(input, files) {
        if (!input || !files.length || !window.DataTransfer) return false;
        const dt = new DataTransfer();
        Array.from(input.files).forEach(f => dt.items.add(f));
        files.forEach(f => dt.items.add(f));
        input.files = dt.files;
        input.dispatchEvent(new Event('change'));
        return true;
    }

    const fileInput = document.getElementById('files') || document.getElementById('attach-files');
    if (fileInput) {
        document.addEventListener('paste', e => {
            const images = Array.from(e.clipboardData?.items || [])
                .filter(item => item.kind === 'file' && item.type.startsWith('image/'))
                .map((item, i) => {
                    const blob = item.getAsFile();
                    const ext = (blob.type.split('/')[1] || 'png').replace('jpeg', 'jpg');
                    const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
                    return new File([blob], `screenshot-${stamp}${i ? '-' + i : ''}.${ext}`, { type: blob.type });
                });
            if (images.length && addFiles(fileInput, images)) {
                e.preventDefault();
                const zone = fileInput.closest('[data-dropzone]');
                if (zone && window.confirm(`Attach ${images.length} pasted screenshot${images.length > 1 ? 's' : ''} now?`)) zone.submit();
            }
        });

        const preview = document.getElementById('paste-preview');
        if (preview) fileInput.addEventListener('change', () => {
            preview.innerHTML = '';
            Array.from(fileInput.files).forEach(f => {
                const chip = document.createElement('span');
                chip.className = 'badge text-bg-light border fw-normal';
                chip.textContent = f.name;
                preview.appendChild(chip);
            });
        });
    }

    document.querySelectorAll('[data-dropzone]').forEach(zone => {
        const card = zone.closest('.card') || zone;
        const input = zone.querySelector('input[type=file]');
        ['dragenter', 'dragover'].forEach(ev => card.addEventListener(ev, e => { e.preventDefault(); zone.classList.add('dragover'); }));
        ['dragleave', 'drop'].forEach(ev => card.addEventListener(ev, e => { e.preventDefault(); zone.classList.remove('dragover'); }));
        card.addEventListener('drop', e => {
            if (addFiles(input, Array.from(e.dataTransfer.files))) zone.submit();
        });
    });

    // ── "+" buttons that add a device / build / mode inline ─────────────
    const modalEl = document.getElementById('lookup-modal');
    if (modalEl && window.bootstrap) {
        const modal = new bootstrap.Modal(modalEl);
        const form = document.getElementById('lookup-form');
        const nameInput = document.getElementById('lookup-name');
        const error = document.getElementById('lookup-error');
        let target = null;

        document.querySelectorAll('[data-add-lookup]').forEach(btn => btn.addEventListener('click', () => {
            target = { select: document.getElementById(btn.dataset.addLookup), api: btn.dataset.api };
            modalEl.querySelector('.modal-title').textContent = btn.title;
            nameInput.value = '';
            nameInput.classList.remove('is-invalid');
            modal.show();
        }));
        modalEl.addEventListener('shown.bs.modal', () => nameInput.focus());

        form.addEventListener('submit', async e => {
            e.preventDefault();
            const body = new FormData();
            body.append('name', nameInput.value.trim());
            const resp = await fetch(target.api, { method: 'POST', body, headers: { 'X-CSRFToken': csrfToken } });
            const data = await resp.json().catch(() => ({ error: 'Unexpected response' }));
            if (!resp.ok && !data.id) {
                error.textContent = data.error || 'Could not add';
                nameInput.classList.add('is-invalid');
                return;
            }
            // Add to every dropdown fed by the same list (e.g. SW build + fixed in build).
            const kind = target.select.dataset.lookup;
            document.querySelectorAll(`select[data-lookup="${kind}"]`).forEach(sel => {
                if (!Array.from(sel.options).some(o => o.value === String(data.id))) sel.add(new Option(data.name, data.id));
            });
            target.select.value = String(data.id);
            modal.hide();
        });
    }
})();

/* ═══════════════════════════════════════════════════════════
   DnDTools — Feedback page behaviour
   ═══════════════════════════════════════════════════════════ */
(function () {
    function init() {
        const ISSUES_URL = (window.PRODUCT && window.PRODUCT.issuesUrl) || '';

        let selectedType = 'idea';

        // DOM refs
        const typeButtons = document.querySelectorAll('.feedback-type-btn');
        const labelText = document.getElementById('feedback-label-text');
        const messageEl = document.getElementById('feedback-message');
        const contactEl = document.getElementById('feedback-contact');
        const charCount = document.getElementById('feedback-chars');
        const submitBtn = document.getElementById('feedback-submit');
        const successEl = document.getElementById('feedback-success');
        const formCard = document.querySelector('.feedback-form-card');
        const typeRow = document.querySelector('.feedback-type-row');
        const resetBtn = document.getElementById('feedback-reset');

        const labels = {
            idea: { label: 'Describe your idea', placeholder: "Tell us what you'd like to see or what could be improved…" },
            bug: { label: 'Describe the bug', placeholder: 'What happened? What did you expect to happen instead?' },
        };

        // Type selector
        typeButtons.forEach((btn) => {
            btn.addEventListener('click', () => {
                selectedType = btn.dataset.type;
                typeButtons.forEach((b) => b.classList.toggle('active', b === btn));
                labelText.textContent = labels[selectedType].label;
                messageEl.placeholder = labels[selectedType].placeholder;
            });
        });

        // Character counter
        messageEl.addEventListener('input', () => {
            charCount.textContent = messageEl.value.length;
        });

        // Submit
        submitBtn.addEventListener('click', async () => {
            const message = messageEl.value.trim();
            if (!message || message.length < 3) {
                showNotification('Please write at least a few words.', 'warning');
                return;
            }

            // Feedback goes to our GitHub issues, pre-filled, in the user's own browser: nothing is sent
            // anywhere until they press "Submit new issue" there.
            let appVersion = null;
            try {
                if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.get_app_version === 'function') {
                    appVersion = await window.pywebview.api.get_app_version();
                }
            } catch (_) { /* ignore */ }
            const title = `[${selectedType === 'bug' ? 'Bug' : 'Idea'}] ${message.split('\n')[0].slice(0, 70)}`;
            const lines = [message, '', '---', `App version: ${appVersion || 'unknown'}`];
            const contact = contactEl.value.trim();
            if (contact) lines.push(`Contact: ${contact}`);
            const url = `${ISSUES_URL}/new?title=${encodeURIComponent(title)}&body=${encodeURIComponent(lines.join('\n'))}`;
            window.open(url, '_blank', 'noopener');
            formCard.style.display = 'none';
            typeRow.style.display = 'none';
            successEl.style.display = 'flex';
        });

        // Reset form
        resetBtn.addEventListener('click', () => {
            messageEl.value = '';
            contactEl.value = '';
            charCount.textContent = '0';
            successEl.style.display = 'none';
            formCard.style.display = '';
            typeRow.style.display = '';
        });

        // Simple notification helper (uses app.js notification system if available)
        function showNotification(message, type) {
            if (typeof window.showNotification === 'function') {
                window.showNotification(message, type);
                return;
            }
            alert(message);
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init, { once: true });
    } else {
        init();
    }
})();

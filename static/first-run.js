const setupForm = document.getElementById('first-run-form');
const setupStatus = document.getElementById('setup-status');
setupForm.addEventListener('submit', async event => {
    event.preventDefault();
    const submit = setupForm.querySelector('button');
    submit.disabled = true;
    setupStatus.textContent = 'Проверяю подключение к AD…';
    try {
        const response = await fetch(setupForm.action, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(Object.fromEntries(new FormData(setupForm)))
        });
        const data = await response.json();
        if (response.ok && data.ok) {
            setupForm.reset();
            window.location.assign('/');
            return;
        }
        setupStatus.textContent = data.message || 'Не удалось сохранить настройки';
    } catch {
        setupStatus.textContent = 'Не удалось связаться с панелью';
    } finally {
        submit.disabled = false;
    }
});

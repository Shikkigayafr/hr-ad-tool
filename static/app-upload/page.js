const uploadForm = document.getElementById('app-upload-form');
const installer = document.getElementById('installer');
const publishName = document.getElementById('publish-name');
const args = document.getElementById('arguments');
const preview = document.getElementById('app-upload-preview');
const statusText = document.getElementById('app-upload-status');

function updatePreview() {
    const name = publishName.value.trim();
    const msi = /\.msi$/i.test(name);
    document.getElementById('exe-arguments').hidden = !/\.exe$/i.test(name);
    preview.textContent = !name ? 'Выберите файл' : msi
        ? `msiexec.exe /i "%~dp0${name}" /qn /norestart`
        : `"%~dp0${name}" ${args.value.trim()}`.trimEnd();
}
installer.addEventListener('change', () => {
    publishName.value = installer.files[0]?.name || '';
    updatePreview();
});
publishName.addEventListener('input', updatePreview);
args.addEventListener('input', updatePreview);
uploadForm.addEventListener('submit', async event => {
    event.preventDefault();
    const button = uploadForm.querySelector('button');
    const body = new FormData(uploadForm);
    document.getElementById('app-upload-password').value = '';
    button.disabled = true;
    statusText.textContent = 'Публикация…';
    try {
        const response = await fetch(uploadForm.action, {method: 'POST', body});
        const data = await response.json();
        statusText.textContent = data.message || 'Не удалось опубликовать файл';
        if (response.ok) {
            uploadForm.reset();
            updatePreview();
        }
    } catch {
        statusText.textContent = 'Связь прервалась. Проверьте результат перед повтором.';
    } finally {
        button.disabled = false;
    }
});

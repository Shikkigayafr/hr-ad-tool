// static/greetings.js

function getGreeting(rawName) {
    // Результат вставляется через innerHTML, поэтому имя экранируем
    const name = String(rawName ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
    const now = new Date();
    const hour = now.getHours();
    const day = now.getDate();
    const month = now.getMonth() + 1; // 0-11 -> 1-12
    const year = now.getFullYear();

    // --- 1. Проверяем праздники (Приоритет выше, чем время суток) ---
    
    // Новый год (1 января, или можно растянуть на каникулы)
    if (month === 1 && day === 1) {
        return `С Новым годом, <strong>${name}</strong>! 🎄`;
    }
    // Рождество (7 января)
    if (month === 1 && day === 7) {
        return `С Рождеством, <strong>${name}</strong>! ❄️`;
    }
    // 23 февраля
    if (month === 2 && day === 23) {
        return `С Днём защитника Отечества, <strong>${name}</strong>! 🎖️`;
    }
    // 8 марта
    if (month === 3 && day === 8) {
        return `С 8 Марта, <strong>${name}</strong>! 🌷`;
    }
    // 1 мая
    if (month === 5 && day === 1) {
        return `С Праздником Весны и Труда, <strong>${name}</strong>! ☀️`;
    }
    // 9 мая
    if (month === 5 && day === 9) {
        return `С Днём Победы, <strong>${name}</strong>! 🎗️`;
    }
    // Хэллоуин (31 октября)
    if (month === 10 && day === 31) {
        return `С Хэллоуином, <strong>${name}</strong>! 🎃`;
    }

    // --- 2. Если праздников нет, смотрим на время суток ---

    if (hour >= 5 && hour < 12) {
        return `Доброе утро, <strong>${name}</strong>! ☕`;
    } 
    if (hour >= 12 && hour < 18) {
        return `Добрый день, <strong>${name}</strong>! ☀️`;
    } 
    if (hour >= 18 && hour < 23) {
        return `Добрый вечер, <strong>${name}</strong>! 🌆`;
    } 
    
    // Ночь (с 23:00 до 5:00)
    return `Доброй ночи, <strong>${name}</strong>! 🌙`;
}
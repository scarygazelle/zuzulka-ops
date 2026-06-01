from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="Zuzulka Home Ops API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_ingress_prefix(request: Request, call_next):
    root_path = request.headers.get("X-Ingress-Path", "")
    if root_path:
        request.scope["root_path"] = root_path
    response = await call_next(request)
    return response

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Zuzulka Home Ops</title>
        <meta charset="utf-8">
        <script src="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.11/index.global.min.js"></script>
        <style>
            :root {
                --bg-color: #121212;
                --card-bg: #1e1e1e;
                --text-color: #e0e0e0;
                --primary: #03a9f4;
                --accent: #ff9800;
                --past-gray: #757575;
                --today-green: #4caf50;
                --future-orange: #ff9800;
            }
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background-color: var(--bg-color);
                color: var(--text-color);
                margin: 0;
                padding: 20px;
            }
            h1 {
                text-align: center;
                color: var(--primary);
                margin-bottom: 30px;
            }
            .container {
                display: grid;
                grid-template-columns: 1fr;
                gap: 20px;
                max-width: 1400px;
                margin: 0 auto;
            }
            @media (min-width: 992px) {
                .container {
                    grid-template-columns: 2fr 1fr;
                }
                .full-width {
                    grid-column: span 2;
                }
            }
            .card {
                background-color: var(--card-bg);
                border-radius: 12px;
                padding: 20px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.5);
            }
            .card h2 {
                margin-top: 0;
                border-bottom: 2px solid #333;
                padding-bottom: 10px;
                color: var(--primary);
            }
            /* Стилізація календаря під темну тему */
            #calendar {
                background: var(--card-bg);
                padding: 10px;
                border-radius: 8px;
            }
            .fc {
                --fc-border-color: #333;
                --fc-page-bg-color: var(--card-bg);
                --fc-neutral-text-color: var(--text-color);
            }
            .fc .fc-button-primary {
                background-color: var(--primary);
                border-color: var(--primary);
            }
            .fc .fc-button-primary:hover {
                background-color: #0288d1;
                border-color: #0288d1;
            }
            /* Список подій */
            .event-list {
                list-style: none;
                padding: 0;
                max-height: 500px;
                overflow-y: auto;
            }
            .event-item {
                padding: 12px;
                margin-bottom: 10px;
                border-radius: 6px;
                background: #252525;
                display: flex;
                justify-content: space-between;
                align-items: center;
                border-left: 5px solid transparent;
            }
            .event-item.past {
                border-left-color: var(--past-gray);
                color: var(--past-gray);
            }
            .event-item.today {
                border-left-color: var(--today-green);
                background: #1b2e1c;
            }
            .event-item.today .event-date {
                color: var(--today-green);
                font-weight: bold;
            }
            .event-item.future {
                border-left-color: var(--future-orange);
            }
            .event-item.future .event-date {
                color: var(--future-orange);
            }
            .event-title {
                font-weight: 600;
            }
            .event-badge {
                font-size: 0.8rem;
                padding: 2px 6px;
                border-radius: 4px;
                background: #333;
                color: #aaa;
            }
            /* Форма */
            .form-group {
                margin-bottom: 15px;
            }
            .form-group label {
                display: block;
                margin-bottom: 5px;
                font-size: 0.9rem;
            }
            .form-group input, .form-group select, .form-group textarea {
                width: 100%;
                padding: 10px;
                background-color: #252525;
                border: 1px solid #444;
                border-radius: 6px;
                color: var(--text-color);
                box-sizing: border-box;
            }
            .form-group input:focus, .form-group select:focus {
                border-color: var(--primary);
                outline: none;
            }
            .btn {
                background-color: var(--primary);
                color: white;
                border: none;
                padding: 12px 20px;
                border-radius: 6px;
                cursor: pointer;
                font-weight: bold;
                width: 100%;
                transition: background 0.2s;
            }
            .btn:hover {
                background-color: #0288d1;
            }
        </style>
    </head>
    <body>

        <h1>Бортовий Журнал "Зузулька" 🚀</h1>

        <div class="container">

            <div class="card">
                <h2>📅 Календар подій</h2>
                <div id="calendar"></div>
            </div>

            <div style="display: flex; flex-direction: column; gap: 20px;">

                <div class="card">
                    <h2>➕ Нова задача / Подія</h2>
                    <form id="taskForm">
                        <div class="form-group">
                            <label for="title">Назва події / задачі</label>
                            <input type="text" id="title" required placeholder="Наприклад: Заміна фільтрів осмосу">
                        </div>
                        <div class="form-group">
                            <label for="eventDate">Дата виконання</label>
                            <input type="date" id="eventDate" required>
                        </div>
                        <div class="form-group">
                            <label for="type">Тип події</label>
                            <select id="type">
                                <option value="once">Одноразова подія</option>
                                <option value="recurring">Рекурентна (Повторювана)</option>
                            </select>
                        </div>
                        <button type="submit" class="btn">Додати в журнал</button>
                    </form>
                </div>

                <div class="card">
                    <h2>📋 Хронологічний список</h2>
                    <ul id="eventList" class="event-list">
                        </ul>
                </div>

            </div>
        </div>

        <script>
            // Демо-дані за замовчуванням
            const defaultEvents = [
                { id: "1", title: "Заміна блідера гідроакумулятора", start: "2026-05-15", extendedProps: { type: "once" } },
                { id: "2", title: "Обслуговування септика", start: "2026-06-01", extendedProps: { type: "recurring" } },
                { id: "3", title: "Ревізія LiFePO4 акумуляторів", start: "2026-06-10", extendedProps: { type: "recurring" } }
            ];

            // Завантаження даних з localStorage або використання дефолтних
            let events = JSON.parse(localStorage.getItem('zuzulka_events')) || defaultEvents;

            function saveEvents() {
                localStorage.setItem('zuzulka_events', JSON.stringify(events));
            }

            // Отримання поточної дати у форматі YYYY-MM-DD (локальний час)
            function getTodayDateString() {
                const today = new Date();
                const offset = today.getTimezoneOffset();
                const localToday = new Date(today.getTime() - (offset * 60 * 1000));
                return localToday.toISOString().split('T')[0];
            }

            document.addEventListener('DOMContentLoaded', function() {
                const calendarEl = document.getElementById('calendar');
                const todayStr = getTodayDateString();

                // Ініціалізація календаря
                const calendar = new FullCalendar.Calendar(calendarEl, {
                    initialView: 'dayGridMonth',
                    locale: 'uk',
                    firstDay: 1, // Початок тижня з понеділка
                    headerToolbar: {
                        left: 'prev,next today',
                        center: 'title',
                        right: 'dayGridMonth,listMonth'
                    },
                    events: events,
                    eventColor: '#03a9f4'
                });
                calendar.render();

                // Функція рендерингу списку подій з колірним маркуванням
                function renderEventList() {
                    const listEl = document.getElementById('eventList');
                    listEl.innerHTML = '';

                    // Сортуємо події від найстаріших до найновіших
                    const sortedEvents = [...events].sort((a, b) => new Date(a.start) - new Date(b.start));

                    sortedEvents.forEach(ev => {
                        const li = document.createElement('li');
                        li.className = 'event-item';

                        // Логіка визначення статусу (минуле, сьогодні, майбутнє)
                        if (ev.start < todayStr) {
                            li.classList.add('past');
                        } else if (ev.start === todayStr) {
                            li.classList.add('today');
                        } else {
                            li.classList.add('future');
                        }

                        const isRecurring = ev.extendedProps?.type === 'recurring';
                        const badgeText = isRecurring ? '🔄 Повтор' : '📌 Одноразова';

                        li.innerHTML = `
                            <div>
                                <div class="event-title">${ev.title}</div>
                                <span class="event-badge">${badgeText}</span>
                            </div>
                            <div class="event-date">${ev.start}</div>
                        `;
                        listEl.appendChild(li);
                    });
                }

                renderEventList();

                // Обробка форми додавання нових задач
                const form = document.getElementById('taskForm');
                form.addEventListener('submit', function(e) {
                    e.preventDefault();

                    const title = document.getElementById('title').value;
                    const date = document.getElementById('eventDate').value;
                    const type = document.getElementById('type').value;

                    const newEvent = {
                        id: String(Date.now()),
                        title: title,
                        start: date,
                        extendedProps: { type: type }
                    };

                    // Оновлюємо масив, зберігаємо та перерендеримо компоненти
                    events.push(newEvent);
                    saveEvents();

                    calendar.addEvent(newEvent);
                    renderEventList();

                    // Скидаємо форму
                    form.reset();
                });
            });
        </script>
    </body>
    </html>
    """

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import sys
import re
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from pathlib import Path

def load_messages(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f, strict=False)
    return data.get('messages', data) if isinstance(data, dict) else data

def extract_text(text_field):
    if isinstance(text_field, str): return text_field
    if isinstance(text_field, list):
        return ' '.join([str(t.get('text', '')) if isinstance(t, dict) else str(t) for t in text_field])
    return ''

def classify_event(text_lower):
    if any(w in text_lower for w in ['сбит', 'уничтож', 'сбив']): return ('Сбит БПЛА', 'Основная', 9)
    if 'тревога' in text_lower: return ('Тревога', 'Основная', 8)
    if 'опасность' in text_lower or 'внимание' in text_lower: return ('Внимание/Опасность', 'Основная', 7)
    if 'отбой' in text_lower: return ('Отбой', 'Основная', 1)
    if 'фиксаций' in text_lower or 'пролет' in text_lower or 'движение' in text_lower: return ('Фиксация/Пролет', 'Основная', 6)
    if 'массовый запуск' in text_lower or 'готовит' in text_lower: return ('Угроза масс.запуска', 'Основная', 8)

    if any(w in text_lower for w in ['тихо', 'спокойно', 'обстановк']): return ('info', 'Спокойная обстановка', 0)
    if 'монитор' in text_lower or 'продолжаем' in text_lower: return ('info', 'Мониторинг', 2)
    if any(w in text_lower for w in ['ожид', 'ждём', 'готовность']): return ('info', 'Ожидание', 3)
    if any(w in text_lower for w in ['берегите', 'безопасност', 'меры']): return ('info', 'Рекомендации', 2)
    if 'последствия' in text_lower or 'осколк' in text_lower or 'поврежден' in text_lower: return ('info', 'Последствия атаки', 5)
    if 'губернатор' in text_lower or 'сообщил' in text_lower: return ('info', 'Официальные сводки', 4)
    if 'ростов' in text_lower or 'краснодар' in text_lower or 'сочи' in text_lower: return ('info', 'Соседние регионы', 5)
    if 'приготов' in text_lower: return ('info', 'Предупреждение', 6)
    if 'от 10' in text_lower or 'много' in text_lower or 'волна' in text_lower: return ('info', 'Массовая атака', 8)
    return ('info', 'Прочее', 3)

def detect_locations(text_lower):
    locs = {'Невинномысск': ['невинномысск'], 'Ставрополь': ['ставрополь'], 'Татарка': ['татарка'],
            'Изобильный': ['изобильный'], 'Армавир': ['армавир'], 'Ростов': ['ростов'], 'Будённовск': ['будённовск']}
    return [loc for loc, patterns in locs.items() if any(p in text_lower for p in patterns)]

def count_downed(text_lower):
    if not any(w in text_lower for w in ['сбит', 'уничтож', 'сбив']): return 0
    return sum(int(n) for n in re.findall(r'\b\d+\b', text_lower) if 1 <= int(n) <= 200)

def parse_messages(messages):
    records = []
    for m in messages:
        text = extract_text(m.get('text', ''))
        if not text.strip(): continue
        try:
            dt = datetime.strptime(m['date'], "%Y-%m-%dT%H:%M:%S")
        except (KeyError, ValueError): continue

        cat, subcat, threat = classify_event(text.lower())
        records.append({
            'datetime': dt.isoformat(), 'date': dt.date().isoformat(), 'hour': dt.hour,
            'weekday': dt.weekday(), 'weekday_name': ['Пн','Вт','Ср','Чт','Пт','Сб','Вс'][dt.weekday()],
            'location': ', '.join(detect_locations(text.lower())) or 'Не указана',
            'category': cat, 'subcategory': subcat, 'threat_level': threat,
            'downed': count_downed(text.lower())
        })
    return records

def calculate_sessions(records):
    sorted_recs = sorted(records, key=lambda r: r['datetime'])
    sessions, session_start, session_date = [], None, None

    for rec in sorted_recs:
        current_date = rec['date']
        current_dt = datetime.fromisoformat(rec['datetime'])

        if rec['category'] in ['Внимание/Опасность', 'Тревога', 'Угроза масс.запуска']:
            if session_start is None:
                session_start = current_dt
                session_date = current_date
        elif rec['category'] == 'Отбой' and session_start is not None:
            if current_date == session_date or (current_dt - session_start).total_seconds() < 43200:
                duration = (current_dt - session_start).total_seconds() / 3600
                sessions.append({
                    'date': session_date,
                    'start': session_start.strftime('%H:%M'),
                    'end': current_dt.strftime('%H:%M'),
                    'duration_hours': round(duration, 2)
                })
                session_start = None
                session_date = None
            else:
                session_start = None
                session_date = None
    return sessions

def calculate_weekly_candles(records):
    weekly = defaultdict(lambda: {'days': defaultdict(int)})
    for rec in records:
        dt = datetime.fromisoformat(rec['datetime'])
        week_start = (dt - timedelta(days=dt.weekday())).date().isoformat()
        weekly[week_start]['days'][dt.date().isoformat()] += 1

    candles = []
    for week_key in sorted(weekly.keys()):
        days = weekly[week_key]['days']
        vals = list(days.values())
        open_val = sum(cnt for d, cnt in days.items() if datetime.fromisoformat(d).weekday() <= 2)
        close_val = sum(cnt for d, cnt in days.items() if datetime.fromisoformat(d).weekday() > 2)
        candles.append({'date': week_key, 'open': open_val, 'close': close_val, 'high': max(vals) if vals else 0, 'low': min(vals) if vals else 0})
    return candles

def generate_chart_summaries(records, sessions, candles, hourly, weekday, events, downed_days):
    summaries = {}

    if records:
        first_date = min(r['date'] for r in records)
        last_date = max(r['date'] for r in records)
        total_days = (datetime.fromisoformat(last_date) - datetime.fromisoformat(first_date)).days + 1
        avg_per_day = len(records) / total_days if total_days > 0 else 0
        daily_counts = Counter(r['date'] for r in records)
        top_days = daily_counts.most_common(3)
        top_days_str = ', '.join([f"{d} ({c} соб.)" for d, c in top_days])
        summaries['timeline'] = f"📊 За период с {first_date} по {last_date} ({total_days} дней) зафиксировано {len(records)} оповещений. В среднем {avg_per_day:.1f} событий в день. Самые активные дни: {top_days_str}."

    if candles:
        total_weeks = len(candles)
        avg_per_week = sum(c['open'] + c['close'] for c in candles) / total_weeks if total_weeks > 0 else 0
        most_active = max(candles, key=lambda c: c['open'] + c['close'])
        if len(candles) >= 6:
            early_avg = sum(c['open'] + c['close'] for c in candles[:3]) / 3
            late_avg = sum(c['open'] + c['close'] for c in candles[-3:]) / 3
            trend = "рост активности" if late_avg > early_avg * 1.2 else "снижение активности" if late_avg < early_avg * 0.8 else "стабильная активность"
        else:
            trend = "недостаточно данных для тренда"
        summaries['candle'] = f"📈 Проанализировано {total_weeks} недель. Средняя активность: {avg_per_week:.0f} событий/неделю. Самая активная неделя: {most_active['date']} ({most_active['open']+most_active['close']} соб.). Тренд: {trend}."

    if hourly:
        peak_hour = max(range(24), key=lambda h: hourly[h])
        calmest_hours = sorted(range(24), key=lambda h: hourly[h])[:3]
        calmest_str = ', '.join([f"{h}:00" for h in calmest_hours])
        night_count = sum(hourly[h] for h in [22,23,0,1,2,3,4,5])
        day_count = sum(hourly) - night_count
        summaries['hourly'] = f"⏰ Пик активности: {peak_hour}:00 ({hourly[peak_hour]} оповещ.). Самые спокойные часы: {calmest_str}. Ночь (22:00-06:00): {night_count} событий ({night_count/sum(hourly)*100:.0f}%), день: {day_count} ({day_count/sum(hourly)*100:.0f}%)."

    if weekday:
        wd_names = ['Пн','Вт','Ср','Чт','Пт','Сб','Вс']
        safest_day = wd_names[min(range(7), key=lambda i: weekday[i])]
        safest_count = min(weekday)
        sorted_days = sorted(range(7), key=lambda i: weekday[i], reverse=True)
        top2_dangerous = ', '.join([wd_names[i] for i in sorted_days[:2]])
        dangerous_count = max(weekday)
        summaries['weekday'] = f"📅 Самый безопасный день: {safest_day} ({safest_count} соб.). Самые опасные: {top2_dangerous}. Разница: {dangerous_count - safest_count} событий ({(dangerous_count/safest_count-1)*100:.0f}% больше)."

    if events:
        total_events = sum(events.values())
        top_event = max(events, key=events.get)
        top_count = events[top_event]
        top_pct = top_count / total_events * 100
        info_total = sum(v for k, v in events.items() if k.startswith('info'))
        info_pct = info_total / total_events * 100
        summaries['events'] = f"📋 Всего категорий: {len(events)}. Доминирует: {top_event} ({top_count} соб., {top_pct:.0f}%). Информационные сообщения: {info_total} ({info_pct:.0f}%)."

    if sessions:
        avg_dur = sum(s['duration_hours'] for s in sessions) / len(sessions)
        max_sess = max(sessions, key=lambda s: s['duration_hours'])
        short = sum(1 for s in sessions if s['duration_hours'] < 3)
        medium = sum(1 for s in sessions if 3 <= s['duration_hours'] < 8)
        long = sum(1 for s in sessions if s['duration_hours'] >= 8)
        summaries['sessions'] = f"️ Проанализировано {len(sessions)} сессий. Средняя: {avg_dur:.1f} ч. Максимальная: {max_sess['duration_hours']:.1f} ч ({max_sess['date']}). Короткие (<3ч): {short}, средние (3-8ч): {medium}, длинные (>8ч): {long}."

    if downed_days:
        total_downed = sum(downed_days.values())
        peak_day = max(downed_days, key=downed_days.get)
        peak_count = downed_days[peak_day]
        avg_downed = total_downed / len(downed_days)
        summaries['downed'] = f"💥 Всего сбито: {total_downed} БПЛА за {len(downed_days)} дней. В среднем {avg_downed:.1f} сбитий/день. Рекорд: {peak_count} БПЛА ({peak_day})."

    return summaries

def generate_html(records, sessions, candles, daily_stats, output_path):
    total = len(records)
    total_downed = sum(r['downed'] for r in records)
    night = sum(1 for r in records if r['hour'] in [22,23,0,1,2,3,4,5])

    hourly = [sum(1 for r in records if r['hour'] == h) for h in range(24)]
    weekday = [sum(1 for r in records if r['weekday'] == d) for d in range(7)]
    wd_names = ['Пн','Вт','Ср','Чт','Пт','Сб','Вс']

    events = Counter(f"{r['category']} / {r['subcategory']}" for r in records)
    locs = Counter(r['location'] for r in records).most_common(10)
    downed_days = {k: v['downed'] for k, v in daily_stats.items() if v['downed'] > 0}

    avg_sess = sum(s['duration_hours'] for s in sessions) / len(sessions) if sessions else 0
    max_sess = max((s['duration_hours'] for s in sessions), default=0)

    summaries = generate_chart_summaries(records, sessions, candles, hourly, weekday, events, downed_days)

    def to_json(obj): return json.dumps(obj, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Анализ БПЛА: Рекомендации и Статистика</title>
    <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Segoe UI', system-ui, sans-serif;
            background: linear-gradient(135deg, #0f0f1e 0%, #1a1a2e 100%);
            color: #e0e0e0;
            padding: 20px;
            min-height: 100vh;
        }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        h1 {{
            text-align: center;
            color: #ff6b6b;
            margin-bottom: 10px;
            font-size: 2.2em;
        }}
        .subtitle {{ text-align: center; color: #888; margin-bottom: 30px; }}

        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin-bottom: 30px;
        }}
        .stat-card {{
            background: rgba(255,255,255,0.03);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 10px;
            padding: 20px;
            text-align: center;
        }}
        .stat-value {{ font-size: 2.2em; font-weight: bold; color: #ff6b6b; margin-bottom: 5px; }}
        .stat-label {{ color: #888; font-size: 0.85em; }}

        .section {{
            background: rgba(255,255,255,0.03);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 12px;
            padding: 25px;
            margin-bottom: 25px;
        }}
        .section-title {{
            color: #fff;
            font-size: 1.3em;
            margin-bottom: 20px;
            padding-left: 15px;
            border-left: 4px solid #3498db;
        }}
        .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 25px; margin-bottom: 25px; }}
        @media (max-width: 900px) {{ .grid-2 {{ grid-template-columns: 1fr; }} }}

        .chart-container {{ background: rgba(0,0,0,0.2); border-radius: 8px; padding: 10px; height: 350px; }}
        .chart-container.tall {{ height: 450px; }}

        .chart-summary {{
            background: rgba(52, 152, 219, 0.1);
            border-left: 3px solid #3498db;
            padding: 15px;
            margin-top: 15px;
            border-radius: 6px;
            font-size: 0.95em;
            line-height: 1.6;
            color: #d0d0d0;
        }}

        .session-list {{
            max-height: 300px; overflow-y: auto; background: rgba(0,0,0,0.2);
            border-radius: 8px; padding: 15px; margin-bottom: 20px;
        }}
        .session-item {{
            display: flex; justify-content: space-between; padding: 10px;
            border-bottom: 1px solid rgba(255,255,255,0.1); font-size: 0.9em;
        }}
        .session-item:last-child {{ border-bottom: none; }}
        .session-duration {{ color: #f39c12; font-weight: bold; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🛡️ АНАЛИЗ БЕСПИЛОТНОЙ ОПАСНОСТИ</h1>
        <p class="subtitle">Автоматический отчет на основе данных Telegram-канала</p>

        <div class="stats-grid">
            <div class="stat-card"><div class="stat-value">{total}</div><div class="stat-label">Всего сообщений</div></div>
            <div class="stat-card"><div class="stat-value">{total_downed}</div><div class="stat-label">Сбито БПЛА</div></div>
            <div class="stat-card"><div class="stat-value">{len(sessions)}</div><div class="stat-label">Заверш. сессий</div></div>
            <div class="stat-card"><div class="stat-value">{avg_sess:.1f} ч</div><div class="stat-label">Средняя тревога</div></div>
        </div>

        <div class="section">
            <h2 class="section-title">📅 Хронология оповещений</h2>
            <div id="timeline" class="chart-container tall"></div>
            <div class="chart-summary">{summaries.get('timeline', '')}</div>
        </div>

        <div class="section">
            <h2 class="section-title">🕯️ Динамика по неделям (Свечной график)</h2>
            <div id="candle" class="chart-container"></div>
            <div class="chart-summary">{summaries.get('candle', '')}</div>
        </div>

        <div class="grid-2">
            <div class="section">
                <h2 class="section-title">⏰ Активность по часам</h2>
                <div id="hourly" class="chart-container"></div>
                <div class="chart-summary">{summaries.get('hourly', '')}</div>
            </div>
            <div class="section">
                <h2 class="section-title">📊 По дням недели</h2>
                <div id="weekday" class="chart-container"></div>
                <div class="chart-summary">{summaries.get('weekday', '')}</div>
            </div>
        </div>

        <div class="section">
            <h2 class="section-title">📋 Детальная классификация событий</h2>
            <div id="events" class="chart-container tall"></div>
            <div class="chart-summary">{summaries.get('events', '')}</div>
        </div>

        <div class="section">
            <h2 class="section-title">⏱️ Длительность тревожных сессий</h2>
            <div class="session-list">
                {"".join(f'<div class="session-item"><span>📅 {s["date"]}</span><span>{s["start"]} – {s["end"]}</span><span class="session-duration">{s["duration_hours"]:.1f} ч.</span></div>' for s in sessions[:30]) or '<div style="padding:20px;text-align:center;color:#888;">Нет завершенных сессий</div>'}
            </div>
            <div id="sessChart" class="chart-container"></div>
            <div class="chart-summary">{summaries.get('sessions', '')}</div>
        </div>

        <div class="section">
            <h2 class="section-title">💥 Сбитые БПЛА по дням</h2>
            <div id="downed" class="chart-container"></div>
            <div class="chart-summary">{summaries.get('downed', '')}</div>
        </div>
    </div>

    <script>
        const data = {{
            hourly: {to_json(hourly)},
            wd: {to_json(weekday)},
            wdNames: {to_json(wd_names)},
            evLabels: {to_json(list(events.keys()))},
            evVals: {to_json(list(events.values()))},
            daily: {to_json(daily_stats)},
            downed: {to_json(downed_days)},
            candles: {to_json(candles)},
            sessions: {to_json(sessions)}
        }};

        const layoutBase = {{
            paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
            font: {{color: '#e0e0e0', family: 'Segoe UI'}},
            margin: {{t: 30, b: 50, l: 60, r: 20}}
        }};
        const gridCol = 'rgba(255,255,255,0.1)';

        Plotly.newPlot('timeline', [{{
            x: Object.keys(data.daily), y: Object.values(data.daily).map(x => x.count),
            type: 'scatter', mode: 'lines+markers', line: {{color: '#ff6b6b', width: 2}}, marker: {{size: 4}}
        }}], Object.assign({{}}, layoutBase, {{
            xaxis: {{title: 'Дата', gridcolor: gridCol, rangeslider: {{thickness: 0.1}}}},
            yaxis: {{title: 'Кол-во оповещений', gridcolor: gridCol}}
        }}), {{responsive: true}});

        Plotly.newPlot('candle', [{{
            x: data.candles.map(c => c.date),
            open: data.candles.map(c => c.open), close: data.candles.map(c => c.close),
            high: data.candles.map(c => c.high), low: data.candles.map(c => c.low),
            type: 'candlestick',
            increasing: {{line: {{color: '#4ade80'}}, fillcolor: '#4ade80'}},
            decreasing: {{line: {{color: '#ef4444'}}, fillcolor: '#ef4444'}},
            hovertemplate: '<b>Неделя от %{{x}}</b><br>Пн-Ср: %{{open}} соб.<br>Чт-Вс: %{{close}} соб.<br>Пиковый день: %{{high}} соб.<br>Спокойный день: %{{low}} соб.<extra></extra>'
        }}], Object.assign({{}}, layoutBase, {{
            xaxis: {{title: 'Начало недели', gridcolor: gridCol}},
            yaxis: {{title: 'Событий', gridcolor: gridCol}}
        }}), {{responsive: true}});

        Plotly.newPlot('hourly', [{{
            x: Array.from({{length: 24}}, (_, i) => i), y: data.hourly, type: 'bar',
            marker: {{color: data.hourly.map((_, i) => [22,23,0,1,2,3,4,5].includes(i) ? '#ef4444' : '#4ade80')}},
            hovertemplate: 'Час: %{{x}}:00<br>Оповещений: %{{y}}<extra></extra>'
        }}], Object.assign({{}}, layoutBase, {{
            xaxis: {{title: 'Час суток', dtick: 2, gridcolor: gridCol}},
            yaxis: {{title: 'Количество', gridcolor: gridCol}}
        }}), {{responsive: true}});

        Plotly.newPlot('weekday', [{{
            x: data.wdNames, y: data.wd, type: 'bar', marker: {{color: '#9b59b6'}},
            hovertemplate: 'День: %{{x}}<br>Оповещений: %{{y}}<extra></extra>'
        }}], Object.assign({{}}, layoutBase, {{
            xaxis: {{title: 'День', gridcolor: gridCol}}, yaxis: {{title: 'Количество', gridcolor: gridCol}}
        }}), {{responsive: true}});

        Plotly.newPlot('events', [{{
            y: data.evLabels, x: data.evVals, type: 'bar', orientation: 'h', marker: {{color: '#3498db'}},
            hovertemplate: '%{{y}}<br>Кол-во: %{{x}}<extra></extra>'
        }}], Object.assign({{}}, layoutBase, {{
            xaxis: {{title: 'Количество', gridcolor: gridCol}}, yaxis: {{automargin: true}}, margin: {{t: 30, b: 50, l: 250, r: 20}}
        }}), {{responsive: true}});

        if (data.sessions.length > 0) {{
            Plotly.newPlot('sessChart', [{{
                x: data.sessions.map(s => s.date), y: data.sessions.map(s => s.duration_hours), type: 'bar',
                marker: {{color: data.sessions.map(s => s.duration_hours > 10 ? '#ef4444' : (s.duration_hours > 5 ? '#f39c12' : '#4ade80'))}},
                hovertemplate: 'Дата: %{{x}}<br>Длительность: %{{y}} ч.<extra></extra>'
            }}], Object.assign({{}}, layoutBase, {{
                xaxis: {{title: 'Дата', gridcolor: gridCol}}, yaxis: {{title: 'Часов', gridcolor: gridCol}}
            }}), {{responsive: true}});
        }}

        Plotly.newPlot('downed', [{{
            x: Object.keys(data.downed), y: Object.values(data.downed), type: 'bar', marker: {{color: '#c0392b'}},
            hovertemplate: 'Дата: %{{x}}<br>Сбито: %{{y}}<extra></extra>'
        }}], Object.assign({{}}, layoutBase, {{
            xaxis: {{title: 'Дата', gridcolor: gridCol, rangeslider: {{thickness: 0.1}}}},
            yaxis: {{title: 'Сбито БПЛА', gridcolor: gridCol}}
        }}), {{responsive: true}});
    </script>
</body>
</html>"""

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"✅ Готово! Файл: {output_path}")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Использование: python drone_report.py messages.json")
        sys.exit(1)

    print("Загрузка данных...")
    msgs = load_messages(sys.argv[1])
    print(f"Парсинг {len(msgs)} сообщений...")
    recs = parse_messages(msgs)

    daily = defaultdict(lambda: {'count': 0, 'downed': 0})
    for r in recs:
        daily[r['date']]['count'] += 1
        daily[r['date']]['downed'] += r['downed']

    print("Генерация отчета...")
    generate_html(recs, calculate_sessions(recs), calculate_weekly_candles(recs), dict(daily), Path(sys.argv[1]).stem + '_report.html')

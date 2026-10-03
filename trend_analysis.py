#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import sys
from datetime import datetime, timedelta
from collections import defaultdict
import matplotlib.pyplot as plt
import numpy as np
from scipy import stats

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
    if any(w in text_lower for w in ['сбит', 'уничтож', 'сбив']): return 'Сбит БПЛА'
    if 'тревога' in text_lower: return 'Тревога'
    if 'опасность' in text_lower or 'внимание' in text_lower: return 'Внимание/Опасность'
    if 'отбой' in text_lower: return 'Отбой'
    if 'фиксаций' in text_lower or 'пролет' in text_lower: return 'Фиксация/Пролет'
    if 'массовый запуск' in text_lower: return 'Угроза масс.запуска'
    return 'info'

def parse_messages(messages):
    records = []
    for m in messages:
        text = extract_text(m.get('text', ''))
        if not text.strip(): continue
        try:
            dt = datetime.strptime(m['date'], "%Y-%m-%dT%H:%M:%S")
        except (KeyError, ValueError): continue

        records.append({
            'datetime': dt,
            'date': dt.date(),
            'category': classify_event(text.lower())
        })
    return records

def calculate_weekly_trend(records):
    """Группировка по неделям с расчетом тренда."""
    weekly = defaultdict(int)

    for rec in records:
        # Начало недели (понедельник)
        week_start = rec['datetime'] - timedelta(days=rec['datetime'].weekday())
        week_key = week_start.date()
        weekly[week_key] += 1

    # Сортировка по дате
    sorted_weeks = sorted(weekly.items())
    dates = [d for d, _ in sorted_weeks]
    counts = [c for _, c in sorted_weeks]

    # Расчет линейного тренда
    x = np.arange(len(dates))
    slope, intercept, r_value, p_value, std_err = stats.linregress(x, counts)

    # Скользящее среднее (4 недели)
    window = 4
    moving_avg = []
    for i in range(len(counts)):
        if i < window - 1:
            moving_avg.append(np.mean(counts[:i+1]))
        else:
            moving_avg.append(np.mean(counts[i-window+1:i+1]))

    return dates, counts, moving_avg, slope, r_value**2

def plot_trend(dates, counts, moving_avg, slope, r_squared, output_path):
    """Создание графика тренда."""
    plt.rcParams['font.sans-serif'] = ['DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False

    fig, ax1 = plt.subplots(figsize=(16, 8))

    # Основные данные
    ax1.bar(dates, counts, alpha=0.3, color='#3498db', label='Оповещений за неделю', width=5)
    ax1.plot(dates, moving_avg, color='#e74c3c', linewidth=3, label='Скользящее среднее (4 нед.)')

    # Линия тренда
    x = np.arange(len(dates))
    trend_line = slope * x + (counts[0] - slope * 0)
    ax1.plot(dates, trend_line, color='#2ecc71', linewidth=2, linestyle='--', label=f'Линия тренда (наклон: {slope:.2f}/нед)')

    # Определение тренда
    if slope > 0.5:
        trend_text = " РОСТ активности"
        trend_color = '#e74c3c'
    elif slope < -0.5:
        trend_text = " СНИЖЕНИЕ активности"
        trend_color = '#2ecc71'
    else:
        trend_text = "➡️ СТАБИЛЬНАЯ активность"
        trend_color = '#f39c12'

    # Статистика
    total_weeks = len(dates)
    avg_count = np.mean(counts)
    max_count = max(counts)
    max_date = dates[counts.index(max_count)]

    # Последние 4 недели vs первые 4 недели
    if len(counts) >= 8:
        recent_avg = np.mean(counts[-4:])
        early_avg = np.mean(counts[:4])
        change_pct = ((recent_avg - early_avg) / early_avg) * 100
    else:
        recent_avg = np.mean(counts[-2:]) if len(counts) >= 2 else avg_count
        early_avg = np.mean(counts[:2]) if len(counts) >= 2 else avg_count
        change_pct = ((recent_avg - early_avg) / early_avg) * 100 if early_avg > 0 else 0

    ax1.set_xlabel('Дата (начало недели)', fontsize=12)
    ax1.set_ylabel('Количество оповещений', fontsize=12)
    ax1.set_title(f'Тренд активности БПЛА\n{trend_text} | R² = {r_squared:.3f}',
                  fontsize=16, fontweight='bold', color=trend_color)
    ax1.legend(loc='upper left', fontsize=10)
    ax1.grid(True, alpha=0.3)

    # Поворот дат для читаемости
    plt.xticks(rotation=45, ha='right')

    # Текстовый блок со статистикой
    stats_text = f"""
    Статистика:
    • Период: {dates[0]} — {dates[-1]} ({total_weeks} нед.)
    • Среднее: {avg_count:.1f} соб./нед
    • Пик: {max_count} соб. ({max_date})
    • Изменение (первые vs последние 4 нед.): {change_pct:+.1f}%
    • Наклон тренда: {slope:.2f} соб./нед
    • Достоверность (R²): {r_squared:.3f}
    """

    ax1.text(0.02, 0.98, stats_text, transform=ax1.transAxes,
             fontsize=10, verticalalignment='top',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"✅ График сохранён: {output_path}")
    print(f"\n📊 ВЫВОД: {trend_text}")
    print(f"   Изменение активности: {change_pct:+.1f}%")
    print(f"   Достоверность тренда: {r_squared:.3f} (0=нет тренда, 1=точный тренд)")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Использование: python trend_analysis.py messages.json")
        sys.exit(1)

    print("Загрузка данных...")
    msgs = load_messages(sys.argv[1])
    print(f"Парсинг {len(msgs)} сообщений...")
    recs = parse_messages(msgs)

    print("Анализ тренда...")
    dates, counts, moving_avg, slope, r_squared = calculate_weekly_trend(recs)

    output_path = 'bpla_trend.png'
    plot_trend(dates, counts, moving_avg, slope, r_squared, output_path)

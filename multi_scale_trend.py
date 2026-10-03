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

def remove_outliers(data, threshold=2.0):
    """Удаление выбросов методом IQR."""
    arr = np.array(data)
    q1 = np.percentile(arr, 25)
    q3 = np.percentile(arr, 75)
    iqr = q3 - q1
    lower = q1 - threshold * iqr
    upper = q3 + threshold * iqr
    return np.where((arr >= lower) & (arr <= upper), arr, np.nan)

def calculate_trends(records, cutoff_date):
    """Расчет трендов с учетом cutoff_date (исключение текущего месяца)."""
    # Фильтруем данные до cutoff_date
    filtered = [r for r in records if r['datetime'] < cutoff_date]

    # Группировка по неделям
    weekly = defaultdict(int)
    for rec in filtered:
        week_start = rec['datetime'] - timedelta(days=rec['datetime'].weekday())
        weekly[week_start.date()] += 1

    # Группировка по месяцам
    monthly = defaultdict(int)
    for rec in filtered:
        month_key = rec['datetime'].replace(day=1).date()
        monthly[month_key] += 1

    # Группировка по кварталам
    quarterly = defaultdict(int)
    for rec in filtered:
        quarter = (rec['datetime'].month - 1) // 3 + 1
        quarter_key = datetime(rec['datetime'].year, quarter * 3 - 2, 1).date()
        quarterly[quarter_key] += 1

    return weekly, monthly, quarterly, len(filtered)

def analyze_and_plot(weekly, monthly, quarterly, cutoff_date, filtered_count, output_path):
    """Анализ и визуализация многоуровневого тренда."""
    plt.rcParams['font.sans-serif'] = ['DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False

    fig, axes = plt.subplots(3, 1, figsize=(18, 14))

    # ===== НЕДЕЛЬНЫЙ ТРЕНД =====
    ax1 = axes[0]
    weeks = sorted(weekly.keys())
    week_counts = [weekly[w] for w in weeks]
    week_clean = remove_outliers(week_counts, threshold=1.5)

    x_week = np.arange(len(weeks))
    week_clean_arr = np.array(week_clean)
    valid = ~np.isnan(week_clean_arr)

    if valid.sum() > 2:
        slope_w, intercept_w, r_w, _, _ = stats.linregress(x_week[valid], week_clean_arr[valid])
    else:
        slope_w, r_w = 0, 0

    # Прогноз на 12 недель вперед
    future_weeks = 12
    x_future = np.arange(len(weeks), len(weeks) + future_weeks)
    y_future = slope_w * x_future + intercept_w

    ax1.bar(weeks, week_counts, alpha=0.3, color='#3498db', label='Факт (недели)', width=5)
    ax1.plot(weeks, week_clean, 'o-', color='#e74c3c', linewidth=2, label='Без выбросов', markersize=4)
    ax1.plot(weeks, slope_w * x_week + intercept_w, '--', color='#2ecc71', linewidth=2,
             label=f'Тренд (наклон: {slope_w:.2f}/нед)')
    ax1.plot([weeks[-1] + timedelta(weeks=i) for i in range(1, future_weeks+1)],
             y_future, ':', color='#9b59b6', linewidth=2, label=f'Прогноз ({future_weeks} нед.)')

    trend_w = " РОСТ" if slope_w > 0.1 else "📉 СНИЖЕНИЕ" if slope_w < -0.1 else "➡️ СТАБИЛЬНО"
    ax1.set_title(f'Недельный тренд: {trend_w} | R²={r_w**2:.3f}',
                  fontsize=14, fontweight='bold')
    ax1.legend(loc='upper right', fontsize=9)
    ax1.grid(True, alpha=0.3)
    ax1.set_ylabel('Оповещений/неделю')

    # ===== МЕСЯЧНЫЙ ТРЕНД =====
    ax2 = axes[1]
    months = sorted(monthly.keys())
    month_counts = [monthly[m] for m in months]
    month_clean = remove_outliers(month_counts, threshold=1.5)

    x_month = np.arange(len(months))
    month_clean_arr = np.array(month_clean)
    valid_m = ~np.isnan(month_clean_arr)

    if valid_m.sum() > 2:
        slope_m, intercept_m, r_m, _, _ = stats.linregress(x_month[valid_m], month_clean_arr[valid_m])
    else:
        slope_m, r_m = 0, 0

    future_months = 6
    x_future_m = np.arange(len(months), len(months) + future_months)
    y_future_m = slope_m * x_future_m + intercept_m

    ax2.bar(months, month_counts, alpha=0.3, color='#3498db', label='Факт (месяцы)', width=20)
    ax2.plot(months, month_clean, 'o-', color='#e74c3c', linewidth=2, label='Без выбросов', markersize=5)
    ax2.plot(months, slope_m * x_month + intercept_m, '--', color='#2ecc71', linewidth=2,
             label=f'Тренд (наклон: {slope_m:.2f}/мес)')
    ax2.plot([months[-1] + timedelta(days=30*i) for i in range(1, future_months+1)],
             y_future_m, ':', color='#9b59b6', linewidth=2, label=f'Прогноз ({future_months} мес.)')

    trend_m = "📈 РОСТ" if slope_m > 0.5 else "📉 СНИЖЕНИЕ" if slope_m < -0.5 else "➡️ СТАБИЛЬНО"
    ax2.set_title(f'Месячный тренд: {trend_m} | R²={r_m**2:.3f}',
                  fontsize=14, fontweight='bold')
    ax2.legend(loc='upper right', fontsize=9)
    ax2.grid(True, alpha=0.3)
    ax2.set_ylabel('Оповещений/месяц')

    # ===== КВАРТАЛЬНЫЙ ТРЕНД =====
    ax3 = axes[2]
    quarters = sorted(quarterly.keys())
    quarter_counts = [quarterly[q] for q in quarters]

    x_quarter = np.arange(len(quarters))
    if len(quarters) > 2:
        slope_q, intercept_q, r_q, _, _ = stats.linregress(x_quarter, quarter_counts)
    else:
        slope_q, r_q = 0, 0

    future_quarters = 4
    x_future_q = np.arange(len(quarters), len(quarters) + future_quarters)
    y_future_q = slope_q * x_future_q + intercept_q

    ax3.bar(quarters, quarter_counts, alpha=0.3, color='#3498db', label='Факт (кварталы)', width=60)
    ax3.plot(quarters, slope_q * x_quarter + intercept_q, '--', color='#2ecc71', linewidth=2,
             label=f'Тренд (наклон: {slope_q:.2f}/кварт)')
    ax3.plot([quarters[-1] + timedelta(days=90*i) for i in range(1, future_quarters+1)],
             y_future_q, ':', color='#9b59b6', linewidth=2, label=f'Прогноз ({future_quarters} кварт.)')

    trend_q = " РОСТ" if slope_q > 2 else "📉 СНИЖЕНИЕ" if slope_q < -2 else "➡️ СТАБИЛЬНО"
    ax3.set_title(f'Квартальный тренд: {trend_q} | R²={r_q**2:.3f}',
                  fontsize=14, fontweight='bold')
    ax3.legend(loc='upper right', fontsize=9)
    ax3.grid(True, alpha=0.3)
    ax3.set_ylabel('Оповещений/квартал')
    ax3.set_xlabel('Дата')

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')

    # Вывод анализа
    print("\n" + "="*70)
    print("МНОГОУРОВНЕВЫЙ АНАЛИЗ ТРЕНДА БПЛА")
    print(f"Дата анализа: {datetime.now().strftime('%d.%m.%Y')}")
    print(f"Исключен текущий месяц (неполный): {cutoff_date.strftime('%B %Y')}")
    print(f"Проанализировано сообщений: {filtered_count}")
    print("="*70)

    print(f"\n📅 НЕДЕЛЬНЫЙ МАСШТАБ:")
    print(f"   Наклон: {slope_w:.3f} опов./неделю")
    print(f"   Тренд: {trend_w}")
    print(f"   Достоверность: R² = {r_w**2:.3f}")
    print(f"   Прогноз на 3 месяца: {'увеличение' if slope_w > 0 else 'снижение'} на {abs(slope_w*12):.0f} опов./нед")

    print(f"\n📆 МЕСЯЧНЫЙ МАСШТАБ:")
    print(f"   Наклон: {slope_m:.3f} опов./месяц")
    print(f"   Тренд: {trend_m}")
    print(f"   Достоверность: R² = {r_m**2:.3f}")
    print(f"   Прогноз на полгода: {'увеличение' if slope_m > 0 else 'снижение'} на {abs(slope_m*6):.0f} опов./мес")

    print(f"\n📊 КВАРТАЛЬНЫЙ МАСШТАБ:")
    print(f"   Наклон: {slope_q:.3f} опов./квартал")
    print(f"   Тренд: {trend_q}")
    print(f"   Достоверность: R² = {r_q**2:.3f}")

    print(f"\n💡 ВЫВОД:")
    if slope_w < -0.1 and slope_m > 0.5:
        print("   ⚠️  ПРОТИВОРЕЧИЕ: Краткосрочный тренд снижается, но долгосрочный растет!")
        print("   Это означает, что после текущего затишья возможна новая волна активности.")
    elif slope_w < -0.1 and slope_m < -0.5:
        print("   ✅ ПОЛОЖИТЕЛЬНАЯ ДИНАМИКА: Активность снижается на всех масштабах.")
    elif slope_w > 0.1 and slope_m > 0.5:
        print("   ⚠️  НЕГАТИВНАЯ ДИНАМИКА: Активность растет на всех масштабах.")
    else:
        print("   ️  СМЕШАННАЯ КАРТИНА: Нет четкого тренда, возможны колебания.")

    print("="*70)

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Использование: python multi_scale_trend.py messages.json")
        sys.exit(1)

    # Получаем текущую дату и устанавливаем cutoff_date на начало текущего месяца
    now = datetime.now()
    cutoff_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    print(f"Текущая дата: {now.strftime('%d.%m.%Y %H:%M')}")
    print(f"Анализ до: {cutoff_date.strftime('%d.%m.%Y')} (исключая текущий месяц)")

    print("\nЗагрузка данных...")
    msgs = load_messages(sys.argv[1])
    print(f"Всего сообщений в файле: {len(msgs)}")

    print("Парсинг сообщений...")
    recs = parse_messages(msgs)
    print(f"Успешно распарсено: {len(recs)}")

    print("Расчет трендов на разных масштабах...")
    weekly, monthly, quarterly, filtered_count = calculate_trends(recs, cutoff_date)

    output_path = 'multi_scale_trend.png'
    analyze_and_plot(weekly, monthly, quarterly, cutoff_date, filtered_count, output_path)
    print(f"\n✅ График сохранён: {output_path}")

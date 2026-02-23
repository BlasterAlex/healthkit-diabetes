from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


FILE_PATH = "export.xml"

GLUCOSE_MIN = 4  # ммоль/л — нижняя граница целевого диапазона
GLUCOSE_MAX = 10  # ммоль/л — верхняя граница целевого диапазона

# Единый источник цветов для графика и блока статистики
_ZONE_COLOR = {
    "in_range": "#32CD32",  # зелёный  — в диапазоне
    "above":    "#FF4444",  # красный  — выше диапазона
    "below":    "#FFA500",  # оранжевый — ниже диапазона
}


def _glucose_zone(v: float) -> str:
    """Определяет зону глюкозы: 'below', 'in_range' или 'above'."""
    if v < GLUCOSE_MIN:
        return "below"
    if v > GLUCOSE_MAX:
        return "above"
    return "in_range"

st.set_page_config(layout="wide", page_title="Дневник Диабета")

st.markdown(
    """
<style>
    .block-container { padding: 1rem 5rem 0; }

    [data-testid="stAppDeployButton"] { display: none; }
    [data-testid="stMainMenuList"] > ul:nth-child(4),
    [data-testid="stMainMenuList"] > ul:nth-child(5),
    [data-testid="stMainMenuDivider"] { display: none; }
    
    div[data-testid="stDateInput"] label { margin-bottom: 16px; }
    div[data-testid="stDateInput"] p { font-size: 16px; }

    div[data-testid="stDateInput"] > div,
    div[data-testid="stDateInput"] input { cursor: pointer !important; }
    
    div[data-testid="stDateInput"] input {
        background-image: url("data:image/svg+xml,%3Csvg width='24' height='24' viewBox='0 0 24 24' fill='none' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M6 9L12 15L18 9' stroke='%23808495' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E") !important;
        background-repeat: no-repeat !important;
        background-position: right 10px center !important;
        background-size: 18px !important;
        padding-right: 35px !important;
    }
</style>
""",
    unsafe_allow_html=True,
)


def _fmt_units(v: float) -> str:
    return str(int(v)) if v == int(v) else f"{v:.1f}"


def _crossing_point(
    t0: pd.Timestamp, t1: pd.Timestamp, v0: float, v1: float
) -> tuple[pd.Timestamp, float]:
    """Вычисляет момент и значение пересечения с границей целевого диапазона."""
    boundary = GLUCOSE_MIN if (v0 < GLUCOSE_MIN) != (v1 < GLUCOSE_MIN) else GLUCOSE_MAX
    ratio = (boundary - v0) / (v1 - v0) if v1 != v0 else 0.5
    return t0 + (t1 - t0) * ratio, boundary


def _glucose_traces(df: pd.DataFrame) -> list[go.Scatter]:
    """Разбивает линию глюкозы на сегменты по зонам: ниже/норма/выше диапазона."""
    if df.empty:
        return []

    dates = df["date"].tolist()
    values = df["value"].tolist()

    segments: list[tuple] = []
    seg_x = [dates[0]]
    seg_y = [values[0]]
    seg_ok = _glucose_zone(values[0])

    for pt in range(1, len(values)):
        if _glucose_zone(values[pt]) == seg_ok:
            seg_x.append(dates[pt])
            seg_y.append(values[pt])
        else:
            t_cross, boundary = _crossing_point(
                dates[pt - 1], dates[pt], values[pt - 1], values[pt]
            )
            seg_x.append(t_cross)
            seg_y.append(boundary)
            segments.append((seg_x, seg_y, seg_ok))

            seg_x = [t_cross, dates[pt]]
            seg_y = [boundary, values[pt]]
            seg_ok = _glucose_zone(values[pt])

    segments.append((seg_x, seg_y, seg_ok))

    result = []
    for idx, (seg_x, seg_y, ok) in enumerate(segments):
        result.append(go.Scatter(
            x=seg_x,
            y=seg_y,
            name="Глюкоза (ммоль/л)",
            mode="lines",
            line=dict(color=_ZONE_COLOR[ok], width=2, shape="spline"),
            yaxis="y1",
            legendgroup="glucose",
            showlegend=idx == 0,
            hoverinfo="skip",
        ))

    # отдельный невидимый трейс для hover — только реальные точки, без дублей
    hover_colors = [_ZONE_COLOR[_glucose_zone(v)] for v in values]
    result.append(go.Scatter(
        x=dates,
        y=values,
        name="Глюкоза (ммоль/л)",
        mode="markers",
        marker=dict(color=hover_colors, size=12, symbol="square", opacity=0),
        yaxis="y1",
        legendgroup="glucose",
        showlegend=False,
        hovertemplate="<b>Глюкоза:</b> %{y:.1f} ммоль/л<extra></extra>",
    ))

    return result


def _xaxis_ticks() -> dict:
    if _days <= 3:
        dtick = 2 * 3600_000        # каждые 2 часа
    elif _days <= 7:
        dtick = 6 * 3600_000        # каждые 6 часов
    elif _days <= 14:
        dtick = 12 * 3600_000       # каждые 12 часов
    elif _days <= 31:
        dtick = 24 * 3600_000       # каждые 24 часа
    else:
        dtick = 7 * 24 * 3600_000   # каждые 7 дней

    if _days <= 14:
        # время на тиках, дата — отдельными жирными аннотациями под осью
        return {"dtick": dtick, "tickformat": "%H:%M"}

    # крупный диапазон — только даты, жирным
    return {"dtick": dtick, "tickformat": "%d.%m", "tickfont": dict(weight="bold")}


def _glucose_stats(df: pd.DataFrame) -> dict | None:
    """Вычисляет TIR/TAR/TBR и базовые показатели глюкозы. Возвращает None если данных нет."""
    if df.empty:
        return None
    vals = df["value"]
    n = len(vals)
    tir = round(vals.between(GLUCOSE_MIN, GLUCOSE_MAX).sum() / n * 100)
    tar = round((vals > GLUCOSE_MAX).sum() / n * 100)
    return {
        "tir": tir, "tar": tar, "tbr": 100 - tir - tar,
        "mean": vals.mean(), "min": vals.min(), "max": vals.max(),
    }


def _stats_section(
    glc: pd.DataFrame,
    ins: pd.DataFrame,
    crb: pd.DataFrame,
    n_days: int,
) -> None:
    """Рендерит блок сводной статистики за выбранный период.

    n_days — количество календарных суток в выбранном диапазоне (>= 1),
    используется для расчёта среднесуточных значений инсулина и углеводов.
    """
    g = _glucose_stats(glc)
    bolus = ins[ins["reason"] == "Болюс"]["value"].sum() if not ins.empty else 0.0
    basal = ins[ins["reason"] == "Базал"]["value"].sum() if not ins.empty else 0.0
    carbs = int(crb["value"].sum()) if not crb.empty else 0

    st.markdown("---")

    # Цветная полоска: зелёный — в диапазоне, красный — выше, оранжевый — ниже
    if g:
        st.markdown(
            f"""
<div style="display:flex;height:20px;border-radius:6px;overflow:hidden;
            gap:2px;margin-bottom:6px">
  <div style="width:{g['tir']}%;background:{_ZONE_COLOR['in_range']}" title="В диапазоне: {g['tir']}%"></div>
  <div style="width:{g['tar']}%;background:{_ZONE_COLOR['above']}" title="Выше диапазона: {g['tar']}%"></div>
  <div style="width:{g['tbr']}%;background:{_ZONE_COLOR['below']}" title="Ниже диапазона: {g['tbr']}%"></div>
</div>""",
            unsafe_allow_html=True,
        )

    col_tir, col_gl, col_i, col_c = st.columns(4)

    with col_tir:
        st.markdown("**⏱️ Время в диапазоне**")
        if g:
            c1, c2, c3 = st.columns(3)
            c1.metric("🟢 В диап.", f"{g['tir']}%")
            c2.metric("🔴 Выше", f"{g['tar']}%")
            c3.metric("🟠 Ниже", f"{g['tbr']}%")

    with col_gl:
        st.markdown("**🩸 Глюкоза, ммоль/л**")
        if g:
            c1, c2, c3 = st.columns(3)
            c1.metric("Среднее", f"{g['mean']:.1f}")
            c2.metric("Мин", f"{g['min']:.1f}")
            c3.metric("Макс", f"{g['max']:.1f}")

    with col_i:
        st.markdown("**💉 Инсулин**")
        c1, c2 = st.columns(2)
        c1.metric(
            "Болюс, ЕД/сут",
            round(bolus / n_days),
            delta=f"всего {round(bolus)}",
            delta_color="off",
        )
        c2.metric(
            "Базал, ЕД/сут",
            round(basal / n_days),
            delta=f"всего {round(basal)}",
            delta_color="off",
        )

    with col_c:
        st.markdown("**🍞 Углеводы**")
        st.metric(
            "г / сутки",
            int(round(carbs / n_days)),
            delta=f"всего {carbs} г",
            delta_color="off",
        )


def _to_sorted_df(records: list[dict]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records).sort_values("date")
    df["date"] = df["date"].dt.tz_localize(None)
    return df


@st.cache_data(persist="disk")
def load_data(file_path: str, mtime: float) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:  # pylint: disable=unused-argument
    """Загружает данные из HealthKit XML и кэширует результат на диск.

    Кэш инвалидируется автоматически при изменении файла: mtime (время
    последнего изменения) входит в ключ кэша. Параметры с префиксом ``_``
    Streamlit из ключа исключает, поэтому имя без подчёркивания.
    """
    if not os.path.exists(file_path):
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    glucose: list[dict] = []
    carbs: list[dict] = []
    insulin: list[dict] = []
    skipped = 0

    try:
        context = ET.iterparse(file_path, events=("end",))
        for _, elem in context:
            if elem.tag == "Record":
                record_type = elem.get("type")

                if record_type in [
                    "HKQuantityTypeIdentifierBloodGlucose",
                    "HKQuantityTypeIdentifierDietaryCarbohydrates",
                    "HKQuantityTypeIdentifierInsulinDelivery",
                ]:
                    try:
                        date_val = pd.to_datetime(elem.get("startDate"))
                        # type: ignore[arg-type]
                        val = float(elem.get("value"))
                    except (ValueError, TypeError):
                        skipped += 1
                        elem.clear()
                        continue

                    if record_type == "HKQuantityTypeIdentifierBloodGlucose":
                        glucose.append({"date": date_val, "value": val})

                    elif record_type == "HKQuantityTypeIdentifierDietaryCarbohydrates":
                        carbs.append({"date": date_val, "value": val})

                    elif record_type == "HKQuantityTypeIdentifierInsulinDelivery":
                        reason = "Болюс"  # Значение по умолчанию

                        # ГЛУБОКИЙ ПОИСК: перебираем все вложенные теги внутри Record
                        for meta in elem.iter():
                            # Проверяем, содержит ли тег в названии MetadataEntry
                            if "MetadataEntry" in meta.tag:
                                if meta.get("key") == "HKInsulinDeliveryReason":
                                    if meta.get("value") == "1":
                                        reason = "Базал"

                        insulin.append(
                            {"date": date_val, "value": val, "reason": reason})

                # Очищаем память, чтобы скрипт не съел всю ОЗУ
                elem.clear()

    except ET.ParseError as e:
        st.error(f"Ошибка разбора XML: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    if skipped:
        st.warning(f"Пропущено некорректных записей: {skipped}")

    return _to_sorted_df(glucose), _to_sorted_df(carbs), _to_sorted_df(insulin)


# === ИНТЕРФЕЙС ===
st.title("📊 Дневник Диабета")

df_g, df_c, df_i = load_data(
    FILE_PATH,
    os.path.getmtime(FILE_PATH) if os.path.exists(FILE_PATH) else 0.0,
)

if df_g.empty and df_c.empty and df_i.empty:
    st.error(f"Файл {FILE_PATH} не найден или пуст.")
    st.stop()

all_dates = pd.concat([df["date"]
                      for df in [df_g, df_c, df_i] if not df.empty])
min_date_val = all_dates.min().date()
max_date_val = all_dates.max().date()

if "start_date" not in st.session_state:
    st.session_state.start_date = max(
        min_date_val, max_date_val - timedelta(days=3))
if "end_date" not in st.session_state:
    st.session_state.end_date = max_date_val

col1, col2 = st.columns([1, 2], vertical_alignment="top")

with col1:
    selected_dates = st.date_input(
        "📅 Выберите период",
        value=(st.session_state.start_date, st.session_state.end_date),
        min_value=min_date_val,
        max_value=max_date_val,
    )
    if len(selected_dates) == 2:
        st.session_state.start_date, st.session_state.end_date = selected_dates

with col2:
    st.write("⏱️ Быстрый выбор:")
    btn1, btn2, btn3, btn4, btn5 = st.columns(5)

    if btn1.button("3 дня", width="stretch"):
        st.session_state.start_date = max_date_val - timedelta(days=3)
        st.session_state.end_date = max_date_val
        st.rerun()
    if btn2.button("1 неделя", width="stretch"):
        st.session_state.start_date = max_date_val - timedelta(days=7)
        st.session_state.end_date = max_date_val
        st.rerun()
    if btn3.button("2 недели", width="stretch"):
        st.session_state.start_date = max_date_val - timedelta(days=14)
        st.session_state.end_date = max_date_val
        st.rerun()
    if btn4.button("1 месяц", width="stretch"):
        st.session_state.start_date = max_date_val - timedelta(days=30)
        st.session_state.end_date = max_date_val
        st.rerun()
    if btn5.button("2 месяца", width="stretch"):
        st.session_state.start_date = max_date_val - timedelta(days=60)
        st.session_state.end_date = max_date_val
        st.rerun()

# --- ФИЛЬТРАЦИЯ ---
start_dt = pd.to_datetime(st.session_state.start_date)
end_dt = pd.to_datetime(st.session_state.end_date) + pd.Timedelta(
    hours=23, minutes=59, seconds=59
)

f_g = df_g[(df_g["date"] >= start_dt) & (df_g["date"] <= end_dt)]
f_c = df_c[(df_c["date"] >= start_dt) & (df_c["date"] <= end_dt)]
f_i = df_i[(df_i["date"] >= start_dt) & (df_i["date"] <= end_dt)]

# --- ГРАФИК ---
fig = go.Figure()

max_g = f_g["value"].max() if not f_g.empty else 15
max_i = f_i["value"].max() if not f_i.empty else 10
max_c = f_c["value"].max() if not f_c.empty else 100

# 1. Глюкоза
if not f_g.empty:
    for trace in _glucose_traces(f_g):
        fig.add_trace(trace)

    fig.add_hrect(
        y0=GLUCOSE_MIN,
        y1=GLUCOSE_MAX,
        line_width=0,
        fillcolor=_ZONE_COLOR["in_range"],
        opacity=0.06,
        annotation_text="Целевой диапазон",
        annotation_position="top left",
        annotation_font_color=_ZONE_COLOR["in_range"],
    )

    for thresh in (GLUCOSE_MIN, GLUCOSE_MAX):
        fig.add_hline(
            y=thresh,
            line_dash="dash",
            line_color=_ZONE_COLOR["in_range"],
            line_width=1,
            opacity=0.5,
        )

# 2. Инсулин
if not f_i.empty:
    i_bolus = f_i[f_i["reason"] == "Болюс"]
    i_basal = f_i[f_i["reason"] == "Базал"]

    if not i_bolus.empty:
        fig.add_trace(
            go.Bar(
                x=i_bolus["date"],
                y=i_bolus["value"],
                name="Болюс (Короткий)",
                marker_color="rgba(0, 191, 255, 0.7)",
                width=1000 * 60 * 30,
                yaxis="y2",
                hovertemplate="<b>Болюс:</b> %{y} ЕД<extra></extra>",
                text=i_bolus["value"].apply(_fmt_units),
                textposition="outside",
                textfont=dict(size=11, color="#00BFFF"),
            )
        )

    if not i_basal.empty:
        fig.add_trace(
            go.Bar(
                x=i_basal["date"],
                y=i_basal["value"],
                name="Базал (Длинный)",
                marker_color="rgba(128, 128, 128, 0.6)",
                width=1000 * 60 * 30,
                yaxis="y2",
                hovertemplate="<b>Базал:</b> %{y} ЕД<extra></extra>",
                text=i_basal["value"].apply(_fmt_units),
                textposition="outside",
                textfont=dict(size=11, color="#808080"),
            )
        )

# 3. Углеводы
if not f_c.empty:
    fig.add_trace(
        go.Scatter(
            x=f_c["date"],
            y=f_c["value"],
            name="Углеводы (г)",
            mode="markers+text",
            marker=dict(
                symbol="diamond",
                color="orange",
                size=14,
                line=dict(color="darkorange", width=2),
            ),
            text=f_c["value"].astype(int).astype(str) + " г",
            textposition="top center",
            yaxis="y3",
            hovertemplate="<b>Углеводы:</b> %{y} г<extra></extra>",
        )
    )

days = pd.date_range(start=start_dt.floor("D"), end=end_dt.ceil("D"), freq="D")
for i, day_start in enumerate(days[:-1]):
    day_end = days[i + 1]
    fig.add_vrect(
        x0=day_start,
        x1=day_end,
        fillcolor="rgba(200, 200, 200, 0.15)" if i % 2 == 0 else "rgba(0, 0, 0, 0)",
        line_width=0,
        layer="below",
    )
    fig.add_vline(
        x=day_start,
        line_width=1,
        line_dash="dash",
        line_color="rgba(128, 128, 128, 0.5)",
    )

START_STR = st.session_state.start_date.strftime("%d.%m.%Y")
END_STR = st.session_state.end_date.strftime("%d.%m.%Y")
DATE_RANGE_STR = f"{START_STR} — {END_STR}"

_days = (st.session_state.end_date - st.session_state.start_date).days

# Жирные подписи дат под осью — только для коротких диапазонов,
# где тики показывают лишь время (%H:%M)
if _days <= 14:
    for day_start in days[:-1]:
        fig.add_annotation(
            x=day_start + pd.Timedelta(hours=12),
            xref="x",
            y=0,
            yref="paper",
            yshift=-28,   # пикселей вниз от нижней границы графика
            text=f"<b>{day_start.strftime('%d.%m')}</b>",
            showarrow=False,
            font=dict(size=11),
            xanchor="center",
            yanchor="top",
        )

fig.update_layout(
    title=dict(text=f"Данные за период: {DATE_RANGE_STR}", font=dict(size=18)),
    hovermode="x unified",
    barmode="overlay",
    template="plotly_white",
    legend=dict(orientation="h", yanchor="bottom",
                y=1.02, xanchor="right", x=1),
    height=750,
    margin=dict(l=20, r=20, t=60, b=45 if _days <= 14 else 20),
    xaxis=dict(
        domain=[0, 0.95],
        range=[start_dt, end_dt],
        type="date",
        **_xaxis_ticks(),
    ),
    yaxis=dict(
        title=dict(text="Глюкоза", font=dict(color="blue")),
        tickfont=dict(color="blue"),
        range=[-5, max_g * 1.1],
        tickmode="array",
        tickvals=list(range(0, int(max_g * 1.1) + 2, 2)),
    ),
    yaxis2=dict(
        title=dict(text="Инсулин", font=dict(color="#00BFFF")),
        tickfont=dict(color="#00BFFF"),
        overlaying="y",
        side="right",
        range=[0, max_i * 3],
        showgrid=False,
    ),
    yaxis3=dict(
        title=dict(text="Углеводы", font=dict(color="orange")),
        tickfont=dict(color="orange"),
        overlaying="y",
        side="right",
        position=0.98,
        range=[0, max_c * 1.5],
        showgrid=False,
    ),
)

config = {
    "toImageButtonOptions": {
        "filename": f"Дневник_Диабета_{st.session_state.start_date}_{st.session_state.end_date}",
        "format": "png",
        "scale": 2,
    },
    "displaylogo": False,
    "modeBarButtonsToRemove": ["lasso2d", "select2d", "autoScale2d"],
}

st.plotly_chart(fig, width="stretch", config=config)

_stats_section(f_g, f_i, f_c, max(1, _days + 1))

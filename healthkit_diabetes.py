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
    """Разбивает линию глюкозы на синие (норма) и красные (вне диапазона) сегменты."""
    if df.empty:
        return []

    dates = df["date"].tolist()
    values = df["value"].tolist()

    def in_range(v: float) -> bool:
        return GLUCOSE_MIN <= v <= GLUCOSE_MAX

    segments: list[tuple] = []
    seg_x = [dates[0]]
    seg_y = [values[0]]
    seg_ok = in_range(values[0])

    for pt in range(1, len(values)):
        if in_range(values[pt]) == seg_ok:
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
            seg_ok = in_range(values[pt])

    segments.append((seg_x, seg_y, seg_ok))

    result = []
    for idx, (seg_x, seg_y, ok) in enumerate(segments):
        result.append(go.Scatter(
            x=seg_x,
            y=seg_y,
            name="Глюкоза (ммоль/л)",
            mode="lines",
            line=dict(color="blue" if ok else "red", width=2, shape="spline"),
            yaxis="y1",
            legendgroup="glucose",
            showlegend=idx == 0,
            hoverinfo="skip",
        ))

    # отдельный невидимый трейс для hover — только реальные точки, без дублей
    hover_colors = ["blue" if in_range(v) else "red" for v in values]
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

    tickformat = "%H:%M\n%d.%m" if _days <= 14 else "%d.%m"

    return {"dtick": dtick, "tickformat": tickformat}


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
        fillcolor="#32CD32",
        opacity=0.08,
        annotation_text="Целевой диапазон",
        annotation_position="top left",
        annotation_font_color="#32CD32",
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

fig.update_layout(
    title=dict(text=f"Данные за период: {DATE_RANGE_STR}", font=dict(size=18)),
    hovermode="x unified",
    barmode="overlay",
    template="plotly_white",
    legend=dict(orientation="h", yanchor="bottom",
                y=1.02, xanchor="right", x=1),
    height=800,
    margin=dict(l=20, r=20, t=60, b=20),
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

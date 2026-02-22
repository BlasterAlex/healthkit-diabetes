import os
import xml.etree.ElementTree as ET
from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


FILE_PATH = "export.xml"
GLUCOSE_COLOR = "blue"

st.set_page_config(layout="wide", page_title="Дневник Диабета")

st.markdown(
    """
<style>
    footer {visibility: hidden;}
    
    div[data-testid="stDateInput"] > div,
    div[data-testid="stDateInput"] input {
        cursor: pointer !important;
    }

    div[data-testid="stDateInput"] label {
        margin-bottom: 16px;
    }
    
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


@st.cache_data
def load_data(file_path):
    if not os.path.exists(file_path):
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    context = ET.iterparse(file_path, events=("end",))
    glucose, carbs, insulin = [], [], []

    for _, elem in context:
        if elem.tag == "Record":
            record_type = elem.get("type")

            if record_type in [
                "HKQuantityTypeIdentifierBloodGlucose",
                "HKQuantityTypeIdentifierDietaryCarbohydrates",
                "HKQuantityTypeIdentifierInsulinDelivery",
            ]:

                date_val = pd.to_datetime(elem.get("startDate"))
                val = float(elem.get("value"))

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

    glucose_df = pd.DataFrame(glucose).sort_values(
        "date") if glucose else pd.DataFrame()
    carbs_df = pd.DataFrame(carbs).sort_values("date") if carbs else pd.DataFrame()
    insulin_df = pd.DataFrame(insulin).sort_values(
        "date") if insulin else pd.DataFrame()

    if not glucose_df.empty:
        glucose_df["date"] = glucose_df["date"].dt.tz_localize(None)
    if not carbs_df.empty:
        carbs_df["date"] = carbs_df["date"].dt.tz_localize(None)
    if not insulin_df.empty:
        insulin_df["date"] = insulin_df["date"].dt.tz_localize(None)

    return glucose_df, carbs_df, insulin_df


# === ИНТЕРФЕЙС ===
st.title("📊 Дневник Диабета")

df_g, df_c, df_i = load_data(FILE_PATH)

if df_g.empty and df_c.empty and df_i.empty:
    st.error(f"Файл {FILE_PATH} не найден или пуст.")
    st.stop()

all_dates = pd.concat([df["date"]
                      for df in [df_g, df_c, df_i] if not df.empty])
min_date_val = all_dates.min().date()
max_date_val = all_dates.max().date()

if "start_date" not in st.session_state:
    st.session_state.start_date = max_date_val - timedelta(days=3)
if "end_date" not in st.session_state:
    st.session_state.end_date = max_date_val

col1, col2 = st.columns([1, 2])

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
    if btn5.button("Всё время", width="stretch"):
        st.session_state.start_date = min_date_val
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

max_i = f_i["value"].max() if not f_i.empty else 10
max_c = f_c["value"].max() if not f_c.empty else 100

# 1. Глюкоза
if not f_g.empty:
    fig.add_trace(
        go.Scatter(
            x=f_g["date"],
            y=f_g["value"],
            name="Глюкоза (ммоль/л)",
            mode="lines",
            line=dict(color=GLUCOSE_COLOR, width=2, shape="spline"),
            yaxis="y1",
            hovertemplate="<b>Глюкоза:</b> %{y:.1f} ммоль/л<extra></extra>",
        )
    )
    fig.add_hrect(
        y0=3.9,
        y1=10.0,
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

midnights = pd.date_range(start=start_dt.floor("D"),
                          end=end_dt.ceil("D"), freq="D")
for midnight in midnights:
    fig.add_vline(
        x=midnight,
        line_width=1,
        line_dash="dash",
        line_color="rgba(128, 128, 128, 0.5)",
    )

START_STR = st.session_state.start_date.strftime("%d.%m.%Y")
END_STR = st.session_state.end_date.strftime("%d.%m.%Y")
DATE_RANGE_STR = f"{START_STR} — {END_STR}"

fig.update_layout(
    title=dict(text=f"Данные за период: {DATE_RANGE_STR}", font=dict(size=18)),
    hovermode="x unified",
    barmode="overlay",
    template="plotly_white",
    legend=dict(orientation="h", yanchor="bottom",
                y=1.02, xanchor="right", x=1),
    height=650,
    margin=dict(l=20, r=20, t=60, b=20),
    xaxis=dict(domain=[0, 0.95], range=[start_dt, end_dt], type="date"),
    yaxis=dict(
        title=dict(text="Глюкоза", font=dict(color=GLUCOSE_COLOR)),
        tickfont=dict(color=GLUCOSE_COLOR),
        range=[0, 15],
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
        "format": "png",
        "filename": f"Дневник_Диабета_{st.session_state.start_date}_{st.session_state.end_date}",
        "height": 800,
        "width": 1400,
        "scale": 2,
    },
    "displaylogo": False,
    "modeBarButtonsToRemove": ["lasso2d", "select2d", "autoScale2d"],
}

st.plotly_chart(fig, width="stretch", config=config)

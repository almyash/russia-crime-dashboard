import json
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from shapely.geometry import shape, mapping, MultiPolygon
from shapely.geometry.polygon import orient

# ------------------------------------------------------------------
# КОНФИГ
# ------------------------------------------------------------------
st.set_page_config(
    page_title="Взятки в России: криминальная статистика",
    page_icon="⚖️",
    layout="wide",
)

DATA_FILE = "crimes_final_geo.csv"
GEOJSON_FILE = "russia_regions.geojson"

# ------------------------------------------------------------------
# ДАННЫЕ (С КЭШИРОВАНИЕМ И ИСПРАВЛЕНИЕМ ГЕОМЕТРИИ КАРТЫ)
# ------------------------------------------------------------------
@st.cache_data
def load_data():
    return pd.read_csv(DATA_FILE)

@st.cache_data
def load_geojson_v3():
    with open(GEOJSON_FILE, encoding="utf-8") as f:
        gj = json.load(f)
    
    for feat in gj["features"]:
        geom = shape(feat["geometry"])
        # Упрощаем геометрию и лечим самопересечения через buffer(0)
        geom = geom.simplify(0.02, preserve_topology=True).buffer(0)
        # Приводим обход точек к часовой стрелке (sign=-1.0), чтобы Крым и Севастополь не заливали фон
        if geom.geom_type == "Polygon":
            geom = orient(geom, sign=-1.0)
        elif geom.geom_type == "MultiPolygon":
            geom = MultiPolygon([orient(p, sign=-1.0) for p in geom.geoms])
        feat["geometry"] = mapping(geom)
    return gj

df = load_data()
geojson = load_geojson_v3()

# ------------------------------------------------------------------
# ЗАГОЛОВОК И ПАСПОРТ ДАННЫХ
# ------------------------------------------------------------------
st.title("⚖️ Криминальная статистика России: взяточничество (2012–2022 гг.)")

with st.container(border=True):
    st.markdown(
        "**Проверяемый источник данных:** [Портал правовой статистики Генеральной прокуратуры РФ (crimestat.ru)](http://crimestat.ru/) — "
        "показатели «Предварительно расследовано преступлений по ст. 290 УК РФ (получение взятки)» и «по ст. 291 УК РФ (дача взятки)» (годовые значения на декабрь).  \n"
        "**Источник знаменателя:** [Росстат](https://rosstat.gov.ru/), таблица «Численность населения по субъектам РФ на начало года».  \n"
        "**Единицы измерения и знаменатели:** "
        "1) **Абсолютное число** — ед. (шт.); "
        "2) **Интенсивность** — число преступлений на 100 тыс. человек населения соответствующего региона в том же году (`count / population × 100 000`); "
        "3) **Удельный вес (доля в РФ)** — % от суммарного числа преступлений данного типа по всем субъектам РФ за тот же период."
    )

# ------------------------------------------------------------------
# ФИЛЬТРЫ В САЙДБАРЕ (УЛУЧШЕННЫЙ UX)
# ------------------------------------------------------------------
st.sidebar.header("⚙️ Панель управления")

all_years = sorted(df["year"].unique())
min_y, max_y = int(min(all_years)), int(max(all_years))
year_range = st.sidebar.slider(
    "Период анализа (для динамики и сводки)",
    min_value=min_y, max_value=max_y, value=(min_y, max_y), step=1
)
sel_years = [y for y in all_years if year_range[0] <= y <= year_range[1]]

all_types = sorted(df["crime_type"].unique())
sel_types = st.sidebar.multiselect("Тип преступления (статья УК РФ)", all_types, default=all_types)

all_regions = sorted(df["region"].unique())
region_mode = st.sidebar.radio(
    "Охват регионов:",
    ["Все регионы РФ (85 субъектов)", "Выбрать регионы вручную"],
    index=0,
)
if region_mode == "Все регионы РФ (85 субъектов)":
    sel_regions = all_regions
else:
    sel_regions = st.sidebar.multiselect(
        "Выберите субъекты РФ:",
        all_regions,
        default=["Москва", "Санкт-Петербург", "Московская область", "Республика Татарстан", "Краснодарский край"]
    )

st.sidebar.markdown("---")
st.sidebar.subheader("📍 Срез для Карты, Топ-15 и Сравнения")
map_year = st.sidebar.selectbox(
    "Отчётный год среза",
    sorted(df["year"].unique(), reverse=True),
    index=0,
)

metric_choice = st.sidebar.radio(
    "Основной показатель среза:",
    ["На 100 тыс. населения", "Абсолютное число преступлений", "Доля в РФ (%)"],
    index=0,
)

# Применяем фильтр
f = df[
    df["year"].isin(sel_years) &
    df["region"].isin(sel_regions) &
    df["crime_type"].isin(sel_types)
].copy()

if f.empty:
    st.warning("По выбранным фильтрам нет данных. Пожалуйста, выберите хотя бы один тип преступления и регион.")
    st.stop()

# ------------------------------------------------------------------
# БЛОК 1: 4 КЛЮЧЕВЫХ ПОКАЗАТЕЛЯ (KPI)
# ------------------------------------------------------------------
st.subheader(f"Ключевые показатели за {year_range[0]}–{year_range[1]} гг.")

c1, c2, c3, c4 = st.columns(4)

total_crimes = int(f["count"].sum())
c1.metric("Расследовано преступлений (шт.)", f"{total_crimes:,}".replace(",", " "))

# Корректный расчёт интенсивности через человеко-годы без задвоения населения
pop_unique = f.drop_duplicates(subset=["region", "year"])["population"].sum()
per100 = (total_crimes / pop_unique * 100_000) if pop_unique > 0 else float("nan")
c2.metric("Интенсивность (на 100 тыс. нас.)", f"{per100:.2f}" if pd.notna(per100) else "н/д")

rf_same = df[(df["year"].isin(sel_years)) & (df["crime_type"].isin(sel_types))]["count"].sum()
share = total_crimes / rf_same * 100 if rf_same > 0 else float("nan")
c3.metric("Доля выбранных регионов в РФ", f"{share:.1f}%" if pd.notna(share) else "н/д")

# Четвёртая аналитическая метрика: соотношение Дача / Получение
c_give = f[f["crime_type"] == "Дача взятки"]["count"].sum()
c_take = f[f["crime_type"] == "Получение взятки"]["count"].sum()
ratio_gt = (c_give / c_take) if c_take > 0 else float("nan")
c4.metric(
    "Индекс «Дача / Получение» (291/290)",
    f"{ratio_gt:.2f}" if pd.notna(ratio_gt) else "н/д",
    help="Показывает, сколько расследованных эпизодов дачи взятки (ст. 291) приходится на 1 эпизод получения (ст. 290)."
)

st.divider()

# ------------------------------------------------------------------
# БЛОК 2: ДИНАМИКА И БЕНЧМАРКИНГ (В ВКЛАДКАХ)
# ------------------------------------------------------------------
st.subheader("📈 Временная динамика и сравнительный тренд")

tab_dyn1, tab_dyn2 = st.tabs([
    "Динамика по типам преступлений (с аннотацией реформы УК РФ)",
    "Сравнение регионов со среднероссийским уровнем (на 100 тыс.)"
])

with tab_dyn1:
    ts = f.groupby(["year", "crime_type"], as_index=False)["count"].sum()
    fig_line = px.line(
        ts, x="year", y="count", color="crime_type", markers=True,
        labels={"year": "Год", "count": "Число преступлений (шт.)", "crime_type": "Состав преступления"},
        title="Динамика предварительно расследованных преступлений по ст. 290 и 291 УК РФ",
        color_discrete_map={"Получение взятки": "#d95f02", "Дача взятки": "#1b9e77"}
    )
    # Добавляем вертикальную линию реформы УК РФ 2016 года
    if 2016 >= year_range[0] and 2016 <= year_range[1]:
        fig_line.add_vline(
            x=2016.5, line_width=2, line_dash="dash", line_color="gray",
            annotation_text="ФЗ № 324-ФЗ (2016): введение ст. 291.2 (мелкая взятка до 10 тыс. ₽)",
            annotation_position="top right"
        )
    fig_line.update_layout(hovermode="x unified", legend_title_text="", xaxis=dict(dtick=1))
    st.plotly_chart(fig_line, width="stretch")

with tab_dyn2:
    default_bench = ["Москва", "Санкт-Петербург", "Волгоградская область"]
    bench_regions = st.multiselect(
        "Выберите регионы для сравнения со средним уровнем по РФ:",
        all_regions,
        default=[r for r in default_bench if r in all_regions]
    )
    # Считаем средний уровень по РФ по годам
    rf_ts = df[df["year"].isin(sel_years) & df["crime_type"].isin(sel_types)].copy()
    rf_pop_yr = rf_ts.drop_duplicates(subset=["region", "year"]).groupby("year")["population"].sum()
    rf_cnt_yr = rf_ts.groupby("year")["count"].sum()
    rf_rate_df = pd.DataFrame({
        "year": rf_pop_yr.index,
        "per_100k": (rf_cnt_yr / rf_pop_yr * 100_000).round(2),
        "Объект": "Среднее по РФ"
    })

    if bench_regions:
        reg_ts = df[
            df["year"].isin(sel_years) &
            df["region"].isin(bench_regions) &
            df["crime_type"].isin(sel_types)
        ].groupby(["year", "region"], as_index=False).agg(
            count=("count", "sum"), population=("population", "first")
        )
        reg_ts["per_100k"] = (reg_ts["count"] / reg_ts["population"] * 100_000).round(2)
        reg_ts = reg_ts.rename(columns={"region": "Объект"})
        comp_df = pd.concat([rf_rate_df, reg_ts[["year", "per_100k", "Объект"]]], ignore_index=True)
    else:
        comp_df = rf_rate_df

    fig_bench = px.line(
        comp_df, x="year", y="per_100k", color="Объект", markers=True,
        labels={"year": "Год", "per_100k": "Преступлений на 100 тыс. населения"},
        title="Интенсивность регистрируемого взяточничества: выбранные регионы vs РФ"
    )
    fig_bench.update_layout(hovermode="x unified", xaxis=dict(dtick=1))
    st.plotly_chart(fig_bench, width="stretch")

st.divider()

# ------------------------------------------------------------------
# ПОДГОТОВКА СРЕЗА ЗА MAP_YEAR ДЛЯ КАРТЫ, ТОПА И SCATTER PLOT
# ------------------------------------------------------------------
year_df = df[
    (df["year"] == map_year) &
    (df["region"].isin(sel_regions)) &
    (df["crime_type"].isin(sel_types))
].copy()

rf_year_total = df[(df["year"] == map_year) & (df["crime_type"].isin(sel_types))]["count"].sum()
rf_year_pop = df[(df["year"] == map_year)].drop_duplicates(subset=["region"])["population"].sum()
rf_avg_per100k = (rf_year_total / rf_year_pop * 100_000) if rf_year_pop > 0 else 0.0

reg_agg = (
    year_df.groupby(["region", "region_geo"], as_index=False)
    .agg(count=("count", "sum"), population=("population", "first"))
)
reg_agg = reg_agg[reg_agg["population"].notna() & (reg_agg["population"] > 0)].copy()
reg_agg["per_100k"] = (reg_agg["count"] / reg_agg["population"] * 100_000).round(2)
reg_agg["share_rf_pct"] = (reg_agg["count"] / rf_year_total * 100).round(2) if rf_year_total > 0 else 0.0

metric_col_map = {
    "На 100 тыс. населения": ("per_100k", "Преступлений на 100 тыс. населения"),
    "Абсолютное число преступлений": ("count", "Число преступлений (шт.)"),
    "Доля в РФ (%)": ("share_rf_pct", "Доля в общем числе по РФ (%)"),
}
target_col, target_label = metric_col_map[metric_choice]
types_str = ", ".join(sel_types).lower()

# ------------------------------------------------------------------
# БЛОК 3: ТОП-15 И АСИММЕТРИЯ СТ. 290 VS 291 (ДВЕ КОЛОНКИ)
# ------------------------------------------------------------------
st.subheader(f"🔍 Региональный сравнительный анализ за {map_year} г.")

col_left, col_right = st.columns(2)

with col_left:
    top_df = reg_agg.sort_values(target_col, ascending=False).head(15)
    fig_bar = px.bar(
        top_df.sort_values(target_col, ascending=True),
        x=target_col, y="region", orientation="h",
        text=target_col,
        labels={target_col: target_label, "region": ""},
        title=f"Топ-15 регионов ({metric_choice.lower()}, {map_year} г.)",
        color=target_col,
        color_continuous_scale="YlOrRd"
    )
    if metric_choice == "На 100 тыс. населения" and rf_avg_per100k > 0:
        fig_bar.add_vline(
            x=rf_avg_per100k,
            line_width=2,
            line_dash="dash",
            line_color="#00e5ff",
        )
        fig_bar.add_annotation(
            x=rf_avg_per100k,
            y=1.04,
            yref="paper",
            text=f"Среднее по РФ: {rf_avg_per100k:.2f}",
            showarrow=False,
            xanchor="left",
            xshift=6,
            font=dict(color="#00e5ff", size=12),
            bgcolor="rgba(0,0,0,0.6)",
            borderpad=3,
        )
    fig_bar.update_traces(textposition="outside", cliponaxis=False)
    fig_bar.update_layout(
        showlegend=False,
        coloraxis_showscale=False,
        height=520,
        margin=dict(r=50, t=60),
    )
    st.plotly_chart(fig_bar, width="stretch")

with col_right:
    # Строим кросс-секцию 290 vs 291 за выбранный год
    piv = df[(df["year"] == map_year) & (df["region"].isin(sel_regions))].pivot(
        index="region", columns="crime_type", values="per_100k"
    ).reset_index()
    
    if "Дача взятки" in piv.columns and "Получение взятки" in piv.columns:
        piv = piv.dropna(subset=["Дача взятки", "Получение взятки"])
        max_val = max(piv["Дача взятки"].max(), piv["Получение взятки"].max()) * 1.05
        
        fig_scat = px.scatter(
            piv, x="Получение взятки", y="Дача взятки",
            hover_name="region",
            labels={
                "Получение взятки": "Получение взятки (ст. 290), на 100 тыс. нас.",
                "Дача взятки": "Дача взятки (ст. 291), на 100 тыс. нас."
            },
            title=f"Баланс правоприменения: ст. 291 vs ст. 290 УК РФ ({map_year} г.)"
        )
        fig_scat.update_traces(marker=dict(size=9, color="#d95f02", opacity=0.8, line=dict(width=1, color="DarkSlateGrey")))
        # Биссектриса паритета y = x
        fig_scat.add_trace(
            go.Scatter(
                x=[0, max_val], y=[0, max_val],
                mode="lines",
                line=dict(color="gray", dash="dash"),
                name="Линия паритета (291 = 290)"
            )
        )
        fig_scat.update_layout(height=520, legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
        st.plotly_chart(fig_scat, width="stretch")
    else:
        st.info("Нет данных для построения графика баланса за выбранный год.")

# ------------------------------------------------------------------
# БЛОК 4: ИНТЕРАКТИВНАЯ КАРТА РЕГИОНОВ
# ------------------------------------------------------------------
st.subheader(f"🗺️ Карта регионов России за {map_year} г.")

fig_map = px.choropleth(
    reg_agg,
    geojson=geojson,
    locations="region_geo",
    featureidkey="properties.region",
    color=target_col,
    hover_name="region",
    hover_data={
        "region_geo": False,
        "count": True,
        "per_100k": True,
        "share_rf_pct": True,
        "population": ":,.0f",
    },
    color_continuous_scale="YlOrRd",
    labels={
        "count": "Преступлений (шт.)",
        "per_100k": "На 100 тыс. чел.",
        "share_rf_pct": "Доля в РФ (%)",
        "population": "Население (чел.)",
    },
    title=f"Географическое распределение: {target_label.lower()} ({types_str}), {map_year} г.",
)

fig_map.update_geos(
    visible=False,
    projection_type="conic equal area",
    projection_rotation=dict(lon=100, lat=60, roll=0),
    lataxis_range=[40, 85],
    lonaxis_range=[18, 190],
)
fig_map.update_layout(margin={"r": 0, "t": 40, "l": 0, "b": 0}, height=620)
st.plotly_chart(fig_map, width="stretch")

# ------------------------------------------------------------------
# БЛОК 5: ТАБЛИЦА ДАННЫХ И ЭКСПОРТ
# ------------------------------------------------------------------
with st.expander("📋 Показать и скачать таблицу отфильтрованных данных"):
    show = f[["region", "year", "crime_type", "count",
              "population", "per_100k", "share_rf_pct"]] \
              .sort_values(["year", "region", "crime_type"])
    st.dataframe(show, width="stretch")
    
    csv_bytes = show.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    st.download_button(
        label="⬇️ Скачать текущую выборку в CSV",
        data=csv_bytes,
        file_name=f"bribes_rf_{year_range[0]}_{year_range[1]}.csv",
        mime="text/csv",
    )

st.divider()

# ------------------------------------------------------------------
# БЛОК 6: СОДЕРЖАТЕЛЬНЫЕ ВЫВОДЫ И ОГРАНИЧЕНИЯ СРАВНЕНИЯ
# ------------------------------------------------------------------
col_concl, col_lim = st.columns(2)

with col_concl:
    st.subheader("💡 Ключевые содержательные выводы")
    st.markdown(
        """
1. **Структурный сдвиг 2016–2017 гг. (институциональный эффект):**  
   На графике динамики виден резкий обвал регистрируемых преступлений по ст. 290 и 291 УК РФ — с **10 281** ед. в 2015 г. до **3 975** ед. в 2017 г. (**−61,3%**). Причина — не реальное исчезновение коррупции, а принятие ФЗ № 324-ФЗ от 03.07.2016, который ввёл ст. 291.2 УК РФ («Мелкое взяточничество» до 10 тыс. руб.) и перетянул на себя основную массу бытовых эпизодов.
2. **Смена баланса между дачей и получением взятки:**  
   В 2012 г. расследовалось в два раза больше получений взятки, чем дач (**4 686** по ст. 290 против **2 353** по ст. 291, индекс `0.50`). К 2020–2022 гг. показатели почти сравнялись (индекс `0.92–0.97`), однако межрегиональная корреляция между ними остаётся умеренной (**r ≈ 0,38**). Это указывает на разную специализацию правоохранительных органов в регионах: в одних субъектах акцент делается на пресечении попыток дачи взятки гражданами, в других — на выявлении многоэпизодных получений взяток должностными лицами.
3. **Эффект масштаба vs интенсивность:**  
   В абсолютном выражении лидируют крупнейшие экономические центры (Москва, Московская область, Краснодарский край), но при нормировании на 100 тыс. населения в топ выходят малонаселённые северные и дальневосточные регионы (Ненецкий АО — **50,7** на 100 тыс. в 2022 г., Республика Алтай — **29,9**, Сахалинская область — **17,6**).
        """
    )

with col_lim:
    st.subheader("⚠️ Методологические ограничения сравнения")
    st.markdown(
        """
1. **Высокая латентность и «полицейский фильтр»:**  
   Показатель «предварительно расследовано преступлений» отражает пропускную способность и приоритеты следственных органов (АППГ, «палочная система»), а не истинную распространённость коррупционных сделок, где обе стороны заинтересованы в сокрытии факта.
2. **Эффект малого знаменателя (Small Numbers Problem):**  
   В субъектах с малой численностью населения (Ненецкий АО — 41,4 тыс. чел., Чукотский АО — 50 тыс. чел., Магаданская область — 136 тыс. чел.) расследование всего одного многоэпизодного уголовного дела на 15–20 эпизодов искусственно выводит регион на первое место в РФ по показателю на 100 тыс. населения.
3. **Учёт по моменту окончания расследования, а не совершения:**  
   Предварительно расследованные преступления попадают в статистику того года, когда дело направлено в суд или прекращено, даже если сами взятки передавались несколькими годами ранее.
4. **Неполнота временного ряда по отдельным территориям:**  
   Республика Крым и г. Севастополь присутствуют в расчётах интенсивности только с 2015 г. (отсутствие знаменателя Росстата на начало 2014 г.). Период исследования ограничен 2012–2022 гг. для полной сопоставимости таблиц Генпрокуратуры и Росстата.
        """
    )
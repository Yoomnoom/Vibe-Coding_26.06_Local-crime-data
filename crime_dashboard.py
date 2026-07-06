import json

import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

# ------------------------------------------------------------------
# 데이터 로드
# ------------------------------------------------------------------
CSV_PATH = "경찰청_범죄 발생 지역별 통계_20241231.csv"
GEOJSON_PATH = "skorea_sigungu_simplified.geojson"

# geojson 코드 앞 2자리 -> CSV 시도 표기
PREFIX_TO_SIDO = {
    "11": "서울", "21": "부산", "22": "대구", "23": "인천", "24": "광주",
    "25": "대전", "26": "울산", "29": "세종시", "31": "경기도", "32": "강원도",
    "33": "충북", "34": "충남", "35": "전북", "36": "전남", "37": "경북",
    "38": "경남", "39": "제주",
}
# geojson 지명이 개편으로 CSV 지명과 달라진 경우 (인천 남구 -> 미추홀구, 2018년 개칭)
NAME_ALIASES = {
    ("인천", "남구"): "미추홀구",
}


@st.cache_data
def load_data(path: str) -> pd.DataFrame:
    return pd.read_csv(path, encoding="cp949")


@st.cache_data
def load_geojson(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@st.cache_data
def build_region_table(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """지역(시도+시군구) 단위 요약 테이블과, 지역x범죄대분류 매트릭스를 만든다."""
    domestic_cols = [
        c for c in df.columns
        if c not in ("범죄대분류", "범죄중분류") and not c.startswith("외국")
    ]

    major_by_region = df.groupby("범죄대분류")[domestic_cols].sum().T  # 지역 x 대분류

    region_df = pd.DataFrame({"전체건수": major_by_region.sum(axis=1)})
    region_df["시도"] = [
        c if c == "세종시" else c.split(" ", 1)[0] for c in region_df.index
    ]
    region_df["시군구"] = [
        "-" if c == "세종시" else c.split(" ", 1)[1] for c in region_df.index
    ]

    # 안전 점수: 전체 발생건수가 적을수록 높은 점수 (percentile 기반, 0~100)
    pct_rank = region_df["전체건수"].rank(pct=True)  # 건수가 많을수록 1에 가까움
    region_df["안전점수"] = ((1 - pct_rank) * 100).round(1)
    # 전국 순위: 건수가 적은 지역이 1위(가장 안전)
    region_df["전국순위"] = region_df["전체건수"].rank(method="min").astype(int)
    region_df["전체지역수"] = len(region_df)

    return region_df, major_by_region


@st.cache_data
def build_geo_join(_geojson: dict, region_df: pd.DataFrame) -> pd.DataFrame:
    """geojson 시군구 코드를 CSV 지역 컬럼명에 매칭한다."""
    sido_to_regions = {
        sido: grp["시군구"].tolist()
        for sido, grp in region_df.groupby("시도")
    }

    rows = []
    for ft in _geojson["features"]:
        code = ft["properties"]["code"]
        name = ft["properties"]["name"]
        sido = PREFIX_TO_SIDO.get(code[:2])
        if sido is None:
            continue

        if sido == "세종시":
            rows.append({"code": code, "지역": "세종시"})
            continue

        target_name = NAME_ALIASES.get((sido, name), name)
        best_match = None
        for region in sido_to_regions.get(sido, []):
            if target_name == region or target_name.startswith(region):
                if best_match is None or len(region) > len(best_match):
                    best_match = region
        if best_match:
            rows.append({"code": code, "지역": f"{sido} {best_match}"})

    return pd.DataFrame(rows)


df = load_data(CSV_PATH)
region_cols = [c for c in df.columns if c not in ("범죄대분류", "범죄중분류")]
region_info = pd.DataFrame({"컬럼명": region_cols})
region_info[["시도", "시군구"]] = region_info["컬럼명"].str.split(" ", n=1, expand=True)

region_df, major_by_region = build_region_table(df)

st.set_page_config(page_title="경찰청 범죄 발생 지역별 통계", layout="wide")
st.title("🚓 경찰청 범죄 발생 지역별 통계 (2024.12.31 기준)")
st.caption(f"원본 데이터: {CSV_PATH}")

tab1, tab2 = st.tabs(["📊 전체 통계", "🏠 우리 동네 안전지도"])

# ====================================================================
# TAB 1. 기존 전체 통계 대시보드
# ====================================================================
with tab1:
    st.sidebar.header("필터 (전체 통계 탭)")
    st.sidebar.caption("💡 아무 것도 선택하지 않으면 '전체'로 간주합니다. 여러 개를 함께 선택할 수 있습니다.")

    대분류_목록 = sorted(df["범죄대분류"].unique().tolist())
    selected_대분류_list = st.sidebar.multiselect("범죄 대분류 (복수 선택 가능)", 대분류_목록)

    filtered_by_major = (
        df if not selected_대분류_list else df[df["범죄대분류"].isin(selected_대분류_list)]
    )

    중분류_목록 = sorted(filtered_by_major["범죄중분류"].unique().tolist())
    selected_중분류_list = st.sidebar.multiselect("범죄 중분류 (복수 선택 가능)", 중분류_목록)

    filtered_df = (
        filtered_by_major if not selected_중분류_list
        else filtered_by_major[filtered_by_major["범죄중분류"].isin(selected_중분류_list)]
    )

    시도_목록 = sorted(region_info["시도"].unique().tolist())
    selected_시도_list = st.sidebar.multiselect("시/도 (복수 선택 가능)", 시도_목록)

    if selected_시도_list:
        시군구_후보 = region_info[region_info["시도"].isin(selected_시도_list)]
    else:
        시군구_후보 = region_info
    시군구_옵션 = sorted(시군구_후보["컬럼명"].tolist())
    selected_시군구_list = st.sidebar.multiselect(
        "시/군/구 (복수 선택 가능, 전체 지역명으로 표시)", 시군구_옵션
    )

    top_n = st.sidebar.slider("상위 지역 개수 (Top N)", min_value=5, max_value=30, value=15)

    if selected_시군구_list:
        target_cols = selected_시군구_list
    elif selected_시도_list:
        target_cols = region_info.loc[region_info["시도"].isin(selected_시도_list), "컬럼명"].tolist()
    else:
        target_cols = region_info["컬럼명"].tolist()

    # 시/군/구를 딱 하나만 콕 짚었을 때만, 안전지도 탭 기본값도 그 지역으로 맞춘다.
    tab1_picked_region = selected_시군구_list[0] if len(selected_시군구_list) == 1 else None

    if tab1_picked_region and tab1_picked_region != st.session_state.get("_last_tab1_region"):
        st.session_state["_last_tab1_region"] = tab1_picked_region
        st.session_state["region_choice"] = tab1_picked_region
    elif tab1_picked_region is None:
        st.session_state["_last_tab1_region"] = None


    region_sum = filtered_df[target_cols].sum().sort_values(ascending=False)
    region_sum_df = region_sum.reset_index()
    region_sum_df.columns = ["지역", "발생건수"]

    col1, col2, col3 = st.columns(3)
    col1.metric("선택된 범죄 건수 합계", f"{int(region_sum_df['발생건수'].sum()):,}")
    col2.metric("대상 지역 수", f"{len(target_cols)}")
    col3.metric("최다 발생 지역", region_sum_df.iloc[0]["지역"] if len(region_sum_df) else "-")

    st.subheader(f"지역별 발생 건수 Top {top_n}")
    top_df = region_sum_df.head(top_n)
    fig_bar = px.bar(
        top_df, x="발생건수", y="지역", orientation="h", text="발생건수",
        color="발생건수", color_continuous_scale="Reds",
    )
    fig_bar.update_layout(yaxis={"categoryorder": "total ascending"}, height=500)
    st.plotly_chart(fig_bar, use_container_width=True)

    # 대분류를 특정 값으로 좁혔다면 그 안의 중분류로, 아니면 대분류 기준으로 구성비를 본다.
    if not selected_대분류_list:
        comp_source, comp_group_col = df, "범죄대분류"
    else:
        comp_source, comp_group_col = filtered_by_major, "범죄중분류"

    if not selected_시도_list:
        scope_label = "전국"
    elif len(selected_시도_list) == 1:
        scope_label = selected_시도_list[0] if not selected_시군구_list else selected_시군구_list[0]
    else:
        scope_label = "선택한 " + "·".join(selected_시도_list)

    st.subheader(f"{scope_label} {comp_group_col}별 발생 건수 (선택한 필터 반영)")
    comp_sum = comp_source.groupby(comp_group_col)[target_cols].sum().sum(axis=1).sort_values(ascending=False)
    comp_sum_df = comp_sum.reset_index()
    comp_sum_df.columns = [comp_group_col, "발생건수"]
    fig_pie = px.pie(comp_sum_df, names=comp_group_col, values="발생건수", hole=0.4)
    st.plotly_chart(fig_pie, use_container_width=True)

    st.subheader(f"시/도 × {comp_group_col} 히트맵 (선택한 범죄 필터 반영)")
    heat_categories = comp_source[comp_group_col].unique()
    heat_sido_index = sorted(selected_시도_list) if selected_시도_list else sorted(region_info["시도"].unique())
    sido_major = pd.DataFrame(index=heat_sido_index)
    for sido in sido_major.index:
        cols = region_info.loc[region_info["시도"] == sido, "컬럼명"].tolist()
        sido_major.loc[sido, heat_categories] = (
            comp_source.groupby(comp_group_col)[cols].sum().sum(axis=1)
        )
    sido_major = sido_major.astype(float)
    fig_heat = px.imshow(
        sido_major, aspect="auto", color_continuous_scale="YlOrRd",
        labels=dict(x=comp_group_col, y="시/도", color="발생건수"),
    )
    fig_heat.update_layout(height=700 if len(heat_sido_index) > 3 else 250)
    st.plotly_chart(fig_heat, use_container_width=True)

    st.subheader("원본 데이터 보기")
    show_cols = ["범죄대분류", "범죄중분류"] + target_cols
    st.dataframe(filtered_df[show_cols], use_container_width=True)

# ====================================================================
# TAB 2. 우리 동네 안전지도
# ====================================================================
with tab2:
    st.info(
        "⚠️ 안전 점수는 **인구수 보정 없이** 지역별 범죄 발생 총건수만으로 산출한 상대 점수입니다. "
        "인구가 많은 지역은 절대 건수가 커져 점수가 낮게 나올 수 있으니 참고용으로만 활용하세요.",
        icon="⚠️",
    )

    # --------------------------------------------------------------
    # 1) 주소(지역) 검색
    # --------------------------------------------------------------
    st.subheader("🔍 우리 동네 검색")
    all_regions = sorted(region_df.index.tolist())
    if "region_choice" not in st.session_state or st.session_state["region_choice"] not in all_regions:
        st.session_state["region_choice"] = "서울 강남구" if "서울 강남구" in all_regions else all_regions[0]
    selected_region = st.selectbox(
        "지역을 검색하거나 선택하세요 (예: 서울 강남구)", all_regions, key="region_choice",
    )
    st.caption("💡 왼쪽 '전체 통계' 탭에서 시/도·시/군/구를 고르면 여기 기본 지역도 함께 바뀝니다. "
               "이후 이 드롭다운에서 직접 다른 지역을 골라도 그대로 유지됩니다.")

    row = region_df.loc[selected_region]

    # --------------------------------------------------------------
    # 2) 안전 점수 / 3) 전국 순위
    # --------------------------------------------------------------
    score = row["안전점수"]
    rank = int(row["전국순위"])
    total_regions = int(row["전체지역수"])
    total_count = int(row["전체건수"])

    c1, c2, c3 = st.columns(3)
    c1.metric("안전 점수 (100점 만점)", f"{score:.1f}점")
    c2.metric("전국 순위 (안전한 순)", f"{rank} / {total_regions}위")
    c3.metric("연간 범죄 발생 총건수", f"{total_count:,}건")

    if score >= 80:
        st.success(f"**{selected_region}**은(는) 전국에서 비교적 안전한 지역입니다. 👍")
    elif score >= 40:
        st.warning(f"**{selected_region}**은(는) 전국 평균 수준의 범죄 발생 지역입니다.")
    else:
        st.error(f"**{selected_region}**은(는) 상대적으로 범죄 발생이 많은 지역입니다.")

    # --------------------------------------------------------------
    # 4) 범죄 유형별 비율
    # --------------------------------------------------------------
    st.subheader(f"📌 {selected_region} 범죄 유형별 비율")
    region_major = major_by_region.loc[selected_region]
    region_major_df = region_major.reset_index()
    region_major_df.columns = ["범죄대분류", "발생건수"]
    region_major_df = region_major_df[region_major_df["발생건수"] > 0].sort_values(
        "발생건수", ascending=False
    )

    colA, colB = st.columns([1, 1])
    with colA:
        fig_region_pie = px.pie(
            region_major_df, names="범죄대분류", values="발생건수", hole=0.4,
            title="범죄대분류 구성비",
        )
        st.plotly_chart(fig_region_pie, use_container_width=True)
    with colB:
        fig_region_bar = px.bar(
            region_major_df, x="발생건수", y="범죄대분류", orientation="h",
            text="발생건수", color="발생건수", color_continuous_scale="Blues",
            title="범죄대분류별 발생건수",
        )
        fig_region_bar.update_layout(yaxis={"categoryorder": "total ascending"})
        st.plotly_chart(fig_region_bar, use_container_width=True)

    # --------------------------------------------------------------
    # 5) 비슷한 지역 비교
    # --------------------------------------------------------------
    st.subheader("🤝 안전 점수가 비슷한 지역 Top 5")
    others = region_df.drop(index=selected_region).copy()
    others["점수차이"] = (others["안전점수"] - score).abs()
    similar = others.sort_values("점수차이").head(5)
    similar_display = similar[["안전점수", "전국순위", "전체건수"]].reset_index()
    similar_display.columns = ["지역", "안전점수", "전국순위", "발생건수"]
    st.dataframe(similar_display, use_container_width=True, hide_index=True)

    compare_regions = [selected_region] + similar.index.tolist()
    compare_df = region_df.loc[compare_regions, ["안전점수"]].reset_index()
    compare_df.columns = ["지역", "안전점수"]
    fig_compare = px.bar(
        compare_df, x="안전점수", y="지역", orientation="h", text="안전점수",
        color="지역", color_discrete_sequence=px.colors.qualitative.Set2,
    )
    fig_compare.update_layout(showlegend=False, height=350)
    st.plotly_chart(fig_compare, use_container_width=True)

    # --------------------------------------------------------------
    # 6) 지도 시각화 (히트맵 / 코로플레스)
    # --------------------------------------------------------------
    st.subheader(f"🗺️ {selected_region} 안전 점수 지도")
    zoom_to_selected = st.checkbox("선택 지역으로 지도 확대해서 보기", value=True)

    geojson = load_geojson(GEOJSON_PATH)
    geo_join = build_geo_join(geojson, region_df)
    geo_join = geo_join.merge(
        region_df[["안전점수", "전체건수", "전국순위"]], left_on="지역", right_index=True, how="left"
    )

    fig_map = px.choropleth(
        geo_join,
        geojson=geojson,
        locations="code",
        featureidkey="properties.code",
        color="안전점수",
        color_continuous_scale="RdYlGn",
        range_color=(0, 100),
        hover_name="지역",
        hover_data={"code": False, "전체건수": True, "전국순위": True, "안전점수": True},
    )

    selected_code_series = geo_join.loc[geo_join["지역"] == selected_region, "code"]
    selected_feature = None
    if not selected_code_series.empty:
        selected_code = selected_code_series.iloc[0]
        selected_feature = next(
            (ft for ft in geojson["features"] if ft["properties"]["code"] == selected_code), None
        )

    if selected_feature is not None:
        # 선택 지역 테두리를 굵게 강조 표시
        fig_map.add_trace(go.Choropleth(
            geojson=geojson,
            locations=[selected_feature["properties"]["code"]],
            z=[1],
            featureidkey="properties.code",
            colorscale=[[0, "rgba(0,0,0,0)"], [1, "rgba(0,0,0,0)"]],
            showscale=False,
            marker_line_width=4,
            marker_line_color="#1035c9",
            hoverinfo="skip",
        ))

        def _flatten_coords(coords):
            if isinstance(coords[0], (int, float)):
                yield coords
            else:
                for sub in coords:
                    yield from _flatten_coords(sub)

        pts = list(_flatten_coords(selected_feature["geometry"]["coordinates"]))
        center_lon = sum(p[0] for p in pts) / len(pts)
        center_lat = sum(p[1] for p in pts) / len(pts)

        if zoom_to_selected:
            fig_map.update_geos(visible=False, center=dict(lat=center_lat, lon=center_lon), projection_scale=25)
        else:
            fig_map.update_geos(fitbounds="locations", visible=False)
    else:
        fig_map.update_geos(fitbounds="locations", visible=False)

    fig_map.update_layout(height=700, margin={"r": 0, "t": 0, "l": 0, "b": 0})
    st.plotly_chart(fig_map, use_container_width=True)
    st.caption(
        "초록색일수록 안전 점수가 높고(범죄 발생 적음), 빨간색일수록 낮습니다(범죄 발생 많음). "
        "파란색 굵은 테두리가 현재 선택한 지역입니다."
    )

# -*- coding: utf-8 -*-
import re
import time
from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from curl_cffi import requests

# ---------------------------------------------------------------
# 頁面設定
# 圖表使用 Plotly（由瀏覽器渲染），不需要再用 !wget 下載中文字型
# ---------------------------------------------------------------
st.set_page_config(page_title="MOMO 價格分析", page_icon="🛒", layout="wide")

API_URL = "https://apisearch.momoshop.com.tw/momoSearchCloud/moec/textSearch"
HOME_URL = "https://www.momoshop.com.tw/"
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Content-Type": "application/json;charset=UTF-8",
    "Origin": "https://www.momoshop.com.tw",
    "Referer": "https://www.momoshop.com.tw/",
}


def build_payload(keyword: str, page: int) -> dict:
    return {
        "host": "momoshop",
        "flag": "searchEngine",
        "data": {
            "searchValue": keyword,
            "searchType": "1",
            "cateLevel": "-1",
            "curPage": str(page),
            "priceS": "0",
            "priceE": "9999999",
            "showType": "chessboardType",
            "isFuzzy": "0",
            "rtnCateDatainfo": {
                "cateCode": "",
                "cateLv": "-1",
                "keyword": keyword,
                "curPage": str(page),
                "historyDoPush": "false",
                "timestamp": int(time.time() * 1000),
            },
            "flag": 2018,
            "serviceCode": "MT01",
            "addressSearchData": {},
        },
    }


@st.cache_data(show_spinner=False, ttl=600)
def crawl_momo(keyword: str, pages: int, delay: float = 1.0) -> pd.DataFrame:
    """爬取 MOMO 搜尋結果，回傳 品名 / 價格 / 頁碼 的 DataFrame"""
    session = requests.Session(impersonate="chrome")  # 模擬 Chrome 的 TLS 指紋
    session.get(HOME_URL, headers=HEADERS)  # 先取得 cookie

    rows = []
    for page in range(1, pages + 1):
        resp = session.post(API_URL, headers=HEADERS, json=build_payload(keyword, page))
        if resp.status_code != 200:
            raise RuntimeError(f"第 {page} 頁請求失敗（HTTP {resp.status_code}）：{resp.text[:200]}")
        products = resp.json().get("rtnSearchData", {}).get("goodsInfoList", [])
        if not products:  # 沒有更多資料就提早結束
            break
        for p in products:
            rows.append(
                {
                    "品名": p.get("goodsName", ""),
                    "價格": p.get("goodsPrice", ""),
                    "頁碼": page,
                }
            )
        time.sleep(delay)

    df = pd.DataFrame(rows, columns=["品名", "價格", "頁碼"])
    if df.empty:
        return df

    # 價格清洗：只留下數字
    df["價格"] = df["價格"].astype(str).str.replace(r"[^\d]", "", regex=True)
    df = df[df["價格"] != ""].copy()
    df["價格"] = df["價格"].astype(int)
    return df.reset_index(drop=True)


def extract_brand(name: str) -> str:
    """從品名粗略擷取品牌：優先取【】內文字，否則取第一個中英文詞"""
    name = str(name).strip()
    m = re.match(r"^[【\[]([^】\]]+)[】\]]", name)
    if m:
        return m.group(1)[:10]
    m = re.match(r"^([A-Za-z0-9\u4e00-\u9fff]+)", name)
    return m.group(1)[:8] if m else "其他"


def add_price_range(df: pd.DataFrame, bins: int) -> pd.DataFrame:
    df = df.copy()
    df["價格區間"] = pd.qcut(df["價格"], q=min(bins, df["價格"].nunique()), duplicates="drop")
    df["價格區間"] = df["價格區間"].apply(lambda i: f"{int(i.left)}~{int(i.right)}")
    return df


# ---------------------------------------------------------------
# UI
# ---------------------------------------------------------------
st.title("🛒 MOMO 購物網價格分析")

with st.sidebar:
    st.header("搜尋條件")
    keyword = st.text_input("產品名稱", value="行動電源")
    pages = st.number_input("爬取頁數", min_value=1, max_value=20, value=3, step=1)
    delay = st.slider("每頁間隔秒數", 0.5, 3.0, 1.0, 0.5)
    bins = st.slider("價格區間數（圓餅圖／旭日圖）", 3, 8, 5)
    top_n = st.slider("折線圖顯示筆數上限", 20, 500, 70, 10)
    run = st.button("開始爬取", type="primary", use_container_width=True)

if run:
    if not keyword.strip():
        st.warning("請輸入產品名稱")
        st.stop()
    try:
        with st.spinner("爬取中，請稍候…"):
            st.session_state["df"] = crawl_momo(keyword.strip(), int(pages), float(delay))
            st.session_state["keyword"] = keyword.strip()
    except Exception as e:
        st.error(f"爬取失敗：{e}")
        st.stop()

df = st.session_state.get("df")
kw = st.session_state.get("keyword", keyword)

if df is None:
    st.info("請在左側輸入產品名稱與頁數，然後按「開始爬取」。")
    st.stop()
if df.empty:
    st.warning("沒有抓到任何商品，請換個關鍵字或稍後再試。")
    st.stop()

# ---- 統計 ----
mean_price = df["價格"].mean()
c1, c2, c3, c4 = st.columns(4)
c1.metric("商品數", f"{len(df):,}")
c2.metric("平均價格", f"{mean_price:,.0f}")
c3.metric("最高價格", f"{df['價格'].max():,}")
c4.metric("最低價格", f"{df['價格'].min():,}")

df = add_price_range(df, bins)
df["品牌"] = df["品名"].apply(extract_brand)

tab1, tab2, tab3, tab4 = st.tabs(["📈 折線圖", "🥧 圓餅圖", "☀️ 旭日圖", "📄 資料表"])

# ---- 折線圖 ----
with tab1:
    sub = df.head(top_n).reset_index().rename(columns={"index": "商品序號"})
    fig = px.line(sub, x="商品序號", y="價格", hover_data=["品名"], markers=True)
    fig.add_hline(
        y=mean_price,
        line_dash="dash",
        line_color="red",
        annotation_text=f"平均 {mean_price:,.0f}",
    )
    fig.update_layout(
        title=f"MOMO 電商網站上「{kw}」售價（前 {len(sub)} 筆）",
        xaxis_title="store id",
        yaxis_title="price",
        height=550,
    )
    st.plotly_chart(fig, use_container_width=True)

# ---- 圓餅圖 ----
with tab2:
    pie_df = df["價格區間"].value_counts().reset_index()
    pie_df.columns = ["價格區間", "商品數"]
    # 依區間下限排序
    pie_df["_s"] = pie_df["價格區間"].str.split("~").str[0].astype(int)
    pie_df = pie_df.sort_values("_s").drop(columns="_s")
    fig = px.pie(pie_df, names="價格區間", values="商品數", hole=0.3)
    fig.update_traces(textinfo="percent+label", sort=False)
    fig.update_layout(title=f"「{kw}」價格區間占比", height=550)
    st.plotly_chart(fig, use_container_width=True)

# ---- 旭日圖 ----
with tab3:
    top_brands = df["品牌"].value_counts().head(15).index
    sun_df = df.copy()
    sun_df["品牌"] = sun_df["品牌"].where(sun_df["品牌"].isin(top_brands), "其他")
    sun_df = sun_df.groupby(["價格區間", "品牌"], as_index=False).agg(
        商品數=("品名", "count"), 平均價格=("價格", "mean")
    )
    fig = px.sunburst(
        sun_df,
        path=["價格區間", "品牌"],
        values="商品數",
        color="平均價格",
        color_continuous_scale="Blues",
    )
    fig.update_layout(title=f"「{kw}」價格區間 → 品牌 分布", height=650)
    st.plotly_chart(fig, use_container_width=True)
    st.caption("品牌由品名自動擷取（【】內文字或第一個詞），僅供參考；品牌數過多時，只顯示前 15 名，其餘歸為「其他」。")

# ---- 資料表 ----
with tab4:
    st.dataframe(df[["品名", "價格", "頁碼", "價格區間", "品牌"]], use_container_width=True)
    csv = df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    st.download_button(
        "下載 CSV",
        data=csv,
        file_name=f"MOMO_{kw}_{datetime.now():%Y%m%d}.csv",
        mime="text/csv",
    )

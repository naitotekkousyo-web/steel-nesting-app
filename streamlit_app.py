import streamlit as st
import pandas as pd
import requests
import io
import datetime
import json

# ==========================================
# 1. 設定とマスター読み込み
# ==========================================
SHEET_ID = "1vyjK-jW-5Nl0VRHZRUyKlNAqIaO49NUxe3-kwvTtSUg"
SHEET_NAME = "master"
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={SHEET_NAME}"

def clean_text(t):
    if not t: return ""
    return str(t).upper().replace("*","X").replace("×","X").replace(" ","").strip()

@st.cache_data(ttl=600)
def load_master():
    try:
        response = requests.get(SHEET_URL)
        response.encoding = 'utf-8'
        df = pd.read_csv(io.StringIO(response.text))
        df = df.iloc[:, [0, 1]]
        df.columns = ['サイズ', '単重']
        df['サイズ_KEY'] = df['サイズ'].apply(clean_text)
        df['単重'] = pd.to_numeric(df['単重'], errors='coerce')
        df = df.drop_duplicates(subset='size_KEY' if 'size_KEY' in df else 'サイズ_KEY')
        return df.dropna(subset=['単重']).set_index('サイズ_KEY')[['サイズ', '単重']].to_dict('index')
    except: return {}

# ==========================================
# 2. ロジック & Excel出力用関数
# ==========================================
def calculate_nesting_with_marks(required_parts, available_stocks, kerf, mode, min_waste, max_waste):
    working_list = sorted(required_parts, key=lambda x: x['len'], reverse=True) if mode == "ロス削減重視" else required_parts[:]
    results = []
    remaining_parts = working_list[:]
    while remaining_parts:
        best_stock, best_indices, best_waste = None, [], float('inf')
        for s_len in sorted(available_stocks, reverse=True):
            temp_bin, temp_indices, temp_remain = [], [], s_len
            for i, part in enumerate(remaining_parts):
                if temp_remain >= part['len'] + kerf:
                    temp_bin.append(part)
                    temp_remain -= (part['len'] + kerf)
                    temp_indices.append(i)
            if temp_bin and temp_remain < best_waste:
                best_waste, best_stock, best_indices = temp_remain, s_len, temp_indices
        if best_stock:
            chosen_parts = [remaining_parts[i] for i in best_indices]
            for i in sorted(best_indices, reverse=True): remaining_parts.pop(i)
            results.append({"stock_len": best_stock, "parts": chosen_parts, "waste": best_waste})
        else: break
    return results

def to_excel_with_auto_width(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Sheet1')
        worksheet = writer.sheets['Sheet1']
        for i, col in enumerate(df.columns):
            column_len = max(df[col].astype(str).map(len).max(), len(col)) + 3
            worksheet.set_column(i, i, column_len)
    return output.getvalue()

# ==========================================
# 3. 画面構成
# ==========================================
st.set_page_config(page_title="鋼材一括取り合わせシステム", layout="wide")
st.title("🏗️ 鋼材一括取り合わせ・重量計算システム")
st.warning("【免責事項】計算結果は目安です。実際の切断前には必ず再確認を行ってください。")

master_dict = load_master()
size_options = ["(未選択)"] + [v['サイズ'] for v in master_dict.values()]

if "rows" not in st.session_state: st.session_state.rows = 1
if "calc_results" not in st.session_state: st.session_state.calc_results = None

with st.sidebar:
    st.header("🏢 物件情報")
    pj_name = st.text_input("物件名・現場名", placeholder="例：〇〇邸新築工事")
    st.divider()
    st.header("⚙️ 計算設定")
    if st.button("🔄 マスター情報を強制更新"):
        st.cache_data.clear()
        st.rerun()
    calc_mode = st.radio("計算モード", ["ロス削減重視", "カット数削減重視"])
    default_kerf = st.number_input("切断シロ (mm)", value=5)
    selected_stocks = [L for L in range(6000, 13000, 1000) if st.checkbox(f"{L}mm", value=True, key=f"stock_{L}")]
    st.divider()
    if st.button("🔴 全てのリセット", use_container_width=True):
        st.session_state.rows = 1
        st.session_state.calc_results = None
        st.rerun()

st.write("### 1. 切断リスト入力")
input_data_list = []
for i in range(st.session_state.rows):
    with st.container():
        c1, c2 = st.columns([1, 2])
        with c1:
            s_size = st.selectbox(f"サイズ選択 {i+1}", options=size_options, key=f"size_sel_{i}")
            m_data = master_dict.get(clean_text(s_size), {"サイズ": "未選択", "単重": 0.0})
            if s_size != "(未選択)": st.info(f"単重: {m_data['単重']} kg/m")
        with c2:
            init_df = pd.DataFrame([{"マーク": "", "長さ(mm)": None, "本数": None} for _ in range(3)])
            edited_df = st.data_editor(init_df, num_rows="dynamic", key=f"editor_{i}", use_container_width=True)
        if s_size != "(未選択)":
            input_data_list.append({"size_name": m_data['サイズ'], "unit_weight": m_data['単重'], "df": edited_df})
    st.divider()
st.button("➕ 鋼種を増やす", on_click=lambda: setattr(st.session_state, 'rows', st.session_state.rows + 1))

if st.button("🚀 計算実行", type="primary"):
    results_data = []
    for data in input_data_list:
        df = data['df'].dropna(subset=["長さ(mm)", "本数"])
        parts = []
        for _, row in df.iterrows():
            try:
                l, n, m = float(row["長さ(mm)"]), int(row["本数"]), str(row["マーク"])
                for _ in range(n): parts.append({"len": l, "mark": m})
            except: continue
        if parts:
            res = calculate_nesting_with_marks(parts, selected_stocks, default_kerf, calc_mode, 0, 9999)
            results_data.append({"size": data['size_name'], "unit_w": data['unit_weight'], "nesting": res})
    st.session_state.calc_results = results_data

# ==========================================
# 4. 結果表示
# ==========================================
if st.session_state.calc_results:
    st.write("### 2. 計算結果")
    
    total_order_data = [] # 集計用
    
    for item in st.session_state.calc_results:
        with st.expander(f"📦 {item['size']}", expanded=True):
            # バー表示
            for idx, r in enumerate(item['nesting']):
                st.write(f"**No.{idx+1} (定尺:{r['stock_len']}mm)**")
                # 黒白バーチャート表示
                ratio_list = [(p['len']/r['stock_len'])*100 for p in r['parts']]
                bar_html = f'<div style="display: flex; width: 100%; height: 30px; background: #fff; border: 2px solid #000; margin-bottom: 5px;">'
                for p in r['parts']:
                    w = (p['len']/r['stock_len'])*100
                    bar_html += f'<div style="width: {w}%; background: #333; border-right: 1px solid #fff;"></div>'
                bar_html += '</div>'
                st.markdown(bar_html, unsafe_allow_html=True)
                # テキスト詳細
                txt = " / ".join([f"({i+1}) {p['mark']}:{int(p['len'])}mm" for i, p in enumerate(r['parts'])])
                st.caption(f"{txt} [端材:{int(r['waste'])}mm]")
            
            # 【新規】鋼種ごとの集計
            counts = pd.Series([r['stock_len'] for r in item['nesting']]).value_counts().sort_index()
            st.write("📌 **この鋼種の発注内訳**")
            summary_df = pd.DataFrame({"定尺(mm)": counts.index, "必要本数": counts.values})
            st.table(summary_df)
            for s_len, count in counts.items():
                total_order_data.append({"物件名": pj_name, "鋼種": item['size'], "定尺(mm)": s_len, "本数": count})

    # 帳票出力セクション
    st.write("### 3. 帳票出力")
    today = datetime.date.today().strftime("%Y%m%d")
    
    # 指示書データ(Excel用)
    inst_rows = []
    for item in st.session_state.calc_results:
        for idx, r in enumerate(item['nesting']):
            inst_rows.append({
                "物件名": pj_name, "鋼種": item['size'], "No": idx+1, "定尺(mm)": r['stock_len'],
                "切断構成": " / ".join([f"{p['mark']}:{int(p['len'])}mm" for p in r['parts']]),
                "端材(mm)": int(r['waste'])
            })
    
    c1, c2 = st.columns(2)
    with c1:
        st.info("📊 **発注書**")
        st.download_button("Excel保存", to_excel_with_auto_width(pd.DataFrame(total_order_data)), f"Order_{today}.xlsx")
    with c2:
        st.info("✂️ **加工指示書**")
        st.download_button("Excel保存 (列幅自動調整)", to_excel_with_auto_width(pd.DataFrame(inst_rows)), f"CutList_{today}.xlsx")

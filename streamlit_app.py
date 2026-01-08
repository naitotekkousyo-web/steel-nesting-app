import streamlit as st
import pandas as pd
import requests
import io
import datetime

# ==========================================
# 1. ユーティリティ関数
# ==========================================
def clean_text(t):
    if not t: return ""
    return str(t).upper().replace("*","X").replace("×","X").replace(" ","").strip()

# ==========================================
# 2. マスター読み込み
# ==========================================
SHEET_ID = "1vyjK-jW-5Nl0VRHZRUyKlNAqIaO49NUxe3-kwvTtSUg"
SHEET_NAME = "master"
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={SHEET_NAME}"

@st.cache_data(ttl=300)
def load_master():
    try:
        response = requests.get(SHEET_URL)
        response.encoding = 'utf-8'
        df = pd.read_csv(io.StringIO(response.text))
        df = df.iloc[:, [0, 1]]
        df.columns = ['サイズ', '単重']
        df['サイズ_KEY'] = df['サイズ'].apply(clean_text)
        df['単重'] = pd.to_numeric(df['単重'], errors='coerce')
        df = df.drop_duplicates(subset='サイズ_KEY')
        return df.dropna(subset=['単重']).set_index('サイズ_KEY')[['サイズ', '単重']].to_dict('index')
    except Exception:
        return {}

# ==========================================
# 3. ロジック：最短定尺優先
# ==========================================
def calculate_nesting_optimal(required_parts, available_stocks, kerf, min_waste, max_waste):
    remaining_parts = sorted(required_parts, key=lambda x: x['len'], reverse=True)
    results = []
    stocks_asc = sorted(available_stocks)

    while remaining_parts:
        best_fit = None
        for s_len in stocks_asc:
            temp_parts_indices = []
            current_free = s_len
            for i, part in enumerate(remaining_parts):
                needed = part['len'] + (kerf if temp_parts_indices else 0)
                if current_free >= needed:
                    temp_parts_indices.append(i)
                    current_free -= (part['len'] + kerf)
            
            if temp_parts_indices:
                total_parts_len = sum(remaining_parts[i]['len'] for i in temp_parts_indices)
                waste = s_len - total_parts_len - (len(temp_parts_indices)-1)*kerf
                if (min_waste <= waste <= max_waste) or (waste <= kerf):
                    best_fit = {"stock_len": s_len, "indices": temp_parts_indices, "waste": int(waste)}
                    break
        
        if best_fit:
            chosen_parts = [remaining_parts[i] for i in best_fit["indices"]]
            for i in sorted(best_fit["indices"], reverse=True):
                remaining_parts.pop(i)
            results.append({"stock_len": best_fit["stock_len"], "parts": chosen_parts, "waste": best_fit["waste"]})
        else:
            if remaining_parts:
                part = remaining_parts.pop(0)
                max_s = max(available_stocks)
                results.append({"stock_len": max_s, "parts": [part], "waste": int(max_s - part['len'])})
            else: break
    return results

# ==========================================
# 4. 画面構成
# ==========================================
st.set_page_config(page_title="鋼材一括取り合わせシステム", layout="wide")
st.title("🏗️ 鋼材一括取り合わせ・重量計算システム")

master_dict = load_master()
size_options = ["(未選択)"] + [v['サイズ'] for v in master_dict.values()]

if "rows" not in st.session_state: st.session_state.rows = 1
if "calc_results" not in st.session_state: st.session_state.calc_results = None

with st.sidebar:
    st.header("🏢 物件情報")
    pj_name = st.text_input("物件名・現場名", placeholder="例：〇〇邸新築工事", key="pj_name_input")
    st.divider()
    default_kerf = st.number_input("切断シロ (mm)", value=5, step=1)
    st.write("残材許容範囲 (mm)")
    c_w1, c_w2 = st.columns(2)
    with c_w1: min_waste = st.number_input("最小", value=10, step=10)
    with c_w2: max_waste = st.number_input("最大", value=1000, step=100)
    st.write("使用する定尺長さ")
    stock_lengths = sorted([L for L in range(6000, 13000, 1000)])
    selected_stocks = [L for L in stock_lengths if st.checkbox(f"{L}mm", value=True, key=f"stock_{L}")]

st.write("### 1. 切断リスト入力")
input_data_list = []
for i in range(st.session_state.rows):
    with st.container():
        c1, c2 = st.columns([1, 2])
        with c1:
            s_size = st.selectbox(f"サイズ選択 {i+1}", options=size_options, key=f"size_sel_{i}")
            m_data = master_dict.get(clean_text(s_size), {"サイズ": "未選択", "単重": 0.0})
        with c2:
            init_df = pd.DataFrame([{"マーク": "", "長さ(mm)": None, "本数": None} for _ in range(3)])
            edited_df = st.data_editor(init_df, num_rows="dynamic", key=f"editor_{i}", use_container_width=True)
        if s_size != "(未選択)":
            input_data_list.append({"size_name": m_data['サイズ'], "unit_weight": m_data['単重'], "df": edited_df})
    st.divider()

st.button("➕ 鋼種を増やす", on_click=lambda: setattr(st.session_state, 'rows', st.session_state.rows + 1))

if st.button("🚀 計算実行", type="primary"):
    if not selected_stocks: st.error("定尺長さを選択してください。")
    else:
        results_data = []
        for data in input_data_list:
            df_valid = data['df'].dropna(subset=["長さ(mm)", "本数"])
            parts = []
            for _, row in df_valid.iterrows():
                try:
                    l, n, m = float(row["長さ(mm)"]), int(row["本数"]), str(row["マーク"])
                    for _ in range(n): parts.append({"len": l, "mark": m})
                except: continue
            if parts:
                res = calculate_nesting_optimal(parts, selected_stocks, default_kerf, min_waste, max_waste)
                results_data.append({"size": data['size_name'], "unit_w": data['unit_weight'], "nesting": res})
        st.session_state.calc_results = results_data

# ==========================================
# 5. 結果表示 & 色分けHTML生成
# ==========================================
if st.session_state.calc_results:
    st.write("### 2. 計算結果")
    total_order_rows, inst_rows = [], []
    grand_total_weight = 0.0
    
    # PDF/HTML用のスタイル（黒と白を明確に）
    pdf_html_inst = """
    <style>
        @media print { .page-break { page-break-before: always; } }
        body { font-family: sans-serif; color: #000; }
        .item-container { margin-bottom: 40px; border-bottom: 2px solid #000; padding-bottom: 20px; }
        .bar-outer { display: flex; width: 100%; height: 40px; background: #fff; border: 2px solid #000; margin: 10px 0; overflow: hidden; }
        .part-bar { background: #000; border-right: 1px solid #fff; height: 100%; }
        .waste-bar { background: #fff; height: 100%; }
    </style>
    """

    for i, item in enumerate(st.session_state.calc_results):
        pdf_html_inst += f"<div class='item-container {'page-break' if i>0 else ''}'><h2>切断加工指示書 ({item['size']})</h2><p>物件名: {pj_name}</p>"
        with st.expander(f"📦 {item['size']}", expanded=True):
            for idx, r in enumerate(item['nesting']):
                st.write(f"**No.{idx+1} (定尺:{r['stock_len']}mm)**")
                
                # --- 色分けバー生成 (部材=黒, 残材=白) ---
                parts_html = "".join([f'<div class="part-bar" style="width: {(p["len"]/r["stock_len"])*100}%;"></div>' for p in r['parts']])
                # 残材部分の計算
                total_used = sum(p['len'] for p in r['parts']) + (len(r['parts'])-1)*default_kerf
                waste_ratio = max(0, (r['stock_len'] - total_used) / r['stock_len'] * 100)
                waste_html = f'<div class="waste-bar" style="width: {waste_ratio}%;"></div>'
                
                # 画面表示用
                st.markdown(f'<div class="bar-outer">{parts_html}{waste_html}</div>', unsafe_allow_html=True)
                
                detail_txt = " / ".join([f"({seq+1}) {p['mark']}:{int(p['len'])}mm" for seq, p in enumerate(r['parts'])])
                st.caption(f"{detail_txt} [端材:{int(r['waste'])}mm]")
                
                # 指示書HTML用
                pdf_html_inst += f"<div style='margin-top:20px;'><strong>No.{idx+1} | 定尺: {r['stock_len']}mm</strong></div>"
                pdf_html_inst += f"<div class='bar-outer'>{parts_html}{waste_html}</div><div style='font-size:14px;'>{detail_txt} [端材:{int(r['waste'])}mm]</div>"
                inst_rows.append({"鋼種": item['size'], "No": idx+1, "定尺": r['stock_len'], "構成": detail_txt, "端材": r['waste']})

            # 発注集計
            counts = pd.Series([r['stock_len'] for r in item['nesting']]).value_counts().sort_index()
            for s_len, count in counts.items():
                w = round((s_len / 1000) * item['unit_w'] * count, 2)
                total_order_rows.append({"鋼種": item['size'], "定尺": s_len, "本数": count, "重量": w})
                grand_total_weight += w
        pdf_html_inst += "</div>"

    st.write("### 3. 帳票出力")
    today = datetime.date.today().strftime("%Y%m%d")
    c1, c2 = st.columns(2)
    with c1:
        st.info("📊 発注書")
        if total_order_rows:
            order_df = pd.DataFrame(total_order_rows)
            st.download_button("🖨️ PDF/印刷用", f"<h2>発注書</h2>{order_df.to_html()}<script>window.print();</script>", f"Order_{today}.html", "text/html")
    with c2:
        st.info("✂️ 加工指示書")
        if inst_rows:
            st.download_button("🖨️ PDF/印刷用", pdf_html_inst + "<script>window.print();</script>", f"CutList_{today}.html", "text/html")

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
# 3. ロジック：最短定尺優先・ロス最小化
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

# --- セッション状態の初期化 ---
if "rows" not in st.session_state:
    st.session_state.rows = 1
if "calc_results" not in st.session_state:
    st.session_state.calc_results = None

# 【修正：最強のリセット処理】
def reset_everything():
    # 全てのセッションキーを完全に削除
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    # ページをリロード（これでウィジェットが完全に初期化される）
    st.rerun()

with st.sidebar:
    st.header("🏢 物件情報")
    pj_name = st.text_input("物件名・現場名", placeholder="例：〇〇邸新築工事", key="pj_name_input")
    st.divider()
    
    default_kerf = st.number_input("切断シロ (mm)", value=5, step=1)
    
    st.write("残材許容範囲 (mm)")
    c_w1, c_w2 = st.columns(2)
    with c_w1:
        min_waste = st.number_input("最小", value=10, step=10)
    with c_w2:
        max_waste = st.number_input("最大", value=1000, step=100)
    
    st.write("使用する定尺長さ")
    stock_lengths = sorted([L for L in range(6000, 13000, 1000)])
    selected_stocks = [L for L in stock_lengths if st.checkbox(f"{L}mm", value=True, key=f"stock_{L}")]
    
    st.divider()
    # ボタンクリックでリセット関数を実行
    st.button("🔴 全てリセット", use_container_width=True, on_click=reset_everything)

st.write("### 1. 切断リスト入力")
input_data_list = []
for i in range(st.session_state.get('rows', 1)):
    with st.container():
        c1, c2 = st.columns([1, 2])
        with c1:
            s_size = st.selectbox(f"サイズ選択 {i+1}", options=size_options, key=f"size_sel_{i}")
            m_data = master_dict.get(clean_text(s_size), {"サイズ": "未選択", "単重": 0.0})
            if s_size != "(未選択)": st.info(f"単重: {m_data['単重']} kg/m")
        with c2:
            # keyを動的にすることでリセット時に確実に消去
            init_df = pd.DataFrame([{"マーク": "", "長さ(mm)": None, "本数": None} for _ in range(3)])
            edited_df = st.data_editor(init_df, num_rows="dynamic", key=f"editor_{i}", use_container_width=True)
        
        if s_size != "(未選択)":
            input_data_list.append({"size_name": m_data['サイズ'], "unit_weight": m_data['単重'], "df": edited_df})
    st.divider()

def add_row():
    st.session_state.rows = st.session_state.get('rows', 1) + 1

st.button("➕ 鋼種を増やす", on_click=add_row)

if st.button("🚀 計算実行", type="primary"):
    if not selected_stocks:
        st.error("定尺長さを選択してください。")
    else:
        results_data = []
        for data in input_data_list:
            # 空行を排除
            df_valid = data['df'].dropna(subset=["長さ(mm)", "本数"])
            parts = []
            for _, row in df_valid.iterrows():
                try:
                    l = float(row["長さ(mm)"])
                    n = int(row["本数"])
                    m = str(row["マーク"])
                    for _ in range(n):
                        parts.append({"len": l, "mark": m})
                except:
                    continue
            
            if parts:
                res = calculate_nesting_optimal(parts, selected_stocks, default_kerf, min_waste, max_waste)
                results_data.append({"size": data['size_name'], "unit_w": data['unit_weight'], "nesting": res})
        
        st.session_state.calc_results = results_data

# --- 結果・帳票出力（ここから下はボタンの復元を維持） ---
if st.session_state.get('calc_results'):
    st.write("### 2. 計算結果")
    total_order_rows = []
    inst_rows = []
    grand_total_weight = 0.0
    pdf_html_inst = "<style>@media print { .page-break { page-break-before: always; } } body { font-family: sans-serif; } .item-container { margin-bottom: 40px; border-bottom: 2px solid #000; padding-bottom: 20px; } .bar-outer { display: flex; width: 100%; height: 40px; background: #fff; border: 2px solid #000; margin: 10px 0; } </style>"

    for i, item in enumerate(st.session_state.calc_results):
        pdf_html_inst += f"<div class='item-container {'page-break' if i>0 else ''}'><h2>切断加工指示書 ({item['size']})</h2><p>物件名: {pj_name}</p>"
        with st.expander(f"📦 {item['size']} (単重: {item['unit_w']} kg/m)", expanded=True):
            for idx, r in enumerate(item['nesting']):
                st.write(f"**No.{idx+1} (定尺:{r['stock_len']}mm)**")
                bar_parts_html = "".join([f'<div style="width: {(p["len"]/r["stock_len"])*100}%; background: #333; border-right: 1px solid #fff;"></div>' for p in r['parts']])
                st.markdown(f'<div style="display: flex; width: 100%; height: 30px; background: #fff; border: 2px solid #000; margin-bottom: 5px;">{bar_parts_html}</div>', unsafe_allow_html=True)
                detail_txt = " / ".join([f"({seq+1}) {p['mark']}:{int(p['len'])}mm" for seq, p in enumerate(r['parts'])])
                st.caption(f"{detail_txt} [端材:{int(r['waste'])}mm]")
                pdf_html_inst += f"<div style='margin-top:20px;'><strong>No.{idx+1} | 定尺: {r['stock_len']}mm</strong></div><div class='bar-outer'>{bar_parts_html}</div><div style='font-size:14px;'>{detail_txt} [端材:{int(r['waste'])}mm]</div>"
                inst_rows.append({"物件名": pj_name, "鋼種": item['size'], "No": idx+1, "定尺(mm)": r['stock_len'], "切断構成": detail_txt, "端材(mm)": int(r['waste'])})
            
            counts = pd.Series([r['stock_len'] for r in item['nesting']]).value_counts().sort_index()
            summary_data = []
            for s_len, count in counts.items():
                weight = round((s_len / 1000) * item['unit_w'] * count, 2)
                summary_data.append({"定尺(mm)": s_len, "必要本数": count, "重量合計(kg)": weight})
                total_order_rows.append({"物件名": pj_name, "鋼種": item['size'], "定尺(mm)": s_len, "本数": count, "総重量(kg)": weight})
                grand_total_weight += weight
            st.table(pd.DataFrame(summary_data))
        pdf_html_inst += "</div>"

    st.divider()
    st.metric(label="🏁 全鋼種 総合計重量", value=f"{round(grand_total_weight, 2)} kg")
    st.divider()

    st.write("### 3. 帳票出力")
    today = datetime.date.today().strftime("%Y%m%d")
    c1, c2 = st.columns(2)
    with c1:
        st.info("📊 **発注書**")
        if total_order_rows:
            st.download_button("💾 CSVで保存", pd.DataFrame(total_order_rows).to_csv(index=False).encode('utf-8-sig'), f"Order_{today}.csv", "text/csv", key="dl_order_csv")
            order_html = f"<h2>鋼材発注書</h2><p>物件名: {pj_name}</p><table border='1' style='border-collapse:collapse; width:100%;'><tr><th>鋼種</th><th>定尺</th><th>本数</th><th>重量(kg)</th></tr>"
            for d in total_order_rows: order_html += f"<tr><td>{d['鋼種']}</td><td>{d['定尺(mm)']}mm</td><td>{d['本数']}</td><td>{d['総重量(kg)']}</td></tr>"
            order_html += f"<tr><td colspan='3' align='right'><b>総合計重量</b></td><td><b>{round(grand_total_weight, 2)} kg</b></td></tr></table><script>window.print();</script>"
            st.download_button("🖨️ PDF/印刷用", order_html, f"Order_{today}.html", "text/html", key="dl_order_html")
    with c2:
        st.info("✂️ **加工指示書**")
        if inst_rows:
            st.download_button("💾 CSVで保存", pd.DataFrame(inst_rows).to_csv(index=False).encode('utf-8-sig'), f"CutList_{today}.csv", "text/csv", key="dl_cut_csv")
            st.download_button("🖨️ PDF/印刷用", pdf_html_inst + "<script>window.print();</script>", f"CutList_{today}.html", "text/html", key="dl_cut_html")

import streamlit as st
import pandas as pd
import requests
import io
import datetime

# ==========================================
# 1. 設定とマスター読み込み
# ==========================================
SHEET_ID = "1vyjK-jW-5Nl0VRHZRUyKlNAqIaO49NUxe3-kwvTtSUg"
SHEET_NAME = "master"
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={SHEET_NAME}"

def clean_text(t):
    if not t: return ""
    return str(t).upper().replace("*","X").replace("×","X").replace(" ","").strip()

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
    except: return {}

# ==========================================
# 2. 【改善版】ロジック：端材最小化アルゴリズム
# ==========================================
def calculate_nesting_with_marks(required_parts, available_stocks, kerf, mode):
    # ロス削減重視なら長い順にソートして詰め込む(First Fit Decreasing)
    # カット数削減なら入力順を維持
    working_list = sorted(required_parts, key=lambda x: x['len'], reverse=True) if mode == "ロス削減重視" else required_parts[:]
    results = []
    remaining_parts = working_list[:]

    while remaining_parts:
        best_stock = None
        best_indices = []
        min_waste = float('inf')

        # 利用可能な全ての定尺でシミュレーションし、最も端材が少ない定尺を探す
        for s_len in available_stocks:
            temp_indices = []
            current_free = s_len
            
            for i, part in enumerate(remaining_parts):
                if current_free >= part['len']:
                    temp_indices.append(i)
                    current_free -= (part['len'] + kerf)
            
            # 端材(残った長さ)を計算
            waste = s_len - sum(remaining_parts[i]['len'] + kerf for i in temp_indices) + kerf
            
            # より端材が少ない、あるいは同じ端材なら短い定尺を優先（重量削減）
            if temp_indices:
                if waste < min_waste:
                    min_waste = waste
                    best_stock = s_len
                    best_indices = temp_indices[:]
                elif waste == min_waste:
                    if best_stock is None or s_len < best_stock:
                        best_stock = s_len
                        best_indices = temp_indices[:]

        if best_stock is not None:
            chosen_parts = [remaining_parts[i] for i in best_indices]
            # 選ばれた部材をリストから削除（後ろから削除してインデックスずれ防止）
            for i in sorted(best_indices, reverse=True):
                remaining_parts.pop(i)
            results.append({"stock_len": best_stock, "parts": chosen_parts, "waste": min_waste})
        else:
            # どの定尺にも入らない部材がある場合（定尺より長い部材など）
            break
            
    return results

# ==========================================
# 3. 画面構成（以下、表示部分は前回と同じ）
# ==========================================
st.set_page_config(page_title="鋼材一括取り合わせシステム", layout="wide")
st.title("🏗️ 鋼材一括取り合わせ・重量計算システム")
st.caption("ver 1.3.0 | ロジック大幅改善：端材最小化アルゴリズム搭載")
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
    calc_mode = st.radio("計算モード", ["ロス削減重視", "カット数削減重視"])
    default_kerf = st.number_input("切断シロ (mm)", value=5)
    st.write("使用する定尺長さ")
    # 選択肢を昇順で管理
    stock_lengths = sorted([L for L in range(6000, 13000, 1000)])
    selected_stocks = [L for L in stock_lengths if st.checkbox(f"{L}mm", value=True, key=f"stock_{L}")]
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
    if not selected_stocks:
        st.error("使用する定尺長さを少なくとも1つ選択してください。")
    else:
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
                # 改善したロジックを呼び出し
                res = calculate_nesting_with_marks(parts, selected_stocks, default_kerf, calc_mode)
                results_data.append({"size": data['size_name'], "unit_w": data['unit_weight'], "nesting": res})
        st.session_state.calc_results = results_data

# ==========================================
# 結果表示・帳票出力（前回と同じため省略せず統合）
# ==========================================
if st.session_state.calc_results:
    st.write("### 2. 計算結果")
    total_order_rows = []
    inst_rows = []
    grand_total_weight = 0.0
    
    pdf_html_inst = f"<style>@media print {{ .page-break {{ page-break-before: always; }} }} body {{ font-family: sans-serif; }} .item-container {{ margin-bottom: 40px; border-bottom: 2px solid #000; padding-bottom: 20px; }} .bar-outer {{ display: flex; width: 100%; height: 40px; background: #fff; border: 2px solid #000; margin: 10px 0; }} .bar-inner {{ background: #333; border-right: 2px solid #fff; height: 100%; }}</style>"

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
            st.write("📌 **この鋼種の発注内訳**")
            summary_data = []
            for s_len, count in counts.items():
                weight = round((s_len / 1000) * item['unit_w'] * count, 2)
                summary_data.append({"定尺(mm)": s_len, "必要本数": count, "重量合計(kg)": weight})
                total_order_rows.append({"物件名": pj_name, "鋼種": item['size'], "定尺(mm)": s_len, "本数": count, "総重量(kg)": weight})
                grand_total_weight += weight
            st.table(pd.DataFrame(summary_data))
        pdf_html_inst += "</div>"

    st.divider()
    c_tot1, c_tot2 = st.columns([2, 1])
    with c_tot1: st.subheader("🏁 全鋼種 総合計重量")
    with c_tot2: st.metric(label="Grand Total", value=f"{round(grand_total_weight, 2)} kg")
    st.divider()

    st.write("### 3. 帳票出力")
    today = datetime.date.today().strftime("%Y%m%d")
    c1, c2 = st.columns(2)
    with c1:
        st.info("📊 **発注書**")
        st.download_button("💾 CSVで保存", pd.DataFrame(total_order_rows).to_csv(index=False).encode('utf-8-sig'), f"Order_{today}.csv", "text/csv")
        order_html = f"<h2>鋼材発注書</h2><p>物件名: {pj_name}</p><table border='1' style='border-collapse:collapse; width:100%;'><tr><th>鋼種</th><th>定尺</th><th>本数</th><th>重量(kg)</th></tr>"
        for d in total_order_rows: order_html += f"<tr><td>{d['鋼種']}</td><td>{d['定尺(mm)']}mm</td><td>{d['本数']}</td><td>{d['総重量(kg)']}</td></tr>"
        order_html += f"<tr><td colspan='3' align='right'><b>総合計重量</b></td><td><b>{round(grand_total_weight, 2)} kg</b></td></tr></table><script>window.print();</script>"
        st.download_button("🖨️ PDF/印刷用", order_html, f"Order_{today}.html", "text/html")
    with c2:
        st.info("✂️ **加工指示書**")
        st.download_button("💾 CSVで保存", pd.DataFrame(inst_rows).to_csv(index=False).encode('utf-8-sig'), f"CutList_{today}.csv", "text/csv")
        st.download_button("🖨️ PDF/印刷用", pdf_html_inst + "<script>window.print();</script>", f"CutList_{today}.html", "text/html")

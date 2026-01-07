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
        df = df.drop_duplicates(subset='サイズ_KEY')
        return df.dropna(subset=['単重']).set_index('サイズ_KEY')[['サイズ', '単重']].to_dict('index')
    except: return {}

# ==========================================
# 2. ロジック
# ==========================================
def calculate_nesting_with_marks(required_parts, available_stocks, kerf, mode, min_waste, max_waste):
    working_list = sorted(required_parts, key=lambda x: x['len'], reverse=True) if mode == "ロス削減重視" else required_parts[:]
    results = []
    remaining_parts = working_list[:]
    
    while remaining_parts:
        best_stock, best_indices, best_waste, found_in_range = None, [], float('inf'), False
        for s_len in sorted(available_stocks, reverse=True):
            temp_bin, temp_indices, temp_remain = [], [], s_len
            for i, part in enumerate(remaining_parts):
                if temp_remain >= part['len'] + kerf:
                    temp_bin.append(part)
                    temp_remain -= (part['len'] + kerf)
                    temp_indices.append(i)
            if temp_bin:
                if min_waste <= temp_remain <= max_waste:
                    if not found_in_range or temp_remain < best_waste:
                        best_waste, best_stock, best_indices, found_in_range = temp_remain, s_len, temp_indices, True
                elif not found_in_range and temp_remain < best_waste:
                    best_waste, best_stock, best_indices = temp_remain, s_len, temp_indices
        if best_stock:
            chosen_parts = [remaining_parts[i] for i in best_indices]
            for i in sorted(best_indices, reverse=True): remaining_parts.pop(i)
            results.append({"stock_len": best_stock, "parts": chosen_parts, "waste": best_waste, "in_range": min_waste <= best_waste <= max_waste})
        else: break
    return results

# ==========================================
# 3. 画面構成
# ==========================================
st.set_page_config(page_title="鋼材一括取り合わせシステム", layout="wide")
st.title("🏗️ 鋼材一括取り合わせ・重量計算システム")
st.warning("【免責事項】本ツールの計算結果は目安です。実際の切断作業前には必ず再確認を行ってください。")

master_dict = load_master()
size_options = ["(未選択)"] + [v['サイズ'] for v in master_dict.values()]

if "rows" not in st.session_state: st.session_state.rows = 1
if "calc_results" not in st.session_state: st.session_state.calc_results = None

with st.sidebar:
    st.header("⚙️ 設定")
    if st.button("🔄 マスター更新"):
        st.cache_data.clear()
        st.rerun()
    calc_mode = st.radio("計算モード", ["ロス削減重視", "カット数削減重視"])
    default_kerf = st.number_input("切断シロ (mm)", value=5)
    st.divider()
    st.write("📏 **残材の許容範囲 (mm)**")
    w_min = st.number_input("最小", value=10)
    w_max = st.number_input("最大", value=1000)
    st.divider()
    st.write("🔧 **定尺**")
    selected_stocks = [L for L in range(6000, 13000, 1000) if st.checkbox(f"{L}mm", value=True, key=f"stock_{L}")]

st.write("### 1. 切り出しリスト入力")
input_data_list = []
for i in range(st.session_state.rows):
    with st.container():
        c1, c2 = st.columns([1, 2])
        with c1:
            s_size = st.selectbox(f"サイズ選択 {i+1}", options=size_options, key=f"size_sel_{i}")
            key = clean_text(s_size)
            m_data = master_dict.get(key, {"サイズ": "未選択", "単重": 0.0})
            if s_size != "(未選択)": st.info(f"単重: {m_data['単重']} kg/m")
        with c2:
            init_df = pd.DataFrame([{"マーク": "", "長さ(mm)": None, "本数": None} for _ in range(3)])
            edited_df = st.data_editor(init_df, num_rows="dynamic", key=f"editor_{i}", use_container_width=True)
        if s_size != "(未選択)":
            input_data_list.append({"size_name": m_data['サイズ'], "unit_weight": m_data['単重'], "df": edited_df})
    st.divider()
st.button("➕ 鋼種を増やす", on_click=lambda: setattr(st.session_state, 'rows', st.session_state.rows + 1))

if st.button("🚀 計算実行", type="primary"):
    if not input_data_list or not selected_stocks:
        st.error("入力内容を確認してください。")
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
            if not parts: continue
            res = calculate_nesting_with_marks(parts, selected_stocks, default_kerf, calc_mode, w_min, w_max)
            results_data.append({"size": data['size_name'], "unit_w": data['unit_weight'], "nesting": res})
        st.session_state.calc_results = results_data

# ==========================================
# 4. 結果表示 & 帳票
# ==========================================
def generate_bar_html(r, is_print=False):
    # 切断材は黒(#333)、端材は白(#fff)
    bg_color = "#333"
    waste_color = "#fff"
    txt_color = "#fff"
    
    html = f'<div style="display: flex; width: 100%; height: 35px; background-color: {waste_color}; border: 2px solid #000; border-radius: 4px; overflow: hidden; margin-bottom: 5px;">'
    for p in r['parts']:
        ratio = (p['len'] / r['stock_len']) * 100
        label = f"{p['mark']} {int(p['len'])}" if ratio > 8 else ""
        html += f'<div style="width: {ratio}%; background-color: {bg_color}; border-right: 2px solid #fff; color: {txt_color}; font-size: 11px; text-align: center; line-height: 35px; overflow: hidden; white-space: nowrap; font-weight: bold;">{label}</div>'
    html += '</div>'
    
    html += '<div style="display: flex; flex-wrap: wrap; gap: 10px; font-size: 12px; margin-bottom: 15px; color: #333;">'
    for i, p in enumerate(r['parts']):
        html += f'<span>[{i+1}] <b>{p["mark"]}</b>: {int(p["len"])}mm</span>'
    html += f'<span style="color: #666;">（端材: {int(r["waste"])}mm）</span></div>'
    return html

if st.session_state.calc_results:
    today = datetime.date.today().strftime("%Y/%m/%d")
    st.write("### 2. 計算結果")
    for item in st.session_state.calc_results:
        with st.expander(f"📦 {item['size']}", expanded=True):
            for idx, r in enumerate(item['nesting']):
                st.write(f"**No.{idx+1} (定尺:{r['stock_len']}mm)**")
                st.markdown(generate_bar_html(r), unsafe_allow_html=True)

    st.write("### 3. 帳票出力")
    
    # --- データ準備 (CSV用) ---
    order_rows = []
    inst_rows = []
    for item in st.session_state.calc_results:
        # 発注用
        counts = pd.Series([r['stock_len'] for r in item['nesting']]).value_counts().sort_index()
        for s_len, count in counts.items():
            order_rows.append({"鋼種": item['size'], "定尺(mm)": s_len, "本数": count})
        # 指示用
        for idx, r in enumerate(item['nesting']):
            inst_rows.append({
                "鋼種": item['size'], "No": idx+1, "使用定尺": r['stock_len'],
                "切断構成": " / ".join([f"{p['mark']}:{int(p['len'])}mm" for p in r['parts']]),
                "端材": int(r['waste'])
            })
    
    order_df = pd.DataFrame(order_rows)
    inst_df = pd.DataFrame(inst_rows)

    # --- HTML帳票準備 (PDF/印刷用) ---
    inst_h = f"""
    <style>
        @media print {{ .page-break {{ page-break-before: always; }} }}
        body {{ font-family: sans-serif; }}
        .item-container {{ margin-bottom: 40px; border-bottom: 2px solid #000; padding-bottom: 20px; }}
        .bar-outer {{ display: flex; width: 100%; height: 40px; background: #fff; border: 2px solid #000; margin: 10px 0; }}
        .bar-inner {{ background: #333; border-right: 2px solid #fff; color: #fff; text-align: center; line-height: 40px; font-size: 12px; font-weight: bold; overflow: hidden; }}
        .detail-text {{ display: flex; flex-wrap: wrap; gap: 15px; font-size: 14px; margin-bottom: 20px; font-weight: bold; }}
    </style>
    """
    for i, item in enumerate(st.session_state.calc_results):
        inst_h += f"<div class='item-container {'page-break' if i>0 else ''}'><h2>切断加工指示書 ({item['size']})</h2>"
        for idx, r in enumerate(item['nesting']):
            inst_h += f"<div style='margin-top:20px;'><strong>No.{idx+1} | 定尺: {r['stock_len']}mm</strong></div>"
            inst_h += "<div class='bar-outer'>"
            for p in r['parts']:
                ratio = (p['len'] / r['stock_len']) * 100
                inst_h += f"<div class='bar-inner' style='width: {ratio}%'></div>"
            inst_h += "</div><div class='detail-text'>"
            for seq, p in enumerate(r['parts']):
                inst_h += f"<span>({seq+1}) {p['mark']}: {int(p['len'])}mm</span>"
            inst_h += f"<span style='color:#666;'>[端材:{int(r['waste'])}mm]</span></div>"
        inst_h += "</div>"
    inst_h += "<script>window.print();</script>"

    order_h = f"<style>table{{width:100%;border-collapse:collapse;}}th,td{{border:1px solid black;padding:8px;text-align:left;}}</style><h1>鋼材発注書</h1><p>発行日: {today}</p><table><tr><th>鋼種</th><th>定尺(mm)</th><th>本数</th></tr>"
    for _, row in order_df.iterrows():
        order_h += f"<tr><td>{row['鋼種']}</td><td>{row['定尺(mm)']}</td><td>{row['本数']}</td></tr>"
    order_h += "</table><script>window.print();</script>"

    # --- ボタン配置 ---
    c1, c2 = st.columns(2)
    with c1:
        st.info("📊 **発注書**")
        st.download_button("💾 発注書 CSV出力", order_df.to_csv(index=False).encode('utf-8-sig'), f"order_{today}.csv", "text/csv")
        st.download_button("🖨️ 発注書 PDF/印刷", order_h, f"order_{today}.html", "text/html")

    with c2:
        st.info("✂️ **加工指示書**")
        st.download_button("💾 指示書 CSV出力", inst_df.to_csv(index=False).encode('utf-8-sig'), f"cut_list_{today}.csv", "text/csv")
        st.download_button("🖨️ 指示書 PDF/印刷", inst_h, f"cut_list_{today}.html", "text/html")

import streamlit as st
import pandas as pd
import requests
import io
import datetime
from collections import Counter

# ==========================================
# 1. ユーティリティ関数
# ==========================================
def clean_text(t):
    if not t: return ""
    return str(t).upper().replace("*","X").replace("×","X").replace(" ","").strip()

# ==========================================
# 2. マスター読み込み（自動更新: 5分）
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
# 3. ロジック：モード別の挙動（まとめ切り対応）
# ==========================================
def calculate_nesting_with_marks(required_parts, available_stocks, kerf, mode, min_waste_limit, max_waste_limit):
    # 部材は常に長い順に並べておく
    working_list = sorted(required_parts, key=lambda x: x['len'], reverse=True)
    results = []
    
    # 処理用リスト（ここからpopしていく）
    remaining_parts = working_list[:]
    
    # 定尺の優先順位
    # ロス削減: 短い方から検討（必要最小限の長さを使う）
    # カット数削減: 長い方から検討（一度に多く取るため）
    if mode == "ロス削減重視":
        stocks_order = sorted(available_stocks) 
    else:
        stocks_order = sorted(available_stocks, reverse=True)

    while remaining_parts:
        best_pick = None
        
        # ---------------------------------------------------------
        # A. カット数削減重視（パターンリピート最大化）
        # ---------------------------------------------------------
        if mode == "カット数削減重視":
            # 「今ある部材」で「最も効率よく埋まるパターン」を1つ作る
            # そのパターンが「何回繰り返せるか」を計算し、まとめて採用する
            
            # 1. 基準となるパターンを作成（長い定尺優先で、First Fit Decreasing）
            pattern_candidate = None
            
            for s_len in stocks_order:
                temp_indices = []
                current_free = s_len
                current_used = 0
                
                # シミュレーション用に一時的な使用フラグ管理は難しいので、
                # 単純に「上から順に詰め込んだらどうなるか」を見る
                for i, part in enumerate(remaining_parts):
                    needed = part['len'] + (kerf if temp_indices else 0)
                    if current_free >= needed:
                        temp_indices.append(i)
                        current_free -= (part['len'] + kerf)
                        current_used += part['len']
                
                if temp_indices:
                    # パターンが見つかった
                    waste = s_len - current_used - (len(temp_indices)-1)*kerf
                    pattern_candidate = {
                        "stock_len": s_len,
                        "indices": temp_indices, # これは remaining_parts 内の相対位置
                        "waste": waste,
                        "lengths": [remaining_parts[i]['len'] for i in temp_indices]
                    }
                    break # 長い定尺優先なので、見つかった時点でその定尺を採用（これがベースパターン）
            
            if pattern_candidate:
                # 2. このパターンが何回繰り返せるか計算する
                # 必要な長さの構成: 例 [3000, 3000, 2000]
                req_counts = Counter(pattern_candidate['lengths'])
                
                # 全体の在庫にある各長さの個数
                total_counts = Counter([p['len'] for p in remaining_parts])
                
                # リピート可能回数 = 各長さについて (在庫数 // 1回あたりの必要数) の最小値
                max_repeats = float('inf')
                for length, count_needed in req_counts.items():
                    available = total_counts.get(length, 0)
                    max_repeats = min(max_repeats, available // count_needed)
                
                if max_repeats < 1: max_repeats = 1 # 論理上ありえないが念のため
                
                # 3. max_repeats 回分、結果に追加し、部材リストから削除する
                # インデックス管理が面倒なので、長さとマークでマッチングして削除
                
                for _ in range(max_repeats):
                    chosen_parts = []
                    # パターンの構成要素（長さ）を一つずつ取り出す
                    for length in pattern_candidate['lengths']:
                        # remaining_partsの中から、その長さを持つ最初の要素を探してpop
                        for i, part in enumerate(remaining_parts):
                            if part['len'] == length:
                                chosen_parts.append(remaining_parts.pop(i))
                                break
                    
                    # 結果に追加
                    results.append({
                        "stock_len": pattern_candidate['stock_len'],
                        "parts": chosen_parts,
                        "waste": int(pattern_candidate['waste'])
                    })
                
                # ループ継続（次のパターンを探す）
                continue

        # ---------------------------------------------------------
        # B. ロス削減重視（従来の端材最小化ロジック）
        # ---------------------------------------------------------
        else:
            best_waste = float('inf')
            
            for s_len in stocks_order:
                temp_indices = []
                current_free = s_len
                current_used = 0
                
                for i, part in enumerate(remaining_parts):
                    needed = part['len'] + (kerf if temp_indices else 0)
                    if current_free >= needed:
                        temp_indices.append(i)
                        current_free -= (part['len'] + kerf)
                        current_used += part['len']
                
                if temp_indices:
                    waste = s_len - current_used - (len(temp_indices)-1)*kerf
                    
                    is_waste_ok = (waste >= min_waste_limit) or (waste <= kerf)
                    
                    if is_waste_ok:
                        if waste < best_waste:
                            best_waste = waste
                            best_pick = {"stock_len": s_len, "indices": temp_indices, "waste": waste}
        
            if best_pick:
                chosen_parts = [remaining_parts[i] for i in best_pick["indices"]]
                for i in sorted(best_pick["indices"], reverse=True):
                    remaining_parts.pop(i)
                
                results.append({
                    "stock_len": best_pick["stock_len"],
                    "parts": chosen_parts,
                    "waste": int(best_pick["waste"])
                })
            else:
                # 救済措置：条件を満たすものがない場合、一番長い定尺に入れて処理を進める
                if remaining_parts:
                    part = remaining_parts.pop(0)
                    max_stock = max(available_stocks)
                    results.append({
                        "stock_len": max_stock,
                        "parts": [part],
                        "waste": int(max_stock - part['len'])
                    })
                else:
                    break
            
    return results

# ==========================================
# 4. 画面構成
# ==========================================
st.set_page_config(page_title="鋼材一括取り合わせシステム", layout="wide")
st.title("🏗️ 鋼材一括取り合わせ・重量計算システム")
st.caption("ver 1.5.0 | ロジック完成版：まとめ切り（パターン繰り返し）対応")

master_dict = load_master()
size_options = ["(未選択)"] + [v['サイズ'] for v in master_dict.values()]

if "rows" not in st.session_state: st.session_state.rows = 1
if "calc_results" not in st.session_state: st.session_state.calc_results = None

with st.sidebar:
    st.header("🏢 物件情報")
    pj_name = st.text_input("物件名・現場名", placeholder="例：〇〇邸新築工事")
    st.divider()
    st.header("⚙️ 計算設定")
    
    # モード設定
    calc_mode = st.radio("計算モード", ["ロス削減重視", "カット数削減重視"])
    if calc_mode == "ロス削減重視":
        st.caption("💡 **重量最優先**：端材が最小になる定尺を1本ずつ厳密に選定します。定尺の種類や切り方はバラバラになりやすいです。")
    else:
        st.caption("💡 **作業性最優先**：同じ切り方（パターン）をできるだけ繰り返します。定尺を束ねて一度に切断（まとめ切り）するのに適しています。")
    
    default_kerf = st.number_input("切断シロ (mm)", value=5)
    
    c_w1, c_w2 = st.columns(2)
    with c_w1:
        min_waste = st.number_input("残材 最小(mm)", value=0, help="これより短い端材が出ないように計算します（0に近い端材は許容されます）")
    with c_w2:
        max_waste = st.number_input("残材 最大(mm)", value=9999, disabled=True)
    
    st.write("使用する定尺長さ")
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
                except Exception: continue
            if parts:
                res = calculate_nesting_with_marks(parts, selected_stocks, default_kerf, calc_mode, min_waste, max_waste)
                results_data.append({"size": data['size_name'], "unit_w": data['unit_weight'], "nesting": res})
        st.session_state.calc_results = results_data

# 変数の初期化
total_order_rows = []
inst_rows = []
grand_total_weight = 0.0
pdf_html_inst = ""

if st.session_state.calc_results:
    st.write("### 2. 計算結果")
    pdf_html_inst = "<style>@media print { .page-break { page-break-before: always; } } body { font-family: sans-serif; } .item-container { margin-bottom: 40px; border-bottom: 2px solid #000; padding-bottom: 20px; } .bar-outer { display: flex; width: 100%; height: 40px; background: #fff; border: 2px solid #000; margin: 10px 0; } </style>"

    for i, item in enumerate(st.session_state.calc_results):
        pdf_html_inst += f"<div class='item-container {'page-break' if i>0 else ''}'><h2>切断加工指示書 ({item['size']})</h2><p>物件名: {pj_name}</p>"
        with st.expander(f"📦 {item['size']} (単重: {item['unit_w']} kg/m)", expanded=True):
            for idx, r in enumerate(item['nesting']):
                st.write(f"**No.{idx+1} (定尺:{r['stock_len']}mm)**")
                
                bar_parts_html = "".join([f'<div style="width: {(p["len"]/r["stock_len"])*100}%; background: #333; border-right: 1px solid #fff;"></div>' for p in r['parts']])
                bar_style = "display: flex; width: 100%; height: 30px; background: #fff; border: 2px solid #000; margin-bottom: 5px;"
                st.markdown(f'<div style="{bar_style}">{bar_parts_html}</div>', unsafe_allow_html=True)
                
                detail_txt = " / ".join([f"({seq+1}) {p['mark']}:{int(p['len'])}mm" for seq, p in enumerate(r['parts'])])
                st.caption(f"{detail_txt} [端材:{int(r['waste'])}mm]")
                
                pdf_html_inst += f"<div style='margin-top:20px;'><strong>No.{idx+1} | 定尺: {r['stock_len']}mm</strong></div>"
                pdf_html_inst += f"<div class='bar-outer'>{bar_parts_html}</div>"
                pdf_html_inst += f"<div style='font-size:14px;'>{detail_txt} [端材:{int(r['waste'])}mm]</div>"
                
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
        if total_order_rows:
            st.download_button("💾 CSVで保存", pd.DataFrame(total_order_rows).to_csv(index=False).encode('utf-8-sig'), f"Order_{today}.csv", "text/csv")
            order_html = f"<h2>鋼材発注書</h2><p>物件名: {pj_name}</p><table border='1' style='border-collapse:collapse; width:100%;'><tr><th>鋼種</th><th>定尺</th><th>本数</th><th>重量(kg)</th></tr>"
            for d in total_order_rows: order_html += f"<tr><td>{d['鋼種']}</td><td>{d['定尺(mm)']}mm</td><td>{d['本数']}</td><td>{d['総重量(kg)']}</td></tr>"
            order_html += f"<tr><td colspan='3' align='right'><b>総合計重量</b></td><td><b>{round(grand_total_weight, 2)} kg</b></td></tr></table><script>window.print();</script>"
            st.download_button("🖨️ PDF/印刷用", order_html, f"Order_{today}.html", "text/html")
    with c2:
        st.info("✂️ **加工指示書**")
        if inst_rows:
            st.download_button("💾 CSVで保存", pd.DataFrame(inst_rows).to_csv(index=False).encode('utf-8-sig'), f"CutList_{today}.csv", "text/csv")
            st.download_button("🖨️ PDF/印刷用", pdf_html_inst + "<script>window.print();</script>", f"CutList_{today}.html", "text/html")

import streamlit as st
import pandas as pd
import requests
import io
import datetime

# ==========================================
# 1. ユーティリティ関数（最初に行う）
# ==========================================
def clean_text(t):
    if not t: return ""
    # 文字列を整えて、マスターのキーと一致させる
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
        # 最初の2列（サイズ, 単重）を抽出
        df = df.iloc[:, [0, 1]]
        df.columns = ['サイズ', '単重']
        # キーを作成
        df['サイズ_KEY'] = df['サイズ'].apply(clean_text)
        # 数値変換
        df['単重'] = pd.to_numeric(df['単重'], errors='coerce')
        # 重複削除
        df = df.drop_duplicates(subset='サイズ_KEY')
        # 辞書形式で返す
        return df.dropna(subset=['単重']).set_index('サイズ_KEY')[['サイズ', '単重']].to_dict('index')
    except Exception as e:
        st.error(f"マスター読み込みエラー: {e}")
        return {}

# ==========================================
# 3. ロジック：重量効率（密度）優先アルゴリズム
# ==========================================
def calculate_nesting_with_marks(required_parts, available_stocks, kerf, mode):
    # ロス削減重視なら長い順にソート。カット数削減なら入力順。
    working_list = sorted(required_parts, key=lambda x: x['len'], reverse=True) if mode == "ロス削減重視" else required_parts[:]
    results = []
    remaining_parts = working_list[:]
    stocks = sorted(available_stocks)

    while remaining_parts:
        best_pick = None
        best_efficiency = -1.0
        
        for s_len in stocks:
            temp_indices = []
            current_free = s_len
            current_total_parts_len = 0
            
            for i, part in enumerate(remaining_parts):
                # 最初の部材以外は切断シロを加算
                needed = part['len'] + (kerf if temp_indices else 0)
                if current_free >= needed:
                    temp_indices.append(i)
                    current_free -= (part['len'] + kerf)
                    current_total_parts_len += part['len']
            
            if temp_indices:
                # 充填率（密度）で評価
                efficiency = current_total_parts_len / s_len
                # 効率が良いもの、同じなら短い定尺を優先
                if efficiency > best_efficiency:
                    best_efficiency = efficiency
                    best_pick = {
                        "stock_len": s_len,
                        "indices": temp_indices[:],
                        "waste": s_len - current_total_parts_len - (len(temp_indices)-1)*kerf
                    }
                elif abs(efficiency - best_efficiency) < 1e-7:
                    if best_pick and s_len < best_pick["stock_len"]:
                        best_pick = {
                            "stock_len": s_len,
                            "indices": temp_indices[:],
                            "waste": s_len - current_total_parts_len - (len(temp_indices)-1)*kerf
                        }

        if best_pick:
            chosen_parts = [remaining_parts[i] for i in best_pick["indices"]]
            for i in sorted(best_pick["indices"], reverse=True):
                remaining_parts.pop(i)
            results.append({
                "stock_len": best_pick["stock_len"],
                "parts": chosen_parts,
                "waste": max(0, int(best_pick["waste"]))
            })
        else:
            break
            
    return results

# ==========================================
# 4. 画面構成
# ==========================================
st.set_page_config(page_title="鋼材一括取り合わせシステム", layout="wide")
st.title("🏗️ 鋼材一括取り合わせ・重量計算システム")
st.caption("ver 1.3.2 | マスター自動更新(5分) | ロジック最適化済み")

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
            # クリーンにしたキーでマスターから取得
            m_data = master_dict.get(clean_text(s_size), {"サイズ": "未選択", "単重": 0.0})
            if s_size != "(未選択)": st.info(f"単重: {m_data['単重']} kg/m")
        with c2:
            init_df = pd.DataFrame([{"マーク": "", "長さ(mm)": None, "本数": None} for _ in range(3)])
            edited_df = st.data_editor(init_df, num_rows="dynamic", key=f"editor_{i}", use_container_width=True)
        if s_size != "(未選択)":
            input_data_list.append({"size_name": m_data['サイズ'], "unit_weight": m_data['単重'], "df": edited_df})
    st.divider()
st.button("➕ 鋼種を増やす", on_click=lambda: setattr(st.session_state, 'rows', st.session_state.rows + 1))

# ==========================================
# 5. 計算実行 & 結果表示
# ==========================================
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
                res = calculate_nesting_with_marks(parts, selected_stocks, default_kerf, calc_mode)
                results_data.append({"size": data['size_name'], "unit_w": data['unit_weight'], "nesting": res})
        st.session_state.calc_results = results_data

if st.session_state.calc_results:
    st.write("### 2. 計算結果")
    total_order_rows = []
    inst_rows

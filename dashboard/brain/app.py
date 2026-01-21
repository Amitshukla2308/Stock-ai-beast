import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
import json
import os
import shutil
import time

st.set_page_config(page_title="🧠 Beast Brain Inspector", layout="wide")

# --- DATABASE CONNECTION ---
DB_PATH = "/app/data/trading.db"
SHADOW_DIR = "/tmp/db_shadow"
SHADOW_PATH = os.path.join(SHADOW_DIR, "trading.db")

@st.cache_resource(ttl=5)  # Re-run getting connection every 5s to refresh data
def get_connection():
    # Strategy: Copy DB to temp folder to avoid read/write locks from the trading engine
    if not os.path.exists(SHADOW_DIR):
        os.makedirs(SHADOW_DIR)
    
    # Simple check: Copy if original is newer or shadow missing
    if os.path.exists(DB_PATH):
        try:
            # We use cp command for speed and wildcards (WAL files) if needed, but shutil is fine
            # We assume DB is in WAL mode, so we need trading.db and trading.db.wal if exists
            shutil.copy2(DB_PATH, SHADOW_PATH)
            # Copy WAL if exists
            if os.path.exists(DB_PATH + ".wal"):
                shutil.copy2(DB_PATH + ".wal", SHADOW_PATH + ".wal")
        except Exception as e:
            st.warning(f"Could not refresh DB shadow copy: {e}")
    
    try:
        # Connect to shadow copy
        conn = sqlite3.connect(SHADOW_PATH)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        st.error(f"Failed to connect to DB: {e}")
        return None

conn = get_connection()

if not conn:
    st.stop()

# --- SIDEBAR ---
st.sidebar.title("🧠 Brain Inspector")
st.sidebar.markdown("---")

# --- DATA FETCHING ---
try:
    tables_query = "SELECT name FROM sqlite_master WHERE type='table'"
    tables_df = pd.read_sql_query(tables_query, conn)
    tables = tables_df['name'].values.tolist()

    if 'simulation_sessions' not in tables:
        st.warning("No backtest sessions found. Run a backtest first!")
        st.stop()

    # 1. Get Runs from simulation_sessions (Source of Truth)
    df_runs = pd.read_sql_query("SELECT * FROM simulation_sessions ORDER BY created_at DESC", conn)
    
    if df_runs.empty:
        st.info("No recorded sessions yet.")
        st.stop()

    # Sidebar Run Selector
    run_options = df_runs.apply(lambda x: f"{x['session_id']} | {x['symbol']} | {x['created_at']}", axis=1).tolist()
    selected_run_str = st.sidebar.selectbox("Select Backtest Run", run_options, index=0)
    selected_run_id = selected_run_str.split(" | ")[0]
    
    st.sidebar.markdown(f"**Selected Run:** `{selected_run_id}`")

    # 2. Fetch DATA for Selected Run
    
    # A. Live Trades (simulation_trades)
    df_trades = pd.DataFrame()
    if 'simulation_trades' in tables:
        df_trades = pd.read_sql_query("SELECT * FROM simulation_trades WHERE session_id = ? ORDER BY entry_time DESC", conn, params=(selected_run_id,))

    # B. Live Logs (simulation_logs)
    df_logs = pd.DataFrame()
    if 'simulation_logs' in tables:
        df_logs = pd.read_sql_query("SELECT * FROM simulation_logs WHERE session_id = ? ORDER BY timestamp DESC LIMIT 500", conn, params=(selected_run_id,))

    # C. EOD Experience (experience_replay) - Might be empty if mid-day
    df_exp = pd.DataFrame()
    if 'experience_replay' in tables:
        # Filter by string containment since experience PK is {RUN}_{DATE}
        # Safe check using LIKE
        df_exp = pd.read_sql_query(f"SELECT * FROM experience_replay WHERE session_id LIKE '{selected_run_id}%' ORDER BY date DESC", conn)

    # D. Nuggets
    df_nuggets = pd.DataFrame()
    if 'knowledge_nuggets' in tables:
        # Join with experience to filter by run, or brute force filter
        # We stored nuggets with session_id same as experience_replay ({RUN}_{DATE})
        df_nuggets = pd.read_sql_query(f"SELECT * FROM knowledge_nuggets WHERE session_id LIKE '{selected_run_id}%' ORDER BY created_at DESC", conn)

except Exception as e:
    st.error(f"Query Error: {e}")
    st.stop()

# --- TABS ---
tab1, tab2, tab3, tab4 = st.tabs(["🔴 Live Monitor", "📊 Days Overview", "🧐 Episode Inspector", "💎 Knowledge Bank"])

# --- TAB 1: LIVE MONITOR (NEW) ---
with tab1:
    st.header(f"Live Monitor: {selected_run_id}")
    
    # 1. Live Stats
    if not df_trades.empty:
        total_pnl = df_trades['pnl'].sum()
        win_count = len(df_trades[df_trades['pnl'] > 0])
        trade_count = len(df_trades)
        win_rate = (win_count / trade_count * 100) if trade_count > 0 else 0
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Live PnL", f"{total_pnl:.1f}", delta_color="normal")
        c2.metric("Trades Executed", f"{trade_count}")
        c3.metric("Win Rate", f"{win_rate:.1f}%")
        
        st.subheader("Recent Trades")
        st.dataframe(
            df_trades[['entry_time', 'side', 'entry_price', 'exit_price', 'pnl', 'reason']], 
            use_container_width=True,
            height=300
        )
    else:
        st.info("No trades executed yet in this run.")

    # 2. Live Logs (The Neural Stream)
    st.subheader("Neural Stream (Latest Logs)")
    if not df_logs.empty:
        for idx, row in df_logs.iterrows():
            with st.expander(f"{row['timestamp']} | {row['event_type']}"):
                try:
                    # Try to format JSON if possible
                    import json
                    content = json.loads(row['content'])
                    st.json(content)
                except:
                    st.write(row['content'])
    else:
        st.write("Waiting for brain activity...")

# --- TAB 2: OVERVIEW (Historic EOD) ---
with tab2:
    st.header("Daily Performance (EOD Audits)")
    if not df_exp.empty:
        df_exp['date'] = pd.to_datetime(df_exp['date'])
        df_exp = df_exp.sort_values('date')
        df_exp['cumulative_pnl'] = df_exp['total_pnl'].cumsum()
        
        # Metrics
        total_pnl = df_exp['total_pnl'].sum()
        win_rate = (len(df_exp[df_exp['total_pnl'] > 0]) / len(df_exp) * 100) if len(df_exp) > 0 else 0
        total_days = len(df_exp)
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Total PnL Points", f"{total_pnl:.2f}")
        c2.metric("Win Rate (Days)", f"{win_rate:.1f}%")
        c3.metric("Experience/Episodes", f"{total_days}")
        
        fig = px.line(df_exp, x='date', y='cumulative_pnl', title="Accumulated Brain PnL (Points)", markers=True)
        st.plotly_chart(fig, use_container_width=True)
        
        st.subheader("Daily Journal")
        st.dataframe(df_exp[['date', 'symbol', 'total_pnl']].sort_values('date', ascending=False), use_container_width=True)

# --- TAB 3: EPISODE INSPECTOR ---
with tab3:
    st.header("Deep Dive into Consciousness")
    
    if not df_exp.empty:
        # Selector
        options = df_exp.apply(lambda x: f"{x['date'].date()} | {x['session_id']} | PnL: {x['total_pnl']}", axis=1).tolist()
        selected_option = st.selectbox("Select Episode", options)
        
        if selected_option:
            selected_id = selected_option.split(" | ")[1]
            row = df_exp[df_exp['session_id'] == selected_id].iloc[0]
            
            c1, c2 = st.columns([1, 1])
            
            with c1:
                st.subheader("📝 Morning Plan")
                try:
                    plan = json.loads(row['morning_plan'])
                    # Pretty print key info
                    st.info(f"**Bias:** {plan.get('primary_bias')} | **Personality:** {plan.get('market_personality')}")
                    st.write(f"**Morning Logic:** {plan.get('morning_logic')}")
                    with st.expander("Full Plan JSON"):
                        st.json(plan)
                except:
                    st.warning("Could not parse Morning Plan")
            
            with c2:
                st.subheader("📊 EOD Reflection")
                try:
                    audit = json.loads(row['eod_audit'])
                    st.success(f"**Summary:** {audit.get('audit_summary', 'N/A')}")
                    
                    st.write("**What Worked:**")
                    st.write(audit.get('nugget_good', '-'))
                    
                    st.write("**What Failed:**")
                    st.write(audit.get('nugget_bad', '-'))
                    
                    with st.expander("Full Audit JSON"):
                        st.json(audit)
                except:
                     st.warning("Could not parse Audit")

            st.markdown("---")
            st.subheader("⚡ Execution Trace")
            try:
                trades = json.loads(row['trades'])
                if trades:
                    df_trades = pd.DataFrame(trades)
                    params = ['entry_time', 'side', 'entry_price', 'exit_price', 'pnl', 'reason']
                    # Filter columns if exist
                    cols = [c for c in params if c in df_trades.columns]
                    st.dataframe(df_trades[cols], use_container_width=True)
                else:
                    st.info("No trades executed this day.")
            except:
                st.error("Error parsing trades logs.")

# --- TAB 4: KNOWLEDGE BANK ---
with tab4:
    st.header("💎 The Knowledge Bank")
    st.info("These are the atomic lessons ('nuggets') extracted from every trading session.")
    
    if not df_nuggets.empty:
        # Filters
        cat_filter = st.multiselect("Category", df_nuggets['category'].unique(), default=df_nuggets['category'].unique())
        
        # Filter Logic
        filtered_df = df_nuggets[df_nuggets['category'].isin(cat_filter)]
        
        # Display
        for index, row in filtered_df.iterrows():
            color = "green" if row['category'] == 'GOOD' else "red"
            icon = "✅" if row['category'] == 'GOOD' else "❌"
            
            with st.container():
                st.markdown(f"**{icon} {row['category']}** | *Tags: {row['condition_tags']}*")
                st.info(row['lesson'])
                st.caption(f"Source: {row['session_id']} | Created: {row['created_at']}")
                st.markdown("---")
    else:
        st.warning("No nuggets collected yet.")

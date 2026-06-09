#!/usr/bin/env python3
"""
ui_components.py — Streamlit UI component library and custom CSS injection
for the Unified Operations Toolkit.

Provides reusable UI building blocks: server input matrix, command sidebar,
status indicators, and premium dark-theme styling.
"""

import streamlit as st
from config import THEME, DIAGNOSTIC_COMMANDS
from storage import load_servers, save_servers, delete_saved_servers, SERVERS_FILE


# ═══════════════════════════════════════════════════════════════════════════
#  CUSTOM CSS — Premium dark-theme styling
# ═══════════════════════════════════════════════════════════════════════════

def inject_custom_css():
    """Inject the full custom CSS theme into the Streamlit page."""
    st.markdown(f"""
    <style>
        /* ── Import Google Fonts ────────────────────────────────────── */
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap');

        /* ── Global Overrides ───────────────────────────────────────── */
        .stApp {{
            font-family: {THEME['font_family']};
        }}

        /* ── Header Banner ──────────────────────────────────────────── */
        .app-header {{
            background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 50%, #0f172a 100%);
            border: 1px solid {THEME['border']};
            border-radius: 16px;
            padding: 2rem 2.5rem;
            margin-bottom: 2rem;
            position: relative;
            overflow: hidden;
        }}
        .app-header::before {{
            content: '';
            position: absolute;
            top: 0; left: 0; right: 0; bottom: 0;
            background: radial-gradient(ellipse at 30% 50%, {THEME['accent_glow']} 0%, transparent 70%);
            pointer-events: none;
        }}
        .app-header h1 {{
            font-size: 2rem;
            font-weight: 800;
            letter-spacing: -0.5px;
            background: linear-gradient(135deg, {THEME['accent_secondary']} 0%, #c084fc 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 0.3rem;
        }}
        .app-header p {{
            color: {THEME['text_secondary']};
            font-size: 0.95rem;
            font-weight: 400;
            margin: 0;
        }}

        /* ── Server Cards ───────────────────────────────────────────── */
        .server-card {{
            background: linear-gradient(145deg, {THEME['bg_card']} 0%, #151d30 100%);
            border: 1px solid {THEME['border']};
            border-radius: 12px;
            padding: 1.5rem;
            margin-bottom: 1rem;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }}
        .server-card:hover {{
            border-color: {THEME['border_hover']};
            box-shadow: 0 4px 24px {THEME['accent_glow']};
        }}
        .server-card-header {{
            display: flex;
            align-items: center;
            gap: 0.75rem;
            margin-bottom: 1rem;
        }}
        .server-card-header .badge {{
            background: linear-gradient(135deg, {THEME['accent_primary']}, {THEME['accent_secondary']});
            color: white;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.75rem;
            font-weight: 600;
            padding: 0.25rem 0.75rem;
            border-radius: 20px;
        }}
        .server-card-header .label {{
            color: {THEME['text_secondary']};
            font-size: 0.85rem;
            font-weight: 500;
        }}

        /* ── Status Pills ───────────────────────────────────────────── */
        .status-pill {{
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.78rem;
            font-weight: 500;
            padding: 0.3rem 0.85rem;
            border-radius: 20px;
            margin: 0.15rem 0.25rem;
        }}
        .status-success {{
            background: rgba(16, 185, 129, 0.12);
            color: {THEME['success']};
            border: 1px solid rgba(16, 185, 129, 0.25);
        }}
        .status-error {{
            background: rgba(239, 68, 68, 0.12);
            color: {THEME['error']};
            border: 1px solid rgba(239, 68, 68, 0.25);
        }}
        .status-warning {{
            background: rgba(245, 158, 11, 0.12);
            color: {THEME['warning']};
            border: 1px solid rgba(245, 158, 11, 0.25);
        }}
        .status-info {{
            background: rgba(99, 102, 241, 0.12);
            color: {THEME['accent_secondary']};
            border: 1px solid rgba(99, 102, 241, 0.25);
        }}

        /* ── Results Section ────────────────────────────────────────── */
        .results-header {{
            background: linear-gradient(135deg, #0f172a, #1e1b4b);
            border: 1px solid {THEME['border']};
            border-radius: 12px;
            padding: 1.25rem 1.75rem;
            margin: 1.5rem 0 1rem 0;
        }}
        .results-header h3 {{
            color: {THEME['text_primary']};
            font-weight: 700;
            margin: 0;
        }}

        /* ── Sidebar Styling ────────────────────────────────────────── */
        section[data-testid="stSidebar"] {{
            background: linear-gradient(180deg, #0f172a 0%, #1a1040 100%);
            border-right: 1px solid {THEME['border']};
        }}
        section[data-testid="stSidebar"] .stMarkdown h2 {{
            background: linear-gradient(135deg, {THEME['accent_secondary']}, #c084fc);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            font-weight: 700;
        }}

        /* ── Metric Cards ───────────────────────────────────────────── */
        .metric-card {{
            background: linear-gradient(145deg, {THEME['bg_card']}, #151d30);
            border: 1px solid {THEME['border']};
            border-radius: 12px;
            padding: 1.25rem;
            text-align: center;
            transition: all 0.3s ease;
        }}
        .metric-card:hover {{
            border-color: {THEME['border_hover']};
            transform: translateY(-2px);
            box-shadow: 0 8px 30px {THEME['accent_glow']};
        }}
        .metric-value {{
            font-family: 'JetBrains Mono', monospace;
            font-size: 2rem;
            font-weight: 700;
            background: linear-gradient(135deg, {THEME['accent_secondary']}, #c084fc);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        .metric-label {{
            color: {THEME['text_secondary']};
            font-size: 0.8rem;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-top: 0.3rem;
        }}

        /* ── Security Notice ────────────────────────────────────────── */
        .security-notice {{
            background: linear-gradient(135deg, rgba(16, 185, 129, 0.06), rgba(16, 185, 129, 0.02));
            border: 1px solid rgba(16, 185, 129, 0.2);
            border-radius: 10px;
            padding: 0.85rem 1.25rem;
            margin: 1rem 0;
            display: flex;
            align-items: center;
            gap: 0.6rem;
        }}
        .security-notice span {{
            color: {THEME['success']};
            font-size: 0.82rem;
            font-weight: 500;
        }}

        /* ── Log Entry ──────────────────────────────────────────────── */
        .log-entry {{
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.8rem;
            padding: 0.5rem 1rem;
            border-left: 3px solid {THEME['border']};
            margin: 0.3rem 0;
            background: rgba(15, 23, 42, 0.5);
            border-radius: 0 6px 6px 0;
        }}
        .log-entry.log-success {{ border-left-color: {THEME['success']}; }}
        .log-entry.log-error   {{ border-left-color: {THEME['error']}; }}
        .log-entry.log-warning {{ border-left-color: {THEME['warning']}; }}
        .log-entry.log-info    {{ border-left-color: {THEME['accent_primary']}; }}

        /* ── Button Overrides ───────────────────────────────────────── */
        .stButton > button[kind="primary"] {{
            background: linear-gradient(135deg, {THEME['accent_primary']}, #7c3aed) !important;
            border: none !important;
            font-weight: 600 !important;
            letter-spacing: 0.5px !important;
            transition: all 0.3s ease !important;
        }}
        .stButton > button[kind="primary"]:hover {{
            box-shadow: 0 4px 20px {THEME['accent_glow']} !important;
            transform: translateY(-1px) !important;
        }}

        /* ── Footer ─────────────────────────────────────────────────── */
        .app-footer {{
            text-align: center;
            padding: 2rem 0;
            color: {THEME['text_muted']};
            font-size: 0.78rem;
            border-top: 1px solid {THEME['border']};
            margin-top: 3rem;
        }}
    </style>
    """, unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════
#  HEADER COMPONENT
# ═══════════════════════════════════════════════════════════════════════════

def render_header():
    """Render the application header banner."""
    st.markdown("""
    <div class="app-header">
        <h1>🛡️ Unified Operations Toolkit</h1>
        <p>Enterprise Kubernetes Diagnostics Dashboard — Secure Multi-Cluster Remote Execution</p>
    </div>
    """, unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════
#  SECURITY NOTICE
# ═══════════════════════════════════════════════════════════════════════════

def render_security_notice():
    """Display the local storage security notice."""
    st.markdown(f"""
    <div class="security-notice">
        <span>💾 Local Storage Mode — Server profiles are saved to disk for persistence
        across sessions. SSH sessions remain encrypted and ephemeral.</span>
    </div>
    """, unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════
#  SERVER INPUT MATRIX
# ═══════════════════════════════════════════════════════════════════════════

def init_server_list():
    """
    Initialize the expandable target server array in session state.
    Loads previously saved servers from disk on first run.
    Falls back to a single empty entry if no saved data exists.
    """
    if "servers" not in st.session_state:
        st.session_state.servers = load_servers()


def add_server():
    """Append a fresh server dictionary to the session state array."""
    st.session_state.servers.append({"host": "", "username": "", "password": ""})


def remove_server(index: int):
    """Remove a server entry at the given index."""
    if len(st.session_state.servers) > 1:
        st.session_state.servers.pop(index)


def render_server_matrix():
    """
    Render the expandable target server input matrix.

    Uses st.session_state to preserve typed data across reruns.
    Each server entry gets its own card with Host IP, Username,
    and Password fields.
    """
    st.markdown("### 🖥️ Target Server Matrix")

    for idx, server in enumerate(st.session_state.servers):
        st.markdown(f"""
        <div class="server-card">
            <div class="server-card-header">
                <span class="badge">NODE {idx + 1}</span>
                <span class="label">Target Cluster Server</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

        cols = st.columns([3, 2, 2, 1])

        with cols[0]:
            host = st.text_input(
                "Host IP / FQDN",
                value=server.get("host", ""),
                key=f"host_{idx}",
                placeholder="e.g., 10.120.50.101",
            )

        with cols[1]:
            username = st.text_input(
                "Username",
                value=server.get("username", ""),
                key=f"user_{idx}",
                placeholder="e.g., admin",
            )

        with cols[2]:
            password = st.text_input(
                "Password",
                value=server.get("password", ""),
                key=f"pass_{idx}",
                type="password",
                placeholder="••••••••",
            )

        with cols[3]:
            st.markdown("<div style='height: 1.65rem'></div>", unsafe_allow_html=True)
            if len(st.session_state.servers) > 1:
                if st.button("✕", key=f"remove_{idx}", help="Remove this server"):
                    remove_server(idx)
                    st.rerun()

        # Sync widget values back into session state
        st.session_state.servers[idx]["host"] = host
        st.session_state.servers[idx]["username"] = username
        st.session_state.servers[idx]["password"] = password

    # Action buttons row
    btn_cols = st.columns([2, 1, 1])

    with btn_cols[0]:
        st.button(
            "➕ Add Another Server",
            on_click=add_server,
            use_container_width=True,
            type="secondary",
        )

    with btn_cols[1]:
        if st.button("💾 Save Servers", use_container_width=True, type="primary"):
            if save_servers(st.session_state.servers):
                st.toast("✅ Server profiles saved to disk.", icon="💾")
            else:
                st.toast("❌ Failed to save server profiles.", icon="⚠️")

    with btn_cols[2]:
        if st.button("🗑️ Clear Saved", use_container_width=True):
            delete_saved_servers()
            st.session_state.servers = [{"host": "", "username": "", "password": ""}]
            st.toast("🗑️ Saved server profiles cleared.", icon="🗑️")
            st.rerun()


# ═══════════════════════════════════════════════════════════════════════════
#  COMMAND SELECTOR SIDEBAR
# ═══════════════════════════════════════════════════════════════════════════

def render_command_sidebar() -> dict:
    """
    Render the diagnostic command selector in the sidebar.

    Returns
    -------
    dict
        Keys are command keys (str), values are dicts with:
        - enabled: bool
        - params:  dict of any required parameters (pod_name, source_ip, etc.)
    """
    with st.sidebar:
        st.markdown("## ⚡ Diagnostic Checks")
        st.markdown("---")

        selections = {}

        for cmd_def in DIAGNOSTIC_COMMANDS:
            key = cmd_def["key"]
            label = cmd_def["label"]

            enabled = st.checkbox(
                label,
                key=f"cmd_{key}",
                value=False,
            )

            params = {}

            # Collect additional parameters if this command requires them
            if enabled and cmd_def["requires"]:
                with st.container():
                    for param_name in cmd_def["requires"]:
                        friendly = param_name.replace("_", " ").title()
                        param_val = st.text_input(
                            f"  ↳ {friendly}",
                            key=f"param_{key}_{param_name}",
                            placeholder=f"Enter {friendly}",
                        )
                        params[param_name] = param_val

            selections[key] = {
                "enabled": enabled,
                "params": params,
                "definition": cmd_def,
            }

        st.markdown("---")

        # Quick-select helpers
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("Select All", use_container_width=True):
                for cmd_def in DIAGNOSTIC_COMMANDS:
                    st.session_state[f"cmd_{cmd_def['key']}"] = True
                st.rerun()
        with col_b:
            if st.button("Clear All", use_container_width=True):
                for cmd_def in DIAGNOSTIC_COMMANDS:
                    st.session_state[f"cmd_{cmd_def['key']}"] = False
                st.rerun()

        st.markdown("---")
        st.markdown("""
        <div class="security-notice" style="margin-top: 1rem;">
            <span>🔐 All commands execute over encrypted SSH channels.
            Server profiles are saved locally for convenience.</span>
        </div>
        """, unsafe_allow_html=True)

    return selections


# ═══════════════════════════════════════════════════════════════════════════
#  STATUS & LOG DISPLAY HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def render_status_pill(text: str, status: str = "info") -> str:
    """Return HTML for a styled status pill."""
    return f'<span class="status-pill status-{status}">{"●"} {text}</span>'


def render_log_entry(message: str, level: str = "info"):
    """Display a styled log line."""
    st.markdown(
        f'<div class="log-entry log-{level}">{message}</div>',
        unsafe_allow_html=True,
    )


def render_metric_cards(metrics: dict):
    """
    Display a row of metric summary cards.

    Parameters
    ----------
    metrics : dict
        Keys are label strings, values are (value, icon) tuples.
    """
    cols = st.columns(len(metrics))
    for col, (label, (value, icon)) in zip(cols, metrics.items()):
        with col:
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-value">{icon} {value}</div>
                <div class="metric-label">{label}</div>
            </div>
            """, unsafe_allow_html=True)


def render_footer():
    """Render the application footer."""
    st.markdown("""
    <div class="app-footer">
        Unified Operations Toolkit • Local Storage Persistence •
        Enterprise Kubernetes Diagnostics
    </div>
    """, unsafe_allow_html=True)

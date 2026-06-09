#!/usr/bin/env python3
"""
app.py — Main entry point for the Unified Operations Toolkit.

A production-ready Streamlit dashboard for executing remote Kubernetes
diagnostic commands across multiple target cluster servers via SSH.

SECURITY MODEL: Zero-retention, in-memory-only credential handling.
All server IPs, usernames, and passwords exist solely in volatile
st.session_state dictionaries and are never written to disk.

Launch:
    streamlit run app.py
"""

import streamlit as st
import pandas as pd
from datetime import datetime

# ── Project Modules ─────────────────────────────────────────────────────
from config import (
    APP_TITLE,
    APP_ICON,
    APP_SUBTITLE,
    DIAGNOSTIC_COMMANDS,
)
from ssh_handler import (
    create_ssh_client,
    execute_remote_command,
    close_ssh_client,
    SSHConnectionError,
)
from data_processor import (
    parse_whitespace_table,
    parse_dlb_peerlist,
    parse_ping_result,
    parse_raw_output,
    aggregate_dataframes,
    dataframe_to_csv_bytes,
)
from ui_components import (
    inject_custom_css,
    render_header,
    render_security_notice,
    init_server_list,
    render_server_matrix,
    render_command_sidebar,
    render_status_pill,
    render_log_entry,
    render_metric_cards,
    render_footer,
)

# ═══════════════════════════════════════════════════════════════════════════
#  PAGE CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title=APP_TITLE,
    page_icon=APP_ICON,
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "About": f"### {APP_TITLE}\n{APP_SUBTITLE}\n\nSecure multi-cluster Kubernetes diagnostics.",
    },
)

# ═══════════════════════════════════════════════════════════════════════════
#  INITIALIZATION
# ═══════════════════════════════════════════════════════════════════════════

# Inject premium dark-theme CSS
inject_custom_css()

# Initialize session state for the expandable server list
init_server_list()

# Initialize results storage in session state
if "results_df" not in st.session_state:
    st.session_state.results_df = None
if "execution_log" not in st.session_state:
    st.session_state.execution_log = []
if "last_run_time" not in st.session_state:
    st.session_state.last_run_time = None


# ═══════════════════════════════════════════════════════════════════════════
#  ORCHESTRATION ENGINE
# ═══════════════════════════════════════════════════════════════════════════

def run_diagnostics(servers: list, selected_commands: dict):
    """
    Core orchestration pipeline.

    Loops sequentially through the user-defined array of target servers,
    establishes independent SSH channels, executes selected diagnostic
    commands, parses output, and aggregates results.

    Parameters
    ----------
    servers : list[dict]
        Each dict contains 'host', 'username', 'password' keys.
    selected_commands : dict
        Output from render_command_sidebar() — only 'enabled' entries
        are executed.

    Returns
    -------
    pd.DataFrame
        Unified aggregated results across all servers and commands.
    list
        Execution log entries for the UI.
    """
    all_frames = []
    execution_log = []
    active_checks = {k: v for k, v in selected_commands.items() if v["enabled"]}

    total_ops = len(servers) * len(active_checks)
    progress_bar = st.progress(0, text="Initializing diagnostic pipeline...")
    status_container = st.container()
    completed = 0

    for server_idx, server in enumerate(servers):
        host = server["host"].strip()
        username = server["username"].strip()
        password = server["password"]

        if not host or not username or not password:
            msg = f"⚠️ Server #{server_idx + 1}: Incomplete credentials — skipped."
            execution_log.append(("warning", msg))
            completed += len(active_checks)
            continue

        # ── Establish SSH Connection ────────────────────────────────
        ssh_client = None
        try:
            with status_container:
                render_log_entry(
                    f"🔗 Connecting to <b>{host}</b> ...",
                    "info",
                )

            ssh_client = create_ssh_client(
                hostname=host,
                username=username,
                password=password,
            )

            execution_log.append((
                "success",
                f"✅ {host} — SSH connection established.",
            ))

        except SSHConnectionError as e:
            msg = f"❌ {host} — {e.error_type}: {e.message}"
            execution_log.append(("error", msg))

            with status_container:
                render_log_entry(msg, "error")

            # Skip all commands for this server, move to next
            completed += len(active_checks)
            progress_bar.progress(
                min(completed / total_ops, 1.0),
                text=f"Skipped {host} — connection failed",
            )
            continue

        # ── Execute Selected Commands ───────────────────────────────
        try:
            for cmd_key, cmd_info in active_checks.items():
                cmd_def = cmd_info["definition"]
                params = cmd_info["params"]
                completed += 1

                progress_bar.progress(
                    min(completed / total_ops, 1.0),
                    text=f"[{host}] Running: {cmd_def['label']}",
                )

                # Build the command string with parameter substitution
                try:
                    command_str = cmd_def["cmd"].format(**params)
                except KeyError as ke:
                    msg = f"⚠️ {host} / {cmd_def['label']}: Missing parameter {ke} — skipped."
                    execution_log.append(("warning", msg))
                    continue

                # Execute the remote command
                try:
                    stdout_text, stderr_text = execute_remote_command(
                        ssh_client, command_str, host,
                    )

                    if stderr_text and not stdout_text:
                        msg = f"⚠️ {host} / {cmd_def['label']}: stderr → {stderr_text[:120]}"
                        execution_log.append(("warning", msg))

                    # ── Parse Output Based on Command Type ──────────
                    if cmd_key == "dlb_peers":
                        df = parse_dlb_peerlist(
                            stdout_text,
                            source_ip=host,
                            pod_name=params.get("pod_name", "unknown"),
                        )
                    elif cmd_key == "ping_test":
                        df = parse_ping_result(
                            stdout_text,
                            source_ip=host,
                            ping_source=params.get("source_ip", ""),
                            ping_dest=params.get("dest_ip", ""),
                        )
                    elif cmd_def["columns"] == ["RAW_OUTPUT"]:
                        df = parse_raw_output(stdout_text, host, cmd_key)
                    else:
                        df = parse_whitespace_table(
                            stdout_text,
                            expected_columns=cmd_def["columns"],
                            source_ip=host,
                            command_key=cmd_key,
                        )

                    if not df.empty:
                        all_frames.append(df)
                        msg = f"✅ {host} / {cmd_def['label']}: {len(df)} row(s) captured."
                    else:
                        msg = f"ℹ️ {host} / {cmd_def['label']}: No output returned."

                    execution_log.append(("success" if not df.empty else "info", msg))

                    with status_container:
                        render_log_entry(msg, "success" if not df.empty else "warning")

                except SSHConnectionError as e:
                    msg = f"❌ {host} / {cmd_def['label']}: {e.message}"
                    execution_log.append(("error", msg))
                    with status_container:
                        render_log_entry(msg, "error")
                    # Continue to next command — fault isolation
                    continue

        finally:
            # ── Always tear down the SSH connection ──────────────────
            close_ssh_client(ssh_client)
            execution_log.append((
                "info",
                f"🔒 {host} — SSH session closed. Credentials purged from memory.",
            ))

    progress_bar.progress(1.0, text="✅ Diagnostic pipeline complete.")
    return aggregate_dataframes(all_frames), execution_log


# ═══════════════════════════════════════════════════════════════════════════
#  MAIN APPLICATION LAYOUT
# ═══════════════════════════════════════════════════════════════════════════

def main():
    """Compose the full application UI and wire up the orchestration."""

    # ── Header ──────────────────────────────────────────────────────
    render_header()
    render_security_notice()

    # ── Sidebar: Command Selector ───────────────────────────────────
    selected_commands = render_command_sidebar()

    # ── Main Content: Server Matrix ─────────────────────────────────
    render_server_matrix()

    st.markdown("---")

    # ── Validation & Run Button ─────────────────────────────────────
    active_cmds = [v for v in selected_commands.values() if v["enabled"]]
    valid_servers = [
        s for s in st.session_state.servers
        if s.get("host", "").strip() and s.get("username", "").strip() and s.get("password", "")
    ]

    # Pre-flight status
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(
            render_status_pill(
                f"{len(valid_servers)} server(s) configured",
                "success" if valid_servers else "warning",
            ),
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            render_status_pill(
                f"{len(active_cmds)} check(s) selected",
                "success" if active_cmds else "warning",
            ),
            unsafe_allow_html=True,
        )
    with col3:
        if st.session_state.last_run_time:
            st.markdown(
                render_status_pill(
                    f"Last run: {st.session_state.last_run_time}",
                    "info",
                ),
                unsafe_allow_html=True,
            )

    st.markdown("")

    # ── Run Diagnostics Button ──────────────────────────────────────
    can_run = bool(valid_servers) and bool(active_cmds)

    if st.button(
        "🚀  Run Diagnostics",
        type="primary",
        use_container_width=True,
        disabled=not can_run,
    ):
        if not can_run:
            st.error("Please configure at least one server and select at least one diagnostic check.")
            return

        # Execute the orchestration pipeline
        with st.spinner(""):
            results_df, execution_log = run_diagnostics(
                st.session_state.servers,
                selected_commands,
            )

        # Persist results in session state
        st.session_state.results_df = results_df
        st.session_state.execution_log = execution_log
        st.session_state.last_run_time = datetime.now().strftime("%H:%M:%S")

    # ═══════════════════════════════════════════════════════════════════
    #  RESULTS DISPLAY
    # ═══════════════════════════════════════════════════════════════════

    if st.session_state.results_df is not None:
        df = st.session_state.results_df
        log = st.session_state.execution_log

        st.markdown("""
        <div class="results-header">
            <h3>📊 Diagnostic Results</h3>
        </div>
        """, unsafe_allow_html=True)

        # ── Summary Metrics ─────────────────────────────────────────
        successes = sum(1 for level, _ in log if level == "success")
        errors = sum(1 for level, _ in log if level == "error")
        warnings = sum(1 for level, _ in log if level == "warning")
        total_rows = len(df) if not df.empty else 0

        render_metric_cards({
            "Data Rows": (str(total_rows), "📋"),
            "Successful": (str(successes), "✅"),
            "Warnings": (str(warnings), "⚠️"),
            "Errors": (str(errors), "❌"),
        })

        st.markdown("")

        # ── Execution Log (Collapsible) ─────────────────────────────
        with st.expander("📝 Execution Log", expanded=False):
            for level, message in log:
                render_log_entry(message, level)

        # ── Data Grid Display ───────────────────────────────────────
        if not df.empty:
            # Group by CHECK_TYPE for organized display
            if "CHECK_TYPE" in df.columns:
                check_types = df["CHECK_TYPE"].unique()

                tabs = st.tabs(
                    ["📊 All Results"] + [f"🔍 {ct}" for ct in check_types]
                )

                # Tab 0: Combined view
                with tabs[0]:
                    st.dataframe(
                        df,
                        use_container_width=True,
                        height=min(400, 40 + len(df) * 35),
                    )

                # Per-check tabs
                for i, check_type in enumerate(check_types):
                    with tabs[i + 1]:
                        filtered = df[df["CHECK_TYPE"] == check_type].reset_index(drop=True)
                        st.dataframe(
                            filtered,
                            use_container_width=True,
                            height=min(400, 40 + len(filtered) * 35),
                        )
            else:
                st.dataframe(df, use_container_width=True)

            # ── CSV Download Button ─────────────────────────────────
            st.markdown("")
            csv_bytes = dataframe_to_csv_bytes(df)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            col_dl1, col_dl2, col_dl3 = st.columns([1, 2, 1])
            with col_dl2:
                st.download_button(
                    label="📥  Download Full Report as CSV",
                    data=csv_bytes,
                    file_name=f"diagnostic_report_{timestamp}.csv",
                    mime="text/csv",
                    use_container_width=True,
                    type="primary",
                )

        else:
            st.info(
                "No data rows were captured. Check the execution log above "
                "for connection errors or empty command outputs.",
                icon="ℹ️",
            )

    # ── Footer ──────────────────────────────────────────────────────
    render_footer()


# ═══════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    main()

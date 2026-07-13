import streamlit as st
import pandas as pd
from datetime import datetime

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

st.set_page_config(
    page_title=APP_TITLE,
    page_icon=APP_ICON,
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "About": f"### {APP_TITLE}\n{APP_SUBTITLE}\n\nSecure multi-cluster Kubernetes diagnostics.",
    },
)

inject_custom_css()
init_server_list()

if "results_df" not in st.session_state:
    st.session_state.results_df = None
if "execution_log" not in st.session_state:
    st.session_state.execution_log = []
if "last_run_time" not in st.session_state:
    st.session_state.last_run_time = None
if "custom_cmd_results" not in st.session_state:
    st.session_state.custom_cmd_results = None


def run_diagnostics(servers: list, selected_commands: dict):
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

            completed += len(active_checks)
            progress_bar.progress(
                min(completed / total_ops, 1.0),
                text=f"Skipped {host} — connection failed",
            )
            continue

        try:
            for cmd_key, cmd_info in active_checks.items():
                cmd_def = cmd_info["definition"]
                params = cmd_info["params"]
                completed += 1

                progress_bar.progress(
                    min(completed / total_ops, 1.0),
                    text=f"[{host}] Running: {cmd_def['label']}",
                )

                namespace = st.session_state.get("namespace", "").strip()
                if namespace:
                    params["namespace"] = namespace
                elif "{namespace}" in cmd_def["cmd"]:
                    msg = f"⚠️ {host} / {cmd_def['label']}: Namespace required but not provided — skipped."
                    execution_log.append(("warning", msg))
                    with status_container:
                        render_log_entry(msg, "warning")
                    continue

                try:
                    command_str = cmd_def["cmd"].format(**params)
                except KeyError as ke:
                    msg = f"⚠️ {host} / {cmd_def['label']}: Missing parameter {ke} — skipped."
                    execution_log.append(("warning", msg))
                    continue

                try:
                    stdout_text, stderr_text = execute_remote_command(
                        ssh_client, command_str, host,
                    )

                    if stderr_text and not stdout_text:
                        msg = f"⚠️ {host} / {cmd_def['label']}: stderr → {stderr_text[:120]}"
                        execution_log.append(("warning", msg))

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
                    continue

        finally:
            close_ssh_client(ssh_client)
            execution_log.append((
                "info",
                f"🔒 {host} — SSH session closed. Credentials purged from memory.",
            ))

    progress_bar.progress(1.0, text="✅ Diagnostic pipeline complete.")
    return aggregate_dataframes(all_frames), execution_log


def run_custom_command(servers: list, command: str):
    """Execute a single command on every server and return per-host results."""
    results = []
    total = len(servers)
    progress_bar = st.progress(0, text="Initializing custom command pipeline...")
    status_container = st.container()

    for idx, server in enumerate(servers):
        host = server["host"].strip()
        username = server["username"].strip()
        password = server["password"]

        if not host or not username or not password:
            results.append({
                "host": host or f"Server #{idx + 1}",
                "status": "skipped",
                "stdout": "",
                "stderr": "Incomplete credentials — skipped.",
            })
            progress_bar.progress(
                min((idx + 1) / total, 1.0),
                text=f"Skipped {host or f'Server #{idx + 1}'} — incomplete credentials",
            )
            continue

        ssh_client = None
        try:
            progress_bar.progress(
                min((idx + 0.5) / total, 1.0),
                text=f"Connecting to {host}...",
            )
            with status_container:
                render_log_entry(f"🔗 Connecting to <b>{host}</b> ...", "info")

            ssh_client = create_ssh_client(
                hostname=host,
                username=username,
                password=password,
            )

            progress_bar.progress(
                min((idx + 0.7) / total, 1.0),
                text=f"[{host}] Running: {command[:50]}...",
            )

            stdout_text, stderr_text = execute_remote_command(
                ssh_client, command, host,
            )

            results.append({
                "host": host,
                "status": "success",
                "stdout": stdout_text,
                "stderr": stderr_text,
            })

            with status_container:
                render_log_entry(f"✅ {host} — command executed.", "success")

        except SSHConnectionError as e:
            results.append({
                "host": host,
                "status": "error",
                "stdout": "",
                "stderr": f"{e.error_type}: {e.message}",
            })
            with status_container:
                render_log_entry(f"❌ {host} — {e.error_type}: {e.message}", "error")

        finally:
            close_ssh_client(ssh_client)

        progress_bar.progress(
            min((idx + 1) / total, 1.0),
            text=f"Completed {idx + 1}/{total} servers",
        )

    progress_bar.progress(1.0, text="✅ Custom command execution complete.")
    return results


def main():

    render_header()
    render_security_notice()

    selected_commands = render_command_sidebar()

    render_server_matrix()

    st.markdown("---")

    active_cmds = [v for v in selected_commands.values() if v["enabled"]]
    valid_servers = [
        s for s in st.session_state.servers
        if s.get("host", "").strip() and s.get("username", "").strip() and s.get("password", "")
    ]

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

    can_run = bool(valid_servers) and bool(active_cmds)

    namespace = st.session_state.get("namespace", "").strip()
    namespaced_cmds_selected = any(
        "{namespace}" in v["definition"]["cmd"]
        for v in active_cmds
    )
    if not namespace and namespaced_cmds_selected:
        st.warning(
            "⚠️ **Namespace not set.** Some selected checks (StatefulSet, Certificate, PVC, Pods, DLB) "
            "require a Kubernetes namespace. Enter it in the sidebar before running.",
            icon="🏷️",
        )

    if st.button(
        "🚀  Run Diagnostics",
        type="primary",
        use_container_width=True,
        disabled=not can_run,
    ):
        if not can_run:
            st.error("Please configure at least one server and select at least one diagnostic check.")
            return

        with st.spinner(""):
            results_df, execution_log = run_diagnostics(
                st.session_state.servers,
                selected_commands,
            )

        st.session_state.results_df = results_df
        st.session_state.execution_log = execution_log
        st.session_state.last_run_time = datetime.now().strftime("%H:%M:%S")

    if st.session_state.results_df is not None:
        df = st.session_state.results_df
        log = st.session_state.execution_log

        st.markdown("""
        <div class="results-header">
            <h3>📊 Diagnostic Results</h3>
        </div>
        """, unsafe_allow_html=True)

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

        with st.expander("📝 Execution Log", expanded=False):
            for level, message in log:
                render_log_entry(message, level)

        if not df.empty:
            if "CHECK_TYPE" in df.columns:
                check_types = df["CHECK_TYPE"].unique()

                tabs = st.tabs(
                    ["📊 All Results"] + [f"🔍 {ct}" for ct in check_types]
                )

                with tabs[0]:
                    st.dataframe(
                        df,
                        use_container_width=True,
                        height=min(400, 40 + len(df) * 35),
                    )

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

    # ── Custom Command Execution Section ──────────────────────────────
    st.markdown("---")
    st.markdown("""
    <div class="results-header">
        <h3>⚡ Custom Command Execution</h3>
    </div>
    """, unsafe_allow_html=True)

    st.markdown(
        '<p style="color: #94a3b8; font-size: 0.9rem; margin-bottom: 1rem;">'
        'Enter any command below and execute it across <b>all configured servers</b> simultaneously. '
        'Results are displayed per-node.</p>',
        unsafe_allow_html=True,
    )

    custom_cmd = st.text_input(
        "🔧 Command",
        key="custom_command_input",
        placeholder="e.g., kubectl get nodes, uptime, df -h, free -m",
        help="This command will be executed on every server in the Target Server Matrix above.",
    )

    can_run_custom = bool(valid_servers) and bool(custom_cmd and custom_cmd.strip())

    if st.button(
        "⚡  Execute on All Nodes",
        type="primary",
        use_container_width=True,
        disabled=not can_run_custom,
        key="run_custom_cmd_btn",
    ):
        with st.spinner(""):
            st.session_state.custom_cmd_results = run_custom_command(
                st.session_state.servers,
                custom_cmd.strip(),
            )

    if st.session_state.custom_cmd_results is not None:
        results = st.session_state.custom_cmd_results

        successes = sum(1 for r in results if r["status"] == "success")
        errors = sum(1 for r in results if r["status"] == "error")
        skipped = sum(1 for r in results if r["status"] == "skipped")

        render_metric_cards({
            "Nodes": (str(len(results)), "🖥️"),
            "Successful": (str(successes), "✅"),
            "Failed": (str(errors), "❌"),
            "Skipped": (str(skipped), "⏭️"),
        })

        st.markdown("")

        for r in results:
            host_label = r["host"]
            if r["status"] == "success":
                icon = "✅"
            elif r["status"] == "error":
                icon = "❌"
            else:
                icon = "⏭️"

            with st.expander(f"{icon}  {host_label}", expanded=(r["status"] == "success")):
                if r["stdout"]:
                    st.markdown(
                        f'<span style="color: #10b981; font-size: 0.8rem; font-weight: 600; '
                        f'text-transform: uppercase; letter-spacing: 0.5px;">Standard Output</span>',
                        unsafe_allow_html=True,
                    )
                    st.code(r["stdout"], language="text")

                if r["stderr"]:
                    st.markdown(
                        f'<span style="color: #f59e0b; font-size: 0.8rem; font-weight: 600; '
                        f'text-transform: uppercase; letter-spacing: 0.5px;">Standard Error</span>',
                        unsafe_allow_html=True,
                    )
                    st.code(r["stderr"], language="text")

                if not r["stdout"] and not r["stderr"]:
                    st.info("No output returned.", icon="ℹ️")

    render_footer()


if __name__ == "__main__":
    main()

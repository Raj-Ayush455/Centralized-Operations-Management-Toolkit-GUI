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
    classify_dataframe,
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
                "info",
                f"🔗 {host} — SSH connection established.",
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
                        log_level = "success"
                    else:
                        msg = f"⚠️ {host} / {cmd_def['label']}: No output returned."
                        log_level = "warning"

                    execution_log.append((log_level, msg))

                    with status_container:
                        render_log_entry(msg, log_level)

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

    # ── Mock Data Button (for local UI testing without real servers) ──
    with st.expander("🧪 Load Mock Data (Testing Only)", expanded=False):
        st.caption("Use this to test the UI without connecting to real servers.")
        if st.button("🧪  Load Sample Results", key="load_mock_data"):
            mock_log = [
                ("info",    "🔗 10.120.50.101 — SSH connection established."),
                ("success", "✅ 10.120.50.101 / Worker Node Status Check: 5 row(s) captured."),
                ("success", "✅ 10.120.50.101 / Service Status Check: 4 row(s) captured."),
                ("success", "✅ 10.120.50.101 / CPU Capacity Audit: 5 row(s) captured."),
                ("success", "✅ 10.120.50.101 / StatefulSet Health Check: 4 row(s) captured."),
                ("success", "✅ 10.120.50.101 / Certificate Readiness Check: 4 row(s) captured."),
                ("success", "✅ 10.120.50.101 / PVC Binding Health Check: 4 row(s) captured."),
                ("info",    "🔒 10.120.50.101 — SSH session closed."),
                ("info",    "🔗 10.120.50.102 — SSH connection established."),
                ("success", "✅ 10.120.50.102 / Pod Readiness Check: 8 row(s) captured."),
                ("success", "✅ 10.120.50.102 / Diameter LB Peer Check: 4 row(s) captured."),
                ("success", "✅ 10.120.50.102 / Source Interface Ping Test: 4 row(s) captured."),
                ("info",    "🔒 10.120.50.102 — SSH session closed."),
            ]

            # ── Worker Nodes (healthy + 1 NotReady) ──
            mock_nodes = pd.DataFrame({
                "SOURCE_SERVER": ["10.120.50.101"] * 5,
                "NAME":       ["node-1", "node-2", "node-3", "node-4", "node-5"],
                "STATUS":     ["Ready", "Ready", "NotReady", "Ready", "Ready"],
                "ROLES":      ["worker"] * 5,
                "AGE":        ["45d", "45d", "12d", "45d", "30d"],
                "VERSION":    ["v1.28.2"] * 5,
                "CHECK_TYPE": ["worker_nodes"] * 5,
            })

            # ── Services (all healthy — informational) ──
            mock_services = pd.DataFrame({
                "SOURCE_SERVER": ["10.120.50.101"] * 4,
                "NAME":       ["api-gateway", "user-service", "payment-svc", "cache-redis"],
                "TYPE":       ["ClusterIP", "ClusterIP", "LoadBalancer", "ClusterIP"],
                "CLUSTER_IP": ["10.96.0.10", "10.96.0.11", "10.96.0.12", "10.96.0.13"],
                "EXTERNAL_IP": ["<none>", "<none>", "203.0.113.50", "<none>"],
                "PORTS":      ["8080/TCP", "8081/TCP", "443/TCP", "6379/TCP"],
                "AGE":        ["90d", "90d", "60d", "90d"],
                "CHECK_TYPE": ["services"] * 4,
            })

            # ── CPU Audit (healthy + warning + critical) ──
            mock_cpu = pd.DataFrame({
                "SOURCE_SERVER": ["10.120.50.101"] * 5,
                "NAME":       ["node-1", "node-2", "node-3", "node-4", "node-5"],
                "CPU_CORES":  ["1200m", "3800m", "950m", "4200m", "800m"],
                "CPU_%":      ["45%", "91%", "12%", "96%", "78%"],
                "MEMORY_BYTES": ["4Gi", "7Gi", "2Gi", "7.5Gi", "3Gi"],
                "MEMORY_%":   ["52%", "88%", "30%", "97%", "65%"],
                "CHECK_TYPE": ["cpu_audit"] * 5,
            })

            # ── StatefulSet (healthy + partial + zero ready) ──
            mock_sts = pd.DataFrame({
                "SOURCE_SERVER": ["10.120.50.101"] * 4,
                "NAME":       ["mysql-primary", "redis-cluster", "kafka-broker", "zookeeper"],
                "READY":      ["3/3", "2/3", "0/3", "3/3"],
                "AGE":        ["60d", "60d", "5d", "60d"],
                "CHECK_TYPE": ["statefulset"] * 4,
            })

            # ── Certificates (healthy + not ready) ──
            mock_certs = pd.DataFrame({
                "SOURCE_SERVER": ["10.120.50.101"] * 4,
                "NAME":       ["tls-api-cert", "tls-ingress-cert", "tls-internal-cert", "tls-expired-cert"],
                "READY":      ["True", "True", "False", "False"],
                "SECRET":     ["api-tls-secret", "ingress-tls-secret", "internal-tls-secret", "expired-tls-secret"],
                "AGE":        ["120d", "90d", "2d", "365d"],
                "CHECK_TYPE": ["certificates"] * 4,
            })

            # ── PVC (Bound + Pending + Lost) ──
            mock_pvc = pd.DataFrame({
                "SOURCE_SERVER": ["10.120.50.101"] * 4,
                "NAME":       ["data-mysql-0", "data-redis-0", "data-kafka-0", "data-orphan-0"],
                "STATUS":     ["Bound", "Bound", "Pending", "Lost"],
                "VOLUME":     ["pv-001", "pv-002", "", "pv-old"],
                "CAPACITY":   ["50Gi", "20Gi", "", "10Gi"],
                "ACCESS_MODES": ["RWO", "RWO", "", "RWO"],
                "STORAGECLASS": ["standard", "standard", "standard", "standard"],
                "AGE":        ["60d", "60d", "1h", "200d"],
                "CHECK_TYPE": ["pvc"] * 4,
            })

            # ── Pods (Running + CrashLoop + Pending + high restarts) ──
            mock_pods = pd.DataFrame({
                "SOURCE_SERVER": ["10.120.50.102"] * 8,
                "NAME":       ["api-pod-1", "api-pod-2", "worker-pod-1", "db-pod-1",
                               "cache-pod-1", "init-pod-1", "err-pod-1", "flaky-pod-1"],
                "READY":      ["1/1", "1/1", "1/1", "1/1", "1/1", "0/1", "0/1", "1/1"],
                "STATUS":     ["Running", "Running", "Running", "Running",
                               "Running", "Pending", "CrashLoopBackOff", "Running"],
                "RESTARTS":   ["0", "2", "1", "0", "8", "0", "42", "12"],
                "AGE":        ["3d", "3d", "1d", "5d", "2d", "10m", "3d", "7d"],
                "IP":         ["10.0.0.1", "10.0.0.2", "10.0.0.3", "10.0.0.4",
                               "10.0.0.5", "", "10.0.0.7", "10.0.0.8"],
                "NODE":       ["node-1", "node-1", "node-2", "node-3",
                               "node-3", "node-4", "node-2", "node-5"],
                "NOMINATED_NODE": [""] * 8,
                "READINESS_GATES": [""] * 8,
                "CHECK_TYPE": ["pods"] * 8,
            })

            # ── DLB Peers (OPEN + CLOSED + WAITING) ──
            mock_dlb = pd.DataFrame({
                "SOURCE_SERVER": ["10.120.50.102"] * 4,
                "POD":        ["dlb-pod-1"] * 4,
                "ADDRESS":    ["aaa://10.0.1.1:3868", "aaa://10.0.1.2:3868",
                               "aaa://10.0.1.3:3868", "aaa://10.0.1.4:3868"],
                "STATUS":     ["OPEN", "OPEN", "CLOSED", "WAITING"],
                "CHECK_TYPE": ["dlb_peers"] * 4,
            })

            # ── Ping Test (REACHABLE + UNREACHABLE) ──
            mock_ping = pd.DataFrame({
                "SOURCE_SERVER": ["10.120.50.102"] * 4,
                "PING_SOURCE": ["10.120.50.102"] * 4,
                "PING_DEST":  ["10.0.1.1", "10.0.1.2", "10.0.1.3", "10.0.1.4"],
                "RESULT":     ["REACHABLE", "REACHABLE", "UNREACHABLE", "REACHABLE"],
                "RTT_MS":     ["1.23", "0.89", "N/A", "2.10"],
                "CHECK_TYPE": ["ping_test"] * 4,
            })

            mock_df = pd.concat([
                mock_nodes, mock_services, mock_cpu, mock_sts, mock_certs,
                mock_pvc, mock_pods, mock_dlb, mock_ping,
            ], ignore_index=True)
            st.session_state.results_df = mock_df
            st.session_state.execution_log = mock_log
            st.session_state.last_run_time = datetime.now().strftime("%H:%M:%S")
            st.rerun()

    if st.session_state.results_df is not None:
        df = st.session_state.results_df
        log = st.session_state.execution_log

        st.markdown("""
        <div class="results-header">
            <h3>📊 Diagnostic Results</h3>
        </div>
        """, unsafe_allow_html=True)

        # ── Classify data rows by actual health ──
        if not df.empty:
            classified_df = classify_dataframe(df)
            healthy_df = classified_df[classified_df["HEALTH_STATUS"] == "healthy"].reset_index(drop=True)
            warning_df = classified_df[classified_df["HEALTH_STATUS"] == "warning"].reset_index(drop=True)
            critical_df = classified_df[classified_df["HEALTH_STATUS"] == "critical"].reset_index(drop=True)
        else:
            classified_df = df
            healthy_df = pd.DataFrame()
            warning_df = pd.DataFrame()
            critical_df = pd.DataFrame()

        total_rows = len(df) if not df.empty else 0
        n_healthy = len(healthy_df)
        n_warning = len(warning_df)
        n_critical = len(critical_df)

        # ── Metric card buttons (premium flashy styling) ──
        st.markdown("""
        <style>
            .metric-cards-marker { display: none; }

            /* ── Base card style ── */
            [data-testid="stElementContainer"]:has(.metric-cards-marker)
              + [data-testid="stElementContainer"] [data-testid="stColumn"] {
                padding: 0 0.35rem !important;
            }
            [data-testid="stElementContainer"]:has(.metric-cards-marker)
              + [data-testid="stElementContainer"] button {
                background: linear-gradient(160deg, #1a2236 0%, #0f1729 50%, #1a1040 100%) !important;
                border: 1px solid rgba(99, 102, 241, 0.2) !important;
                border-radius: 16px !important;
                padding: 1.5rem 0.75rem 1.2rem !important;
                min-height: 120px !important;
                font-family: 'JetBrains Mono', monospace !important;
                font-size: 1.6rem !important;
                font-weight: 800 !important;
                color: #f1f5f9 !important;
                transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1) !important;
                width: 100% !important;
                position: relative !important;
                overflow: hidden !important;
                text-shadow: 0 1px 3px rgba(0, 0, 0, 0.3) !important;
                letter-spacing: 0.5px !important;
            }
            /* Animated shimmer overlay */
            [data-testid="stElementContainer"]:has(.metric-cards-marker)
              + [data-testid="stElementContainer"] button::before {
                content: '';
                position: absolute;
                top: 0; left: -100%; right: 0; bottom: 0;
                width: 200%;
                background: linear-gradient(
                    115deg,
                    transparent 20%,
                    rgba(255, 255, 255, 0.03) 40%,
                    rgba(255, 255, 255, 0.07) 50%,
                    rgba(255, 255, 255, 0.03) 60%,
                    transparent 80%
                );
                animation: cardShimmer 6s ease-in-out infinite;
                pointer-events: none;
            }
            @keyframes cardShimmer {
                0%, 100% { transform: translateX(-30%); }
                50% { transform: translateX(30%); }
            }
            /* Hover glow */
            [data-testid="stElementContainer"]:has(.metric-cards-marker)
              + [data-testid="stElementContainer"] button:hover {
                transform: translateY(-4px) scale(1.02) !important;
                box-shadow:
                    0 10px 40px rgba(99, 102, 241, 0.3),
                    0 0 20px rgba(99, 102, 241, 0.15),
                    inset 0 1px 0 rgba(255, 255, 255, 0.05) !important;
                border-color: rgba(99, 102, 241, 0.5) !important;
            }
            /* Disabled */
            [data-testid="stElementContainer"]:has(.metric-cards-marker)
              + [data-testid="stElementContainer"] button:disabled {
                opacity: 0.6 !important;
                transform: none !important;
                cursor: default !important;
            }
            /* Inner text styling */
            [data-testid="stElementContainer"]:has(.metric-cards-marker)
              + [data-testid="stElementContainer"] button p {
                font-family: 'JetBrains Mono', monospace !important;
                font-size: 1.6rem !important;
                font-weight: 800 !important;
                line-height: 1.4 !important;
            }

            /* ── Per-card accent colors (using nth-child on columns) ── */

            /* Card 1: Total — Indigo glow */
            [data-testid="stElementContainer"]:has(.metric-cards-marker)
              + [data-testid="stElementContainer"] [data-testid="stColumn"]:nth-child(1) button {
                background: linear-gradient(160deg, #1a2236 0%, #1e1b4b 60%, #1a2236 100%) !important;
                border-color: rgba(99, 102, 241, 0.3) !important;
                box-shadow: 0 4px 20px rgba(99, 102, 241, 0.12), inset 0 1px 0 rgba(255,255,255,0.04) !important;
            }

            /* Card 2: Healthy — Emerald glow */
            [data-testid="stElementContainer"]:has(.metric-cards-marker)
              + [data-testid="stElementContainer"] [data-testid="stColumn"]:nth-child(2) button {
                background: linear-gradient(160deg, #0f2922 0%, #064e3b 40%, #0f2922 100%) !important;
                border-color: rgba(16, 185, 129, 0.3) !important;
                box-shadow: 0 4px 20px rgba(16, 185, 129, 0.12), inset 0 1px 0 rgba(255,255,255,0.04) !important;
            }
            [data-testid="stElementContainer"]:has(.metric-cards-marker)
              + [data-testid="stElementContainer"] [data-testid="stColumn"]:nth-child(2) button:hover {
                box-shadow:
                    0 10px 40px rgba(16, 185, 129, 0.3),
                    0 0 25px rgba(16, 185, 129, 0.15),
                    inset 0 1px 0 rgba(255,255,255,0.06) !important;
                border-color: rgba(16, 185, 129, 0.6) !important;
            }

            /* Card 3: Warning — Amber glow */
            [data-testid="stElementContainer"]:has(.metric-cards-marker)
              + [data-testid="stElementContainer"] [data-testid="stColumn"]:nth-child(3) button {
                background: linear-gradient(160deg, #27200a 0%, #451a03 40%, #27200a 100%) !important;
                border-color: rgba(245, 158, 11, 0.3) !important;
                box-shadow: 0 4px 20px rgba(245, 158, 11, 0.12), inset 0 1px 0 rgba(255,255,255,0.04) !important;
            }
            [data-testid="stElementContainer"]:has(.metric-cards-marker)
              + [data-testid="stElementContainer"] [data-testid="stColumn"]:nth-child(3) button:hover {
                box-shadow:
                    0 10px 40px rgba(245, 158, 11, 0.3),
                    0 0 25px rgba(245, 158, 11, 0.15),
                    inset 0 1px 0 rgba(255,255,255,0.06) !important;
                border-color: rgba(245, 158, 11, 0.6) !important;
            }

            /* Card 4: Critical — Red glow */
            [data-testid="stElementContainer"]:has(.metric-cards-marker)
              + [data-testid="stElementContainer"] [data-testid="stColumn"]:nth-child(4) button {
                background: linear-gradient(160deg, #2a0a0a 0%, #450a0a 40%, #2a0a0a 100%) !important;
                border-color: rgba(239, 68, 68, 0.3) !important;
                box-shadow: 0 4px 20px rgba(239, 68, 68, 0.12), inset 0 1px 0 rgba(255,255,255,0.04) !important;
            }
            [data-testid="stElementContainer"]:has(.metric-cards-marker)
              + [data-testid="stElementContainer"] [data-testid="stColumn"]:nth-child(4) button:hover {
                box-shadow:
                    0 10px 40px rgba(239, 68, 68, 0.3),
                    0 0 25px rgba(239, 68, 68, 0.15),
                    inset 0 1px 0 rgba(255,255,255,0.06) !important;
                border-color: rgba(239, 68, 68, 0.6) !important;
            }
        </style>
        <div class="metric-cards-marker"></div>
        """, unsafe_allow_html=True)

        card_cols = st.columns(4)

        with card_cols[0]:
            st.button(
                f"📋  {total_rows}\n\nTOTAL ROWS",
                key="btn_total",
                disabled=True,
            )

        with card_cols[1]:
            if st.button(f"✅  {n_healthy}\n\nHEALTHY", key="btn_healthy", disabled=(n_healthy == 0)):
                cur = st.session_state.get("active_health_view")
                st.session_state["active_health_view"] = None if cur == "healthy" else "healthy"

        with card_cols[2]:
            if st.button(f"⚠️  {n_warning}\n\nWARNING", key="btn_warning", disabled=(n_warning == 0)):
                cur = st.session_state.get("active_health_view")
                st.session_state["active_health_view"] = None if cur == "warning" else "warning"

        with card_cols[3]:
            if st.button(f"🔴  {n_critical}\n\nCRITICAL", key="btn_critical", disabled=(n_critical == 0)):
                cur = st.session_state.get("active_health_view")
                st.session_state["active_health_view"] = None if cur == "critical" else "critical"

        # ── Detail panel grouped by check type ──
        active_view = st.session_state.get("active_health_view")

        if active_view:
            view_config = {
                "healthy":  (healthy_df,  "✅", "#10b981", "Healthy Nodes & Resources"),
                "warning":  (warning_df,  "⚠️", "#f59e0b", "Warning — Needs Attention"),
                "critical": (critical_df, "🔴", "#ef4444", "Critical — Immediate Action Required"),
            }
            target_df, icon, color, label = view_config[active_view]

            if not target_df.empty:
                st.markdown(
                    f'<div style="border-left: 4px solid {color}; padding-left: 1rem; margin: 1.5rem 0 0.5rem 0;">'
                    f'<p style="color: {color}; font-weight: 700; font-size: 1.05rem; margin: 0;">'
                    f'{icon} {label} — {len(target_df)} item(s)</p></div>',
                    unsafe_allow_html=True,
                )

                # Group by CHECK_TYPE with tabs
                check_types = sorted(target_df["CHECK_TYPE"].unique())

                # Friendly labels for check types
                check_labels = {
                    "worker_nodes": "🖥️ Worker Nodes",
                    "services": "🌐 Services",
                    "cpu_audit": "📊 CPU Audit",
                    "statefulset": "📦 StatefulSet",
                    "certificates": "🔐 Certificates",
                    "pvc": "💾 PVC",
                    "pods": "🐳 Pods",
                    "dlb_peers": "🔗 DLB Peers",
                    "ping_test": "📡 Ping Test",
                }

                if len(check_types) > 1:
                    tab_labels = [f"{check_labels.get(ct, ct)}  ({len(target_df[target_df['CHECK_TYPE'] == ct])})" for ct in check_types]
                    tabs = st.tabs(tab_labels)
                    for tab, ct in zip(tabs, check_types):
                        with tab:
                            subset = target_df[target_df["CHECK_TYPE"] == ct].reset_index(drop=True)
                            st.dataframe(subset, width="stretch", height=min(350, 40 + len(subset) * 35))
                else:
                    st.dataframe(target_df, width="stretch", height=min(400, 40 + len(target_df) * 35))

                # Context message
                if active_view == "healthy":
                    st.markdown(
                        f'<p style="color: #10b981; font-size: 0.82rem;"><b>{len(target_df)}</b> resource(s) operating normally.</p>',
                        unsafe_allow_html=True,
                    )
                elif active_view == "warning":
                    st.markdown(
                        '<p style="color: #f59e0b; font-size: 0.82rem;">'
                        '<b>Possible causes:</b> CPU/Memory above 85%, pod restarts ≥ 5, '
                        'StatefulSet replicas not fully ready, certificate not ready, DLB peer not OPEN.</p>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        '<p style="color: #ef4444; font-size: 0.82rem;">'
                        '<b>Possible causes:</b> Node NotReady, CPU/Memory above 95%, '
                        'pod CrashLoopBackOff/Error, PVC unbound, ping unreachable.</p>',
                        unsafe_allow_html=True,
                    )

        with st.expander("📝 Execution Log", expanded=False):
            for level, message in log:
                render_log_entry(message, level)

        if not df.empty:
            if "CHECK_TYPE" in classified_df.columns:
                check_types = classified_df["CHECK_TYPE"].unique()

                tabs = st.tabs(
                    ["📊 All Results"] + [f"🔍 {ct}" for ct in check_types]
                )

                with tabs[0]:
                    st.dataframe(
                        classified_df,
                        use_container_width=True,
                        height=min(400, 40 + len(classified_df) * 35),
                    )

                for i, check_type in enumerate(check_types):
                    with tabs[i + 1]:
                        filtered = classified_df[classified_df["CHECK_TYPE"] == check_type].reset_index(drop=True)
                        st.dataframe(
                            filtered,
                            use_container_width=True,
                            height=min(400, 40 + len(filtered) * 35),
                        )
            else:
                st.dataframe(classified_df, use_container_width=True)

            st.markdown("")
            csv_bytes = dataframe_to_csv_bytes(classified_df)
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

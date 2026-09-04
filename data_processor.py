import re
import pandas as pd
from typing import List, Dict, Optional
from io import StringIO

def parse_whitespace_table(
    raw_text: str,
    expected_columns: List[str],
    source_ip: str,
    command_key: str,
) -> pd.DataFrame:
    if not raw_text or not raw_text.strip():
        return pd.DataFrame()

    rows = []
    for line in raw_text.strip().splitlines():
        line = line.strip()
        if not line:
            continue

        tokens = line.split()

        if len(tokens) >= len(expected_columns):
            row = tokens[: len(expected_columns) - 1]
            row.append(" ".join(tokens[len(expected_columns) - 1 :]))
        elif len(tokens) < len(expected_columns):
            row = tokens + [""] * (len(expected_columns) - len(tokens))
        else:
            row = tokens

        rows.append(row)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=expected_columns)

    df.insert(0, "SOURCE_SERVER", source_ip)
    df["CHECK_TYPE"] = command_key

    return df


def parse_dlb_peerlist(
    raw_text: str,
    source_ip: str,
    pod_name: str,
) -> pd.DataFrame:
    if not raw_text or not raw_text.strip():
        return pd.DataFrame()

    peers = []
    current_address = None

    for line in raw_text.splitlines():
        line = line.strip()
        if line.startswith("address:"):
            current_address = line.split("address:", 1)[1].strip()
        elif line.startswith("status:"):
            status = line.split("status:", 1)[1].strip()
            if current_address:
                peers.append({"ADDRESS": current_address, "STATUS": status})
                current_address = None
        elif "status:" in line:
            match_status = re.search(r"status:\s*(\S+)", line)
            match_addr = re.search(r"(aaa://\S+)", line)
            if match_status:
                peers.append({
                    "ADDRESS": match_addr.group(1) if match_addr else "unknown",
                    "STATUS": match_status.group(1),
                })

    if not peers:
        return pd.DataFrame()

    df = pd.DataFrame(peers)
    df.insert(0, "SOURCE_SERVER", source_ip)
    df.insert(1, "POD", pod_name)
    df["CHECK_TYPE"] = "dlb_peers"

    return df


def parse_ping_result(
    raw_text: str,
    source_ip: str,
    ping_source: str,
    ping_dest: str,
) -> pd.DataFrame:
    success = "1 received" in raw_text or "1 packets received" in raw_text or ", 0% packet loss" in raw_text

    rtt_match = re.search(r"time[=<]\s*([\d.]+)\s*ms", raw_text)
    rtt_ms = rtt_match.group(1) if rtt_match else "N/A"

    result = "REACHABLE" if success else "UNREACHABLE"

    df = pd.DataFrame([{
        "SOURCE_SERVER": source_ip,
        "PING_SOURCE": ping_source,
        "PING_DEST": ping_dest,
        "RESULT": result,
        "RTT_MS": rtt_ms,
        "CHECK_TYPE": "ping_test",
    }])

    return df


def parse_raw_output(
    raw_text: str,
    source_ip: str,
    command_key: str,
) -> pd.DataFrame:
    if not raw_text or not raw_text.strip():
        return pd.DataFrame()

    lines = [line.strip() for line in raw_text.strip().splitlines() if line.strip()]

    df = pd.DataFrame({"RAW_OUTPUT": lines})
    df.insert(0, "SOURCE_SERVER", source_ip)
    df["CHECK_TYPE"] = command_key

    return df


def aggregate_dataframes(frames: List[pd.DataFrame]) -> pd.DataFrame:
    valid = [df for df in frames if df is not None and not df.empty]
    if not valid:
        return pd.DataFrame()

    return pd.concat(valid, ignore_index=True)


def dataframe_to_csv_bytes(df: pd.DataFrame) -> bytes:
    csv_string = df.to_csv(index=False)
    return ("\ufeff" + csv_string).encode("utf-8")


# ── Data-Level Health Classification ──────────────────────────────────

# Thresholds
CPU_WARN_THRESHOLD = 85       # percentage
MEMORY_WARN_THRESHOLD = 85    # percentage
RESTART_WARN_THRESHOLD = 5    # pod restart count

def _parse_percentage(value: str) -> Optional[float]:
    """Extract a numeric percentage from strings like '45%', '85%', '92m'."""
    if not value or not isinstance(value, str):
        return None
    cleaned = value.strip().rstrip("%")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _check_ready_fraction(value: str) -> str:
    """Check READY columns like '3/3', '0/3', '2/3'. Returns health status."""
    if not value or not isinstance(value, str):
        return "healthy"
    parts = value.strip().split("/")
    if len(parts) == 2:
        try:
            current, desired = int(parts[0]), int(parts[1])
            if desired == 0:
                return "warning"
            if current == desired:
                return "healthy"
            if current == 0:
                return "critical"
            return "warning"
        except ValueError:
            pass
    return "healthy"


def classify_row_health(row: pd.Series) -> str:
    """
    Classify a single data row as 'healthy', 'warning', or 'critical'
    based on the actual diagnostic values.
    """
    check_type = str(row.get("CHECK_TYPE", "")).lower()

    # ── Worker Nodes: STATUS must be 'Ready' ──
    if check_type == "worker_nodes":
        status = str(row.get("STATUS", "")).strip()
        if status.lower() != "ready":
            return "critical"
        return "healthy"

    # ── CPU Audit: CPU_% and MEMORY_% thresholds ──
    if check_type == "cpu_audit":
        cpu_pct = _parse_percentage(str(row.get("CPU_%", "")))
        mem_pct = _parse_percentage(str(row.get("MEMORY_%", "")))
        if cpu_pct is not None and cpu_pct >= CPU_WARN_THRESHOLD:
            return "warning" if cpu_pct < 95 else "critical"
        if mem_pct is not None and mem_pct >= MEMORY_WARN_THRESHOLD:
            return "warning" if mem_pct < 95 else "critical"
        return "healthy"

    # ── StatefulSet: READY column (e.g. '3/3' vs '2/3') ──
    if check_type == "statefulset":
        return _check_ready_fraction(str(row.get("READY", "")))

    # ── Certificates: READY must be 'True' ──
    if check_type == "certificates":
        ready = str(row.get("READY", "")).strip().lower()
        if ready == "true":
            return "healthy"
        return "warning"

    # ── PVC: STATUS must be 'Bound' ──
    if check_type == "pvc":
        status = str(row.get("STATUS", "")).strip().lower()
        if status == "bound":
            return "healthy"
        if status == "pending":
            return "warning"
        return "critical"

    # ── Pods: STATUS and RESTARTS ──
    if check_type == "pods":
        status = str(row.get("STATUS", "")).strip().lower()
        restarts = 0
        try:
            restarts = int(str(row.get("RESTARTS", "0")).strip())
        except ValueError:
            pass

        if status in ("running", "completed", "succeeded"):
            if restarts >= RESTART_WARN_THRESHOLD:
                return "warning"
            return "healthy"
        if status in ("pending", "init:0/1", "containercreating", "podinitialing"):
            return "warning"
        # CrashLoopBackOff, Error, ImagePullBackOff, etc.
        return "critical"

    # ── DLB Peers: STATUS should be 'OPEN' ──
    if check_type == "dlb_peers":
        status = str(row.get("STATUS", "")).strip().upper()
        if status == "OPEN":
            return "healthy"
        return "warning"

    # ── Ping Test: RESULT must be 'REACHABLE' ──
    if check_type == "ping_test":
        result = str(row.get("RESULT", "")).strip().upper()
        if result == "REACHABLE":
            return "healthy"
        return "critical"

    # ── Services: generally informational, always healthy ──
    if check_type == "services":
        return "healthy"

    return "healthy"


def classify_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add a HEALTH_STATUS column to the DataFrame by classifying each row
    based on actual diagnostic data values.
    """
    if df.empty:
        return df
    df = df.copy()
    df["HEALTH_STATUS"] = df.apply(classify_row_health, axis=1)
    return df

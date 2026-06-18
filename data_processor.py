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

#!/usr/bin/env python3
"""
data_processor.py — Text parsing engine and Pandas data normalizer.

Converts raw SSH stdout byte streams into structured DataFrames with
originating server metadata columns.  Handles whitespace-delimited
kubectl output, free-form text (DLB peers, ping), and aggregation
across multiple target servers.
"""

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
    """
    Parse whitespace-delimited kubectl output into a structured DataFrame.

    kubectl's `--no-headers` output is column-aligned with variable
    whitespace.  This parser splits each line by whitespace, maps tokens
    to the expected column names, and appends metadata columns.

    Parameters
    ----------
    raw_text : str
        The decoded UTF-8 stdout text from the remote command.
    expected_columns : list[str]
        Ordered column names to assign to parsed tokens.
    source_ip : str
        The originating target server IP (added as a metadata column).
    command_key : str
        The diagnostic command slug (added as a metadata column).

    Returns
    -------
    pd.DataFrame
        Parsed and normalized data with SOURCE_SERVER and CHECK_TYPE columns.
    """
    if not raw_text or not raw_text.strip():
        return pd.DataFrame()

    rows = []
    for line in raw_text.strip().splitlines():
        line = line.strip()
        if not line:
            continue

        # Split on whitespace — kubectl output is column-aligned
        tokens = line.split()

        if len(tokens) >= len(expected_columns):
            # If more tokens than columns, join overflow into last column
            row = tokens[: len(expected_columns) - 1]
            row.append(" ".join(tokens[len(expected_columns) - 1 :]))
        elif len(tokens) < len(expected_columns):
            # Pad short rows with empty strings
            row = tokens + [""] * (len(expected_columns) - len(tokens))
        else:
            row = tokens

        rows.append(row)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=expected_columns)

    # Append structural metadata
    df.insert(0, "SOURCE_SERVER", source_ip)
    df["CHECK_TYPE"] = command_key

    return df


def parse_dlb_peerlist(
    raw_text: str,
    source_ip: str,
    pod_name: str,
) -> pd.DataFrame:
    """
    Parse Diameter LB `client peerlist` output into structured peer data.

    The peerlist output uses a key: value format across multiple lines.
    This parser extracts address/status pairs and normalizes them.

    Parameters
    ----------
    raw_text : str
        Raw peerlist output from the DLB pod.
    source_ip : str
        The originating target server IP.
    pod_name : str
        The pod name from which the peerlist was retrieved.

    Returns
    -------
    pd.DataFrame
        Columns: SOURCE_SERVER, POD, ADDRESS, STATUS, CHECK_TYPE
    """
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
            # Inline format: address and status on same line
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
    """
    Parse ping command output into a single-row result DataFrame.

    Parameters
    ----------
    raw_text : str
        Raw ping stdout output.
    source_ip : str
        The target server that executed the ping.
    ping_source : str
        The source interface IP used for the ping.
    ping_dest : str
        The destination IP that was pinged.

    Returns
    -------
    pd.DataFrame
        Columns: SOURCE_SERVER, PING_SOURCE, PING_DEST, RESULT, RTT_MS, CHECK_TYPE
    """
    # Determine if the ping was successful
    success = "1 received" in raw_text or "1 packets received" in raw_text or ", 0% packet loss" in raw_text

    # Extract round-trip time if available
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
    """
    Fallback parser for commands that produce unstructured output.
    Stores each non-empty line as a row in a RAW_OUTPUT column.

    Parameters
    ----------
    raw_text : str
        The raw command output text.
    source_ip : str
        The originating target server IP.
    command_key : str
        The diagnostic command slug.

    Returns
    -------
    pd.DataFrame
        Columns: SOURCE_SERVER, RAW_OUTPUT, CHECK_TYPE
    """
    if not raw_text or not raw_text.strip():
        return pd.DataFrame()

    lines = [line.strip() for line in raw_text.strip().splitlines() if line.strip()]

    df = pd.DataFrame({"RAW_OUTPUT": lines})
    df.insert(0, "SOURCE_SERVER", source_ip)
    df["CHECK_TYPE"] = command_key

    return df


def aggregate_dataframes(frames: List[pd.DataFrame]) -> pd.DataFrame:
    """
    Combine multiple DataFrames from different servers and checks
    into a single unified grid.

    Parameters
    ----------
    frames : list[pd.DataFrame]
        Individual result DataFrames from each server × command pair.

    Returns
    -------
    pd.DataFrame
        A single concatenated DataFrame with reset index.
    """
    # Filter out empty frames
    valid = [df for df in frames if df is not None and not df.empty]
    if not valid:
        return pd.DataFrame()

    return pd.concat(valid, ignore_index=True)


def dataframe_to_csv_bytes(df: pd.DataFrame) -> bytes:
    """
    Serialize a DataFrame to CSV bytes suitable for download.

    Parameters
    ----------
    df : pd.DataFrame
        The data to export.

    Returns
    -------
    bytes
        UTF-8 encoded CSV content with BOM for Excel compatibility.
    """
    # Prepend UTF-8 BOM for seamless Excel opening
    csv_string = df.to_csv(index=False)
    return ("\ufeff" + csv_string).encode("utf-8")

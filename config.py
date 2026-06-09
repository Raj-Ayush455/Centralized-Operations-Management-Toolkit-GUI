#!/usr/bin/env python3
"""
config.py — Application constants, command registry, and theme configuration
for the Unified Operations Toolkit.

This module centralizes all diagnostic command definitions, UI theme tokens,
and application-wide settings to enforce a single source of truth.
"""

# ---------------------------------------------------------------------------
# Application Identity
# ---------------------------------------------------------------------------
APP_TITLE = "Unified Operations Toolkit"
APP_ICON = "🛡️"
APP_SUBTITLE = "Enterprise Kubernetes Diagnostics Dashboard"

# ---------------------------------------------------------------------------
# SSH Connection Defaults
# ---------------------------------------------------------------------------
SSH_PORT = 22
SSH_TIMEOUT = 10        # seconds
COMMAND_TIMEOUT = 60    # seconds for individual command execution

# ---------------------------------------------------------------------------
# Diagnostic Command Registry
# ---------------------------------------------------------------------------
# Each entry maps a human-readable label to:
#   - cmd        : the exact shell command string to execute via SSH
#   - key        : a short unique slug for session-state / dataframe tagging
#   - requires   : optional list of extra parameters the UI must collect
#                   (e.g., pod name, source IP, destination IP)
#   - columns    : expected column headers for parsing the whitespace-
#                   delimited stdout output into a DataFrame
#
# Commands requiring dynamic substitution use Python str.format() placeholders.
# ---------------------------------------------------------------------------

DIAGNOSTIC_COMMANDS = [
    {
        "label": "Worker Node Status Check",
        "cmd": "kubectl get nodes --no-headers",
        "key": "worker_nodes",
        "requires": [],
        "columns": ["NAME", "STATUS", "ROLES", "AGE", "VERSION"],
    },
    {
        "label": "CPU Capacity Audit",
        "cmd": "kubectl top nodes -l eric-bss-app=caf --no-headers",
        "key": "cpu_audit",
        "requires": [],
        "columns": ["NAME", "CPU_CORES", "CPU_%", "MEMORY_BYTES", "MEMORY_%"],
    },
    {
        "label": "StatefulSet Health Check",
        "cmd": "kubectl get statefulset --no-headers",
        "key": "statefulset",
        "requires": [],
        "columns": ["NAME", "READY", "AGE"],
    },
    {
        "label": "Certificate Readiness Check",
        "cmd": "kubectl get certificate --no-headers",
        "key": "certificates",
        "requires": [],
        "columns": ["NAME", "READY", "SECRET", "AGE"],
    },
    {
        "label": "PVC Binding Health Check",
        "cmd": "kubectl get pvc --no-headers",
        "key": "pvc",
        "requires": [],
        "columns": ["NAME", "STATUS", "VOLUME", "CAPACITY", "ACCESS_MODES", "STORAGECLASS", "AGE"],
    },
    {
        "label": "Pod Readiness Check",
        "cmd": "kubectl get pods -o wide --no-headers",
        "key": "pods",
        "requires": [],
        "columns": ["NAME", "READY", "STATUS", "RESTARTS", "AGE", "IP", "NODE", "NOMINATED_NODE", "READINESS_GATES"],
    },
    {
        "label": "Diameter LB Peer Check",
        "cmd": "kubectl exec -it {pod_name} -- client peerlist",
        "key": "dlb_peers",
        "requires": ["pod_name"],
        "columns": ["RAW_OUTPUT"],
    },
    {
        "label": "Source Interface Ping Test",
        "cmd": "ping -c 1 -W 1 -I {source_ip} {dest_ip}",
        "key": "ping_test",
        "requires": ["source_ip", "dest_ip"],
        "columns": ["RAW_OUTPUT"],
    },
]

# ---------------------------------------------------------------------------
# UI Theme Tokens (used by custom CSS injection)
# ---------------------------------------------------------------------------
THEME = {
    "bg_primary":       "#0a0e17",
    "bg_secondary":     "#111827",
    "bg_card":          "#1a2236",
    "bg_card_hover":    "#1e2a42",
    "accent_primary":   "#6366f1",
    "accent_secondary": "#818cf8",
    "accent_glow":      "rgba(99, 102, 241, 0.25)",
    "success":          "#10b981",
    "warning":          "#f59e0b",
    "error":            "#ef4444",
    "text_primary":     "#f1f5f9",
    "text_secondary":   "#94a3b8",
    "text_muted":       "#64748b",
    "border":           "rgba(99, 102, 241, 0.15)",
    "border_hover":     "rgba(99, 102, 241, 0.40)",
    "font_family":      "'Inter', 'Segoe UI', -apple-system, sans-serif",
}

APP_TITLE = "Automation in Intelligent Network System"
APP_ICON = "🛡️"
APP_SUBTITLE = "Enterprise Kubernetes Diagnostics Dashboard"

SSH_PORT = 22
SSH_TIMEOUT = 10
COMMAND_TIMEOUT = 60

DIAGNOSTIC_COMMANDS = [
    {
        "label": "Worker Node Status Check",
        "cmd": "kubectl get nodes --no-headers",
        "key": "worker_nodes",
        "requires": [],
        "columns": ["NAME", "STATUS", "ROLES", "AGE", "VERSION"],
    },
   {
      "label": "Service Status Check",
      "cmd": "kubectl get svc -n {namespace} --no-headers",
      "key": "services",
      "requires": [],
      "columns": ["NAME", "TYPE", "CLUSTER_IP", "EXTERNAL_IP", "PORTS", "AGE"],
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
        "cmd": "kubectl get statefulset -n {namespace} --no-headers",
        "key": "statefulset",
        "requires": [],
        "columns": ["NAME", "READY", "AGE"],
    },
    {
        "label": "Certificate Readiness Check",
        "cmd": "kubectl get certificate -n {namespace} --no-headers",
        "key": "certificates",
        "requires": [],
        "columns": ["NAME", "READY", "SECRET", "AGE"],
    },
    {
        "label": "PVC Binding Health Check",
        "cmd": "kubectl get pvc -n {namespace} --no-headers",
        "key": "pvc",
        "requires": [],
        "columns": ["NAME", "STATUS", "VOLUME", "CAPACITY", "ACCESS_MODES", "STORAGECLASS", "AGE"],
    },
    {
        "label": "Pod Readiness Check",
        "cmd": "kubectl get pods -n {namespace} -o wide --no-headers | head -50",
        "key": "pods",
        "requires": [],
        "columns": ["NAME", "READY", "STATUS", "RESTARTS", "AGE", "IP", "NODE", "NOMINATED_NODE", "READINESS_GATES"],
    },
    {
        "label": "Diameter LB Peer Check",
        "cmd": "kubectl exec -it -n {namespace} {pod_name} -- client peerlist",
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

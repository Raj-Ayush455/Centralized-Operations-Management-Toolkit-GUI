#!/usr/bin/env python3
"""
ssh_handler.py — Secure SSH connection manager using Paramiko.

Implements a zero-retention, in-memory-only credential model.
All connections are ephemeral: opened, used, and torn down within a
single diagnostic run.  No credentials are ever written to disk,
cached, or logged.
"""

import paramiko
import logging
from typing import Tuple, Optional

from config import SSH_PORT, SSH_TIMEOUT, COMMAND_TIMEOUT

# ---------------------------------------------------------------------------
# Suppress Paramiko's verbose transport-layer logging to prevent any
# accidental credential leakage into log streams.
# ---------------------------------------------------------------------------
logging.getLogger("paramiko").setLevel(logging.WARNING)


class SSHConnectionError(Exception):
    """Raised when an SSH connection or command execution fails."""

    def __init__(self, host: str, message: str, error_type: str = "CONNECTION_ERROR"):
        self.host = host
        self.message = message
        self.error_type = error_type
        super().__init__(f"[{error_type}] {host}: {message}")


def create_ssh_client(
    hostname: str,
    username: str,
    password: str,
    port: int = SSH_PORT,
    timeout: int = SSH_TIMEOUT,
) -> paramiko.SSHClient:
    """
    Initialize an independent encrypted SSH channel to a target server.

    Parameters
    ----------
    hostname : str
        Target server IP or FQDN.
    username : str
        SSH login username (held in-memory only).
    password : str
        SSH login password (held in-memory only — never written to disk).
    port : int
        SSH port (default 22).
    timeout : int
        Connection timeout in seconds.

    Returns
    -------
    paramiko.SSHClient
        An authenticated, ready-to-use SSH client.

    Raises
    ------
    SSHConnectionError
        With a descriptive error_type indicating the failure class:
        - AUTHENTICATION_FAILED
        - HOST_UNREACHABLE
        - CONNECTION_TIMEOUT
        - CONNECTION_ERROR
    """
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        ssh.connect(
            hostname=hostname,
            port=port,
            username=username,
            password=password,
            timeout=timeout,
            allow_agent=False,       # Disable SSH agent forwarding
            look_for_keys=False,     # Do not scan ~/.ssh for key files
        )
        return ssh

    except paramiko.AuthenticationException:
        raise SSHConnectionError(
            hostname,
            "Authentication failed — invalid username or password.",
            "AUTHENTICATION_FAILED",
        )
    except paramiko.ssh_exception.NoValidConnectionsError:
        raise SSHConnectionError(
            hostname,
            f"Host unreachable — no valid connection on port {port}.",
            "HOST_UNREACHABLE",
        )
    except TimeoutError:
        raise SSHConnectionError(
            hostname,
            f"Connection timed out after {timeout}s.",
            "CONNECTION_TIMEOUT",
        )
    except OSError as exc:
        raise SSHConnectionError(
            hostname,
            f"Network error — {exc}",
            "HOST_UNREACHABLE",
        )
    except Exception as exc:
        raise SSHConnectionError(
            hostname,
            f"Unexpected error — {exc}",
            "CONNECTION_ERROR",
        )


def execute_remote_command(
    ssh_client: paramiko.SSHClient,
    command: str,
    hostname: str,
    timeout: int = COMMAND_TIMEOUT,
) -> Tuple[str, str]:
    """
    Execute a single command over an open SSH channel and capture output.

    Parameters
    ----------
    ssh_client : paramiko.SSHClient
        An already-authenticated SSH client.
    command : str
        The shell command to execute on the remote host.
    hostname : str
        The originating hostname (used for error context only).
    timeout : int
        Maximum seconds to wait for command completion.

    Returns
    -------
    tuple[str, str]
        (stdout_text, stderr_text) — both decoded to UTF-8 with
        leading/trailing whitespace stripped.

    Raises
    ------
    SSHConnectionError
        If the command execution fails or times out.
    """
    try:
        stdin, stdout, stderr = ssh_client.exec_command(command, timeout=timeout)

        # Read and decode output streams
        stdout_text = stdout.read().decode("utf-8", errors="replace").strip()
        stderr_text = stderr.read().decode("utf-8", errors="replace").strip()

        return stdout_text, stderr_text

    except TimeoutError:
        raise SSHConnectionError(
            hostname,
            f"Command timed out after {timeout}s: {command}",
            "COMMAND_TIMEOUT",
        )
    except Exception as exc:
        raise SSHConnectionError(
            hostname,
            f"Command execution failed — {exc}",
            "COMMAND_EXECUTION_ERROR",
        )


def close_ssh_client(ssh_client: Optional[paramiko.SSHClient]) -> None:
    """
    Safely tear down an SSH connection.
    Silently ignores None or already-closed clients.
    """
    if ssh_client is not None:
        try:
            ssh_client.close()
        except Exception:
            pass  # Connection may already be dead — nothing to clean up

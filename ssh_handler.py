import paramiko
import logging
from typing import Tuple, Optional

from config import SSH_PORT, SSH_TIMEOUT, COMMAND_TIMEOUT

logging.getLogger("paramiko").setLevel(logging.WARNING)


class SSHConnectionError(Exception):

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
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        ssh.connect(
            hostname=hostname,
            port=port,
            username=username,
            password=password,
            timeout=timeout,
            allow_agent=False,
            look_for_keys=False,
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
    try:
        stdin, stdout, stderr = ssh_client.exec_command(command, timeout=timeout)

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
    if ssh_client is not None:
        try:
            ssh_client.close()
        except Exception:
            pass

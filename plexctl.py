#!/usr/bin/env python3

import argparse
import json
import os
import shutil
import subprocess
import sys
import textwrap
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, NoReturn, cast


DEFAULT_BASE_URL = "http://127.0.0.1:32400"
DEFAULT_CONTAINER = "plex"
HTTP_TIMEOUT_SECONDS = 10


def _eprint(message: str) -> None:
    print(message, file=sys.stderr)


def die(message: str, exit_code: int = 1) -> NoReturn:
    _eprint(f"Error: {message}")
    raise SystemExit(exit_code)


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and ((value[0] == value[-1] == '"') or (value[0] == value[-1] == "'")):
        return value[1:-1]
    return value


def load_dotenv_if_present(dotenv_path: Path) -> None:
    """Loads KEY=VALUE pairs into os.environ if the key is not already set.

    This is a minimal .env loader (no dependencies).
    """

    if not dotenv_path.exists() or not dotenv_path.is_file():
        return

    try:
        content = dotenv_path.read_text(encoding="utf-8")
    except OSError as exc:
        die(f"Failed to read .env file: {dotenv_path} ({exc})")

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = _strip_quotes(value)
        if not key:
            continue
        if key not in os.environ:
            os.environ[key] = value


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        die(
            f"Missing required environment variable {name}. "
            f"Create a .env file (see .env.example) or export it in your shell."
        )
    return value


def get_env(name: str, default: str) -> str:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value


def mask_token_in_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    masked: list[tuple[str, str]] = []
    for k, v in query:
        if k == "X-Plex-Token":
            masked.append((k, "****"))
        else:
            masked.append((k, v))
    new_query = urllib.parse.urlencode(masked, doseq=True)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, new_query, parsed.fragment))


def build_plex_url(base_url: str, path: str, params: dict[str, str]) -> str:
    base = base_url.rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    query = urllib.parse.urlencode(params)
    return f"{base}{path}?{query}" if query else f"{base}{path}"


def http_get(url: str) -> tuple[int, bytes]:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            status = int(getattr(resp, "status", 200))
            return status, resp.read()
    except urllib.error.HTTPError as exc:
        body = exc.read() if hasattr(exc, "read") else b""
        return int(exc.code), body
    except urllib.error.URLError as exc:
        die(f"Plex is not reachable at {url.split('?', 1)[0]} ({exc})")


def parse_sections_xml(xml_bytes: bytes) -> list[dict[str, Any]]:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        die(f"Failed to parse Plex response XML ({exc})")

    sections: list[dict[str, Any]] = []
    for directory in root.findall("Directory"):
        key = directory.attrib.get("key")
        title = directory.attrib.get("title")
        section_type = directory.attrib.get("type")
        if key is None:
            continue
        sections.append({"id": key, "title": title or "", "type": section_type or ""})
    return sections


def cmd_sections(args: argparse.Namespace) -> int:
    base_url = get_env("PLEX_BASE_URL", DEFAULT_BASE_URL)
    token = require_env("PLEX_TOKEN")

    url = build_plex_url(base_url, "/library/sections", {"X-Plex-Token": token})
    status, body = http_get(url)

    if status < 200 or status >= 300:
        safe_url = mask_token_in_url(url)
        die(f"Plex returned HTTP {status} for {safe_url}")

    sections = parse_sections_xml(body)

    if args.json:
        print(json.dumps(sections, indent=2, sort_keys=False))
        return 0

    if not sections:
        print("No sections found.")
        return 0

    id_width = max(len(str(s["id"])) for s in sections)
    type_width = max(len(str(s["type"])) for s in sections)

    print(f"{'ID'.ljust(id_width)}  {'TYPE'.ljust(type_width)}  TITLE")
    print(f"{'-' * id_width}  {'-' * type_width}  {'-' * 5}")
    for s in sections:
        print(f"{str(s['id']).ljust(id_width)}  {str(s['type']).ljust(type_width)}  {s['title']}")

    return 0


def cmd_refresh(args: argparse.Namespace) -> int:
    base_url = get_env("PLEX_BASE_URL", DEFAULT_BASE_URL)
    token = require_env("PLEX_TOKEN")

    params: dict[str, str] = {"X-Plex-Token": token}
    if args.force:
        params["force"] = "1"
    if args.path is not None:
        if args.path.strip() == "":
            die("--path was provided but empty")
        if not args.path.startswith("/"):
            die("--path must be an absolute path (start with '/'): " + args.path)
        params["path"] = args.path

    section_id = args.section
    url = build_plex_url(base_url, f"/library/sections/{section_id}/refresh", params)

    status, _body = http_get(url)
    safe_url = mask_token_in_url(url)

    if status < 200 or status >= 300:
        die(f"Refresh failed (HTTP {status})\nURL: {safe_url}")

    print(f"Refresh triggered successfully (HTTP {status})")
    print(f"URL: {safe_url}")
    return 0


def _require_docker() -> str:
    docker_path = shutil.which("docker")
    if not docker_path:
        die("docker CLI not found in PATH")
    return cast(str, docker_path)


def _docker_container_exists(container: str) -> bool:
    _require_docker()
    proc = subprocess.run(
        ["docker", "inspect", container],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return proc.returncode == 0


def _run_docker_command(cmd: list[str]) -> int:
    _require_docker()
    proc = subprocess.run(cmd, check=False)
    return int(proc.returncode)


def cmd_logs(args: argparse.Namespace) -> int:
    container = get_env("PLEX_CONTAINER", DEFAULT_CONTAINER)
    if not _docker_container_exists(container):
        die(f"Docker container '{container}' not found")

    n = int(args.n)
    if n <= 0:
        die("-n must be a positive integer")

    return _run_docker_command(["docker", "logs", "-n", str(n), container])


def cmd_restart(args: argparse.Namespace) -> int:
    container = get_env("PLEX_CONTAINER", DEFAULT_CONTAINER)
    if not _docker_container_exists(container):
        die(f"Docker container '{container}' not found")

    return _run_docker_command(["docker", "restart", container])


def cmd_scanner(args: argparse.Namespace) -> int:
    if not args.list:
        die("Missing --list")

    container = get_env("PLEX_CONTAINER", DEFAULT_CONTAINER)
    if not _docker_container_exists(container):
        die(f"Docker container '{container}' not found")

    scanner_path = "/usr/lib/plexmediaserver/Plex Media Scanner"

    # Use argv-list form so spaces in the binary path are handled correctly.
    cmd = ["docker", "exec", "-i", container, scanner_path, "--list"]
    rc = _run_docker_command(cmd)
    if rc != 0:
        _eprint(
            textwrap.dedent(
                f"""\
                Scanner command failed (exit code {rc}).
                Tried: docker exec -i {container} {scanner_path!r} --list

                Notes:
                - Some Plex images use a different scanner path.
                - Ensure the container is running and includes Plex Media Scanner.
                """
            ).rstrip()
        )
    return rc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="plexctl",
        description="Small local CLI to control Plex (Plex Media Server URL Commands + docker).",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    p_sections = sub.add_parser("sections", help="List Plex libraries (sections)")
    p_sections.add_argument("--json", action="store_true", help="Output JSON")
    p_sections.set_defaults(func=cmd_sections)

    p_refresh = sub.add_parser("refresh", help="Refresh a Plex section")
    p_refresh.add_argument("--section", required=True, help="Section id")
    p_refresh.add_argument("--force", action="store_true", help="Force refresh (force=1)")
    p_refresh.add_argument("--path", help="Absolute folder path to refresh (path=...)")
    p_refresh.set_defaults(func=cmd_refresh)

    p_logs = sub.add_parser("logs", help="Show Plex container logs")
    p_logs.add_argument("-n", default=200, help="Number of log lines (default: 200)")
    p_logs.set_defaults(func=cmd_logs)

    p_restart = sub.add_parser("restart", help="Restart Plex container")
    p_restart.set_defaults(func=cmd_restart)

    p_scanner = sub.add_parser("scanner", help="Run Plex Media Scanner in the container")
    p_scanner.add_argument("--list", action="store_true", help="List scanner sections")
    p_scanner.set_defaults(func=cmd_scanner)

    return parser


def main(argv: list[str]) -> int:
    script_dir = Path(__file__).resolve().parent
    load_dotenv_if_present(script_dir / ".env")

    parser = build_parser()
    args = parser.parse_args(argv)

    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 2

    return int(func(args))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

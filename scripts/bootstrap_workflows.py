#!/usr/bin/env python3
"""Create workflows and complete all workflow steps via API.

Usage:
  python scripts/bootstrap_workflows.py \
    --access-token "<token>" \
    --company-id "<uuid>"

Optional:
  --base-url http://localhost:8000
  --data-file postman/workflow_test_data.json
  --include CAC/NEW,FIRS/RENEWAL
  --exclude BPP_FEDERAL,BPP_STATE
  --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib import error, request


def _parse_csv(value: str | None) -> set[str]:
    if not value:
        return set()
    return {item.strip() for item in value.split(",") if item.strip()}


def _load_workflows(data_file: Path) -> list[dict[str, Any]]:
    payload = json.loads(data_file.read_text(encoding="utf-8"))
    return payload.get("workflows", [])


def _workflow_key(workflow: dict[str, Any]) -> str:
    return f"{workflow['compliance_type']}/{workflow['mode']}"


def _workflow_id_key(workflow: dict[str, Any]) -> str:
    return str(workflow["id"])


def _is_selected(workflow: dict[str, Any], include: set[str], exclude: set[str]) -> bool:
    key = _workflow_key(workflow)
    workflow_id = _workflow_id_key(workflow)
    if include and key not in include and workflow_id not in include:
        return False
    if key in exclude or workflow_id in exclude or workflow["compliance_type"] in exclude:
        return False
    return True


def _request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> None:
    if dry_run:
        if json_body is None:
            print(f"[DRY-RUN] {method} {url}")
        else:
            print(f"[DRY-RUN] {method} {url} body={json.dumps(json_body)}")
        return

    data = None
    req_headers = dict(headers or {})
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        req_headers["Content-Type"] = "application/json"

    req = request.Request(url=url, method=method, data=data, headers=req_headers)
    try:
        with request.urlopen(req, timeout=30) as resp:
            status = resp.getcode()
            if status >= 400:
                body = resp.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"{method} {url} failed: {status} {body}")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed: {exc.code} {body}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"{method} {url} failed: {exc.reason}") from exc
    print(f"[OK] {method} {url}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create workflows and add completed workflow steps for a company."
    )
    parser.add_argument("--access-token", required=True, help="Bearer token value")
    parser.add_argument("--company-id", required=True, help="Target company UUID")
    parser.add_argument("--base-url", default="http://localhost:8000", help="API base URL")
    parser.add_argument(
        "--data-file",
        default="postman/workflow_test_data.json",
        help="Path to workflow_test_data.json",
    )
    parser.add_argument(
        "--include",
        default=None,
        help="Comma-separated workflow ids or keys (e.g. firs_renewal,CAC/NEW)",
    )
    parser.add_argument(
        "--exclude",
        default="BPP_FEDERAL,BPP_STATE",
        help="Comma-separated workflow ids/keys/types to skip",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print calls without sending requests",
    )
    args = parser.parse_args()

    data_file = Path(args.data_file).resolve()
    if not data_file.exists():
        print(f"Data file not found: {data_file}", file=sys.stderr)
        sys.exit(1)

    include = _parse_csv(args.include)
    exclude = _parse_csv(args.exclude)
    workflows = _load_workflows(data_file)
    selected = [w for w in workflows if _is_selected(w, include, exclude)]

    if not selected:
        print("No workflows selected. Check --include/--exclude filters.", file=sys.stderr)
        sys.exit(1)

    base_url = args.base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {args.access_token}"}

    print(f"Selected workflows: {len(selected)}")
    for wf in selected:
        print(f" - {_workflow_id_key(wf)} ({_workflow_key(wf)})")

    for wf in selected:
        compliance_type = wf["compliance_type"]
        mode = wf["mode"]
        key = _workflow_key(wf)
        print(f"\n== {key} ==")

        start_url = (
            f"{base_url}/api/v1/workflow/{compliance_type}/{mode}/companies/"
            f"{args.company_id}/start"
        )
        _request("POST", start_url, headers=headers, dry_run=args.dry_run)

        steps = wf.get("steps", [])
        for step in sorted(steps, key=lambda s: int(s["step_number"])):
            step_number = int(step["step_number"])
            step_name = str(step["step_name"])
            step_url = (
                f"{base_url}/api/v1/workflow/{compliance_type}/{mode}/companies/"
                f"{args.company_id}/steps/{step_number}/complete"
            )
            _request(
                "POST",
                step_url,
                headers=headers,
                json_body={"step_name": step_name},
                dry_run=args.dry_run,
            )

    print("\nDone. Workflows and step progress are created/updated.")
    print("Note: this script does not upload documents or submit workflows.")


if __name__ == "__main__":
    main()

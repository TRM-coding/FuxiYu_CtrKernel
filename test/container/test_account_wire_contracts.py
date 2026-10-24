"""Ctrl → Node account wire contract tests.

These tests use the real Ctrl request models and the real Ctrl wire helpers.
The Node side is loaded in a subprocess from the current worktree, using its
real FastAPI bare router + TestClient and real Pydantic wire models.  Only the
Docker/container execution functions are replaced; the schemas and route
validation are not mocked.

Run under the offline WSL venv, from the repo parent:

    /home/chest/.cache/fuxi-password-tests-offline/bin/python -m pytest \
        test/container/test_account_wire_contracts.py
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ...constant import ROLE
from ...schemas.container import CollaboratorRequest, UpdateRoleRequest
from ...services.container_module import collaborators as collaborator_utils
from ...services.container_module import creation
from ...services.container_module import passwords

REPO_ROOT = Path(__file__).resolve().parents[2]
FUXI_ROOT = REPO_ROOT.parent
NODE_ROOT = FUXI_ROOT / "FuxiYu_NodeKernel"


NODE_PROBE = r'''
import json
import os
import sys

sys.path.insert(0, os.getcwd())

from fastapi import FastAPI
from fastapi.testclient import TestClient
from FuxiYu_NodeKernel.network import api
from FuxiYu_NodeKernel.schemas.container import (
    AddCollaboratorMessage,
    CreateContainerMessage,
    ResetContainerPasswordMessage,
    UpdateRoleMessage,
)

# Only the Docker/container execution layer is mocked.  Route validation,
# SecretStr handling, response models and no-store behavior stay real.
api.add_collaborator = lambda *args, **kwargs: True
api.update_role = lambda *args, **kwargs: True
api.reset_container_password = lambda *args, **kwargs: True

app = FastAPI()
app.include_router(api.router)
client = TestClient(app)

MODELS = {
    "AddCollaboratorMessage": AddCollaboratorMessage,
    "CreateContainerMessage": CreateContainerMessage,
    "ResetContainerPasswordMessage": ResetContainerPasswordMessage,
    "UpdateRoleMessage": UpdateRoleMessage,
}


def _response(resp):
    return {
        "status": resp.status_code,
        "body": resp.json(),
        "cache_control": resp.headers.get("cache-control"),
    }


out = []
for case in json.load(sys.stdin):
    kind = case["kind"]
    if kind == "add":
        out.append(_response(client.post("/api/add_collaborator", json=case["payload"])))
    elif kind == "update":
        out.append(_response(client.post("/api/update_role", json=case["payload"])))
    elif kind == "reset":
        out.append(_response(client.post("/api/reset_container_password", json=case["payload"])))
    elif kind == "model":
        try:
            model = MODELS[case["model"]].model_validate(case["payload"])
            out.append({"ok": True, "dump": model.model_dump(mode="json")})
        except Exception as exc:
            errors = (
                exc.errors(include_input=False, include_url=False)
                if hasattr(exc, "errors")
                else [str(exc)]
            )
            out.append({"ok": False, "errors": errors})
    else:
        raise AssertionError(f"unknown probe kind: {kind}")
print(json.dumps(out))
'''


@pytest.fixture(scope="session")
def node_contract():
    """Run real Node schema/router checks in a separate interpreter."""

    if not NODE_ROOT.is_dir():
        pytest.skip("FuxiYu_NodeKernel is not available")

    def run(cases: list[dict]) -> list[dict]:
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(
            [str(FUXI_ROOT), env.get("PYTHONPATH", "")]
        ).rstrip(os.pathsep)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env.pop("DATABASE_URL", None)
        proc = subprocess.run(
            [sys.executable, "-c", NODE_PROBE],
            cwd=str(FUXI_ROOT),
            env=env,
            input=json.dumps(cases),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if proc.returncode != 0:
            pytest.fail(
                "real Node bare-router probe failed:\n"
                f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
            )
        return json.loads(proc.stdout)

    return run


def _assert_no_secret_in_wire_json(value: object, secret: str) -> None:
    rendered = json.dumps(value, ensure_ascii=False)
    assert secret not in rendered


@pytest.mark.parametrize("web_role", [None, "ADMIN", "COLLABORATOR"])
def test_ctrl_collaborator_wire_uppercase_request_is_normalized_for_node(
    node_contract, web_role,
):
    request_body = {"container_id": 1, "user_id": 2}
    if web_role is not None:
        request_body["role"] = web_role
    request = CollaboratorRequest.model_validate(request_body)
    expected_web_role = web_role or "COLLABORATOR"
    assert request.role == expected_web_role

    password = "AddPwd_123456"
    wire = collaborator_utils._build_collaborator_payload(
        "wire_add_container",
        "wire_add_user",
        role=ROLE(request.role),
        password=password,
    )
    assert wire["config"]["role"] == expected_web_role.lower()
    assert wire["config"]["password"] == password

    raw_uppercase = {
        "config": {
            "container_name": "wire_add_container",
            "user_name": "wire_add_user",
            "role": expected_web_role,
            "password": password,
        }
    }
    results = node_contract(
        [
            {"kind": "add", "payload": raw_uppercase},
            {"kind": "add", "payload": wire},
        ]
    )
    rejected, accepted = results
    assert rejected["status"] == 422
    assert rejected["body"]["error_reason"] == "invalid_request"
    _assert_no_secret_in_wire_json(rejected["body"], password)

    assert accepted["status"] == 200
    assert accepted["body"]["success"] is True
    assert accepted["cache_control"] == "no-store"


@pytest.mark.parametrize(
    ("web_role", "root_password", "admin_password"),
    [
        ("ROOT", "RootPwd_123456", None),
        ("ADMIN", None, "AdminPwd_123456"),
        ("COLLABORATOR", None, None),
    ],
)
def test_ctrl_update_role_wire_uppercase_request_is_normalized_for_node(
    node_contract, web_role, root_password, admin_password,
):
    request = UpdateRoleRequest.model_validate(
        {
            "container_id": 1,
            "user_id": 2,
            "updated_role": web_role,
            "transfer_root": web_role == "ROOT",
        }
    )
    assert request.updated_role == web_role
    assert request.transfer_root is (web_role == "ROOT")

    wire = collaborator_utils._role_payload(
        "wire_role_container",
        "wire_role_user",
        ROLE(request.updated_role),
        password=admin_password,
        root_password=root_password,
    )
    assert wire["config"]["updated_role"] == web_role.lower()
    assert "transfer_root" not in wire["config"]
    if web_role == "ROOT":
        assert "root_password" in wire["config"]
        assert "password" not in wire["config"]
    elif web_role == "ADMIN":
        assert "password" in wire["config"]
        assert "root_password" not in wire["config"]
    else:
        assert "password" not in wire["config"]
        assert "root_password" not in wire["config"]

    raw_uppercase = copy.deepcopy(wire)
    raw_uppercase["config"]["updated_role"] = web_role
    results = node_contract(
        [
            {"kind": "update", "payload": raw_uppercase},
            {"kind": "update", "payload": wire},
        ]
    )
    rejected, accepted = results
    assert rejected["status"] == 422
    assert rejected["body"]["error_reason"] == "invalid_request"
    for secret in (root_password, admin_password):
        if secret:
            _assert_no_secret_in_wire_json(rejected["body"], secret)

    assert accepted["status"] == 200
    assert accepted["body"]["success"] is True
    assert accepted["cache_control"] == "no-store"


def test_ctrl_transfer_root_never_enters_node_wire(node_contract):
    request = UpdateRoleRequest.model_validate(
        {
            "container_id": 1,
            "user_id": 2,
            "updated_role": "ROOT",
            "transfer_root": True,
        }
    )
    wire = collaborator_utils._role_payload(
        "wire_transfer_container",
        "wire_transfer_user",
        ROLE(request.updated_role),
        root_password="RootPwd_123456",
    )
    assert "transfer_root" not in json.dumps(wire)
    result = node_contract([{"kind": "update", "payload": wire}])[0]
    assert result["status"] == 200
    assert result["body"]["success"] is True


@pytest.mark.parametrize("restore_role", ["COLLABORATOR", "ADMIN"])
def test_ctrl_restore_accounts_wire_uses_real_node_restore_schema(
    node_contract, container_info, restore_role,
):
    accounts = [
        {
            "user_id": 7,
            "system_username": f"wire_restore_{restore_role.lower()}",
            "container_username": f"wire_restore_{restore_role.lower()}",
            "role": restore_role,
            "public_key": "ssh-rsa AAAATEST",
        }
    ]
    original = copy.deepcopy(accounts)
    prepared = creation._with_transient_restore_passwords(accounts)
    assert accounts == original  # transient password is not written back
    assert prepared[0]["password"]

    wire = creation._build_create_payload(
        container_info,
        "wire_restore_owner",
        root_password="RootPwd_123456",
        restore_accounts=prepared,
    )
    assert wire["root_password"] == "RootPwd_123456"
    assert "root_password" not in wire["config"]
    assert wire["restore_accounts"][0]["role"] == restore_role.lower()
    assert wire["restore_accounts"][0]["password"] == prepared[0]["password"]

    valid = node_contract(
        [{"kind": "model", "model": "CreateContainerMessage", "payload": wire}]
    )[0]
    assert valid["ok"] is True

    bad = copy.deepcopy(wire)
    bad["restore_accounts"][0]["role"] = restore_role
    rejected = node_contract(
        [{"kind": "model", "model": "CreateContainerMessage", "payload": bad}]
    )[0]
    assert rejected["ok"] is False
    _assert_no_secret_in_wire_json(
        rejected["errors"], prepared[0]["password"]
    )

    missing_root_password = copy.deepcopy(wire)
    missing_root_password.pop("root_password")
    missing = node_contract(
        [
            {
                "kind": "model",
                "model": "CreateContainerMessage",
                "payload": missing_root_password,
            }
        ]
    )[0]
    assert missing["ok"] is False


def test_node_password_models_mask_secret_values(node_contract):
    secret = "MaskPwd_123456"
    cases = [
        {
            "kind": "model",
            "model": "AddCollaboratorMessage",
            "payload": {
                "config": {
                    "container_name": "wire_mask",
                    "user_name": "wire_mask_user",
                    "role": "collaborator",
                    "password": secret,
                }
            },
        },
        {
            "kind": "model",
            "model": "ResetContainerPasswordMessage",
            "payload": {
                "config": {
                    "container_name": "wire_mask",
                    "user_name": "wire_mask_user",
                    "password": secret,
                }
            },
        },
        {
            "kind": "model",
            "model": "UpdateRoleMessage",
            "payload": {
                "config": {
                    "container_name": "wire_mask",
                    "user_name": "wire_mask_user",
                    "updated_role": "root",
                    "root_password": secret,
                }
            },
        },
        {
            "kind": "model",
            "model": "UpdateRoleMessage",
            "payload": {
                "config": {
                    "container_name": "wire_mask",
                    "user_name": "wire_mask_user",
                    "updated_role": "admin",
                    "password": secret,
                }
            },
        },
        {
            "kind": "model",
            "model": "CreateContainerMessage",
            "payload": {
                "owner_name": "wire_mask_owner",
                "config": {
                    "gpu_list": [],
                    "cpu_number": 1,
                    "memory": 1,
                    "shared_memory": 0,
                    "name": "wire_mask",
                    "port": 0,
                    "image": "ubuntu:22.04",
                },
                "root_password": secret,
                "restore_accounts": [
                    {
                        "user_name": "wire_mask_user",
                        "role": "collaborator",
                        "password": secret,
                    }
                ],
            },
        },
    ]
    results = node_contract(cases)
    assert len(results) == len(cases)
    for result in results:
        assert result["ok"] is True
        rendered = json.dumps(result["dump"], ensure_ascii=False)
        assert secret not in rendered
        assert "**********" in rendered


def test_ctrl_reset_wire_uses_real_node_reset_schema(node_contract, monkeypatch):
    sent = []

    def _capture(url, payload, timeout=5.0):
        sent.append({"url": url, "payload": payload, "timeout": timeout})
        return {"success": 1}

    monkeypatch.setattr(passwords.node_comms, "send", _capture)
    password = "ResetPwd_123456"
    passwords._request_node_reset(
        "wire_host", 1234, "wire_reset_container", "wire_reset_user", password,
    )
    assert len(sent) == 1
    wire = sent[0]["payload"]
    assert wire["config"]["container_name"] == "wire_reset_container"
    assert wire["config"]["user_name"] == "wire_reset_user"
    assert wire["config"]["password"] == password

    invalid = {
        "config": {
            "container_name": "wire_reset_container",
            "user_name": "wire_reset_user",
        }
    }
    results = node_contract(
        [
            {"kind": "reset", "payload": wire},
            {"kind": "reset", "payload": invalid},
        ]
    )
    accepted, rejected = results
    assert accepted["status"] == 200
    assert accepted["body"]["success"] == 1
    assert rejected["status"] == 422
    _assert_no_secret_in_wire_json(rejected["body"], password)


def _auth(monkeypatch, user_id: int = 1) -> None:
    from ...api import deps
    from ...api import container_api

    monkeypatch.setattr(
        deps.authentications_repo, "is_token_valid",
        lambda token, **kwargs: True,
    )
    monkeypatch.setattr(
        deps.authentications_repo, "get_user_id_by_token",
        lambda token, **kwargs: user_id,
    )
    monkeypatch.setattr(
        "FuxiYu_CtrKernel.services.rbac_service.user_has_entity",
        lambda uid, code: True,
    )
    monkeypatch.setattr(
        "FuxiYu_CtrKernel.services.rbac_service.user_has_resource",
        lambda uid, rtype, rid: True,
    )
    monkeypatch.setattr(
        "FuxiYu_CtrKernel.repositories.containers_repo.get_machine_id_by_container_id",
        lambda cid, session: 1,
    )
    return container_api


@pytest.mark.parametrize(
    ("path", "body"),
    [
        (
            "/api/containers/add_collaborator",
            {"container_id": 1, "user_id": 1, "role": "OWNER"},
        ),
        (
            "/api/containers/update_role",
            {"container_id": 1, "user_id": 1, "updated_role": "OWNER"},
        ),
    ],
)
def test_ctrl_unknown_role_never_reaches_node(
    client, monkeypatch, path, body,
):
    container_api = _auth(monkeypatch)
    calls = []

    monkeypatch.setattr(
        container_api.container_service, "start_add_collaborator",
        lambda **kwargs: calls.append(("add", kwargs)) or {},
    )
    monkeypatch.setattr(
        container_api.container_service, "start_single_root_promotion",
        lambda **kwargs: calls.append(("single_root", kwargs)) or {},
    )
    monkeypatch.setattr(
        container_api.container_service, "start_root_handover",
        lambda **kwargs: calls.append(("handover", kwargs)) or {},
    )

    response = client.post(path, json=body)
    assert response.status_code in (400, 422)
    assert response.json()["success"] in (0, False)
    assert calls == []

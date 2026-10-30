"""Q51 SYSTEM template category guard."""

import pytest

from ...extensions import session_scope
from ...repositories import announcement_repo
from ..assertions import assert_json_error, assert_json_success
from ..factories import create_user
from ..mocks import mock_operator_token

_OPERATOR_HEADERS = {"token": "test-operator-token"}


def _api_module():
    return __import__("FuxiYu_CtrKernel.api.announcement_api", fromlist=[""])


def _make_template(*, name="guard-template", category="system"):
    with session_scope() as session:
        return announcement_repo.create_template(
            name=name,
            subject_template="guard subject",
            body_template="guard body",
            description="guard description",
            category=category,
            session=session,
        )


def _read_template(template_id):
    with session_scope(commit=False) as session:
        return announcement_repo.get_template_by_id(template_id, session=session)


def _snapshot(template):
    return {
        "name": template.name,
        "category": template.category,
        "description": template.description,
        "subject_template": template.subject_template,
        "body_template": template.body_template,
        "source_announcement_id": template.source_announcement_id,
    }


def _operator(monkeypatch):
    operator = create_user(operator=True)
    mock_operator_token(monkeypatch, _api_module(), user_id=operator.id)
    return operator


def test_system_to_custom_rejected_with_reason(client, monkeypatch):
    _operator(monkeypatch)
    template = _make_template()

    response = client.put(
        f"/api/announcements/templates/{template.id}",
        headers=_OPERATOR_HEADERS,
        json={"category": "custom"},
    )

    assert_json_error(response, 400, "cannot_change_system_template_category")
    stored = _read_template(template.id)
    assert stored.category.value == "system"


def test_repository_rejects_system_category_change(db_session):
    template = _make_template(name="repo-guard")
    before = _snapshot(template)

    with pytest.raises(ValueError, match="cannot_change_system_template_category"):
        announcement_repo.update_template(
            template.id,
            session=db_session,
            name="should-not-apply",
            category="custom",
        )

    stored = _read_template(template.id)
    assert _snapshot(stored) == before


def test_system_multi_field_update_is_atomic_on_rejection(client, monkeypatch):
    _operator(monkeypatch)
    template = _make_template(name="atomic-before")
    before = _snapshot(template)

    response = client.put(
        f"/api/announcements/templates/{template.id}",
        headers=_OPERATOR_HEADERS,
        json={
            "name": "atomic-after",
            "description": "new description",
            "subject_template": "new subject",
            "body_template": "new body",
            "category": "custom",
        },
    )

    assert_json_error(response, 400, "cannot_change_system_template_category")
    stored = _read_template(template.id)
    assert _snapshot(stored) == before


@pytest.mark.parametrize(
    ("include_category", "category"),
    [
        pytest.param(False, None, id="omitted"),
        pytest.param(True, None, id="null"),
    ],
)
def test_system_content_update_without_category_allowed(
    client, monkeypatch, include_category, category
):
    _operator(monkeypatch)
    template = _make_template(name="content-before")
    payload = {
        "name": "content-after",
        "description": "new description",
        "subject_template": "new subject",
        "body_template": "new body",
    }
    if include_category:
        payload["category"] = category

    response = client.put(
        f"/api/announcements/templates/{template.id}",
        headers=_OPERATOR_HEADERS,
        json=payload,
    )

    assert_json_success(response)
    stored = _read_template(template.id)
    assert stored.name == "content-after"
    assert stored.description == "new description"
    assert stored.subject_template == "new subject"
    assert stored.body_template == "new body"
    assert stored.category.value == "system"


def test_system_content_update_with_same_category_allowed(client, monkeypatch):
    _operator(monkeypatch)
    template = _make_template(name="same-before")

    response = client.put(
        f"/api/announcements/templates/{template.id}",
        headers=_OPERATOR_HEADERS,
        json={
            "name": "same-after",
            "description": "same description",
            "subject_template": "same subject",
            "body_template": "same body",
            "category": "system",
        },
    )

    assert_json_success(response)
    stored = _read_template(template.id)
    assert stored.name == "same-after"
    assert stored.description == "same description"
    assert stored.subject_template == "same subject"
    assert stored.body_template == "same body"
    assert stored.category.value == "system"


def test_custom_to_system_allowed(client, monkeypatch):
    _operator(monkeypatch)
    template = _make_template(name="custom-to-system", category="custom")

    response = client.put(
        f"/api/announcements/templates/{template.id}",
        headers=_OPERATOR_HEADERS,
        json={
            "name": "now-system",
            "description": "now description",
            "subject_template": "now subject",
            "body_template": "now body",
            "category": "system",
        },
    )

    assert_json_success(response)
    stored = _read_template(template.id)
    assert stored.name == "now-system"
    assert stored.description == "now description"
    assert stored.subject_template == "now subject"
    assert stored.body_template == "now body"
    assert stored.category.value == "system"

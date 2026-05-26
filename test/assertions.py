def assert_json_success(response, status_code: int = 200):
    assert response.status_code == status_code
    payload = response.get_json()
    assert payload["success"] == 1
    return payload


def assert_json_error(response, status_code: int, reason: str | None = None):
    assert response.status_code == status_code
    payload = response.get_json()
    assert payload["success"] == 0
    if reason is not None:
        assert payload["error_reason"] == reason
    return payload

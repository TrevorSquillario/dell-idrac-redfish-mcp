import pytest
import os


@pytest.mark.asyncio
async def test_login_sets_token(mock_idrac_client, host, username, password):
    if not username or not password:
        pytest.skip("USERNAME and PASSWORD environment variables required for integration tests")

    await mock_idrac_client.login(username, password)

    # token should be set from the live response (accept any non-empty token)
    assert mock_idrac_client.token_valid() is True
    token = mock_idrac_client._token
    assert isinstance(token, str) and token != ""

    # session uri should be populated from Location header
    assert mock_idrac_client._session_uri is not None

    # underlying http client should include the header and match the token
    assert mock_idrac_client.http.headers.get("X-Auth-Token") == token


@pytest.mark.asyncio
async def test_logout_clears_token_and_headers(mock_idrac_client, host, username, password):
    if not username or not password:
        pytest.skip("USERNAME and PASSWORD environment variables required for integration tests")

    # ensure we have a token to clear
    await mock_idrac_client.login(username, password)
    assert mock_idrac_client.token_valid() is True

    await mock_idrac_client.logout()

    # token and session uri should be cleared and header removed
    assert mock_idrac_client.token_valid() is False
    assert mock_idrac_client._token is None
    assert "X-Auth-Token" not in mock_idrac_client.http.headers


@pytest.mark.asyncio
async def test_get_lifecycle_logs_with_critical_severity(mock_idrac_client, host, username, password):
    if not username or not password:
        pytest.skip("USERNAME and PASSWORD environment variables required for integration tests")

    # ensure authenticated
    await mock_idrac_client.login(username, password)

    # request lifecycle logs with critical severity (start/end left as None)
    logs = await mock_idrac_client.get_lifecycle_logs(start_date=None, end_date=None, severity='critical')
    assert isinstance(logs, list)

    # if any entries returned, they should indicate Critical severity
    if logs:
        for entry in logs:
            sev = entry.get('Severity') or entry.get('severity')
            assert sev in ('Critical', 'critical') or ()


@pytest.mark.asyncio
async def test_get_error_and_event_registry_returns_first_entry(mock_idrac_client, host, username, password):
    if not username or not password:
        pytest.skip("USERNAME and PASSWORD environment variables required for integration tests")

    # ensure authenticated
    await mock_idrac_client.login(username, password)

    # request the full message registry mapping
    messages = await mock_idrac_client.get_error_and_event_registry(message_id=None)
    assert isinstance(messages, dict)
    assert messages, "Message registry should not be empty"

    # inspect the first entry returned by the registry
    first_key = next(iter(messages))
    first_entry = messages[first_key]
    assert isinstance(first_entry, dict)
    # key fields expected on message entries
    assert ('Message' in first_entry) or ('Description' in first_entry)

    # verify fetching a specific message_id returns the same entry
    single = await mock_idrac_client.get_error_and_event_registry(message_id=first_key)
    assert single == first_entry


@pytest.mark.asyncio
async def test_get_metric_report_definitions(mock_idrac_client, host, username, password):
    if not username or not password:
        pytest.skip("USERNAME and PASSWORD environment variables required for integration tests")

    await mock_idrac_client.login(username, password)

    members = await mock_idrac_client.telemetry.get_metric_report_definitions()
    assert isinstance(members, list)


@pytest.mark.asyncio
async def test_get_metric_report_definitions_systemusage(mock_idrac_client, host, username, password):
    if not username or not password:
        pytest.skip("USERNAME and PASSWORD environment variables required for integration tests")

    await mock_idrac_client.login(username, password)

    members = await mock_idrac_client.telemetry.get_metric_report_definitions(report_name="SystemUsage")
    assert isinstance(members, list)

@pytest.mark.asyncio
async def test_get_metric_report_readings_systemusage(mock_idrac_client, host, username, password):
    if not username or not password:
        pytest.skip("USERNAME and PASSWORD environment variables required for integration tests")

    await mock_idrac_client.login(username, password)

    readings = await mock_idrac_client.telemetry.get_metric_report_readings(report_name="SystemUsage")
    assert isinstance(readings, dict)

    # If readings present, keys should follow the '{MetricId}_{ContextID}' pattern
    if readings:
        for k, v in readings.items():
            assert isinstance(k, str) and "_" in k

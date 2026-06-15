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

    if readings:
        assert any("CPUUsage" in k for k in readings.keys())

@pytest.mark.asyncio
async def test_get_pciedevice_info(mock_idrac_client, host, username, password):
    if not username or not password:
        pytest.skip("USERNAME and PASSWORD environment variables required for integration tests")

    # ensure authenticated
    await mock_idrac_client.login(username, password)

    devices = await mock_idrac_client.inventory.get_pciedevice_info()
    assert isinstance(devices, list)

    # If devices are present, validate expected keys on the first entry
    if devices:
        first = devices[0]
        assert isinstance(first, dict)
        # required fields
        assert 'Manufacturer' in first or 'Name' in first or 'Id' in first


@pytest.mark.asyncio
async def test_get_firmware_inventory(mock_idrac_client, host, username, password):
    if not username or not password:
        pytest.skip("USERNAME and PASSWORD environment variables required for integration tests")

    # ensure authenticated
    await mock_idrac_client.login(username, password)

    members = await mock_idrac_client.inventory.get_firmware_inventory()
    assert isinstance(members, list)

    # If entries present, validate expected keys on the first entry
    if members:
        first = members[0]
        assert isinstance(first, dict)
        assert 'Id' in first or 'Name' in first or 'Version' in first


@pytest.mark.asyncio
async def test_get_idrac_users_username_attribute(mock_idrac_client, host, username, password):
    if not username or not password:
        pytest.skip("USERNAME and PASSWORD environment variables required for integration tests")

    # ensure authenticated
    await mock_idrac_client.login(username, password)

    # request the specific iDRAC attribute Users.2.UserName
    attrs = await mock_idrac_client.get_idrac_attributes(attributes="Users.2.UserName")
    assert isinstance(attrs, dict)

    # if returned, the requested key should be present
    if attrs:
        assert 'Users.2.UserName' in attrs


@pytest.mark.asyncio
async def test_get_bios_bootmode_attribute(mock_idrac_client, host, username, password):
    if not username or not password:
        pytest.skip("USERNAME and PASSWORD environment variables required for integration tests")

    # ensure authenticated
    await mock_idrac_client.login(username, password)

    # request the BIOS BootMode attribute
    bios = await mock_idrac_client.config.get_bios_attributes(attributes="BootMode")
    assert isinstance(bios, dict)

    # if returned, the BootMode key should be present
    if bios:
        assert 'BootMode' in bios

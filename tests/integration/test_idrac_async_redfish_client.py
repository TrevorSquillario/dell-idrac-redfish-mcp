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
async def test_export_server_screen_shot_server_screenshot(mock_idrac_client, host, username, password):
    if not username or not password:
        pytest.skip("USERNAME and PASSWORD environment variables required for integration tests")

    # ensure authenticated
    await mock_idrac_client.login(username, password)

    # request a ServerScreenShot (filetype=2)
    result = await mock_idrac_client.export_server_screen_shot(filetype=2)

    # accept bytes or a temporary filepath string
    if isinstance(result, (bytes, bytearray)):
        assert len(result) > 8
        assert result[:8] == b'\x89PNG\r\n\x1a\n'
    elif isinstance(result, str):
        # path returned; file should exist and begin with PNG header
        assert os.path.exists(result)
        with open(result, 'rb') as f:
            data = f.read(8)
        assert data == b'\x89PNG\r\n\x1a\n'
        try:
            os.unlink(result)
        except Exception:
            pass
    else:
        pytest.fail(f"unexpected return type from export_server_screen_shot: {type(result)!r}")


@pytest.mark.asyncio
async def test_support_assist_collection_returns_zip_path(mock_idrac_client, host, username, password):
    if not username or not password:
        pytest.skip("USERNAME and PASSWORD environment variables required for integration tests")

    await mock_idrac_client.login(username, password)

    # SupportAssist collection can take a while; use a generous timeout
    result = await mock_idrac_client.support_assist_collection(
        filter_val="0",
        data="0,1,2",
    )

    # result should be a string path to a sacollect.zip in a temp directory
    assert isinstance(result, str), f"expected str path, got {type(result)!r}"
    assert os.path.exists(result), f"zip path does not exist: {result}"
    assert result.endswith('.zip'), f"expected .zip suffix, got: {result}"
    assert 'sacollect' in result, f"expected 'sacollect' in path, got: {result}"

    # clean up
    try:
        os.unlink(result)
    except Exception:
        pass


@pytest.mark.asyncio
async def test_get_hardware_inventory_returns_xml_string(mock_idrac_client, host, username, password):
    if not username or not password:
        pytest.skip("USERNAME and PASSWORD environment variables required for integration tests")

    await mock_idrac_client.login(username, password)

    # trigger hardware inventory export and wait for the XML result
    result = await mock_idrac_client.get_hardware_inventory()

    # result should be XML text (a non-empty string starting with <?xml or <)
    assert isinstance(result, str), f"expected str, got {type(result)!r}"
    assert result, "hwinv.xml should not be empty"
    assert result.lstrip().startswith(('<', '<?xml')), f"unexpected XML start: {result[:50]!r}"

    # basic sanity: should mention Dell hardware somewhere in the content
    assert 'Dell' in result or 'dell' in result.lower(), f"expected Dell hardware info in XML, got: {result[:200]!r}"

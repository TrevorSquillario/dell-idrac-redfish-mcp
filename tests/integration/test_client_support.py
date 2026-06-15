import pytest
import os

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

    # result should be a dict containing 'sacollect_path' pointing to a sacollect.zip
    assert isinstance(result, dict), f"expected dict, got {type(result)!r}"
    assert 'sacollect_path' in result, f"expected 'sacollect_path' in result, got: {result!r}"
    sacollect_path = result['sacollect_path']
    assert isinstance(sacollect_path, str), f"expected str path, got {type(sacollect_path)!r}"
    assert os.path.exists(sacollect_path), f"zip path does not exist: {sacollect_path}"
    assert sacollect_path.endswith('.zip'), f"expected .zip suffix, got: {sacollect_path}"
    assert 'sacollect' in sacollect_path, f"expected 'sacollect' in path, got: {sacollect_path}"

    # clean up
    try:
        os.unlink(sacollect_path)
    except Exception:
        pass


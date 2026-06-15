import os
from datetime import datetime, timedelta

import pytest

from idrac_async_redfish_client.client import iDRACAsyncRedfishClient


def test_set_token_records_timestamp_and_valid():
    client = iDRACAsyncRedfishClient('1.2.3.4', verify=False)
    client.set_token('abc', session_uri='https://1.2.3.4/redfish/v1/SessionService/Sessions/1')
    assert client._token == 'abc'
    assert client._token_created_at is not None
    assert 'X-Auth-Token' in client.http.headers
    assert client.token_valid()


def test_token_expires_based_on_env(monkeypatch):
    client = iDRACAsyncRedfishClient('1.2.3.4', verify=False)
    client._token = 'abc'
    client.http.headers['X-Auth-Token'] = 'abc'
    # simulate token created in the past
    client._token_created_at = datetime.utcnow() - timedelta(seconds=2000)
    monkeypatch.setenv('IDRAC_SESSION_TIMEOUT', '1800')
    assert client.token_valid() is False
    assert client._token is None
    assert 'X-Auth-Token' not in client.http.headers

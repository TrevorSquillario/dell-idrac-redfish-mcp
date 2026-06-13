
### No EEMIRegistry for 17g
It's in the iDRAC10 API https://developer.dell.com/apis/1796449a-cc87-4882-925b-6241fbf1bfea/versions/1.30.xx/eemiregistry-instance-254609e0
Maybe the redfish mock creator didn't capture it? Test this out on a real iDRAC.

```
pytest -s -q tests/integration/test_idrac_async_redfish_client.py


E       httpx.HTTPStatusError: Client error '404 Not Found' for url 'https://192.168.0.203/redfish/v1/Registries/Messages/EEMIRegistry'
E       For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404

/opt/venv/lib/python3.13/site-packages/httpx/_models.py:829: HTTPStatusError
```
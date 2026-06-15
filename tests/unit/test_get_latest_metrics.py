import json
from pathlib import Path

from idrac_async_redfish_client.services.telemetry import TelemetryService


def test_get_latest_metrics_from_example_json():
	"""Load the provided example JSON and verify a known custom key value."""
	p = Path(__file__).with_name("test_get_latest_metrics.json")
	data = json.loads(p.read_text())

	latest = TelemetryService.get_latest_metrics(data)

	# Check metric and context exist and have the expected latest value
	assert "TemperatureReading" in latest
	assert "DIMM.Socket.A1" in latest["TemperatureReading"]
	assert latest["TemperatureReading"]["DIMM.Socket.A1"] == "28"


def test_get_latest_metrics_chooses_newer_timestamp():
	"""Ensure that when multiple entries share the same MetricId+ContextID,
	the entry with the newer Timestamp is selected.
	"""
	report = {
		"MetricValues": [
			{
				"MetricId": "MyMetric",
				"Timestamp": "2026-01-01T00:00:00Z",
				"MetricValue": "old",
				"Oem": {"Dell": {"ContextID": "CTX1"}},
			},
			{
				"MetricId": "MyMetric",
				"Timestamp": "2026-01-01T00:00:01Z",
				"MetricValue": "new",
				"Oem": {"Dell": {"ContextID": "CTX1"}},
			},
		]
	}

	latest = TelemetryService.get_latest_metrics(report)
	assert "MyMetric" in latest
	assert "CTX1" in latest["MyMetric"]
	assert latest["MyMetric"]["CTX1"] == "new"


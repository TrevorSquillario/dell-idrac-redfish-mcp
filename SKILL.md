Start a Redfish API directory walk starting with /redfish/v1/Chassis/System.Embedded.1 on 192.168.5.69. Use the idrac get_redfish_uri to make the request and return a grouped list of links to follow next. Provide a prompt to ask the user which links to follow next, and then make those requests in parallel, collecting the results into a single response.

---

Start a PCIeDevice walk starting with /redfish/v1/Chassis/System.Embedded.1/PCIeDevices. Retreive the list of PCIe device links, then in parallel batches of 4, retrieve the details for each device. Collect the results into a single response.

---

Start a Storage walk starting with /redfish/v1/Systems/System.Embedded.1/Storage. Retreive the list of storage device links, then in parallel batches of 4, retrieve the details for each device. Collect the results into a single response.

---

Metric Report Definition browser. Start with /redfish/v1/TelemetryService/MetricReportDefinitions. Retrieve the list of metric report definition links, then present the user with a prompt to select which metric report definitions to retrieve. Retrieve the details for the selected metric report definition.

---

Get the the last 10 lifecycle logs for these hosts. Separate them into parallel subtasks and collect the results into a single response:

192.168.5.66
192.168.5.67
192.168.5.68
192.168.5.69
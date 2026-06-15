# idrac-redfish-mcp
Basic MCP Server for the Dell iDRAC using Redfish

The goal of this project is not to be at feature parity with every Redfish endpoint but to narrow it's scope to useful tools for troubleshooting and eventually managing servers. Outputs have to be specially crafted to not exceed context windows and prevent context bloat. 

# Setup

Copy `.env.example` to `.env` or update the `compose.yaml` with the required environment variables.

Update your Hermes `config.yaml` with:

For `http`

```
mcp_servers:
  idrac:
    url: http://192.168.8.110:8088/mcp
    ssl_verify: false
```

For `stdio` you can add a volume mapping to your `compose.yaml`
```
volumes:
- ../../idrac-redfish-mcp:/mcp/idrac-redfish-mcp:ro
```

```
mcp_servers:
  idrac:
    command: "/opt/venv/bin/python"
    args: ["/mcp/idrac-redfish-mcp/src/fastmcp_server.py"]
    env:
      IDRAC_USERNAME: ${IDRAC_USERNAME}
      IDRAC_PASSWORD: ${IDRAC_PASSWORD}
      IDRAC_SSL_VERIFY: ${IDRAC_SSL_VERIFY}
```

# Troubleshooting

```
docker exec -it hermes /bin/bash
cd /mcp/idrac-redfish-mcp
fastmcp list src/fastmcp_server.py get_lc_logs host=192.168.0.200
fastmcp call src/fastmcp_server.py get_lc_logs host=192.168.0.200
```
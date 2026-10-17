#!/usr/bin/env python3
"""Authenticated HTTP proxy over the operator's existing Blender stdio MCP wrapper."""
from common import runtime_args,read
def main():
 root=runtime_args(__doc__)
 from fastmcp import FastMCP
 from fastmcp.client.transports import StdioTransport
 from fastmcp.server.auth.providers.jwt import StaticTokenVerifier
 config=read(root/'blender-config.json');token=read(root/'secrets.json')['blender_upstream']
 transport=StdioTransport(config['command'],args=config['args'],env=config['env'])
 proxy=FastMCP.as_proxy(transport,name='Mac Blender',auth=StaticTokenVerifier(tokens={token:{'client_id':'mcphub','scopes':['tools']}}))
 proxy.run(transport='http',host='127.0.0.1',port=config['port'],show_banner=False)
if __name__=='__main__':main()

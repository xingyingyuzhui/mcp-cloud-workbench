#!/usr/bin/env python3
"""Keep the original ComfyUI MCP loopback Host validation intact."""
from common import runtime_args,read
def main():
 root=runtime_args(__doc__)
 from fastmcp import FastMCP
 from fastmcp.server.auth.providers.jwt import StaticTokenVerifier
 config=read(root/'comfyui-config.json');token=read(root/'secrets.json')['comfyui_upstream']
 proxy=FastMCP.as_proxy(config['upstream_url'],name='Mac ComfyUI',auth=StaticTokenVerifier(tokens={token:{'client_id':'mcphub','scopes':['tools']}}))
 proxy.run(transport='http',host='127.0.0.1',port=config['port'],show_banner=False)
if __name__=='__main__':main()

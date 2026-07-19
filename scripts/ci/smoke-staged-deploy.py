#!/usr/bin/env python3
import argparse, json, threading, urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

p=argparse.ArgumentParser(); p.add_argument('--dist-root',type=Path,required=True); p.add_argument('--api-root',type=Path,required=True); a=p.parse_args()
index=a.api_root/'index.json'; copied=a.dist_root/'api'/a.api_root.name/'index.json'
for path in (a.dist_root/'index.html',index,copied):
    if not path.is_file(): raise SystemExit('staged deploy smoke failed')
payload=json.loads(index.read_text(encoding='utf-8'))
if not isinstance(payload,dict) or not isinstance(payload.get('data'),dict) or not isinstance(payload['data'].get('protocols'),list): raise SystemExit('staged deploy smoke failed')
class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *_): pass
server=ThreadingHTTPServer(('127.0.0.1',0),lambda *args: Quiet(*args,directory=str(a.dist_root),**kwargs))
thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
try:
    base=f'http://127.0.0.1:{server.server_port}'
    for route in ('/','/api/v1.7.0/index.json'):
        with urllib.request.urlopen(base+route,timeout=5) as response:
            if response.status != 200: raise SystemExit('staged deploy smoke failed')
finally:
    server.shutdown(); thread.join()
print('staged deploy smoke passed')

import argparse,json
from pathlib import Path
REPO=Path(__file__).resolve().parents[1]
def runtime_args(description):
 p=argparse.ArgumentParser(description=description)
 p.add_argument('--runtime',type=Path,default=REPO/'runtime/mac-bridge')
 a=p.parse_args();return a.runtime.resolve()
def read(path):return json.loads(path.read_text())

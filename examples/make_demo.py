"""Create a tiny original fixture without Sphinx or network access."""
import argparse
from pathlib import Path
import zlib

parser = argparse.ArgumentParser()
parser.add_argument('destination')
parser.add_argument('--broken', action='store_true')
args = parser.parse_args()
root = Path(args.destination)
root.mkdir(parents=True, exist_ok=False)
(root / 'index.html').write_text('<!doctype html><title>Demo</title><h1 id="demo.greet">Greeting</h1>\n', encoding='utf-8')
uri = 'index.html#removed' if args.broken else 'index.html#$'
header = b'# Sphinx inventory version 2\n# Project: Demo\n# Version: 1\n# zlib\n'
(root / 'objects.inv').write_bytes(header + zlib.compress(f'demo.greet py:function 1 {uri} -\n'.encode()))
print(root)

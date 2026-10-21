#!/bin/bash
TX=$1
curl -s -X POST -H "Content-Type: application/json" \
  --data "{\"jsonrpc\":\"2.0\",\"method\":\"eth_getTransactionByHash\",\"params\":[\"$TX\"],\"id\":1}" \
  http://127.0.0.1:8545 | venv/bin/python -c "
import json,sys
t=json.load(sys.stdin)['result']
d=t['input'][10:]
w=[d[i:i+64] for i in range(0,len(d),64)]
print('block     :', int(t['blockNumber'],16))
print('contract  :', t['to'])
print('from      :', t['from'])
print('file hash : 0x'+w[3])
print('merkle    : 0x'+w[4])
print('chunks    :', int(w[5],16))
"

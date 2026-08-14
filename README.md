# Casting

Choose the harness and model for a task profile.

The approved boundary and migration design lives in
[PWC issue #7](https://github.com/shreyansqt/pwc/issues/7#issuecomment-5294907115).

## Current scope

This repository contains the standalone routing core. It owns qualification,
preference selection, cost order, and the complete route explanation. It does not
read PWC tasks, launch processes, or choose a work host.

The caller supplies two values:

- A profile with an opaque stable key, domain, reasoning, verifiability, risk,
  and context need.
- A version 1 policy document with model rows, an overlay, and the top-level
  `preferences` block.

Shared D1 storage, host inventory, and the PWC compatibility adapter are later
tasks. The core accepts policy as data, so those components can call the same pure
library without changing route behavior.

## Library

```python
from casting import route

decision = route(
    {
        "stable_key": "repo#7:implementation",
        "domain": "implementation",
        "reasoning": 4,
        "verifiability": 4,
        "risk": "none",
        "context_need": 200_000,
    },
    policy,
)
```

`route` does not perform input or output operations. It hashes the stable key but
does not parse its format.

## Command line

The command line uses protocol version 1 and emits JSON:

```bash
python3 bin/casting route \
  --key 'repo#7:implementation' \
  --domain implementation \
  --reasoning 4 \
  --verifiability 4 \
  --context-need 200000 \
  --policy policy.json \
  --explain
```

A pipeline can send the complete request on standard input:

```bash
python3 bin/casting route --request - < request.json
```

The request must contain `profile` and `policy` objects. The response includes
`schema_version: 1`. Pass `--protocol-version 1` when a caller must pin the
contract. Casting rejects unsupported versions.

## Verification

```bash
PYTHONPATH=src python3 -m pytest
```

The migration fixtures include the post-issue-12 routing fields and their SHA-256
digest. Private notes are not part of the fixture. The corpus uses synthetic keys.
It must produce 240 Codex routes, 60 Claude routes, and no errors.

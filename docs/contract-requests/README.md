# Contract requests

`packages/contracts` and `packages/db` are owned by the foundation prompt. If your lane needs a change (a new field, a new tool, a column, a grant), don't edit those packages. Append to `docs/contract-requests/<lane>.md`:

```
## <date> · <short title>
Need: what you need, and the exact model / field / column.
Why: which feature it unblocks.
Workaround: what you did meanwhile, if anything.
```

The foundation prompt reviews requests, updates the contracts, the migrations and the JSON Schema, and notes the outcome under the request.

# api

api is the FastAPI service the browser talks to: auth, POST/GET /api/imports, POST /api/plans (returns plan_id), GET /api/plans/{id}/events as Server-Sent Events, POST /api/plans/{id}/review and /answer to resume the paused graph, and GET /api/plans/{id} for the saved plan. Every request and response body and every SSE event is a model from homefund_contracts.

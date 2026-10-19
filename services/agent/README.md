# agent

agent is the LangGraph state machine on the design's Agent graph page: parse_goal, ask_user, estimate_home_cost, analyze_spending, project_savings, solve_cuts, review_cuts, explain_costs and write_plan over PlanState, with interrupt() pauses at ask_user and review_cuts and a Postgres checkpointer. It calls the three MCP servers for every number, uses the model server only for language, recomputes every figure before a plan is shown, and emits the SSE event union from homefund_contracts.

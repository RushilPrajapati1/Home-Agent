# evals

End-to-end and model-quality evaluations, owned by the evals lane. Start from `fixtures/golden_scenario.json`: run the whole graph on a `FixedClock(2026-10-01)` against the seeded demo user and the FRED/RentCast mocks, then assert every expected number. Further suites: importer categorization accuracy against `fixtures/demo_user/transactions_labeled.csv`, and retrieval quality (recall@20, nDCG@5) for guides-mcp. Evals may call the local model server. Unit tests may not.

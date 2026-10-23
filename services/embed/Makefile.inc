# embed targets. Owned by the embed lane; prefix every target with embed-.
.PHONY: embed-run embed-up embed-models embed-test-slow

embed-run: ## Run the embed service on the host at EMBED_URL (CUDA+fp16 if present, else CPU)
	$(UV) --package homefund-embed --extra model homefund-embed

embed-up: ## Start the embed container and wait until the models are loaded
	$(COMPOSE) up -d --wait embed

embed-models: ## Pull BGE-M3 and bge-reranker-v2-m3 into the embed_models volume (egress)
	$(COMPOSE) --profile tools run --rm embed-models

embed-test-slow: ## The one test that loads the real models (HF cache or network needed)
	HOMEFUND_SLOW=1 $(UV) --package homefund-embed --extra model pytest services/embed/tests/test_real_model.py

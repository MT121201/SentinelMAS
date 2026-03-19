.PHONY: dev build test lint generate-vault-key rotate-jwt-secret backup-db logs ps down clean help

# ─── Default ──────────────────────────────────────────────
help:
	@echo "GPU-MAS — available targets:"
	@echo "  make dev               Start all services (build if needed)"
	@echo "  make build             Build all service images"
	@echo "  make down              Stop and remove containers"
	@echo "  make logs              Tail logs for all services"
	@echo "  make ps                Show running containers"
	@echo "  make test              Run all tests"
	@echo "  make lint              Run ruff linter"
	@echo "  make migrate           Apply Alembic migrations"
	@echo "  make generate-vault-key  Generate a new VAULT_MASTER_KEY"
	@echo "  make rotate-jwt-secret   Generate a new JWT_SECRET_KEY"
	@echo "  make backup-db         Dump masdb to ./backups/"
	@echo "  make clean             Remove containers, volumes, images"

# ─── Dev lifecycle ────────────────────────────────────────
dev:
	docker compose up --build

build:
	docker compose build

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

ps:
	docker compose ps

# ─── Testing ──────────────────────────────────────────────
test:
	pytest services/ -v --asyncio-mode=auto

test-service:
	@echo "Usage: make test-service SERVICE=client-agent"
	pytest services/$(SERVICE)/tests/ -v --asyncio-mode=auto

# ─── Linting ──────────────────────────────────────────────
lint:
	ruff check services/
	ruff format --check services/

lint-fix:
	ruff check --fix services/
	ruff format services/

# ─── Database ─────────────────────────────────────────────
migrate:
	docker compose exec api-gateway alembic upgrade head

migrate-down:
	docker compose exec api-gateway alembic downgrade -1

# ─── Security helpers ─────────────────────────────────────
generate-vault-key:
	@python3 -c "import secrets, base64; print('VAULT_MASTER_KEY=' + base64.b64encode(secrets.token_bytes(32)).decode())"

rotate-jwt-secret:
	@python3 -c "import secrets; print('JWT_SECRET_KEY=' + secrets.token_urlsafe(48))"

# ─── Backup ───────────────────────────────────────────────
backup-db:
	@mkdir -p backups
	docker compose exec postgres pg_dump -U mas masdb > backups/masdb_$(shell date +%Y%m%d_%H%M%S).sql
	@echo "Backup saved to backups/"

# ─── Scale helpers ────────────────────────────────────────
scale-client:
	@echo "Usage: make scale-client N=6"
	docker compose up --scale client-agent=$(N) -d

scale-inserver:
	@echo "Usage: make scale-inserver N=4"
	docker compose up --scale inserver-agent=$(N) -d

# ─── Clean ────────────────────────────────────────────────
clean:
	docker compose down -v --rmi local

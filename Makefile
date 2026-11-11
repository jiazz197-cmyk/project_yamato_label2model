# ===========================================================================
# label2model 开发命令
#
# 容器化开发（推荐，只依赖 Docker/Compose）：
#   make dev-up          启动默认开发栈（app/web/中间件，源码挂载）
#   make dev-up-build    首次或改依赖后构建并启动
#   make dev-rebuild     只重建依赖镜像（改 pyproject/poetry.lock/Dockerfile 后）
#   make ml-up           启用训练/推理侧车（ml-api + ml-worker）
#   make dev-logs / web-logs / ml-logs
#
# VS Code：安装 Dev Containers 扩展后打开本目录，执行
#   Dev Containers: Reopen in Container
#
# 本地开发（备选，需要 Python 3.12 + Poetry + Node/Yarn）
# ===========================================================================

.DEFAULT_GOAL := dev-up

.PHONY: dev-up dev-up-build dev-down dev-down-clean dev-ps dev-logs dev-rebuild \
        web-logs dev-shell ml-up ml-down ml-logs ml-rebuild env-setup \
        docker-build docker-up docker-up-build docker-down docker-down-clean \
        docker-ps docker-logs docker-config docker-build-ml docker-up-ml \
        docker-ps-ml docker-logs-ml docker-migrate-dev docker-makemigrations-dev \
        docker-collectstatic-dev docker-createsuperuser docker-admin-org docker-shell \
        docker-test docker-test-gateway run-dev migrate-dev makemigrations-dev shell-dev \
        frontend-install frontend-setup frontend-dev frontend-watch frontend-build \
        frontend-storybook-serve test update-urls fmt fmt-all fmt-check fmt-check-all \
        configure-hooks generate-swagger

# ---------------------------------------------------------------------------
# 容器化开发（推荐）
# ---------------------------------------------------------------------------
dev-up:
	docker compose up -d

dev-up-build:
	docker compose up -d --build

dev-down:
	docker compose down

dev-down-clean:
	docker compose down -v

dev-ps:
	docker compose ps

dev-logs:
	docker compose logs -f --tail=100

web-logs:
	docker compose logs -f --tail=100 web

# 只有依赖清单 / Dockerfile 变化时才需要执行
dev-rebuild:
	docker compose build app web

dev-shell:
	docker compose exec app bash

# ---------------------------------------------------------------------------
# 训练/推理侧车（ml profile）
# ---------------------------------------------------------------------------
ml-up:
	docker compose --profile ml up -d --build

ml-down:
	docker compose --profile ml stop ml-api ml-worker

ml-logs:
	docker compose --profile ml logs -f --tail=100 ml-api ml-worker

ml-rebuild:
	docker compose --profile ml build

# ---------------------------------------------------------------------------
# 兼容旧命令名
# ---------------------------------------------------------------------------
docker-build: dev-rebuild
docker-up: dev-up
docker-up-build: dev-up-build
docker-down: dev-down
docker-down-clean: dev-down-clean
docker-ps: dev-ps
docker-logs: dev-logs
docker-config:
	docker compose config -q
docker-build-ml: ml-rebuild
docker-up-ml: ml-up
docker-ps-ml:
	docker compose --profile ml ps
docker-logs-ml:
	docker compose --profile ml logs -f --tail=100

docker-migrate-dev:
	docker compose exec app python label_studio/manage.py migrate

docker-makemigrations-dev:
	docker compose exec app python label_studio/manage.py makemigrations

docker-collectstatic-dev:
	docker compose exec app python label_studio/manage.py collectstatic --noinput --no-default-ignore

docker-createsuperuser:
	docker compose exec app python label_studio/manage.py createsuperuser
	@echo "提示：命令行创建的超管还没有组织，请执行 make docker-admin-org EMAIL=<邮箱>"

docker-admin-org:
	docker compose exec app python docker/ensure_admin_org.py $(EMAIL)

docker-shell:
	docker compose exec app python label_studio/manage.py shell_plus

# 训练域（FastAPI ml-api）测试：SQLAlchemy + TestClient，跑在 ml 镜像里
docker-test:
	docker compose --profile ml run --rm ml-api bash -lc "cd /label-studio && pytest -c services/pytest.ini -v services/tests"

# Django 侧仅剩 /api/training/ 网关，测试转发/鉴权/状态码映射
docker-test-gateway:
	docker compose exec app bash -lc "cd label_studio && DJANGO_DB=sqlite pytest --import-mode=importlib -c pytest.ini -v -m 'not integration_tests' tests/test_training_proxy.py"

env-setup:
	@if [ ! -f .env ]; then cp .env.example .env && echo "已生成 .env（可选，compose 有内置开发默认值）"; fi

# ---------------------------------------------------------------------------
# 本地 Poetry 开发（备选）
# ---------------------------------------------------------------------------
run-dev:
	DJANGO_DB=sqlite LOG_DIR=tmp DEBUG=true LOG_LEVEL=DEBUG DJANGO_SETTINGS_MODULE=core.settings.label_studio poetry run python label_studio/manage.py runserver

migrate-dev:
	DJANGO_DB=sqlite LOG_DIR=tmp DEBUG=true LOG_LEVEL=DEBUG DJANGO_SETTINGS_MODULE=core.settings.label_studio poetry run python label_studio/manage.py migrate

makemigrations-dev:
	DJANGO_DB=sqlite LOG_DIR=tmp DEBUG=true LOG_LEVEL=DEBUG DJANGO_SETTINGS_MODULE=core.settings.label_studio poetry run python label_studio/manage.py makemigrations

shell-dev:
	DJANGO_DB=sqlite LOG_DIR=tmp DEBUG=true LOG_LEVEL=DEBUG DJANGO_SETTINGS_MODULE=core.settings.label_studio poetry run python label_studio/manage.py shell_plus

# ---------------------------------------------------------------------------
# 前端本地命令（容器内开发不需要；web 服务已提供 HMR）
# ---------------------------------------------------------------------------
frontend-install:
	cd web && yarn install --frozen-lockfile

frontend-setup: frontend-install

frontend-dev:
	cd web && yarn run dev

frontend-watch:
	cd web && yarn run watch

frontend-build: frontend-setup
	cd web && yarn run build

frontend-storybook-serve: frontend-setup
	cd web && yarn run ui:serve

# ---------------------------------------------------------------------------
# 测试与维护
# ---------------------------------------------------------------------------
test:
	cd label_studio && DJANGO_DB=sqlite pytest -v -m "not integration_tests"

update-urls:
	DJANGO_DB=sqlite LOG_DIR=tmp DEBUG=true LOG_LEVEL=DEBUG DJANGO_SETTINGS_MODULE=core.settings.label_studio poetry run python label_studio/manage.py show_urls --format pretty-json > ./label_studio/core/all_urls.json

fmt:
	pre-commit run --config .pre-commit-dev.yaml --hook-stage manual

fmt-all:
	pre-commit run --config .pre-commit-dev.yaml --hook-stage manual --all-files

fmt-check:
	pre-commit run --hook-stage pre-push

fmt-check-all:
	pre-commit run --hook-stage pre-push --all-files

configure-hooks:
	pre-commit install --hook-type pre-push

generate-swagger:
	DJANGO_DB=sqlite LOG_DIR=tmp DEBUG=true LOG_LEVEL=DEBUG DJANGO_SETTINGS_MODULE=core.settings.label_studio poetry run python label_studio/manage.py generate_swagger swagger.json

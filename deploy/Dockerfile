FROM node:22-alpine AS web-build

WORKDIR /src/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    NEBULA_ONE_HOST=0.0.0.0 \
    NEBULA_ONE_PORT=8088 \
    NEBULA_ONE_DATABASE_URL=sqlite:////app/runtime/nebula-one.db \
    NEBULA_ONE_CASEPACK_ROOTS=/app/cases \
    NEBULA_ONE_RELEASE_CATALOG_FILE=/app/config/public-catalog.v1.json \
    NEBULA_ONE_WEB_ROOT=/app/web

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

COPY cases/standard-lca-seeds/iron-steel-bf-bof-crude-steel/ ./cases/standard-lca-seeds/iron-steel-bf-bof-crude-steel/
COPY cases/project-templates/steel-bf-bof-inventory/ ./cases/project-templates/steel-bf-bof-inventory/
COPY deploy/public-catalog.v1.json ./config/public-catalog.v1.json
COPY --from=web-build /src/web/dist/ ./web/
RUN mkdir -p /app/runtime

EXPOSE 8088

CMD ["python", "-m", "nebula_one"]

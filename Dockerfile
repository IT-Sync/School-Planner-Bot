FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN groupadd --gid 10001 planner \
    && useradd --uid 10001 --gid planner --no-create-home --shell /usr/sbin/nologin planner

COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock

COPY pyproject.toml README.md ./
COPY app ./app
COPY migrations ./migrations
RUN pip install --no-cache-dir --no-deps .

USER planner
EXPOSE 8000 8088
CMD ["python", "-m", "app.main"]

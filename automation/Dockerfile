# Build context is the repository root (see docker-compose.yml) so this
# image can include config/defaults.yaml alongside the automation service.
FROM python:3.11-slim

WORKDIR /app

COPY automation/requirements.txt automation/requirements.txt
RUN pip install --no-cache-dir -r automation/requirements.txt

COPY automation/ automation/
COPY config/ config/
RUN pip install --no-cache-dir -e automation/

CMD ["python", "-m", "automation_service.main"]

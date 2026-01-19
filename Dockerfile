# Dockerfile
FROM python:3.8-slim-bookworm
COPY requirements.txt /app/requirements.txt
WORKDIR /app
RUN pip install --no-cache-dir -r requirements.txt
COPY . /app
ENTRYPOINT ["python"]
EXPOSE 5007
CMD ["run.py"]
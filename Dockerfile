# Dockerfile
FROM python:3.8-slim-bookworm

ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN mkdir -p /home/evidence /home/cases

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

EXPOSE 5007 8080
ENTRYPOINT ["python"]
CMD ["run.py"]
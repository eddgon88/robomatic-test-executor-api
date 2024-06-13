# Dockerfile
FROM python:3.8.10
COPY requirements.txt /app/requirements.txt
WORKDIR /app
RUN apt-get update && apt-get install -y docker.io
RUN pip install -r requirements.txt
COPY . /app
ENTRYPOINT ["python"]
EXPOSE 5007
CMD ["run.py"]
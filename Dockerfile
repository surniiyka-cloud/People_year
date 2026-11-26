FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py .
COPY static static
ENV PEOPLE_DB=/data/people.sqlite3
EXPOSE 8080
CMD ["python", "server.py"]

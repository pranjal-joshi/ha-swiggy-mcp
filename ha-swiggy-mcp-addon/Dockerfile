ARG BUILD_FROM
FROM $BUILD_FROM

# Install Python3 + pip
RUN apk add --no-cache python3 py3-pip

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY src/ ./src/

CMD ["python3", "-u", "src/server.py"]

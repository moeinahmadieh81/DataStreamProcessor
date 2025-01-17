FROM python:3.11-slim-buster

RUN apt-get update  && apt-get install -y \
    postgresql-client \
    gcc \
    python3-dev \
    libpq-dev \
    netcat-openbsd

WORKDIR /code

COPY requirements.txt /code/
RUN pip install --upgrade pip
RUN pip install -r requirements.txt
RUN pip install --upgrade boto3


COPY ./consumer.py /code/

CMD ["python", "consumer.py"]

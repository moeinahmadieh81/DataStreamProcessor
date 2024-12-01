import time
import requests
import json
from confluent_kafka import Consumer, KafkaError
import os
from minio import Minio
from minio.error import S3Error
import psycopg2
from datetime import timedelta
from io import BytesIO


TABLE_NAME = 'PRODUCER_RECORDS'
TOPIC_NAME = 'objectFiles'
DB_NAME = os.getenv('POSTGRES_DB')
DB_USER = os.getenv('POSTGRES_USER')
DB_PASSWORD = os.getenv('POSTGRES_PASSWORD')
KAFKA_LISTENER_INTERNAL = os.getenv('KAFKA_LISTENER_NAME_INTERNAL')
MINIO_USERNAME = os.getenv('MINIO_ROOT_USER')
MINIO_PASSWORD = os.getenv('MINIO_ROOT_PASSWORD')


MAX_RETRIES = 3
RETRY_DELAY = 5


def download_file_from_producer(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        print(f'status code: {response.status_code}')
        file_content = response.content
        return file_content

    except requests.exceptions.RequestException as error:
        print(f'error in downloading file: {error}')
        return None


def upload_file_to_minio(minio_client, file_content, bucket_name, object_name):
    try:
        if not minio_client.bucket_exists(bucket_name):
            print(f'bucket {bucket_name} does not exist')
            minio_client.make_bucket(bucket_name)

        file_stream = BytesIO(file_content)
        file_stream.seek(0)
        minio_client.put_object(bucket_name, object_name, file_stream, len(file_content))
        print(f'file {object_name} uploaded to {bucket_name}')

        stat = minio_client.stat_object(bucket_name, object_name)
        return stat.size, stat.etag

    except S3Error as error:
        print(f'error in uploading file: {error}')
        return None, None

def get_file_presigned_url(minio_client, bucket_name, object_name):
    try:
        url = minio_client.presigned_get_object(bucket_name, object_name, expires=timedelta(seconds=3600))
        return url
    except S3Error as error:
        print(f'error in getting presigned url: {error}')
        return None


def update_database_schema(file_size, etag, object_id):
    try:
        connection = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host='db',
            port='5432'
        )
        cursor = connection.cursor()

        update_query = f"""UPDATE {TABLE_NAME}
                              SET size = %s, etag = %s
                              WHERE id = %s"""
        cursor.execute(update_query, (file_size, etag, object_id))
        connection.commit()
        print(f'record {object_id} updated with size {file_size}, etag {etag}')

    except (Exception, psycopg2.DatabaseError) as error:
        print(f'error in updating database: {error}')

    finally:
        if connection:
            cursor.close()
            connection.close()


def create_consumer():
    consumer = Consumer({
        'bootstrap.servers': KAFKA_LISTENER_INTERNAL,
        'group.id': 'my_group',
        'auto.offset.reset': 'earliest',
    })
    consumer.subscribe([TOPIC_NAME])
    return consumer

if __name__ == '__main__':
    consumer = create_consumer()
    try:
        while True:
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                else:
                    print(f'error in receiving message: {msg.error()}')
                    break

            content = json.loads(msg.value().decode('utf-8'))
            print(f'content: {content}')
            consumer.commit(asynchronous=False)

            for attempt in range(MAX_RETRIES):
                try:
                    file_content = download_file_from_producer(content['url'])

                    minio_client = Minio('minio:9000',
                                         access_key=MINIO_USERNAME,
                                         secret_key=MINIO_PASSWORD,
                                         secure=False)

                    if file_content is not None:
                        bucket_name = content['bucket_name']
                        object_name = content['object_name']
                        file_size, file_etag = upload_file_to_minio(minio_client, file_content, bucket_name, object_name)
                        presigned_url = get_file_presigned_url(minio_client, bucket_name, object_name)
                        if presigned_url:
                            print(f"Pre-signed URL: {presigned_url}")

                        if file_size is not None and file_etag is not None:
                            update_database_schema(file_size, file_etag, content['id'])
                        break
                    else:
                        raise Exception("unsuccessful download!")

                except Exception as error:
                    print(f'error in processing file: {error}')
                    if attempt < MAX_RETRIES - 1:
                        print(f'retrying {attempt+1}/{MAX_RETRIES} in {RETRY_DELAY} seconds')
                        time.sleep(RETRY_DELAY)
                    else:

                        print('out of retries')

    except KeyboardInterrupt:
        print('consumer stopped')
    finally:
        consumer.close()

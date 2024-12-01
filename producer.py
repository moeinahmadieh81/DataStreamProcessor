import psycopg2
from confluent_kafka import Producer
import json
import os


TABLE_NAME = 'PRODUCER_RECORDS'
TOPIC_NAME = 'objectFiles'
DB_NAME = os.getenv('POSTGRES_DB')
DB_USER = os.getenv('POSTGRES_USER')
DB_PASSWORD = os.getenv('POSTGRES_PASSWORD')
KAFKA_LISTENER_INTERNAL = os.getenv('KAFKA_LISTENER_NAME_INTERNAL')


class Content:
    def __init__(self, id, url, bucket_name, object_name, etag=None, size=None):
        self.id = id
        self.url = url
        self.bucket_name = bucket_name
        self.object_name = object_name
        self.etag = etag
        self.size = size

    def __str__(self):
        return f'content[ id: {self.id}, url: {self.url}, bucket_name: {self.bucket_name}, object_name: {self.object_name}]'


def create_table():
    try:
        conn = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host='db',
            port='5432'
        )

        cur = conn.cursor()
        cur.execute(f'''CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
                        id INTEGER PRIMARY KEY,
                        url VARCHAR(255) NOT NULL,
                        bucket_name VARCHAR(100) NOT NULL,
                        object_name VARCHAR(100) NOT NULL,
                        etag VARCHAR(100) DEFAULT NULL,
                        size INTEGER DEFAULT NULL
                        );
        ''')
        conn.commit()
        print(f'Table {TABLE_NAME} created')

    except (Exception, psycopg2.DatabaseError) as error:
        print(f'error in creating table: {error}')
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def store_content_to_db(content):
    try:
        conn = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host='db',
            port='5432'
        )
        cur = conn.cursor()

        values = (content.id, content.url, content.bucket_name, content.object_name)

        cur.execute(f'''
        INSERT INTO {TABLE_NAME}(id, url, bucket_name, object_name)
        VALUES(%s, %s, %s, %s);
        ''', values)

        conn.commit()
        print('inserted into db')
    except (Exception, psycopg2.DatabaseError) as error:
        print(f'error in inserting {content} into db: {error}')
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def send_content_to_kafka(content):
    try:
        producer = Producer({'bootstrap.servers': KAFKA_LISTENER_INTERNAL})
        content_json = json.dumps(content.__dict__)
        producer.produce(topic=TOPIC_NAME, value=content_json)
        producer.flush()
        print(f'content sent to kafka: {content_json}')
    except Exception as error:
        print(f'error in sending to kafka: {error}')


if __name__ == '__main__':
    create_table()
    while True:

        url = input("enter url (type exit to quit): ")
        if url == 'exit':
            break

        id = int(input("enter id of file: "))
        bucket_name = input("enter your bucket name: ")
        object_name = input("enter your object name: ")
        content = Content(id, url, bucket_name, object_name)
        print(content)
        store_content_to_db(content)
        send_content_to_kafka(content)

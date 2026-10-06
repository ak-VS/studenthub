import os
import mysql.connector

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def get_db_connection():
    config = {
        "host": os.environ.get("DB_HOST", "localhost"),
        "port": int(os.environ.get("DB_PORT", 3306)),
        "user": os.environ.get("DB_USER", "root"),
        "password": os.environ.get("DB_PASSWORD", ""),
        "database": os.environ.get("DB_NAME", "studenthub"),
    }

    if os.environ.get("DB_SSL", "false").lower() == "true":
        config["ssl_ca"] = os.path.join(BASE_DIR, "ca.pem")
        config["ssl_verify_cert"] = True

    return mysql.connector.connect(**config)

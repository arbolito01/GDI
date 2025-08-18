import mysql.connector
from dotenv import load_dotenv
import os

load_dotenv()

db_config = {
    'host': os.getenv('DB_HOST', '127.0.0.1'),
    'user': os.getenv('DB_USER', 'root'),
    'password': os.getenv('DB_PASSWORD', ''),
    'database': os.getenv('DB_DATABASE', 'gestor_instalaciones')
}

def get_db_connection():
    """
    Establece y devuelve una conexión a la base de datos.
    """
    try:
        return mysql.connector.connect(**db_config)
    except mysql.connector.Error as err:
        # Aquí puedes añadir un logger para registrar el error
        print(f"Error al conectar con la base de datos: {err}")
        return None
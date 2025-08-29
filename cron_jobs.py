# cron_jobs.py

import os
import requests
from dotenv import load_dotenv
from database import get_db_connection
from datetime import date, timedelta
import logging

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Cargar variables de entorno
load_dotenv()
ADL_API_URL = os.getenv("ADL_API_URL")

def check_and_cut_unpaid_clients():
    """
    Función que revisa los clientes con pagos vencidos y corta el servicio.
    """
    conexion = get_db_connection()
    if not conexion:
        logging.error("No se pudo conectar a la base de datos de GDI.")
        return

    cursor = conexion.cursor(dictionary=True)
    try:
        # 1. Identificar clientes con pago vencido que aún no están cortados
        sql = "SELECT id_cliente, nombre, onu_sn FROM clientes WHERE estado_pago != 'Cortado' AND fecha_proximo_pago < %s"
        cursor.execute(sql, (date.today(),))
        clientes_vencidos = cursor.fetchall()
        
        if not clientes_vencidos:
            logging.info("No hay clientes con pagos vencidos.")
            return

        for cliente in clientes_vencidos:
            logging.info(f"Cliente {cliente['nombre']} con pago vencido. Iniciando proceso de corte.")
            
            # 2. Llamar a la API de AdL para desactivar el servicio
            if ADL_API_URL:
                payload = {
                    "nombre": cliente['nombre'],
                    "onu_sn": cliente['onu_sn']
                }
                try:
                    response = requests.post(f"{ADL_API_URL}/api/desactivar/", json=payload)
                    response.raise_for_status()
                    logging.info(f"Servicio de {cliente['nombre']} cortado con éxito a través de la API de AdL.")
                    
                    # 3. Actualizar el estado de pago en la base de datos de GDI
                    update_sql = "UPDATE clientes SET estado_pago = 'Cortado' WHERE id_cliente = %s"
                    cursor.execute(update_sql, (cliente['id_cliente'],))
                    conexion.commit()
                    
                except requests.exceptions.RequestException as e:
                    logging.error(f"Error al llamar a la API de AdL para cortar el servicio de {cliente['nombre']}: {e}")

    except Exception as e:
        conexion.rollback()
        logging.error(f"Error inesperado en la lógica de corte automático: {e}")
    finally:
        if conexion and conexion.is_connected():
            cursor.close()
            conexion.close()

if __name__ == '__main__':
    check_and_cut_unpaid_clients()
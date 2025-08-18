import uuid
from datetime import date
import mysql.connector
import os
import requests
import logging
import json
from database import get_db_connection

# Leer variables de entorno para WhatsApp
whatsapp_token = os.getenv("WHATSAPP_TOKEN")
phone_number_id = os.getenv("PHONE_NUMBER_ID")

def send_whatsapp_notification(recipient_number, message_text):
    """
    Función genérica para enviar notificaciones de WhatsApp.
    """
    if not recipient_number or not whatsapp_token or not phone_number_id:
        logging.error("Faltan variables de entorno o número de destinatario para enviar WhatsApp.")
        return False, "Faltan credenciales o número de destinatario."

    headers = {
        "Authorization": f"Bearer {whatsapp_token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient_number,
        "type": "text",
        "text": {
            "body": message_text
        }
    }
    
    try:
        response = requests.post(
            f"https://graph.facebook.com/v15.0/{phone_number_id}/messages",
            json=payload,
            headers=headers
        )
        response.raise_for_status()
        logging.info(f"Mensaje de WhatsApp enviado con éxito a {recipient_number}.")
        return True, "Mensaje enviado con éxito."
    except requests.exceptions.RequestException as e:
        logging.error(f"Error al enviar el mensaje de WhatsApp a {recipient_number}: {e}")
        return False, f"Error en la API de WhatsApp: {e}"

def create_new_installation(
    nombre_instalacion, descripcion, hora_solicitada, tecnico_asignado_id,
    dni_cliente, nombre_cliente, telefono_cliente, referencia_domicilio,
    id_admin, imagen_url="", ubicacion_gps=""
):
    conexion = get_db_connection()
    if not conexion:
        raise Exception("No se pudo conectar a la base de datos.")
    
    cursor = conexion.cursor(dictionary=True)
    try:
        # 1. Buscar o crear el cliente
        cursor.execute("SELECT id_cliente FROM clientes WHERE dni = %s", (dni_cliente,))
        cliente = cursor.fetchone()
        
        id_cliente = None
        if cliente:
            id_cliente = cliente['id_cliente']
        else:
            pppoe_password = uuid.uuid4().hex[:8].upper()
            nombre_formateado = nombre_cliente.upper().replace(' ', '-')
            # Buscar el último número en la base de datos para generar uno nuevo
            cursor.execute("SELECT MAX(SUBSTRING_INDEX(codigo_cliente, '-', 1)) AS ultimo_numero FROM clientes WHERE codigo_cliente LIKE '5%'")
            ultimo_numero_str = cursor.fetchone()['ultimo_numero']
            if ultimo_numero_str and ultimo_numero_str.isdigit():
                nuevo_numero = int(ultimo_numero_str) + 1
            else:
                nuevo_numero = 5000
            codigo_cliente = f"{nuevo_numero}-{nombre_formateado}"

            sql_insert_cliente = """
                INSERT INTO clientes (nombre, telefono, direccion, dni, codigo_cliente, pppoe_password) 
                VALUES (%s, %s, %s, %s, %s, %s)
            """
            valores_cliente = (nombre_cliente, telefono_cliente, referencia_domicilio, dni_cliente, codigo_cliente, pppoe_password)
            cursor.execute(sql_insert_cliente, valores_cliente)
            id_cliente = cursor.lastrowid
        
        # 2. Insertar la instalación
        sql_insert_instalacion = """
            INSERT INTO instalaciones (id_cliente, nombre, descripcion, imagen_url, hora_solicitada, tecnico_asignado, id_instalador, estado)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        valores_instalacion = (
            id_cliente, nombre_instalacion, descripcion, imagen_url, hora_solicitada,
            tecnico_asignado_id, tecnico_asignado_id, "Asignado"
        )
        cursor.execute(sql_insert_instalacion, valores_instalacion)
        id_instalacion_creada = cursor.lastrowid
        
        # 3. Insertar la tarea
        descripcion_tarea = f"Instalación de {nombre_instalacion} para el cliente {nombre_cliente}"
        sql_insert_tarea = """
            INSERT INTO tareas (id_instalacion, id_admin, id_usuario_asignado, tipo_tarea, descripcion, fecha_asignacion, estado)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        valores_tarea = (id_instalacion_creada, id_admin, tecnico_asignado_id, nombre_instalacion, descripcion_tarea, date.today(), "Pendiente")
        cursor.execute(sql_insert_tarea, valores_tarea)
        
        conexion.commit()

        # 4. Enviar notificación al técnico asignado
        cursor.execute("SELECT telefono FROM usuarios WHERE id_usuario = %s", (tecnico_asignado_id,))
        telefono_tecnico = cursor.fetchone()['telefono']
        if telefono_tecnico:
            mensaje = f"¡Hola! Se te ha asignado una nueva tarea: {nombre_instalacion}. Revisa la app para más detalles."
            send_whatsapp_notification(telefono_tecnico, mensaje)

        return True, "Instalación/Solicitud añadida con éxito."

    except mysql.connector.Error as err:
        conexion.rollback()
        return False, f"Error al añadir la instalación/solicitud: {err}"
    except Exception as e:
        conexion.rollback()
        return False, f"Error inesperado: {e}"
    finally:
        if conexion and conexion.is_connected():
            cursor.close()
            conexion.close()
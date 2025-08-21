import os
import requests
import uuid
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import mysql.connector
from werkzeug.utils import secure_filename
from functools import wraps
from datetime import date, datetime
import json
from routeros_api import RouterOsApiPool
import pandas as pd
from io import BytesIO
from flask import send_file
import csv
from io import StringIO
import logging

# Se importa la función del servicio para la notificación por WhatsApp
from database import get_db_connection
from services import create_new_installation, send_whatsapp_notification


# Configuración del logger
logging.basicConfig(filename='app.log', level=logging.INFO, format='%(asctime)s %(levelname)s:%(message)s')

# Cargar las variables de entorno desde el archivo .env
load_dotenv()
# Variable global para almacenar los datos importados
imported_clients_data = []

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'tu_clave_secreta_aqui')

# --- Configuración de Archivos ---
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# --- Lectura de variables de entorno ---
whatsapp_token = os.getenv("WHATSAPP_TOKEN")
phone_number_id = os.getenv("PHONE_NUMBER_ID")
router_ip = os.getenv("ROUTER_IP")
router_port = int(os.getenv("ROUTER_PORT", '8728'))
router_user = os.getenv("ROUTER_USER")
router_password = os.getenv("ROUTER_PASSWORD")
maps_api_key = os.getenv("Maps_API_KEY")
reniec_api_key = os.getenv("RENIEC_API_KEY")
reniec_api_endpoint = os.getenv("RENIEC_API_ENDPOINT")


# --- Funciones Auxiliares ---
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- Decoradores para Control de Acceso ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'id_usuario' not in session:
            flash("Debes iniciar sesión para acceder a esta página.", "error")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'id_usuario' not in session or not session.get('es_admin'):
            flash("No tienes permisos para acceder a esta página.", "error")
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

def instalador_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'id_usuario' not in session or session.get('es_admin'):
            flash("No tienes permisos para acceder a esta página.", "error")
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# Decorador para restringir el acceso solo a clientes logueados
def cliente_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'id_cliente_usuario' not in session:
            flash("Por favor, inicia sesión para acceder a esta página.", "error")
            return redirect(url_for('cliente_login'))
        return f(*args, **kwargs)
    return decorated_function

# --- IMPORTADOR JSON ---
@app.template_filter('from_json')
def from_json_filter(value):
    return json.loads(value)

# --- Rutas de Autenticación ---
@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        nombre = request.form['nombre']
        email = request.form['email']
        password = request.form['password']
        direccion = request.form.get('direccion')
        telefono = request.form.get('telefono')
        dni = request.form.get('dni')
        hashed_password = generate_password_hash(password)

        try:
            conexion = get_db_connection()
            cursor = conexion.cursor()
            sql = "INSERT INTO usuarios (nombre, email, password, es_admin, direccion, telefono, dni) VALUES (%s, %s, %s, 0, %s, %s, %s)"
            valores = (nombre, email, hashed_password, direccion, telefono, dni)
            cursor.execute(sql, valores)
            conexion.commit()
            flash("Registro exitoso. ¡Inicia sesión ahora!", "success")
            return redirect(url_for('login'))
        except mysql.connector.Error as err:
            flash(f"Error al registrar usuario: {err}", "error")
            return redirect(url_for('registro'))
        finally:
            if 'conexion' in locals() and conexion.is_connected():
                cursor.close()
                conexion.close()
    return render_template('registro.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        conexion = get_db_connection()
        cursor = conexion.cursor(dictionary=True)
        sql = "SELECT * FROM usuarios WHERE email = %s"
        cursor.execute(sql, (email,))
        usuario = cursor.fetchone()
        cursor.close()
        conexion.close()

        if usuario and check_password_hash(usuario['password'], password):
            session['id_usuario'] = usuario['id_usuario']
            session['nombre'] = usuario['nombre']
            session['es_admin'] = usuario['es_admin']
            flash(f"¡Bienvenido, {usuario['nombre']}!", "success")
            return redirect(url_for('index'))
        else:
            flash('Credenciales incorrectas.', "error")
            return render_template('login.html')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    session.pop('id_usuario', None)
    session.pop('nombre', None)
    session.pop('es_admin', None) 
    flash("Has cerrado sesión correctamente.", "success")
    return redirect(url_for('login'))

@app.route('/cliente/registro', methods=['GET', 'POST'])
def cliente_registro():
    if request.method == 'POST':
        dni = request.form['dni']
        email = request.form['email']
        password = request.form['password']
        hashed_password = generate_password_hash(password)

        conexion = get_db_connection()
        cursor = conexion.cursor(dictionary=True)
        
        try:
            # 1. Verificar si el DNI existe en la tabla de clientes
            cursor.execute("SELECT id_cliente FROM clientes WHERE dni = %s", (dni,))
            cliente = cursor.fetchone()
            if not cliente:
                flash("El DNI no está registrado en nuestra base de datos. Por favor, contacte a soporte.", "error")
                return redirect(url_for('cliente_registro'))

            id_cliente = cliente['id_cliente']

            # 2. Verificar si ya existe una cuenta de usuario con ese email
            cursor.execute("SELECT id_cliente_usuario FROM clientes_usuarios WHERE email = %s", (email,))
            if cursor.fetchone():
                flash("Ya existe una cuenta con este correo electrónico. Por favor, inicie sesión.", "error")
                return redirect(url_for('cliente_registro'))

            # 3. Crear el nuevo usuario
            sql = "INSERT INTO clientes_usuarios (id_cliente, email, password) VALUES (%s, %s, %s)"
            cursor.execute(sql, (id_cliente, email, hashed_password))
            conexion.commit()
            
            flash("Registro exitoso. ¡Inicie sesión ahora!", "success")
            return redirect(url_for('cliente_login'))
        
        except Exception as e:
            conexion.rollback()
            logging.error(f"Error en el registro de cliente: {e}")
            flash("Ocurrió un error al registrarse. Por favor, inténtelo de nuevo.", "error")
            return redirect(url_for('cliente_registro'))
        finally:
            cursor.close()
            conexion.close()
            
    return render_template('cliente_registro.html')

@app.route('/cliente/login', methods=['GET', 'POST'])
def cliente_login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        conexion = get_db_connection()
        cursor = conexion.cursor(dictionary=True)
        
        try:
            sql = "SELECT cu.id_cliente_usuario, cu.password, c.nombre FROM clientes_usuarios cu JOIN clientes c ON cu.id_cliente = c.id_cliente WHERE cu.email = %s"
            cursor.execute(sql, (email,))
            usuario_cliente = cursor.fetchone()
            
            if usuario_cliente and check_password_hash(usuario_cliente['password'], password):
                session['id_cliente_usuario'] = usuario_cliente['id_cliente_usuario']
                session['nombre_cliente'] = usuario_cliente['nombre']
                flash(f"¡Bienvenido, {usuario_cliente['nombre']}!", "success")
                return redirect(url_for('cliente_dashboard'))
            else:
                flash('Credenciales incorrectas.', "error")
                return render_template('cliente_login.html')
        except Exception as e:
            logging.error(f"Error en el login de cliente: {e}")
            flash("Ocurrió un error. Por favor, inténtelo de nuevo.", "error")
            return redirect(url_for('cliente_login'))
        finally:
            cursor.close()
            conexion.close()
            
    return render_template('cliente_login.html')

@app.route('/cliente/logout')
def cliente_logout():
    session.pop('id_cliente_usuario', None)
    session.pop('nombre_cliente', None)
    flash("Has cerrado sesión correctamente.", "success")
    return redirect(url_for('cliente_login'))

# --- Rutas del Panel de Administración ---
@app.route('/admin')
@admin_required
def admin():
    conexion = get_db_connection()
    cursor = conexion.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT i.*, c.nombre AS nombre_cliente, c.telefono AS telefono_cliente, c.dni AS dni_cliente,
                 MAX(t.estado) AS estado_tarea, MAX(t.id_usuario_asignado) AS id_usuario_asignado,
                 MAX(u.nombre) AS tecnico_asignado, MAX(t.fecha_asignacion) AS fecha_asignacion
        FROM instalaciones i
        JOIN clientes c ON i.id_cliente = c.id_cliente
        LEFT JOIN tareas t ON i.id_instalacion = t.id_instalacion
        LEFT JOIN usuarios u ON t.id_usuario_asignado = u.id_usuario
        GROUP BY i.id_instalacion
        ORDER BY fecha_asignacion DESC
    """)
    instalaciones = cursor.fetchall()
    
    cursor.execute("SELECT r.*, u.nombre AS nombre_usuario, i.nombre AS nombre_instalacion FROM reservas r JOIN usuarios u ON r.id_usuario = u.id_usuario JOIN instalaciones i ON r.id_instalacion = i.id_instalacion ORDER BY r.fecha DESC")
    reservas = cursor.fetchall()
    cursor.execute("SELECT * FROM usuarios")
    usuarios = cursor.fetchall()
    cursor.execute("""
        SELECT t.*, i.nombre AS nombre_instalacion, u.nombre AS nombre_usuario_asignado, a.nombre AS nombre_admin
        FROM tareas t
        JOIN instalaciones i ON t.id_instalacion = i.id_instalacion
        JOIN usuarios u ON t.id_usuario_asignado = u.id_usuario
        JOIN usuarios a ON t.id_admin = a.id_usuario
        ORDER BY t.fecha_asignacion DESC
    """)
    tareas = cursor.fetchall()
    cursor.execute("SELECT id_usuario, nombre FROM usuarios WHERE es_admin = 0")
    tecnicos = cursor.fetchall()
    cursor.close()
    conexion.close()

    return render_template('admin.html', instalaciones=instalaciones, reservas=reservas, usuarios=usuarios, tareas=tareas, tecnicos=tecnicos)

@app.route('/nueva-instalacion', methods=['GET', 'POST'])
@login_required
@admin_required
def nueva_instalacion():
    conexion = get_db_connection()
    cursor = conexion.cursor(dictionary=True)

    cursor.execute("SELECT id_usuario, nombre FROM usuarios WHERE es_admin = 0")
    tecnicos = cursor.fetchall()

# Consulta para obtener los tipos de instalación desde la tabla `tipos_instalacion`
    cursor.execute("SELECT nombre FROM tipos_instalacion ORDER BY nombre")
    tipos_instalacion = [row['nombre'] for row in cursor.fetchall()]
        # Consulta para obtener los planes de la tabla `clientes`
    cursor.execute("SELECT DISTINCT plan FROM clientes WHERE plan IS NOT NULL ORDER BY plan")
    planes_clientes = [row['plan'] for row in cursor.fetchall()]
        # Combina ambas listas para ofrecer una selección completa
    todos_los_planes = sorted(list(set(tipos_instalacion + planes_clientes)))

    # Nueva lógica para obtener las zonas
    conexion_zonas = get_db_connection()
    cursor_zonas = conexion_zonas.cursor(dictionary=True)
    cursor_zonas.execute("SELECT id_zona, nombre FROM zonas ORDER BY nombre")
    zonas = cursor_zonas.fetchall()
    cursor_zonas.close()
    conexion_zonas.close()


    if request.method == 'POST':
        nombre_instalacion = request.form.get('nombre')
        descripcion = request.form.get('descripcion')
        hora_solicitada = request.form.get('hora_solicitada')
        tecnico_asignado_id = request.form.get('tecnico_asignado')
        dni_cliente = request.form.get('dni')
        nombre_cliente = request.form.get('nombre_cliente')
        telefono_cliente = request.form.get('telefono_cliente')
        referencia = request.form.get('referencia')
        latitud = request.form.get('latitud', '')
        longitud = request.form.get('longitud', '')
        ubicacion_gps = f"{latitud},{longitud}" if latitud and longitud else ""
        id_zona = request.form.get('id_zona')
        
        imagen_url = ""
        if 'imagen' in request.files and request.files['imagen'].filename != '':
            file = request.files['imagen']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                full_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(full_path)
                imagen_url = os.path.join('uploads', filename).replace('\\', '/')

        success, message = create_new_installation(
            nombre_instalacion, id_zona, hora_solicitada, tecnico_asignado_id,
            dni_cliente, nombre_cliente, telefono_cliente, referencia,
            session.get('id_usuario'), imagen_url, ubicacion_gps
        )

        if success:
            flash(message, "success")
            return redirect(url_for('admin'))
        else:
            flash(message, "error")
            logging.error(message)
            return redirect(url_for('nueva_instalacion'))

    return render_template('nueva_instalacion.html', tecnicos=tecnicos, tipos_instalacion=todos_los_planes, maps_api_key=maps_api_key, zonas=zonas)

@app.route('/editar_instalacion/<int:id>', methods=['GET', 'POST'])
@admin_required
def editar_instalacion(id):
    conexion = get_db_connection()
    cursor = conexion.cursor(dictionary=True)
    
    if request.method == 'POST':
        nombre = request.form['nombre']
        descripcion = request.form['descripcion']
        imagen_url = request.form.get('imagen_actual', '')
        
        if 'imagen' in request.files and request.files['imagen'].filename != '':
            file = request.files['imagen']
            if file and allowed_file(file.filename):
                if imagen_url and os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], os.path.basename(imagen_url))):
                    os.remove(os.path.join(app.config['UPLOAD_FOLDER'], os.path.basename(imagen_url)))
                
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                imagen_url = os.path.join('uploads', filename).replace('\\', '/')
        
        cursor.execute("UPDATE instalaciones SET nombre = %s, descripcion = %s, imagen_url = %s WHERE id_instalacion = %s", (nombre, descripcion, imagen_url, id))
        conexion.commit()
        conexion.close()
        flash("Instalación actualizada con éxito.", "success")
        return redirect(url_for('admin'))

    cursor.execute("SELECT * FROM instalaciones WHERE id_instalacion = %s", (id,))
    instalacion = cursor.fetchone()
    conexion.close()
    if not instalacion:
        flash("Instalación no encontrada.", "error")
        return redirect(url_for('admin'))
        
    return render_template('editar_instalacion.html', instalacion=instalacion)

@app.route('/eliminar_instalacion/<int:id>', methods=['POST'])
@admin_required
def eliminar_instalacion(id):
    try:
        conexion = get_db_connection()
        cursor = conexion.cursor(dictionary=True)
        
        cursor.execute("DELETE FROM solicitudes_traspaso WHERE id_tarea IN (SELECT id_tarea FROM tareas WHERE id_instalacion = %s)", (id,))
        cursor.execute("DELETE FROM reservas WHERE id_instalacion = %s", (id,))
        cursor.execute("DELETE FROM tareas WHERE id_instalacion = %s", (id,))
        
        cursor.execute("SELECT imagen_url FROM instalaciones WHERE id_instalacion = %s", (id,))
        instalacion = cursor.fetchone()
        if instalacion and instalacion['imagen_url'] and os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], os.path.basename(instalacion['imagen_url']))):
            os.remove(os.path.join(app.config['UPLOAD_FOLDER'], os.path.basename(instalacion['imagen_url'])))
        cursor.execute("DELETE FROM instalaciones WHERE id_instalacion = %s", (id,))
        conexion.commit()
        flash("Instalación eliminada con éxito.", "success")
        return redirect(url_for('admin'))
    except mysql.connector.Error as err:
        flash(f"Error al eliminar la instalación: {err}", "error")
        return redirect(url_for('admin'))
    finally:
        if 'conexion' in locals() and conexion.is_connected():
            cursor.close()
            conexion.close()
@app.route('/editar_usuario/<int:id>', methods=['GET', 'POST'])
@admin_required
def editar_usuario(id):
    conexion = get_db_connection()
    cursor = conexion.cursor(dictionary=True)
    usuario = None
    try:
        cursor.execute("SELECT * FROM usuarios WHERE id_usuario = %s", (id,))
        usuario = cursor.fetchone()
        if not usuario:
            flash("Usuario no encontrado.", "error")
            return redirect(url_for('admin'))

        if request.method == 'POST':
            nombre = request.form['nombre']
            email = request.form['email']
            password = request.form['password']
            
            sql_update = "UPDATE usuarios SET nombre = %s, email = %s WHERE id_usuario = %s"
            valores = (nombre, email, id)

            if password:
                hashed_password = generate_password_hash(password)
                sql_update = "UPDATE usuarios SET nombre = %s, email = %s, password = %s WHERE id_usuario = %s"
                valores = (nombre, email, hashed_password, id)
            
            cursor.execute(sql_update, valores)
            conexion.commit()
            flash('Usuario actualizado con éxito', 'success')
            return redirect(url_for('admin'))
    except mysql.connector.Error as err:
        flash(f"Error al editar el usuario: {err}", "error")
        return redirect(url_for('admin'))
    finally:
        if 'conexion' in locals() and conexion.is_connected():
            cursor.close()
            conexion.close()
    
    return render_template('editar_usuario.html', usuario=usuario)

@app.route('/eliminar_usuario/<int:id>', methods=['POST'])
@admin_required
def eliminar_usuario(id):
    if id == session['id_usuario']:
        flash("No puedes eliminar tu propio usuario.", "error")
        return redirect(url_for('admin'))
        
    try:
        conexion = get_db_connection()
        cursor = conexion.cursor()
        cursor.execute("DELETE FROM tareas WHERE id_usuario_asignado = %s", (id,))
        cursor.execute("DELETE FROM usuarios WHERE id_usuario = %s", (id,))
        conexion.commit()
        flash("Usuario eliminado con éxito.", "success")
    except mysql.connector.Error as err:
        flash(f"Error al eliminar el usuario: {err}", "error")
    finally:
        if 'conexion' in locals() and conexion.is_connected():
            cursor.close()
            conexion.close()
    
    return redirect(url_for('admin'))

@app.route('/toggle_admin/<int:id>', methods=['POST'])
@admin_required
def toggle_admin(id):
    try:
        conexion = get_db_connection()
        cursor = conexion.cursor()
        cursor.execute("SELECT es_admin FROM usuarios WHERE id_usuario = %s", (id,))
        usuario = cursor.fetchone()
        if usuario:
            es_admin_actual = usuario[0]
            nuevo_estado = not es_admin_actual
            sql = "UPDATE usuarios SET es_admin = %s WHERE id_usuario = %s"
            cursor.execute(sql, (nuevo_estado, id))
            conexion.commit()
            flash("Permisos de administrador actualizados con éxito.", "success")
        else:
            flash("Usuario no encontrado.", "error")
    except mysql.connector.Error as err:
        flash(f"Error al actualizar permisos: {err}", "error")
    finally:
        if 'conexion' in locals() and conexion.is_connected():
            cursor.close()
            conexion.close()
    return redirect(url_for('admin'))

@app.route('/asignar_tarea', methods=['GET', 'POST'])
@admin_required
def asignar_tarea():
    conexion = get_db_connection()
    cursor = conexion.cursor(dictionary=True)
    if request.method == 'POST':
        id_instalacion = request.form['id_instalacion']
        id_usuario_asignado = request.form['id_usuario_asignado']
        tipo_tarea = request.form['tipo_tarea']
        descripcion = request.form['descripcion']
        fecha_asignacion = date.today()
        id_admin = session['id_usuario']
        estado = "Pendiente"
        try:
            cursor.execute("SELECT nombre FROM usuarios WHERE id_usuario = %s", (id_usuario_asignado,))
            nombre_tecnico = cursor.fetchone()['nombre']
            sql_insert_tarea = "INSERT INTO tareas (id_instalacion, id_admin, id_usuario_asignado, tipo_tarea, descripcion, fecha_asignacion, estado) VALUES (%s, %s, %s, %s, %s, %s, %s)"
            valores_tarea = (id_instalacion, id_admin, id_usuario_asignado, tipo_tarea, descripcion, fecha_asignacion, estado)
            cursor.execute(sql_insert_tarea, valores_tarea)
            sql_update_instalacion = "UPDATE instalaciones SET tecnico_asignado = %s, estado = %s, id_instalador = %s WHERE id_instalacion = %s"
            valores_update = (nombre_tecnico, 'Asignado', id_usuario_asignado, id_instalacion)
            cursor.execute(sql_update_instalacion, valores_update)
            conexion.commit()
            flash("Tarea asignada con éxito.", "success")
            return redirect(url_for('admin'))
        except mysql.connector.Error as err:
            flash(f"Error al asignar la tarea: {err}", "error")
        finally:
            if 'conexion' in locals() and conexion.is_connected():
                cursor.close()
                conexion.close()
    
    cursor.execute("SELECT id_instalacion, nombre FROM instalaciones WHERE estado = 'Pendiente'")
    instalaciones = cursor.fetchall()
    cursor.execute("SELECT id_usuario, nombre FROM usuarios WHERE es_admin = 0")
    usuarios_no_admin = cursor.fetchall()
    cursor.close()
    conexion.close()
    return render_template('asignar_tarea.html', instalaciones=instalaciones, usuarios_no_admin=usuarios_no_admin)

# --- Rutas de Instalador ---
@app.route('/')
@login_required
def index():
    es_admin = session.get('es_admin', False)
    if es_admin:
        return redirect(url_for('admin'))
    
    id_usuario = session.get('id_usuario')
    conexion = get_db_connection()
    cursor = conexion.cursor(dictionary=True)
    sql = """
        SELECT t.*, i.nombre as nombre_instalacion, c.nombre as nombre_cliente, c.telefono as telefono_cliente
        FROM tareas t
        JOIN instalaciones i ON t.id_instalacion = i.id_instalacion
        JOIN clientes c ON i.id_cliente = c.id_cliente
        WHERE t.id_usuario_asignado = %s AND t.estado IN ('Pendiente', 'Disponible')
        ORDER BY t.fecha_asignacion DESC
    """
    cursor.execute(sql, (id_usuario,))
    tareas_asignadas = cursor.fetchall()
    cursor.close()
    conexion.close()
    
    return render_template('tareas_asignadas.html', tareas=tareas_asignadas)

# app.py

@app.route('/mis_tareas')
@login_required
@instalador_required
def mis_tareas():
    id_usuario = session['id_usuario']
    conexion = get_db_connection()
    cursor = conexion.cursor(dictionary=True)

    # Consulta para obtener solo las tareas pendientes
    cursor.execute("""
        SELECT t.*, i.nombre AS nombre_instalacion, c.nombre as nombre_cliente, c.telefono as telefono_cliente
        FROM tareas t
        JOIN instalaciones i ON t.id_instalacion = i.id_instalacion
        JOIN clientes c ON i.id_cliente = c.id_cliente
        WHERE t.id_usuario_asignado = %s AND t.estado = 'Pendiente'
        ORDER BY t.fecha_asignacion DESC
    """, (id_usuario,))
    tareas_pendientes = cursor.fetchall()
    
    # Lógica para obtener otros instaladores y solicitudes de traspaso (código existente)
    cursor.execute("SELECT id_usuario, nombre FROM usuarios WHERE id_usuario != %s AND es_admin = 0", (id_usuario,))
    otros_instaladores = cursor.fetchall()

    cursor.execute("""
        SELECT st.id_solicitud, t.id_tarea, t.tipo_tarea, t.descripcion, u.nombre as solicitante
        FROM solicitudes_traspaso st
        JOIN tareas t ON st.id_tarea = t.id_tarea
        JOIN usuarios u ON st.id_solicitante = u.id_usuario
        WHERE st.id_receptor = %s AND st.estado = 'Pendiente'
    """, (id_usuario,))
    solicitudes_recibidas = cursor.fetchall()
    
    cursor.close()
    conexion.close()

    # Se pasan las variables correctas a la plantilla
    return render_template('mis_tareas.html', 
        tareas_pendientes=tareas_pendientes,
        solicitudes_recibidas=solicitudes_recibidas,
        otros_instaladores=otros_instaladores
    )


@app.route('/completar_instalacion/<int:instalacion_id>', methods=['GET', 'POST'])
@login_required
@instalador_required
def completar_instalacion(instalacion_id):
    conexion = get_db_connection()
    cursor = conexion.cursor(dictionary=True)
    
    sql_tarea = """
        SELECT i.*, t.id_tarea, t.tipo_tarea, t.descripcion as descripcion_tarea, c.telefono as telefono_cliente, c.nombre as nombre_cliente
        FROM instalaciones i
        JOIN tareas t ON i.id_instalacion = t.id_instalacion
        JOIN clientes c ON i.id_cliente = c.id_cliente
        WHERE i.id_instalacion = %s AND t.id_usuario_asignado = %s AND t.estado = 'Pendiente'
    """
    cursor.execute(sql_tarea, (instalacion_id, session.get('id_usuario')))
    tarea = cursor.fetchone()
    
    if not tarea:
        flash("La tarea no existe, ya ha sido completada o no te ha sido asignada.", "error")
        cursor.close()
        conexion.close()
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        try:
            id_equipo_instalado = request.form.get('id_equipo_instalado')
            if not id_equipo_instalado:
                flash("Debes seleccionar un equipo del inventario.", "error")
                return redirect(url_for('completar_instalacion', instalacion_id=instalacion_id))

            referencia = request.form.get('referencia')
            metodo_pago = request.form.get('metodo_pago')
            numero_transaccion = request.form.get('numero_transaccion')
            descripcion_final = request.form.get('descripcion_final')
            latitud = request.form.get('latitud')
            longitud = request.form.get('longitud')
            ubicacion_gps_final = f"{latitud},{longitud}"
            
            if not latitud or not longitud:
                flash("La ubicación GPS es obligatoria.", "error")
                return redirect(url_for('completar_instalacion', instalacion_id=instalacion_id))

            fotos = request.files.getlist('fotos[]')
            fotos_adjuntas_urls = []
            if not fotos or not fotos[0].filename:
                flash("Debes adjuntar al menos una foto de la instalación.", "error")
                return redirect(url_for('completar_instalacion', instalacion_id=instalacion_id))

            for foto in fotos:
                if foto and allowed_file(foto.filename):
                    filename = secure_filename(f"{uuid.uuid4().hex}_{foto.filename}")
                    foto_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    foto.save(foto_path)
                    fotos_adjuntas_urls.append(os.path.join('uploads', filename).replace('\\', '/'))
                else:
                    flash("Se subió un archivo no permitido. Solo se aceptan imágenes.", "error")
                    return redirect(url_for('completar_instalacion', instalacion_id=instalacion_id))
            
            foto_adjunta_url_final = json.dumps(fotos_adjuntas_urls)
            fecha_completado = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            sql_update_instalacion = """
                UPDATE instalaciones SET 
                descripcion_final = %s, 
                ubicacion_gps_final = %s, 
                foto_adjunta = %s, 
                fecha_completado = %s,
                metodo_pago = %s,
                numero_transaccion = %s,
                id_equipo_instalado = %s,
                estado = 'Completado'
                WHERE id_instalacion = %s
            """
            valores_update_instalacion = (
                descripcion_final, ubicacion_gps_final, foto_adjunta_url_final, fecha_completado,
                metodo_pago, numero_transaccion, id_equipo_instalado, instalacion_id
            )
            cursor.execute(sql_update_instalacion, valores_update_instalacion)

            cursor.execute("UPDATE inventario SET estado = 'Instalado' WHERE id_equipo = %s", (id_equipo_instalado,))
            cursor.execute("UPDATE inventario SET estado = 'Instalado', fecha_instalacion = %s WHERE id_equipo = %s", (fecha_completado, id_equipo_instalado))

            sql_update_tarea = "UPDATE tareas SET estado = 'Completada' WHERE id_tarea = %s"
            cursor.execute(sql_update_tarea, (tarea['id_tarea'],))
            
            conexion.commit()
            
            recipient_number = tarea.get('telefono_cliente')
            if recipient_number:
                message_text = f"¡Hola {tarea['nombre_cliente']}! Tu instalación de {tarea['nombre']} ha sido completada con éxito. Fecha de finalización: {fecha_completado}."
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
                        f"[https://graph.facebook.com/v15.0/](https://graph.facebook.com/v15.0/){phone_number_id}/messages",
                        json=payload,
                        headers=headers
                    )
                    response.raise_for_status()
                    logging.info("Mensaje de WhatsApp enviado con éxito.")
                except requests.exceptions.RequestException as e:
                    logging.error(f"Error al enviar el mensaje de WhatsApp: {e}")
                except Exception as e:
                    logging.error(f"Error inesperado al enviar WhatsApp: {e}")
            else:
                logging.warning("No se encontró número de teléfono para enviar el mensaje de WhatsApp.")

            flash('La tarea se ha completado con éxito.', "success")
            return redirect(url_for('mis_tareas_completadas'))
        
        except Exception as e:
            flash(f'Error al completar la tarea: {e}', "error")
            logging.error(f"Error en completar_instalacion: {e}")
            return redirect(url_for('completar_instalacion', instalacion_id=instalacion_id))
        finally:
            if 'conexion' in locals() and conexion.is_connected():
                cursor.close()
                conexion.close()
    
    cursor.execute("""
        SELECT * FROM inventario WHERE estado = 'Disponible'
    """)
    inventario_disponible = cursor.fetchall()
    
    cursor.close()
    conexion.close()
    return render_template('finalizar_tarea.html', tarea=tarea, maps_api_key=os.getenv("Maps_API_KEY"), inventario_disponible=inventario_disponible)

@app.route('/mis_tareas_completadas')
@login_required
@instalador_required
def mis_tareas_completadas():
    id_usuario = session['id_usuario']
    conexion = get_db_connection()
    cursor = conexion.cursor(dictionary=True)
    cursor.execute("""
        SELECT t.*, i.nombre AS nombre_instalacion
        FROM tareas t
        JOIN instalaciones i ON t.id_instalacion = i.id_instalacion
        WHERE t.id_usuario_asignado = %s AND t.estado = 'Completada'
        ORDER BY t.fecha_asignacion DESC
    """, (id_usuario,))
    todas_mis_tareas = cursor.fetchall()
    cursor.close()
    conexion.close()
    return render_template('mis_tareas_completadas.html', todas_mis_tareas=todas_mis_tareas)

def get_mikrotik_users():
    users = []
    
    router_ip_env = os.getenv("ROUTER_IP")
    router_port_env = int(os.getenv("ROUTER_PORT", '8728'))
    router_user_env = os.getenv("ROUTER_USER")
    router_password_env = os.getenv("ROUTER_PASSWORD")
    
    api = None
    api_pool = None
    try:
        api_pool = RouterOsApiPool(router_ip_env, router_user_env, router_password_env, port=router_port_env)
        api = api_pool.get_api()
        pppoe_secrets = api.talk('/ppp/secret/print')
            
        for secret in pppoe_secrets:
            users.append({
                'username': secret.get('name', ''),
                'service': secret.get('service', ''),
                'phone': secret.get('comment', 'No especificado')
            })
        
        return users
    except Exception as e:
        logging.error(f"Error al conectar con MikroTik: {e}")
        return []
    finally:
        if api and api_pool:
            api_pool.return_api(api)


@app.route('/api/mikrotik_users', methods=['GET'])
@admin_required
def api_mikrotik_users():
    query = request.args.get('q', '')
    usuarios_mikrotik = get_mikrotik_users()
    
    if query:
        filtered_users = [user for user in usuarios_mikrotik if query.lower() in user['username'].lower()]
        return jsonify(filtered_users)
        
    return jsonify(usuarios_mikrotik)


@app.route('/importar_clientes', methods=['GET', 'POST'])
@admin_required
def importar_clientes():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No se seleccionó ningún archivo', 'error')
            return redirect(request.url)
        file = request.files['file']
        if file.filename == '':
            flash('No se seleccionó ningún archivo', 'error')
            return redirect(request.url)
        if file and file.filename.endswith('.csv'):
            try:
                conexion = get_db_connection()
                cursor = conexion.cursor()
                stream = StringIO(file.stream.read().decode("UTF8"), newline=None)
                reader = csv.reader(stream)
                header = next(reader)
                
                try:
                    cliente_idx = header.index('CLIENTE')
                    dni_idx = header.index('DNI')
                    direccion_idx = header.index('DIRECCION')
                    telefono_idx = header.index('TELEFONO')
                    plan_idx = header.index('PLAN')
                except ValueError as e:
                    flash(f'Error: El archivo CSV no tiene las columnas esperadas: {e}', "error")
                    return redirect(request.url)

                for row in reader:
                    dni_value = row[dni_idx] if row[dni_idx] else None
                    
                    if dni_value:
                        cursor.execute("SELECT dni FROM clientes WHERE dni = %s", (dni_value,))
                        if cursor.fetchone():
                            logging.warning(f"DNI duplicado detectado y omitido: {dni_value}")
                            continue

                    sql = "INSERT INTO clientes (nombre, dni, direccion, telefono, plan) VALUES (%s, %s, %s, %s, %s)"
                    valores = (row[cliente_idx], dni_value, row[direccion_idx], row[telefono_idx], row[plan_idx])
                    cursor.execute(sql, valores)
                
                conexion.commit()
                flash("Clientes importados con éxito desde el archivo CSV a la base de datos.", "success")
                return redirect(url_for('reparacion_migracion'))
            except mysql.connector.Error as err:
                flash(f"Error al importar clientes: {err}", "error")
            finally:
                if 'conexion' in locals() and conexion.is_connected():
                    cursor.close()
                    conexion.close()
        else:
            flash('Tipo de archivo no permitido. Por favor, sube un archivo CSV.', 'error')
            return redirect(request.url)
    
    return render_template('importar_clientes.html')


@app.route('/api/clientes', methods=['GET'])
def api_clientes_search():
    query = request.args.get('q', '').lower()
    conexion = get_db_connection()
    cursor = conexion.cursor(dictionary=True)
    
    sql = "SELECT nombre, plan as service, telefono as phone, dni FROM clientes WHERE lower(nombre) LIKE %s OR lower(telefono) LIKE %s OR lower(dni) LIKE %s ORDER BY nombre"
    search_term = f"%{query}%"
    cursor.execute(sql, (search_term, search_term, search_term))
    clientes = cursor.fetchall()
    
    cursor.close()
    conexion.close()
    return jsonify(clientes)

@app.route('/reparacion_migracion', methods=['GET', 'POST'])
@admin_required
def reparacion_migracion():
    conexion = get_db_connection()
    if not conexion:
        flash("Error al conectar con la base de datos.", "error")
        return render_template('reparacion_migracion.html', usuarios_no_admin=[])
    
    cursor = conexion.cursor(dictionary=True)
    
    # Obtener usuarios no administradores para el formulario GET
    cursor.execute("SELECT id_usuario, nombre FROM usuarios WHERE es_admin = 0")
    usuarios_no_admin = cursor.fetchall()

    if request.method == 'POST':
        nombre_cliente = request.form.get('nombre_cliente')
        tipo_servicio = request.form.get('tipo_servicio')
        telefono_cliente = request.form.get('telefono_cliente')
        tipo_tarea = request.form.get('tipo_tarea')
        id_usuario_asignado = request.form.get('id_usuario_asignado')
        descripcion_tarea = request.form.get('descripcion')
        
        try:
            # 1. Buscar o crear el cliente
            cursor.execute("SELECT id_cliente FROM clientes WHERE nombre = %s AND telefono = %s", (nombre_cliente, telefono_cliente))
            cliente = cursor.fetchone()
            
            id_cliente = None
            if cliente:
                id_cliente = cliente['id_cliente']
            else:
                # Si el cliente no existe, se crea uno nuevo con datos básicos.
                sql_insert_cliente = """
                    INSERT INTO clientes (nombre, telefono, plan) 
                    VALUES (%s, %s, %s)
                """
                valores_cliente = (nombre_cliente, telefono_cliente, tipo_servicio)
                cursor.execute(sql_insert_cliente, valores_cliente)
                id_cliente = cursor.lastrowid
            
            # 2. Insertar la instalación (Ahora solo con los campos que existen en la tabla)
            sql_insert_instalacion = """
                INSERT INTO instalaciones (id_cliente, nombre, estado, id_instalador)
                VALUES (%s, %s, %s, %s)
            """
            valores_instalacion = (id_cliente, f"{tipo_tarea} - {nombre_cliente}", 'Pendiente', id_usuario_asignado)
            cursor.execute(sql_insert_instalacion, valores_instalacion)
            id_instalacion_creada = cursor.lastrowid
            
            # 3. Insertar la tarea (se mantiene el campo de descripción)
            sql_insert_tarea = """
                INSERT INTO tareas (id_instalacion, id_admin, id_usuario_asignado, tipo_tarea, descripcion, fecha_asignacion, estado)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """
            valores_tarea = (id_instalacion_creada, session.get('id_usuario'), id_usuario_asignado, tipo_tarea, descripcion_tarea, date.today(), 'Pendiente')
            cursor.execute(sql_insert_tarea, valores_tarea)
            
            conexion.commit()
            flash(f"Tarea de {tipo_tarea} asignada con éxito a un técnico.", "success")
            return redirect(url_for('admin'))
        except mysql.connector.Error as err:
            conexion.rollback()
            flash(f"Error al asignar la tarea: {err}", "error")
            logging.error(f"Error en reparacion_migracion: {err}")
        finally:
            if conexion and conexion.is_connected():
                cursor.close()
                conexion.close()
    
    # Renderizar la plantilla para la solicitud GET
    return render_template('reparacion_migracion.html', usuarios_no_admin=usuarios_no_admin)


@app.route('/instalacion/<int:id>')
@login_required
def detalle_instalacion(id):
    conexion = get_db_connection()
    cursor = conexion.cursor(dictionary=True)
    cursor.execute("SELECT * FROM instalaciones WHERE id_instalacion = %s", (id,))
    instalacion = cursor.fetchone()
    if not instalacion:
        cursor.close()
        conexion.close()
        flash("Instalación no encontrada.", "error")
        return redirect(url_for('index'))
    sql_reservas = "SELECT r.*, u.nombre AS nombre_cliente FROM reservas r JOIN usuarios u ON r.id_usuario = u.id_usuario WHERE r.id_instalacion = %s ORDER BY r.fecha, r.hora_inicio"
    cursor.execute(sql_reservas, (id,))
    reservas = cursor.fetchall()
    cursor.close()
    conexion.close()
    return render_template('detalle_instalacion.html', instalacion=instalacion, reservas=reservas)

@app.route('/reservar', methods=['POST'])
@login_required
def reservar():
    id_instalacion = request.form['id_instalacion']
    id_usuario = session['id_usuario']
    fecha = request.form['fecha']
    hora_inicio = request.form['hora_inicio']
    hora_fin = request.form['hora_fin']
    try:
        conexion = get_db_connection()
        cursor = conexion.cursor(dictionary=True) 
        sql_verificacion = """
            SELECT COUNT(*) AS total FROM reservas
            WHERE id_instalacion = %s
            AND fecha = %s
            AND (
                (hora_inicio < %s AND hora_fin > %s) OR
                (hora_inicio >= %s AND hora_inicio < %s) OR
                (hora_fin > %s AND hora_fin <= %s)
            )
        """
        valores_verificacion = (id_instalacion, fecha, hora_fin, hora_inicio, hora_inicio, hora_fin, hora_inicio, hora_fin)
        cursor.execute(sql_verificacion, valores_verificacion)
        resultado_conflicto = cursor.fetchone()
        if resultado_conflicto['total'] > 0:
            flash("La instalación ya está reservada en el horario seleccionado.", "error")
            return redirect(url_for('detalle_instalacion', id=id_instalacion))
        sql_insert = "INSERT INTO reservas (id_instalacion, id_usuario, fecha, hora_inicio, hora_fin) VALUES (%s, %s, %s, %s, %s)"
        valores_insert = (id_instalacion, id_usuario, fecha, hora_inicio, hora_fin)
        cursor.execute(sql_insert, valores_insert)
        conexion.commit()
        nueva_reserva_id = cursor.lastrowid
        cursor.execute("SELECT * FROM reservas WHERE id_reserva = %s", (nueva_reserva_id,))
        reserva = cursor.fetchone()
        cursor.execute("SELECT * FROM instalaciones WHERE id_instalacion = %s", (id_instalacion,))
        instalacion = cursor.fetchone()
        flash("¡Reserva exitosa!", "success")
        return render_template('reserva_exitosa.html', instalacion=instalacion, reserva=reserva)
    except mysql.connector.Error as err:
        flash(f"Error al realizar la reserva: {err}", "error")
        return redirect(url_for('detalle_instalacion', id=id_instalacion))
    finally:
        if 'conexion' in locals() and conexion.is_connected():
            cursor.close()
            conexion.close()

@app.route('/eliminar_reserva/<int:id_reserva>', methods=['POST'])
@login_required
def eliminar_reserva(id_reserva):
    id_usuario = session['id_usuario']
    try:
        conexion = get_db_connection()
        cursor = conexion.cursor()
        sql_verificacion = "SELECT COUNT(*) FROM reservas WHERE id_reserva = %s AND id_usuario = %s"
        cursor.execute(sql_verificacion, (id_reserva, id_usuario))
        pertenece_al_usuario = cursor.fetchone()[0]
        if pertenece_al_usuario:
            sql_eliminar = "DELETE FROM reservas WHERE id_reserva = %s"
            cursor.execute(sql_eliminar, (id_reserva,))
            conexion.commit()
            flash("Reserva eliminada con éxito.", "success")
            return redirect(url_for('mis_reservas'))
        else:
            flash("Error: No tienes permiso para eliminar esta reserva.", "error")
            return redirect(url_for('mis_reservas'))
    except mysql.connector.Error as err:
        flash(f"Error al eliminar la reserva: {err}", "error")
        return redirect(url_for('mis_reservas'))
    finally:
        if 'conexion' in locals() and conexion.is_connected():
            cursor.close()
            conexion.close()

@app.route('/mis_reservas')
@login_required
def mis_reservas():
    id_usuario = session['id_usuario']
    conexion = get_db_connection()
    cursor = conexion.cursor(dictionary=True)
    sql = """
        SELECT r.id_reserva, r.fecha, r.hora_inicio, r.hora_fin, i.nombre as nombre_instalacion 
        FROM reservas r
        JOIN instalaciones i ON r.id_instalacion = i.id_instalacion
        WHERE r.id_usuario = %s
        ORDER BY r.fecha, r.hora_inicio
    """
    cursor.execute(sql, (id_usuario,))
    reservas_usuario = cursor.fetchall()
    cursor.close()
    conexion.close()
    return render_template('mis_reservas.html', reservas=reservas_usuario)

@app.route('/asignar_tecnico_en_linea', methods=['POST'])
@admin_required
def asignar_tecnico_en_linea():
    id_instalacion = request.form.get('id_instalacion')
    id_usuario_asignado = request.form.get('id_usuario_asignado')
    
    conexion = get_db_connection()
    cursor = conexion.cursor(dictionary=True)

    try:
        if not id_instalacion or not id_usuario_asignado:
            flash("Faltan datos para asignar el técnico.", "error")
            return redirect(url_for('admin'))

        cursor.execute("SELECT nombre, telefono FROM usuarios WHERE id_usuario = %s", (id_usuario_asignado,))
        tecnico_info = cursor.fetchone()
        nombre_tecnico = tecnico_info['nombre']
        telefono_tecnico = tecnico_info['telefono']

        sql_update_instalacion = "UPDATE instalaciones SET tecnico_asignado = %s, estado = 'Asignado', id_instalador = %s WHERE id_instalacion = %s"
        valores_update = (nombre_tecnico, id_usuario_asignado, id_instalacion)
        cursor.execute(sql_update_instalacion, valores_update)

        cursor.execute("SELECT nombre, descripcion FROM instalaciones WHERE id_instalacion = %s", (id_instalacion,))
        instalacion = cursor.fetchone()
        
        tipo_tarea = instalacion['nombre']
        descripcion_tarea = instalacion['descripcion']

        sql_insert_tarea = "INSERT INTO tareas (id_instalacion, id_admin, id_usuario_asignado, tipo_tarea, descripcion, fecha_asignacion, estado) VALUES (%s, %s, %s, %s, %s, %s, %s)"
        valores_tarea = (id_instalacion, session.get('id_usuario'), id_usuario_asignado, tipo_tarea, descripcion_tarea, date.today(), 'Pendiente')
        cursor.execute(sql_insert_tarea, valores_tarea)
        
        conexion.commit()
        flash("Técnico asignado con éxito y tarea creada.", "success")
        
        if telefono_tecnico:
            mensaje = f"¡Hola! Se te ha asignado una nueva tarea: {tipo_tarea}. Revisa la app para más detalles."
            success_notif, msg_notif = send_whatsapp_notification(telefono_tecnico, mensaje)
            if not success_notif:
                logging.warning(f"No se pudo enviar la notificación a {nombre_tecnico}: {msg_notif}")
    
    except mysql.connector.Error as err:
        flash(f"Error al asignar el técnico: {err}", "error")
        logging.error(f"Error en asignar_tecnico_en_linea: {err}")
    finally:
        if 'conexion' in locals() and conexion.is_connected():
            cursor.close()
            conexion.close()
    
    return redirect(url_for('admin'))

@app.route('/ver_tarea_completada/<int:tarea_id>')
@login_required
@instalador_required
def ver_tarea_completada(tarea_id):
    conexion = get_db_connection()
    cursor = conexion.cursor(dictionary=True)

    cursor.execute("""
        SELECT t.*, c.nombre as nombre_cliente, c.codigo_cliente, c.telefono as telefono_cliente,
               i.descripcion_final, i.ubicacion_gps_final, i.foto_adjunta,
               i.fecha_completado, i.nombre as nombre_instalacion, u.nombre AS tecnico_asignado
        FROM tareas t
        JOIN instalaciones i ON t.id_instalacion = i.id_instalacion
        JOIN clientes c ON i.id_cliente = c.id_cliente
        LEFT JOIN usuarios u ON t.id_usuario_asignado = u.id_usuario
        WHERE t.id_tarea = %s
    """, (tarea_id,))
    tarea = cursor.fetchone()
    cursor.close()
    conexion.close()

    if not tarea:
        abort(404)

    return render_template('ver_tarea_completada.html', tarea=tarea)


@app.route('/exportar_tareas_excel')
@admin_required
def exportar_tareas_excel():
    conexion = get_db_connection()
    cursor = conexion.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT 
            t.id_tarea,
            t.tipo_tarea,
            i.nombre AS nombre_instalacion,
            c.nombre AS nombre_cliente,
            t.fecha_asignacion,
            t.estado,
            i.descripcion_final,
            i.ubicacion_gps_final,
            i.foto_adjunta,
            i.fecha_completado,
            u.nombre AS tecnico_asignado
        FROM tareas t
        JOIN instalaciones i ON t.id_instalacion = i.id_instalacion
        JOIN clientes c ON i.id_cliente = c.id_cliente
        JOIN usuarios u ON t.id_usuario_asignado = u.id_usuario
        WHERE t.estado = 'Completada'
        ORDER BY t.fecha_asignacion DESC
    """)
    tareas = cursor.fetchall()
    
    cursor.close()
    conexion.close()

    if not tareas:
        flash("No hay tareas completadas para exportar.", "error")
        return redirect(url_for('admin'))

    df = pd.DataFrame(tareas)
    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='openpyxl')
    df.to_excel(writer, index=False, sheet_name='Tareas Completadas')
    writer.close()
    output.seek(0)

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        download_name='tareas_completadas.xlsx',
        as_attachment=True
    )

@app.route('/gestion_tareas')
@admin_required
def gestion_tareas():
    conexion = get_db_connection()
    cursor = conexion.cursor(dictionary=True)

    cursor.execute("""
        SELECT t.*, i.nombre AS nombre_instalacion, u.nombre AS nombre_usuario_asignado, a.nombre AS nombre_admin
        FROM tareas t
        JOIN instalaciones i ON t.id_instalacion = i.id_instalacion
        JOIN usuarios u ON t.id_usuario_asignado = u.id_usuario
        JOIN usuarios a ON t.id_admin = a.id_usuario
        ORDER BY t.fecha_asignacion DESC
    """)
    tareas = cursor.fetchall()
    
    cursor.close()
    conexion.close()
    
    return render_template('gestion_tareas.html', tareas=tareas)

@app.route('/api/mis_tareas_completadas')
@login_required
@instalador_required
def api_mis_tareas_completadas():
    id_usuario = session['id_usuario']
    conexion = get_db_connection()
    cursor = conexion.cursor(dictionary=True)
    cursor.execute("""
        SELECT t.id_tarea, i.nombre, i.fecha_completado
        FROM instalaciones i
        JOIN tareas t ON i.id_instalacion = t.id_instalacion
        WHERE t.id_usuario_asignado = %s AND t.estado = 'Completada'
        ORDER BY t.fecha_asignacion DESC
    """, (id_usuario,))
    tareas = cursor.fetchall()
    cursor.close()
    conexion.close()

    events = []
    for tarea in tareas:
        events.append({
            'id': tarea['id_tarea'],
            'title': f"Tarea: {tarea['nombre']}",
            'start': tarea['fecha_completado'].isoformat()
        })

    return jsonify(events) 

@app.route('/mis_tareas_completadas_calendario')
@login_required
@instalador_required
def mis_tareas_completadas_calendario():
    return render_template('tareas_completadas_calendario.html')

@app.route('/admin/tareas_calendario')
@admin_required
def admin_tareas_calendario():
    conexion = get_db_connection()
    cursor = conexion.cursor(dictionary=True)
    # Obtener la lista de técnicos para el formulario del calendario
    cursor.execute("SELECT id_usuario, nombre FROM usuarios WHERE es_admin = 0")
    tecnicos = cursor.fetchall()
    cursor.close()
    conexion.close()
    return render_template('admin_tareas_calendario.html', tecnicos=tecnicos)

# En app.py, agrega esta nueva función
@app.route('/asignar_tarea_calendario', methods=['POST'])
@admin_required
def asignar_tarea_calendario():
    fecha = request.form.get('fecha_asignacion')
    tecnico_asignado_id = request.form.get('id_usuario_asignado')
    tipo_tarea = request.form.get('tipo_tarea')
    descripcion = request.form.get('descripcion')
    
    conexion = get_db_connection()
    cursor = conexion.cursor()
    
    try:
        # Aquí la lógica es similar a `nueva_instalacion`, pero sin todos los campos.
        # Necesitas un id_instalacion. Como no lo tienes, puedes crear uno con datos básicos.
        sql_insert_instalacion = """
            INSERT INTO instalaciones (nombre, descripcion, estado, id_instalador)
            VALUES (%s, %s, %s, %s)
        """
        nombre_instalacion = f"{tipo_tarea} - {fecha}"
        valores_instalacion = (nombre_instalacion, descripcion, 'Pendiente', tecnico_asignado_id)
        cursor.execute(sql_insert_instalacion, valores_instalacion)
        id_instalacion_creada = cursor.lastrowid

        sql_insert_tarea = """
            INSERT INTO tareas (id_instalacion, id_admin, id_usuario_asignado, tipo_tarea, descripcion, fecha_asignacion, estado)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        valores_tarea = (id_instalacion_creada, session.get('id_usuario'), tecnico_asignado_id, tipo_tarea, descripcion, fecha, 'Pendiente')
        cursor.execute(sql_insert_tarea, valores_tarea)
        
        conexion.commit()
        flash("Tarea asignada con éxito desde el calendario.", "success")
    except Exception as e:
        conexion.rollback()
        flash(f"Error al asignar la tarea: {e}", "error")
    finally:
        cursor.close()
        conexion.close()
    
    return redirect(url_for('admin_tareas_calendario'))

@app.route('/api/admin_tareas_asignadas')
@admin_required
def api_admin_tareas_asignadas():
    conexion = get_db_connection()
    cursor = conexion.cursor(dictionary=True)
    cursor.execute("""
        SELECT t.id_tarea, t.tipo_tarea, t.descripcion, t.fecha_asignacion, t.estado, u.nombre AS tecnico_asignado
        FROM tareas t
        JOIN usuarios u ON t.id_usuario_asignado = u.id_usuario
        ORDER BY t.fecha_asignacion ASC
    """)
    tareas = cursor.fetchall()
    cursor.close()
    conexion.close()

    events = []
    for tarea in tareas:
        title = f"{tarea['tipo_tarea']} ({tarea['tecnico_asignado']})"
        if tarea['estado'] == 'Completada':
            title = f"COMPLETADA: {title}"

        events.append({
            'id': tarea['id_tarea'],
            'title': title,
            'start': tarea['fecha_asignacion'].isoformat(),
            'color': 'green' if tarea['estado'] == 'Completada' else 'blue'
        })

    return jsonify(events)

@app.route('/admin/ver_tarea/<int:id_tarea>')
@admin_required
def admin_ver_tarea(id_tarea):
    conexion = get_db_connection()
    cursor = conexion.cursor(dictionary=True)

    cursor.execute("""
        SELECT t.*, c.nombre as nombre_cliente, c.codigo_cliente, c.telefono as telefono_cliente,
               i.descripcion_final, i.ubicacion_gps_final, i.foto_adjunta,
               i.fecha_completado, i.nombre as nombre_instalacion, u.nombre AS tecnico_asignado
        FROM tareas t
        JOIN instalaciones i ON t.id_instalacion = i.id_instalacion
        JOIN clientes c ON i.id_cliente = c.id_cliente
        LEFT JOIN usuarios u ON t.id_usuario_asignado = u.id_usuario
        WHERE t.id_tarea = %s
    """, (id_tarea,))
    tarea = cursor.fetchone()
    cursor.close()
    conexion.close()

    if not tarea:
        abort(404)

    return render_template('ver_tarea_completada.html', tarea=tarea)

@app.route('/api/reniec_search', methods=['GET'])
@admin_required
def api_reniec_search():
    dni = request.args.get('dni')
    if not dni:
        return jsonify({'success': False, 'message': 'DNI no proporcionado'}), 400

    headers = {
        "Authorization": f"Bearer {reniec_api_key}",
        "Content-Type": "application/json"
    }
    params = {
        "dni": dni
    }

    try:
        response = requests.get(reniec_api_endpoint, headers=headers, params=params)
        response.raise_for_status()
        
        data = response.json()

        if data and data.get('nombre'):
            return jsonify({'success': True, 'nombre': data['nombre']})
        else:
            return jsonify({'success': False, 'message': 'DNI no encontrado en RENIEC'}), 404

    except requests.exceptions.RequestException as e:
        logging.error(f"Error al conectar con la API de RENIEC: {e}")
        return jsonify({'success': False, 'message': 'Error al conectar con la API de RENIEC'}), 500

@app.route('/solicitar_traspaso', methods=['POST'])
@login_required
@instalador_required
def solicitar_traspaso():
    id_tarea = request.form.get('id_tarea')
    id_receptor = request.form.get('id_receptor')
    id_solicitante = session.get('id_usuario')
    conexion = get_db_connection()
    cursor = conexion.cursor()
    
    try:
        # Verificar que la tarea le pertenece al usuario actual y que está en estado Pendiente
        cursor.execute("SELECT * FROM tareas WHERE id_tarea = %s AND id_usuario_asignado = %s AND estado = 'Pendiente'", (id_tarea, id_solicitante))
        tarea_existente = cursor.fetchone()
        
        if not tarea_existente:
            flash("La tarea no existe, no te ha sido asignada o ya ha sido transferida.", "error")
            return redirect(url_for('mis_tareas'))
            
        # Insertar la solicitud de traspaso
        sql = "INSERT INTO solicitudes_traspaso (id_tarea, id_solicitante, id_receptor) VALUES (%s, %s, %s)"
        cursor.execute(sql, (id_tarea, id_solicitante, id_receptor))
        
        # Opcional: Cambiar el estado de la tarea a "En Traspaso" para evitar conflictos
        cursor.execute("UPDATE tareas SET estado = 'En Traspaso' WHERE id_tarea = %s", (id_tarea,))

        conexion.commit()
        flash("Solicitud de traspaso enviada con éxito.", "success")
    except Exception as e:
        conexion.rollback()
        flash(f"Error al solicitar el traspaso: {e}", "error")
    finally:
        cursor.close()
        conexion.close()
    
    return redirect(url_for('mis_tareas'))

@app.route('/gestionar_traspaso', methods=['POST'])
@login_required
@instalador_required
def gestionar_traspaso():
    id_solicitud = request.form.get('id_solicitud')
    accion = request.form.get('accion')
    id_usuario_actual = session.get('id_usuario')
    conexion = get_db_connection()
    cursor = conexion.cursor()
    
    try:
        # Verificar que la solicitud existe y está pendiente para el usuario actual
        cursor.execute("SELECT * FROM solicitudes_traspaso WHERE id_solicitud = %s AND id_receptor = %s AND estado = 'Pendiente'", (id_solicitud, id_usuario_actual))
        solicitud = cursor.fetchone()
        
        if not solicitud:
            flash("La solicitud no existe o no te corresponde.", "error")
            return redirect(url_for('mis_tareas'))
        
        id_tarea = solicitud[1]
        
        if accion == 'aceptar':
            # Actualizar la tarea con el nuevo instalador y el estado a 'Pendiente'
            cursor.execute("UPDATE tareas SET id_usuario_asignado = %s, estado = 'Pendiente' WHERE id_tarea = %s", (id_usuario_actual, id_tarea))
            # Actualizar la solicitud de traspaso a 'Aceptada'
            cursor.execute("UPDATE solicitudes_traspaso SET estado = 'Aceptada' WHERE id_solicitud = %s", (id_solicitud,))
            flash("Traspaso aceptado con éxito. La tarea ha sido asignada a tu cuenta.", "success")
        elif accion == 'rechazar':
            # Devolver el estado de la tarea a "Pendiente" para que pueda ser reasignada
            cursor.execute("UPDATE tareas SET estado = 'Pendiente' WHERE id_tarea = %s", (id_tarea,))
            # Actualizar la solicitud de traspaso a 'Rechazada'
            cursor.execute("UPDATE solicitudes_traspaso SET estado = 'Rechazada' WHERE id_solicitud = %s", (id_solicitud,))
            flash("Has rechazado el traspaso de la tarea.", "info")
        else:
            flash("Acción no válida.", "error")
            return redirect(url_for('mis_tareas'))

        conexion.commit()

    except Exception as e:
        conexion.rollback()
        flash(f"Error al gestionar el traspaso: {e}", "error")
    finally:
        cursor.close()
        conexion.close()
    
    return redirect(url_for('mis_tareas'))

@app.route('/api/admin_stats')
@admin_required
def api_admin_stats():
    conexion = get_db_connection()
    cursor = conexion.cursor(dictionary=True)
    
    # Total de tareas por estado
    cursor.execute("""
        SELECT estado, COUNT(*) as count
        FROM tareas
        GROUP BY estado
    """)
    tareas_por_estado = cursor.fetchall()
    
    # Tareas completadas por técnico
    cursor.execute("""
        SELECT u.nombre, COUNT(t.id_tarea) as count
        FROM tareas t
        JOIN usuarios u ON t.id_usuario_asignado = u.id_usuario
        WHERE t.estado = 'Completada'
        GROUP BY u.nombre
    """)
    tareas_completadas_por_tecnico = cursor.fetchall()
    
    # Tareas por tipo
    cursor.execute("""
        SELECT tipo_tarea, COUNT(*) as count
        FROM tareas
        GROUP BY tipo_tarea
    """)
    tareas_por_tipo = cursor.fetchall()
    
    cursor.close()
    conexion.close()
    
    return jsonify({
        'tareas_por_estado': tareas_por_estado,
        'tareas_completadas_por_tecnico': tareas_completadas_por_tecnico,
        'tareas_por_tipo': tareas_por_tipo
    })

@app.route('/api/tecnico_stats/<int:id_tecnico>')
@login_required
@instalador_required
def api_tecnico_stats(id_tecnico):
    if session.get('id_usuario') != id_tecnico:
        abort(403)
        
    conexion = get_db_connection()
    cursor = conexion.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT COUNT(*) as count FROM tareas
        WHERE id_usuario_asignado = %s AND estado = 'Completada'
    """, (id_tecnico,))
    completadas = cursor.fetchone()['count']
    
    cursor.execute("""
        SELECT COUNT(*) as count FROM tareas
        WHERE id_usuario_asignado = %s AND estado = 'Pendiente'
    """, (id_tecnico,))
    pendientes = cursor.fetchone()['count']
    
    cursor.close()
    conexion.close()
    
    return jsonify({
        'total_completadas': completadas,
        'total_pendientes': pendientes
    })

@app.route('/tecnico/dashboard')
@login_required
@instalador_required
def tecnico_dashboard():
    return render_template('tecnico_dashboard.html')


@app.route('/cliente/dashboard', methods=['GET', 'POST'])
@cliente_login_required
def cliente_dashboard():
    conexion = get_db_connection()
    cursor = conexion.cursor(dictionary=True)
    id_cliente_usuario = session.get('id_cliente_usuario')
    
    sql = """
        SELECT c.*, cu.id_cliente_usuario
        FROM clientes c
        JOIN clientes_usuarios cu ON c.id_cliente = cu.id_cliente
        WHERE cu.id_cliente_usuario = %s
    """
    cursor.execute(sql, (id_cliente_usuario,))
    cliente_data = cursor.fetchone()

    sql_instalaciones = """
    SELECT i.*, inv.numero_serie, t.estado AS estado_tarea
    FROM instalaciones i
    LEFT JOIN inventario inv ON i.id_equipo_instalado = inv.id_equipo
    LEFT JOIN tareas t ON i.id_instalacion = t.id_instalacion
    WHERE i.id_cliente = %s
    ORDER BY i.id_instalacion DESC
"""
    cursor.execute(sql_instalaciones, (cliente_data['id_cliente'],))
    instalaciones = cursor.fetchall()
    
    if request.method == 'POST':
        id_instalacion = request.form.get('id_instalacion')
        descripcion_problema = request.form.get('descripcion_problema')
        
        if not id_instalacion or not descripcion_problema:
            flash("Todos los campos son obligatorios para reportar un problema.", "error")
            return redirect(url_for('cliente_dashboard'))

        try:
            sql_insert_tarea = """
                INSERT INTO tareas (id_instalacion, tipo_tarea, descripcion, fecha_creacion, estado)
                VALUES (%s, 'Reparacion', %s, NOW(), 'Pendiente')
            """
            cursor.execute(sql_insert_tarea, (id_instalacion, descripcion_problema))
            conexion.commit()

            flash("El problema ha sido reportado con éxito. Un técnico se comunicará contigo pronto.", "success")
        except Exception as e:
            conexion.rollback()
            logging.error(f"Error al reportar problema desde el cliente: {e}")
            flash("Ocurrió un error al reportar el problema. Por favor, inténtelo de nuevo.", "error")
        finally:
            cursor.close()
            conexion.close()
            return redirect(url_for('cliente_dashboard'))
    
    cursor.close()
    conexion.close()
    return render_template('cliente_dashboard.html', cliente=cliente_data, instalaciones=instalaciones)


@app.route('/admin/inventario')
@admin_required
def inventario_admin():
    conexion = get_db_connection()
    cursor = conexion.cursor(dictionary=True)
    cursor.execute("""
        SELECT
            i.*,
            u.nombre AS nombre_tecnico,
            MAX(inst.fecha_completado) AS fecha_instalacion
        FROM inventario i
        LEFT JOIN instalaciones inst ON i.id_equipo = inst.id_equipo_instalado
        LEFT JOIN usuarios u ON inst.id_instalador = u.id_usuario
        GROUP BY i.id_equipo
        ORDER BY i.fecha_ingreso DESC
    """)
    inventario = cursor.fetchall()
    cursor.close()
    conexion.close()
    return render_template('inventario_admin.html', inventario=inventario)

@app.route('/admin/inventario/agregar', methods=['POST'])
@admin_required
def inventario_agregar():
    numero_serie = request.form.get('numero_serie')
    modelo = request.form.get('modelo')
    fecha_ingreso = date.today()
    
    conexion = get_db_connection()
    cursor = conexion.cursor()
    
    try:
        sql = "INSERT INTO inventario (numero_serie, modelo, estado, fecha_ingreso) VALUES (%s, %s, 'Disponible', %s)"
        cursor.execute(sql, (numero_serie, modelo, fecha_ingreso))
        conexion.commit()
        flash("Equipo añadido al inventario con éxito.", "success")
    except mysql.connector.Error as err:
        flash(f"Error al añadir equipo: {err}", "error")
        logging.error(f"Error al añadir equipo al inventario: {err}")
    finally:
        cursor.close()
        conexion.close()
    
    return redirect(url_for('inventario_admin'))

@app.route('/admin/inventario/editar/<int:id>', methods=['GET', 'POST'])
@admin_required
def inventario_editar(id):
    conexion = get_db_connection()
    cursor = conexion.cursor(dictionary=True)
    
    if request.method == 'POST':
        numero_serie = request.form.get('numero_serie')
        modelo = request.form.get('modelo')
        estado = request.form.get('estado')
        
        try:
            sql = "UPDATE inventario SET numero_serie = %s, modelo = %s, estado = %s WHERE id_equipo = %s"
            cursor.execute(sql, (numero_serie, modelo, estado, id))
            conexion.commit()
            flash("Equipo actualizado con éxito.", "success")
        except mysql.connector.Error as err:
            flash(f"Error al editar equipo: {err}", "error")
            logging.error(f"Error al editar equipo: {err}")
        finally:
            cursor.close()
            conexion.close()
        
        return redirect(url_for('inventario_admin'))

    cursor.execute("SELECT * FROM inventario WHERE id_equipo = %s", (id,))
    equipo = cursor.fetchone()
    cursor.close()
    conexion.close()
    
    if not equipo:
        flash("Equipo no encontrado.", "error")
        return redirect(url_for('inventario_admin'))
    
    return render_template('inventario_editar.html', equipo=equipo)


@app.route('/admin/inventario/eliminar/<int:id>', methods=['POST'])
@admin_required
def inventario_eliminar(id):
    conexion = get_db_connection()
    cursor = conexion.cursor()
    try:
        sql = "DELETE FROM inventario WHERE id_equipo = %s"
        cursor.execute(sql, (id,))
        conexion.commit()
        flash("Equipo eliminado con éxito.", "success")
    except mysql.connector.Error as err:
        flash(f"Error al eliminar equipo: {err}", "error")
        logging.error(f"Error al eliminar equipo: {err}")
    finally:
        cursor.close()
        conexion.close()
    
    return redirect(url_for('inventario_admin'))

@app.route('/admin/inventario/exportar')
@admin_required
def exportar_inventario():
    conexion = get_db_connection()
    cursor = conexion.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            i.numero_serie,
            i.modelo,
            i.estado,
            i.fecha_ingreso,
            MAX(inst.fecha_completado) AS fecha_instalacion,
            u.nombre AS nombre_tecnico
        FROM inventario i
        LEFT JOIN instalaciones inst ON i.id_equipo = inst.id_equipo_instalado
        LEFT JOIN usuarios u ON inst.id_instalador = u.id_usuario
        GROUP BY i.id_equipo
        ORDER BY i.fecha_ingreso DESC
    """)
    inventario = cursor.fetchall()
    cursor.close()
    conexion.close()

    if not inventario:
        flash("No hay equipos en el inventario para exportar.", "error")
        return redirect(url_for('inventario_admin'))

    df = pd.DataFrame(inventario)
    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='openpyxl')
    df.to_excel(writer, index=False, sheet_name='Inventario de Equipos')
    writer.close()
    output.seek(0)

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        download_name='inventario.xlsx',
        as_attachment=True
    )


@app.route('/api/clientes', methods=['GET'])
def api_clientes():
    query = request.args.get('q', '').lower()
    conexion = get_db_connection()
    cursor = conexion.cursor(dictionary=True)
    
    sql = "SELECT nombre, plan as service, telefono as phone, dni FROM clientes WHERE lower(nombre) LIKE %s OR lower(telefono) LIKE %s OR lower(dni) LIKE %s ORDER BY nombre"
    search_term = f"%{query}%"
    cursor.execute(sql, (search_term, search_term, search_term))
    clientes = cursor.fetchall()
    
    cursor.close()
    conexion.close()
    return jsonify(clientes)

# En app.py, añade esta nueva ruta
@app.route('/api/inventario/buscar_por_serie', methods=['GET'])
@admin_required
def api_buscar_equipo_por_serie():
    numero_serie = request.args.get('numero_serie')
    if not numero_serie:
        return jsonify({'success': False, 'message': 'Número de serie no proporcionado.'}), 400

    conexion = get_db_connection()
    cursor = conexion.cursor(dictionary=True)
    
    try:
        sql = "SELECT numero_serie, modelo FROM inventario WHERE numero_serie = %s"
        cursor.execute(sql, (numero_serie,))
        equipo = cursor.fetchone()
        
        if equipo:
            return jsonify({'success': True, 'numero_serie': equipo['numero_serie'], 'modelo': equipo['modelo']})
        else:
            return jsonify({'success': False, 'message': 'Equipo no encontrado en el inventario.'}), 404
            
    except mysql.connector.Error as err:
        return jsonify({'success': False, 'message': f'Error en la base de datos: {err}'}), 500
    finally:
        if conexion and conexion.is_connected():
            cursor.close()
            conexion.close()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)

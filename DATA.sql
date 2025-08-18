-- --------------------------------------------------------
-- Host:                         127.0.0.1
-- Server version:               10.4.32-MariaDB - mariadb.org binary distribution
-- Server OS:                    Win64
-- HeidiSQL Version:             12.10.0.7000
-- --------------------------------------------------------

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET NAMES utf8 */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;


-- Dumping database structure for gestor_instalaciones
DROP DATABASE IF EXISTS `gestor_instalaciones`;
CREATE DATABASE IF NOT EXISTS `gestor_instalaciones` /*!40100 DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci */;
USE `gestor_instalaciones`;

-- Dumping structure for table gestor_instalaciones.instalaciones
DROP TABLE IF EXISTS `instalaciones`;
CREATE TABLE IF NOT EXISTS `instalaciones` (
  `id_instalacion` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `nombre` varchar(255) NOT NULL,
  `descripcion` text DEFAULT NULL,
  `imagen_url` text DEFAULT NULL,
  `hora_solicitada` time DEFAULT NULL,
  `codigo_cliente` varchar(50) DEFAULT NULL,
  `solicitud` varchar(255) DEFAULT NULL,
  `tecnico_asignado` varchar(255) DEFAULT NULL,
  `id_instalador` int(11) DEFAULT NULL,
  `nombre_cliente` varchar(255) DEFAULT NULL,
  `telefono_cliente` varchar(20) DEFAULT NULL,
  `referencia` text DEFAULT NULL,
  `ruta_caja_nap` varchar(255) DEFAULT NULL,
  `ubicacion_gps` varchar(255) DEFAULT NULL,
  `descripcion_final` text DEFAULT NULL,
  `ubicacion_gps_final` varchar(255) DEFAULT NULL,
  `foto_adjunta` varchar(255) DEFAULT NULL,
  `numero_serie` varchar(255) DEFAULT NULL,
  `metodo_pago` varchar(50) DEFAULT NULL,
  `numero_transaccion` varchar(255) DEFAULT NULL,
  `fecha_completado` datetime DEFAULT NULL,
  `foto_domicilio` varchar(255) DEFAULT NULL,
  `foto_equipo_instalado` varchar(255) DEFAULT NULL,
  `telefono_referencia` varchar(20) DEFAULT NULL,
  `pppoe_password` varchar(255) DEFAULT NULL,
  `estado` varchar(50) NOT NULL DEFAULT 'Disponible',
  `dni` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`id_instalacion`)
) ENGINE=InnoDB AUTO_INCREMENT=1379 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- Data exporting was unselected.

-- Dumping structure for table gestor_instalaciones.reservas
DROP TABLE IF EXISTS `reservas`;
CREATE TABLE IF NOT EXISTS `reservas` (
  `id_reserva` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `id_instalacion` int(10) unsigned NOT NULL,
  `nombre_cliente` varchar(255) NOT NULL,
  `fecha` date NOT NULL,
  `hora_inicio` time NOT NULL,
  `hora_fin` time NOT NULL,
  `estado` varchar(50) NOT NULL DEFAULT 'Confirmada',
  `id_usuario` int(11) DEFAULT NULL,
  PRIMARY KEY (`id_reserva`),
  KEY `id_instalacion` (`id_instalacion`),
  CONSTRAINT `reservas_ibfk_1` FOREIGN KEY (`id_instalacion`) REFERENCES `instalaciones` (`id_instalacion`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- Data exporting was unselected.

-- Dumping structure for table gestor_instalaciones.solicitudes_traspaso
DROP TABLE IF EXISTS `solicitudes_traspaso`;
CREATE TABLE IF NOT EXISTS `solicitudes_traspaso` (
  `id_solicitud` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `id_tarea` int(10) NOT NULL,
  `id_solicitante` int(10) unsigned NOT NULL,
  `id_receptor` int(10) unsigned NOT NULL,
  `estado` enum('Pendiente','Aceptada','Rechazada') NOT NULL DEFAULT 'Pendiente',
  `fecha_creacion` datetime NOT NULL,
  PRIMARY KEY (`id_solicitud`),
  KEY `id_tarea` (`id_tarea`),
  KEY `id_solicitante` (`id_solicitante`),
  KEY `id_receptor` (`id_receptor`),
  CONSTRAINT `solicitudes_traspaso_ibfk_1` FOREIGN KEY (`id_tarea`) REFERENCES `tareas` (`id_tarea`),
  CONSTRAINT `solicitudes_traspaso_ibfk_2` FOREIGN KEY (`id_solicitante`) REFERENCES `usuarios` (`id_usuario`),
  CONSTRAINT `solicitudes_traspaso_ibfk_3` FOREIGN KEY (`id_receptor`) REFERENCES `usuarios` (`id_usuario`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- Data exporting was unselected.

-- Dumping structure for table gestor_instalaciones.tareas
DROP TABLE IF EXISTS `tareas`;
CREATE TABLE IF NOT EXISTS `tareas` (
  `id_tarea` int(10) NOT NULL AUTO_INCREMENT,
  `id_instalacion` int(10) unsigned NOT NULL,
  `id_admin` int(10) unsigned NOT NULL,
  `id_usuario_asignado` int(10) unsigned NOT NULL,
  `tipo_tarea` varchar(50) NOT NULL,
  `descripcion` text NOT NULL,
  `fecha_asignacion` date NOT NULL,
  `estado` varchar(50) NOT NULL,
  PRIMARY KEY (`id_tarea`),
  KEY `id_instalacion` (`id_instalacion`),
  KEY `id_admin` (`id_admin`),
  KEY `id_usuario_asignado` (`id_usuario_asignado`),
  CONSTRAINT `fk_tareas_admin` FOREIGN KEY (`id_admin`) REFERENCES `usuarios` (`id_usuario`),
  CONSTRAINT `fk_tareas_instalacion` FOREIGN KEY (`id_instalacion`) REFERENCES `instalaciones` (`id_instalacion`),
  CONSTRAINT `fk_tareas_usuario_asignado` FOREIGN KEY (`id_usuario_asignado`) REFERENCES `usuarios` (`id_usuario`),
  CONSTRAINT `tareas_ibfk_1` FOREIGN KEY (`id_instalacion`) REFERENCES `instalaciones` (`id_instalacion`)
) ENGINE=InnoDB AUTO_INCREMENT=40 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- Data exporting was unselected.

-- Dumping structure for table gestor_instalaciones.tipos_instalacion
DROP TABLE IF EXISTS `tipos_instalacion`;
CREATE TABLE IF NOT EXISTS `tipos_instalacion` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `nombre` varchar(255) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `nombre` (`nombre`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- Data exporting was unselected.

-- Dumping structure for table gestor_instalaciones.usuarios
DROP TABLE IF EXISTS `usuarios`;
CREATE TABLE IF NOT EXISTS `usuarios` (
  `id_usuario` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `nombre` varchar(255) NOT NULL,
  `email` varchar(255) NOT NULL,
  `password` varchar(255) NOT NULL,
  `es_admin` tinyint(1) DEFAULT 0,
  `direccion` varchar(255) DEFAULT NULL,
  `telefono` varchar(20) DEFAULT NULL,
  `dni` varchar(20) DEFAULT NULL,
  PRIMARY KEY (`id_usuario`),
  UNIQUE KEY `email` (`email`)
) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- Data exporting was unselected.

/*!40103 SET TIME_ZONE=IFNULL(@OLD_TIME_ZONE, 'system') */;
/*!40101 SET SQL_MODE=IFNULL(@OLD_SQL_MODE, '') */;
/*!40014 SET FOREIGN_KEY_CHECKS=IFNULL(@OLD_FOREIGN_KEY_CHECKS, 1) */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40111 SET SQL_NOTES=IFNULL(@OLD_SQL_NOTES, 1) */;

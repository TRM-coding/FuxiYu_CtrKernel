-- MySQL dump 10.13  Distrib 8.0.43, for Linux (x86_64)
--
-- Host: localhost    Database: fuxi
-- ------------------------------------------------------
-- Server version	8.0.43-0ubuntu0.24.04.2

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `containers`
--

DROP TABLE IF EXISTS `containers`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `containers` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(120) NOT NULL,
  `image` varchar(200) NOT NULL,
  `machine_id` int NOT NULL,
  `container_status` varchar(255) NOT NULL DEFAULT 'maintenance',
  `port` int NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_container_name_machine` (`name`,`machine_id`),
  KEY `idx_containers_machine_id` (`machine_id`),
  KEY `idx_containers_port` (`port`),
  CONSTRAINT `fk_containers_machine` FOREIGN KEY (`machine_id`) REFERENCES `machines` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=42 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `containers`
--

LOCK TABLES `containers` WRITE;
/*!40000 ALTER TABLE `containers` DISABLE KEYS */;
INSERT INTO `containers` VALUES (1,'web','nginx:1.25',1,'online',8080),(2,'db','mysql:8.0',1,'maintenance',3306),(3,'api','python:3.11',2,'offline',9000),(4,'web','nginx:1.25',2,'online',8081),(5,'cache','redis:7',1,'online',6379),(6,'ml','pytorch/pytorch:2.4.0-cuda12.1-cudnn9-runtime',1,'online',7010),(7,'db','postgres:16',2,'online',5432),(8,'runner','ghcr.io/actions/runner:latest',2,'maintenance',9123),(9,'web','nginx:1.27',3,'online',8082),(10,'api','python:3.12',3,'online',9001),(11,'db','mysql:8.4',3,'maintenance',3307),(12,'monitor','prom/prometheus:latest',4,'online',9090),(13,'web','nginx:1.27',4,'offline',8083);
/*!40000 ALTER TABLE `containers` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `machines`
--

DROP TABLE IF EXISTS `machines`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `machines` (
  `id` int NOT NULL AUTO_INCREMENT,
  `machine_name` varchar(120) NOT NULL,
  `machine_ip` varchar(120) NOT NULL,
  `machine_type` varchar(255) NOT NULL,
  `machine_status` varchar(255) NOT NULL DEFAULT 'maintenance',
  `cpu_core_number` int DEFAULT NULL,
  `memory_size_gb` int DEFAULT NULL,
  `gpu_number` int DEFAULT NULL,
  `gpu_type` varchar(120) DEFAULT NULL,
  `disk_size_gb` int DEFAULT NULL,
  `machine_description` varchar(500) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_machines_machine_name` (`machine_name`),
  UNIQUE KEY `uq_machines_machine_ip` (`machine_ip`)
) ENGINE=InnoDB AUTO_INCREMENT=37 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `machines`
--

LOCK TABLES `machines` WRITE;
/*!40000 ALTER TABLE `machines` DISABLE KEYS */;
INSERT INTO `machines` VALUES (1,'node-a','10.0.0.10','CPU','online',16,64,2,'RTX 3090',2000,'Rack A main host'),(2,'node-b','10.0.0.11','GPU','maintenance',8,32,0,NULL,500,'KVM guest'),(3,'node-c','10.0.0.12','CPU','offline',32,128,4,'RTX 4090',6000,'GPU box'),(4,'node-d','10.0.0.13','GPU','maintenance',4,8,0,NULL,200,'Test VM');
/*!40000 ALTER TABLE `machines` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `user_container`
--

DROP TABLE IF EXISTS `user_container`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `user_container` (
  `user_id` int NOT NULL,
  `container_id` int NOT NULL,
  `role` varchar(255) NOT NULL,
  `granted_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `public_key` varchar(500) DEFAULT NULL,
  `username` varchar(120) NOT NULL,
  PRIMARY KEY (`user_id`,`container_id`),
  KEY `idx_uc_container_id` (`container_id`),
  KEY `idx_uc_username` (`username`),
  CONSTRAINT `fk_uc_container` FOREIGN KEY (`container_id`) REFERENCES `containers` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_uc_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `user_container`
--

LOCK TABLES `user_container` WRITE;
/*!40000 ALTER TABLE `user_container` DISABLE KEYS */;
INSERT INTO `user_container` VALUES (1,1,'admin','2025-10-24 22:21:21','ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQDalice','alice'),(1,2,'collaborator','2025-10-24 22:21:21','ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQDcalicedb','alice-db'),(1,6,'admin','2025-10-24 22:21:49','ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAAalice-ml','alice-ml'),(2,1,'collaborator','2025-10-24 22:21:21','ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIbob','bob'),(2,3,'collaborator','2025-10-24 22:21:21','ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAbobapi','bob-api'),(2,7,'collaborator','2025-10-24 22:21:49','ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAAbob-pg','bob-pg'),(2,8,'collaborator','2025-10-24 22:21:49','ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAAbob-runner','bob-runner'),(3,4,'collaborator','2025-10-24 22:21:21','ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQDcarol','carol-web'),(3,5,'collaborator','2025-10-24 22:21:49','ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQcarolc','carol-cache'),(3,9,'collaborator','2025-10-24 22:21:49','ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQcaroln','carol-nodec'),(4,9,'collaborator','2025-10-24 22:21:49','ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAAdavew','dave-web'),(4,10,'collaborator','2025-10-24 22:21:49','ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAAdavea','dave-api'),(5,12,'collaborator','2025-10-24 22:21:49','ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAAerinm','erin-mon'),(6,11,'collaborator','2025-10-24 22:21:49','ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQfrankd','frank-db'),(6,13,'collaborator','2025-10-24 22:21:49','ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQfrankw','frank-web');
/*!40000 ALTER TABLE `user_container` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `users`
--

DROP TABLE IF EXISTS `users`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `users` (
  `id` int NOT NULL AUTO_INCREMENT,
  `username` varchar(80) NOT NULL,
  `email` varchar(120) NOT NULL,
  `password_hash` varchar(255) NOT NULL,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `graduation_year` varchar(120) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_users_username` (`username`),
  UNIQUE KEY `uq_users_email` (`email`)
) ENGINE=InnoDB AUTO_INCREMENT=92 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `users`
--

LOCK TABLES `users` WRITE;
/*!40000 ALTER TABLE `users` DISABLE KEYS */;
INSERT INTO `users` VALUES (1,'alice','alice@example.com','$2y$dummyhashalice','2025-10-24 22:21:08','2026'),(2,'bob','bob@example.com','$2y$dummyhashbob','2025-10-24 22:21:08','2027'),(3,'carol','carol@example.com','$2y$dummyhashcarol','2025-10-24 22:21:08','2025'),(4,'dave','dave@example.com','$2y$dummyhashdave','2025-10-24 22:21:35','2028'),(5,'erin','erin@example.com','$2y$dummyhasherin','2025-10-24 22:21:35','2026'),(6,'frank','frank@example.com','$2y$dummyhashfrank','2025-10-24 22:21:35','2027');
/*!40000 ALTER TABLE `users` ENABLE KEYS */;
UNLOCK TABLES;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2025-10-26 21:37:42

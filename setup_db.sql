-- BOSS System — MySQL Setup Script
-- Run as MySQL root user:  mysql -u root -p < setup_db.sql

CREATE DATABASE IF NOT EXISTS boss_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'boss_user'@'localhost' IDENTIFIED BY 'boss_pass';
GRANT ALL PRIVILEGES ON boss_db.* TO 'boss_user'@'localhost';
FLUSH PRIVILEGES;

SELECT 'Database boss_db created and user boss_user granted access.' AS Status;

"""Database connection helpers for MySQL and Neo4j.

Connection settings are read from environment variables so that no credentials are
committed to the repository. See .env.example for the full list.
"""
import os

import pymysql
import pymysql.cursors
from neo4j import GraphDatabase

MYSQL_CFG = {
    "host": os.getenv("MYSQL_HOST", "localhost"),
    "port": int(os.getenv("MYSQL_PORT", "3306")),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", ""),
    "database": os.getenv("MYSQL_DATABASE", "benti"),
    "charset": "utf8mb4",
}

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_AUTH = (
    os.getenv("NEO4J_USER", "neo4j"),
    os.getenv("NEO4J_PASSWORD", ""),
)

_driver = None


def get_mysql_conn():
    return pymysql.connect(cursorclass=pymysql.cursors.DictCursor, **MYSQL_CFG)


def get_neo4j_driver():
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
    return _driver


def close_neo4j():
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None

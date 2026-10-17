"""Verify Neo4j connectivity."""
import os

from neo4j import GraphDatabase

driver = GraphDatabase.driver(
    os.getenv("NEO4J_URI", "bolt://localhost:7687"),
    auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "")),
)
try:
    with driver.session() as s:
        result = s.run("RETURN 'connected' AS msg")
        print(result.single()["msg"])
        # Existing labels and rel types
        labels = [r["label"] for r in s.run("CALL db.labels()")]
        rels = [r["relationshipType"] for r in s.run("CALL db.relationshipTypes()")]
        print(f"Labels: {labels}")
        print(f"Relationship types: {rels}")
finally:
    driver.close()

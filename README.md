# DOCAR — Ontology-Driven Dynamic Data Classification and Reasoning

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23449067.svg)](https://doi.org/10.5281/zenodo.23449067)

Research artifact accompanying the manuscript submitted to *Data & Knowledge Engineering*
(Elsevier). It contains the prototype system, the domain dataset used in Section 5.1, and the
scripts that produce the results reported in Section 5.

The system builds a domain ontology from heterogeneous sources (structured tables and
unstructured news texts), instantiates it as a knowledge graph, keeps the ontology and the graph
in sync with changing business data, and uses the resulting ontology to constrain reasoning
(SQL / Cypher generation) over the knowledge base.

---

## 1. Repository structure

```
ontology_reasoning/
├── backend/     Flask REST API: ontology construction, rule engine, text extraction,
│               SQL/Cypher query services, TF-IDF retrieval, QA services
├── frontend/    Vue 3 + Vite UI for ontology and knowledge-graph exploration
├── data/        test1.sql — dump of the domain relational database + news corpus
└── scripts/     data preparation, KG construction, ontology engineering, experiment runners
```

Key modules in `backend/`:

| File | Role |
|---|---|
| `ontology.py` | concept layer: concepts, concept relations, concept graph |
| `extractor.py` | instance layer: instance (entity) extraction and instance graph |
| `text_extractor.py` | extraction of concepts / relations / instances from unstructured text |
| `rules.py` | rule engine that triggers extraction operations on new data |
| `functions.py` | domain functions registered on the ontology |
| `reasoning_service.py`, `qa_sql.py`, `qa_kg_retrieval.py`, `qa_vector.py` | the reasoning / QA pipelines evaluated in Section 5 |
| `llm_client.py` | OpenAI-compatible client used for LLM-assisted extraction and query generation |

---

## 2. Requirements

| Component | Version used |
|---|---|
| Python | 3.11 |
| MySQL | 8.0 |
| Neo4j | 5.x |
| Node.js | 18+ (frontend only) |

```bash
pip install -r backend/requirements.txt
```

---

## 3. Setup

### 3.1 Import the domain dataset

`data/test1.sql` is a MySQL 8.0 dump. It contains the simulated relational database used in
Section 5.1 (12 tables: `countries_regions`, `persons`, `organizations`, `equipments`,
`facilities`, `events`, `event_persons`, `event_organizations`, `event_equipments`,
`event_facilities`, `event_timeline`, `text_sources`) together with the 132 news documents,
which are stored in the `content` column of `text_sources`. The structured tables hold 5,512
records in total, and the news corpus contains 43,758 characters (332 on average per document),
matching the figures reported in Section 5.1.1.

```bash
mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS benti CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;"
mysql -u root -p benti < data/test1.sql

# sanity check: expect 132
mysql -u root -p benti -e "SELECT COUNT(*) FROM text_sources;"
```

### 3.2 Configure the connections

No credentials are stored in the repository. All connection settings are read from environment
variables; `.env.example` lists them. Export them in your shell before starting anything:

```bash
export MYSQL_HOST=localhost MYSQL_PORT=3306 MYSQL_USER=root
export MYSQL_PASSWORD=<your-password> MYSQL_DATABASE=benti
export NEO4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j NEO4J_PASSWORD=<your-password>
export LLM_API_KEY=<your-key>            # required by the LLM-dependent pipelines
export LLM_BASE_URL=https://api.deepseek.com
export LLM_MODEL=deepseek-v4-flash
```

`backend/db.py` (`MYSQL_CFG`, `NEO4J_AUTH`) and `backend/llm_client.py` read these variables at
import time. `llm_client.get_client()` raises an explicit error if `LLM_API_KEY` is missing
rather than falling back to a built-in key.

Alternatively, copy `.env.example` to `.env`, fill in your own values and source it before
running anything:

```bash
set -a; source .env; set +a        # Git Bash / Linux / macOS
```

`.env` is git-ignored and must never be committed.

### 3.3 Start Neo4j

```bash
neo4j start          # or start Neo4j Desktop / the Docker image
```

Make sure the credentials match `NEO4J_AUTH` in `backend/db.py`.

### 3.4 Start the backend

```bash
cd backend
python app.py        # serves http://localhost:5000
```

### 3.5 Start the frontend

```bash
cd frontend
npm install
npm run dev
```

---

## 4. Reproducing the experiments

### 4.1 Section 5.1 — domain data experiments

| Script | Purpose |
|---|---|
| `scripts/expand_mysql_data.py` | populate the relational tables with the simulated domain data |
| `scripts/generate_text_data.py` | build / import the news corpus into `text_sources` and index it |
| `scripts/import_cmnee.py` | optional: import the CMNEE event-annotated corpus (see note below) |
| `scripts/build_cmnee_kg.py` | build the military-domain KG in Neo4j from CMNEE annotations |
| `scripts/ontology_engineering.py` | concept/relation completion and entity alignment (method A′) |
| `scripts/run_l2_experiment.py` | compare methods A, A′, F, D and E; reports accuracy, latency and token consumption |

```bash
python scripts/run_l2_experiment.py
```

An existing import of `data/test1.sql` is sufficient for the table-driven part; the
CMNEE-based knowledge graph is only needed for the variants that use the annotated corpus.

### 4.2 Section 5.2 — KQAPro experiments

| Script | Purpose |
|---|---|
| `scripts/import_kqapro.py` | download `kb.json` from Hugging Face and import it into Neo4j under independent `KQA_*` labels |
| `scripts/run_kqapro_experiment.py` | run the ablation variants (`A`, `B`, `C`, `D` or `all`); checkpoints after every question and resumes automatically |
| `scripts/run_kqapro_batch.py` | batch runner over the evaluation set |

```bash
python scripts/import_kqapro.py
python scripts/run_kqapro_experiment.py all
```

Checkpoints are written under `data/kqapro_experiment/`, so an interrupted run can be resumed.

---

## 5. External datasets

* **KQAPro** — not redistributed here. It is downloaded by `scripts/import_kqapro.py` from its
  official release (Hugging Face). Please cite Cao et al., ACL 2022.
* **CMNEE** — the event-annotation corpus is not redistributed here. Place it under
  `data/cmnee/CMNEE/` before running `scripts/import_cmnee.py`. Datasets derived from it can be
  skipped without affecting the table-driven results.

Only the data in `data/test1.sql` is released as part of this artifact.

---

## 6. Use of large language models

All LLM calls are routed through `backend/llm_client.py`, which targets an OpenAI-compatible
endpoint (DeepSeek by default, model `deepseek-v4-flash`). The LLM is used for ontology and
instance extraction from text, for generating SQL/Cypher queries under ontology constraints,
and for auxiliary experiment scripting. No API key is required to read or inspect the code;
running the LLM-dependent pipelines requires `LLM_API_KEY`.

---

## 7. Citation

If you use this code or data, please cite the archived release of this repository (see the DOI
badge on the GitHub page, minted by Zenodo) and the accompanying article:

> X. Zhao, X. Yuan, C. Yi. DOCAR: A Domain Ontology Construction and Reasoning Method Combined
> with Large Language Models. *Data & Knowledge Engineering* (under review).
>
> Code and data: https://github.com/sar31/ontology_reasoning — archived as v1.0.0 at
> https://doi.org/10.5281/zenodo.23449067 (all versions: 10.5281/zenodo.23449066).

```bibtex
@software{zhao_dobar_2026,
  author    = {Zhao, Xiaoxing and Yuan, Xiang and Yi, Changyan},
  title     = {DOCAR: Domain Ontology Construction and Reasoning Method Combined with
               Large Language Models - Reproducibility Package},
  version   = {1.0.0},
  year      = {2026},
  publisher = {Zenodo},
  doi       = {10.5281/zenodo.23449067},
  url       = {https://doi.org/10.5281/zenodo.23449067}
}
```

`CITATION.cff` and `.zenodo.json` carry the same metadata, so GitHub and Zenodo render the
citation automatically.

---

## 8. Licence

* Code (`backend/`, `frontend/`, `scripts/`) — MIT, see `LICENSE`.
* Dataset (`data/`) — CC BY 4.0.
* KQAPro and CMNEE are not redistributed and remain under their original licences.

---

## 9. Contact

Corresponding author: Xiaoxing Zhao — xiaoxing12@yeah.net.

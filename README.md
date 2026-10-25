# MaintAgent

An AI maintenance agent for industrial machines: a failure-risk model trained on sensor data, plus an LLM agent that investigates faults with tools and drafts work orders behind human approval.

> Work in progress. This README will grow into the full write-up (architecture, results, design decisions).

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # then add your GROQ_API_KEY
```

## Data

Download the **Microsoft Azure Predictive Maintenance** dataset from Kaggle and put the five CSV files in `data/raw/`:
`PdM_telemetry.csv`, `PdM_errors.csv`, `PdM_maint.csv`, `PdM_failures.csv`, `PdM_machines.csv`.

```bash
python scripts/load_data.py      # loads the CSVs into data/maintagent.duckdb
python scripts/check_groq.py     # checks that tool calling works on Groq
python scripts/train_model.py    # trains the failure-risk model (time-based split)
pytest                           # runs the tests (no Kaggle data needed)
```

No Kaggle data yet? `python scripts/train_model.py --synthetic` runs the whole pipeline on generated data with the same schema. Synthetic results are not meaningful; they only show the code works.

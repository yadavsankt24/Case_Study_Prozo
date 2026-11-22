# Prozo EIR (Agentic AI): Case Studies 2 and 3

One FastAPI + MongoDB web app that holds two proof-of-concept solutions from the Prozo take-home.

| | Case Study 2 | Case Study 3 |
|---|---|---|
| **Problem** | Check a contractor's monthly wagesheet against the PF and ESIC ECRs | Watch each FC's daily P&L and alert the manager when it drifts |
| **Input** | Wagesheet (Excel/CSV) + PF ECR PDF + ESIC ECR PDF | Daily P&L (CSV/Excel) for one or more FCs |
| **Output** | Per-employee status, ₹ short-deposited, 6-sheet Excel report, "Ask" assistant | Colour per FC-day, anomaly log, insights, daily email digest, central dashboard |
| **Open in app** | `/case-study-2` | `/case-study-3` |
| **Full documentation** | [docs/case_study_2/README.md](docs/case_study_2/README.md) | [docs/case_study_3/README.md](docs/case_study_3/README.md) |

## Run it

```bash
./run.sh                     # creates .venv, installs requirements, starts on http://localhost:8000
# or: docker compose up --build
```

Copy `.env.example` to `.env` to set MongoDB, the LLM (Gemini / Ollama / none) and SMTP. Without MongoDB the app runs in demo mode with an in-memory database.

## Check it

```bash
python -m pytest                                  # 104 tests, both case studies
python scripts/case_study_2/evaluate.py           # Case Study 2: accuracy vs answer keys (100%)
python scripts/case_study_3/evaluate.py           # Case Study 3: sample colours + 124/124 scenarios
```

## Folder structure

Each case study has the same folder name in every top-level folder, so everything about one case study is easy to find.

```
prozo-compliance-poc/
├── app/
│   ├── main.py              app factory: registers each case study's API and pages
│   ├── config.py            settings from environment / .env
│   ├── container.py         builds the repositories and services (composition root)
│   ├── shared/              used by both: MongoDB connection, LLM clients, errors, home page
│   ├── case_study_2/        wagesheet vs PF/ESIC verification
│   ├── case_study_3/        daily FC P&L monitor and digest
│   ├── templates/           shared/ · case_study_2/ · case_study_3/
│   └── static/              css/ · js/shared/ · js/case_study_2/ · js/case_study_3/
├── data/                    case_study_2/ · case_study_3/   (sample + generated test data)
├── scripts/                 case_study_2/ · case_study_3/   (data generators, evaluators, CLI)
├── outputs/                 case_study_2/ · case_study_3/   (Excel reports from the test data)
├── tests/                   shared/ · case_study_2/ · case_study_3/
├── docs/                    case_study_2/ · case_study_3/   (READMEs, Word documents, screenshots)
├── Dockerfile · docker-compose.yml · run.sh · requirements.txt · .env.example
└── README.md                this file
```

Inside a case study, each file has one job (for example `rules.py` holds every business rule, `api.py` the endpoints, `pages.py` the web pages, `repository.py` the MongoDB access). The core logic does not import FastAPI or MongoDB, so the web app, the scripts and the tests all run the same code.

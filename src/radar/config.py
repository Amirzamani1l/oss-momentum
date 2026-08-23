"""Registry of tracked projects.

Adding a project is a one-line change here; nothing else in the
pipeline needs to know about it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Project:
    """A single tracked open-source project."""

    repo: str  # "owner/name" on GitHub
    category: str
    pypi: str | None = None  # PyPI distribution name, when it has one

    @property
    def slug(self) -> str:
        """Filesystem-safe identifier."""
        return self.repo.replace("/", "__")

    @property
    def name(self) -> str:
        return self.repo.split("/", 1)[1]


CATEGORIES: dict[str, str] = {
    "data-engineering": "Data engineering",
    "machine-learning": "Machine learning",
    "visualisation": "Visualisation & apps",
    "database": "Databases",
    "platform": "Platform & DevOps",
    "web-backend": "Web & backend",
}


PROJECTS: tuple[Project, ...] = (
    # --- data engineering -------------------------------------------------
    Project("pandas-dev/pandas", "data-engineering", "pandas"),
    Project("pola-rs/polars", "data-engineering", "polars"),
    Project("duckdb/duckdb", "data-engineering", "duckdb"),
    Project("apache/arrow", "data-engineering", "pyarrow"),
    Project("apache/airflow", "data-engineering", "apache-airflow"),
    Project("dbt-labs/dbt-core", "data-engineering", "dbt-core"),
    Project("dagster-io/dagster", "data-engineering", "dagster"),
    Project("PrefectHQ/prefect", "data-engineering", "prefect"),
    Project("ibis-project/ibis", "data-engineering", "ibis-framework"),
    Project("unionai-oss/pandera", "data-engineering", "pandera"),
    Project("apache/iceberg", "data-engineering", None),
    Project("delta-io/delta", "data-engineering", None),
    # --- machine learning -------------------------------------------------
    Project("scikit-learn/scikit-learn", "machine-learning", "scikit-learn"),
    Project("pytorch/pytorch", "machine-learning", "torch"),
    Project("huggingface/transformers", "machine-learning", "transformers"),
    Project("ray-project/ray", "machine-learning", "ray"),
    Project("mlflow/mlflow", "machine-learning", "mlflow"),
    Project("optuna/optuna", "machine-learning", "optuna"),
    Project("dmlc/xgboost", "machine-learning", "xgboost"),
    Project("microsoft/LightGBM", "machine-learning", "lightgbm"),
    # --- visualisation ----------------------------------------------------
    Project("plotly/plotly.py", "visualisation", "plotly"),
    Project("altair-viz/altair", "visualisation", "altair"),
    Project("streamlit/streamlit", "visualisation", "streamlit"),
    Project("gradio-app/gradio", "visualisation", "gradio"),
    Project("matplotlib/matplotlib", "visualisation", "matplotlib"),
    Project("apache/superset", "visualisation", "apache-superset"),
    # --- databases --------------------------------------------------------
    Project("postgres/postgres", "database", None),
    Project("ClickHouse/ClickHouse", "database", None),
    Project("redis/redis", "database", None),
    Project("questdb/questdb", "database", None),
    Project("timescale/timescaledb", "database", None),
    Project("valkey-io/valkey", "database", None),
    # --- platform ---------------------------------------------------------
    Project("kubernetes/kubernetes", "platform", None),
    Project("hashicorp/terraform", "platform", None),
    Project("grafana/grafana", "platform", None),
    Project("prometheus/prometheus", "platform", None),
    Project("open-telemetry/opentelemetry-collector", "platform", None),
    # --- web / backend ----------------------------------------------------
    Project("fastapi/fastapi", "web-backend", "fastapi"),
    Project("django/django", "web-backend", "Django"),
    Project("pallets/flask", "web-backend", "Flask"),
    Project("encode/httpx", "web-backend", "httpx"),
    Project("pydantic/pydantic", "web-backend", "pydantic"),
)


PROJECT_BY_REPO: dict[str, Project] = {p.repo: p for p in PROJECTS}


def projects_in(category: str) -> list[Project]:
    return [p for p in PROJECTS if p.category == category]

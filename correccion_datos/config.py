from __future__ import annotations

import os


def _load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        return
    load_dotenv()


_load_dotenv_if_available()


def env(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


API_BASE_URL = env("CD_API_BASE_URL", "http://seaap.minsa.gob.pe/")

DB_HOST = env("CD_DB_HOST", "31.220.84.86")
DB_USER = env("CD_DB_USER", "felix")
DB_PASSWORD = os.getenv("CD_DB_PASSWORD", "")
DB_NAME = env("CD_DB_NAME", "compromiso_uno")

DB_TABLE = env("CD_DB_TABLE", "padronnominal")
DB_DNI_FIELD = env("CD_DB_DNI_FIELD", "dni")
DB_FILTER_FIELD = env("CD_DB_FILTER_FIELD", "etapa")
DB_FILTER_VALUE = env("CD_DB_FILTER_VALUE", "2025-05-01")

MAP_APELLIDOS = env("CD_MAP_APELLIDOS", "")
MAP_NOMBRES = env("CD_MAP_NOMBRES", "")
MAP_FECHA_NAC = env("CD_MAP_FECHA_NAC", "")
MAP_NAME = env("CD_MAP_NAME", "nombres")
MAP_DIRECCION = env("CD_MAP_DIRECCION", "NuevaDireccion")


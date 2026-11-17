POSTGRES_ENGINES = {
    "django.db.backends.postgresql",
    "django.db.backends.postgresql_psycopg2",
}
POSTGIS_ENGINE = "django.contrib.gis.db.backends.postgis"


def use_postgis(databases):
    """A database provider's plain postgres:// URL gives Django the non-GIS engine,
    and every geometry query would then fail. Upgrade it."""
    for config in databases.values():
        if config.get("ENGINE") in POSTGRES_ENGINES:
            config["ENGINE"] = POSTGIS_ENGINE
    return databases
from alembic import context
from sqlalchemy import engine_from_config, pool
from logging.config import fileConfig
import os
import sys

# Add the project root to sys.path to allow importing the app
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

# Prevent circular migration calls and premature model queries during migration
os.environ["ALEMBIC_RUNNING"] = "1"

# Bring in the Flask app so Alembic knows the real DB URL and metadata
from aot.aot_flask.app import create_app
from aot.aot_flask.extensions import db
import aot.databases.models # Ensure all models are loaded

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Initialize Flask app context for Alembic
app = create_app()
app.app_context().push()

# If the Flask app provides the DB URL, inject it into Alembic's config
db_url = app.config.get("SQLALCHEMY_DATABASE_URI")
if db_url:
  config.set_main_option("sqlalchemy.url", db_url)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = db.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline():
    """
    Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = config.get_main_option("sqlalchemy.url")
    is_sqlite = (config.get_main_option("sqlalchemy.url") or "").startswith("sqlite")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        render_as_batch=is_sqlite,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """
    Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix='sqlalchemy.',
        poolclass=pool.NullPool)

    with connectable.connect() as connection:
        is_sqlite = (config.get_main_option("sqlalchemy.url") or "").startswith("sqlite")
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=is_sqlite,
        )

        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

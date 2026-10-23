import os
from alembic import context
from backend.storage.database import Database
from backend.storage.models import metadata

target_metadata = metadata

if context.is_offline_mode():
    url = os.environ["STUDY_DATABASE_URL"].replace("postgresql://", "postgresql+psycopg://", 1)
    context.configure(url=url, target_metadata=metadata, literal_binds=True, include_schemas=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    db = Database()
    with db.engine.connect() as connection:
        context.configure(connection=connection, target_metadata=metadata, include_schemas=True)
        with context.begin_transaction():
            context.run_migrations()

import os

from alembic import context
from sqlalchemy import create_engine, pool


from app.db.database import Base
import app.db.models

engine = create_engine(os.environ["DATABASE_URL"], poolclass=pool.NullPool)
with engine.connect() as conn:
    context.configure(connection=conn, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()

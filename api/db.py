from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from config import get_settings

# Database configuration
settings = get_settings()
database_url = f"postgresql+asyncpg://{settings.postgres_user}:{settings.postgres_password}@pgsql:5432/{settings.postgres_db}"

engine = create_async_engine(database_url, echo=settings.db_echo)

AsyncSessionLocal = async_sessionmaker(
    engine, 
    class_=AsyncSession, 
    expire_on_commit=False
)

class Base(DeclarativeBase):
    pass

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close() 
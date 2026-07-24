from collections.abc import AsyncIterator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import DATABASE_URL

# libpq-only query params Neon connection strings include that asyncpg's
# connect() doesn't accept as kwargs -- replaced with asyncpg's own `ssl` param.
_LIBPQ_ONLY_PARAMS = {"channel_binding", "sslmode"}


def to_async_url(url: str) -> str:
    """asyncpg needs the `postgresql+asyncpg://` scheme, and Neon is
    always-TLS, so libpq's `sslmode`/`channel_binding` become asyncpg's `ssl`."""
    scheme, netloc, path, query, fragment = urlsplit(url)
    if scheme in ("postgresql", "postgres"):
        scheme = "postgresql+asyncpg"
    kept = [(k, v) for k, v in parse_qsl(query) if k not in _LIBPQ_ONLY_PARAMS]
    kept.append(("ssl", "require"))
    return urlunsplit((scheme, netloc, path, urlencode(kept), fragment))


def create_app_async_engine(url: str):
    """Neon's pooled (`-pooler`) endpoints run PgBouncer in transaction mode,
    which is incompatible with asyncpg's server-side prepared-statement cache
    (causes 'another operation is in progress' / bind errors) -- disable it."""
    return create_async_engine(to_async_url(url), connect_args={"statement_cache_size": 0})


engine = create_app_async_engine(DATABASE_URL) if DATABASE_URL else None
async_session_factory = (
    async_sessionmaker(engine, expire_on_commit=False) if engine is not None else None
)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session

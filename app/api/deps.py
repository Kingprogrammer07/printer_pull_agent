from starlette.requests import HTTPConnection

from app.repositories.job_repository import JobRepository


def get_repo(connection: HTTPConnection) -> JobRepository:
    return connection.app.state.job_repo


def get_agent_manager(connection: HTTPConnection):
    return connection.app.state.agent_manager

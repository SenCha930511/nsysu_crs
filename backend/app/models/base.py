"""Declarative base. Constraint names are explicit everywhere so hand-written
migrations and models can never drift."""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    metadata = MetaData()

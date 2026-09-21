"""Inicialización del esquema OLTP para el sistema de vinculación.

La capa operativa no almacena nombres ni otros identificadores directos.
Las claves primarias son UUID seudonimizados y se guardan como texto para
mantener compatibilidad entre SQLite y PostgreSQL.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, time
from pathlib import Path

from sqlalchemy import CheckConstraint, DateTime, Float, String, Time, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base declarativa de las tablas OLTP."""


class Solicitud(Base):
    """Familia que requiere servicios de cuidado."""

    __tablename__ = "Solicitudes"
    __table_args__ = (
        CheckConstraint(
            "latitud IS NULL OR (latitud >= -90 AND latitud <= 90)",
            name="ck_solicitudes_latitud",
        ),
        CheckConstraint(
            "longitud IS NULL OR (longitud >= -180 AND longitud <= 180)",
            name="ck_solicitudes_longitud",
        ),
        CheckConstraint(
            "horario_requerido_fin > horario_requerido_inicio",
            name="ck_solicitudes_horario",
        ),
    )

    solicitud_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    alcaldia: Mapped[str] = mapped_column(String(100), nullable=False)
    colonia: Mapped[str] = mapped_column(String(150), nullable=False)
    latitud: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitud: Mapped[float | None] = mapped_column(Float, nullable=True)
    horario_requerido_inicio: Mapped[time] = mapped_column(Time, nullable=False)
    horario_requerido_fin: Mapped[time] = mapped_column(Time, nullable=False)
    dias_requeridos: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="Días ISO separados por coma, por ejemplo: lun,mar"
    )
    creado_en: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )


class Oferente(Base):
    """Persona cuidadora disponible para ofrecer servicios."""

    __tablename__ = "Oferentes"
    __table_args__ = (
        CheckConstraint(
            "latitud IS NULL OR (latitud >= -90 AND latitud <= 90)",
            name="ck_oferentes_latitud",
        ),
        CheckConstraint(
            "longitud IS NULL OR (longitud >= -180 AND longitud <= 180)",
            name="ck_oferentes_longitud",
        ),
        CheckConstraint(
            "horario_ofrecido_fin > horario_ofrecido_inicio",
            name="ck_oferentes_horario",
        ),
    )

    oferente_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    alcaldia: Mapped[str] = mapped_column(String(100), nullable=False)
    colonia: Mapped[str] = mapped_column(String(150), nullable=False)
    latitud: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitud: Mapped[float | None] = mapped_column(Float, nullable=True)
    horario_ofrecido_inicio: Mapped[time] = mapped_column(Time, nullable=False)
    horario_ofrecido_fin: Mapped[time] = mapped_column(Time, nullable=False)
    dias_ofrecidos: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="Días ISO separados por coma, por ejemplo: lun,mar"
    )
    creado_en: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )


def crear_base_de_datos(ruta: str | Path = "sistema_vinculacion.db") -> None:
    """Crea las tablas OLTP si todavía no existen."""

    database_url = os.getenv("DATABASE_URL") or f"sqlite:///{Path(ruta)}"
    engine = create_engine(database_url)
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()


if __name__ == "__main__":
    crear_base_de_datos()
    print("Base de datos OLTP inicializada correctamente.")
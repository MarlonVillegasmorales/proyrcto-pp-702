"""Motor base de vinculación para el piloto del sistema de cuidados.

El motor trabaja únicamente con identificadores seudonimizados y las columnas
operativas de ``Solicitudes`` y ``Oferentes``. No incorpora nombres, género ni
otros atributos personales.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Any

import numpy as np
import pandas as pd
from sklearn.neighbors import NearestNeighbors


class MotorMatching:
    """Empareja solicitudes y oferentes por horario y proximidad geográfica.

    El algoritmo primero exige compatibilidad de días y ventana horaria.
    Después usa ``NearestNeighbors`` con métrica haversiana para limitar los
    candidatos a ``max_distance_km`` y calcula una puntuación reproducible:
    60 % proximidad y 40 % cobertura horaria/días.

    Limitaciones UCA 5/UCA 6:
    - La distancia geográfica puede actuar como proxy socioeconómico y
      favorecer zonas con mayor densidad de oferentes; no prueba calidad,
      seguridad ni idoneidad del cuidado.
    - No se usan variables de género, pero el modelo no puede medir brechas
      de género porque las tablas OLTP no contienen esa variable. El resultado
      no debe interpretarse como ausencia de sesgo.
    - La asignación es uno-a-uno porque el esquema no define capacidad de
      atención de un oferente. Esto puede dejar demanda sin atender aunque
      una persona pudiera cubrir varios servicios.
    - Si la demanda supera la oferta compatible en una zona, no se fuerza un
      emparejamiento: se devuelve ``demanda_supera_oferta_zona`` y se conserva
      la solicitud para que el Dashboard reporte la necesidad no atendida.
    """

    SOLICITUD_REQUIRED = {
        "solicitud_id",
        "latitud",
        "longitud",
        "horario_requerido_inicio",
        "horario_requerido_fin",
        "dias_requeridos",
    }
    OFERENTE_REQUIRED = {
        "oferente_id",
        "latitud",
        "longitud",
        "horario_ofrecido_inicio",
        "horario_ofrecido_fin",
        "dias_ofrecidos",
    }

    def __init__(
        self,
        *,
        max_distance_km: float = 10.0,
        distancia_weight: float = 0.6,
        horario_weight: float = 0.4,
    ) -> None:
        if max_distance_km <= 0:
            raise ValueError("max_distance_km debe ser mayor que cero.")
        if distancia_weight < 0 or horario_weight < 0:
            raise ValueError("Los pesos no pueden ser negativos.")
        if distancia_weight + horario_weight == 0:
            raise ValueError("Al menos un peso debe ser mayor que cero.")
        self.max_distance_km = max_distance_km
        total = distancia_weight + horario_weight
        self.distancia_weight = distancia_weight / total
        self.horario_weight = horario_weight / total

    def emparejar(
        self,
        solicitudes: pd.DataFrame,
        oferentes: pd.DataFrame,
    ) -> pd.DataFrame:
        """Retorna un resultado por solicitud, emparejada o no.

        Las columnas de salida incluyen ``estado``, ``motivo``,
        ``distancia_km``, ``compatibilidad_horaria`` y ``puntuacion`` para
        que el Dashboard pueda auditar cobertura y demanda no atendida.
        """

        solicitudes = self._validar_y_copiar(
            solicitudes, self.SOLICITUD_REQUIRED, "Solicitudes"
        )
        oferentes = self._validar_y_copiar(
            oferentes, self.OFERENTE_REQUIRED, "Oferentes"
        )
        solicitudes["_inicio"] = solicitudes["horario_requerido_inicio"].map(
            self._parse_time
        )
        solicitudes["_fin"] = solicitudes["horario_requerido_fin"].map(self._parse_time)
        solicitudes["_dias"] = solicitudes["dias_requeridos"].map(self._parse_days)
        oferentes["_inicio"] = oferentes["horario_ofrecido_inicio"].map(self._parse_time)
        oferentes["_fin"] = oferentes["horario_ofrecido_fin"].map(self._parse_time)
        oferentes["_dias"] = oferentes["dias_ofrecidos"].map(self._parse_days)

        self._validar_intervalos(solicitudes, "_inicio", "_fin", "Solicitud")
        self._validar_intervalos(oferentes, "_inicio", "_fin", "Oferente")

        candidatos = self._candidatos_geograficos(solicitudes, oferentes)
        usados: set[str] = set()
        resultados: list[dict[str, Any]] = []
        for _, solicitud in solicitudes.iterrows():
            posibles = candidatos.get(solicitud["solicitud_id"], [])
            compatibles = [
                candidato
                for candidato in posibles
                if candidato["oferente_id"] not in usados
                and self._compatible_horario(solicitud, candidato)
            ]
            if compatibles:
                mejor = max(
                    compatibles,
                    key=lambda candidato: self._puntuacion(solicitud, candidato),
                )
                usados.add(mejor["oferente_id"])
                resultados.append(
                    self._resultado(solicitud, mejor, "emparejada", "compatible")
                )
                continue
            resultados.append(
                self._resultado(
                    solicitud,
                    None,
                    "no_emparejada",
                    self._motivo_no_emparejada(solicitud, oferentes, posibles),
                )
            )
        return pd.DataFrame(resultados)

    @staticmethod
    def _validar_y_copiar(
        frame: pd.DataFrame, required: set[str], nombre: str
    ) -> pd.DataFrame:
        if not isinstance(frame, pd.DataFrame):
            raise TypeError(f"{nombre} debe ser un pandas.DataFrame.")
        missing = required.difference(frame.columns)
        if missing:
            raise ValueError(f"{nombre} no contiene columnas requeridas: {sorted(missing)}")
        if frame.empty:
            return frame.copy()
        copy = frame.copy()
        for column in ("latitud", "longitud"):
            copy[column] = pd.to_numeric(copy[column], errors="coerce")
        invalid_latitude = copy["latitud"].notna() & ~copy["latitud"].between(-90, 90)
        invalid_longitude = copy["longitud"].notna() & ~copy["longitud"].between(-180, 180)
        if invalid_latitude.any() or invalid_longitude.any():
            raise ValueError(f"{nombre} contiene coordenadas fuera de rango.")
        if copy["solicitud_id" if nombre == "Solicitudes" else "oferente_id"].isna().any():
            raise ValueError(f"{nombre} contiene identificadores nulos.")
        return copy

    @staticmethod
    def _parse_time(value: object) -> time:
        if isinstance(value, time):
            return value
        if isinstance(value, datetime):
            return value.time()
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            raise ValueError(f"Horario inválido: {value!r}")
        return parsed.time()

    @staticmethod
    def _parse_days(value: object) -> frozenset[str]:
        if pd.isna(value):
            raise ValueError("Los días no pueden ser nulos.")
        days = frozenset(day.strip().lower() for day in str(value).split(",") if day.strip())
        if not days:
            raise ValueError("Debe existir al menos un día disponible/requerido.")
        return days

    @staticmethod
    def _validar_intervalos(
        frame: pd.DataFrame, inicio: str, fin: str, nombre: str
    ) -> None:
        invalid = frame.apply(lambda row: row[inicio] >= row[fin], axis=1)
        if invalid.any():
            raise ValueError(f"{nombre}: el horario final debe ser posterior al inicial.")

    def _candidatos_geograficos(
        self, solicitudes: pd.DataFrame, oferentes: pd.DataFrame
    ) -> dict[str, list[dict[str, Any]]]:
        resultado = {str(identifier): [] for identifier in solicitudes["solicitud_id"]}
        valid_offers = oferentes.dropna(subset=["latitud", "longitud"]).copy()
        valid_requests = solicitudes.dropna(subset=["latitud", "longitud"])
        if valid_offers.empty or valid_requests.empty:
            return resultado

        radians_offers = np.radians(valid_offers[["latitud", "longitud"]].to_numpy())
        model = NearestNeighbors(metric="haversine", algorithm="ball_tree")
        model.fit(radians_offers)
        distances, indices = model.radius_neighbors(
            np.radians(valid_requests[["latitud", "longitud"]].to_numpy()),
            radius=self.max_distance_km / 6371.0088,
            sort_results=True,
        )
        for request_position, (_, request) in enumerate(valid_requests.iterrows()):
            request_id = str(request["solicitud_id"])
            for distance, offer_position in zip(
                distances[request_position], indices[request_position]
            ):
                offer = valid_offers.iloc[offer_position].to_dict()
                offer["distancia_km"] = float(distance * 6371.0088)
                resultado[request_id].append(offer)
        return resultado

    @staticmethod
    def _compatible_horario(solicitud: pd.Series, oferente: dict[str, Any]) -> bool:
        return (
            solicitud["_dias"].issubset(oferente["_dias"])
            and oferente["_inicio"] <= solicitud["_inicio"]
            and oferente["_fin"] >= solicitud["_fin"]
        )

    def _puntuacion(self, solicitud: pd.Series, oferente: dict[str, Any]) -> float:
        distancia_score = max(0.0, 1.0 - oferente["distancia_km"] / self.max_distance_km)
        dias_score = len(solicitud["_dias"]) / len(oferente["_dias"])
        duracion_solicitud = self._minutes(solicitud["_fin"]) - self._minutes(
            solicitud["_inicio"]
        )
        duracion_oferta = self._minutes(oferente["_fin"]) - self._minutes(
            oferente["_inicio"]
        )
        horario_score = (duracion_solicitud / duracion_oferta) * dias_score
        return self.distancia_weight * distancia_score + self.horario_weight * horario_score

    @staticmethod
    def _minutes(value: time) -> int:
        return value.hour * 60 + value.minute

    def _resultado(
        self,
        solicitud: pd.Series,
        oferente: dict[str, Any] | None,
        estado: str,
        motivo: str,
    ) -> dict[str, Any]:
        if oferente is None:
            return {
                "solicitud_id": solicitud["solicitud_id"],
                "oferente_id": None,
                "estado": estado,
                "motivo": motivo,
                "distancia_km": None,
                "compatibilidad_horaria": False,
                "puntuacion": None,
            }
        return {
            "solicitud_id": solicitud["solicitud_id"],
            "oferente_id": oferente["oferente_id"],
            "estado": estado,
            "motivo": motivo,
            "distancia_km": round(oferente["distancia_km"], 3),
            "compatibilidad_horaria": True,
            "puntuacion": round(self._puntuacion(solicitud, oferente), 4),
        }

    def _motivo_no_emparejada(
        self,
        solicitud: pd.Series,
        oferentes: pd.DataFrame,
        posibles: list[dict[str, Any]],
    ) -> str:
        if oferentes.empty:
            return "sin_oferta_disponible"
        if pd.isna(solicitud["latitud"]) or pd.isna(solicitud["longitud"]):
            return "ubicacion_ausente"
        if not posibles:
            return "demanda_supera_oferta_zona"
        if not any(self._compatible_horario(solicitud, offer) for offer in posibles):
            return "sin_compatibilidad_horaria"
        return "demanda_supera_oferta_zona"
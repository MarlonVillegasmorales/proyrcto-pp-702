"""ETL territorial para el Observatorio de la Economía del Cuidado.

El resultado conserva una fila por alcaldía de la CDMX. La infraestructura
del Shapefile se agrega antes de unirla con las fuentes tabulares para evitar
duplicar los indicadores territoriales por cada colonia o polígono.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Iterable

import geopandas as gpd
import pandas as pd


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_OBSERVATORIO = ROOT_DIR / "datos_observatorio_cuidado_alcaldias_cdmx.csv"
DEFAULT_CENSO = ROOT_DIR / "base_censo_CDMX_observatorio_v1.csv"
DEFAULT_ENUT = ROOT_DIR / "ENUT_2024_CDMX_resumen_ponderado.csv"
DEFAULT_SHAPEFILE = (
    ROOT_DIR / "visualizacion" / "Equipamiento_de_asistencia_social.shp"
)


def _normalizar_alcaldia(valor: object) -> str | None:
    """Devuelve una llave comparable para nombres de alcaldías."""

    if pd.isna(valor):
        return None
    texto = str(valor).strip().upper().replace("&", " Y ")
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(caracter for caracter in texto if not unicodedata.combining(caracter))
    texto = re.sub(r"[^A-Z0-9]+", " ", texto).strip()
    aliases = {
        "ALVARO OBREGON": "ALVARO OBREGON",
        "LVARO OBREGON": "ALVARO OBREGON",
        "BENITO JU REZ": "BENITO JUAREZ",
        "BENITO JUAREZ": "BENITO JUAREZ",
        "COYOAC N": "COYOACAN",
        "COYOACAN": "COYOACAN",
        "CUAUHT MOC": "CUAUHTEMOC",
        "CUAUHTEMOC": "CUAUHTEMOC",
        "TLAHUAC": "TLAHUAC",
    }
    return aliases.get(texto, texto)


def _limpiar_tabla(tabla: pd.DataFrame) -> pd.DataFrame:
    """Normaliza encabezados y elimina filas completamente vacías."""

    limpia = tabla.copy()
    limpia.columns = [
        str(columna).replace("\ufeff", "").strip() for columna in limpia.columns
    ]
    limpia = limpia.dropna(how="all").reset_index(drop=True)
    if "alcaldia" in limpia.columns:
        limpia["alcaldia"] = limpia["alcaldia"].map(_normalizar_alcaldia)
    return limpia


def cargar_tabulares(
    rutas: Iterable[str | Path],
    *,
    encoding: str = "utf-8-sig",
) -> dict[str, pd.DataFrame]:
    """Carga y limpia archivos CSV tabulares indexados por nombre de archivo."""

    tablas: dict[str, pd.DataFrame] = {}
    for ruta in rutas:
        path = Path(ruta)
        if not path.is_file():
            raise FileNotFoundError(f"No existe el archivo tabular: {path}")
        tablas[path.stem] = _limpiar_tabla(pd.read_csv(path, encoding=encoding))
    return tablas


def cargar_shapefile(ruta: str | Path = DEFAULT_SHAPEFILE) -> gpd.GeoDataFrame:
    """Carga el Shapefile y valida sus columnas geográficas esenciales."""

    path = Path(ruta)
    if not path.is_file():
        raise FileNotFoundError(f"No existe el Shapefile: {path}")
    mapa = gpd.read_file(path)
    requeridas = {"alcaldia", "geometry"}
    faltantes = requeridas.difference(mapa.columns)
    if faltantes:
        raise ValueError(
            f"El Shapefile no contiene las columnas requeridas: {sorted(faltantes)}"
        )
    mapa = mapa.loc[mapa.geometry.notna() & ~mapa.geometry.is_empty].copy()
    mapa["alcaldia"] = mapa["alcaldia"].map(_normalizar_alcaldia)
    return mapa


def _agregar_infraestructura(mapa: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Disuelve polígonos por alcaldía y suma sus atributos de infraestructura."""

    mapa = mapa.loc[mapa["alcaldia"].notna()].copy()
    columnas_suma = [
        columna
        for columna in ("No_Guard", "C_No_Guard", "pob_2010")
        if columna in mapa.columns
    ]
    agregados = mapa.dissolve(
        by="alcaldia",
        aggfunc={columna: "sum" for columna in columnas_suma},
    ).reset_index()
    conteos = (
        mapa.groupby("alcaldia", as_index=False)
        .size()
        .rename(columns={"size": "poligonos_infraestructura"})
    )
    agregados = agregados.merge(conteos, on="alcaldia", validate="one_to_one")
    return gpd.GeoDataFrame(agregados, geometry="geometry", crs=mapa.crs)


def _agregar_enut(enut: pd.DataFrame) -> dict[str, float]:
    """Calcula KPIs agregados de pobreza de tiempo sin territorializarlos."""

    requeridas = {
        "poblacion_estimada_12_mas",
        "personas_estimadas_que_realizan_cuidado",
        "horas_promedio_semanales_cuidado_todos",
    }
    faltantes = requeridas.difference(enut.columns)
    if faltantes:
        raise ValueError(f"ENUT no contiene columnas requeridas: {sorted(faltantes)}")
    poblacion = enut["poblacion_estimada_12_mas"].sum()
    cuidado = enut["personas_estimadas_que_realizan_cuidado"].sum()
    horas = (
        enut["horas_promedio_semanales_cuidado_todos"] * enut["poblacion_estimada_12_mas"]
    ).sum() / poblacion
    return {
        "enut_poblacion_12_mas": float(poblacion),
        "enut_personas_que_cuidan": float(cuidado),
        "enut_porcentaje_que_cuida": float(cuidado / poblacion * 100),
        "enut_horas_promedio_cuidado": float(horas),
    }


def construir_dataset_consolidado(
    *,
    ruta_observatorio: str | Path = DEFAULT_OBSERVATORIO,
    ruta_censo: str | Path = DEFAULT_CENSO,
    ruta_enut: str | Path = DEFAULT_ENUT,
    ruta_shapefile: str | Path = DEFAULT_SHAPEFILE,
) -> gpd.GeoDataFrame:
    """Integra infraestructura, censos y KPIs de cuidado para el Dashboard."""

    tablas = cargar_tabulares([ruta_observatorio, ruta_censo, ruta_enut])
    observatorio = tablas[Path(ruta_observatorio).stem]
    censo = tablas[Path(ruta_censo).stem]
    enut = tablas[Path(ruta_enut).stem]

    observatorio = observatorio.loc[observatorio["alcaldia"] != "TOTAL CDMX"].copy()
    censo = censo.drop_duplicates(subset="alcaldia")
    territorial = observatorio.merge(
        censo,
        on="alcaldia",
        how="outer",
        suffixes=("", "_censo"),
        validate="one_to_one",
    )
    infraestructura = _agregar_infraestructura(cargar_shapefile(ruta_shapefile))
    consolidado = infraestructura.merge(
        territorial,
        on="alcaldia",
        how="outer",
        validate="one_to_one",
    )
    consolidado = gpd.GeoDataFrame(
        consolidado, geometry="geometry", crs=infraestructura.crs
    )

    if "cobertura_caci_0_2_pct" in consolidado:
        consolidado["brecha_cobertura_caci_0_2_pct"] = (
            100 - consolidado["cobertura_caci_0_2_pct"]
        )
    if {"No_Guard", "pob_Total"}.issubset(consolidado.columns):
        consolidado["guarderias_por_1000_habitantes"] = (
            consolidado["No_Guard"] / consolidado["pob_Total"] * 1000
        )
    consolidado = consolidado.sort_values("alcaldia").reset_index(drop=True)
    consolidado.attrs["indicadores_pobreza_tiempo_cdmx"] = _agregar_enut(enut)
    consolidado.attrs["fuente_pobreza_tiempo"] = Path(ruta_enut).name
    return consolidado


if __name__ == "__main__":
    dataset = construir_dataset_consolidado()
    print(
        f"Dataset consolidado: {len(dataset)} alcaldías, "
        f"{len(dataset.columns)} columnas, CRS {dataset.crs}"
    )
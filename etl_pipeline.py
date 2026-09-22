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
DEFAULT_MACRO = ROOT_DIR / "indicadores_macro_economia_cuidado.csv"
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


def _validar_indicadores_macro(macro: pd.DataFrame) -> dict[str, str]:
    """Valida y conserva los indicadores macroeconómicos declarados como fuente."""

    requeridas = {"indicador", "valor", "fuente"}
    faltantes = requeridas.difference(macro.columns)
    if faltantes:
        raise ValueError(
            "Indicadores macro no contiene columnas requeridas: "
            f"{sorted(faltantes)}"
        )
    return {
        str(fila["indicador"]): str(fila["valor"])
        for _, fila in macro.iterrows()
        if pd.notna(fila["indicador"])
    }


def _poblacion_dependiente(censo: pd.DataFrame) -> pd.Series:
    """Suma la población de 0 a 14 y de 60 años o más del Censo."""

    grupos_edad = [
        "pob_De 0 a 4 años",
        "pob_De 5 a 9 años",
        "pob_De 10 a 14 años",
        "pob_De 60 a 64 años",
        "pob_De 65 a 69 años",
        "pob_De 70 a 74 años",
        "pob_De 75 a 79 años",
        "pob_De 80 a 84 años",
        "pob_85 años y más",
    ]
    faltantes = [columna for columna in grupos_edad if columna not in censo.columns]
    if faltantes:
        raise ValueError(
            "Censo no contiene columnas de población dependiente: "
            + ", ".join(faltantes)
        )
    return censo[grupos_edad].apply(pd.to_numeric, errors="coerce").fillna(0).sum(axis=1)


def _calcular_abandono_laboral_cuidados(
    enut: pd.DataFrame, territorial: pd.DataFrame, censo: pd.DataFrame
) -> pd.Series:
    """Obtiene el abandono laboral por cuidados y lo asigna a cada alcaldía.

    La ENUT no tiene desglose territorial. Cuando una fuente territorial no
    aporta el indicador, el total CDMX se distribuye según la población
    dependiente del Censo.
    """

    columna_exacta = "abandono_laboral_cuidados"
    if columna_exacta in territorial.columns:
        valores = pd.to_numeric(territorial[columna_exacta], errors="coerce")
        if valores.notna().all():
            return valores

    if {
        "personas_estimadas_que_abandonan_el_mercado_laboral_por_cuidado",
    }.issubset(enut.columns):
        total_abandono = pd.to_numeric(
            enut["personas_estimadas_que_abandonan_el_mercado_laboral_por_cuidado"],
            errors="coerce",
        ).sum()
    else:
        columnas_requeridas = {
            "personas_estimadas_que_realizan_cuidado",
            "personas_estimadas_cuidado_y_trabajo_mercado",
        }
        faltantes = columnas_requeridas.difference(enut.columns)
        if faltantes:
            raise ValueError(
                "ENUT no permite calcular abandono laboral por cuidados; "
                f"faltan columnas: {sorted(faltantes)}"
            )
        cuidado = pd.to_numeric(
            enut["personas_estimadas_que_realizan_cuidado"], errors="coerce"
        ).fillna(0)
        cuidado_y_trabajo = pd.to_numeric(
            enut["personas_estimadas_cuidado_y_trabajo_mercado"], errors="coerce"
        ).fillna(0)
        total_abandono = (cuidado - cuidado_y_trabajo).clip(lower=0).sum()

    dependientes = _poblacion_dependiente(censo)
    total_dependientes = dependientes.sum()
    if total_dependientes <= 0:
        raise ValueError(
            "No se puede estimar abandono laboral: la población dependiente "
            "del Censo no tiene un total positivo."
        )
    participacion = dependientes / total_dependientes
    return (
        territorial["alcaldia"]
        .map(dict(zip(censo["alcaldia"], participacion)))
        .fillna(0)
        * float(total_abandono)
    )


def construir_dataset_consolidado(
    *,
    ruta_observatorio: str | Path = DEFAULT_OBSERVATORIO,
    ruta_censo: str | Path = DEFAULT_CENSO,
    ruta_enut: str | Path = DEFAULT_ENUT,
    ruta_macro: str | Path = DEFAULT_MACRO,
    ruta_shapefile: str | Path = DEFAULT_SHAPEFILE,
) -> gpd.GeoDataFrame:
    """Integra exclusivamente las cinco fuentes de evidencia del proyecto."""

    tablas = cargar_tabulares(
        [ruta_observatorio, ruta_censo, ruta_enut, ruta_macro]
    )
    observatorio = tablas[Path(ruta_observatorio).stem]
    censo = tablas[Path(ruta_censo).stem]
    enut = tablas[Path(ruta_enut).stem]
    macro = tablas[Path(ruta_macro).stem]

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
    consolidado["abandono_laboral_cuidados"] = _calcular_abandono_laboral_cuidados(
        enut, consolidado, censo
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
    consolidado.attrs["indicadores_macro_economia_cuidado"] = (
        _validar_indicadores_macro(macro)
    )
    consolidado.attrs["fuentes_evidencia"] = tuple(
        Path(ruta).name
        for ruta in (
            ruta_enut,
            ruta_censo,
            ruta_shapefile,
            ruta_observatorio,
            ruta_macro,
        )
    )
    return consolidado


if __name__ == "__main__":
    dataset = construir_dataset_consolidado()
    print(
        f"Dataset consolidado: {len(dataset)} alcaldías, "
        f"{len(dataset.columns)} columnas, CRS {dataset.crs}"
    )
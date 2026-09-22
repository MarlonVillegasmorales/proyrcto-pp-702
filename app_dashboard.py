"""Dashboard accesible del Observatorio de la Economía del Cuidado.

Ejecutar con: ``streamlit run app_dashboard.py``.
"""

from __future__ import annotations

import html
import re
import unicodedata
from datetime import time
from pathlib import Path

import folium
import pandas as pd
import streamlit as st
from branca.colormap import linear
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from streamlit_folium import st_folium

from database_setup import Base, Oferente, Solicitud
from etl_pipeline import construir_dataset_consolidado
from modelo_matching import MotorMatching


CAPACIDAD_PROMEDIO_GUARDERIA = 100
RADIO_MATCHING_KM = 10.0
DATABASE_PATH = Path(__file__).resolve().parent / "sistema_vinculacion.db"
FUENTE_ACADEMICA = (
    "Fuente: Elaboración propia del Observatorio del Cuidado CDMX con datos "
    "geográficos y censales (INEGI 2020), infraestructura de asistencia social "
    "y estimaciones de la Encuesta Nacional para el Sistema de Cuidados "
    "(ENUT 2024)."
)

st.set_page_config(
    layout="wide",
    page_title="Observatorio del Cuidado CDMX",
    page_icon="💜",
)

st.markdown(
    """
    <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}
        html, body, [class*="css"] {
            color: #31333F;
        }
        [data-testid="stAppViewContainer"] {
            background: #F0F2F6;
            color: #31333F;
        }
        [data-testid="stHeader"] {
            background: #F0F2F6;
        }
        .block-container {
            padding-top: 2.5rem;
            padding-bottom: 3rem;
        }
        [data-testid="stAppViewContainer"] h1,
        [data-testid="stAppViewContainer"] h2,
        [data-testid="stAppViewContainer"] h3,
        [data-testid="stAppViewContainer"] p,
        [data-testid="stAppViewContainer"] label,
        [data-testid="stAppViewContainer"] [data-testid="stMarkdownContainer"] {
            color: #31333F;
        }
        [data-testid="stMetric"] {
            background: #FFFFFF;
            border: 1px solid #D7D9E0;
            border-radius: 16px;
            padding: 1rem 1.1rem;
            box-shadow: 0 8px 24px rgba(30, 41, 59, 0.10);
        }
        [data-testid="stMetricLabel"],
        [data-testid="stMetricValue"],
        [data-testid="stMetricDelta"] {
            color: #31333F !important;
        }
        [data-baseweb="tab-list"] {
            background: #FFFFFF;
            border-radius: 12px;
            padding: 0.25rem;
        }
        [data-baseweb="tab"] {
            color: #31333F !important;
            font-weight: 600;
        }
        [data-baseweb="tab"][aria-selected="true"] {
            color: #5B21B6 !important;
            border-bottom-color: #5B21B6 !important;
        }
        [data-testid="stTextInput"] input,
        [data-testid="stNumberInput"] input,
        [data-testid="stTimeInput"] input,
        [data-testid="stSelectbox"] > div,
        [data-testid="stMultiSelect"] > div {
            background: #FFFFFF;
            color: #31333F;
        }
        [data-testid="stAlert"] {
            color: #31333F;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(show_spinner="Cargando evidencia territorial...")
def cargar_evidencia():
    dataset = construir_dataset_consolidado()
    dataset = dataset.copy()
    dataset["poblacion_dependiente"] = _calcular_poblacion_dependiente(dataset)
    dataset["poblacion_cubierta"] = (
        pd.to_numeric(dataset["No_Guard"], errors="coerce").fillna(0)
        * CAPACIDAD_PROMEDIO_GUARDERIA
    )
    dataset["personas_afectadas"] = (
        dataset["poblacion_dependiente"] - dataset["poblacion_cubierta"]
    ).clip(lower=0)
    return dataset


def _normalizar_columna(columna: object) -> str:
    texto = unicodedata.normalize("NFKD", str(columna))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", texto.lower())


def _calcular_poblacion_dependiente(dataset: pd.DataFrame) -> pd.Series:
    """Suma infancias de 0-14 y personas de 60+ del censo territorial."""

    columnas = {_normalizar_columna(columna): columna for columna in dataset.columns}
    prefijos = [
        "pobde0a4",
        "pobde5a9",
        "pobde10a14",
        "pobde60a64",
        "pobde65a69",
        "pobde70a74",
        "pobde75a79",
        "pobde80a84",
        "pob85",
    ]
    seleccionadas = {
        prefijo: next(
            (columna for normalizada, columna in columnas.items() if normalizada.startswith(prefijo)),
            None,
        )
        for prefijo in prefijos
    }
    faltantes = [prefijo for prefijo, columna in seleccionadas.items() if columna is None]
    if faltantes:
        raise ValueError(
            "No se pudieron identificar grupos de edad dependiente del censo: "
            + ", ".join(faltantes)
        )
    return dataset[[columna for columna in seleccionadas.values() if columna is not None]].apply(
        pd.to_numeric, errors="coerce"
    ).fillna(0).sum(axis=1)


def _formato_alcaldia(valor: str) -> str:
    return str(valor).title()


def _crear_mapa(dataset: pd.DataFrame, metrica: str) -> folium.Map:
    mapa_data = dataset.to_crs(epsg=4326).copy()
    columna_metrica = {
        "Déficit de Infraestructura (Guarderías)": "personas_afectadas",
        "Abandono Laboral por Cuidados": "abandono_laboral_cuidados",
    }[metrica]
    valores = pd.to_numeric(mapa_data[columna_metrica], errors="coerce").fillna(0)
    minimo = float(valores.min())
    maximo = max(float(valores.max()), minimo + 1)
    escala = (
        linear.Purples_09.scale(minimo, maximo)
        if columna_metrica == "abandono_laboral_cuidados"
        else linear.Blues_09.scale(minimo, maximo)
    )
    escala.caption = metrica

    mapa = folium.Map(
        location=[19.33, -99.15],
        zoom_start=10,
        tiles="CartoDB positron",
        control_scale=True,
    )
    for _, fila in mapa_data.iterrows():
        nombre = _formato_alcaldia(fila["alcaldia"])
        valor_metrica = pd.to_numeric(fila[columna_metrica], errors="coerce")
        valor_metrica = 0.0 if pd.isna(valor_metrica) else float(valor_metrica)
        text = (
            f"Alcaldía: {html.escape(nombre)}<br>"
            f"Déficit de cupos: {fila['personas_afectadas']:,.0f} "
            "infantes sin guardería.<br>"
            f"Abandono laboral: {fila['abandono_laboral_cuidados']:,.0f} "
            "personas dejaron su empleo para cuidar."
        )
        folium.GeoJson(
            data=fila.geometry.__geo_interface__,
            style_function=lambda _, color=escala(valor_metrica): {
                "fillColor": color,
                "color": "#475569",
                "weight": 1.2,
                "fillOpacity": 0.86,
            },
            highlight_function=lambda _: {
                "weight": 3,
                "color": "#7c3aed",
                "fillOpacity": 0.95,
            },
        ).add_child(folium.Tooltip(text, sticky=True)).add_to(mapa)
    escala.add_to(mapa)
    return mapa


def _metricas_principales(dataset: pd.DataFrame) -> None:
    total_guarderias = dataset["No_Guard"].sum()
    total_dependiente = dataset["poblacion_dependiente"].sum()
    total_afectadas = dataset["personas_afectadas"].sum()
    columnas = st.columns(3)
    columnas[0].metric("Total de guarderías", f"{total_guarderias:,.0f}")
    columnas[1].metric(
        "Población dependiente",
        f"{total_dependiente:,.0f} personas",
    )
    columnas[2].metric(
        "Personas afectadas sin acceso",
        f"{total_afectadas:,.0f} personas",
    )


def _mostrar_contexto_enut(dataset: pd.DataFrame) -> None:
    indicadores = dataset.attrs["indicadores_pobreza_tiempo_cdmx"]
    st.caption(
        "Contexto ENUT para la CDMX: la fuente no contiene alcaldía, por lo que "
        "sus valores no se asignan artificialmente a cada polígono."
    )
    columnas = st.columns(3)
    columnas[0].metric(
        "Personas que realizan cuidado",
        f"{indicadores['enut_personas_que_cuidan']:,.0f}",
    )
    columnas[1].metric(
        "Población que cuida",
        f"{indicadores['enut_porcentaje_que_cuida']:.1f}%",
    )
    columnas[2].metric(
        "Horas semanales de cuidado",
        f"{indicadores['enut_horas_promedio_cuidado']:.1f}",
    )


def mostrar_visor_territorial(dataset) -> None:
    st.header("Visor Territorial")
    st.write(
        "Explora el impacto territorial del cuidado con una métrica a la vez. "
        f"Se estima una capacidad de {CAPACIDAD_PROMEDIO_GUARDERIA} personas "
        "por guardería para convertir infraestructura en impacto absoluto."
    )
    metrica = st.radio(
        "Métrica del mapa",
        [
            "Déficit de Infraestructura (Guarderías)",
            "Abandono Laboral por Cuidados",
        ],
        horizontal=True,
    )
    _mostrar_contexto_enut(dataset)
    st_folium(_crear_mapa(dataset, metrica), use_container_width=True, height=560)
    st.caption(FUENTE_ACADEMICA)
    tabla = dataset[
        [
            "alcaldia",
            "poblacion_dependiente",
            "No_Guard",
            "personas_afectadas",
            "abandono_laboral_cuidados",
        ]
    ].copy()
    tabla["alcaldia"] = tabla["alcaldia"].map(_formato_alcaldia)
    tabla.columns = [
        "Alcaldía",
        "Población que requiere cuidado",
        "Guarderías disponibles",
        "Personas afectadas sin acceso",
        "Abandono laboral por cuidados",
    ]
    st.dataframe(
        tabla.style.format(
            {
                "Población que requiere cuidado": "{:,.0f}",
                "Guarderías disponibles": "{:,.0f}",
                "Personas afectadas sin acceso": "{:,.0f}",
                "Abandono laboral por cuidados": "{:,.0f}",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )


def seed_datos_simulacion(
    dataset: pd.DataFrame,
    alcaldia: str,
    ruta_db: str | Path = DATABASE_PATH,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Si hace falta, siembra el piloto con proporciones del Censo territorial."""

    ruta = Path(ruta_db).resolve()
    engine = create_engine(f"sqlite:///{ruta}")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            solicitudes_existentes = session.scalar(
                select(Solicitud).where(Solicitud.alcaldia == alcaldia)
            )
            oferentes_existentes = session.scalar(
                select(Oferente).where(Oferente.alcaldia == alcaldia)
            )

            if solicitudes_existentes is None or oferentes_existentes is None:
                fila = dataset.loc[dataset["alcaldia"] == alcaldia]
                if fila.empty:
                    raise ValueError(f"No existe evidencia territorial para {alcaldia}.")
                fila = fila.iloc[0]
                dependientes = pd.to_numeric(
                    dataset["poblacion_dependiente"], errors="coerce"
                ).fillna(0)
                total_dependientes = dependientes.sum()
                promedio_dependientes = dependientes[dependientes > 0].mean()
                if total_dependientes <= 0 or promedio_dependientes <= 0:
                    raise ValueError(
                        "No se puede sembrar el simulador sin población dependiente positiva."
                    )

                poblacion_zona = float(fila["poblacion_dependiente"])
                solicitudes = max(
                    15, round(15 * poblacion_zona / promedio_dependientes)
                )
                afectados = max(float(fila["personas_afectadas"]), 0)
                cobertura = max(
                    0.05,
                    1 - min(afectados / max(poblacion_zona, 1), 0.95),
                )
                oferentes = max(1, round(solicitudes * cobertura))
                centroide = dataset.loc[
                    dataset["alcaldia"] == alcaldia
                ].to_crs(epsg=4326).geometry.iloc[0].centroid
                colonia = f"Zona piloto {alcaldia.title()}"
                if solicitudes_existentes is None:
                    session.add_all(
                        [
                            Solicitud(
                                alcaldia=alcaldia,
                                colonia=colonia,
                                latitud=float(centroide.y),
                                longitud=float(centroide.x),
                                horario_requerido_inicio=time(8),
                                horario_requerido_fin=time(12),
                                dias_requeridos="lun,mar",
                            )
                            for _ in range(solicitudes)
                        ]
                    )
                if oferentes_existentes is None:
                    session.add_all(
                        [
                            Oferente(
                                alcaldia=alcaldia,
                                colonia=colonia,
                                latitud=float(centroide.y),
                                longitud=float(centroide.x),
                                horario_ofrecido_inicio=time(8),
                                horario_ofrecido_fin=time(12),
                                dias_ofrecidos="lun,mar",
                            )
                            for _ in range(oferentes)
                        ]
                    )
                session.commit()

            solicitudes_rows = session.scalars(
                select(Solicitud).where(Solicitud.alcaldia == alcaldia)
            ).all()
            oferentes_rows = session.scalars(
                select(Oferente).where(Oferente.alcaldia == alcaldia)
            ).all()
            solicitudes_frame = pd.DataFrame(
                [
                    {
                        "solicitud_id": fila.solicitud_id,
                        "latitud": fila.latitud,
                        "longitud": fila.longitud,
                        "horario_requerido_inicio": fila.horario_requerido_inicio,
                        "horario_requerido_fin": fila.horario_requerido_fin,
                        "dias_requeridos": fila.dias_requeridos,
                    }
                    for fila in solicitudes_rows
                ]
            )
            oferentes_frame = pd.DataFrame(
                [
                    {
                        "oferente_id": fila.oferente_id,
                        "latitud": fila.latitud,
                        "longitud": fila.longitud,
                        "horario_ofrecido_inicio": fila.horario_ofrecido_inicio,
                        "horario_ofrecido_fin": fila.horario_ofrecido_fin,
                        "dias_ofrecidos": fila.dias_ofrecidos,
                    }
                    for fila in oferentes_rows
                ]
            )
            return solicitudes_frame, oferentes_frame
    finally:
        engine.dispose()


def mostrar_simulador(dataset: pd.DataFrame) -> None:
    st.header("Cuando la demanda supera la oferta")
    st.write(
        "Imagina una familia que necesita apoyo para cuidar a sus seres queridos. "
        "Esta experiencia muestra qué ocurre cuando muchas familias solicitan "
        "ayuda y solo hay unas pocas cuidadoras disponibles."
    )
    alcaldias = sorted(dataset["alcaldia"].dropna().unique())
    zona = st.selectbox(
        "Elige una zona para observar el piloto",
        alcaldias or ["IZTAPALAPA"],
        index=(alcaldias.index("IZTAPALAPA") if "IZTAPALAPA" in alcaldias else 0),
    )
    st.caption(
        f"Escenario ilustrativo para {zona.title()}: la cantidad de familias "
        "y cuidadoras se estima con la población dependiente y el déficit "
        "territorial observados en las fuentes del proyecto."
    )

    if st.button(
        "Ejecutar Simulación de Asignación",
        type="primary",
        use_container_width=True,
    ):
        solicitudes_frame, oferentes_frame = seed_datos_simulacion(
            dataset, zona
        )
        resultado = MotorMatching(max_distance_km=RADIO_MATCHING_KM).emparejar(
            solicitudes_frame, oferentes_frame
        )
        familias = len(resultado)
        vinculadas = int((resultado["estado"] == "emparejada").sum())
        sin_cobertura = familias - vinculadas

        columnas = st.columns(3)
        columnas[0].metric("Familias Solicitantes", f"{familias:,}")
        columnas[1].metric("Familias Vinculadas", f"{vinculadas:,}")
        columnas[2].metric("Familias sin Cobertura", f"{sin_cobertura:,}")

        if sin_cobertura:
            st.warning(
                f"{sin_cobertura} familias no pudieron recibir apoyo en esta "
                "simulación porque la oferta disponible se agotó."
            )
        else:
            st.success("Todas las familias encontraron una cuidadora compatible.")

        st.info(
            "Transparencia del Algoritmo: El motor prioriza cercanía y horarios, "
            f"pero debido al déficit estructural de oferta, {sin_cobertura} "
            "familias no pudieron ser vinculadas. Ningún dato personal fue "
            "expuesto (Privacidad por Diseño - UCA 1)."
        )
    st.caption(FUENTE_ACADEMICA)


def mostrar_transparencia() -> None:
    st.header("Transparencia Algorítmica")
    st.write(
        "El Dashboard visibiliza el Trabajo No Remunerado de los Hogares (TNRH) "
        "y sus brechas de acceso; no presenta el resultado como una decisión "
        "automática incuestionable."
    )
    with st.expander("UCA 1 · Privacidad por diseño", expanded=False):
        st.markdown(
            "- `Solicitudes` y `Oferentes` usan identificadores internos "
            "seudonimizados.\n"
            "- No se almacenan nombres reales, teléfonos, correos ni género.\n"
            "- El simulador no persiste datos personales.\n"
            "- La capa operativa conserva únicamente ubicación y horarios "
            "necesarios para el matching."
        )
    with st.expander("UCA 5/6 · Transparencia, sesgos y límites", expanded=False):
        st.markdown(
            "- La compatibilidad exige coincidencia de días y de la ventana horaria.\n"
            f"- La búsqueda geográfica usa un radio máximo de {RADIO_MATCHING_KM:g} km.\n"
            "- La puntuación pondera 60% proximidad y 40% cobertura horaria.\n"
            "- La asignación es uno-a-uno porque el esquema no registra capacidad "
            "múltiple por oferente.\n"
            "- La distancia puede actuar como proxy socioeconómico y favorecer "
            "zonas con más oferta.\n"
            "- Al no existir género en el OLTP, no se puede auditar ese sesgo."
        )
        st.info(
            "La demanda no atendida se conserva con motivos explícitos como "
            "`demanda_supera_oferta_zona`, `sin_compatibilidad_horaria` o "
            "`ubicacion_ausente`; no se fuerzan emparejamientos incompatibles."
        )


def main() -> None:
    dataset = cargar_evidencia()
    st.title("Observatorio del Cuidado CDMX")
    st.caption(
        "Evidencia territorial para decisiones de cuidado · UCA 3"
    )
    _metricas_principales(dataset)
    st.caption(FUENTE_ACADEMICA)
    visor, simulador, transparencia = st.tabs(
        ["Visor Territorial", "Simulador de Vinculación", "Transparencia Algorítmica"]
    )
    with visor:
        mostrar_visor_territorial(dataset)
    with simulador:
        mostrar_simulador(dataset)
    with transparencia:
        mostrar_transparencia()


if __name__ == "__main__":
    main()

"""Dashboard accesible del Observatorio de la Economía del Cuidado.

Ejecutar con: ``streamlit run app_dashboard.py``.
"""

from __future__ import annotations

import html
import re
import unicodedata
import uuid
from datetime import time

import folium
import pandas as pd
import streamlit as st
from branca.colormap import linear
from streamlit_folium import st_folium

from etl_pipeline import construir_dataset_consolidado
from modelo_matching import MotorMatching


CAPACIDAD_PROMEDIO_GUARDERIA = 100
RADIO_MATCHING_KM = 10.0

st.set_page_config(
    page_title="Observatorio de la Economía del Cuidado",
    page_icon="🫶",
    layout="wide",
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


def _crear_mapa(dataset: pd.DataFrame) -> folium.Map:
    mapa_data = dataset.to_crs(epsg=4326).copy()
    valores = mapa_data["personas_afectadas"].astype(float)
    minimo = float(valores.min())
    maximo = max(float(valores.max()), minimo + 1)
    escala = linear.Blues_09.scale(minimo, maximo)
    escala.caption = "Personas afectadas sin acceso"

    mapa = folium.Map(
        location=[19.33, -99.15],
        zoom_start=10,
        tiles="CartoDB positron",
        control_scale=True,
    )
    for _, fila in mapa_data.iterrows():
        nombre = _formato_alcaldia(fila["alcaldia"])
        text = (
            f"Alcaldía: {html.escape(nombre)}<br>"
            f"Población que requiere cuidado: "
            f"{fila['poblacion_dependiente']:,.0f} personas.<br>"
            f"Guarderías disponibles: {fila['No_Guard']:,.0f} centros.<br>"
            f"Población afectada sin acceso: "
            f"{fila['personas_afectadas']:,.0f} personas."
        )
        folium.GeoJson(
            data=fila.geometry.__geo_interface__,
            style_function=lambda _, color=escala(fila["personas_afectadas"]): {
                "fillColor": color,
                "color": "#334155",
                "weight": 1,
                "fillOpacity": 0.82,
            },
            highlight_function=lambda _: {
                "weight": 3,
                "color": "#0f172a",
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
        "La escala oscura identifica más personas afectadas sin acceso estimado. "
        f"Se estima una capacidad de {CAPACIDAD_PROMEDIO_GUARDERIA} personas "
        "por guardería para convertir infraestructura en impacto absoluto."
    )
    _mostrar_contexto_enut(dataset)
    st_folium(_crear_mapa(dataset), use_container_width=True, height=560)
    tabla = dataset[
        ["alcaldia", "poblacion_dependiente", "No_Guard", "personas_afectadas"]
    ].copy()
    tabla["alcaldia"] = tabla["alcaldia"].map(_formato_alcaldia)
    tabla.columns = [
        "Alcaldía",
        "Población que requiere cuidado",
        "Guarderías disponibles",
        "Personas afectadas sin acceso",
    ]
    st.dataframe(
        tabla.style.format(
            {
                "Población que requiere cuidado": "{:,.0f}",
                "Guarderías disponibles": "{:,.0f}",
                "Personas afectadas sin acceso": "{:,.0f}",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )


def _filas_sesion(tipo: str) -> list[dict[str, object]]:
    clave = "solicitudes_simulador" if tipo == "Solicitud" else "oferentes_simulador"
    return st.session_state.setdefault(clave, [])


def _entrada_perfil(tipo: str) -> dict[str, object]:
    prefijo = tipo.lower()
    st.subheader(f"Nueva {tipo.lower()}")
    colonia = st.text_input("Colonia", value="Centro", key=f"{prefijo}_colonia")
    latitud = st.number_input(
        "Latitud", -90.0, 90.0, 19.355, format="%.6f", key=f"{prefijo}_latitud"
    )
    longitud = st.number_input(
        "Longitud", -180.0, 180.0, -99.05, format="%.6f", key=f"{prefijo}_longitud"
    )
    inicio = st.time_input("Inicio", value=time(8), key=f"{prefijo}_inicio")
    fin = st.time_input("Fin", value=time(12), key=f"{prefijo}_fin")
    dias = st.multiselect(
        "Días",
        ["lun", "mar", "mie", "jue", "vie", "sab", "dom"],
        default=["lun", "mar"],
        key=f"{prefijo}_dias",
    )
    return {
        "colonia": colonia,
        "latitud": latitud,
        "longitud": longitud,
        "inicio": inicio,
        "fin": fin,
        "dias": ",".join(dias),
    }


def mostrar_simulador() -> None:
    st.header("Simulador de Vinculación")
    st.write(
        "Simula perfiles del piloto de Iztapalapa. Los identificadores se generan "
        "como UUID y no se solicitan nombres reales."
    )
    solicitud_col, oferente_col = st.columns(2)
    with solicitud_col:
        solicitud = _entrada_perfil("Solicitud")
        if st.button("Agregar solicitud", type="primary", use_container_width=True):
            if not solicitud["dias"] or solicitud["inicio"] >= solicitud["fin"]:
                st.error("Revisa días y rango horario.")
            elif len(_filas_sesion("Solicitud")) >= 15:
                st.error("El piloto está limitado a 15 solicitudes.")
            else:
                _filas_sesion("Solicitud").append(solicitud)
                st.success("Solicitud agregada.")
    with oferente_col:
        oferente = _entrada_perfil("Oferente")
        if st.button("Agregar oferente", use_container_width=True):
            if not oferente["dias"] or oferente["inicio"] >= oferente["fin"]:
                st.error("Revisa días y rango horario.")
            elif len(_filas_sesion("Oferente")) >= 6:
                st.error("El piloto está limitado a 6 oferentes.")
            else:
                _filas_sesion("Oferente").append(oferente)
                st.success("Oferente agregado.")

    solicitudes = _filas_sesion("Solicitud")
    oferentes = _filas_sesion("Oferente")
    st.caption(f"{len(solicitudes)} solicitudes · {len(oferentes)} oferentes")
    if st.button("Ejecutar matching", type="primary", use_container_width=True):
        solicitudes_frame = pd.DataFrame(
            [
                {
                    "solicitud_id": str(uuid.uuid4()),
                    "alcaldia": "IZTAPALAPA",
                    "latitud": perfil["latitud"],
                    "longitud": perfil["longitud"],
                    "horario_requerido_inicio": perfil["inicio"],
                    "horario_requerido_fin": perfil["fin"],
                    "dias_requeridos": perfil["dias"],
                }
                for perfil in solicitudes
            ]
        )
        oferentes_frame = pd.DataFrame(
            [
                {
                    "oferente_id": str(uuid.uuid4()),
                    "alcaldia": "IZTAPALAPA",
                    "latitud": perfil["latitud"],
                    "longitud": perfil["longitud"],
                    "horario_ofrecido_inicio": perfil["inicio"],
                    "horario_ofrecido_fin": perfil["fin"],
                    "dias_ofrecidos": perfil["dias"],
                }
                for perfil in oferentes
            ]
        )
        if solicitudes_frame.empty:
            st.info("Agrega al menos una solicitud.")
        else:
            resultado = MotorMatching(max_distance_km=RADIO_MATCHING_KM).emparejar(
                solicitudes_frame, oferentes_frame
            )
            st.metric(
                "Solicitudes emparejadas",
                f"{(resultado['estado'] == 'emparejada').sum():,.0f}/{len(resultado):,.0f}",
            )
            st.dataframe(resultado, use_container_width=True, hide_index=True)


def mostrar_transparencia() -> None:
    st.header("Transparencia Algorítmica")
    st.write(
        "El Dashboard visibiliza el Trabajo No Remunerado de los Hogares (TNRH) "
        "y sus brechas de acceso; no presenta el resultado como una decisión "
        "automática incuestionable."
    )
    with st.expander("UCA 1 · Privacidad por diseño", expanded=False):
        st.markdown(
            "- `Solicitudes` y `Oferentes` usan UUID seudonimizados.\n"
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
    st.title("Observatorio de la Economía del Cuidado")
    st.caption(
        "CDMX · Evidencia territorial para decisiones de cuidado · UCA 3"
    )
    _metricas_principales(dataset)
    visor, simulador, transparencia = st.tabs(
        ["Visor Territorial", "Simulador de Vinculación", "Transparencia Algorítmica"]
    )
    with visor:
        mostrar_visor_territorial(dataset)
    with simulador:
        mostrar_simulador()
    with transparencia:
        mostrar_transparencia()


if __name__ == "__main__":
    main()

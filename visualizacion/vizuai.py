import geopandas as gpd
import matplotlib.pyplot as plt

# La ruta debe apuntar al archivo principal .shp

ruta_shapefile = r"D:\git\proyrcto-pp-702\visualizacion\Equipamiento_de_asistencia_social.shp"

# Cargar el Shapefile como un GeoDataFrame
mapa_asistencia = gpd.read_file(ruta_shapefile)

# Explorar las primeras filas para ver qué columnas de atributos (del .dbf) contiene
print("Primeros registros de la base de datos espacial:")
print(mapa_asistencia.head())

# Ver el sistema de coordenadas (proveniente del .prj)
print("\nSistema de Referencia de Coordenadas (CRS):")
print(mapa_asistencia.crs)

# Generar un gráfico rápido para visualizar la distribución espacial
mapa_asistencia.plot(figsize=(10, 8), color='blue', edgecolor='black', markersize=10)
plt.title("Distribución de Equipamiento de Asistencia Social")
plt.xlabel("Longitud")
plt.ylabel("Latitud")
plt.show()
"""
Aplicativo Streamlit para la conversión de archivos KMZ/KML a Shapefile (SHP) y File Geodatabase (GDB).
Extrae geometrías (Puntos, Líneas y Polígonos) y convierte el contenido HTML de los popups <description>
y <ExtendedData> en columnas de la tabla de atributos.
"""

import io
import os
import streamlit as st
import geopandas as gpd
import pandas as pd
import folium
from streamlit_folium import st_folium
import zipfile

from kml_parser import load_kmz_or_kml
from exporter import features_to_geodataframes, export_to_shp_zip, export_to_gdb_zip, export_to_geojson_zip, sanitize_dataframe_columns


st.set_page_config(
    page_title="Conversor KMZ/KML a SHP & GDB",
    page_icon="🗺️",
    layout="wide"
)

# Estilos CSS personalizados
st.markdown("""
    <style>
    .main-header {
        font-size: 2.3rem;
        font-weight: 700;
        color: #1E3A8A;
        margin-bottom: 0.2rem;
    }
    .sub-header {
        font-size: 1.1rem;
        color: #4B5563;
        margin-bottom: 1.5rem;
    }
    .metric-box {
        background-color: #F3F4F6;
        border-radius: 8px;
        padding: 1rem;
        text-align: center;
        border-left: 4px solid #2563EB;
    }
    </style>
""", unsafe_allow_html=True)


def main():
    st.markdown('<div class="main-header">🗺️ Conversor KMZ/KML a SHP & File Geodatabase (GDB)</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Extrae automáticamente Puntos, Líneas y Polígonos y <b>transforma la información de los Popups HTML</b> en atributos tabulares estructurados.</div>', unsafe_allow_html=True)

    # Sidebar - Configuración
    st.sidebar.header("⚙️ Opciones de Conversión")

    export_format = st.sidebar.selectbox(
        "Formato de Salida",
        options=["Shapefile (.zip)", "File Geodatabase (.gdb en .zip)", "GeoJSON (.zip)", "Todos (SHP + GDB + GeoJSON)"],
        index=3
    )

    sanitize_cols = st.sidebar.checkbox(
        "Sanitizar nombres de columnas (Sin caracteres especiales)",
        value=True,
        help="Reemplaza tildes, espacios y caracteres especiales por guiones bajos para garantizar compatibilidad GIS."
    )

    max_dbf_len = st.sidebar.slider(
        "Límite de caracteres por columna (DBF)",
        min_value=8,
        max_value=32,
        value=10,
        help="Los archivos Shapefile (.dbf) requieren nombres de columna de máximo 10 caracteres."
    )

    st.sidebar.subheader("🌐 Sistema de Coordenadas (CRS)")
    crs_option = st.sidebar.selectbox(
        "Proyección de Salida",
        options=[
            "EPSG:4326 (WGS 84 - Geográficas)",
            "EPSG:32719 (UTM Zona 19S)",
            "EPSG:32718 (UTM Zona 18S)",
            "EPSG:32717 (UTM Zona 17S)",
            "EPSG:3857 (Web Mercator)",
            "Personalizado"
        ],
        index=0
    )

    if crs_option == "Personalizado":
        target_crs = st.sidebar.text_input("Ingresa el código EPSG (ej: EPSG:32719)", value="EPSG:4326")
    else:
        target_crs = crs_option.split(" ")[0]

    # Carga de archivo KMZ/KML
    uploaded_file = st.file_uploader(
        "Carga tu archivo KMZ o KML aquí",
        type=["kmz", "kml"],
        help="Selecciona un archivo .kmz o .kml que contenga capas y popups con información."
    )

    if uploaded_file is not None:
        file_bytes = uploaded_file.getvalue()
        filename = uploaded_file.name

        with st.spinner("Procesando archivo KMZ/KML y parseando popups HTML..."):
            try:
                features = load_kmz_or_kml(file_bytes, filename=filename)
            except Exception as e:
                st.error(f"Error al leer el archivo KMZ/KML: {e}")
                return

        if not features:
            st.warning("No se encontraron elementos geográficos (Placemarks) en el archivo subido.")
            return

        # Generar GeoDataFrames
        gdfs = features_to_geodataframes(features, target_crs=target_crs)

        # Aplicar eliminación de columnas desde session_state
        for layer_name in ["Puntos", "Lineas", "Poligonos"]:
            state_key = f"dropped_cols_{layer_name}"
            if state_key not in st.session_state:
                st.session_state[state_key] = []
            
            cols_to_drop = st.session_state[state_key]
            if cols_to_drop and not gdfs[layer_name].empty:
                existing_cols_to_drop = [c for c in cols_to_drop if c in gdfs[layer_name].columns]
                gdfs[layer_name] = gdfs[layer_name].drop(columns=existing_cols_to_drop)

        pts_count = len(gdfs['Puntos'])
        lines_count = len(gdfs['Lineas'])
        poly_count = len(gdfs['Poligonos'])
        total_count = pts_count + lines_count + poly_count

        # Recopilar todos los nombres de campos extraídos
        all_attr_keys = set()
        for f in features:
            all_attr_keys.update(f.get('attributes', {}).keys())

        # Métricas principales
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("📍 Total Entidades", total_count)
        col2.metric("📌 Puntos", pts_count)
        col3.metric("📏 Líneas", lines_count)
        col4.metric("🔷 Polígonos", poly_count)
        col5.metric("🏷️ Campos Popup", len(all_attr_keys))

        st.markdown("---")

        # Pestañas principales
        tab_tables, tab_map, tab_download = st.tabs([
            "📊 Previsualización de Atributos",
            "🗺️ Mapa Interactivo",
            "📥 Descargar Archivos Convertidos"
        ])

        # Tab 1: Previsualización de Tablas
        with tab_tables:
            st.subheader("Atributos Extraídos por Tipo de Geometría")
            st.info("Los popups HTML en la descripción del KMZ fueron transformados automáticamente en las siguientes columnas de atributos:")

            # Contenedor para la tabla, se renderiza visualmente aquí pero lo llenamos después
            table_container = st.container()

            st.markdown("---")
            st.markdown("##### 🔍 Inspeccionar Popup HTML Crudo de una Entidad")
            feature_names = [f"{i+1}: {f.get('name') or 'Sin Nombre'}" for i, f in enumerate(features)]
            selected_idx = st.selectbox("Selecciona un elemento para ver su popup HTML original:", range(len(features)), format_func=lambda i: feature_names[i])
            
            selected_feat = features[selected_idx]
            with st.expander("Ver contenido HTML crudo y atributos parseados"):
                st.json(selected_feat.get('attributes', {}))
                st.code(selected_feat.get('description_raw', 'Sin descripción HTML'), language="html")

            # Ahora sí llenamos la tabla con los datos ya filtrados por el usuario
            with table_container:
                geom_selected_label = st.radio(
                    "Selecciona la capa a visualizar:",
                    options=["Puntos", "Líneas", "Polígonos"],
                    horizontal=True
                )

                geom_map = {"Puntos": "Puntos", "Líneas": "Lineas", "Polígonos": "Poligonos"}
                geom_selected = geom_map[geom_selected_label]

                current_gdf = gdfs[geom_selected]

                if current_gdf.empty:
                    st.warning(f"No se encontraron elementos de tipo {geom_selected_label} en el archivo KMZ.")
                else:
                    display_gdf = current_gdf.copy()
                    if sanitize_cols:
                        display_gdf = sanitize_dataframe_columns(display_gdf, max_len=max_dbf_len)

                    st.markdown(f"**Capa `{geom_selected_label}` ({len(display_gdf)} registros, {len(display_gdf.columns) - 1} atributos)**")
                    
                    # Mostrar botones para eliminar columnas
                    st.write("Haz clic en una columna para eliminarla:")
                    cols_to_show = [c for c in current_gdf.columns if c != 'geometry']
                    
                    if cols_to_show:
                        # Add a "Restore All" button
                        if st.session_state[f"dropped_cols_{geom_selected}"]:
                            if st.button("🔄 Restaurar columnas eliminadas", key=f"restore_{geom_selected}"):
                                st.session_state[f"dropped_cols_{geom_selected}"] = []
                                if hasattr(st, "rerun"):
                                    st.rerun()
                                else:
                                    st.experimental_rerun()

                        # Layout in chunks to create a row of buttons
                        chunk_size = 6
                        for i in range(0, len(cols_to_show), chunk_size):
                            chunk = cols_to_show[i:i+chunk_size]
                            # Crear siempre 6 columnas para que el ancho sea uniforme y no se dispersen
                            btn_cols = st.columns(chunk_size)
                            for idx, col_name in enumerate(chunk):
                                with btn_cols[idx]:
                                    if st.button(f"{col_name}  ✖", key=f"drop_btn_{geom_selected}_{col_name}", use_container_width=True):
                                        st.session_state[f"dropped_cols_{geom_selected}"].append(col_name)
                                        if hasattr(st, "rerun"):
                                            st.rerun()
                                        else:
                                            st.experimental_rerun()
                                            
                    # Mostrar DataFrame excluyendo o formateando la columna geometry
                    df_view = pd.DataFrame(display_gdf.drop(columns=['geometry'], errors='ignore'))
                    st.dataframe(df_view, width='stretch', height=350)

        # Tab 2: Mapa Interactivo (Folium)
        with tab_map:
            st.subheader("Visualización Geográfica de Capas Extraídas")
            
            # Asegurar que el mapa esté en WGS84 para Folium
            wgs_gdfs = features_to_geodataframes(features, target_crs="EPSG:4326")
            
            # Selector de Atributo para Choropleth Dinámico
            st.markdown("##### 🎨 Coloración Automática (Choropleth)")
            st.write("Selecciona una columna para colorear los elementos geográficos automáticamente según sus valores.")
            
            # Recopilamos las columnas disponibles (excluyendo geometry) de todas las capas
            all_cols = set()
            for gdf_layer in wgs_gdfs.values():
                all_cols.update([c for c in gdf_layer.columns if c != 'geometry'])
            all_cols_sorted = sorted(list(all_cols))
            
            color_by_col = st.selectbox(
                "Colorear según...",
                options=["Ninguno (Color por defecto)"] + all_cols_sorted,
                index=0
            )
            
            # Calcular centro del mapa
            bounds_list = []
            for gdf_layer in wgs_gdfs.values():
                if not gdf_layer.empty:
                    bounds_list.append(gdf_layer.total_bounds)

            if bounds_list:
                minx = min(b[0] for b in bounds_list)
                miny = min(b[1] for b in bounds_list)
                maxx = max(b[2] for b in bounds_list)
                maxy = max(b[3] for b in bounds_list)
                center_lat = (miny + maxy) / 2
                center_lon = (minx + maxx) / 2
                m = folium.Map(
                    location=[center_lat, center_lon], 
                    zoom_start=12, 
                    tiles='https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}',
                    attr='Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ',
                    prefer_canvas=True
                )
            else:
                m = folium.Map(
                    location=[0, 0], 
                    zoom_start=2, 
                    tiles='https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}',
                    attr='Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ',
                    prefer_canvas=True
                )

            default_colors = {'Puntos': 'red', 'Lineas': 'blue', 'Poligonos': 'green'}
            
            import branca.colormap as cm
            import numpy as np

            for layer_name, gdf_layer in wgs_gdfs.items():
                if gdf_layer.empty:
                    continue

                feature_group = folium.FeatureGroup(name=f"{layer_name} ({len(gdf_layer)})")

                # Generar el estilo dinámicamente si se eligió un atributo
                style_function = None
                if color_by_col != "Ninguno (Color por defecto)" and color_by_col in gdf_layer.columns:
                    # Encontrar valores unicos
                    unique_vals = gdf_layer[color_by_col].astype(str).unique()
                    
                    # Crear una paleta de colores
                    is_numeric = pd.api.types.is_numeric_dtype(gdf_layer[color_by_col])
                    
                    if is_numeric and len(unique_vals) > 5:
                        vmin, vmax = gdf_layer[color_by_col].min(), gdf_layer[color_by_col].max()
                        colormap = cm.LinearColormap(colors=['blue', 'yellow', 'red'], vmin=vmin, vmax=vmax)
                        m.add_child(colormap)
                        def create_style(feature):
                            val = feature['properties'].get(color_by_col)
                            color = colormap(val) if val is not None else default_colors[layer_name]
                            return {'fillColor': color, 'color': color, 'weight': 2, 'fillOpacity': 0.6}
                        style_function = create_style
                    else:
                        # Categórico
                        palette = ['#e6194b', '#3cb44b', '#ffe119', '#4363d8', '#f58231', '#911eb4', '#46f0f0', '#f032e6', '#bcf60c', '#fabebe', '#008080', '#e6beff', '#9a6324', '#fffac8', '#800000', '#aaffc3', '#808000', '#ffd8b1', '#000075', '#808080', '#ffffff', '#000000']
                        val_to_color = {val: palette[i % len(palette)] for i, val in enumerate(unique_vals)}
                        
                        def create_style(feature):
                            val = str(feature['properties'].get(color_by_col))
                            color = val_to_color.get(val, default_colors[layer_name])
                            return {'fillColor': color, 'color': color, 'weight': 2, 'fillOpacity': 0.6}
                        style_function = create_style
                else:
                    # Color por defecto según geometría
                    def create_style(feature, lyr_name=layer_name):
                        color = default_colors[lyr_name]
                        return {'fillColor': color, 'color': color, 'weight': 2, 'fillOpacity': 0.5}
                    style_function = create_style

                # Convertir fechas a strings para que JSON serialice correctamente
                for col in gdf_layer.columns:
                    if pd.api.types.is_datetime64_any_dtype(gdf_layer[col]):
                        gdf_layer[col] = gdf_layer[col].astype(str)

                # Optimización: Agregar todos los polígonos y líneas con folium.GeoJson (bulk)
                fields_to_show = [c for c in gdf_layer.columns if c != 'geometry']
                popup = folium.GeoJsonPopup(
                    fields=fields_to_show,
                    aliases=fields_to_show,
                    localize=True,
                    max_width=300
                )
                
                tooltip_fields = fields_to_show[:3]
                tooltip = folium.GeoJsonTooltip(
                    fields=tooltip_fields,
                    aliases=tooltip_fields
                ) if tooltip_fields else None

                if layer_name == 'Puntos':
                    # Para puntos usamos un renderizado especial
                    folium.GeoJson(
                        gdf_layer,
                        name=layer_name,
                        style_function=style_function,
                        marker=folium.CircleMarker(radius=5, fill=True, fill_opacity=0.8),
                        popup=popup,
                        tooltip=tooltip
                    ).add_to(feature_group)
                else:
                    folium.GeoJson(
                        gdf_layer,
                        name=layer_name,
                        style_function=style_function,
                        popup=popup,
                        tooltip=tooltip
                    ).add_to(feature_group)

                feature_group.add_to(m)

            folium.LayerControl().add_to(m)
            st_folium(m, width=1200, height=500, returned_objects=[])

        # Tab 3: Descarga
        with tab_download:
            st.subheader("📥 Generación y Descarga de Archivos GIS")
            st.markdown("Selecciona y descarga tus archivos procesados listos para abrir en ArcGIS, QGIS o Google Earth Pro:")

            col_dn1, col_dn2, col_dn3 = st.columns(3)

            base_filename = os.path.splitext(filename)[0]

            if export_format in ["Shapefile (.zip)", "Ambos (SHP + GDB)", "Todos (SHP + GDB + GeoJSON)"]:
                with col_dn1:
                    st.markdown("### 📁 ESRI Shapefile")
                    st.write("Capas `SHP` empaquetadas en un único archivo ZIP.")
                    with st.spinner("Empaquetando Shapefile ZIP..."):
                        shp_zip_bytes = export_to_shp_zip(gdfs, sanitize_cols=sanitize_cols)
                    st.download_button(
                        label="⬇️ Descargar Shapefile",
                        data=shp_zip_bytes,
                        file_name=f"{base_filename}_SHP.zip",
                        mime="application/zip",
                        key="btn_shp"
                    )

            if export_format in ["File Geodatabase (.gdb en .zip)", "Ambos (SHP + GDB)", "Todos (SHP + GDB + GeoJSON)"]:
                with col_dn2:
                    st.markdown("### 🗄️ File Geodatabase")
                    st.write("Feature Classes dentro de `.gdb` empaquetadas en ZIP.")
                    with st.spinner("Generando File Geodatabase..."):
                        gdb_zip_bytes = export_to_gdb_zip(gdfs, gdb_name=f"{base_filename}.gdb", sanitize_cols=sanitize_cols)
                    st.download_button(
                        label="⬇️ Descargar Geodatabase",
                        data=gdb_zip_bytes,
                        file_name=f"{base_filename}_GDB.zip",
                        mime="application/zip",
                        key="btn_gdb"
                    )

            if export_format in ["GeoJSON (.zip)", "Todos (SHP + GDB + GeoJSON)"]:
                with col_dn3:
                    st.markdown("### 🌐 GeoJSON")
                    st.write("Archivos GeoJSON estándar empaquetados en ZIP.")
                    with st.spinner("Generando GeoJSON ZIP..."):
                        geojson_zip_bytes = export_to_geojson_zip(gdfs, sanitize_cols=sanitize_cols)
                    st.download_button(
                        label="⬇️ Descargar GeoJSON",
                        data=geojson_zip_bytes,
                        file_name=f"{base_filename}_GeoJSON.zip",
                        mime="application/zip",
                        key="btn_geojson"
                    )

if __name__ == "__main__":
    main()
    # Forzar recarga de modulos

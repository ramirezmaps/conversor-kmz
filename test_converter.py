"""
Pruebas unitarias para kml_parser.py y exporter.py
"""

import io
import zipfile
import unittest
import geopandas as gpd
from shapely.geometry import Point, LineString, Polygon
from kml_parser import parse_popup_html, parse_kml_content, load_kmz_or_kml, unzip_kmz
from exporter import features_to_geodataframes, sanitize_column_name, sanitize_dataframe_columns, export_to_shp_zip, export_to_gdb_zip

class TestKMLConverter(unittest.TestCase):

    def test_popup_html_vertical_table(self):
        html = """
        <table border="1">
          <tr><th>CLAVE_PROPIEDAD</th><td>P-9921</td></tr>
          <tr><th>PROPIETARIO_NOMBRE</th><td>Juan Carlos Perez</td></tr>
          <tr><th>SUPERFICIE_HA</th><td>12.5</td></tr>
        </table>
        """
        attrs = parse_popup_html(html)
        self.assertEqual(attrs.get('CLAVE_PROPIEDAD'), 'P-9921')
        self.assertEqual(attrs.get('PROPIETARIO_NOMBRE'), 'Juan Carlos Perez')
        self.assertEqual(attrs.get('SUPERFICIE_HA'), '12.5')

    def test_popup_html_horizontal_table(self):
        html = """
        <table>
          <tr><th>CODIGO</th><th>ESTADO</th><th>CAPACIDAD</th></tr>
          <tr><td>SUB-01</td><td>Operativo</td><td>500 kVA</td></tr>
        </table>
        """
        attrs = parse_popup_html(html)
        self.assertEqual(attrs.get('CODIGO'), 'SUB-01')
        self.assertEqual(attrs.get('ESTADO'), 'Operativo')
        self.assertEqual(attrs.get('CAPACIDAD'), '500 kVA')

    def test_popup_html_bold_tags(self):
        html = """
        <div>
          <b>Nombre del Poste:</b> P-442<br>
          <b>Material:</b> Hormigon<br>
          <b>Altura:</b> 12m<br>
        </div>
        """
        attrs = parse_popup_html(html)
        self.assertEqual(attrs.get('Nombre del Poste'), 'P-442')
        self.assertEqual(attrs.get('Material'), 'Hormigon')
        self.assertEqual(attrs.get('Altura'), '12m')

    def test_full_kml_parsing(self):
        kml = """<?xml version="1.0" encoding="UTF-8"?>
        <kml xmlns="http://www.opengis.net/kml/2.2">
          <Document>
            <Folder>
              <name>Capa1</name>
              <Placemark>
                <name>Punto 01</name>
                <description><![CDATA[
                  <table>
                    <tr><th>CAMPO_A</th><td>VALOR_A</td></tr>
                  </table>
                ]]></description>
                <Point><coordinates>-70.65,-33.45,0</coordinates></Point>
              </Placemark>
              <Placemark>
                <name>Linea 01</name>
                <description><![CDATA[<b>CAMPO_B:</b> VALOR_B]]></description>
                <LineString><coordinates>-70.65,-33.45,0 -70.66,-33.46,0</coordinates></LineString>
              </Placemark>
              <Placemark>
                <name>Poligono 01</name>
                <ExtendedData>
                  <Data name="EXT_FIELD"><value>EXT_VAL</value></Data>
                </ExtendedData>
                <Polygon>
                  <outerBoundaryIs>
                    <LinearRing>
                      <coordinates>-70.65,-33.45 -70.66,-33.45 -70.66,-33.46 -70.65,-33.46 -70.65,-33.45</coordinates>
                    </LinearRing>
                  </outerBoundaryIs>
                </Polygon>
              </Placemark>
            </Folder>
          </Document>
        </kml>
        """
        features = parse_kml_content(kml)
        self.assertEqual(len(features), 3)

        gdfs = features_to_geodataframes(features)
        self.assertEqual(len(gdfs['Puntos']), 1)
        self.assertEqual(len(gdfs['Lineas']), 1)
        self.assertEqual(len(gdfs['Poligonos']), 1)

        self.assertEqual(gdfs['Puntos'].iloc[0]['CAMPO_A'], 'VALOR_A')
        self.assertEqual(gdfs['Lineas'].iloc[0]['CAMPO_B'], 'VALOR_B')
        self.assertEqual(gdfs['Poligonos'].iloc[0]['EXT_FIELD'], 'EXT_VAL')

    def test_column_sanitization(self):
        col1 = sanitize_column_name("PROPIETARIO_NOMBRE", max_len=10)
        self.assertEqual(col1, "PROPIETARI")

        df = gpd.GeoDataFrame({
            'PROPIETARIO_NOMBRE': ['A'],
            'PROPIETARIO_NÚMERO': [1],
            'geometry': [Point(0,0)]
        })
        df_clean = sanitize_dataframe_columns(df, max_len=10)
        cols = list(df_clean.columns)
        self.assertIn('PROPIETARI', cols)
        self.assertIn('PROPIETA_1', cols)

    def test_kmz_zip_creation_and_export(self):
        kml = """<?xml version="1.0" encoding="UTF-8"?>
        <kml xmlns="http://www.opengis.net/kml/2.2">
          <Document>
            <Placemark>
              <name>Punto Test</name>
              <description><![CDATA[<table><tr><th>VALOR</th><td>100</td></tr></table>]]></description>
              <Point><coordinates>-70.0,-33.0,0</coordinates></Point>
            </Placemark>
          </Document>
        </kml>
        """
        # Crear KMZ en memoria
        kmz_buf = io.BytesIO()
        with zipfile.ZipFile(kmz_buf, 'w') as zf:
            zf.writestr('doc.kml', kml)
        kmz_buf.seek(0)

        features = load_kmz_or_kml(kmz_buf.getvalue(), filename="test.kmz")
        self.assertEqual(len(features), 1)

        gdfs = features_to_geodataframes(features)
        
        # Test SHP export
        shp_bytes = export_to_shp_zip(gdfs)
        self.assertTrue(len(shp_bytes) > 0)

        # Test GDB export
        gdb_bytes = export_to_gdb_zip(gdfs)
        self.assertTrue(len(gdb_bytes) > 0)

if __name__ == '__main__':
    unittest.main()

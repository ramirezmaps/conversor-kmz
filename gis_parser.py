import os
import tempfile
import zipfile
import geopandas as gpd

def load_gis_file(file_bytes, filename):
    """
    Reads a SHP (zip), GDB (zip), GeoJSON or DXF file and returns a dictionary 
    of GeoDataFrames, usually grouped by layer name or geometry type.
    """
    gdfs = {}
    ext = os.path.splitext(filename)[1].lower()
    
    if ext == '.zip':
        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = os.path.join(tmpdir, filename)
            with open(zip_path, 'wb') as f:
                f.write(file_bytes)
                
            try:
                with zipfile.ZipFile(zip_path, 'r') as zf:
                    zf.extractall(tmpdir)
            except zipfile.BadZipFile:
                raise ValueError("El archivo ZIP está corrupto o no es válido.")

            # Search for .shp or .gdb
            for root, dirs, files in os.walk(tmpdir):
                # Check for SHP
                for file in files:
                    if file.lower().endswith('.shp'):
                        shp_path = os.path.join(root, file)
                        layer_name = os.path.splitext(file)[0]
                        try:
                            gdf = gpd.read_file(shp_path)
                            gdfs[layer_name] = gdf
                        except Exception as e:
                            print(f"Error reading {file}: {e}")
                
                # Check for GDB
                for d in dirs:
                    if d.lower().endswith('.gdb'):
                        gdb_path = os.path.join(root, d)
                        try:
                            import fiona
                            layers = fiona.listlayers(gdb_path)
                            for layer in layers:
                                gdf = gpd.read_file(gdb_path, layer=layer)
                                gdfs[layer] = gdf
                        except Exception as e:
                            print(f"Error reading GDB {d}: {e}")

    elif ext in ['.geojson', '.json']:
        with tempfile.NamedTemporaryFile(suffix='.geojson', delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        try:
            gdf = gpd.read_file(tmp_path)
            layer_name = os.path.splitext(filename)[0]
            gdfs[layer_name] = gdf
        finally:
            os.remove(tmp_path)
            
    elif ext == '.dxf':
        with tempfile.NamedTemporaryFile(suffix='.dxf', delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        try:
            gdf = gpd.read_file(tmp_path)
            layer_name = os.path.splitext(filename)[0]
            gdfs[layer_name] = gdf
        finally:
            os.remove(tmp_path)
    else:
        raise ValueError(f"Formato de archivo no soportado: {ext}")
        
    return gdfs

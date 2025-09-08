# streamlit_app.py
import streamlit as st
from pathlib import Path
import folium
from streamlit_folium import st_folium
from branca.element import MacroElement, Template

st.set_page_config(page_title="ICVI Dashboard", layout="wide")
st.title("Indonesia Provinces (ADM1)")

# --- Paths ---
GEOJSON_PATH = Path("data/geoBoundaries-IDN-ADM1_simplified.geojson")
if not GEOJSON_PATH.exists():
    st.error(f"GeoJSON not found: {GEOJSON_PATH.resolve()}")
    st.stop()

# --- Base map ---
m = folium.Map(location=[-2, 118], zoom_start=5, tiles="CartoDB positron", control_scale=True)

# --- Remove the click focus rectangle (inside the iframe) ---
# 1) CSS: hide focus ring on interactive paths
css = MacroElement()
css._template = Template("""
{% macro html(this, kwargs) %}
<style>
.leaflet-interactive:focus,
.leaflet-interactive:focus-visible {
    outline: none !important;
    outline-offset: 0 !important;
}
</style>
{% endmacro %}
""")
m.get_root().add_child(css)

# 2) JS: strip tabindex & blur so polygons cannot receive focus
js = MacroElement()
js._template = Template("""
{% macro script(this, kwargs) %}
function __defocus__(){
  document.querySelectorAll('.leaflet-interactive').forEach(function(el){
    el.removeAttribute('tabindex');
    if (el.blur) el.blur();
  });
}
var map = {{ this._parent.get_name() }};
map.on('layeradd', __defocus__);
map.on('click', __defocus__);
setTimeout(__defocus__, 300);
{% endmacro %}
""")
m.get_root().add_child(js)

# --- Province layer ---
folium.GeoJson(
    data=str(GEOJSON_PATH),
    name="Provinces",
    style_function=lambda f: {
        "fillColor": "#dbeafe",   # light blue
        "color": "#111827",       # dark border
        "weight": 1,
        "fillOpacity": 0.3,
    },
    highlight_function=lambda f: {
        "weight": 2,
        "color": "#2563eb",
        "fillOpacity": 0.5,
    },
    tooltip=folium.GeoJsonTooltip(
        fields=["shapeName"],
        aliases=["Province:"],
        sticky=True,
    ),
    popup=folium.GeoJsonPopup(
        fields=["shapeName"],
        aliases=["Province:"],
        localize=True,
        labels=True,
    ),
).add_to(m)

folium.LayerControl(collapsed=False).add_to(m)

# --- Render in Streamlit ---
st_folium(m, use_container_width=True, height=620)

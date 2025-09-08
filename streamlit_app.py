import streamlit as st
import folium
from streamlit_folium import st_folium

# Set Streamlit page config
st.set_page_config(page_title="ICVI Dashboard", layout="wide")

st.title("Indonesia Provincial Boundaries (ADM1)")

# Load map
m = folium.Map(location=[-2, 118], zoom_start=5, tiles="cartodbpositron")

# Add province boundaries (ADM1)
geojson_path = "geoBoundaries-IDN-ADM1_simplified.geojson"
folium.GeoJson(
    geojson_path,
    name="Provinces",
    style_function=lambda feature: {
        "fillColor": "lightblue",
        "color": "black",
        "weight": 1,
        "fillOpacity": 0.2,
    },
    tooltip=folium.GeoJsonTooltip(fields=["shapeName"], aliases=["Province:"])
).add_to(m)

# Add layer control
folium.LayerControl().add_to(m)

# Show map in Streamlit
st_data = st_folium(m, width=900, height=600)

import streamlit as st
import geopandas as gpd
import plotly.express as px
import json

st.title("Check Province Boundaries")

# Load only provinces GeoJSON
gdf = gpd.read_file("data/geoBoundaries-IDN-ADM1_simplified.geojson")

# Convert to proper GeoJSON
geojson_data = json.loads(gdf.to_json())

# Choropleth with dummy color (all provinces shown)
gdf["dummy"] = 1

fig = px.choropleth(
    gdf,
    geojson=geojson_data,
    locations=gdf.index,
    color="dummy",
    hover_name="shapeName",
    projection="mercator"
)

fig.update_geos(fitbounds="locations", visible=False)
st.plotly_chart(fig, use_container_width=True)

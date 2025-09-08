import streamlit as st
import ee
from google.oauth2 import service_account
import geemap.foliumap as geemap

# ----------------------------------------------------
# Earth Engine Authentication
# ----------------------------------------------------
# Load credentials from Streamlit secrets
service_account_info = st.secrets["GEE_KEY"]

credentials = service_account.Credentials.from_service_account_info(service_account_info)
scoped_credentials = credentials.with_scopes(['https://www.googleapis.com/auth/earthengine'])
ee.Initialize(scoped_credentials)

# ----------------------------------------------------
# Streamlit UI
# ----------------------------------------------------
st.title("ICVI Dashboard")
st.subheader("Indonesia Provinces (GAUL) with Earth Engine")

# Create a map centered on Indonesia
m = geemap.Map(center=[-2, 118], zoom=4)

# Load GAUL provinces from Earth Engine
gaul = ee.FeatureCollection("FAO/GAUL/2015/level1")
indo = gaul.filter(ee.Filter.eq("ADM0_NAME", "Indonesia"))

# Add to map
m.addLayer(indo, {}, "Indonesia Provinces")

# Display map in Streamlit
m.to_streamlit(width=800, height=600)

st.markdown("""
**Notes:**
- This map uses the GAUL 2015 dataset from FAO (hosted on Google Earth Engine).
- Next step: join with ICVI results (province-level) to color provinces by vulnerability index.
""")

import streamlit as st
import requests
import xml.etree.ElementTree as ET
from datetime import datetime

# Page configuration for wide layout
st.set_page_config(page_title="Rail Live Dashboard", layout="wide", initial_sidebar_state="collapsed")

# Custom CSS to mimic a clean dark theme dashboard
st.markdown("""
    <style>
    .main {
        background-color: #0b0c10;
        color: #ffffff;
    }
    h1 {
        color: #ffffff;
        font-family: 'Segoe UI', sans-serif;
    }
    .stDataFrame {
        background-color: #1f2833;
    }
    </style>
""", unsafe_allow_html=True)

st.title("Train Status Dashboard")
st.write(f"Live Feed Connected — Last updated: {datetime.now().strftime('%H:%M:%S (%a)')}")

@st.cache_data(ttl=30)
def fetch_all_data():
    url = "https://api.irishrail.ie/realtime/realtime.asmx/getCurrentTrainsXML"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            root_xml = ET.fromstring(response.content)
            namespace = {'ns': 'http://api.irishrail.ie/realtime/'}
            train_nodes = root_xml.findall('.//ns:objTrainPositions', namespace)
            
            trains_list = []
            for train_node in train_nodes:
                def get_node_text(tag):
                    node = train_node.find(f'ns:{tag}', namespace)
                    return node.text.strip() if node is not None and node.text else ""
                
                train_code = get_node_text("TrainCode")
                status_flag = get_node_text("TrainStatus")
                public_msg = get_node_text("PublicMessage")
                direction = get_node_text("Direction")
                origin_station = get_node_text("TrainOrigin") or "Origin"
                dest_station = get_node_text("TrainDestination") or "Destination"
                
                is_cancelled = status_flag == "C" or (public_msg and "CANCEL" in public_msg.upper())
                
                # Basic cleaning of public message for table view
                clean_status = "En Route"
                if is_cancelled:
                    clean_status = "Cancelled"
                elif status_flag == "N":
                    clean_status = "Not yet started"
                elif status_flag == "E":
                    clean_status = "Service terminated"
                elif status_flag == "R":
                    clean_status = f"En route to {dest_station}"

                trains_list.append({
                    "ID": train_code,
                    "Origin": origin_station,
                    "Destination": dest_station,
                    "Status": clean_status,
                    "Direction": direction
                })
            return trains_list
    except Exception as e:
        st.error(f"Error connecting to Irish Rail API: {e}")
    return []

# Fetch and display data in an interactive table
trains_data = fetch_all_data()

if trains_data:
    # Add a search filter box for Train IDs
    search_query = st.text_input("Search Train ID:", "").strip().upper()
    
    if search_query:
        filtered_data = [t for t in trains_data if search_query in t["ID"]]
    else:
        filtered_data = trains_data

    st.write(f"Showing {len(filtered_data)} active services:")
    st.dataframe(filtered_data, use_container_width=True, hide_index=True)
else:
    st.warning("No train data currently available or API connection failed.")

import streamlit as st
import requests
import xml.etree.ElementTree as ET
from datetime import datetime

st.set_page_config(page_title="Rail Live Dashboard", layout="wide")
st.title("train Status Dashboard")

@st.cache_data(ttl=30)
def fetch_train_data():
    url = "https://api.irishrail.ie/realtime/realtime.asmx/getCurrentTrainsXML"
    response = requests.get(url, timeout=10)
    if response.status_code == 200:
        root_xml = ET.fromstring(response.content)
        namespace = {'ns': 'http://api.irishrail.ie/realtime/'}
        train_nodes = root_xml.findall('.//ns:objTrainPositions', namespace)
        
        trains = []
        for node in train_nodes:
            trains.append({
                "Code": node.find('ns:TrainCode', namespace).text,
                "Status": node.find('ns:TrainStatus', namespace).text,
                "Message": node.find('ns:PublicMessage', namespace).text
            })
        return trains
    return []

trains = fetch_train_data()
st.write(f"Loaded {len(trains)} active trains.")
st.table(trains)
import streamlit as st
import pandas as pd
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

st.set_page_config(page_title="Rail Live Dashboard", layout="wide")

# Custom styling to hide the top header bar, style tables, and ensure dark theme
st.markdown("""
    <style>
    [data-testid="stHeader"] {
        display: none;
    }
    .stApp {
        background-color: #0b0c10;
        color: #ffffff;
    }
    .block-container {
        padding-top: 1.0rem;
        padding-bottom: 1rem;
        padding-left: 2rem;
        padding-right: 2rem;
    }
    h1, h2, h3, p, label {
        color: #ffffff !important;
    }
    .train-table {
        width: 100%;
        border-collapse: collapse;
        font-family: 'Segoe UI', sans-serif;
        font-size: 14px;
    }
    .train-table th {
        background-color: #1f2833;
        color: #ffffff;
        text-align: left;
        padding: 8px 12px;
        font-weight: bold;
    }
    .train-table td {
        padding: 8px 12px;
        border-bottom: 1px solid #151c24;
    }
    </style>
""", unsafe_allow_html=True)

def parse_time(time_str):
    """Parse time to total minutes as float (including seconds)."""
    if not time_str or time_str == "00:00:00":
        return None
    try:
        if len(time_str) == 8:  # HH:MM:SS
            h, m, s = map(int, time_str.split(':'))
            return h * 60 + m + s / 60.0
        else:  # HH:MM
            h, m = map(int, time_str.split(':'))
            return h * 60 + m
    except:
        return None

def calculate_delay(scheduled, expected, actual):
    """Return delay in fractional minutes."""
    sched_min = parse_time(scheduled)
    if sched_min is None:
        return 0.0

    for t in [actual, expected]:
        if t and t != "00:00:00":
            actual_min = parse_time(t)
            if actual_min is not None:
                return round(actual_min - sched_min, 1)
    return 0.0

@st.cache_data(ttl=30)
def fetch_live_trains():
    url = "https://api.irishrail.ie/realtime/realtime.asmx/getCurrentTrainsXML"
    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            root_xml = ET.fromstring(response.content)
            namespace = {'ns': 'http://api.irishrail.ie/realtime/'}
            train_nodes = root_xml.findall('.//ns:objTrainPositions', namespace)
            live_trains = {}

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
                origin_time = "--:--"
                late_mins = 0
                is_cancelled = status_flag == "C" or (public_msg and "CANCEL" in public_msg.upper())

                if public_msg:
                    clean_msg = public_msg.replace("\\n", "\n").replace(r"\n", "\n")
                    lines = [l.strip() for l in clean_msg.split("\n") if l.strip()]
                    if lines:
                        first_line = lines[0]
                        if " to " in first_line and not first_line.startswith(("Expected", "Cancelled")):
                            parts = first_line.split(" to ", 1)
                            origin_station = parts[0].strip()
                            dest_station = parts[1].split("(")[0].strip() if "(" in parts[1] else parts[1].strip()
                        elif "Destination" in first_line or " and " in first_line or " and Destination" in clean_msg:
                            origin_candidate = first_line
                            if origin_candidate[0].isalpha() and len(origin_candidate) <= 5:
                                origin_candidate = lines[1] if len(lines) > 1 else first_line
                            if " and Destination" in clean_msg or "Destination" in clean_msg:
                                if "Destination" in clean_msg:
                                    dest_part = clean_msg.split("Destination")[-1].strip()
                                    dest_station = dest_part.split("\n")[0].split()[0] if dest_part else dest_station
                                if " and " in origin_candidate:
                                    origin_station = origin_candidate.split(" and ")[0].strip()
                                else:
                                    origin_station = origin_candidate.strip()
                        elif len(lines) >= 2:
                            route_info = lines[1]
                            if " - " in route_info:
                                origin_time = route_info.split(" - ")[0].strip()
                                core_route = route_info.split(" - ")[1]
                                if " to " in core_route:
                                    origin_station = core_route.split(" to ")[0].strip()
                                    dest_part = core_route.split(" to ")[1]
                                    dest_station = dest_part.split("(")[0].strip()
                                    if "late)" in dest_part:
                                        try: late_mins = int(dest_part.split("(")[1].split(" min")[0])
                                        except: pass
                                    elif "early)" in dest_part:
                                        try: late_mins = -int(dest_part.split("(")[1].split(" min")[0])
                                        except: pass
                    if origin_station in ["Origin", "--"] or dest_station in ["Destination", "--"]:
                        if "Expected Departure" in clean_msg:
                            try: origin_time = clean_msg.split("Expected Departure ")[1][:5]
                            except: pass
                        msg_lower = clean_msg.lower()
                        if " to " in msg_lower:
                            idx = msg_lower.find(" to ")
                            if idx != -1:
                                origin_station = clean_msg[:idx].split("\n")[-1].strip()
                                dest_station = clean_msg[idx+4:].split("\n")[0].split("(")[0].strip()
                            
                    if origin_station.upper().startswith(train_code.upper()):
                        origin_station = origin_station[len(train_code):].strip()

                if origin_station in ["Origin", "--"] and direction:
                    if " to " in direction:
                        dest_station = direction.split(" to ")[-1].strip()
                    elif "bound" in direction.lower():
                        dest_station = direction

                if origin_station in ["Origin", "", "--"]: origin_station = "--"
                if dest_station in ["Destination", "", "--"]: dest_station = "--"

                clean_status = "Unknown Status"
                delay_reason = "--"

                if is_cancelled:
                    clean_status = "Cancelled"
                    delay_reason = "Service Cancelled"
                elif public_msg:
                    msg_lines = [l.strip() for l in public_msg.replace(r"\n", "\n").split("\n") if l.strip()]
                    if len(msg_lines) >= 3:
                        clean_status = msg_lines[2]
                    elif len(msg_lines) == 1:
                        clean_status = msg_lines[0]
                    if len(msg_lines) >= 4:
                        delay_reason = msg_lines[3]
                else:
                    if status_flag == "N": clean_status = "Not yet started"
                    elif status_flag == "E": clean_status = "Service terminated"
                    elif status_flag == "R": clean_status = f"En route to {dest_station}"

                live_trains[train_code] = {
                    "trainCode": train_code,
                    "origin": origin_station,
                    "destination": dest_station,
                    "origintime": origin_time,
                    "late": late_mins,
                    "statusCode": status_flag,
                    "cleanStatus": clean_status,
                    "delayReason": delay_reason,
                    "isCancelled": is_cancelled
                }
            return live_trains
    except Exception as e:
        st.error(f"Error connecting to Irish Rail API: {e}")
    return {}

# --- ITINERARY VIEW ---
def render_itinerary_view(train_code):
    if st.button("← Back to Live Dashboard"):
        st.query_params.clear()
        st.rerun()

    now = datetime.now()
    use_yesterday = False
    date_str = (now - timedelta(days=1)).strftime("%d %b %Y") if use_yesterday else now.strftime("%d %b %Y")
    url = f"https://api.irishrail.ie/realtime/realtime.asmx/getTrainMovementsXML?TrainId={train_code}&TrainDate={date_str}"

    with st.spinner(f"Loading itinerary for service {train_code} (waiting up to 60s for API response)..."):
        try:
            response = requests.get(url, timeout=60)

            if response.status_code != 200:
                if now.hour < 3 and not use_yesterday:
                    yesterday_str = (now - timedelta(days=1)).strftime("%d %b %Y")
                    response = requests.get(f"https://api.irishrail.ie/realtime/realtime.asmx/getTrainMovementsXML?TrainId={train_code}&TrainDate={yesterday_str}", timeout=60)
                
                if response.status_code != 200:
                    st.error(f"API Error: {response.status_code}")
                    return
                
            root_xml = ET.fromstring(response.content)
            namespace = {'ns': 'http://api.irishrail.ie/realtime/'}
            movements = root_xml.findall('.//ns:objTrainMovements', namespace)

            if not movements:
                st.warning(f"No movement data found for {train_code} on {date_str}.")
                return

            def get_location_order(node):
                val = node.find('ns:LocationOrder', namespace)
                return int(val.text) if val is not None and val.text else 0
            movements.sort(key=get_location_order)

            def extract_node_txt(node, tag):
                item = node.find(f'ns:{tag}', namespace)
                return item.text.strip() if item is not None and item.text else ""

            first_node = movements[0]
            last_node = movements[-1]
            
            orig_time = extract_node_txt(first_node, "ScheduledDeparture")
            if len(orig_time) == 8: orig_time = orig_time[:5]
            if not orig_time or orig_time == "00:00":
                orig_time = extract_node_txt(first_node, "ScheduledArrival")
                if len(orig_time) == 8: orig_time = orig_time[:5]

            origin_name = extract_node_txt(first_node, "LocationFullName")
            dest_name = extract_node_txt(last_node, "LocationFullName")

            has_any_cancel = any(extract_node_txt(n, "LocationType") == "C" for n in movements)
            is_fully_cancelled = all(extract_node_txt(n, "LocationType") == "C" for n in movements)
            
            latest_delay = 0.0
            for node in movements:
                sched_dep = extract_node_txt(node, "ScheduledDeparture")
                sched_arr = extract_node_txt(node, "ScheduledArrival")
                exp_dep = extract_node_txt(node, "ExpectedDeparture")
                exp_arr = extract_node_txt(node, "ExpectedArrival")
                actual_dep = extract_node_txt(node, "Departure")
                actual_arr = extract_node_txt(node, "Arrival")
                has_served = (actual_arr and actual_arr != "00:00:00") or (actual_dep and actual_dep != "00:00:00")
                if has_served:
                    if sched_dep and sched_dep != "00:00:00":
                        latest_delay = calculate_delay(sched_dep, exp_dep, actual_dep)
                    elif sched_arr and sched_arr != "00:00:00":
                        latest_delay = calculate_delay(sched_arr, exp_arr, actual_arr)

            if is_fully_cancelled or has_any_cancel:
                status_str, status_color = "Cancelled", "#c678dd"
                id_color = "#c678dd"
            elif latest_delay == 0:
                status_str, status_color = "On Time", "#2ecc71"
                id_color = "#d4af37"
            elif latest_delay <= 2:
                status_str, status_color = f"Late {latest_delay:.1f}m", "#2ecc71"
                id_color = "#d4af37"
            elif latest_delay <= 5:
                status_str, status_color = f"Late {latest_delay:.1f}m", "#f1c40f"
                id_color = "#d4af37"
            else:
                status_str, status_color = f"Late {latest_delay:.1f}m", "#e74c3c"
                id_color = "#d4af37"

            header_html = f"""
            <div style="font-size: 20px; font-weight: bold; font-family: 'Segoe UI', sans-serif; margin-bottom: 15px;">
                <span style="color: {id_color};">{train_code}</span> 
                <span style="color: #ffffff;">{orig_time}</span> 
                <span style="color: #2ecc71;">{origin_name} → {dest_name}</span> 
                <span style="color: {status_color};">({status_str})</span>
            </div>
            """
            st.markdown(header_html, unsafe_allow_html=True)

            itinerary_rows = []
            for node in movements:
                station_name = extract_node_txt(node, "LocationFullName") or extract_node_txt(node, "LocationCode")
                loc_type = extract_node_txt(node, "LocationType")
                stops_text = "Non Stop" if loc_type == "C" else ("Stops" if loc_type in ["O", "D", "S"] else "")

                sched_arr = extract_node_txt(node, "ScheduledArrival")
                sched_dep = extract_node_txt(node, "ScheduledDeparture")
                due_time = sched_dep if sched_dep and sched_dep != "00:00:00" else sched_arr
                if len(due_time) == 8: due_time = due_time[:5]

                actual_arr = extract_node_txt(node, "Arrival")
                actual_dep = extract_node_txt(node, "Departure")
                exp_arr = extract_node_txt(node, "ExpectedArrival")
                exp_dep = extract_node_txt(node, "ExpectedDeparture")
                reason_text = extract_node_txt(node, "AutoReason") or "--"

                has_served = (actual_arr and actual_arr != "00:00:00") or (actual_dep and actual_dep != "00:00:00")
                delay_mins = 0
                if has_served:
                    if sched_dep and sched_dep != "00:00:00":
                        delay_mins = calculate_delay(sched_dep, exp_dep, actual_dep)
                    elif sched_arr and sched_arr != "00:00:00":
                        delay_mins = calculate_delay(sched_arr, exp_arr, actual_arr)

                arrive_text = (actual_arr if actual_arr and actual_arr != "00:00:00" else exp_arr) or "--:--"
                if len(arrive_text) == 8: arrive_text = arrive_text[:5]

                depart_text = (actual_dep if actual_dep and actual_dep != "00:00:00" else exp_dep) or "--:--"
                if len(depart_text) == 8: depart_text = depart_text[:5]

                mins_text = f"{delay_mins:.1f}" if has_served else ""

                itinerary_rows.append({
                    "Location": station_name,
                    "Stops": stops_text,
                    "Due": due_time,
                    "Arrive": arrive_text,
                    "Depart": depart_text,
                    "Mins": mins_text,
                    "Reason": reason_text,
                    "_hasServed": has_served,
                    "_delayMins": delay_mins,
                    "_locType": loc_type
                })

            df_itin = pd.DataFrame(itinerary_rows)
            display_itin = df_itin.drop(columns=["_hasServed", "_delayMins", "_locType"])

            def style_itin(df_sub):
                styles = pd.DataFrame('', index=df_sub.index, columns=df_sub.columns)
                for i, row in df_sub.iterrows():
                    has_served = df_itin.at[i, "_hasServed"]
                    delay_mins = df_itin.at[i, "_delayMins"]
                    loc_type = df_itin.at[i, "_locType"]

                    if loc_type in ["O", "D", "S"]:
                        styles.at[i, "Location"] = "color: #d4af37;"
                    elif loc_type == "C":
                        styles.at[i, "Location"] = "color: #c678dd;"

                    if loc_type == "C":
                        styles.at[i, "Stops"] = "color: #c678dd;"

                    if has_served:
                        styles.at[i, "Arrive"] = "color: #00ffff;"
                        styles.at[i, "Depart"] = "color: #00ffff;"
                    else:
                        styles.at[i, "Arrive"] = "color: #666666;"
                        styles.at[i, "Depart"] = "color: #666666;"

                    if has_served:
                        if delay_mins == 0:
                            styles.at[i, "Mins"] = "color: #2ecc71; font-weight: bold;"
                        elif delay_mins < 0:
                            styles.at[i, "Mins"] = "color: #ffffff;"
                        elif delay_mins <= 2:
                            styles.at[i, "Mins"] = "color: #2ecc71; font-weight: bold;"
                        elif delay_mins <= 5:
                            styles.at[i, "Mins"] = "color: #f1c40f; font-weight: bold;"
                        else:
                            styles.at[i, "Mins"] = "color: #e74c3c; font-weight: bold;"

                    if str(row["Reason"]) != "--":
                        styles.at[i, "Reason"] = "color: #e74c3c;"
                    else:
                        styles.at[i, "Reason"] = "color: #a6a6a6;"

                return styles

            styled_itin = display_itin.style.apply(style_itin, axis=None)
            st.dataframe(styled_itin, use_container_width=True, hide_index=True, height=700)
        except Exception as e:
            st.error(f"Error fetching itinerary: {e}")

# --- MAIN DASHBOARD VIEW ---
def render_dashboard():
    live_trains = fetch_live_trains()
    if not live_trains:
        st.warning("No live train data returned from API.")
        return

    display_list = list(live_trains.values())
    display_list.sort(key=lambda t: t["origintime"] if t["origintime"] != "--:--" else "99:99")

    col_title, col_search = st.columns([3, 1])
    with col_title:
        st.title("Train Status")
        st.write(f"Last updated: {datetime.now().strftime('%H:%M:%S (%a)')} — ({len(display_list)} live train data blocks returned by API)")
    with col_search:
        st.markdown("<div style='margin-top: 5px;'></div>", unsafe_allow_html=True)
        search_query = st.text_input("Search Train ID:", "").strip().upper()
        if search_query:
            if search_query in live_trains:
                st.query_params["train"] = search_query
                st.rerun()
            else:
                st.warning(f"Train ID '{search_query}' not found.")

    # Build HTML table where Train IDs open in a new tab/window via target="_blank"
    html_table = """
    <table class="train-table">
        <tr>
            <th>ID</th>
            <th>Time</th>
            <th>Origin</th>
            <th>Destination</th>
            <th>Delay</th>
            <th>Status</th>
            <th>Reason</th>
        </tr>
    """

    for idx, train in enumerate(display_list):
        train_code = train["trainCode"]
        delay_mins = train["late"]
        is_cancelled = train.get("isCancelled", False)

        if is_cancelled:
            color, delay_text = "#e74c3c", "Cancelled"
        elif train["statusCode"] == "N":
            color, delay_text = "#ffffff", "Not Due"
        elif train["statusCode"] == "E":
            color, delay_text = "#a6a6a6", "Finished"
        elif delay_mins < 0:
            color, delay_text = "#ffffff", f"{abs(delay_mins)}m Early"
        elif 0 <= delay_mins <= 2:
            color, delay_text = "#2ecc71", ("On Time" if delay_mins == 0 else f"{delay_mins}m Delay")
        elif 2 < delay_mins <= 5:
            color, delay_text = "#f1c40f", f"{delay_mins}m Delay"
        else:
            color, delay_text = "#e74c3c", f"{delay_mins}m Delay"

        bg_color = "#1f2833" if idx % 2 == 0 else "#151c24"
        train_id_color = "#c678dd" if is_cancelled else "#d4af37"
        reason_color = "#e74c3c" if train["delayReason"] != "--" else "#a6a6a6"
        orig_display = train["origin"] if train["origin"] not in ["Origin", ""] else "--"
        dest_display = train["destination"] if train["destination"] not in ["Destination", ""] else "--"

        html_table += f"""
        <tr style="background-color: {bg_color};">
            <td><a href="?train={train_code}" target="_blank" style="color: {train_id_color}; font-weight: bold; text-decoration: none;">{train_code}</a></td>
            <td style="color: #ffffff;">{train["origintime"]}</td>
            <td style="color: #ffffff;">{orig_display}</td>
            <td style="color: #ffffff;">{dest_display}</td>
            <td style="color: {color}; font-weight: bold;">{delay_text}</td>
            <td style="color: #ffffff;">{train["cleanStatus"]}</td>
            <td style="color: {reason_color};">{train["delayReason"]}</td>
        </tr>
        """
    html_table += "</table>"

    st.markdown(html_table, unsafe_allow_html=True)

# Router controller: Checks if a train query parameter exists in the URL
query_params = st.query_params
if "train" in query_params:
    render_itinerary_view(query_params["train"])
else:
    render_dashboard()

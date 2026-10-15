import streamlit as st
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

st.set_page_config(page_title="Rail Live Dashboard", layout="wide")

# Custom CSS matching your exact dark theme and color styling
st.markdown("""
    <style>
    .stApp {
        background-color: #0b0c10;
        color: #ffffff;
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

def strikethrough(text):
    """Apply Unicode combining strikethrough to text."""
    if not text:
        return ""
    return ''.join(char + '\u0336' for char in text)

def parse_time(time_str):
    """Parse time to total minutes as float (including seconds)[cite: 3]."""
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
    """Return delay in fractional minutes[cite: 3]."""
    sched_min = parse_time(scheduled)
    if sched_min is None:
        return 0.0

    for t in [actual, expected]:
        if t and t != "00:00:00":
            actual_min = parse_time(t)
            if actual_min is not None:
                return round(actual_min - sched_min, 1)
    return 0.0

# Initialize session state for train selection
if "selected_train" not in st.session_state:
    st.session_state.selected_train = None

@st.cache_data(ttl=30)
def fetch_live_trains():
    url = "https://api.irishrail.ie/realtime/realtime.asmx/getCurrentTrainsXML"
    try:
        response = requests.get(url, timeout=10)
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

                # Exact message parsing logic from original script[cite: 3]
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
        st.session_state.selected_train = None
        st.rerun()

    st.subheader(f"Itinerary for Service {train_code}")

    now = datetime.now()
    use_yesterday = False
    date_str = (now - timedelta(days=1)).strftime("%d %b %Y") if use_yesterday else now.strftime("%d %b %Y")
    url = f"https://api.irishrail.ie/realtime/realtime.asmx/getTrainMovementsXML?TrainId={train_code}&TrainDate={date_str}"

    try:
        response = requests.get(url, timeout=15)
        if response.status_code != 200:
            st.error(f"API Error: {response.status_code}")
            return
            
        root_xml = ET.fromstring(response.content)
        namespace = {'ns': 'http://api.irishrail.ie/realtime/'}
        movements = root_xml.findall('.//ns:objTrainMovements', namespace)

        if not movements and now.hour < 3:
            yesterday_str = (now - timedelta(days=1)).strftime("%d %b %Y")
            response = requests.get(f"https://api.irishrail.ie/realtime/realtime.asmx/getTrainMovementsXML?TrainId={train_code}&TrainDate={yesterday_str}", timeout=10)
            if response.status_code == 200:
                root_xml = ET.fromstring(response.content)
                movements = root_xml.findall('.//ns:objTrainMovements', namespace)

        if not movements:
            st.warning(f"No movement data found for {train_code} on {date_str}.")
            return

        def get_location_order(node):
            val = node.find('ns:LocationOrder', namespace)
            return int(val.text) if val is not None and val.text else 0
        movements.sort(key=get_location_order)

        html_table = """
        <table class="train-table">
            <tr>
                <th>Location</th>
                <th>Stops</th>
                <th>Due</th>
                <th>Arrive</th>
                <th>Depart</th>
                <th>Mins</th>
                <th>Reason</th>
            </tr>
        """

        for idx, node in enumerate(movements):
            def get_txt(tag):
                item = node.find(f'ns:{tag}', namespace)
                return item.text.strip() if item is not None and item.text else ""

            station_name = get_txt("LocationFullName") or get_txt("LocationCode")
            loc_type = get_txt("LocationType")
            
            if loc_type == "C":
                stops_text, stops_color = "Non Stop", "#c678dd"
            elif loc_type in ["O", "D", "S"]:
                stops_text, stops_color = "Stops", "#ffffff"
            else:
                stops_text, stops_color = "", "#ffffff"
            
            location_color = "#d4af37" if loc_type in ["O", "D", "S"] else "#ffffff"

            sched_arr = get_txt("ScheduledArrival")
            sched_dep = get_txt("ScheduledDeparture")
            due_time = sched_dep if sched_dep and sched_dep != "00:00:00" else sched_arr
            if len(due_time) == 8: due_time = due_time[:5]

            actual_arr = get_txt("Arrival")
            actual_dep = get_txt("Departure")
            exp_arr = get_txt("ExpectedArrival")
            exp_dep = get_txt("ExpectedDeparture")
            reason_text = get_txt("AutoReason") or "--"
            reason_color = "#e74c3c" if reason_text != "--" else "#a6a6a6"

            has_served = (actual_arr and actual_arr != "00:00:00") or (actual_dep and actual_dep != "00:00:00")
            delay_mins = 0
            if has_served:
                if sched_dep and sched_dep != "00:00:00":
                    delay_mins = calculate_delay(sched_dep, exp_dep, actual_dep)
                elif sched_arr and sched_arr != "00:00:00":
                    delay_mins = calculate_delay(sched_arr, exp_arr, actual_arr)

            arrive_text = (actual_arr if actual_arr and actual_arr != "00:00:00" else exp_arr) or "--:--"
            if len(arrive_text) == 8: arrive_text = arrive_text[:5]
            arrive_color = "#00ffff" if (actual_arr and actual_arr != "00:00:00") else "#ffffff"

            depart_text = (actual_dep if actual_dep and actual_dep != "00:00:00" else exp_dep) or "--:--"
            if len(depart_text) == 8: depart_text = depart_text[:5]
            depart_color = "#00ffff" if (actual_dep and actual_dep != "00:00:00") else "#ffffff"

            if has_served:
                if delay_mins == 0:
                    mins_text, mins_color = "0.0", "#2ecc71"
                elif delay_mins < 0:
                    mins_text, mins_color = f"{abs(delay_mins):.1f}", "#ffffff"
                else:
                    mins_text = f"-{delay_mins:.1f}"
                    mins_color = "#e74c3c" if delay_mins > 5 else ("#f1c40f" if delay_mins > 2 else "#2ecc71")
            else:
                mins_text, mins_color = "", "#ffffff"

            bg_color = "#1f2833" if idx % 2 == 0 else "#151c24"

            html_table += f"""
            <tr style="background-color: {bg_color};">
                <td style="color: {location_color};">{station_name}</td>
                <td style="color: {stops_color};">{stops_text}</td>
                <td style="color: #00ffff;">{due_time}</td>
                <td style="color: {arrive_color};">{arrive_text}</td>
                <td style="color: {depart_color};">{depart_text}</td>
                <td style="color: {mins_color};">{mins_text}</td>
                <td style="color: {reason_color};">{reason_text}</td>
            </tr>
            """
        html_table += "</table>"
        st.markdown(html_table, unsafe_allow_html=True)

    except Exception as e:
        st.error(f"Error fetching itinerary: {e}")

# --- MAIN DASHBOARD VIEW ---
def render_dashboard():
    st.title("Train Status")
    st.write(f"Last updated: {datetime.now().strftime('%H:%M:%S (%a)')}")

    live_trains = fetch_live_trains()
    if not live_trains:
        st.warning("No live train data returned from API.")
        return

    col1, col2 = st.columns([3, 1])
    with col2:
        search_query = st.text_input("Search Train ID:", "").strip().upper()
        if search_query:
            if search_query in live_trains:
                st.session_state.selected_train = search_query
                st.rerun()
            else:
                st.warning(f"Train ID '{search_query}' not found in active live trains.")

    display_list = list(live_trains.values())
    display_list.sort(key=lambda t: t["origintime"] if t["origintime"] != "--:--" else "99:99")

    st.write(f"({len(display_list)} live train data blocks returned by API)")

    # Build HTML table with exact color-coding and click action
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

        # Exact delay severity color rules from original script[cite: 3]
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
            <td><a href="?train={train_code}" target="_self" style="color: {train_id_color}; font-weight: bold; text-decoration: none;">{train_code}</a></td>
            <td style="color: #ffffff;">{train["origintime"]}</td>
            <td style="color: #ffffff;">{orig_display}</td>
            <td style="color: #ffffff;">{dest_display}</td>
            <td style="color: {color}; font-weight: bold;">{delay_text}</td>
            <td style="color: #ffffff;">{train["cleanStatus"]}</td>
            <td style="color: {reason_color};">{train["delayReason"]}</td>
        </tr>
        """
    html_table += "</table>"

    # Capture URL query parameters for click selection
    query_params = st.query_params
    if "train" in query_params:
        clicked_train = query_params["train"]
        st.session_state.selected_train = clicked_train
        st.rerun()

    st.markdown(html_table, unsafe_allow_html=True)

    # Alternatively, use a clean dropdown selector to jump to any train itinerary
    st.markdown("---")
    train_codes = [t["trainCode"] for t in display_list]
    selected_service = st.selectbox("Or select train ID to view full itinerary:", ["-- Select Train ID --"] + train_codes)
    if selected_service != "-- Select Train ID --":
        st.session_state.selected_train = selected_service
        st.rerun()

# Router controller
if st.session_state.selected_train:
    render_itinerary_view(st.session_state.selected_train)
else:
    render_dashboard()

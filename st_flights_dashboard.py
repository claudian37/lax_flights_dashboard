import altair as alt
import datetime as dt
import glob
import logging
import os
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objs as go
import requests
import streamlit as st
from typing import Optional
import warnings

warnings.filterwarnings("ignore")

# SET PAGE CONFIGS
st.set_page_config(
    layout="wide", page_title="LAX Flight Departures", page_icon=":airplane:"
)

# LOAD DATA
@st.experimental_singleton
def load_data(csv_filename: str, csv_filepath: str, airport_iata: str):
    date_today = dt.date.today()
    try:
        latest_csv_name = max(glob.glob(os.path.join(csv_filepath, csv_filename)))
        latest_csv_date = dt.datetime.strptime(latest_csv_name[-12:-4], "%Y%m%d").date()
    except:
        latest_csv_name = None
        latest_csv_date = None

    if latest_csv_date == date_today:
        data = pd.read_csv(latest_csv_name)
    else:
        # Call API for today's data
        timestamp_api_call = dt.datetime.now()
        api_key = os.environ.get("AIRLABS_API_KEY")
        url_base = "https://airlabs.co/api/v9/"
        url_path = "schedules"
        params = {"api_key": api_key, "dep_iata": airport_iata}
        result = requests.get(url_base + url_path, params)
        response = result.json().get("response")
        # If API returns no data, import latest csv
        if response == None:
            logging.error("Airlabs API returned no data: ", result.json())
            data = pd.read_csv(latest_csv_name)
        else:
            data = pd.DataFrame(response)
            data["timestamp_api_call"] = timestamp_api_call
            data.to_csv(
                os.path.join(
                    csv_filepath,
                    f"{airport_iata.lower()}_flights_{date_today.strftime('%Y%m%d')}.csv",
                ),
                index=False,
            )

    data["dep_time"] = pd.to_datetime(data["dep_time"])
    data["timestamp_api_call"] = pd.to_datetime(data["timestamp_api_call"])

    return data


# FILTER DATA FOR A SELECTED HOUR (CACHED)
@st.experimental_memo
def filter_data(
    data: pd.DataFrame,
    departure_hour: Optional[int],
    terminal_selected: Optional[str] = None,
):
    if departure_hour:
        data = data[data["dep_time"].dt.hour == departure_hour]
    if terminal_selected:
        data = data[data["dep_terminal"] == terminal_selected]
    return data


# CALCULATE DATA BY HOUR AND TERMINAL (CACHED)
@st.experimental_memo
def calculate_data_by_hour(
    data: pd.DataFrame,
    departure_hour: Optional[int],
    terminal_selected: Optional[str] = None,
):
    data = filter_data(data, departure_hour, terminal_selected)
    hist = np.histogram(data["dep_time"].dt.minute, bins=60, range=(0, 60))[0]

    return pd.DataFrame({"minute": range(60), "departures": hist})


# CALCULATE GROUPED DATA BY TERMINAL
@st.experimental_memo
def group_data_by_terminal(data: pd.DataFrame, departure_hour: Optional[int]):
    data = filter_data(data, departure_hour)
    grouped = (
        data.groupby(["dep_terminal"])
        .agg(count_flights=("flight_iata", "nunique"))
        .reset_index()
    )
    return grouped


# CALCULATE GROUPED DATA BY AIRLINE
@st.experimental_memo
def group_data_by_airline(data: pd.DataFrame, departure_hour: Optional[int]):
    data = filter_data(data, departure_hour)
    grouped = (
        data.groupby(["dep_terminal", "airline_iata"])
        .agg(count_flights=("flight_iata", "nunique"))
        .reset_index()
    )
    grouped["airport"] = "LAX"
    return grouped


# STREAMLIT APP LAYOUT
data = load_data(
    csv_filename="lax_flights_*.csv",
    csv_filepath="/Users/clau/Documents/Github/flights/data/",
    airport_iata="LAX",
)

# SEE IF THERE IS A QUERY PARAM IN URL
if not st.session_state.get("url_synced", False):
    try:
        hour_selected = int(st.experimental_get_query_params()["departure_hour"][0])
        st.session_state["departure_hour"] = hour_selected
        st.session_state["url_synced"] = True
    except KeyError:
        pass

# UPDATE QUERY PARAM IF SLIDER CHANGES
def update_query_params():
    hour_selected = st.session_state["departure_hour"]
    st.experimental_get_query_params()


# TOP SECTION APP LAYOUT
st.title("✈️ LAX Flight Departures Data")
st.markdown("#### About Dataset")
st.markdown(
    f"""
	Data pulled: {data["timestamp_api_call"].iloc[0].date()}\n
	Dataset contains all LAX flight departures from \
	{data["dep_time"].min().strftime("%Y-%m-%d %H")}:00 to \
	{data["dep_time"].max().strftime("%Y-%m-%d %H")}:00 (Pacific Time).
	"""
)
st.markdown(
    "***Adjust slider to see how LAX flight departures differ by terminal at different hours of the day.***"
)

hour_selected = st.slider(
    "Select hour of flight departure",
    0,
    23,
    key="departure_hour",
    on_change=update_query_params,
)

# LAYOUT MIDDLE SECTION OF APP WITH CHARTS
row2_1, row2_2 = st.columns((1, 1), gap="large")

# CALCULATE DATA FOR CHARTS
chart_data = calculate_data_by_hour(data, hour_selected)
grouped_by_terminal_data = group_data_by_terminal(data, hour_selected)
grouped_by_airline_data = group_data_by_airline(data, hour_selected)

chart_dep = (
    alt.Chart(chart_data)
    .mark_area(
        interpolate="step-after",
    )
    .encode(
        x=alt.X("minute:Q"),
        y=alt.Y("departures:Q"),
        tooltip=["minute", "departures"],
        opacity=alt.value(0.6),
        color=alt.value("red"),
    )
)

chart_terminal = (
    alt.Chart(grouped_by_terminal_data)
    .mark_bar()
    .encode(
        x=alt.X("count_flights:Q"),
        y=alt.Y("dep_terminal:N"),
        tooltip=["dep_terminal", "count_flights"],
        color=alt.Color("dep_terminal:N"),
        opacity=alt.OpacityValue(0.8),
    )
)
chart_all = alt.vconcat(
    chart_dep,
    chart_terminal,
    data=chart_data,
    autosize=alt.AutoSizeParams(contains="content", resize=True),
)

# PLOT CHARTS
with row2_1:
    st.write(
        f"**Breakdown of departures by terminal & airline between {hour_selected}:00 and {(hour_selected + 1) % 24}:00**"
    )
    if grouped_by_airline_data.empty:
        st.write(
            f"***No Flights leaving LAX between {hour_selected}:00 and {(hour_selected + 1) % 24}:00***"
        )
    else:
        fig = px.sunburst(
            grouped_by_airline_data,
            path=["airport", "dep_terminal", "airline_iata"],
            values="count_flights",
        )
        fig.update_layout(margin=go.layout.Margin(l=0, r=0, b=0, t=0))
        fig.update_traces(
            hovertemplate="terminal/airline:%{id},\n count_flights:%{value}",
            selector=dict(type="sunburst"),
        )
        st.plotly_chart(fig, use_container_width=True)

with row2_2:
    st.write(
        f"**Breakdown of departures per minute between {hour_selected}:00 and {(hour_selected + 1) % 24}:00**"
    )
    st.altair_chart(chart_all, use_container_width=True)

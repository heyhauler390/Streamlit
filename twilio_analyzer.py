import streamlit as st
import pandas as pd
import plotly.express as px
from pytz import timezone

# Caching data loading functions
@st.cache_data
def load_twilio_logs(uploaded_files):
    """Load multiple Twilio log files (CSV format) into a combined DataFrame."""
    combined_data = pd.DataFrame()
    for file in uploaded_files:
        df = pd.read_csv(file)
        combined_data = pd.concat([combined_data, df], ignore_index=True)
    return combined_data

@st.cache_data
def load_customer_list(customer_file):
    """Load the customer list file (Excel format)."""
    return pd.read_excel(customer_file)

# Title of the app
st.title("Twilio Multi-File Log Analyzer")

# Step 1: Upload multiple Twilio log files
uploaded_files = st.file_uploader(
    "Upload your Twilio message logs (CSV format)", 
    type=["csv"], 
    accept_multiple_files=True
)
customer_file = st.file_uploader(
    "Upload your customer list (Excel format)", 
    type=["xlsx"]
)

if uploaded_files and customer_file:
    # Load data
    message_logs = load_twilio_logs(uploaded_files)
    customer_list = load_customer_list(customer_file)

    # Rename dateSent to date for consistency
    if "dateSent" in message_logs.columns:
        message_logs.rename(columns={"dateSent": "date"}, inplace=True)
    else:
        st.error("The column 'dateSent' was not found in the log files.")
        st.stop()

    # Ensure the date column is parsed correctly
    message_logs["date"] = pd.to_datetime(message_logs["date"], errors="coerce", utc=True)

    # Convert to Mountain Time
    mountain_tz = timezone("US/Mountain")
    message_logs["date"] = message_logs["date"].dt.tz_convert(mountain_tz)

    # Extract only the date part
    message_logs["date"] = message_logs["date"].dt.date

    # Check for invalid dates
    if message_logs["date"].isnull().any():
        st.warning("Some rows have invalid dates. These rows will be ignored.")
        message_logs = message_logs[message_logs["date"].notnull()]

    # Standardize column names for matching
    message_logs.rename(columns={"to": "PhoneNumber"}, inplace=True)
    customer_list.rename(columns={"Number": "PhoneNumber"}, inplace=True)

    # Ensure 'PhoneNumber' columns are strings
    message_logs["PhoneNumber"] = message_logs["PhoneNumber"].astype(str)
    customer_list["PhoneNumber"] = customer_list["PhoneNumber"].astype(str)

    # Merge the data
    merged_data = pd.merge(
        message_logs, customer_list, on="PhoneNumber", how="left"
    )

    # Ensure numSegments is numeric and clean
    if "numSegments" in merged_data.columns:
        merged_data["numSegments"] = pd.to_numeric(merged_data["numSegments"], errors="coerce")
        merged_data["numSegments"].fillna(0, inplace=True)
        merged_data["numSegments"] = merged_data["numSegments"].astype(int)
    else:
        st.error("numSegments column not found in the merged data.")
        st.stop()

    # Ensure price is numeric and convert to positive
    if "price" in merged_data.columns:
        merged_data["price"] = pd.to_numeric(merged_data["price"], errors="coerce").abs()
        merged_data["price"].fillna(0, inplace=True)
    else:
        st.error("price column not found in the merged data.")
        st.stop()

    # Display the most recent date
    most_recent_date = merged_data["date"].max()
    st.subheader(f"Most Recent Date in Logs: {most_recent_date}")

    # Filter data to the most recent date
    recent_data = merged_data[merged_data["date"] == most_recent_date]

    # Analytics for the most recent date
    st.subheader("Analytics for the Most Recent Date")

    # Total messages by customer
    total_messages = recent_data.groupby("CO").size().reset_index(name="Total Messages")

    # Messages by segment type
    pivot_segments = pd.pivot_table(
        recent_data,
        values="PhoneNumber",
        index="CO",
        columns="numSegments",
        aggfunc="count",
        fill_value=0
    ).reset_index()

    # Total cost by customer
    total_cost = recent_data.groupby("CO")["price"].sum().reset_index(name="Total Cost")

    # Combine analytics into a single table
    combined_analytics = pd.merge(total_messages, pivot_segments, on="CO", how="outer")
    combined_analytics = pd.merge(combined_analytics, total_cost, on="CO", how="outer")

    # Display combined analytics
    st.dataframe(combined_analytics)

    # Create a historic stacked column chart for costs
    st.subheader("Historic Stacked Column Chart: Total Costs by Date and Customer")
    cost_by_date_customer = merged_data.groupby(["date", "CO"])["price"].sum().reset_index()
    fig = px.bar(
        cost_by_date_customer,
        x="date",
        y="price",
        color="CO",
        title="Total Costs by Date (Stacked by Customer)",
        labels={"price": "Total Cost ($)", "date": "Date", "CO": "Customer"}
    )
    st.plotly_chart(fig, use_container_width=True)

else:
    st.write("Please upload multiple Twilio log files and a customer list.")

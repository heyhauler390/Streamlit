import os
import pandas as pd
import streamlit as st
import plotly.express as px
from datetime import datetime, timedelta
from pytz import timezone
from dotenv import load_dotenv
import openai

# -----------------------------------
# 1. Load OpenAI API Key
# -----------------------------------
load_dotenv()
api_key = os.getenv("API_KEY") or st.secrets.get("API_KEY")
if not api_key:
    st.error("OpenAI API key not found. Please set it in a .env file or Streamlit Secrets.")
    st.stop()

openai.api_key = api_key  # Set the API key for OpenAI

# -----------------------------------
# 2. Helper Functions
# -----------------------------------
DEFAULT_CUSTOMER_LIST_PATH = "TwilioPhoneMap.xlsx"

@st.cache_data
def load_twilio_logs(uploaded_files):
    """Load multiple Twilio log files (CSV) into a single DataFrame."""
    combined_data = pd.DataFrame()
    for file in uploaded_files:
        df = pd.read_csv(file)
        combined_data = pd.concat([combined_data, df], ignore_index=True)
    return combined_data

@st.cache_data
def load_default_customer_list():
    """Load the default customer list (Excel)."""
    return pd.read_excel(DEFAULT_CUSTOMER_LIST_PATH)

@st.cache_data
def most_frequent(column, top_n=10):
    """Return the top N most frequent values in a column."""
    return column.value_counts().head(top_n).reset_index()

# -----------------------------------
# 3. Session State for Chat
# -----------------------------------
if "messages" not in st.session_state:
    st.session_state["messages"] = [
        {"role": "system", "content": "You are a data analysis assistant."}
    ]

# -----------------------------------
# 4. Main Page Logic
# -----------------------------------
st.title("Twilio Analyzer")

# Define the timezone
mountain_tz = timezone("US/Mountain")

# Calculate yesterday's date
today = datetime.now(tz=mountain_tz).date()
yesterday = today - timedelta(days=1)

# If merged_data not in session_state, show uploaders
if "merged_data" not in st.session_state:
    st.subheader("Upload Twilio Logs & Customer List")

    uploaded_files = st.file_uploader(
        "Upload your Twilio message logs (CSV format)",
        type=["csv"],
        accept_multiple_files=True
    )
    uploaded_customer_file = st.file_uploader(
        "Upload a customer list (Excel). If not provided, we'll use the default.",
        type=["xlsx"]
    )

    if uploaded_files:
        # Load Twilio logs
        message_logs = load_twilio_logs(uploaded_files)

        # Load or fallback to default
        if uploaded_customer_file:
            customer_list = pd.read_excel(uploaded_customer_file)
            st.success("Custom customer list loaded.")
        else:
            if os.path.exists(DEFAULT_CUSTOMER_LIST_PATH):
                customer_list = load_default_customer_list()
                st.info("Using default customer list.")
            else:
                st.error("No default customer list found. Please upload one.")
                st.stop()

        # Ensure necessary column
        if "dateSent" not in message_logs.columns:
            st.error("No 'dateSent' column in logs. Please check your CSV format.")
            st.stop()

        # Preprocess
        message_logs.rename(columns={"dateSent": "date"}, inplace=True)
        message_logs["date"] = pd.to_datetime(message_logs["date"], errors="coerce", utc=True)
        message_logs["date"] = message_logs["date"].dt.tz_convert(mountain_tz).dt.date

        message_logs.rename(columns={"to": "PhoneNumber"}, inplace=True)
        customer_list.rename(columns={"Number": "PhoneNumber"}, inplace=True)

        message_logs["PhoneNumber"] = message_logs["PhoneNumber"].astype(str)
        customer_list["PhoneNumber"] = customer_list["PhoneNumber"].astype(str)

        merged_data = pd.merge(message_logs, customer_list, on="PhoneNumber", how="left")
        merged_data["numSegments"] = pd.to_numeric(
            merged_data.get("numSegments", 0),
            errors="coerce"
        ).fillna(0).astype(int)
        merged_data["price"] = pd.to_numeric(
            merged_data.get("price", 0),
            errors="coerce"
        ).abs().fillna(0)

        # Store in session state
        st.session_state["merged_data"] = merged_data
        st.success("Data loaded! You can now see the Analysis below.")
    else:
        st.write("Please upload at least one Twilio log CSV to proceed.")

# If data is in session_state, show the analysis UI
if "merged_data" in st.session_state:
    st.divider()
    st.header("Analysis")

    merged_data = st.session_state["merged_data"]

    # Build list of customers
    customers_with_data = merged_data["CO"].dropna().unique().tolist()
    customers_with_data = sorted(customers_with_data)
    all_customers = ["All Customers"] + customers_with_data

    # Sidebar radio for customer selection
    selected_customer = st.sidebar.radio("Select a Customer", all_customers)

    # ---------------------------------------
    # Time Range Toggle
    # ---------------------------------------
    st.sidebar.subheader("Select Time Range")
    time_range = st.sidebar.radio(
        "Choose data to display:",
        ("All History", "Yesterday")
    )

    # Filter data based on time_range
    if time_range == "Yesterday":
        filtered_data = merged_data[merged_data["date"] == yesterday]
        st.sidebar.write(f"Displaying data for **{yesterday}**")
    else:
        filtered_data = merged_data
        st.sidebar.write("Displaying **All Historical Data**")

    # ---------------------------------------
    # All Customers Overview
    # ---------------------------------------
    if selected_customer == "All Customers":
        st.subheader("All Customers Overview")

        # Stacked column charts on top
        col1, col2 = st.columns(2)

        # Message Segments by Date Chart
        with col1:
            st.subheader("Message Segments by Date")
            segment_data = (
                filtered_data.groupby(["date", "numSegments"])
                .size()
                .reset_index(name="Count")
            )
            fig_segments = px.bar(
                segment_data,
                x="date",
                y="Count",
                color="numSegments",
                title="Messages Sent by Segment",
                labels={"numSegments": "Message Segment", "Count": "Number of Messages", "date": "Date"}
            )
            st.plotly_chart(fig_segments, use_container_width=True)

        # Message Status by Date Chart
        with col2:
            st.subheader("Message Status by Date")
            status_data = (
                filtered_data.groupby(["date", "status"])
                .size()
                .reset_index(name="Count")
            )
            fig_status = px.bar(
                status_data,
                x="date",
                y="Count",
                color="status",
                title="Messages Sent by Status",
                labels={"status": "Message Status", "Count": "Number of Messages", "date": "Date"}
            )
            st.plotly_chart(fig_status, use_container_width=True)

        # Stacked Bar Chart: Messages Sent by Customer
        st.subheader("Messages Sent by Customer Over Time")
        messages_by_customer = (
            filtered_data.groupby(["date", "CO"])
            .size()
            .reset_index(name="Count")
        )
        fig_customer_messages = px.bar(
            messages_by_customer,
            x="date",
            y="Count",
            color="CO",
            title="Messages Sent by Customer",
            labels={"CO": "Customer", "Count": "Number of Messages", "date": "Date"}
        )
        st.plotly_chart(fig_customer_messages, use_container_width=True)

        # Combined Table for All Customers
        st.subheader("Customer Summary Table")
        total_messages = filtered_data.groupby("CO").size().reset_index(name="Total Messages")
        pivot_segments = pd.pivot_table(
            filtered_data,
            values="PhoneNumber",
            index="CO",
            columns="numSegments",
            aggfunc="count",
            fill_value=0
        ).reset_index()

        # Convert all column names to strings to avoid mixed-type issues
        pivot_segments.columns = pivot_segments.columns.map(str)

        total_cost = filtered_data.groupby("CO")["price"].sum().reset_index(name="Total Cost")

        combined_table = total_messages.merge(pivot_segments, on="CO", how="outer").merge(total_cost, on="CO", how="outer")
        combined_table["Total Cost"] = combined_table["Total Cost"].map("${:,.2f}".format)

        st.write(combined_table)

    # ---------------------------------------
    # Individual Customer Dashboard
    # ---------------------------------------
    else:
        st.subheader(f"Dashboard for {selected_customer}")
        customer_data = filtered_data[filtered_data["CO"] == selected_customer].copy()

        # Stacked column charts on top
        col1, col2 = st.columns(2)

        # Message Segments by Date Chart
        with col1:
            st.subheader("Message Segments by Date")
            segment_data = (
                customer_data.groupby(["date", "numSegments"])
                .size()
                .reset_index(name="Count")
            )
            fig_segments = px.bar(
                segment_data,
                x="date",
                y="Count",
                color="numSegments",
                title=f"Messages Sent by Segment for {selected_customer}",
                labels={"numSegments": "Message Segment", "Count": "Number of Messages", "date": "Date"}
            )
            st.plotly_chart(fig_segments, use_container_width=True)

        # Message Status by Date Chart
        with col2:
            st.subheader("Message Status by Date")
            status_data = (
                customer_data.groupby(["date", "status"])
                .size()
                .reset_index(name="Count")
            )
            fig_status = px.bar(
                status_data,
                x="date",
                y="Count",
                color="status",
                title=f"Messages Sent by Status for {selected_customer}",
                labels={"status": "Message Status", "Count": "Number of Messages", "date": "Date"}
            )
            st.plotly_chart(fig_status, use_container_width=True)

        # Specific View for VITAL
        if selected_customer.upper() == "VITAL":
            st.subheader("Alarms by Route (VITAL)")
            
            # Extract and truncate the route names
            customer_data["Route"] = (
                customer_data["body"]
                .str.split(":", n=1, expand=True)[0]
                .str.strip()
                .apply(lambda x: x[:25] + "..." if len(x) > 25 else x)  # Truncate to 25 characters
            )
            
            # Group by date and route
            route_by_date = customer_data.groupby(["date", "Route"]).size().reset_index(name="Count")

            # Plot the stacked column chart
            fig_vital = px.bar(
                route_by_date,
                x="date",
                y="Count",
                color="Route",
                title="Messages by Route Over Time (VITAL)",
                labels={"date": "Date", "Count": "Total Messages", "Route": "Route"}
            )
            st.plotly_chart(fig_vital, use_container_width=True)

        # Top 10 Most Frequent Phone Numbers
        st.subheader("10 Most Frequent Phone Numbers")
        top_numbers = most_frequent(customer_data["PhoneNumber"], top_n=10)
        top_numbers.columns = ["Phone Number", "Count"]

        # Add Rank column starting at 1
        top_numbers.insert(0, "Rank", range(1, len(top_numbers) + 1))
        st.write(top_numbers)

        # Top Messages by Selected Number
        selected_number = st.selectbox("Select a Phone Number", top_numbers["Phone Number"])
        if selected_number:
            st.subheader(f"Top Messages for {selected_number}")
            msgs_for_number = (
                customer_data[customer_data["PhoneNumber"] == selected_number]["body"]
                .value_counts()
                .head(10)
                .reset_index()
            )
            msgs_for_number.columns = ["Messages", "Count"]
            st.write(msgs_for_number)

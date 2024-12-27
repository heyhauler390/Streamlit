import os
import pandas as pd
import streamlit as st
import plotly.express as px
from pytz import timezone
from openai import OpenAI

# Default customer list path
DEFAULT_CUSTOMER_LIST_PATH = "TwilioPhoneMap.xlsx"

@st.cache_data
def load_default_customer_list():
    """Load the default customer list file."""
    return pd.read_excel(DEFAULT_CUSTOMER_LIST_PATH)

@st.cache_data
def load_twilio_logs(uploaded_files):
    """Load multiple Twilio log files (CSV format) into a combined DataFrame."""
    combined_data = pd.DataFrame()
    for file in uploaded_files:
        df = pd.read_csv(file)
        combined_data = pd.concat([combined_data, df], ignore_index=True)
    return combined_data

@st.cache_data
def most_frequent(column, top_n=10):
    """Find the most frequent entries in a specific column."""
    return column.value_counts().head(top_n).reset_index()

# Initialize OpenAI API
api_key = os.getenv("API_KEY")
if not api_key:
    st.error("OpenAI API key not found. Please set it as an environment variable or in Streamlit Secrets.")
    st.stop()

client = OpenAI(api_key=api_key)

# Sidebar State Management
if "selected_customer" not in st.session_state:
    st.session_state["selected_customer"] = "All Customers"

st.title("Twilio Customer-Specific Dashboard")

# File uploader for logs
uploaded_files = st.file_uploader(
    "Upload your Twilio message logs (CSV format)", 
    type=["csv"], 
    accept_multiple_files=True
)

# File uploader for customer list updates
uploaded_customer_file = st.file_uploader(
    "Upload an updated customer list (Excel format). If no file is uploaded, the default list will be used.", 
    type=["xlsx"]
)

# Load customer list
if uploaded_customer_file:
    customer_list = pd.read_excel(uploaded_customer_file)
    st.success("Updated customer list loaded.")
else:
    if os.path.exists(DEFAULT_CUSTOMER_LIST_PATH):
        customer_list = load_default_customer_list()
        st.info("Using the default customer list.")
    else:
        st.error("Default customer list not found. Please upload a customer list.")
        st.stop()

if uploaded_files:
    # Load message logs
    message_logs = load_twilio_logs(uploaded_files)

    # Rename and preprocess columns
    if "dateSent" in message_logs.columns:
        message_logs.rename(columns={"dateSent": "date"}, inplace=True)
    else:
        st.error("The column 'dateSent' was not found in the log files.")
        st.stop()

    message_logs["date"] = pd.to_datetime(message_logs["date"], errors="coerce", utc=True)
    mountain_tz = timezone("US/Mountain")
    message_logs["date"] = message_logs["date"].dt.tz_convert(mountain_tz).dt.date
    message_logs.rename(columns={"to": "PhoneNumber"}, inplace=True)
    customer_list.rename(columns={"Number": "PhoneNumber"}, inplace=True)
    message_logs["PhoneNumber"] = message_logs["PhoneNumber"].astype(str)
    customer_list["PhoneNumber"] = customer_list["PhoneNumber"].astype(str)
    merged_data = pd.merge(message_logs, customer_list, on="PhoneNumber", how="left")
    merged_data["numSegments"] = pd.to_numeric(merged_data.get("numSegments", 0), errors="coerce").fillna(0).astype(int)
    merged_data["price"] = pd.to_numeric(merged_data.get("price", 0), errors="coerce").abs().fillna(0)

    # Sidebar Tabs for Customers
    all_customers = ["All Customers"] + customer_list["CO"].unique().tolist()
    selected_customer = st.sidebar.radio("Select a Customer", all_customers, key="customer_selection")

    if selected_customer == "All Customers":
        st.subheader("All Customers Overview")

        # Analytics for All Customers
        total_messages = merged_data.groupby("CO").size().reset_index(name="Total Messages")
        pivot_segments = pd.pivot_table(
            merged_data,
            values="PhoneNumber",
            index="CO",
            columns="numSegments",
            aggfunc="count",
            fill_value=0
        ).reset_index()
        total_cost = merged_data.groupby("CO")["price"].sum().reset_index(name="Total Cost")

        combined_analytics = pd.merge(total_messages, pivot_segments, on="CO", how="outer")
        combined_analytics = pd.merge(combined_analytics, total_cost, on="CO", how="outer")

        # Display analytics
        st.dataframe(combined_analytics)

        # Historic stacked column chart
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

        # Chat Interface
        st.subheader("Ask Questions About Your Data")
        user_question = st.text_input("Enter your question:")

        if user_question:
            try:
                response = client.chat.completions.create(
                    model="gpt-4",
                    messages=[
                        {"role": "system", "content": "You are a data analysis assistant."},
                        {"role": "user", "content": f"Dataset: {merged_data.to_dict(orient='records')}. Question: {user_question}"}
                    ]
                )
                answer = response.choices[0].message.content
                st.write("Answer:")
                st.write(answer)
            except Exception as e:
                st.error(f"Error: {str(e)}")
    else:
        st.subheader(f"Dashboard for {selected_customer}")
        customer_data = merged_data[merged_data["CO"] == selected_customer]

        # Most frequent phone numbers
        st.subheader("10 Most Frequent Phone Numbers")
        top_numbers = most_frequent(customer_data["PhoneNumber"], top_n=10)
        top_numbers.columns = ["Phone Number", "Count"]
        st.table(top_numbers)

        # Top messages for a selected number
        selected_number = st.selectbox("Select a Phone Number", top_numbers["Phone Number"])
        if selected_number:
            st.subheader(f"Top Messages for {selected_number}")
            messages_for_number = customer_data[customer_data["PhoneNumber"] == selected_number]["body"]
            st.table(messages_for_number.head(10))

        # Stacked column chart for message segments by date
        st.subheader("Message Segments by Date")
        segment_data = (
            customer_data.groupby(["date", "numSegments"])
            .size()
            .reset_index(name="Count")
        )
        fig = px.bar(
            segment_data,
            x="date",
            y="Count",
            color="numSegments",
            title=f"Messages Sent by Segment for {selected_customer}",
            labels={"numSegments": "Message Segment", "Count": "Number of Messages", "date": "Date"}
        )
        st.plotly_chart(fig, use_container_width=True)

        # Chat Interface
        st.subheader("Ask Questions About This Customer's Data")
        user_question = st.text_input("Enter your question:", key=f"chat_{selected_customer}")

        if user_question:
            try:
                response = client.chat.completions.create(
                    model="gpt-4",
                    messages=[
                        {"role": "system", "content": "You are a data analysis assistant."},
                        {"role": "user", "content": f"Dataset for {selected_customer}: {customer_data.to_dict(orient='records')}. Question: {user_question}"}
                    ]
                )
                answer = response.choices[0].message.content
                st.write("Answer:")
                st.write(answer)
            except Exception as e:
                st.error(f"Error: {str(e)}")
else:
    st.write("Please upload your Twilio message logs.")

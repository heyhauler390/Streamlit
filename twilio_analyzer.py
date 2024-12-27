import os
import streamlit as st
import pandas as pd
import plotly.express as px
from pytz import timezone
from collections import Counter
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables from .env file for local development
load_dotenv()

# Function to get the API key based on the environment
def get_api_key():
    try:
        # Check if Streamlit secrets exist and retrieve the API key
        return st.secrets["API_KEY"]
    except (FileNotFoundError, KeyError, AttributeError):
        # Fallback to .env for local development
        return os.getenv("API_KEY")

# Retrieve the API key
api_key = get_api_key()

# Initialize OpenAI client with the API key
if not api_key:
    st.error("API key not found. Please set it in a .env file for local development or Streamlit Secrets for deployment.")
    st.stop()
else:
    st.success("API key successfully loaded.")
    client = OpenAI(api_key=api_key)

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

@st.cache_data
def most_frequent_messages(dataframe, column, top_n=10):
    """Find the most frequent full messages in a specific column."""
    message_counts = dataframe[column].value_counts().head(top_n).reset_index()
    message_counts.columns = ["Message", "Count"]
    return message_counts

st.title("Twilio Multi-File Log Analyzer with Chat")

# File uploaders for logs and customer list
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

    # Display most frequent messages
    st.subheader("Most Frequent Messages")
    frequent_messages = most_frequent_messages(merged_data, "body", top_n=10)
    st.table(frequent_messages)

    # Most recent date
    most_recent_date = merged_data["date"].max()
    st.subheader(f"Most Recent Date in Logs: {most_recent_date}")

    # Filter for most recent date
    recent_data = merged_data[merged_data["date"] == most_recent_date]

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
        # Aggregate trends and reduce data size
        trend_data = (
            merged_data.groupby(["date", "CO", "numSegments"])
            .size()
            .reset_index(name="Message Count")
            .head(50)  # Limit to 50 rows for smaller context
        )
        
        # Aggregate phone number data
        phone_data = (
            merged_data.groupby(["CO", "PhoneNumber"]).size()
            .reset_index(name="Total Messages")
            .sort_values(by="Total Messages", ascending=False)
            .head(50)  # Limit to 50 rows for smaller context
        )
        
        # Limit the frequent messages to top 10
        frequent_messages_limited = frequent_messages.head(10).to_dict(orient="records")

        # Combine reduced summaries
        context_data = {
            "trends": trend_data.to_dict(orient="records"),
            "phone_summary": phone_data.to_dict(orient="records"),
            "frequent_messages": frequent_messages_limited
        }

        try:
            # Call OpenAI API with reduced input
            response = client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "You are a data analysis assistant. Use the provided dataset to answer questions."},
                    {"role": "user", "content": f"Dataset: {context_data}. Question: {user_question}"}
                ]
            )
            # Extract response
            answer = response.choices[0].message.content
            st.write("Answer:")
            st.write(answer)
        except Exception as e:
            st.error(f"Error: {str(e)}")
else:
    st.write("Please upload multiple Twilio log files and a customer list.")

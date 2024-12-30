import os
import pandas as pd
import streamlit as st
import plotly.express as px
from datetime import datetime
from pytz import timezone
from dotenv import load_dotenv
from openai import OpenAI

# --------------------------
# 1. Load OpenAI API Key
# --------------------------
load_dotenv()
api_key = os.getenv("API_KEY") or st.secrets.get("API_KEY")
if not api_key:
    st.error("OpenAI API key not found. Please set it in a .env file or Streamlit Secrets.")
    st.stop()

client = OpenAI(api_key=api_key)

# --------------------------
# 2. Helper Functions
# --------------------------
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

# --------------------------
# 3. Session State for Chat
# --------------------------
if "messages" not in st.session_state:
    st.session_state["messages"] = [
        {"role": "system", "content": "You are a data analysis assistant."}
    ]

# --------------------------
# 4. Main Page Logic
# --------------------------
st.title("Twilio Analyzer")

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
        mountain_tz = timezone("US/Mountain")
        message_logs["date"] = message_logs["date"].dt.tz_convert(mountain_tz).dt.date

        message_logs.rename(columns={"to": "PhoneNumber"}, inplace=True)
        customer_list.rename(columns={"Number": "PhoneNumber"}, inplace=True)

        message_logs["PhoneNumber"] = message_logs["PhoneNumber"].astype(str)
        customer_list["PhoneNumber"] = customer_list["PhoneNumber"].astype(str)

        merged_data = pd.merge(message_logs, customer_list, on="PhoneNumber", how="left")
        merged_data["numSegments"] = pd.to_numeric(merged_data.get("numSegments", 0), errors="coerce").fillna(0).astype(int)
        merged_data["price"] = pd.to_numeric(merged_data.get("price", 0), errors="coerce").abs().fillna(0)

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

    # Sidebar radio
    selected_customer = st.sidebar.radio("Select a Customer", all_customers)

    # ---------------------------------------
    # All Customers
    # ---------------------------------------
    if selected_customer == "All Customers":
        st.subheader("All Customers Overview")

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

        st.dataframe(combined_analytics)

        cost_by_date_customer = merged_data.groupby(["date", "CO"])["price"].sum().reset_index()
        fig_all = px.bar(
            cost_by_date_customer,
            x="date",
            y="price",
            color="CO",
            title="Total Costs by Date (Stacked by Customer)",
            labels={"price": "Total Cost ($)", "date": "Date", "CO": "Customer"}
        )
        st.plotly_chart(fig_all, use_container_width=True)

        # GPT Q&A
        st.subheader("Ask Questions About All Customers' Data")
        user_question = st.text_input("Enter your question for All Customers:")
        if user_question:
            st.session_state["messages"].append({"role": "user", "content": user_question})
            try:
                response = client.chat.completions.create(
                    model="gpt-4",
                    messages=st.session_state["messages"]
                )
                answer = response.choices[0].message.content
                st.session_state["messages"].append({"role": "assistant", "content": answer})
                st.write("**Answer:**")
                st.write(answer)
            except Exception as e:
                st.error(f"Error: {str(e)}")

    # ---------------------------------------
    # Individual Customer
    # ---------------------------------------
    else:
        st.subheader(f"Dashboard for {selected_customer}")
        customer_data = merged_data[merged_data["CO"] == selected_customer]

        # If VITAL, parse route and show stacked route chart
        if selected_customer == "VITAL":
            st.subheader("Alarms by Route (VITAL)")

            customer_data["Route"] = (
                customer_data["body"]
                .astype(str)
                .str.split(":", n=1, expand=True)
                .iloc[:, 0]
                .str.strip()
            )

            # Create a stacked column chart with date on x, total messages on y, color by Route
            route_by_date = customer_data.groupby(["date", "Route"]).size().reset_index(name="Count")
            fig_stacked = px.bar(
                route_by_date,
                x="date",
                y="Count",
                color="Route",
                title="Messages by Route Over Time (VITAL) (Stacked)",
                labels={"date": "Date", "Count": "Total Messages", "Route": "Route"}
            )
            st.plotly_chart(fig_stacked, use_container_width=True)

        # Shared stats for all customers
        st.subheader("10 Most Frequent Phone Numbers")
        top_numbers = most_frequent(customer_data["PhoneNumber"], top_n=10)
        top_numbers.columns = ["Phone Number", "Count"]
        st.table(top_numbers)

        selected_number = st.selectbox("Select a Phone Number", top_numbers["Phone Number"])
        if selected_number:
            st.subheader(f"Top Messages for {selected_number}")
            msgs_for_number = customer_data[customer_data["PhoneNumber"] == selected_number]["body"]
            st.table(msgs_for_number.head(10))

        st.subheader("Message Segments by Date")
        segment_data = (
            customer_data.groupby(["date", "numSegments"])
            .size()
            .reset_index(name="Count")
        )
        fig_customer = px.bar(
            segment_data,
            x="date",
            y="Count",
            color="numSegments",
            title=f"Messages Sent by Segment for {selected_customer}",
            labels={"numSegments": "Message Segment", "Count": "Number of Messages", "date": "Date"}
        )
        st.plotly_chart(fig_customer, use_container_width=True)

        # GPT Q&A
        st.subheader(f"Ask Questions About {selected_customer}'s Data")
        user_question = st.text_input("Enter your question:", key=f"chat_{selected_customer}")
        if user_question:
            st.session_state["messages"].append({"role": "user", "content": user_question})
            try:
                response = client.chat.completions.create(
                    model="gpt-4",
                    messages=st.session_state["messages"]
                )
                answer = response.choices[0].message.content
                st.session_state["messages"].append({"role": "assistant", "content": answer})
                st.write("**Answer:**")
                st.write(answer)
            except Exception as e:
                st.error(f"Error: {str(e)}")

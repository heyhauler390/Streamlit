import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt

# Caching the data loading functions
@st.cache_data
def load_twilio_log(uploaded_file):
    """Load the Twilio log file (CSV format)"""
    return pd.read_csv(uploaded_file)

@st.cache_data
def load_customer_list(customer_file):
    """Load the customer list file (Excel format)"""
    return pd.read_excel(customer_file)

# Title of the app
st.title("Twilio Message Log Analyzer")

# Step 1: Upload the Twilio log file
uploaded_file = st.file_uploader("Upload your Twilio message log (CSV format)", type=["csv"])
customer_file = st.file_uploader("Upload your customer list (Excel format)", type=["xlsx"])

if uploaded_file and customer_file:
    # Load data using caching
    message_log = load_twilio_log(uploaded_file)
    customer_list = load_customer_list(customer_file)

    # Step 3: Standardize Column Names for Matching
    message_log.rename(columns={"to": "PhoneNumber"}, inplace=True)
    customer_list.rename(columns={"Number": "PhoneNumber"}, inplace=True)

    # Ensure 'PhoneNumber' columns are strings
    message_log["PhoneNumber"] = message_log["PhoneNumber"].astype(str)
    customer_list["PhoneNumber"] = customer_list["PhoneNumber"].astype(str)

    # Step 4: Merge the data
    merged_data = pd.merge(
        message_log, customer_list, on="PhoneNumber", how="left"
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

    # Step 5: Aggregate Messages by Company (CO)
    if "CO" in merged_data.columns:
        # Total cost by company
        total_cost = merged_data.groupby("CO")["price"].sum().reset_index(name="Total Cost")
        st.subheader("Total Message Cost by Customer")
        st.dataframe(total_cost)

        # Option to download the total cost table
        total_cost_csv = total_cost.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="Download Total Cost Summary as CSV",
            data=total_cost_csv,
            file_name="total_message_cost_by_customer.csv",
            mime="text/csv"
        )

        # Add a pie chart for total costs
        filtered_total_cost = total_cost[total_cost["Total Cost"] > 0]
        st.subheader("Total Costs per Customer - Pie Chart")
        if not filtered_total_cost.empty:
            fig, ax = plt.subplots()
            ax.pie(
                filtered_total_cost["Total Cost"],
                labels=filtered_total_cost["CO"],
                autopct='%1.1f%%',
                startangle=90
            )
            ax.axis("equal")  # Equal aspect ratio ensures the pie is drawn as a circle.
            st.pyplot(fig)
        else:
            st.write("No data to display in the pie chart. All costs are zero or negative.")

        # Group by company (CO) and count the number of messages
        summary = merged_data.groupby("CO").size().reset_index(name="Message Count")
        st.subheader("Message Summary by Company")
        st.dataframe(summary)

        csv = summary.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="Download Message Summary as CSV",
            data=csv,
            file_name="message_summary_by_company.csv",
            mime="text/csv"
        )

        # Step 6: Create Pivot Table for numSegments
        pivot_table = pd.pivot_table(
            merged_data,
            values="PhoneNumber",  # Use PhoneNumber to count occurrences
            index="CO",
            columns="numSegments",
            aggfunc="count",
            fill_value=0
        )

        # Reset index to display as a table
        pivot_table.reset_index(inplace=True)

        st.subheader("Message Segments Count by Customer")
        st.dataframe(pivot_table)

        pivot_csv = pivot_table.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="Download Message Segments Summary as CSV",
            data=pivot_csv,
            file_name="message_segments_summary.csv",
            mime="text/csv"
        )
    else:
        st.error("CO column not found in the merged data.")
else:
    st.write("Please upload both the Twilio log (CSV) and customer list (Excel) files.")

import pandas as pd
import streamlit as st

def create_comprehensive_failure_table():
    """Create comprehensive failure analysis table"""
    
    st.header("📊 Comprehensive Failure Analysis Table")
    
    # Load data
    df = pd.read_csv('snowbird_field_returns.csv')
    
    # Summary metrics
    col1, col2, col3, col4 = st.columns(4)
    
    total_returns = len(df)
    real_failures = len(df[df['Root_Cause'] == 'Root Cause Identified'])
    ntf_cases = len(df[df['Root_Cause'] == 'No Failure Found'])
    wont_do = len(df[df['Root_Cause'] == "Won't do"])
    
    col1.metric("Total Returns", total_returns)
    col2.metric("Real Failures", real_failures, f"{real_failures/total_returns*100:.1f}%")
    col3.metric("NTF (No Trouble Found)", ntf_cases, f"{ntf_cases/total_returns*100:.1f}%")
    col4.metric("Won't Do (Not Analyzed)", wont_do, f"{wont_do/total_returns*100:.1f}%")
    
    st.markdown("---")
    
    # Create organized failure categories
    st.subheader("Failure Analysis by Category")
    
    # Real Failures (Root Cause Identified)
    with st.expander("✅ REAL FAILURES - Root Cause Identified (10 cases)", expanded=True):
        real_fail = df[df['Root_Cause'] == 'Root Cause Identified'].copy()
        
        # Normalize Root_Cause_Reason (fix inconsistencies)
        real_fail['Root_Cause_Reason_Normalized'] = real_fail['Root_Cause_Reason'].str.lower().str.strip()
        real_fail.loc[real_fail['Root_Cause_Reason_Normalized'].str.contains('liquid', na=False), 'Root_Cause_Reason_Normalized'] = 'Liquid Ingress'
        real_fail.loc[real_fail['Root_Cause_Reason_Normalized'] == 'eipd', 'Root_Cause_Reason_Normalized'] = 'EIPD/EOS'
        real_fail.loc[real_fail['Root_Cause_Reason_Normalized'].str.contains('exothermic', na=False), 'Root_Cause_Reason_Normalized'] = 'Exothermic Event (PSU/Outlet)'
        real_fail.loc[real_fail['Root_Cause_Reason_Normalized'].str.contains('emmc', na=False), 'Root_Cause_Reason_Normalized'] = 'eMMC Corruption'
        real_fail.loc[real_fail['Root_Cause_Reason_Normalized'].str.contains('cloud', na=False), 'Root_Cause_Reason_Normalized'] = 'Cloud Registration'
        real_fail.loc[real_fail['Root_Cause_Reason_Normalized'].str.contains('mount', na=False), 'Root_Cause_Reason_Normalized'] = 'Mount Bracket'
        
        # Summary by root cause
        st.markdown("**Breakdown by Root Cause:**")
        cause_summary = real_fail['Root_Cause_Reason_Normalized'].value_counts()
        for cause, count in cause_summary.items():
            st.write(f"- **{cause}**: {count} case(s)")
        
        # Detailed table
        st.markdown("**Detailed Cases:**")
        display_cols = ['ID', 'User_Reported_Date', 'Return_Reason_Code', 'Root_Cause_Reason', 
                       'Power_Adapter', 'SW_Related_Issue', 'HW_Related_Issue', 'Jira_Ticket']
        st.dataframe(real_fail[display_cols], use_container_width=True, hide_index=True)
    
    # No Trouble Found (NTF)
    with st.expander("❌ NO TROUBLE FOUND (NTF) - No Failure Found (9 cases)", expanded=True):
        ntf = df[df['Root_Cause'] == 'No Failure Found'].copy()
        
        st.markdown("**Breakdown by Return Reason:**")
        ntf_reasons = ntf['Return_Reason_Code'].value_counts()
        for reason, count in ntf_reasons.items():
            st.write(f"- **{reason}**: {count} case(s)")
        
        # Detailed table
        st.markdown("**Detailed Cases:**")
        display_cols = ['ID', 'User_Reported_Date', 'Return_Reason_Code', 'Root_Cause_Reason', 
                       'Power_Adapter', 'Comments']
        st.dataframe(ntf[display_cols], use_container_width=True, hide_index=True)
    
    # Won't Do (Not Analyzed)
    with st.expander("⚠️ WON'T DO - Not Analyzed (Units Not Returned) (43 cases)", expanded=False):
        wont = df[df['Root_Cause'] == "Won't do"].copy()
        
        st.warning(f"**{len(wont)} cases** were marked as 'Won't do' because units were never returned for analysis")
        
        st.markdown("**Breakdown by Return Reason:**")
        wont_reasons = wont['Return_Reason_Code'].value_counts()
        for reason, count in wont_reasons.items():
            st.write(f"- **{reason}**: {count} case(s)")
        
        # Detailed table
        st.markdown("**Detailed Cases:**")
        display_cols = ['ID', 'User_Reported_Date', 'Return_Reason_Code', 'Unit_SN', 'Comments']
        st.dataframe(wont[display_cols], use_container_width=True, hide_index=True)
    
    # Other statuses
    other = df[~df['Root_Cause'].isin(['Root Cause Identified', 'No Failure Found', "Won't do"])].copy()
    if len(other) > 0:
        with st.expander(f"📋 OTHER STATUS ({len(other)} cases)", expanded=False):
            st.dataframe(other[['ID', 'Return_Reason_Code', 'Root_Cause', 'Comments']], 
                        use_container_width=True, hide_index=True)
    
    st.markdown("---")
    
    # DAA Analysis
    st.subheader("🔍 DAA (Dead After Arrival) Deep Dive")
    
    daa_cases = df[df['Return_Reason_Code'] == 'DAA'].copy()
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total DAA", len(daa_cases))
    col2.metric("DAA - Real Failures", len(daa_cases[daa_cases['Root_Cause'] == 'Root Cause Identified']))
    col3.metric("DAA - NTF", len(daa_cases[daa_cases['Root_Cause'] == 'No Failure Found']))
    col4.metric("DAA - Won't Do", len(daa_cases[daa_cases['Root_Cause'] == "Won't do"]))
    
    # DAA with root causes
    daa_real = daa_cases[daa_cases['Root_Cause'] == 'Root Cause Identified']
    if len(daa_real) > 0:
        st.markdown("**DAA Root Causes:**")
        for idx, row in daa_real.iterrows():
            st.write(f"- ID {row['ID']}: **{row['Root_Cause_Reason']}** - {row['Comments'][:100]}...")
    
    st.markdown("---")
    
    # Power/PSU Analysis
    st.subheader("⚡ Power Adapter / PSU Analysis")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**Power Adapter Distribution:**")
        power_dist = df['Power_Adapter'].value_counts()
        for adapter, count in power_dist.items():
            if pd.notna(adapter):
                st.write(f"- {adapter}: {count}")
    
    with col2:
        st.markdown("**PSU-Related Failures:**")
        # Check for Goldfinch (PSU) issues
        goldfinch_cases = df[df['Power_Adapter'] == 'Goldfinch']
        goldfinch_failures = goldfinch_cases[goldfinch_cases['Root_Cause'] == 'Root Cause Identified']
        
        st.write(f"- Total Goldfinch (30W PSU) cases: {len(goldfinch_cases)}")
        st.write(f"- Goldfinch with failures: {len(goldfinch_failures)}")
        
        # Exothermic events (PSU/outlet related)
        exothermic = df[df['Root_Cause_Reason'].str.contains('exothermic', case=False, na=False)]
        if len(exothermic) > 0:
            st.write(f"- **Exothermic events (PSU/outlet): {len(exothermic)}**")
            for idx, row in exothermic.iterrows():
                st.write(f"  - ID {row['ID']}: {row['Comments'][:100]}...")
    
    st.markdown("---")
    
    # Liquid Ingress Analysis
    st.subheader("💧 Liquid Ingress Analysis")
    
    # Find all liquid ingress cases (case-insensitive)
    liquid_cases = df[df['Root_Cause_Reason'].str.contains('liquid|ingress', case=False, na=False)]
    
    st.write(f"**Total Liquid Ingress Cases: {len(liquid_cases)}**")
    st.info("Note: 'Liquid ingress' and 'Liquid Ingress' are the same failure mode (case variation)")
    
    for idx, row in liquid_cases.iterrows():
        st.write(f"- **ID {row['ID']}**: {row['Root_Cause_Reason']}")
        st.caption(f"  Comment: {row['Comments'][:150]}...")
    
    st.markdown("---")
    
    # Export full analysis
    st.subheader("📥 Export Analysis")
    
    # Create summary dataframe
    summary_data = []
    for idx, row in df.iterrows():
        summary_data.append({
            'ID': row['ID'],
            'Date': row['User_Reported_Date'],
            'Return_Reason': row['Return_Reason_Code'],
            'Root_Cause_Status': row['Root_Cause'],
            'Root_Cause_Detail': row['Root_Cause_Reason'],
            'Power_Adapter': row['Power_Adapter'],
            'SW_Issue': row['SW_Related_Issue'],
            'HW_Issue': row['HW_Related_Issue'],
            'JIRA': row['Jira_Ticket'],
            'Category': 'Real Failure' if row['Root_Cause'] == 'Root Cause Identified' 
                       else 'NTF' if row['Root_Cause'] == 'No Failure Found'
                       else "Won't Do" if row['Root_Cause'] == "Won't do"
                       else 'Other'
        })
    
    summary_df = pd.DataFrame(summary_data)
    
    csv = summary_df.to_csv(index=False)
    st.download_button(
        label="📥 Download Complete Analysis (CSV)",
        data=csv,
        file_name="snowbird_failure_analysis_complete.csv",
        mime="text/csv"
    )

if __name__ == "__main__":
    st.set_page_config(page_title="Failure Analysis Table", layout="wide")
    create_comprehensive_failure_table()

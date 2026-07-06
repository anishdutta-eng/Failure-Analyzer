# Failure Analysis Pattern Recognition Tool

An interactive GUI application for analyzing field return data, identifying failure patterns, and generating comprehensive reports.

## Features

### Dashboard View
- **Interactive Dashboard**: Web-based GUI built with Streamlit
- **Data Visualization**: Multiple chart types (bar, pie, line, sunburst)
- **Fault Tree Analysis**: Hierarchical visualization of failure causes
- **Timeline Analysis**: Track returns over time
- **SW vs HW Breakdown**: Categorize software and hardware issues
- **Report Generation**: Automated Word document reports
- **Data Export**: Export filtered data and analysis results
- **Multi-Program Support**: Designed to scale from Snowbird to other programs

### Triage Assistant (NEW)
- **Technical Keyword Search**: Search historical data for specific terms (eMMC, liquid ingress, EIPD, etc.)
- **Product Knowledge Base**: Built-in technical specs for eero Outdoor 7 (Snowbird)
- **LED Status Reference**: Complete LED indicator diagnostic guide
- **Failure Mode Identification**: Automatically identifies likely failure modes
- **ML-Powered Predictions**: Machine learning predicts root causes with confidence scores
- **Technical Triage Procedures**: Detailed, step-by-step diagnostic procedures
- **JIRA Integration**: Finds and displays related JIRA tickets
- **Similar Case Matching**: Shows historical cases with similar symptoms
- **Priority Assessment**: Automatic priority assignment (Critical/High/Medium/Low)

## Installation

1. Install Python 3.8 or higher

2. Install dependencies:
```bash
pip3 install -r requirements.txt
```

3. Configure Streamlit (optional - already done):
```bash
mkdir -p ~/.streamlit
```

The app is pre-configured to disable telemetry and welcome messages.

## Usage

1. Start the application:
```bash
streamlit run failure_analysis_app.py
```

Or if `streamlit` command is not found:
```bash
python3 -m streamlit run failure_analysis_app.py
```

2. The app will open in your default browser at `http://localhost:8501`

3. In the sidebar:
   - Enter your program name (default: Snowbird)
   - Upload your CSV file
   - Select analysis options

4. Explore the visualizations and generate reports

## CSV File Format

The tool expects a CSV file with the following columns:
- ID
- User_Reported_Date
- Return_Reason_Code
- Unit_SN
- Power_Adapter
- Root_Cause
- Root_Cause_Reason
- SW_Related_Issue
- HW_Related_Issue
- Shipment_Status
- Comments
- (and other relevant fields)

## Adding New Programs

To analyze data from other programs:
1. Prepare your CSV file in the same format
2. Enter the new program name in the sidebar
3. Upload the CSV file
4. The tool will automatically adapt to the new program

## Report Output

Generated reports include:
- Executive summary with key metrics
- Top return reasons
- Root cause breakdown
- SW vs HW issue analysis
- Exportable in Word (.docx) format

## Technology Stack

- **Python**: Core programming language
- **Streamlit**: Web-based GUI framework
- **Pandas**: Data manipulation and analysis
- **Plotly**: Interactive visualizations
- **Matplotlib/Seaborn**: Additional plotting capabilities
- **python-docx**: Report generation

## Future Enhancements

- Machine learning for pattern prediction
- Comparative analysis across programs
- Advanced filtering and search
- Custom report templates
- Database integration
- Email notifications for critical failures

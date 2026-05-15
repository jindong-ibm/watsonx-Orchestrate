"""
Predictive Maintenance Flow

Orchestrates the full predictive maintenance pipeline:
1. Collect IoT sensor data via Sensor MCP server
2. Analyze anomalies and root causes
3. Retrieve maintenance history via Maintenance History MCP server
4. Generate maintenance recommendation
5. Human-in-the-loop: operator reviews recommendation and approves/rejects
6. Check spare parts via Spare Parts MCP server
7. Order spare parts if stock is low (branch on urgency)
8. Generate detailed maintenance plan with work items
9. Format and deliver the final maintenance report

The flow uses:
- aflow.tool() for Python tool nodes
- aflow.tool("mcp_tool_name") for MCP toolkit tool nodes
- aflow.userflow() + user_flow.field() for human-in-the-loop interactions
- aflow.branch() for conditional spare parts ordering
- aflow.map_output() for explicit output mapping
"""

from pydantic import BaseModel, Field
from ibm_watsonx_orchestrate.flow_builder.flows import Flow, flow, Branch, START, END
from ibm_watsonx_orchestrate.flow_builder.types import UserFieldKind
from ibm_watsonx_orchestrate.flow_builder.data_map import DataMap
from ibm_watsonx_orchestrate.flow_builder.types import Assignment

from .analyze_sensor_anomalies import analyze_sensor_anomalies
from .generate_maintenance_recommendation import generate_maintenance_recommendation
from .generate_maintenance_plan import generate_maintenance_plan
from .format_maintenance_report import format_maintenance_report


# ── Input / Output Schemas ─────────────────────────────────────────────────────

class PredictiveMaintenanceInput(BaseModel):
    """Input schema for the Predictive Maintenance Flow."""
    device_name: str = Field(
        description="Unique name or identifier of the device to analyze (e.g., 'PUMP-001')"
    )
    device_type: str = Field(
        description=(
            "Type/category of the device. Supported types: "
            "centrifugal_pump, air_compressor, electric_motor, conveyor, turbine"
        )
    )
    timestamp: str = Field(
        default="",
        description=(
            "ISO 8601 timestamp for sensor data retrieval. "
            "Leave empty to use current time."
        )
    )


class PredictiveMaintenanceOutput(BaseModel):
    """Output schema for the Predictive Maintenance Flow."""
    maintenance_report: str = Field(
        description="Complete formatted Markdown maintenance report"
    )


# ── Flow Definition ────────────────────────────────────────────────────────────

@flow(
    name="predictive_maintenance_flow",
    display_name="Predictive Maintenance Flow",
    description=(
        "End-to-end predictive maintenance pipeline for manufacturing equipment. "
        "Collects IoT sensor data, detects anomalies, retrieves maintenance history, "
        "generates recommendations, checks spare parts, and produces a detailed "
        "maintenance plan with work items. Includes human-in-the-loop approval."
    ),
    input_schema=PredictiveMaintenanceInput,
    output_schema=PredictiveMaintenanceOutput,
)
def build_predictive_maintenance_flow(aflow: Flow) -> Flow:
    """
    Build the predictive maintenance agentic workflow.

    Flow topology:
        START
          │
          ▼
        [1] get_sensor_data (MCP: Sensor MCP Server)
          │
          ▼
        [2] analyze_sensor_anomalies (Python tool)
          │
          ▼
        [3] get_maintenance_history (MCP: Maintenance History MCP Server)
          │
          ▼
        [4] generate_maintenance_recommendation (Python tool)
          │
          ▼
        [5] userflow_review (Human-in-the-loop: display recommendation, collect approval)
          │
          ▼
        [6] branch: operator_approved?
           ├─ True  ──► [7] get_spare_parts (MCP: Spare Parts MCP Server)
           │                  │
           │                  ▼
           │             [8] branch: needs_reorder?
           │                  ├─ True  ──► [9] order_spare_parts (MCP)
           │                  │                  │
           │                  │                  ▼
           │                  └─ False ──► [10] generate_maintenance_plan (Python tool)
           │                                     │
           │                                     ▼
           │                              [11] format_maintenance_report (Python tool)
           │                                     │
           └─ False ──► [12] userflow_rejected    ▼
                              │                  END
                              ▼
                             END
    """

    # ── Node 1: Get Sensor Data (MCP tool) ────────────────────────────────────
    get_sensor_data_node = aflow.tool(
        "get_sensor_data",
        name="get_sensor_data",
        display_name="Get IoT Sensor Data",
        description="Retrieve real-time IoT sensor metrics from the Sensor MCP server",
    )
    get_sensor_data_node.map_input(
        input_variable="device_name",
        expression="flow.input.device_name",
    )
    get_sensor_data_node.map_input(
        input_variable="device_type",
        expression="flow.input.device_type",
    )
    get_sensor_data_node.map_input(
        input_variable="timestamp",
        expression="flow.input.timestamp",
    )

    # ── Node 2: Analyze Sensor Anomalies (Python tool) ────────────────────────
    analyze_anomalies_node = aflow.tool(
        analyze_sensor_anomalies,
        name="analyze_sensor_anomalies",
        display_name="Analyze Sensor Anomalies",
        description="Detect anomalies and perform root cause analysis on sensor data",
    )
    analyze_anomalies_node.map_input(
        input_variable="device_name",
        expression="flow.input.device_name",
    )
    analyze_anomalies_node.map_input(
        input_variable="device_type",
        expression="flow.input.device_type",
    )
    analyze_anomalies_node.map_input(
        input_variable="sensor_data_json",
        expression="flow.get_sensor_data.output",
    )

    # ── Node 3: Get Maintenance History (MCP tool) ────────────────────────────
    get_history_node = aflow.tool(
        "get_maintenance_history",
        name="get_maintenance_history",
        display_name="Get Maintenance History",
        description="Retrieve historical maintenance records from the Maintenance History MCP server",
    )
    get_history_node.map_input(
        input_variable="device_name",
        expression="flow.input.device_name",
    )
    get_history_node.map_input(
        input_variable="device_type",
        expression="flow.input.device_type",
    )

    # ── Node 4: Generate Maintenance Recommendation (Python tool) ─────────────
    recommendation_node = aflow.tool(
        generate_maintenance_recommendation,
        name="generate_maintenance_recommendation",
        display_name="Generate Maintenance Recommendation",
        description="Generate prioritized maintenance recommendation from anomaly analysis and history",
    )
    recommendation_node.map_input(
        input_variable="device_name",
        expression="flow.input.device_name",
    )
    recommendation_node.map_input(
        input_variable="device_type",
        expression="flow.input.device_type",
    )
    recommendation_node.map_input(
        input_variable="anomaly_analysis_json",
        expression="flow.analyze_sensor_anomalies.output",
    )
    recommendation_node.map_input(
        input_variable="maintenance_history_json",
        expression="flow.get_maintenance_history.output",
    )

    # ── Node 5: Human-in-the-Loop — Review Recommendation ────────────────────
    # Display the recommendation summary and collect operator approval decision
    review_userflow = aflow.userflow()

    # Output field: display the recommendation summary to the operator
    display_map = DataMap()
    display_map.add(Assignment(
        target_variable="self.input.value",
        value_expression="flow.generate_maintenance_recommendation.output",
    ))
    display_rec_node = review_userflow.field(
        direction="output",
        name="display_recommendation",
        display_name="Maintenance Recommendation",
        kind=UserFieldKind.Text,
        text=(
            "📋 **Maintenance Recommendation for {flow.input.device_name}**\n\n"
            "Please review the recommendation above and approve or reject it."
        ),
        input_map=display_map,
    )

    # Input field: collect approval decision (Choice: Approve / Reject)
    approval_choices_map = DataMap()
    approval_choices_map.add(Assignment(
        target_variable="self.input.choices",
        value_expression='["Approve", "Reject"]',
    ))
    approval_node = review_userflow.field(
        direction="input",
        name="operator_decision",
        display_name="Operator Decision",
        kind=UserFieldKind.Choice,
        text="Do you approve this maintenance recommendation?",
        input_map=approval_choices_map,
    )

    # Input field: optional operator notes
    notes_node = review_userflow.field(
        direction="input",
        name="operator_notes",
        display_name="Operator Notes (Optional)",
        kind=UserFieldKind.Text,
        text="Add any notes or comments (optional):",
    )

    review_userflow.edge(START, display_rec_node)
    review_userflow.edge(display_rec_node, approval_node)
    review_userflow.edge(approval_node, notes_node)
    review_userflow.edge(notes_node, END)

    # ── Node 6: Branch — Operator Approved? ───────────────────────────────────
    approval_branch: Branch = aflow.branch(  # type: ignore[arg-type]
        evaluator="flow['userflow_1']['operator_decision'].output.value == 'Approve'"
    )

    # ── Node 7: Get Spare Parts (MCP tool) ────────────────────────────────────
    get_parts_node = aflow.tool(
        "get_spare_parts",
        name="get_spare_parts",
        display_name="Check Spare Parts Availability",
        description="Check spare parts stock levels via the Spare Parts MCP server",
    )
    get_parts_node.map_input(
        input_variable="part_id",
        expression="flow.generate_maintenance_recommendation.output",
    )

    # ── Node 8: Branch — Needs Reorder? ───────────────────────────────────────
    reorder_branch: Branch = aflow.branch(  # type: ignore[arg-type]
        evaluator="'needs_reorder\": true' in flow.get_spare_parts.output"
    )

    # ── Node 9: Order Spare Parts (MCP tool) ──────────────────────────────────
    order_parts_node = aflow.tool(
        "order_spare_parts",
        name="order_spare_parts",
        display_name="Order Spare Parts",
        description="Place spare parts order for low-stock items via the Spare Parts MCP server",
    )
    order_parts_node.map_input(
        input_variable="part_id",
        expression="flow.generate_maintenance_recommendation.output",
    )
    order_parts_node.map_input(
        input_variable="quantity_to_order",
        expression="10",
    )

    # ── Node 10: Generate Maintenance Plan (Python tool) ──────────────────────
    plan_node = aflow.tool(
        generate_maintenance_plan,
        name="generate_maintenance_plan",
        display_name="Generate Maintenance Plan",
        description="Generate detailed maintenance plan with ordered work items and scheduling",
    )
    plan_node.map_input(
        input_variable="device_name",
        expression="flow.input.device_name",
    )
    plan_node.map_input(
        input_variable="device_type",
        expression="flow.input.device_type",
    )
    plan_node.map_input(
        input_variable="recommendation_json",
        expression="flow.generate_maintenance_recommendation.output",
    )
    plan_node.map_input(
        input_variable="spare_parts_json",
        expression="flow.get_spare_parts.output",
    )

    # ── Node 11: Format Maintenance Report (Python tool) ──────────────────────
    report_node = aflow.tool(
        format_maintenance_report,
        name="format_maintenance_report",
        display_name="Format Maintenance Report",
        description="Format the complete maintenance plan as a structured Markdown report",
    )
    report_node.map_input(
        input_variable="device_name",
        expression="flow.input.device_name",
    )
    report_node.map_input(
        input_variable="device_type",
        expression="flow.input.device_type",
    )
    report_node.map_input(
        input_variable="sensor_data_json",
        expression="flow.get_sensor_data.output",
    )
    report_node.map_input(
        input_variable="anomaly_analysis_json",
        expression="flow.analyze_sensor_anomalies.output",
    )
    report_node.map_input(
        input_variable="recommendation_json",
        expression="flow.generate_maintenance_recommendation.output",
    )
    report_node.map_input(
        input_variable="maintenance_plan_json",
        expression="flow.generate_maintenance_plan.output",
    )

    # ── Node 12: Human-in-the-Loop — Rejection Notice ─────────────────────────
    rejected_userflow = aflow.userflow()
    rejected_display_map = DataMap()
    rejected_display_map.add(Assignment(
        target_variable="self.input.value",
        value_expression=(
            "\"⚠️ Maintenance recommendation for \" + flow.input.device_name + "
            "\" was rejected by the operator. No maintenance plan will be generated. "
            "Please review the recommendation and re-run the analysis if needed.\""
        ),
    ))
    rejected_node = rejected_userflow.field(
        direction="output",
        name="rejection_notice",
        display_name="Recommendation Rejected",
        kind=UserFieldKind.Text,
        text="The maintenance recommendation has been rejected.",
        input_map=rejected_display_map,
    )
    rejected_userflow.edge(START, rejected_node)
    rejected_userflow.edge(rejected_node, END)

    # ── Wire the Flow ──────────────────────────────────────────────────────────
    # Phase 1: Data collection and analysis (sequential)
    aflow.sequence(
        START,
        get_sensor_data_node,
        analyze_anomalies_node,
        get_history_node,
        recommendation_node,
        review_userflow,
        approval_branch,
    )

    # Phase 2a: Approved path — check parts, conditionally order, plan, report
    approval_branch.case(True, get_parts_node).case(False, rejected_userflow)

    aflow.edge(get_parts_node, reorder_branch)
    reorder_branch.case(True, order_parts_node).case(False, plan_node)

    # After ordering parts, proceed to plan
    aflow.edge(order_parts_node, plan_node)
    aflow.edge(plan_node, report_node)
    aflow.edge(report_node, END)

    # Phase 2b: Rejected path
    aflow.edge(rejected_userflow, END)

    # ── Output Mapping ─────────────────────────────────────────────────────────
    aflow.map_output(
        output_variable="maintenance_report",
        expression="flow.format_maintenance_report.output",
    )

    return aflow

# Made with Bob
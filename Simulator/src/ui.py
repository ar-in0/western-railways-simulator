# ui.py
# This file defines the SimulatorUI class
# to modularize simulator.py

from dash import Dash, html, dcc, Input, Output, State, callback_context
from dash import dash_table
import dash_bootstrap_components as dbc

def fmt_time(t):
    """Format time in minutes to HH:MM string"""
    if t is None:
        return "--:--"
    t = int(round(t))
    return f"{t//60:02d}:{t%60:02d}"

def visualization_layout(graph_ready):
    """Create visualization graph component"""
    return dcc.Graph(
        id="rake-3d-graph",
        style={
            "height": "75vh",
            "display": "block" if graph_ready else "none"
        }
    )

def service_details_layout():
    """Placeholder for service details"""
    return html.Div("...", style={"padding": "20px"})

def make_summary_card(title, items, footer=None):
    '''Reusable helper to build a clean, minimal summary card.'''
    return dbc.Card(
        [
            dbc.CardHeader(
                html.Strong(title, style={"fontSize": "14px", "color": "#1e293b"}),
                style={
                    "backgroundColor": "#f8fafc",
                    "borderBottom": "1px solid #e2e8f0",
                    "padding": "6px 10px"
                }
            ),
            dbc.CardBody(
                [
                    html.Ul(
                        [html.Li(i, style={"marginBottom": "4px"}) for i in items],
                        style={
                            "paddingLeft": "18px",
                            "margin": "0",
                            "fontSize": "13px",
                            "color": "#334155",
                            "listStyleType": "disc"
                        }
                    )
                ],
                style={"padding": "10px 12px"}
            ),
            dbc.CardFooter(
                footer if footer else "",
                style={
                    "backgroundColor": "#fafafa",
                    "borderTop": "1px solid #e2e8f0",
                    "fontSize": "12px",
                    "color": "#64748b",
                    "padding": "6px 10px"
                }
            ) if footer else None
        ],
        style={
            "borderRadius": "8px",
            "border": "1px solid #e2e8f0",
            "boxShadow": "0 1px 2px rgba(0,0,0,0.04)",
            "backgroundColor": "white",
            "height": "100%"
        }
    )

def build_service_row(svc, draw_connector):
    """Build a service row HTML component (moved from simulator.py)"""
    svc_id_str = ','.join(str(sid) for sid in svc.serviceId) if svc.serviceId else '?'

    row = html.Div(
        [
            html.Span(
                svc_id_str,
                style={"minWidth": "56px", "display": "inline-block"}
            ),
            html.Span(
                f"{svc.initStation.name} → {svc.finalStation.name} ({svc.direction})",
                style={"marginLeft": "6px"}
            ),
            html.Span(
                fmt_time(
                    next((e.atTime for e in svc.events if e.atTime is not None), None)
                ),
                style={"marginLeft": "6px", "color": "#64748b"}
            ),
        ],
        style={"fontSize": "12px"}
    )

    if not draw_connector:
        return row

    return html.Div([row, html.Div("│", style={"marginLeft": "6px"})])


# Factory methods for UI components
class UIComponents:
    @staticmethod
    def create_station_dropdown(component_id, placeholder="Select Station...", multi=False):
        """Factory for station dropdowns"""
        return dcc.Dropdown(
            id=component_id,
            options=[],
            placeholder=placeholder,
            multi=multi,
            className="mb-3"
        )

    @staticmethod
    def create_time_slider(component_id, value=[165, 1605]):
        """Factory for time range sliders"""
        return dcc.RangeSlider(
            id=component_id,
            min=0,
            max=1440,
            step=15,
            value=value,
            marks={
                i: f"{(i // 60):02d}:{(i % 60):02d}" for i in range(0, 1441, 120)
            },
            tooltip={"placement": "bottom", "always_visible": False},
            allowCross=False,
        )

    @staticmethod
    def create_ac_selector(component_id="ac-selector", value="all"):
        """Factory for AC selector radio items"""
        return dbc.RadioItems(
            id=component_id,
            options=[
                {"label": "All", "value": "all"},
                {"label": "AC", "value": "ac"},
                {"label": "Non-AC", "value": "nonac"},
            ],
            value=value,
            inline=True,
            inputStyle={"marginRight": "6px"},
            labelStyle={"marginRight": "12px", "fontSize": "13px"},
        )

class SimulatorUI:
    def __init__(self):
        pass

    def drawLayout(self):
            return html.Div(
                [
                    # Hidden store (optional)
                    dcc.Store(id="rl-table-store"),
                    dcc.Store(id="app-state"),

                    # === LEFT SIDEBAR ===
                    html.Div(
                        [
                            # Title + Subtitle
                            html.Div(
                                [
                                    dcc.Markdown(
                                        '''
                                        ### Western Railways – Timetable Visualizer
                                        '''.replace("  ", ""),
                                        className="title",
                                    ),
                                    dcc.Markdown(
                                        '''
                                        Interactive tool to analyze rake-links during migration to AC.
                                        '''.replace("  ", ""),
                                        className="subtitle",
                                    ),
                                ]
                            ),

                            html.Hr(),
                            html.Div([
                                dcc.Markdown("##### Upload Required Files", className="subtitle"),
                            ], style={"padding": "8px 0px"}),

                            # Upload components
                            dbc.Row([
                                # Upload Full WTT
                                dbc.Col([
                                    dcc.Upload(
                                        id="upload-wtt-inline",
                                        children=html.Div([
                                            html.Img(
                                                src="/assets/excel-icon.png",
                                                style={
                                                    "width": "28px",
                                                    "height": "28px",
                                                    "marginBottom": "6px"
                                                }
                                            ),
                                            html.Div("Full WTT",
                                                    style={"fontWeight": "500", "color": "#334155", "fontSize": "14px"}),
                                            html.Div("Click to upload",
                                                    style={"fontSize": "11px", "color": "#94a3b8", "marginTop": "4px"})
                                        ], className="text-center"),
                                        style={
                                            "height": "140px",
                                            "borderWidth": "2px",
                                            "borderStyle": "dashed",
                                            "borderRadius": "12px",
                                            "borderColor": "#cbd5e1",
                                            "display": "flex",
                                            "alignItems": "center",
                                            "justifyContent": "center",
                                            "cursor": "pointer",
                                            "transition": "all 0.2s ease",
                                        },
                                        multiple=False
                                    )
                                ], xs=12, md=6, className="mb-3 mb-md-0"),

                                # Upload Rake-Link Summary
                                dbc.Col([
                                    dcc.Upload(
                                        id="upload-summary-inline",
                                        children=html.Div([
                                            html.Img(
                                                src="/assets/excel-icon.png",
                                                style={
                                                    "width": "28px",
                                                    "height": "28px",
                                                    "marginBottom": "6px"
                                                }
                                            ),
                                            html.Div("Rake-Link Summary",
                                                    style={"fontWeight": "500", "color": "#334155", "fontSize": "14px"}),
                                            html.Div("Click to upload",
                                                    style={"fontSize": "11px", "color": "#94a3b8", "marginTop": "4px"})
                                        ], className="text-center"),
                                        style={
                                            "height": "140px",
                                            "borderWidth": "2px",
                                            "borderStyle": "dashed",
                                            "borderRadius": "12px",
                                            "borderColor": "#cbd5e1",
                                            "display": "flex",
                                            "alignItems": "center",
                                            "justifyContent": "center",
                                            "cursor": "pointer",
                                            "transition": "all 0.2s ease",
                                        },
                                        multiple=False
                                    )
                                ], xs=12, md=6)
                            ], style={"padding": "0px 35px", "marginBottom": "20px"}),

                            html.Hr(),

                            # Filters
                            html.Div([
                                html.Div([
                                    dcc.Markdown("##### View", className="subtitle"),
                                ], style={"padding": "0px 0px"}),

                                # --- SHARED AC FILTER ---
                                # Moved AC selector here, outside the tabs
                                dbc.RadioItems(
                                    id="ac-selector", # ID remains the same
                                    options=[
                                        {"label": "All", "value": "all"},
                                        {"label": "AC", "value": "ac"},
                                        {"label": "Non-AC", "value": "nonac"},
                                    ],
                                    value="all",
                                    inline=True,
                                    inputStyle={"marginRight": "6px"},
                                    labelStyle={"marginRight": "12px", "fontSize": "13px"},
                                    style={"marginTop": "8px", "marginBottom": "8px", "padding": "0px 35px"}
                                ),

                                # --- TABBED FILTERS ---
                                html.Div(id="filter-overlay", style={"display": "none"}),
                                dbc.Tabs(
                                    id="filter-tabs",
                                    active_tab="tab-rakelink", # Default to rake link
                                    children=[
                                        # --- TAB 1: RAKE LINK FILTERS (Original IDs) ---
                                        dbc.Tab(
                                            label="Rake Links",
                                            tab_id="tab-rakelink",
                                            children=dbc.Card(
                                                [
                                                    dbc.CardBody([
                                                        # Start & End Stations side by side
                                                        dbc.Row([
                                                            dbc.Col([
                                                                html.Label("Start Station", className="criteria-label"),
                                                                dcc.Dropdown(
                                                                    id="start-station", # Original ID
                                                                    options=[],
                                                                    placeholder="Select Station...",
                                                                    className="mb-3",
                                                                    persistence = True,
                                                                    persistence_type = 'session'
                                                                )
                                                            ], width=6),

                                                            dbc.Col([
                                                                html.Label("End Station", className="criteria-label"),
                                                                dcc.Dropdown(
                                                                    id="end-station", # Original ID
                                                                    options=[],
                                                                    placeholder="Select Station...",
                                                                    className="mb-3",
                                                                )
                                                            ], width=6),
                                                        ], className="gx-2"),

                                                        # Intermediate Stations full width below
                                                        html.Label("Passing Through", className="criteria-label"),
                                                        dcc.Dropdown(
                                                            id="intermediate-stations", # Original ID
                                                            options=[],
                                                            multi=True,
                                                            placeholder="Add intermediate stations",
                                                            className="mb-3",
                                                        ),
                                                        html.Label("In time period", className="criteria-label"),
                                                        dcc.RangeSlider(
                                                            id="time-range-slider", # Original ID
                                                            min=0,
                                                            max=1440,
                                                            step=15,
                                                            value=[165, 1605],
                                                            marks={
                                                                i: f"{(i // 60):02d}:{(i % 60):02d}" for i in range(0, 1441, 120)
                                                            },
                                                            tooltip={"placement": "bottom", "always_visible": False},
                                                            allowCross=False,
                                                        ),
                                                    ])
                                                ],
                                                className="criteria-card mb-4",
                                                style={"margin": "0px 0px"}
                                            )
                                        ),

                                        # --- TAB 2: SERVICE FILTERS (New IDs) ---
                                        dbc.Tab(
                                            label="Services",
                                            tab_id="tab-service",
                                            children=dbc.Card(
                                                [
                                                    dbc.CardBody([
                                                        # RE-ID'd components for Services
                                                        dbc.Row([
                                                            dbc.Col([
                                                                html.Label("Start Station", className="criteria-label"),
                                                                dcc.Dropdown(id="start-station_service", # New ID
                                                                            options=[],
                                                                            placeholder="Select Station..."),
                                                            ], width=6),
                                                            dbc.Col([
                                                                html.Label("End Station", className="criteria-label"),
                                                                dcc.Dropdown(id="end-station_service", # New ID
                                                                            options=[],
                                                                            placeholder="Select Station..."),
                                                            ], width=6),
                                                        ], className="gx-2"),
                                                        html.Div([
                                                            html.Label("Passing Through", className="criteria-label me-2"),

                                                            # --- Dropdown + Toggles in same line ---
                                                            html.Div([
                                                                dcc.Dropdown(
                                                                    id="intermediate-stations_service",
                                                                    options=[],
                                                                    multi=True,
                                                                    placeholder="Add intermediate stations",
                                                                    style={"flex": "1"},
                                                                ),

                                                                # Toggle buttons inline to the right of dropdown
                                                                html.Div([
                                                                    # html.Label("Direction", className="criteria-label me-2"),
                                                                    dbc.Checklist(
                                                                        options=[
                                                                            {"label": "UP", "value": "UP"},
                                                                            {"label": "DOWN", "value": "DOWN"},
                                                                        ],
                                                                        value=["UP", "DOWN"],  # default both selected
                                                                        id="direction-selector",
                                                                        inline=True,
                                                                        switch=True,
                                                                        className="ms-3 mb-0",  # spacing between dropdown and toggles
                                                                    )
                                                                ])
                                                            ], className="d-flex align-items-center gap-2 mb-3", style={"width": "100%"}),
                                                        ]),
                                                        html.Label("In time period", className="criteria-label"),
                                                        dcc.RangeSlider(
                                                            id="time-range-slider_service", # New ID
                                                            min=0,
                                                            max=1440,
                                                            step=15,
                                                            value=[165, 1605],
                                                            marks={
                                                                i: f"{(i // 60):02d}:{(i % 60):02d}" for i in range(0, 1441, 120)
                                                            },
                                                            tooltip={"placement": "bottom", "always_visible": False},
                                                            allowCross=False,
                                                        ),


                                                        # html.Label("Service Type", className="criteria-label", style={"marginTop": "16px"}),
                                                        # dbc.RadioItems(
                                                        #     id="service-type-radio",
                                                        #     options=[
                                                        #         {"label": "All", "value": "all"},
                                                        #         {"label": "Fast", "value": "fast"},
                                                        #         {"label": "Slow", "value": "slow"},
                                                        #     ],
                                                        #     value="all",
                                                        #     inline=True,
                                                        #     inputStyle={"marginRight": "6px"},
                                                        #     labelStyle={"marginRight": "12px", "fontSize": "13px"},
                                                        # )
                                                    ])
                                                ],
                                                className="criteria-card mb-4",
                                                style={"margin": "0px 0px"}
                                            )
                                        ),

                                        dbc.Tab(label="Stations",
                                                tab_id="tab-station",
                                                children=dbc.Card(
                                                    [dbc.CardBody([
                                                        html.Label("In time period", className="criteria-label"),
                                                        dcc.RangeSlider(
                                                            id="time-range-slider_station", # New ID
                                                            min=0,
                                                            max=1440,
                                                            step=15,
                                                            value=[165, 1605],
                                                            marks={
                                                                i: f"{(i // 60):02d}:{(i % 60):02d}" for i in range(0, 1441, 120)
                                                            },
                                                            tooltip={"placement": "bottom", "always_visible": False},
                                                            allowCross=False,
                                                        ),
                                                    ])]
                                                ))
                                    ],
                                    className="mb-4" # Add margin to separate from Generate button
                                )
                            ], style={"position": "relative"}),

                            # Generate button
                            html.Div(
                                [
                                    html.Button(
                                        "Generate",
                                        id="generate-button",
                                        n_clicks=0,
                                        className="generate-button",
                                        disabled=True,
                                    )
                                ],
                                style={"padding": "0px 35px"}  # Match other elements
                            ),
                        ],
                        className="four columns sidebar",
                    ),

                    # === RIGHT PANEL ===
                    dcc.Store(id="graph-ready", data=False),
                    html.Div(
                        [
                            html.Div(id="status-div", className="text-box"),

                            # === PILL TOGGLE + EXPORT BUTTON ROW ===
                            html.Div(
                                [
                                    dbc.ButtonGroup(
                                        [
                                            dbc.Button("Visualization", id="mode-viz", color="primary", outline=True, active=True),
                                            dbc.Button("Query Info", id="mode-details", color="primary", outline=True, active=False),
                                        ],
                                        size="sm",
                                        className="mode-pill-toggle",
                                        style={"marginLeft": "20px"}
                                    ),
                                            html.Div(
            dbc.Button(
                "Convert to AC",
                id="convert-ac-button",
                color="primary",
                outline=True,
                disabled=True,
            ),
            style={"marginLeft": "auto", "marginRight": "8px"}
        ),
        html.Div(
        dbc.Button(
            "Reset",
            id="reset-ac-button",
            color="warning",
            outline=True,
            size="sm",
        ),
        style={"marginLeft": "4px", "display": "None"}
        ),

                                    html.Div(
                                        dbc.Button(
                                            "Export Summary",
                                            id="export-button",
                                            color="secondary",
                                            outline=True,
                                            disabled=True,
                                        ),
                                        className="ms-auto",  # push to right
                                    ),
                                ],
                                className="d-flex align-items-center justify-content-between mb-2",
                            ),

                            dcc.Download(id="download-report"),

                            # ---- DYNAMIC CONTENT ----
                            html.Div(
                                id="viz-container",
                                children=[
                                    dcc.Graph(id="rake-3d-graph", style={"height": "65vh"}),
                                    html.Div(
                                        id="rake-link-table-container",
                                        children = [
                                            # html.Hr(style={"margin": "20px 0 10px 0"}),
                                            html.Div(
                                                id="rake-link-count",
                                                style={"marginBottom": "6px", "fontWeight": "500"}
                                            ),

                                            dash_table.DataTable(
                                                id="rake-link-table",
                                                columns=[
                                                    {"name": "Link", "id": "linkname"},
                                                    {"name": "Cars", "id": "cars"},
                                                    {"name": "AC?", "id": "is_ac"},
                                                    {"name": "Length (km)", "id": "length_km"},
                                                    {"name": "Start", "id": "start"},
                                                    {"name": "End", "id": "end"},
                                                    {"name": "#Svcs", "id": "n_services"},
                                                ],
                                                data=[],
                                                row_selectable="multi",
                                                selected_rows=[],
                                                page_size=45,
                                                sort_action="native",
                                                filter_action="native",
                                                style_table={"maxHeight": "260px", "overflowY": "auto"},
                                                style_cell={"padding": "6px", "fontSize": "13px"},
                                            )
                                        ],
                                        style={"padding": "10px 0px"}
                                    ),

# Add a new table that appears ONLY in service mode
html.Div(
    id="service-table-container",
    children=[
        html.Hr(),
        html.Div(
            id="service-count",
            style={"marginBottom": "6px", "fontWeight": "500"}
        ),
        dash_table.DataTable(
            id="service-table",
            columns=[
                {"name": "Service ID", "id": "service_id"},
                {"name": "Direction", "id": "direction"},
                {"name": "AC?", "id": "is_ac"},
                {"name": "Cars", "id": "cars"},
                {"name": "Start", "id": "start_station"},
                {"name": "End", "id": "end_station"},
                {"name": "Start Time", "id": "start_time"},
                {"name": "Rake Link", "id": "rake_link"},
            ],
            data=[],
            row_selectable="multi",
            selected_rows=[],
            page_size=45,
            sort_action="native",
            filter_action="native",
            style_table={"maxHeight": "260px", "overflowY": "auto"},
            style_cell={"padding": "6px", "fontSize": "13px"},
        )
    ],
    style={"padding": "10px 0px", "display": "none"}  # Hidden by default
)

                                    # html.Div(
                                    #     "Click 'Generate' to build visualization.",
                                    #     style={
                                    #         "position": "absolute",
                                    #         "top": "50%",
                                    #         "left": "50%",
                                    #         "transform": "translate(-50%, -50%)",
                                    #         "color": "#888",
                                    #         "fontSize": "18px",
                                    #         "display": "block"
                                    #     },
                                    # )
                                ],
                                style={"position": "relative", "height": "75vh"}
                            ),

                            html.Div(id="right-panel-content", style={"marginTop": "10px"}),
                        ],
                        className="eight columns",
                        id="page",
                    ),


                ],
                className="row flex-display",
                style={"height": "100vh"},
            )
